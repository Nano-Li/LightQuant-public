# -*- coding: utf-8 -*-
# @Time : 2023/11/8 15:07
# @Author : 
# @File : HighFreqTriggerGridFuturesBeta.py
# @Software: PyCharm
import time
import asyncio
import pandas as pd
from LightQuant.Recorder import LogRecorder
from LightQuant.tools.calc import calc, calc_sum
from LightQuant.tools.round_step_size import round_step_size
from LightQuant.Analyzer import Analyzer
from LightQuant.Executor import Executor
from LightQuant.protocols.BinanceToken import BinanceToken as Token


class HighFreqTriggerGridAnalyzerFuturesUltimate(Analyzer):
    """
    适用于所有合约的终极版高频网格!! 功能有：
    1.可选挂单触发 todo 触发缓冲网格，在触发前就有额外缓冲网格
    2.poc高频挂单，高频网格，成交，驳回均维护网格 todo:检查挂单是否在价格范围
    3.定时检查功能：一定次数后检查仓位，一定时间检查挂单
    4.仓位矫正功能：由于poc被驳回，仓位漂移，修改盘口挂单数量以矫正仓位 todo: 10s corotine
        仓位漂移来源：poc被驳回，未被完成的部分成交
    5.部分成交挂单处理：随着交易时间增加，网格会逐渐累积只有部分成交的挂单，todo 定期处理并纳入仓位矫正
    6.价格偏离预警：最新价格与策略价格偏离过多，策略运行故障预警
    """

    STG_NAME = '超高频网格'

    BUY: str = 'BUY'
    SELL: str = 'SELL'

    MID: str = 'MID'

    MARKET_ORDER_ID = 999999
    ENTRY_ORDER_ID = 999998

    param_dict: dict = {
        'symbol_name': None,
        'grid_side': None,
        'up_price': None,
        'down_price': None,
        # 三选一中选择哪个，分别用 int 1, 2, 3 表示
        'tri_selection': None,
        'price_abs_step': None,
        'price_rel_step': None,
        'grid_total_num': None,
        'each_grid_qty': None,
        'leverage': None,

        # 触发条件二选一，分别用 int 1, 2 表示，都不选则为0，然而这是非法的
        'trigger_selection': None,
        'pending_trigger_price': None,
        'price_trigger_price': None,
        # 进场方式三选一，分别用 int 1, 2, 3 表示
        'enter_method_selection': None,

        'need_advance': None,  # bool
        # 二选一中选择哪个，分别用 int 1, 2 表示，0表示都不选
        'dul_selection': None,
        'target_ratio': None,
        'target_price': None,
        'up_boundary_stop': None,  # bool
        'low_boundary_stop': None,  # bool

        'need_stop_loss': None,  # bool
        'max_profit': None,
        'min_profit': None,
    }

    def __init__(self) -> None:
        super().__init__()
        # ==================== 策略参数保存 ==================== #
        self.symbol_name = None
        self.grid_side = None
        self.grid_price_step = None
        self.grid_each_qty = None
        self.initial_quantity = None
        self.symbol_leverage = None
        # 触发挂单价格，挂单启动方法
        self.trigger_order_price = None
        # 触发价格，实时监控方法
        self.trigger_price = None

        # 输入相关，仅作为临时存储
        self._x_grid_side = None
        self._x_grid_up_price = None
        self._x_grid_down_price = None
        self._x_price_abs_step = None
        self._x_price_rel_step = None
        self._x_grid_total_num = None
        self._x_each_grid_qty = None
        self._x_leverage = None
        # 触发相关
        self._x_trigger_order_price = None
        self._x_trigger_price = None

        # 比例网格
        # self._c_need_advance: bool = False
        self._x_dul_selection = None
        self._x_target_ratio = None
        self._x_target_price = None
        self._x_up_boundary_stop: bool = False
        self._x_low_boundary_stop: bool = False
        # 止盈止损
        # self._c_need_stop_loss: bool = False
        self._x_max_profit = None
        self._x_min_profit = None

        # ==================== 合约交易规则变量 ==================== #
        self.symbol_price_min_step = None
        self.symbol_quantity_min_step = None
        self.symbol_max_leverage = None
        self.symbol_min_notional = None
        self.symbol_order_price_div = None  # 挂单价格偏离范围，不能超过此范围
        self.symbol_orders_limit_num = None  # 挂单数量限制
        # 手续费
        self.symbol_maker_fee = 0
        self.symbol_taker_fee = 0

        # ==================== 策略功能相关变量 ==================== #
        self._pre_update_text_task: asyncio.coroutine = None

        self.critical_index = 0
        self.all_grid_price: tuple = ()
        self.max_index = 0
        # 初始的critical index
        self.initial_index = 0
        # self.initial_symbol_price = 0           # 触发策略下该变量没有意义
        # 等效初始成交挂单数量，仅用于信息参考
        self.initial_order_num = 0
        # 触发开始时的策略价格
        self.entry_grid_price = 0
        # 当前最新价格，实时更新，要求最新
        self.current_symbol_price = 0
        # 设置买卖单最大挂单数量，及最小数量
        self.max_buy_order_num = 20
        self.max_sell_order_num = 20
        self.min_buy_order_num = 10
        self.min_sell_order_num = 10
        # 缓冲数量，单边网格数量过少或过多时增减的网格数量
        self.buffer_buy_num = 5
        self.buffer_sell_num = 5
        # batch order 每次下单数量
        self._batch_orders_num = 10
        # 策略布撒网格完成
        self._layout_complete = False
        # 定义了买卖单存储方式
        self.open_buy_orders = [{
            'id': '000032BUY',
            'status': 'NEW',
            'time': None
        }, ]
        self.open_sell_orders = [{
            'id': '000032SELL',
            'status': 'FILLED',
            'time': None
        }, ]
        # 上下边界是否终止策略
        self.up_boundary_stop = False
        self.low_boundary_stop = False
        # 策略止盈止损
        self.max_profit = 0
        self.min_profit = 0

        # ==================== 特殊功能相关变量 ==================== #
        # 累计待处理的maker市价单数量，大于0表示需要买入，否则卖出
        self._accumulated_market_quantity: int = 0
        # 使用一个开关，实现当收到服务器ticker信息时，立刻开启poc下单。功能总开关，打开时，会根据参数逐步实现功能
        self._maker_market_switch_on: bool = False
        # 是否存在最新价格附近的poc挂单
        self._exist_market_poc_order: bool = False
        # 当前收到的update信息是否是由订单修改造成的，false则代表poc订单部分成交
        self._posted_change_poc_order: bool = False

        # 前一个最新价格
        self.previous_price = 0
        # 目标市价单的方向和数量，由于是gate合约，数量为int，注意，这里始终使用正整数
        self._target_maker_side = self.BUY
        self._target_maker_quantity: int = 0
        # 已完成的市价单数量
        self._finished_maker_quantity: int = 0
        # 成交价值，用于计算成交均价
        self._finished_maker_value = 0

        # 策略存在失败的挂单请求
        self._exist_failed_order_request: bool = False
        # 策略需要马上修正挂单，该变量也充当类似开关功能
        self._need_fix_order: bool = False
        # 存在正在修正挂单的任务
        self._executing_order_fixing = False

        # ==================== 策略统计相关变量 ==================== #
        # 策略开始前，账户存量仓位，策略结束后，需要回归该数字
        self._init_account_position: int = 0
        # 理论累计计算的现货仓位
        self._account_position_theory: int = 0
        # 根据当前位置，导出的正确的应有的仓位，正负号代表多空
        self._current_valid_position: int = 0

        self._trading_statistics: dict = {
            'waiting_start_time': None,
            'strategy_start_time': None,
            'filled_buy_order_num': 0,
            'filled_sell_order_num': 0,
            # 已达成交易量
            'achieved_trade_volume': 0,
            # 已实现的总套利利润
            'matched_profit': 0,
            # 套利净利润，此处减去手续费
            'net_profit': 0,
            # 未实现盈亏
            'unmatched_profit': 0,
            # 交易手续费
            'total_trading_fees': 0,
            # 该策略最终净收益
            'final_profit': 0
        }

        # ==================== 其他变量 ==================== #
        # noinspection PyTypeChecker
        self._my_logger: LogRecorder = None

        # 存储所有 coroutine
        self._market_locker_task: asyncio.coroutine = None
        self._fix_position_task: asyncio.coroutine = None
        self._fix_order_task: asyncio.coroutine = None

        self.stg_num = None
        self.stg_num_len = None
        self._is_trading = False  # todo: 修改至基类
        # 另一种状态
        self._is_waiting = False

        # 点击停止次数
        self.manually_stop_request_time: int = 0
        # 用户已经强制终止
        self.force_stopped: bool = False

    def initialize(self, my_executor: Executor) -> None:
        # 绑定 executor
        super().initialize(my_executor)
        return

    # starting methods
    async def _get_trading_rule(self, symbol_name: str) -> bool:
        """
        获取交易规则
        :return: True, 表示查询到该合约并成功存储规则. False, 表示未查询到该合约
        """
        self.symbol_info = await self._running_loop.create_task(self._my_executor.get_symbol_info(symbol_name))
        if self.symbol_info is None:
            return False
        else:
            # 获得合约交易规则
            self.symbol_price_min_step = self.symbol_info['price_min_step']
            self.symbol_quantity_min_step = self.symbol_info['qty_min_step']
            self.symbol_max_leverage = self.symbol_info['max_leverage']
            self.symbol_order_price_div = self.symbol_info['order_price_deviate']
            self.symbol_orders_limit_num = self.symbol_info['orders_limit']
            return True

    async def validate_param(self, input_params: dict) -> dict:
        """
        根据 ui 界面输入的参数字典，合理化后返回正确的参数字典
        :param input_params:
        :return:
        """
        validated_params = input_params.copy()
        param_valid = True

        validated_params['symbol_name'] = input_params['symbol_name'].upper()
        if 'USDT' in validated_params['symbol_name']:
            if '_' not in validated_params['symbol_name']:
                validated_params['symbol_name'] = validated_params['symbol_name'].split('USDT')[0] + '_' + 'USDT'
        else:
            validated_params['symbol_name'] += '合约名称有误'
            validated_params['valid'] = False
            return validated_params

        # 输入相关，仅作为临时存储
        self._x_grid_side = validated_params['grid_side']
        self._x_grid_up_price = validated_params['up_price']
        self._x_grid_down_price = validated_params['down_price']
        tri_selection = validated_params['tri_selection']
        self._x_price_abs_step = validated_params['price_abs_step']
        self._x_price_rel_step = validated_params['price_rel_step']
        self._x_grid_total_num = validated_params['grid_total_num']
        self._x_each_grid_qty = validated_params['each_grid_qty']
        self._x_leverage = validated_params['leverage']

        self._x_trigger_order_price = validated_params['pending_trigger_price']
        self._x_trigger_price = validated_params['price_trigger_price']

        # self._c_need_advance = validated_params['need_advance']
        self._x_dul_selection = validated_params['dul_selection']
        self._x_target_ratio = validated_params['target_ratio']
        self._x_target_price = validated_params['target_price']
        self._x_up_boundary_stop = validated_params['up_boundary_stop']
        self._x_low_boundary_stop = validated_params['low_boundary_stop']

        # self._c_need_stop_loss = validated_params['need_stop_loss']
        self._x_max_profit = validated_params['max_profit']
        self._x_min_profit = validated_params['min_profit']
        # print('\n获得参数')
        # for key, value in validated_params.items():
        #     print(key, ': ', value)

        # 开始判断流程
        symbol_exist = await self._get_trading_rule(validated_params['symbol_name'])

        if symbol_exist:
            self.current_symbol_price = await self._my_executor.get_current_price(validated_params['symbol_name'])

            # 价格判断
            if self._x_grid_up_price <= self._x_grid_down_price:
                self._x_grid_up_price = str(self._x_grid_up_price) + '价格数值有误'
                self._x_grid_down_price = str(self._x_grid_down_price) + '价格数值有误'
                param_valid = False

            # 三选一数值修正
            if param_valid:
                # 此处规整价格的逻辑适用于短线网格
                if self._x_grid_side == self.BUY:
                    self._x_grid_up_price = round_step_size(self._x_grid_up_price, self.symbol_price_min_step)
                else:
                    self._x_grid_down_price = round_step_size(self._x_grid_down_price, self.symbol_price_min_step)

                if tri_selection == 1:
                    self._x_price_abs_step = round_step_size(self._x_price_abs_step, self.symbol_price_min_step)
                elif tri_selection == 2:
                    self._x_price_abs_step = calc(calc(self._x_price_rel_step, 100, '/'), self.current_symbol_price, '*')
                    self._x_price_abs_step = round_step_size(self._x_price_abs_step, self.symbol_price_min_step)
                elif tri_selection == 3:
                    self._x_price_abs_step = calc(calc(self._x_grid_up_price, self._x_grid_down_price, '-'), (self._x_grid_total_num - 1), '/')
                    self._x_price_abs_step = round_step_size(self._x_price_abs_step, self.symbol_price_min_step, upward=True)

                self._x_grid_total_num = int(int(calc(calc(self._x_grid_up_price, self._x_grid_down_price, '-'), self.symbol_price_min_step, '/')) /
                                             int(calc(self._x_price_abs_step, self.symbol_price_min_step, '/'))) + 1

                if self._x_grid_side == self.BUY:
                    self._x_grid_down_price = calc(self._x_grid_up_price, calc((self._x_grid_total_num - 1), self._x_price_abs_step, '*'), '-')
                else:
                    self._x_grid_up_price = calc(self._x_grid_down_price, calc((self._x_grid_total_num - 1), self._x_price_abs_step, '*'), '+')

                self._x_price_rel_step = calc(calc(self._x_price_abs_step, self.current_symbol_price, '/'), 100, '*')
                self._x_price_rel_step = round_step_size(self._x_price_rel_step, 0.000001)

                # 网格数量有要求
                if self._x_grid_total_num < 5:
                    self._x_grid_total_num = str(self._x_grid_total_num) + '网格数量过少'
                    param_valid = False

            # 每格数量和杠杆修正
            if param_valid:
                self._x_each_grid_qty = round_step_size(self._x_each_grid_qty, 1, upward=True)

                # 判断杠杆数是否合理
                if self._x_leverage > self.symbol_max_leverage:
                    self._x_leverage = str(self._x_leverage) + '杠杆数值超限'
                    param_valid = False

            # 触发条件修正
            if param_valid:
                # todo: 后续拓展更多功能
                self._x_trigger_order_price = round_step_size(self._x_trigger_order_price, self.symbol_price_min_step)

                if not (self._x_grid_down_price < self._x_trigger_order_price < self._x_grid_up_price):
                    self._x_trigger_order_price = str(self._x_trigger_order_price) + '触发价在区间外'
                    param_valid = False

                if param_valid:
                    if self.grid_side == self.BUY and self._x_trigger_order_price >= self.current_symbol_price:
                        self._x_trigger_order_price = str(self._x_trigger_order_price) + '触发价高于市价'
                        param_valid = False
                    elif self.grid_side == self.SELL and self._x_trigger_order_price <= self.current_symbol_price:
                        self._x_trigger_order_price = str(self._x_trigger_order_price) + '触发价低于市价'
                        param_valid = False

                if param_valid:
                    if abs(self._x_trigger_order_price - self.current_symbol_price) >= self.current_symbol_price * self.symbol_order_price_div:
                        self._x_trigger_order_price = str(self._x_trigger_order_price) + '触发价过于遥远'
                        param_valid = False

            # 高级区域修正
            if param_valid:
                if validated_params['need_advance']:
                    if self._x_dul_selection == 1:
                        self._x_target_ratio = abs(self._x_target_ratio)
                        if self._x_target_ratio > 1:
                            self._x_target_ratio = calc(self._x_target_ratio, 100, '/')
                        if self._x_grid_side == self.BUY:
                            delta_price = calc(self._x_grid_up_price, self.entry_grid_price, '-')
                            self._x_target_price = calc(calc(delta_price, self._x_target_ratio, '*'), self.entry_grid_price, '+')
                        else:
                            delta_price = calc(self.entry_grid_price, self._x_grid_down_price, '-')
                            self._x_target_price = calc(self.entry_grid_price, calc(delta_price, self._x_target_ratio, '*'), '-')
                        self._x_target_price = round_step_size(self._x_target_price, self.symbol_price_min_step)

                    elif self._x_dul_selection == 2:
                        self._x_target_price = round_step_size(self._x_target_price, self.symbol_price_min_step)
                        if self._x_grid_side == self.BUY:
                            if not (self.entry_grid_price < self._x_target_price < self._x_grid_down_price):
                                self._x_target_price = str(self._x_target_price) + '价格不合理'
                                param_valid = False
                            else:
                                delta_price = calc(self._x_grid_up_price, self.entry_grid_price, '-')
                                self._x_target_ratio = delta_price / calc(self._x_grid_up_price, self._x_grid_down_price, '-')
                                # self._x_target_ratio = round_step_size(self._x_target_ratio, 0.0001)
                        else:
                            if not (self._x_grid_down_price < self._x_target_price < self.entry_grid_price):
                                self._x_target_price = str(self._x_target_price) + '价格不合理'
                                param_valid = False
                            else:
                                delta_price = calc(self.entry_grid_price, self._x_grid_down_price, '-')
                                self._x_target_ratio = delta_price / calc(self._x_grid_up_price, self._x_grid_down_price, '-')
                                # self._x_target_ratio = round_step_size(self._x_target_ratio, 0.0001)

            # 止盈止损修正
            if param_valid:
                if validated_params['need_stop_loss']:
                    if self._x_min_profit != '':
                        if self._x_min_profit > 0:
                            self._x_min_profit = - self._x_min_profit
                    if self._x_max_profit != '':
                        if self._x_max_profit < 0:
                            self._x_max_profit = abs(self._x_max_profit)

        else:
            validated_params['symbol_name'] += '未查询到该合约'
            param_valid = False

        validated_params['up_price'] = self._x_grid_up_price
        validated_params['down_price'] = self._x_grid_down_price
        # validated_params['tri_selection'] =
        validated_params['price_abs_step'] = self._x_price_abs_step
        validated_params['price_rel_step'] = self._x_price_rel_step
        validated_params['grid_total_num'] = self._x_grid_total_num
        validated_params['each_grid_qty'] = self._x_each_grid_qty
        validated_params['leverage'] = self._x_leverage
        validated_params['pending_trigger_price'] = self._x_trigger_order_price
        validated_params['price_trigger_price'] = self._x_trigger_price
        # validated_params['dul_selection'] =
        validated_params['target_ratio'] = self._x_target_ratio
        validated_params['target_price'] = self._x_target_price
        validated_params['max_profit'] = self._x_max_profit
        validated_params['min_profit'] = self._x_min_profit
        validated_params['valid'] = param_valid

        return validated_params


