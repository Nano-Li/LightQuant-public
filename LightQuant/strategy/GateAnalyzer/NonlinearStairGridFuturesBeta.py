# -*- coding: utf-8 -*-
# @Time : 2023/11/8 19:28
# @Author : 
# @File : NonlinearStairGridFuturesBeta.py
# @Software: PyCharm
import time
import asyncio
import numpy as np
import pandas as pd
from decimal import Decimal
from LightQuant.Preserver import Preserver
from LightQuant.Recorder import LogRecorder
from LightQuant.tools.calc import calc, calc_sum
from LightQuant.tools.round_step_size import round_step_size
from LightQuant.Analyzer import Analyzer
from LightQuant.Executor import Executor
from LightQuant.protocols.BinanceToken import BinanceToken as Token


class NonlinearStairGridAnalyzerFuturesBeta(Analyzer):
    """
    适用于所有合约的终极版非线性网格初步开发测试版，功能有：
    1.可选挂单触发 todo 触发缓冲网格，在触发前就有额外缓冲网格
    2.poc高频挂单，高频网格，成交，驳回均维护网格 todo:检查挂单是否在价格范围，挂单限制价格和强制平仓价格：强平价格和账户保证金剩余有关
    3.定时检查功能：一定次数后检查仓位，一定时间检查挂单
    4.仓位矫正功能：由于poc被驳回，仓位漂移，修改盘口挂单数量以矫正仓位 done
        仓位漂移来源：poc被驳回，未被完成的部分成交
    5.部分成交挂单处理：随着交易时间增加，网格会逐渐累积只有部分成交的挂单，todo done
    6.价格偏离预警：最新价格与策略价格偏离过多，策略运行故障预警

    current doing: 高频仓位问题，额外缓冲挂单，适用于山寨翻倍的合理参考信息
    Beta 版高频仓位修复方法：判断当1.2s钟没有收到ticker信息时，盘口不剧烈，可以做额外操作，此时更新修复订单
    优点：策略 ticker stream不需要更改或添加数据结构，只需要延迟触发即可
    """

    STG_NAME = '高频智能调仓Beta'

    BUY: str = 'BUY'
    SELL: str = 'SELL'

    MARKET_ORDER_ID = 99999999  # 市价下单的id，taker成交
    ENTRY_ORDER_ID = 99999998  # 触发挂单id

    param_dict: dict = {        # todo: 考虑使用self实例化字典保存参数
        'symbol_name': None,
        'up_price': None,
        'each_grid_qty': None,
        'leverage': None,
        'trigger_start': None,  # 是否用挂单触发, True/False
        'pending_trigger_price': None,

        # 二选一中选择哪个，分别用 int 1, 2 表示
        'dul_selection': None,
        'grid_abs_step': None,
        'grid_rel_step': None,
        'filling_price_step': None,
        'lower_price_step': None,

        'max_grid_step': None,
        'lower_buffer_price': None,
        # 非线性增长系数，为 1/10 ~ 1 ~ 10 共21个取值
        'alpha': None
    }

    def __init__(self) -> None:
        super().__init__()
        # ==================== 策略参数保存 ==================== #
        self.symbol_name = None
        self.grid_price_step = None
        self.grid_each_qty = None
        self.filling_quantity = None  # 理论上填单网格数量*每格数量 即可得到该变量
        self.symbol_leverage = None
        self.grid_max_step = None
        self.lower_buffer_price_limit = None  # 下方界限，使用相对价格差
        self.alpha = None  # 非线性系数

        self.trigger_start: bool = False
        self.trigger_price = None

        # 输入相关，仅作为临时存储
        self._x_grid_up_limit = None
        self._x_each_grid_qty = None
        self._x_leverage = None
        self._x_trigger_start = False
        self._x_trigger_price = None
        self._x_price_abs_step = None
        self._x_price_rel_step = None
        self._x_filling_price_step = None
        self._x_lower_price_step = None
        self._x_max_grid_step = None
        self._x_lower_buffer_price_limit = None  # 下方最大价差，超出该价格不填单
        self._x_alpha = None

        # ==================== 合约交易规则变量 ==================== #
        self.symbol_price_min_step = None
        self.symbol_quantity_min_step = None
        self.symbol_max_leverage = None
        self.symbol_min_notional = None
        self.symbol_order_price_div = None
        self.symbol_orders_limit_num = None
        # 手续费
        self.symbol_maker_fee = 0
        self.symbol_taker_fee = 0

        # ==================== 策略功能相关变量 ==================== #
        # noinspection PyTypeChecker
        self._pre_update_text_task: asyncio.Task = None

        self.critical_index: int = 0
        # 所有网格的价格，由index索引，考虑到无限网格可能会很大，该元祖会随着网格抬升自动添加
        self.all_grid_price: tuple = ()
        # 非线性区域的所有网格价格，所有价格的非线性部分，会随着网格抬升自动增加数值
        self.nonlinear_grid_prices: tuple = ()
        # 需要补仓的价格index， 当 critical_index 属于其中时，执行补仓操作，补仓后，删除index以实现到达位置只补仓一次的功能
        self.indices_of_filling: list = []
        # 当前处在第几级台阶，即已经补了多少次仓位
        self.present_stair_num = 0
        # 当前需要补仓的index
        self.present_step_up_index = 0
        # 当前补仓price
        self.present_step_up_price = 0
        # 当前最低网格index
        self.present_bottom_index = 0
        self.bottom_virtual_price = 0  # 真实的底部价格由非线性网格底部给出，因此为virtual
        # 当前基准index
        self.present_base_index = 0
        # 当前下方index
        self.present_low_step_index = 0
        self.lower_step_price = 0

        # 上方是动态变量，以下是静态变量
        # 网格总数量，仅参考用，意义不大
        self.grid_total_num = 0
        self.max_index = 0
        # 从入场网格到最上方价格的所有网格数量，包括入场的 entry index，用处不大
        self.up_grid_num = 0
        # 所有非线性间隔的网格数量
        self.nonlinear_grid_num = 0
        # 台阶数量，对应后续可能的最多补仓数量
        self.stairs_total_num = 0
        # 上方用多少个台阶作为缓冲,需要大于等于1
        self.upper_buffer_steps_num = 5
        # 入场时对标网格的价格
        self.entry_grid_price = 0
        self.entry_index = 0
        # 自动补单的网格数量间隔
        self.filling_grid_step_num = 0
        # 补单价差
        self.filling_price_step = 0
        # 下方网格数量
        self.lower_grid_step_num = 0
        # 下方缓冲网格数量
        self.lower_buffer_grid_num = 0

        # 当前最新价格，实时更新，要求最新
        self.current_symbol_price = 0

        # 存储网格数量，防止重复迭代
        self.N_save = 0

        # 设置买卖单最大挂单数量，及最小数量
        self.max_buy_order_num = 45
        self.max_sell_order_num = 45
        self.min_buy_order_num = 25
        self.min_sell_order_num = 25
        # 缓冲数量，单边网格数量过少或过多时增减的网格数量
        self.buffer_buy_num = 10
        self.buffer_sell_num = 10
        # batch order 每次下单数量
        self._batch_orders_num = 10
        # 策略布撒网格完成
        self._layout_complete = False
        # 定义了买卖单存储方式
        self.open_buy_orders = [{
            'id': '00032BUY',
            'status': 'NEW',
            'time': None
        }, ]
        self.open_sell_orders = [{
            'id': '00032SELL',
            'status': 'FILLED',
            'time': None
        }, ]

        # ==================== 特殊功能相关变量 ==================== #
        # 部分成交订单处理  {'id': int}   order_id, left_quantity   注意买卖挂单数量均用绝对值储存
        self.partially_filled_orders: dict[str, int] = {}
        # 按大小顺序？存储部分成交订单index list, 用于判断距离并定时处理
        self.partially_orders_indices_list: list[int] = []

        # 策略需要马上修正挂单，该变量也充当类似开关功能
        self._need_fix_order: bool = False
        # noinspection PyTypeChecker
        self._fix_order_task: asyncio.Task = None
        # 存在正在修正挂单的任务
        # self._executing_order_fixing: bool = False
        # 设置一个锁，该锁为True时，策略正在调整挂单，此时不允许检查挂单
        self._cannot_check_open_orders: bool = False

        # 入场触发挂单剩余数量
        self._ENTRY_ORDER_qty_left: int = 0
        # 市价挂单目标量和剩余量，均为正数表示绝对数量，用于记忆市价挂单交易数量作为比对，该功能不完全必要
        self._MARKET_ORDER_qty_left: int = 0
        self._MARKET_ORDER_qty_target: int = 0
        self._MARKET_ORDER_value = 0          # 市价成交，已完成价值，用于最后求平均值

        # 前一个最新ticker价格
        self.previous_price = 0

        # ============ 核心策略功能 ============ # 修正仓位订单id，-1代表当前没有需要修正的挂单
        self.adjusting_index: int = -1
        # 由此衍生的变量
        self._adjusting_order_side: str = self.BUY
        self._adjusting_qty_left: int = 0
        self._adjusting_qty_target: int = 0

        # 处理修改订单数量失败时，需要使用的变量，存储修改特殊订单位置时，前一个特殊订单的id，归零时一起归零
        self._pre_adjusting_index: int = -1

        # 充当开关作用，表示需要特殊挂单以修正仓位
        self._need_adjust_pos: bool = False

        # 定时器，反复重置以达到核心功能
        # noinspection PyTypeChecker
        self._ticker_delay_timer: asyncio.TimerHandle = None
        # 等待时间 delay，如果超过该delay仍没有收到下一次ticker信息，则做出额外判断和操作
        self._ticker_delay_trigger_time: float = 1.2
        # 协程锁，防止重复开启协程任务
        self._doing_delay_task: bool = False

        # 程序会记录所有的仓位偏移，目前已知的仓位偏移来源：    1.poc订单驳回   2.永久偏离的部分成交
        # 累计待处理的仓位偏移，大于0表示立即买入该数量后，仓位回归正常，反之则表示需要立即卖出       # 该变量记录了驳回导致的仓位偏移
        self._accumulated_pos_deviation: int = 0
        # 当修改订单出现错误时，变量退回到这个偏移，用于防止修改特殊订单失败后丢失仓位偏移信息
        self._pre_save_acc_pos_dev: int = 0

        # # 策略存在失败的挂单请求
        # self._exist_failed_order_request: bool = False

        # ==================== 策略统计相关变量 ==================== #
        # 策略开始前，账户存量仓位，策略结束后，需要回归该数字
        self._init_account_position: int = 0
        # 理论累计计算的现货仓位
        self._account_position_theory: int = 0
        # 根据当前位置，导出的正确的应有的仓位
        self._current_valid_position: int = 0

        # 每个台阶做多利润
        self._each_stair_profit = 0

        self._trading_statistics: dict = {
            'waiting_start_time': None,
            'strategy_start_time': None,
            'filled_buy_order_num': 0,
            'filled_sell_order_num': 0,
            # 已达成交易量
            'achieved_trade_volume': 0,
            # 已实现的网格套利利润
            'matched_profit': 0,
            # 已实现做多利润
            'realized_profit': 0,
            # 未实现盈亏
            'unrealized_profit': 0,
            # 交易手续费
            'total_trading_fees': 0,
            # 该策略最终净收益
            'final_profit': 0
        }

        # ==================== 其他变量 ==================== #
        # noinspection PyTypeChecker
        self._my_logger: LogRecorder = None

        # 存储所有 coroutine
        # self._market_locker_task: asyncio.coroutine = None
        # self._fix_position_task: asyncio.coroutine = None

        self.stg_num = None
        self.stg_num_len = None

        self._is_trading = False  # todo: 修改至基类

        # 是否在等待挂单
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
            self.symbol_min_notional = 0
            self.symbol_order_price_div = self.symbol_info['order_price_deviate']
            self.symbol_orders_limit_num = self.symbol_info['orders_limit']
            return True

    async def validate_param(self, input_params: dict, acquire_params: bool = True) -> dict:
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

        self._x_grid_up_limit = validated_params['up_price']
        self._x_each_grid_qty = validated_params['each_grid_qty']
        self._x_leverage = validated_params['leverage']
        self._x_trigger_start = validated_params['trigger_start']
        self._x_trigger_price = validated_params['pending_trigger_price']
        dul_selection = validated_params['dul_selection']
        self._x_price_abs_step = validated_params['grid_abs_step']
        self._x_price_rel_step = validated_params['grid_rel_step']
        self._x_filling_price_step = validated_params['filling_price_step']
        self._x_lower_price_step = validated_params['lower_price_step']
        self._x_max_grid_step = validated_params['max_grid_step']
        self._x_lower_buffer_price_limit = validated_params['lower_buffer_price']
        self._x_alpha = validated_params['alpha']

        symbol_exist = await self._get_trading_rule(validated_params['symbol_name'])

        if symbol_exist:
            self.current_symbol_price = await self._my_executor.get_current_price(validated_params['symbol_name'])

            self._x_each_grid_qty = round_step_size(self._x_each_grid_qty, 1)

            # 判断杠杆数是否合理
            if self._x_leverage > self.symbol_max_leverage:
                self._x_leverage = str(self._x_leverage) + '杠杆数值超限'
                param_valid = False

            if param_valid and self._x_trigger_start:
                self._x_trigger_price = round_step_size(self._x_trigger_price, self.symbol_price_min_step)

                if self._x_trigger_price >= self.current_symbol_price:
                    self._x_trigger_price = str(self._x_trigger_price) + '触发价高于市场价'
                    param_valid = False

                if param_valid:
                    if abs(self._x_trigger_price - self.current_symbol_price) >= self.current_symbol_price * self.symbol_order_price_div:
                        self._x_trigger_price = str(self._x_trigger_price) + '触发价过低，不能挂单'
                        param_valid = False

            if param_valid:
                if self._x_trigger_start:
                    if self._x_grid_up_limit <= self._x_trigger_price:
                        self._x_grid_up_limit = str(self._x_grid_up_limit) + '上界低于触发价'
                        param_valid = False
                    else:
                        self._x_grid_up_limit = round_step_size(self._x_grid_up_limit, self.symbol_price_min_step)
                else:
                    if self._x_grid_up_limit <= self.current_symbol_price:
                        self._x_grid_up_limit = str(self._x_grid_up_limit) + '当前价高于上界'
                        param_valid = False
                    else:
                        self._x_grid_up_limit = round_step_size(self._x_grid_up_limit, self.symbol_price_min_step)

            # 套利部分
            if param_valid:
                if dul_selection == 2:
                    self._x_price_abs_step = calc(calc(self._x_price_rel_step, 100, '/'), self.current_symbol_price, '*')
                self._x_price_abs_step = round_step_size(self._x_price_abs_step, self.symbol_price_min_step)

                self._x_price_rel_step = calc(calc(self._x_price_abs_step, self.current_symbol_price, '/'), 100, '*')
                self._x_price_rel_step = round_step_size(self._x_price_rel_step, 0.00001)

                self._x_filling_price_step = round_step_size(self._x_filling_price_step, self._x_price_abs_step)
                self._x_lower_price_step = round_step_size(self._x_lower_price_step, self._x_price_abs_step)

                # self.filling_grid_step_num = int(self._x_filling_price_step / self._x_price_abs_step)
                # self.lower_grid_step_num = int(self._x_lower_price_step / self._x_price_abs_step)

                if int(self._x_filling_price_step / self._x_price_abs_step) < 5:
                    self._x_filling_price_step = str(self._x_filling_price_step) + '补仓价差过小'
                    param_valid = False

                if param_valid:
                    if self._x_trigger_start:
                        if self._x_filling_price_step >= (self._x_grid_up_limit - self._x_trigger_price):
                            self._x_filling_price_step = str(self._x_filling_price_step) + '补仓次数小于1'
                            param_valid = False
                    else:
                        if self._x_filling_price_step >= (self._x_grid_up_limit - self.current_symbol_price):
                            self._x_filling_price_step = str(self._x_filling_price_step) + '补仓次数小于1'
                            param_valid = False

                if int(self._x_lower_price_step / self._x_price_abs_step) < 20:
                    self._x_lower_price_step = str(self._x_lower_price_step) + '下方价差过小'
                    param_valid = False

            # 补充：规整上线价格
            if param_valid and self._x_trigger_start:
                # 价格上限按照触发价格和网格价差规整
                self._x_grid_up_limit = calc(self._x_trigger_price,
                                             round_step_size(calc(self._x_grid_up_limit, self._x_trigger_price, '-'), self._x_price_abs_step, upward=True), '+')

            # 缓冲部分
            if param_valid:
                self._x_max_grid_step = round_step_size(self._x_max_grid_step, self._x_price_abs_step)
                self._x_lower_buffer_price_limit = round_step_size(self._x_lower_buffer_price_limit, self._x_price_abs_step)

                if self._x_max_grid_step / self._x_price_abs_step < 1.5:
                    self._x_max_grid_step = str(self._x_max_grid_step) + '间距过小'
                    param_valid = False

                if self._x_lower_buffer_price_limit / self._x_price_abs_step < 5:
                    self._x_lower_buffer_price_limit = str(self._x_lower_buffer_price_limit) + '价差过小'
                    param_valid = False

            if param_valid:
                if self._x_trigger_start:
                    if self._x_lower_buffer_price_limit + self._x_lower_price_step >= self._x_trigger_price:
                        self._x_lower_buffer_price_limit = str(self._x_lower_buffer_price_limit) + '最低价小于0'
                        param_valid = False
                else:
                    if self._x_lower_buffer_price_limit + self._x_lower_price_step >= self.current_symbol_price:
                        self._x_lower_buffer_price_limit = str(self._x_lower_buffer_price_limit) + '最低价小于0'
                        param_valid = False

        else:
            validated_params['symbol_name'] += '未查询到该合约'
            param_valid = False

        validated_params['up_price'] = self._x_grid_up_limit
        validated_params['each_grid_qty'] = self._x_each_grid_qty
        validated_params['leverage'] = self._x_leverage
        validated_params['pending_trigger_price'] = self._x_trigger_price
        validated_params['grid_abs_step'] = self._x_price_abs_step
        validated_params['grid_rel_step'] = self._x_price_rel_step
        validated_params['filling_price_step'] = self._x_filling_price_step
        validated_params['lower_price_step'] = self._x_lower_price_step
        validated_params['max_grid_step'] = self._x_max_grid_step
        validated_params['lower_buffer_price'] = self._x_lower_buffer_price_limit
        validated_params['valid'] = param_valid

        return validated_params

    async def param_ref_info(self, valid_params_dict: dict) -> str:
        symbol_name = valid_params_dict['symbol_name']

        info_texts: str = """\n"""
        info_texts += '*** {} ***\n'.format('=' * 32)
        self.current_symbol_price = await self._my_executor.get_current_price(symbol_name)

        self.N_save = 0
        self.derive_functional_variables()

        if self.trigger_start:
            virtual_current_price = self.trigger_price
        else:
            virtual_current_price = self.current_symbol_price
        info_texts += '\n当前时间: {}\n'.format(str(pd.to_datetime(self.gen_timestamp(), unit='ms')))
        info_texts += '\n合约名称: {}\t\t\t当前价格: {}\n'.format(symbol_name, str(self.current_symbol_price))
        if self.trigger_start:
            info_texts += '\n\t\t\t\t触发价格: {}\n'.format(str(self.trigger_price))

        # 初次近场的价格及下方的所有价格
        stair_0_prices = list(self.all_grid_price[:self.entry_index + 1])

        add_price = calc(self.grid_price_step, (self.indices_of_filling[-1] - self.entry_index), '*')
        stair_last_prices = [calc(each_price, add_price, '+') for each_price in stair_0_prices]

        min_filling_margin_cost = calc(calc(calc(self.filling_quantity, self.symbol_quantity_min_step, '*'), virtual_current_price, '*'), self.symbol_leverage, '/')
        max_filling_margin_cost = calc(calc(calc(self.filling_quantity, self.symbol_quantity_min_step, '*'), stair_last_prices[-1], '*'), self.symbol_leverage, '/')

        max_holding_quantity = calc(calc(self.filling_quantity,
                                         calc(self.grid_each_qty, self.lower_buffer_grid_num + self.lower_grid_step_num, '*'), '+'), self.symbol_quantity_min_step, '*')

        min_max_margin_cost = calc(calc(max_holding_quantity, stair_0_prices[0], '*'), self.symbol_leverage, '/')
        max_max_margin_cost = calc(calc(max_holding_quantity, stair_last_prices[0], '*'), self.symbol_leverage, '/')

        # 给出参考亏损，即台阶底部亏损
        max_loss_ref = self.unmatched_profit_calc(
            initial_index=self.entry_index + 1,
            current_index=0,
            all_prices=self.all_grid_price,
            each_grid_qty=calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'),
            init_pos_price=self.all_grid_price[self.entry_index + 1],
            init_pos_qty=calc(self.filling_quantity, self.symbol_quantity_min_step, '*'),
            current_price=self.all_grid_price[0]
        )
        # 给出5%, 10%, 20%, 30% 下跌时的亏损
        percentage_indices = [0, 0, 0, 0]
        percentage_prices = [round_step_size(calc(virtual_current_price, 0.95, '*'), self.symbol_price_min_step),
                             round_step_size(calc(virtual_current_price, 0.9, '*'), self.symbol_price_min_step),
                             round_step_size(calc(virtual_current_price, 0.8, '*'), self.symbol_price_min_step),
                             round_step_size(calc(virtual_current_price, 0.7, '*'), self.symbol_price_min_step)]
        for _index, _ in enumerate(self.all_grid_price[:-1]):
            if self.all_grid_price[_index] < percentage_prices[0] <= self.all_grid_price[_index + 1]:
                percentage_indices[0] = _index + 1
            if self.all_grid_price[_index] < percentage_prices[1] <= self.all_grid_price[_index + 1]:
                percentage_indices[1] = _index + 1
            if self.all_grid_price[_index] < percentage_prices[2] <= self.all_grid_price[_index + 1]:
                percentage_indices[2] = _index + 1
            if self.all_grid_price[_index] < percentage_prices[3] <= self.all_grid_price[_index + 1]:
                percentage_indices[3] = _index + 1

        percent_5_loss_ref = self.unmatched_profit_calc(
            initial_index=self.entry_index + 1,
            current_index=percentage_indices[0],
            all_prices=self.all_grid_price,
            each_grid_qty=calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'),
            init_pos_price=self.all_grid_price[self.entry_index + 1],
            init_pos_qty=calc(self.filling_quantity, self.symbol_quantity_min_step, '*'),
            current_price=percentage_prices[0]
        )
        percent_10_loss_ref = self.unmatched_profit_calc(
            initial_index=self.entry_index + 1,
            current_index=percentage_indices[1],
            all_prices=self.all_grid_price,
            each_grid_qty=calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'),
            init_pos_price=self.all_grid_price[self.entry_index + 1],
            init_pos_qty=calc(self.filling_quantity, self.symbol_quantity_min_step, '*'),
            current_price=percentage_prices[1]
        )
        percent_20_loss_ref = self.unmatched_profit_calc(
            initial_index=self.entry_index + 1,
            current_index=percentage_indices[2],
            all_prices=self.all_grid_price,
            each_grid_qty=calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'),
            init_pos_price=self.all_grid_price[self.entry_index + 1],
            init_pos_qty=calc(self.filling_quantity, self.symbol_quantity_min_step, '*'),
            current_price=percentage_prices[2]
        )
        percent_30_loss_ref = self.unmatched_profit_calc(
            initial_index=self.entry_index + 1,
            current_index=percentage_indices[3],
            all_prices=self.all_grid_price,
            each_grid_qty=calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'),
            init_pos_price=self.all_grid_price[self.entry_index + 1],
            init_pos_qty=calc(self.filling_quantity, self.symbol_quantity_min_step, '*'),
            current_price=percentage_prices[3]
        )

        # 计算账户需要的最大资金
        min_account_fund_demand = calc(min_max_margin_cost, abs(max_loss_ref), '+')
        max_account_fund_demand = calc(max_max_margin_cost, abs(max_loss_ref), '+')

        suggested_account_fund_low = min_account_fund_demand
        suggested_account_fund_high = 1.5 * max_account_fund_demand

        # 网格间距翻倍时合约价格
        double_step_price = 0
        tmp_prices = list(reversed(self.all_grid_price))[:-1]  # 按顺序递减的价格
        for each_index, _ in enumerate(tmp_prices):
            if each_index >= 1:
                if (tmp_prices[each_index - 1] - tmp_prices[each_index]) >= 2 * self.grid_price_step:
                    double_step_price = tmp_prices[each_index - 1]
                    break

        info_texts += '\n网格间距翻倍时合约价格:\t\t\t{}\n'.format(str(double_step_price))

        info_texts += '\n网格总数量\t\t{:<8}\n'.format(str(self.grid_total_num))
        info_texts += '调仓间隔网格数量\t\t{:<8}\n'.format(str(self.filling_grid_step_num))
        info_texts += '下方缓冲网格数量\t\t{:<8} + {:<8}\n'.format(str(self.lower_grid_step_num), str(self.lower_buffer_grid_num))
        info_texts += '最多补仓次数\t\t{:<8}\t\t次\n'.format(str(self.stairs_total_num))

        info_texts += '\n网格价差占比\t\t{:<8}\t\t{:<8}\n'.format(str(round(self.grid_price_step / virtual_current_price * 100, 6)), '%')
        info_texts += '每格套利利润\t\t{:<8}\t\t{:<8}\n'.format(str(calc(calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'), self.grid_price_step, '*')),
                                                                symbol_name[-4:])
        info_texts += '每阶做多收益\t\t{:<8}\t\t{:<8}\n'.format(str(self._each_stair_profit), symbol_name[-4:])
        info_texts += '全程做多收益\t\t{:<8}\t\t{:<8}\n'.format(str(calc(self._each_stair_profit, self.stairs_total_num, '*')), symbol_name[-4:])

        info_texts += '\n补仓买入数量\t\t{:<8}\t\t{:<8}\n'.format(str(calc(self.filling_quantity, self.symbol_quantity_min_step, '*')), symbol_name[:-4].replace('_', ''))
        info_texts += '补仓占用保证金\t\t{:<8}\t\t{:<8}\t最小\n'.format(str(round(min_filling_margin_cost, 2)), symbol_name[-4:])
        info_texts += '          \t\t\t{:<8}\t\t{:<8}\t最大\n'.format(str(round(max_filling_margin_cost, 2)), symbol_name[-4:])

        info_texts += '\n最大持有仓位\t\t{:<8}\t\t{:<8}\n'.format(str(max_holding_quantity), symbol_name[:-4].replace('_', ''))
        info_texts += '最大持仓保证金\t\t{:<8}\t\t{:<8}\t最小\n'.format(str(round(min_max_margin_cost, 2)), symbol_name[-4:])
        info_texts += '          \t\t\t{:<8}\t\t{:<8}\t最大\n'.format(str(round(max_max_margin_cost, 2)), symbol_name[-4:])

        info_texts += '\n策略资金需求\t\t{:<8}\t\t{:<8}\t最小\n'.format(str(round(min_account_fund_demand, 2)), symbol_name[-4:])
        info_texts += '          \t\t\t{:<8}\t\t{:<8}\t最大\n'.format(str(round(max_account_fund_demand, 2)), symbol_name[-4:])

        info_texts += '\n参考策略亏损\t\t{:<8}\t\t{:<8}\n'.format(str(round(max_loss_ref, 2)), symbol_name[-4:])

        info_texts += '\n下跌 5% 亏损\t\t{:<8}\t\t{:<8}'.format(str(round(percent_5_loss_ref, 2)), symbol_name[-4:])
        info_texts += '\n下跌 10% 亏损\t\t{:<8}\t\t{:<8}'.format(str(round(percent_10_loss_ref, 2)), symbol_name[-4:])
        info_texts += '\n下跌 20% 亏损\t\t{:<8}\t\t{:<8}'.format(str(round(percent_20_loss_ref, 2)), symbol_name[-4:])
        info_texts += '\n下跌 30% 亏损\t\t{:<8}\t\t{:<8}'.format(str(round(percent_30_loss_ref, 2)), symbol_name[-4:])

        info_texts += '\n\n建议账户资金\t\t{:<16}~ {:<16}\t$\n'.format(str(round(suggested_account_fund_low, 2)), str(round(suggested_account_fund_high, 2)))
        info_texts += '\n*** {} ***'.format('=' * 32)

        return info_texts

    def confirm_params(self, input_params: dict) -> None:
        self.symbol_name = input_params['symbol_name']
        # self.symbol_leverage = input_params['leverage']

        self._my_executor.start_single_contract_order_subscription(self.symbol_name)
        self._my_executor.start_single_contract_ticker_subscription(self.symbol_name)

    def return_params(self) -> dict:
        """
        返回策略参数，此时策略参数是正确的，恢复策略用
        :return:
        """
        stg_params = self.param_dict.copy()

        stg_params['symbol_name'] = self.symbol_name
        stg_params['up_price'] = self._x_grid_up_limit
        stg_params['each_grid_qty'] = self._x_each_grid_qty
        stg_params['leverage'] = self._x_leverage
        stg_params['pending_trigger_price'] = self._x_trigger_price
        stg_params['grid_abs_step'] = self._x_price_abs_step
        stg_params['grid_rel_step'] = self._x_price_rel_step
        stg_params['filling_price_step'] = self._x_filling_price_step
        stg_params['lower_price_step'] = self._x_lower_price_step
        stg_params['max_grid_step'] = self._x_max_grid_step
        stg_params['lower_buffer_price'] = self._x_lower_buffer_price_limit
        stg_params['valid'] = True

        return stg_params

    def derive_functional_variables(self, assign_entry_price: float = 0) -> None:
        self.grid_price_step = self._x_price_abs_step
        self.grid_each_qty = self._x_each_grid_qty

        self.symbol_leverage = self._x_leverage
        self.grid_max_step = self._x_max_grid_step
        self.lower_buffer_price_limit = self._x_lower_buffer_price_limit
        self.alpha = self._x_alpha

        self.trigger_start = self._x_trigger_start
        self.trigger_price = self._x_trigger_price

        self.filling_price_step = self._x_filling_price_step

        self.filling_grid_step_num = int(self._x_filling_price_step / self.grid_price_step)
        self.lower_grid_step_num = int(self._x_lower_price_step / self.grid_price_step)
        self.filling_quantity = calc(self.filling_grid_step_num, self.grid_each_qty, '*')

        # 根据当前价格，给出 entry price，最新价格在参考信息和 策略开始运行两处都会使用，如果挂单触发，则为触发价格
        if self.trigger_start:
            self.entry_grid_price = self.trigger_price
        elif assign_entry_price != 0:
            self.entry_grid_price = assign_entry_price
        else:
            # 高低两个价格是根据上限价格，向下按照网格价差规整得到的
            high_price = calc(self._x_grid_up_limit, round_step_size(calc(self._x_grid_up_limit, self.current_symbol_price, '-'), self.grid_price_step), '-')
            low_price = calc(high_price, self.grid_price_step, '-')
            if high_price - self.current_symbol_price <= self.grid_price_step / 2:
                self.entry_grid_price = high_price
            else:
                self.entry_grid_price = low_price

        # print(self.entry_grid_price)
        self.lower_step_price = calc(self.entry_grid_price, self._x_lower_price_step, '-')
        self.up_grid_num = int(calc(calc(self._x_grid_up_limit, self.entry_grid_price, '-'), self.grid_price_step, '/')) + 1
        # 计算合理的缓冲台阶数量，上方100个网格数量的缓冲
        self.upper_buffer_steps_num = max(int(calc(100, self.filling_grid_step_num, '/')), 5)
        # print('缓冲台阶数量 {}'.format(self.upper_buffer_steps_num))
        # 线性区域网格价格，包括缓冲台阶
        linear_grid_prices = tuple([calc(self.lower_step_price, calc(i, self.grid_price_step, '*'), '+')
                                    for i in range(1 + self.lower_grid_step_num + self.upper_buffer_steps_num * self.filling_grid_step_num)])

        # 现在计算所有非线性网格价格
        self.nonlinear_grid_prices = self.nonlinear_grid_price_calc(
            min_grid_step=self.grid_price_step,
            max_grid_step=self.grid_max_step,
            top_start_price=self.lower_step_price,
            lower_price_limit=self.lower_buffer_price_limit,
            alpha=self.alpha
        )
        self.all_grid_price = self.nonlinear_grid_prices + linear_grid_prices
        self.lower_buffer_grid_num = len(self.nonlinear_grid_prices)
        self.grid_total_num = self.up_grid_num + self.lower_grid_step_num + self.lower_buffer_grid_num

        self.max_index = self.grid_total_num - 1

        self.present_bottom_index = 0
        self.present_low_step_index = self.lower_buffer_grid_num
        self.present_base_index = self.present_low_step_index + self.lower_grid_step_num
        self.present_step_up_index = self.present_base_index + self.filling_grid_step_num
        self.present_step_up_price = self.all_grid_price[self.present_step_up_index]

        self.entry_index = self.present_base_index
        self.critical_index = self.entry_index

        # print(self.max_index, self.entry_index, self.filling_grid_step_num)
        # print(self.all_grid_price[self.entry_index])

        add_index = self.entry_index
        self.indices_of_filling.clear()
        while True:
            add_index += self.filling_grid_step_num
            if add_index < self.max_index:
                self.indices_of_filling.append(add_index)
            else:
                break
        self.stairs_total_num = len(self.indices_of_filling)
        if self.stairs_total_num == 0:
            print('台阶数为0，请检查参数')
            print(self.return_params())
            raise IndexError('台阶数量为0，参数错误!!')

        # print(self.nonlinear_grid_prices)
        # print(linear_grid_prices)
        # print(self.indices_of_filling)

        self._each_stair_profit = self.unmatched_profit_calc(
            initial_index=self.entry_index,
            current_index=self.indices_of_filling[0],
            all_prices=self.all_grid_price,
            each_grid_qty=calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'),
            init_pos_price=self.all_grid_price[self.entry_index],
            init_pos_qty=calc(self.filling_quantity, self.symbol_quantity_min_step, '*'),
            current_price=self.all_grid_price[self.indices_of_filling[0]]
        )
        # print(self._each_stair_profit)
        # print(self.entry_index)
        # print(self.indices_of_filling)

    def derive_valid_position(self) -> None:

        if self.present_stair_num < self.stairs_total_num:
            if self.critical_index == self.indices_of_filling[0]:
                self._current_valid_position = self.filling_quantity
            else:
                self._current_valid_position = calc((self.indices_of_filling[0] - self.critical_index), self.grid_each_qty, '*')
        else:
            # self._current_valid_position = calc((self.max_index - self.critical_index), self.grid_each_qty, '*')
            self._current_valid_position = int(self.filling_quantity) + \
                                           int(calc(self.present_base_index - self.critical_index, self.grid_each_qty, '*'))

        if self._current_valid_position < 0:
            raise ValueError('仓位小于0，不合逻辑!!!')

    def acquire_token(self, stg_code: str) -> None:
        # todo: 考虑添加至基类
        self.stg_num = stg_code
        self.stg_num_len = len(stg_code)

    def stop(self) -> None:
        if self._is_waiting:
            # 策略未触发，直接手动停止，撤销一个挂单即可
            self._log_info('~~~ 停止触发等待\n')
            self._pre_update_text_task.cancel()

            maker_order = Token.ORDER_INFO.copy()
            maker_order['symbol'] = self.symbol_name
            maker_order['id'] = self.gen_id(self.ENTRY_ORDER_ID, self.BUY)
            asyncio.create_task(self.command_transmitter(trans_command=maker_order, token=Token.TO_CANCEL))

            self._my_logger.close_file()
            self._my_preserver.stop_preserving()

            self._my_executor.stop_single_contract_order_subscription(self.symbol_name)
            self._my_executor.stop_single_contract_ticker_subscription(self.symbol_name)
            self._my_executor.strategy_stopped(self.stg_num)

            # todo: 此处或许应该在基类中定义
            self._bound_running_column = None
        else:
            asyncio.create_task(self._terminate_trading(reason='人工手动结束'))

    def start(self) -> None:
        """
        start 函数连接按钮，由于不确定是挂单还是直接入场，因此改写父类方法

        操作：
            1. 如果触发挂单，则提交触发挂单并等待触发

            2. 如果直接开启，则市价下单并开启策略

        :return:
        """
        self._my_logger = LogRecorder()
        self._my_logger.open_file(self.symbol_name)
        self._my_preserver = Preserver()
        self._my_preserver.acquire_user_id(self._my_executor.return_user_id())
        self._my_preserver.open_file(self.symbol_name)      # todo: 改写并测试继承方法，使代码更美观

        asyncio.create_task(self._my_executor.change_symbol_leverage(self.symbol_name, self.symbol_leverage))

        if self.trigger_start:
            self._pre_update_text_task = asyncio.create_task(self._pre_update_detail_info(interval_time=1))

            self.derive_functional_variables()

            maker_order = Token.ORDER_INFO.copy()
            maker_order['symbol'] = self.symbol_name
            maker_order['id'] = self.gen_id(self.ENTRY_ORDER_ID, self.BUY)
            maker_order['price'] = self.entry_grid_price
            maker_order['side'] = self.BUY
            maker_order['quantity'] = self.filling_quantity
            self._log_info('~~~ 触发挂单下单\n')
            asyncio.create_task(self.command_transmitter(trans_command=maker_order, token=Token.TO_POST_POC))

            self._ENTRY_ORDER_qty_left = self.filling_quantity
            self._trading_statistics['waiting_start_time'] = self.gen_timestamp()
            self._log_info('开始监听数据，等待触发条件')
            self._is_waiting = True

        else:
            asyncio.create_task(self._start_strategy())

    async def _start_strategy(self):
        self._is_waiting = False
        self._is_trading = True
        self._log_info('高频智能调仓Beta 网格策略开始')

        self._reasonable_order_num_estimate()

        if self.trigger_start:
            self._pre_update_text_task.cancel()
        else:
            fee_dict = await self._my_executor.get_symbol_trade_fee(self.symbol_name)
            self.symbol_maker_fee = fee_dict['maker_fee']
            self.symbol_taker_fee = fee_dict['taker_fee']
            self._log_info('maker fee rate: {}'.format(self.symbol_maker_fee))
            self._log_info('taker fee rate: {}'.format(self.symbol_taker_fee))

        self._update_text_task = asyncio.create_task(self._update_detail_info(interval_time=3))

        self._init_account_position = 0

        self._trading_statistics['strategy_start_time'] = self.gen_timestamp()
        if self.trigger_start:
            self.current_symbol_price = self.trigger_price
        else:
            self.current_symbol_price = await self._my_executor.get_current_price(self.symbol_name)
            # 如果直接入场，在此得到策略参数
            self.derive_functional_variables()
        self._log_info('策略开始合约价格: {}'.format(self.current_symbol_price))
        if not (self.current_symbol_price < self._x_grid_up_limit):
            self._log_info('价格在范围外，需要手动终止策略')
            return

        # 1. 设置初始市价买入数量
        if not self.trigger_start:

            await self._post_market_order(self.BUY, self.filling_quantity)

        # 2. 开始撒网
        asyncio.create_task(self._layout_net())

        # 3. 开启维护挂单任务
        self._fix_order_task = asyncio.create_task(self._order_fixer(interval_time=1200))

    # strategy basic methods
    def _grid_stair_step_up(self) -> None:
        """
        策略上升一个台阶，更新相关变量
        操作：
            prices_tuple 上方添加，存储变量
            更新 tuple 下方价格：将所有非线性价格增加一个数并上移拼接，下方多余部分用0补足，以保持index不变
            更新相关变量，index等

        :return:
        """
        end_price = self.all_grid_price[-1]
        # 实际上，由于max_index的存在，就算添加的网格价格超出了界限，也没关系
        range_end_index = len(self.all_grid_price) + self.filling_grid_step_num - 1
        if range_end_index <= self.max_index:
            max_range = self.filling_grid_step_num + 1
        else:
            max_range = self.grid_total_num - len(self.all_grid_price) + 1

        add_grid_price = tuple(calc(end_price, calc(self.grid_price_step, i, '*'), '+') for i in range(1, max_range))
        self.nonlinear_grid_prices = tuple([calc(each_price, self.filling_price_step, '+') for each_price in self.nonlinear_grid_prices])

        self.all_grid_price = (0,) * (self.present_stair_num + 1) * self.filling_grid_step_num + \
                              self.nonlinear_grid_prices + self.all_grid_price[self.present_low_step_index + self.filling_grid_step_num:] + add_grid_price

        self.present_stair_num += 1
        self.present_step_up_index += self.filling_grid_step_num
        self.present_base_index += self.filling_grid_step_num
        self.present_low_step_index += self.filling_grid_step_num
        self.present_bottom_index += self.filling_grid_step_num

        self.present_step_up_price = calc(self.present_step_up_price, self.filling_price_step, '+')  # 因为有可能超出上边界，此时该价格没有记录
        self.lower_step_price = self.all_grid_price[self.present_low_step_index]

    async def _layout_net(self):
        """
        布撒初始网格， 使用batch order操作
        :return:
        """
        ini_buy_order_num = round((self.min_buy_order_num + self.max_buy_order_num) / 2)
        ini_sell_order_num = round((self.min_sell_order_num + self.max_sell_order_num) / 2)
        self.open_buy_orders = [
            {
                'id': self.gen_id(_index, self.BUY),
                'status': 'NEW',
                'time': self.gen_timestamp()
            } for _index in range(max(self.present_bottom_index, self.critical_index - ini_buy_order_num), self.critical_index)
        ]
        self.open_sell_orders = [
            {
                'id': self.gen_id(_index, self.SELL),
                'status': 'NEW',
                'time': self.gen_timestamp()
            } for _index in range(self.critical_index + 1, min(self.max_index, (self.critical_index + ini_sell_order_num + 1)))
        ]
        self._log_info('\n开始撒网\n')
        temp_buy_indices = [_each for _each in self.open_buy_orders]
        temp_sell_indices = [_each for _each in self.open_sell_orders]
        while True:
            temp_buy_indices, temp_post_buy = temp_buy_indices[:-self._batch_orders_num], temp_buy_indices[-self._batch_orders_num:]
            temp_sell_indices, temp_post_sell = temp_sell_indices[self._batch_orders_num:], temp_sell_indices[:self._batch_orders_num]
            if len(temp_post_buy):
                batch_buy_command = Token.BATCH_ORDER_INFO.copy()
                batch_buy_command['orders'] = [
                    {
                        'symbol': self.symbol_name,
                        'id': each['id'],
                        'price': self.all_grid_price[self.parse_id(each['id'])[0]],
                        'side': self.BUY,
                        'quantity': self.grid_each_qty,
                        'status': Token.TO_POST_POC
                    } for each in temp_post_buy
                ]
                batch_buy_command['status'] = Token.TO_POST_BATCH_POC
                await self.command_transmitter(trans_command=batch_buy_command, token=Token.TO_POST_BATCH_POC)
            if len(temp_post_sell):
                batch_sell_command = Token.BATCH_ORDER_INFO.copy()
                batch_sell_command['orders'] = [
                    {
                        'symbol': self.symbol_name,
                        'id': each['id'],
                        'price': self.all_grid_price[self.parse_id(each['id'])[0]],
                        'side': self.SELL,
                        'quantity': self.grid_each_qty,
                        'status': Token.TO_POST_POC
                    } for each in temp_post_sell
                ]
                batch_sell_command['status'] = Token.TO_POST_BATCH_POC
                await self.command_transmitter(trans_command=batch_sell_command, token=Token.TO_POST_BATCH_POC)

            if len(temp_buy_indices) == 0 and len(temp_sell_indices) == 0:
                break
            # 减缓撒网速度
            await asyncio.sleep(0.2)

        self._layout_complete = True

    def _reasonable_order_num_estimate(self):
        """
        根据当前价格，挂单数量限制，以及价格范围限制设置合理的最大挂单数量
        此时需要已知合约规则和当前价格
        警告：该方法未考虑非线性网格间距，只适用于线性网格
        :return:
        """

        if self.symbol_orders_limit_num != 100 and self.max_buy_order_num > int(self.symbol_orders_limit_num / 2):
            self._log_info('\n*** ================================= ***\n')
            self._log_info('请注意该合约挂单数量限制为 {} ! \n已自动减少缓冲网格数量，请留意交易情况!'.format(self.symbol_orders_limit_num))
            self._log_info('\n*** ================================= ***\n')
            self.max_buy_order_num = self.max_sell_order_num = int(self.symbol_orders_limit_num * 0.8 / 2)
            self.min_buy_order_num = self.min_sell_order_num = int(self.symbol_orders_limit_num * 0.4 / 2)
            self.buffer_buy_num = self.buffer_sell_num = max(3, int(self.min_buy_order_num / 2))

        price_div_demand_side_order_max_num = int(self.current_symbol_price * self.symbol_order_price_div / self.grid_price_step)
        if self.max_buy_order_num > price_div_demand_side_order_max_num:
            self._log_info('\n*** ================================= ***\n')
            self._log_info('请注意价格限制合约挂单数量为 {} ! 已自动减少网格数量'.format(price_div_demand_side_order_max_num))
            self._log_info('\n*** ================================= ***\n')
            self.max_buy_order_num = self.max_sell_order_num = int(price_div_demand_side_order_max_num * 0.95)
            self.min_buy_order_num = self.min_sell_order_num = int(price_div_demand_side_order_max_num * 0.42)
            self.buffer_buy_num = self.buffer_sell_num = max(2, int(self.min_buy_order_num / 2))

        if price_div_demand_side_order_max_num > int(self.symbol_orders_limit_num / 2) and self.max_buy_order_num < int(self.symbol_orders_limit_num * 0.7 / 2):
            self._log_info('\n*** 价格限制充裕，增加网格挂单数量 ***\n')
            self.max_buy_order_num = self.max_sell_order_num = int(self.symbol_orders_limit_num * 0.8 / 2)
            self.min_buy_order_num = self.min_sell_order_num = int(self.symbol_orders_limit_num * 0.4 / 2)
            self.buffer_buy_num = self.buffer_sell_num = max(3, int(self.min_buy_order_num / 2))

    async def _post_market_order(self, market_side: str, market_qty: int) -> None:
        """
        发送市价请求并更新相关统计信息，使程序更简化
        :param market_side:
        :param market_qty:
        :return:
        """
        command = Token.ORDER_INFO.copy()
        command['side'] = market_side
        command['quantity'] = market_qty
        self._log_info('市价下单 {} 张'.format(market_qty))
        await self.command_transmitter(trans_command=command, token=Token.TO_POST_MARKET)
        self._MARKET_ORDER_qty_target = self._MARKET_ORDER_qty_left = market_qty

        if market_side == self.BUY:
            self._account_position_theory += market_qty
        elif market_side == self.SELL:
            self._account_position_theory -= market_qty
        # todo: 由此完善统计信息，更准确

        adding_volume = calc(calc(market_qty, self.symbol_quantity_min_step, '*'), self.current_symbol_price, '*')
        self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
        self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_taker_fee, '*'), '+')

    async def _maintain_grid_order(self, this_order_index: int, this_order_side: str, filled_order_id: str, append_info: str = None, order_filled: bool = True) -> None:

        if not self._is_trading:
            self._log_info('交易结束，不继续维护网格 order_detail: {} {}'.format(str(this_order_index), this_order_side))
            return

        # 1.网格上边界退出
        if append_info:
            self._log_info(append_info)
        self._log_info('维护网格\t\t\t网格位置 = {}'.format(self.critical_index))

        if this_order_index == self.max_index:
            self._log_info('达到网格上边界，退出策略')

            self.open_sell_orders = []
            filled_sell_num = this_order_index - self.critical_index
            self._trading_statistics['filled_sell_order_num'] += filled_sell_num
            adding_volume = calc_sum([calc(each_price, calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'), '*') for each_price in
                                      self.all_grid_price[self.critical_index + 1:this_order_index + 1]])
            self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
            self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

            # self._account_position_theory = calc(self._account_position_theory, calc(filled_sell_num, self.grid_each_qty, '*'), '-')

            self.critical_index = this_order_index

            asyncio.create_task(self._terminate_trading(reason='达到网格上边界'))
            return

        elif this_order_index == -1:
            self._log_info('unknown client_id: {}\nplz check code'.format(this_order_side))
            return

        # 2.根据成交或是poc驳回，维护网格
        if order_filled:
            # ============================== 2.1 订单成交类型 ==============================
            if this_order_index > self.critical_index:
                # 高价位的订单成交
                if this_order_side == self.SELL:
                    # 上方卖单成交，维护网格
                    # 需要瞬间补上的订单数量
                    instant_post_num = this_order_index - self.critical_index
                    self._trading_statistics['filled_sell_order_num'] += instant_post_num
                    adding_volume = calc_sum([calc(each_price, calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'), '*') for each_price in
                                              self.all_grid_price[self.critical_index + 1:this_order_index + 1]])
                    self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
                    self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

                    # self._account_position_theory -= self.grid_each_qty
                    self._log_info('{}卖  {:2} 订单成交\t\t价格: {:<12}\tid: {:<10}'.format
                                   (chr(12288), str(instant_post_num), str(self.all_grid_price[this_order_index]), filled_order_id))

                    instant_post_buy: list = [
                        {
                            'id': self.gen_id(each_index, self.BUY),
                            'status': 'NEW',
                            'time': self.gen_timestamp()
                        } for each_index in range(this_order_index - 1, self.critical_index - 1, -1)
                    ]

                    self.open_buy_orders = self.open_buy_orders + list(reversed(instant_post_buy))
                    self.open_sell_orders = self.open_sell_orders[instant_post_num:]

                    while True:
                        if len(instant_post_buy) < 5:
                            for each_num, each_info in enumerate(instant_post_buy):
                                posting_order = Token.ORDER_INFO.copy()
                                posting_order['symbol'] = self.symbol_name
                                posting_order['id'] = each_info['id']
                                posting_order['price'] = self.all_grid_price[self.parse_id(each_info['id'])[0]]
                                posting_order['side'] = self.BUY
                                posting_order['quantity'] = self.grid_each_qty
                                self._log_info('挂买  {:2} 单\t\t\t价格: {:<12}\tid: {:<10}'.format(str(each_num + 1), posting_order['price'], posting_order['id']))

                                await self.command_transmitter(trans_command=posting_order, token=Token.TO_POST_POC)
                            break
                        else:
                            instant_post_batch, instant_post_buy = instant_post_buy[:self._batch_orders_num], instant_post_buy[self._batch_orders_num:]

                            batch_order = Token.BATCH_ORDER_INFO.copy()
                            batch_order['orders'] = [
                                {
                                    'symbol': self.symbol_name,
                                    'id': each_info['id'],
                                    'price': self.all_grid_price[self.parse_id(each_info['id'])[0]],
                                    'side': self.BUY,
                                    'quantity': self.grid_each_qty,
                                } for each_info in instant_post_batch
                            ]
                            batch_order['status'] = Token.TO_POST_BATCH_POC
                            self._log_info('批量挂买单')
                            await self.command_transmitter(trans_command=batch_order, token=Token.TO_POST_BATCH_POC)

                    self.critical_index = this_order_index

                elif this_order_side == self.BUY:
                    # 上方买单成交，出现快速行情，已经提前反应
                    # self._account_position_theory += self.grid_each_qty
                    self._log_info('{}买 -{:2} 订单成交\t\t价格: {:<12}\tid: {:<10}\t\t已提前做出反应'.format
                                   (chr(12288), str(this_order_index - self.critical_index), str(self.all_grid_price[this_order_index]), filled_order_id))
                else:
                    self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

            elif this_order_index < self.critical_index:
                # 低价位的订单成交
                if this_order_side == self.BUY:
                    # 下方买单成交，维护网格
                    instant_post_num = self.critical_index - this_order_index
                    self._trading_statistics['filled_buy_order_num'] += instant_post_num
                    adding_volume = calc_sum([calc(each_price, calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'), '*') for each_price in
                                              self.all_grid_price[this_order_index:self.critical_index]])
                    self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
                    self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

                    # self._account_position_theory += self.grid_each_qty
                    self._log_info('{}买  {:2} 订单成交\t\t价格: {:<12}\tid: {:<10}'.format
                                   (chr(12288), str(instant_post_num), str(self.all_grid_price[this_order_index]), filled_order_id))

                    instant_post_sell: list = [
                        {
                            'id': self.gen_id(each_index, self.SELL),
                            'status': 'NEW',
                            'time': self.gen_timestamp()
                        } for each_index in range(this_order_index + 1, self.critical_index + 1)
                    ]

                    self.open_buy_orders = self.open_buy_orders[:-instant_post_num]
                    self.open_sell_orders = instant_post_sell + self.open_sell_orders

                    while True:
                        if len(instant_post_sell) < 5:
                            for each_num, each_info in enumerate(instant_post_sell):
                                posting_order = Token.ORDER_INFO.copy()
                                posting_order['symbol'] = self.symbol_name
                                posting_order['id'] = each_info['id']
                                posting_order['price'] = self.all_grid_price[self.parse_id(each_info['id'])[0]]
                                posting_order['side'] = self.SELL
                                posting_order['quantity'] = self.grid_each_qty
                                self._log_info('挂卖  {:2} 单\t\t\t价格: {:<12}\tid: {:<10}'.format(str(each_num + 1), posting_order['price'], posting_order['id']))

                                await self.command_transmitter(trans_command=posting_order, token=Token.TO_POST_POC)
                            break
                        else:
                            instant_post_batch, instant_post_sell = instant_post_sell[:self._batch_orders_num], instant_post_sell[self._batch_orders_num:]

                            batch_order = Token.BATCH_ORDER_INFO.copy()
                            batch_order['orders'] = [
                                {
                                    'symbol': self.symbol_name,
                                    'id': each_info['id'],
                                    'price': self.all_grid_price[self.parse_id(each_info['id'])[0]],
                                    'side': self.SELL,
                                    'quantity': self.grid_each_qty,
                                } for each_info in instant_post_batch
                            ]
                            batch_order['status'] = Token.TO_POST_BATCH_POC
                            self._log_info('批量挂卖单')
                            await self.command_transmitter(trans_command=batch_order, token=Token.TO_POST_BATCH_POC)

                    self.critical_index = this_order_index

                elif this_order_side == self.SELL:
                    # 下方卖单成交，出现快速行情，已经提前反应
                    # self._account_position_theory -= self.grid_each_qty
                    self._log_info('{}卖 -{:2} 订单成交\t\t价格: {:<12}\tid: {:<10}\t\t已提前做出反应'.format
                                   (chr(12288), str(self.critical_index - this_order_index), str(self.all_grid_price[this_order_index]), filled_order_id))
                else:
                    self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

            else:
                # self._log_info('unexpected case that order at critical_index is filled, plz recheck\nid: {}'.format(filled_order_id))
                if this_order_side == self.BUY:
                    # self._account_position_theory += self.grid_each_qty
                    self._log_info('{}买  {:2} 订单成交\t\t价格: {:<12}\tid: {:<10}\t\t延迟有点大'.format
                                   (chr(12288), str(0), str(self.all_grid_price[this_order_index]), filled_order_id))
                elif this_order_side == self.SELL:
                    # self._account_position_theory -= self.grid_each_qty
                    self._log_info('{}卖  {:2} 订单成交\t\t价格: {:<12}\tid: {:<10}\t\t延迟有点大'.format
                                   (chr(12288), str(0), str(self.all_grid_price[this_order_index]), filled_order_id))
                else:
                    self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

        else:
            # ============================== 2.2 订单驳回类型 ==============================
            if this_order_index > self.critical_index:
                # 高价位的卖挂单被驳回
                if this_order_side == self.SELL:
                    # 上方卖单驳回，维护网格
                    # 需要瞬间补上的订单数量
                    instant_reject_num = this_order_index - self.critical_index

                    # self._accumulated_pos_deviation -= self.grid_each_qty

                    self._log_info('{}卖  {:2} 订单被驳回!\t\t价格: {:<12}\tid: {:<10}'.format
                                   (chr(12288), str(instant_reject_num), str(self.all_grid_price[this_order_index]), filled_order_id))
                    # self._log_info('卖 {} 订单成交，价格 {}'.format(str(instant_post_num), str(self.all_grid_price[this_order_index])))
                    instant_post_buy: list = [
                        {
                            'id': self.gen_id(each_index, self.BUY),
                            'status': 'NEW',
                            'time': self.gen_timestamp()
                        } for each_index in range(this_order_index - 1, self.critical_index - 1, -1)
                    ]

                    self.open_buy_orders = self.open_buy_orders + list(reversed(instant_post_buy))
                    self.open_sell_orders = self.open_sell_orders[instant_reject_num:]

                    while True:
                        # todo: 如果2-5之间的情况频繁，考虑也用 batch order
                        if len(instant_post_buy) < 5:
                            for each_num, each_info in enumerate(instant_post_buy):
                                posting_order = Token.ORDER_INFO.copy()
                                posting_order['symbol'] = self.symbol_name
                                posting_order['id'] = each_info['id']
                                posting_order['price'] = self.all_grid_price[self.parse_id(each_info['id'])[0]]
                                posting_order['side'] = self.BUY
                                posting_order['quantity'] = self.grid_each_qty
                                self._log_info('挂买  {:2} 单\t\t\t价格: {:<12}\tid: {:<10}'.format(str(each_num + 1), posting_order['price'], posting_order['id']))
                                # self._log_info('在 {} 价位挂买单, id: {}'.format((str(posting_order['price'])), posting_order['id']))
                                await self.command_transmitter(trans_command=posting_order, token=Token.TO_POST_POC)
                            break
                        else:
                            instant_post_batch, instant_post_buy = instant_post_buy[:self._batch_orders_num], instant_post_buy[self._batch_orders_num:]

                            batch_order = Token.BATCH_ORDER_INFO.copy()
                            batch_order['orders'] = [
                                {
                                    'symbol': self.symbol_name,
                                    'id': each_info['id'],
                                    'price': self.all_grid_price[self.parse_id(each_info['id'])[0]],
                                    'side': self.BUY,
                                    'quantity': self.grid_each_qty,
                                } for each_info in instant_post_batch
                            ]
                            batch_order['status'] = Token.TO_POST_BATCH_POC
                            self._log_info('批量挂买单')
                            await self.command_transmitter(trans_command=batch_order, token=Token.TO_POST_BATCH_POC)

                    self.critical_index = this_order_index

                elif this_order_side == self.BUY:
                    # 上方买单成交，出现快速行情，已经提前反应
                    # self._accumulated_pos_deviation += self.grid_each_qty
                    self._log_info('{}买 -{:2} 订单被驳回!\t\t价格: {:<12}\tid: {:<10}\t\t已提前做出反应'.format
                                   (chr(12288), str(this_order_index - self.critical_index), str(self.all_grid_price[this_order_index]), filled_order_id))
                else:
                    self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

            elif this_order_index < self.critical_index:
                # 低价位的订单成交
                if this_order_side == self.BUY:
                    # 下方买单驳回，维护网格
                    instant_reject_num = self.critical_index - this_order_index

                    # self._accumulated_pos_deviation += self.grid_each_qty

                    self._log_info('{}买  {:2} 订单被驳回!\t\t价格: {:<12}\tid: {:<10}'.format
                                   (chr(12288), str(instant_reject_num), str(self.all_grid_price[this_order_index]), filled_order_id))

                    instant_post_sell: list = [
                        {
                            'id': self.gen_id(each_index, self.SELL),
                            'status': 'NEW',
                            'time': self.gen_timestamp()
                        } for each_index in range(this_order_index + 1, self.critical_index + 1)
                    ]

                    self.open_buy_orders = self.open_buy_orders[:-instant_reject_num]
                    self.open_sell_orders = instant_post_sell + self.open_sell_orders

                    while True:
                        if len(instant_post_sell) < 5:
                            for each_num, each_info in enumerate(instant_post_sell):
                                posting_order = Token.ORDER_INFO.copy()
                                posting_order['symbol'] = self.symbol_name
                                posting_order['id'] = each_info['id']
                                posting_order['price'] = self.all_grid_price[self.parse_id(each_info['id'])[0]]
                                posting_order['side'] = self.SELL
                                posting_order['quantity'] = self.grid_each_qty
                                self._log_info('挂卖  {:2} 单\t\t\t价格: {:<12}\tid: {:<10}'.format(str(each_num + 1), posting_order['price'], posting_order['id']))

                                await self.command_transmitter(trans_command=posting_order, token=Token.TO_POST_POC)
                            break
                        else:
                            instant_post_batch, instant_post_sell = instant_post_sell[:self._batch_orders_num], instant_post_sell[self._batch_orders_num:]

                            batch_order = Token.BATCH_ORDER_INFO.copy()
                            batch_order['orders'] = [
                                {
                                    'symbol': self.symbol_name,
                                    'id': each_info['id'],
                                    'price': self.all_grid_price[self.parse_id(each_info['id'])[0]],
                                    'side': self.SELL,
                                    'quantity': self.grid_each_qty,
                                } for each_info in instant_post_batch
                            ]
                            batch_order['status'] = Token.TO_POST_BATCH_POC
                            self._log_info('批量挂卖单')
                            await self.command_transmitter(trans_command=batch_order, token=Token.TO_POST_BATCH_POC)

                    self.critical_index = this_order_index

                elif this_order_side == self.SELL:
                    # 下方卖单驳回，出现快速行情，已经提前反应
                    # self._accumulated_pos_deviation -= self.grid_each_qty
                    self._log_info('{}卖 -{:2} 订单被驳回!\t\t价格: {:<12}\tid: {:<10}\t\t已提前做出反应'.format
                                   (chr(12288), str(self.critical_index - this_order_index), str(self.all_grid_price[this_order_index]), filled_order_id))
                else:
                    self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

            else:
                # self._log_info('unexpected case that order at critical_index is filled, plz recheck\nid: {}'.format(filled_order_id))
                if this_order_side == self.BUY:
                    # self._accumulated_pos_deviation += self.grid_each_qty
                    self._log_info('{}买  {:2} 订单被驳回!\t\t价格: {:<12}\tid: {:<10}\t\t请检查订单'.format
                                   (chr(12288), str(0), str(self.all_grid_price[this_order_index]), filled_order_id))
                elif this_order_side == self.SELL:
                    # self._accumulated_pos_deviation -= self.grid_each_qty
                    self._log_info('{}卖  {:2} 订单被驳回!\t\t价格: {:<12}\tid: {:<10}\t\t请检查订单'.format
                                   (chr(12288), str(0), str(self.all_grid_price[this_order_index]), filled_order_id))
                else:
                    self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

        # 3.根据实时价格，到达调仓价格时，市价补仓
        # # *.在特定位置补充仓位，撤销多余挂单
        await self._maintainer_by_index()

        # 4.检查买卖单数量并维护其边界挂单，补单全用batch order
        if self._layout_complete:
            # 买单挂单维护
            open_buy_orders_num, open_sell_orders_num = len(self.open_buy_orders), len(self.open_sell_orders)
            if open_buy_orders_num > self.max_buy_order_num:
                post_cancel, self.open_buy_orders = self.open_buy_orders[:self.buffer_buy_num], self.open_buy_orders[self.buffer_buy_num:]
                for each_info in post_cancel:
                    cancel_cmd = Token.ORDER_INFO.copy()
                    cancel_cmd['symbol'] = self.symbol_name
                    cancel_cmd['id'] = each_info['id']
                    await self.command_transmitter(trans_command=cancel_cmd, token=Token.TO_CANCEL)
                    if each_info['id'] in self.partially_filled_orders.keys():
                        traded_qty = int(self.grid_each_qty) - self.partially_filled_orders[each_info['id']]
                        self._accumulated_pos_deviation -= traded_qty
                        self.partially_filled_orders.pop(each_info['id'])

            elif open_buy_orders_num < self.min_buy_order_num:
                if open_buy_orders_num == 0:
                    endpoint_index = self.critical_index
                else:
                    endpoint_index = self.parse_id(self.open_buy_orders[0]['id'])[0]

                # 在超高频网格当中，可能一下子现存订单就非常少，需要一次补充很多挂单
                instant_add_num = self.buffer_buy_num if (self.min_buy_order_num - open_buy_orders_num < self.buffer_buy_num) \
                    else self.max_buy_order_num - open_buy_orders_num - 5

                if endpoint_index > self.present_bottom_index:
                    # <= 时，下方挂单已经达到下边界，不补充挂单
                    filling_post_buy: list = [
                        {
                            'id': self.gen_id(each_index, self.BUY),
                            'status': 'NEW',
                            'time': self.gen_timestamp()
                        } for each_index in range(max(self.present_bottom_index, endpoint_index - instant_add_num), endpoint_index)
                    ]
                    self.open_buy_orders = filling_post_buy + self.open_buy_orders
                    while True:
                        if len(filling_post_buy) == 0:
                            break
                        filling_post_batch, filling_post_buy = filling_post_buy[:self._batch_orders_num], filling_post_buy[self._batch_orders_num:]
                        filling_batch_cmd = Token.BATCH_ORDER_INFO.copy()
                        filling_batch_cmd['orders'] = [
                            {
                                'symbol': self.symbol_name,
                                'id': _info['id'],
                                'price': self.all_grid_price[self.parse_id(_info['id'])[0]],
                                'side': self.BUY,
                                'quantity': self.grid_each_qty,
                            } for _info in filling_post_batch
                        ]
                        filling_batch_cmd['status'] = Token.TO_POST_BATCH_POC
                        await self.command_transmitter(trans_command=filling_batch_cmd, token=Token.TO_POST_BATCH_POC)

            # 卖单挂单维护
            if len(self.open_sell_orders) > self.max_sell_order_num:
                self.open_sell_orders, post_cancel = self.open_sell_orders[:-self.buffer_sell_num], self.open_sell_orders[-self.buffer_sell_num:]
                for each_info in post_cancel:
                    cancel_cmd = Token.ORDER_INFO.copy()
                    cancel_cmd['symbol'] = self.symbol_name
                    cancel_cmd['id'] = each_info['id']
                    await self.command_transmitter(trans_command=cancel_cmd, token=Token.TO_CANCEL)
                    if each_info['id'] in self.partially_filled_orders.keys():
                        traded_qty = int(self.grid_each_qty) - self.partially_filled_orders[each_info['id']]
                        self._accumulated_pos_deviation += traded_qty
                        self.partially_filled_orders.pop(each_info['id'])

            elif len(self.open_sell_orders) < self.min_sell_order_num:
                if len(self.open_sell_orders) == 0:
                    endpoint_index = self.critical_index
                else:
                    endpoint_index = self.parse_id(self.open_sell_orders[-1]['id'])[0]

                # 在超高频网格当中，可能一下子现存订单就非常少，需要一次补充很多挂单
                instant_add_num = self.buffer_sell_num if (self.min_sell_order_num - open_sell_orders_num < self.buffer_sell_num) \
                    else self.max_sell_order_num - open_sell_orders_num - 5

                if endpoint_index < self.max_index:
                    # 否则已经达到边界，不补充挂单
                    filling_post_sell: list = [
                        {
                            'id': self.gen_id(each_index, self.SELL),
                            'status': 'NEW',
                            'time': self.gen_timestamp()
                        } for each_index in range(endpoint_index + 1, min(self.max_index, endpoint_index + instant_add_num) + 1)
                    ]
                    self.open_sell_orders = self.open_sell_orders + filling_post_sell
                    while True:
                        if len(filling_post_sell) == 0:
                            break
                        filling_post_batch, filling_post_sell = filling_post_sell[:self._batch_orders_num], filling_post_sell[self._batch_orders_num:]
                        filling_batch_cmd = Token.BATCH_ORDER_INFO.copy()
                        filling_batch_cmd['orders'] = [
                            {
                                'symbol': self.symbol_name,
                                'id': _info['id'],
                                'price': self.all_grid_price[self.parse_id(_info['id'])[0]],
                                'side': self.SELL,
                                'quantity': self.grid_each_qty,
                            } for _info in filling_post_batch
                        ]
                        filling_batch_cmd['status'] = Token.TO_POST_BATCH_POC
                        await self.command_transmitter(trans_command=filling_batch_cmd, token=Token.TO_POST_BATCH_POC)

        # 5.最后根据需要更新统计信息
        if (self._trading_statistics['filled_buy_order_num'] + self._trading_statistics['filled_sell_order_num']) % 80 == 0:
            self._need_adjust_pos = True

    async def _maintainer_by_price(self) -> None:
        """
        根据价格实时维护网格
        :return:
        """
        if self.current_symbol_price >= self.present_step_up_price:
            self._log_info('\n>>> 价格触发，台阶向上移动\t触发价格: {}\n'.format(self.present_step_up_price))
            self.indices_of_filling.pop(0)
            # 需要向上移动区间
            await self._post_market_order(self.BUY, self.filling_quantity)

            # 删除多余挂单
            endpoint_index = self.parse_id(self.open_buy_orders[0]['id'])[0]
            if endpoint_index < self.present_bottom_index:
                cancel_num = self.present_bottom_index - endpoint_index
                post_cancel, self.open_buy_orders = self.open_buy_orders[:cancel_num], self.open_buy_orders[cancel_num:]
                # todo: 可能有一次性撤销挂单非常多的情况，gate还好，币安则要额外判断
                for each_info in post_cancel:
                    cancel_cmd = Token.ORDER_INFO.copy()
                    cancel_cmd['symbol'] = self.symbol_name
                    cancel_cmd['id'] = each_info['id']
                    await self.command_transmitter(trans_command=cancel_cmd, token=Token.TO_CANCEL)
                    if each_info['id'] in self.partially_filled_orders.keys():
                        traded_qty = int(self.grid_each_qty) - self.partially_filled_orders[each_info['id']]
                        self._accumulated_pos_deviation -= traded_qty
                        self.partially_filled_orders.pop(each_info['id'])

            self._grid_stair_step_up()

    async def _maintainer_by_index(self) -> None:
        """
        根据index实时维护网格
        :return:
        """
        if self.critical_index >= self.present_step_up_index:
            self._log_info('\n>>> 挂单触发，台阶向上移动\t触发价格: {}\n'.format(self.present_step_up_price))
            self.indices_of_filling.pop(0)

            await self._post_market_order(self.BUY, self.filling_quantity)

            # 删除多余挂单
            endpoint_index = self.parse_id(self.open_buy_orders[0]['id'])[0]
            if endpoint_index < self.present_bottom_index:
                cancel_num = self.present_bottom_index - endpoint_index
                post_cancel, self.open_buy_orders = self.open_buy_orders[:cancel_num], self.open_buy_orders[cancel_num:]
                # todo: 可能有一次性撤销挂单非常多的情况，gate还好，币安则要额外判断
                for each_info in post_cancel:
                    cancel_cmd = Token.ORDER_INFO.copy()
                    cancel_cmd['symbol'] = self.symbol_name
                    cancel_cmd['id'] = each_info['id']
                    await self.command_transmitter(trans_command=cancel_cmd, token=Token.TO_CANCEL)
                    if each_info['id'] in self.partially_filled_orders.keys():
                        traded_qty = int(self.grid_each_qty) - self.partially_filled_orders[each_info['id']]
                        self._accumulated_pos_deviation -= traded_qty
                        self.partially_filled_orders.pop(each_info['id'])

            self._grid_stair_step_up()

    async def _terminate_trading(self, reason: str = '') -> None:
        if not self._is_trading:
            self._log_info('--- 策略正在停止，请稍等。。。')
            self.manually_stop_request_time += 1
            self._log_info(str(self.manually_stop_request_time))
            # 点击次数多，用户强行终止
            if self.manually_stop_request_time >= 10:
                self._log_info('--- 用户强行终止策略，请自行平仓和撤销挂单')
                self._update_text_task.cancel()
                self._fix_order_task.cancel()

                self.force_stopped = True
                self._my_logger.close_file()
                self._my_preserver.stop_preserving()
                self._my_executor.stop_single_contract_order_subscription(self.symbol_name)
                self._my_executor.stop_single_contract_ticker_subscription(self.symbol_name)
                self._my_executor.strategy_stopped(self.stg_num)
                self._bound_running_column = None
            return
        self._is_trading = False

        self._update_text_task.cancel()
        self._fix_order_task.cancel()

        cancel_cmd, close_cmd = Token.ORDER_INFO.copy(), Token.ORDER_INFO.copy()
        cancel_cmd['symbol'], close_cmd['symbol'] = self.symbol_name, self.symbol_name

        await asyncio.sleep(0.8)  # 此处延时是为了确保能撤销所有挂单，防止撤单和挂单同时请求，最后出现还剩一单挂着的情况
        await self.command_transmitter(trans_command=cancel_cmd, token=Token.CANCEL_ALL)
        await self._update_trading_statistics()
        await asyncio.sleep(1)

        self._log_info('--- 市价平仓')
        # self._log_info('--- 策略开始前账户仓位:\t{}\t张'.format(self._init_account_position))
        self._log_info('--- 累计理论计算当前仓位:\t{}\t张'.format(self._account_position_theory))
        current_position = await self._my_executor.get_symbol_position(self.symbol_name)
        self._log_info('--- 账户实际当前合约仓位:\t{}\t张'.format(current_position))

        close_qty = current_position - self._init_account_position
        self._log_info('--- 实际市价平掉仓位 {}'.format(str(close_qty)))
        await self.command_transmitter(trans_command=close_cmd, token=Token.CLOSE_POSITION)

        adding_volume = calc(calc(close_qty, self.symbol_quantity_min_step, '*'), self.current_symbol_price, '*')
        self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
        self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_taker_fee, '*'), '+')

        self._log_info('--- 终止策略，终止原因: {}'.format(reason))
        await self._update_detail_info(only_once=True)

        if not self.force_stopped:
            self._my_logger.close_file()
            self._my_preserver.stop_preserving()
            self._my_executor.stop_single_contract_order_subscription(self.symbol_name)
            self._my_executor.stop_single_contract_ticker_subscription(self.symbol_name)
            self._my_executor.strategy_stopped(self.stg_num)

            # todo: 此处或许应该在基类中定义
            self._bound_running_column = None

    async def _update_trading_statistics(self) -> None:

        filled_trading_pair = min(self._trading_statistics['filled_buy_order_num'], self._trading_statistics['filled_sell_order_num'])
        self._trading_statistics['matched_profit'] = calc(calc(filled_trading_pair, self.grid_price_step, '*'), calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'), '*')

        self._trading_statistics['realized_profit'] = calc(self._each_stair_profit, self.present_stair_num, '*')

        # 用最新实时价格计算未配对盈亏
        unmatched_profit = self.unmatched_profit_calc(
            initial_index=self.present_base_index,
            current_index=self.critical_index,
            all_prices=self.all_grid_price,
            each_grid_qty=calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'),
            init_pos_price=self.all_grid_price[self.present_base_index],
            init_pos_qty=calc(self.filling_quantity, self.symbol_quantity_min_step, '*'),
            current_price=self.current_symbol_price
        )

        self._trading_statistics['unrealized_profit'] = unmatched_profit
        self._trading_statistics['final_profit'] = calc(calc(calc(self._trading_statistics['matched_profit'], self._trading_statistics['realized_profit'], '+'),
                                                             self._trading_statistics['unrealized_profit'], '+'), self._trading_statistics['total_trading_fees'], '-')

    async def _update_detail_info(self, interval_time: int = 3, only_once: bool = False) -> None:
        if not only_once:
            await asyncio.sleep(3)

        while True:
            await self._update_trading_statistics()
            self._update_column_text()
            self._save_strategy_data()

            start_t = pd.to_datetime(self._trading_statistics['strategy_start_time'], unit='ms')
            current_t = pd.to_datetime(self.gen_timestamp(), unit='ms')
            running_time = current_t - start_t
            days: int = running_time.days
            seconds: int = running_time.seconds
            hours, seconds = int(seconds / 3600), seconds % 3600
            minutes, seconds = int(seconds / 60), seconds % 60

            bottom_price = self.all_grid_price[self.present_bottom_index]
            # top_price = self.all_grid_price[(self.lower_grid_max_num + (self.present_stair_num + 1) * self.filling_grid_step_num)]
            lower_step_price = self.all_grid_price[self.present_low_step_index]
            top_price = self.all_grid_price[-1]

            showing_texts = '高频智能调仓Beta 统计信息:'
            showing_texts += '\n\n*** {} ***\n\n'.format('=' * 51)

            if days == 0:
                showing_texts += '交易统计\t\t运行时间\t\t{}:{}:{}\n\n'.format(str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2))
            else:
                showing_texts += '交易统计\t\t运行时间\t\t{} day\t{}:{}:{}\n\n'.format(
                    str(days), str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2))
            # showing_texts += '交易统计:\t\t当前时间 {}\n\n'.format(str(str(pd.to_datetime(self.gen_timestamp(), unit='ms'))))
            self.derive_valid_position()
            showing_texts += '-' * 58
            showing_texts += '\n\n策略记忆价格:\t{:<10}\n'.format(str(self.all_grid_price[self.critical_index]))
            showing_texts += '合约最新价格:\t{:<10}\n\n'.format(str(self.current_symbol_price))
            showing_texts += '-' * 58
            showing_texts += '\n\n修正仓位挂单:\t\t{}\n'.format(False if self.adjusting_index == -1 else True)
            showing_texts += '当前正确仓位:\t\t{:<10}张\n'.format(self._current_valid_position)
            showing_texts += '累计计算仓位:\t\t{:<10}张\n'.format(self._account_position_theory)
            showing_texts += '累计仓位偏移:\t\t{:<10}张\n\n'.format(self._accumulated_pos_deviation)
            showing_texts += '部分成交订单:\t\t{:<10}个挂单\n\n'.format(len(self.partially_filled_orders))

            showing_texts += '-' * 58
            showing_texts += '\n\n卖单挂单成交次数:\t{:<10}\n'.format(str(self._trading_statistics['filled_sell_order_num']))
            showing_texts += '买单挂单成交次数:\t{:<10}\n\n'.format(str(self._trading_statistics['filled_buy_order_num']))
            showing_texts += '-' * 58
            showing_texts += '\n\n已补仓次数:\t\t{} / {}\n'.format(self.present_stair_num, self.stairs_total_num)
            showing_texts += '当前套利区间:\t\t{:<10} ~  {:<10}\n'.format(bottom_price, top_price)
            showing_texts += '非线性区间:\t\t{:<10} ~  {:<10}\n'.format(bottom_price, lower_step_price)
            showing_texts += '\n已达成交易量:\t\t{:<20}\t{}\n\n'.format(str(self._trading_statistics['achieved_trade_volume']), self.symbol_name[-4:])
            showing_texts += '-' * 58
            showing_texts += '\n\n套利收益:\t\t{:<20}\t{}\n'.format(self._trading_statistics['matched_profit'], self.symbol_name[-4:])
            showing_texts += '做多收益:\t\t{:<20}\t{}\n'.format(self._trading_statistics['realized_profit'], self.symbol_name[-4:])

            # 如果价格下冲超出下边界，提示一下
            if self.current_symbol_price <= self.all_grid_price[self.present_bottom_index]:
                showing_texts += '未实现盈亏:\t\t{:<20}\t{} (价格走出下区间)\n\n'.format(
                    self._trading_statistics['unrealized_profit'], self.symbol_name[-4:])
            else:
                showing_texts += '未实现盈亏:\t\t{:<20}\t{}\n\n'.format(self._trading_statistics['unrealized_profit'], self.symbol_name[-4:])

            showing_texts += '-' * 58
            showing_texts += '\n\n交易手续费:\t\t{:<20}\t{}\n'.format(self._trading_statistics['total_trading_fees'], self.symbol_name[-4:])
            showing_texts += '\n策略净收益:\t\t{:<20}\t{}\n\n'.format(self._trading_statistics['final_profit'], self.symbol_name[-4:])
            showing_texts += '*** {} ***\n\n'.format('=' * 51)

            self._bound_running_column.update_trade_info(showing_texts)

            if only_once:
                return

            await asyncio.sleep(interval_time)

    async def _pre_update_detail_info(self, interval_time: int = 1) -> None:
        """
        策略还在等待时更新的信息，提升交互感
        给交易员更好的交易体验
        :param interval_time:
        :return:
        """
        while True:
            self._save_strategy_data()

            start_t = pd.to_datetime(self._trading_statistics['waiting_start_time'], unit='ms')
            current_t = pd.to_datetime(self.gen_timestamp(), unit='ms')
            running_time = current_t - start_t
            days: int = running_time.days
            seconds: int = running_time.seconds
            hours, seconds = int(seconds / 3600), seconds % 3600
            minutes, seconds = int(seconds / 60), seconds % 60

            showing_texts = '非线性智能调仓网格 等待触发中。。。'
            showing_texts += '\n\n*** {} ***\n\n'.format('=' * 51)

            if days == 0:
                showing_texts += '等待时间\t\t{}:{}:{}\n\n'.format(str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2))
            else:
                showing_texts += '等待时间\t\t{} day\t{}:{}:{}\n\n'.format(
                    str(days), str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2))

            showing_texts += '合约最新价格:\t{:<10}\n\n'.format(str(self.current_symbol_price))
            showing_texts += '网格触发价格:\t{:<10}\n\n'.format(str(self.entry_grid_price))

            showing_texts += '*** {} ***\n\n'.format('=' * 51)

            self._bound_running_column.update_trade_info(showing_texts)

            await asyncio.sleep(interval_time)

    def _update_column_text(self):
        """
        更新 column 显示的策略收益
        :return:
        """
        # todo: 考虑使用pandas
        self._bound_running_column.update_profit_text(
            matched_profit=str(calc(self._trading_statistics['matched_profit'], self._trading_statistics['realized_profit'], '+')),
            unmatched_profit=str(self._trading_statistics['unrealized_profit'])
        )

    async def show_final_statistics(self) -> str:
        """
        策略结束后，输出最终统计信息
        :return:
        """
        # 使用该变量判断策略是运行前停止还是运行后停止
        if self._is_waiting:
            return str(0)
        else:
            await self._update_trading_statistics()
            return str(self._trading_statistics['final_profit'])

    def _save_strategy_data(self) -> None:
        """
        每次更新策略统计信息时，同步保存策略参数和统计信息，以防策略意外终止
        需要保存的参数：
            self.param_dict
            self.present_base_price
            self.present_stair_num
            self.current_symbol_price, self.previous_price?
            self._trading_statistics
            self._is_waiting, self._is_trading
        :return:
        """
        # todo: work from here
        stg_param_dict = {
            'symbol_name': self.symbol_name,
            'up_price': self._x_grid_up_limit,
            'each_grid_qty': self._x_each_grid_qty,
            'leverage': self._x_leverage,
            'trigger_start': self._x_trigger_start,  # 是否用挂单触发, True/False
            'pending_trigger_price': self._x_trigger_price,

            'grid_abs_step': self._x_price_abs_step,
            'grid_rel_step': self._x_price_rel_step,
            'filling_price_step': self._x_filling_price_step,
            'lower_price_step': self._x_lower_price_step,

            'max_grid_step': self._x_max_grid_step,
            'lower_buffer_price': self._x_lower_buffer_price_limit,
            'alpha': self._x_alpha
        }

        strategy_info = {
            'channel': 'futures',
            'stg_name': self.STG_NAME,
            'symbol_name': self.symbol_name,
            'stg_params': stg_param_dict,
            'stg_entry_price': self.entry_grid_price,
            'present_stair_num': self.present_stair_num,
            'current_symbol_price': self.current_symbol_price,
            'stg_statistics': self._trading_statistics,
            'is_waiting': self._is_waiting,
            'is_trading': self._is_trading
        }
        self._my_preserver.preserve_strategy_info(strategy_info)

    async def restart(self, stg_info: dict, save_file_name: str) -> bool:    # todo: 改为文件名
        """
        使用已保存的策略信息重新开启策略
        重启网格相当于开启了一个新的网格，并重新计算
        :return:
        """
        restart_success = True

        try:
            stg_params = stg_info['stg_params']
            stg_statistics = stg_info['stg_statistics']

            self.symbol_name = stg_info['symbol_name']          # 在重启时也定义了实例的合约名称，此步多余
            # 获取新的记录参数实例
            self._my_logger = LogRecorder()
            self._my_logger.open_file(self.symbol_name)

            self._log_info('\n\\(✿◕‿◕)/ 高频智能调仓Beta 策略重启!\n')

            # 策略初始参数
            self._x_grid_up_limit = stg_params['up_price']
            self._x_each_grid_qty = stg_params['each_grid_qty']
            self._x_leverage = stg_params['leverage']
            self._x_trigger_start = stg_params['trigger_start']
            self._x_trigger_price = stg_params['pending_trigger_price']
            self._x_price_abs_step = stg_params['grid_abs_step']
            self._x_price_rel_step = stg_params['grid_rel_step']
            self._x_filling_price_step = stg_params['filling_price_step']
            self._x_lower_price_step = stg_params['lower_price_step']
            self._x_max_grid_step = stg_params['max_grid_step']
            self._x_lower_buffer_price_limit = stg_params['lower_buffer_price']
            self._x_alpha = stg_params['alpha']

            # 由于一般而言策略重启间隔时间比较短，不开发恢复正在挂单等待的策略
            if stg_info['is_waiting']:
                self._log_info('该策略处于挂单等待触发状态，恢复功能尚未开发，请手动重启')
                return False

            # 按照开启策略的步骤一步步重启
            self._my_executor.start_single_contract_order_subscription(self.symbol_name)
            self._my_executor.start_single_contract_ticker_subscription(self.symbol_name)
            await self._get_trading_rule(self.symbol_name)
            # 得到初始时的所有网格参数变量
            self.derive_functional_variables(assign_entry_price=stg_info['stg_entry_price'])
            # 按照当前价格演化台阶价格变化
            self.current_symbol_price = await self._my_executor.get_current_price(self.symbol_name)
            self._log_info('策略停止时合约价格\t{}\n当前合约价格\t\t{}'.format(str(stg_info['current_symbol_price']), str(self.current_symbol_price)))
            self._log_info('\n停止期间价格变化了\t{} %'.format(round((self.current_symbol_price - stg_info['current_symbol_price']) * 100 / stg_info['current_symbol_price'], 2)))
            # 首先根据历史，移动台阶
            for i in range(int(stg_info['present_stair_num'])):
                self._log_info('复原台阶上移操作')
                self.indices_of_filling.pop(0)
                self._grid_stair_step_up()
            # 然后补充策略停止期间应该操作的台阶上移
            if self.current_symbol_price >= self._x_grid_up_limit:
                # 无意义的重启也需要添加进栏目，方便观察启动记录
                self._log_info('\n当前价已高于策略上限价格，无需重启策略')
                return False
            else:
                while self._x_grid_up_limit > self.current_symbol_price >= self.present_step_up_price:
                    self._log_info('补充策略停止期间的台阶上移操作')
                    self.indices_of_filling.pop(0)
                    self._grid_stair_step_up()
            # 获得 c index
            for each_index, each_grid_price in enumerate(self.all_grid_price):
                if each_grid_price <= self.current_symbol_price < (each_grid_price + self._x_price_abs_step):
                    if self.current_symbol_price - each_grid_price <= self._x_price_abs_step / 2:
                        self.critical_index = each_index
                    else:
                        self.critical_index = each_index + 1
            # 获得详细统计信息
            self._trading_statistics['waiting_start_time'] = stg_statistics['waiting_start_time']
            self._trading_statistics['strategy_start_time'] = stg_statistics['strategy_start_time']
            self._trading_statistics['filled_buy_order_num'] = stg_statistics['filled_buy_order_num']
            self._trading_statistics['filled_sell_order_num'] = stg_statistics['filled_sell_order_num']
            self._trading_statistics['achieved_trade_volume'] = stg_statistics['achieved_trade_volume']
            self._trading_statistics['matched_profit'] = stg_statistics['matched_profit']
            self._trading_statistics['realized_profit'] = stg_statistics['realized_profit']
            self._trading_statistics['unrealized_profit'] = stg_statistics['unrealized_profit']
            self._trading_statistics['total_trading_fees'] = stg_statistics['total_trading_fees']
            self._trading_statistics['final_profit'] = stg_statistics['final_profit']

            self._log_info('\n策略恢复中。。。')
            # 设置合理挂单数量
            self._reasonable_order_num_estimate()

            self._my_preserver = Preserver()                    # todo: 重启失败虽然会移动文件，但是也清除了文件内容，逻辑有点乱，需要修改
            self._my_preserver.acquire_user_id(self._my_executor.return_user_id())
            self._my_preserver.use_existing_file(save_file_name)

            self._update_text_task = asyncio.create_task(self._update_detail_info(interval_time=3))

            # 重启网格并获得正确仓位
            cancel_cmd = Token.ORDER_INFO.copy()
            cancel_cmd['symbol'] = self.symbol_name
            await self.command_transmitter(trans_command=cancel_cmd, token=Token.CANCEL_ALL)
            await asyncio.sleep(1)
            self.derive_valid_position()

            self._is_trading = True
            self._is_waiting = False
            self._layout_complete = False
            # 虽然重启了，也让统计数据好看一些
            self._account_position_theory = await self._my_executor.get_symbol_position(self.symbol_name)

            await self._layout_net()

            self._fix_order_task = asyncio.create_task(self._order_fixer(interval_time=1200))

            self._log_info('$$$ 策略恢复: 网格重启完成')
            # 最后将相关变量归位，并需要调整仓位
            self._reset_functional_vars()
            self._need_adjust_pos = True
        except Exception as e:
            print('{} 策略重启失败!'.format(self.symbol_name))
            print(e, type(e))
            restart_success = False

        return restart_success

    def restart_failed(self) -> None:
        """
        如果策略重启失败，模仿策略终止操作，但是程序上会简单一些
        :return:
        """
        self._is_trading = False
        # 防止调用策略统计功能
        self._is_waiting = True

        if self._update_text_task:
            self._update_text_task.cancel()
        if self._fix_order_task:
            self._fix_order_task.cancel()

        if self._my_logger:
            self._my_logger.close_file()
        if self._my_preserver:
            self._my_preserver.failed_to_preserve()
        self._my_executor.strategy_stopped(self.stg_num)
        self._bound_running_column = None

    # functional methods
    def _clean_accumulated_partial_orders(self) -> None:
        """
        每次维护网格后，判断已累积的部分成交订单中，是否有距离过远的，
        如果有，翻新该订单并将仓位偏移记录在变量中
        :return:
        """
        # 条件执行该函数，可以不必要
        if len(self.partially_orders_indices_list) == 0:
            return
        # 可以考虑买卖单距离判定不相等
        if abs(self.critical_index - self.partially_orders_indices_list[0]) > min(self.min_buy_order_num, self.min_sell_order_num, 10):
            if self.partially_orders_indices_list[0] < self.critical_index:
                traded_qty = int(self.grid_each_qty) - self.partially_filled_orders[self.gen_id(self.partially_orders_indices_list[0], self.BUY)]
                self._accumulated_pos_deviation -= traded_qty
                asyncio.create_task(self._renew_remote_partial_order(self.partially_orders_indices_list[0], self.BUY))
            else:
                traded_qty = int(self.grid_each_qty) - self.partially_filled_orders[self.gen_id(self.partially_orders_indices_list[0], self.SELL)]
                self._accumulated_pos_deviation += traded_qty
                asyncio.create_task(self._renew_remote_partial_order(self.partially_orders_indices_list[0], self.SELL))

        if len(self.partially_orders_indices_list) > 1:
            if abs(self.critical_index - self.partially_orders_indices_list[-1]) > min(self.min_buy_order_num, self.min_sell_order_num, 10):
                if self.partially_orders_indices_list[-1] < self.critical_index:
                    traded_qty = int(self.grid_each_qty) - self.partially_filled_orders[self.gen_id(self.partially_orders_indices_list[-1], self.BUY)]
                    self._accumulated_pos_deviation -= traded_qty
                    asyncio.create_task(self._renew_remote_partial_order(self.partially_orders_indices_list[-1], self.BUY))
                else:
                    traded_qty = int(self.grid_each_qty) - self.partially_filled_orders[self.gen_id(self.partially_orders_indices_list[-1], self.SELL)]
                    self._accumulated_pos_deviation += traded_qty
                    asyncio.create_task(self._renew_remote_partial_order(self.partially_orders_indices_list[-1], self.SELL))

    def _clean_accumulated_partial_orders_beta(self) -> None:
        """
        上一个方法的beta版，遍历原始字典，减少出错可能性
        :return:
        """
        if len(self.partially_filled_orders) == 0:
            return

        for each_id, each_left_qty in self.partially_filled_orders.items():
            each_index, each_side = self.parse_id(each_id)
            if abs(self.critical_index - each_index) > min(self.min_buy_order_num, self.min_sell_order_num, 10):
                traded_qty = int(self.grid_each_qty) - each_left_qty
                if each_side == self.BUY:
                    self._accumulated_pos_deviation -= traded_qty
                    asyncio.create_task(self._renew_remote_partial_order(each_index, self.BUY))
                else:
                    self._accumulated_pos_deviation += traded_qty
                    asyncio.create_task(self._renew_remote_partial_order(each_index, self.SELL))

    async def _renew_remote_partial_order(self, order_index: int, order_side: str) -> None:
        """
        使用协程来翻新订单，避免主功能函数时间阻塞
        操作：撤销残缺订单，等待一定时间后，用新订单代替
        :param order_index:
        :return:
        """
        self._cannot_check_open_orders = True
        renew_order_id = self.gen_id(order_index, order_side)

        cancel_partial = Token.ORDER_INFO.copy()
        cancel_partial['symbol'] = self.symbol_name
        cancel_partial['id'] = renew_order_id

        asyncio.create_task(self.command_transmitter(trans_command=cancel_partial, token=Token.TO_CANCEL))

        time.sleep(0.8)

        renew_order = Token.ORDER_INFO.copy()
        renew_order['symbol'] = self.symbol_name
        renew_order['id'] = renew_order_id
        renew_order['price'] = self.all_grid_price[order_index]
        renew_order['side'] = order_side
        renew_order['quantity'] = self.grid_each_qty

        asyncio.create_task(self.command_transmitter(trans_command=renew_order, token=Token.TO_POST_POC))

        time.sleep(0.4)
        self._cannot_check_open_orders = False

    async def _check_position(self) -> None:
        """
        每隔一段交易量，自动修正仓位，该方法在策略不繁忙时执行
        注意，假设所有的仓位偏移都已知并被记录，没有出现未知来源的仓位偏移，则：
        current_account_qty: 实时读取到的当前账户实际仓位
        accumulated_pos_deviation: 程序累计计算的仓位偏移，来自于所有已知的带来仓位偏移情况
        current_valid_pos: 策略运行至此，如果完全理想，则当前应有的仓位

        current_valid_pos = current_account_qty + accumulated_pos_deviation
        因此等式两边的差值就是未知来源的仓位偏移

        操作：将所有仓位偏移计算后，记录到 accumulated_pos_deviation 变量当中，后续根据该变量调整仓位
        :return:
        """
        start_t = self._running_loop.time()
        current_account_qty = await self._my_executor.get_symbol_position(self.symbol_name)     # todo: 测试延时
        end_t = self._running_loop.time()
        elapsed_t_ms = int((end_t - start_t) * 1000)
        self._log_info('>>> 获取仓位耗时: {} ms'.format(elapsed_t_ms))

        self.derive_valid_position()
        self._log_info('\n### 执行仓位修正:')
        # self._log_info('### 账户初始仓位:\t\t{}\t张'.format(self._init_account_position))
        self._log_info('### 累计理论当前仓位:\t\t{}\t张'.format(self._account_position_theory))
        self._log_info('### 账户实际当前仓位:\t\t{}\t张\n'.format(current_account_qty))
        # 这两行不相等，说明正向理论计算当前仓位存在遗漏或者偏差

        # todo: 统计部分成交订单带来的仓位偏移，该变量
        partial_order_pos_dev: int = 0
        if len(self.partially_filled_orders) > 0:
            for each_id, each_qty in self.partially_filled_orders.items():
                if self.parse_id(each_id)[1] == self.BUY:
                    # 部分买单成交表示需要立即卖出，因此为负数
                    partial_order_pos_dev -= each_qty
                else:
                    partial_order_pos_dev += each_qty

        # self._log_info('### 除去已知偏差后:\t\t{}\t张'.format(str(self._account_position_theory + self._accumulated_pos_deviation)))
        self._log_info('### 策略当前正确仓位:\t\t{}\t张'.format(self._current_valid_position))
        self._log_info('### 当前矫正后仓位: \t\t{}\t张'.format(str(current_account_qty + self._accumulated_pos_deviation + partial_order_pos_dev)))
        # 后两行如果不相等，则表示反向计算累计仓位偏移不完备，存在未知的仓位偏移来源

        fix_qty = int(current_account_qty + self._accumulated_pos_deviation + partial_order_pos_dev - self._current_valid_position)
        # fix_qty 大于 0 表示 修正后 账户多余仓位，小于0 表示 修正后 账户缺少仓位

        if fix_qty == 0:
            self._log_info('\n### 无额外仓位偏移')
        else:
            self._log_info('\n##### 存在未知来源的仓位偏移 #####')
            if fix_qty > 0:
                self._log_info('##### 账户多余仓位 {} 张 #####'.format(str(fix_qty)))
            else:
                self._log_info('##### 账户缺失仓位 {} 张 #####'.format(str(abs(fix_qty))))

            self._accumulated_pos_deviation -= fix_qty
            # self._log_info('### 已记录')

    async def _check_open_orders(self) -> None:
        """
        协程方式检查策略挂单，将挂单修正至正常

        操作：
            1. 如果价格偏离记录价格较多，则说明挂单非常失败，直接撤销所有挂单，并重新layout    todo: layout 修改，以及钉钉提醒机器人

            否则
            2. 如果没有偏移，则
                获取实际挂单id list

                2.1 先检查实际挂单，剔除账户上的多余挂单
                2.2 再使用理论记录的挂单，补充缺少挂单

        :return:
        """
        if self._cannot_check_open_orders:
            self._log_info('$$$ 检查挂单操作被禁止，等待下一回合')
            return
        # 此处最少约有100ms的延时    todo: 测试延时
        # todo: 检测挂单的同时，检测挂单是否部分成交并检查部分成交记录情况

        # 1. 价格偏移较大情况
        if self.critical_index >= 1:
            if abs(calc(self.current_symbol_price, self.all_grid_price[self.critical_index], '-')) > \
                    5 * calc(self.all_grid_price[self.critical_index], self.all_grid_price[self.critical_index - 1], '-'):
                self._log_info('$$$ 价格偏离较大: 最新价 {}; 策略价 {}, 直接重新开启网格!'.format(self.current_symbol_price, self.all_grid_price[self.critical_index]))

                # 撤销所有挂单
                cancel_cmd = Token.ORDER_INFO.copy()
                cancel_cmd['symbol'] = self.symbol_name
                await self.command_transmitter(trans_command=cancel_cmd, token=Token.CANCEL_ALL)
                await asyncio.sleep(1)

                self.current_symbol_price = await self._my_executor.get_current_price(self.symbol_name)
                for each_index, each_grid_price in enumerate(self.all_grid_price):
                    if each_grid_price <= self.current_symbol_price < (each_grid_price + self._x_price_abs_step):
                        if self.current_symbol_price - each_grid_price <= self._x_price_abs_step / 2:
                            self.critical_index = each_index
                        else:
                            self.critical_index = each_index + 1

                self.derive_valid_position()

                self._layout_complete = False
                await self._layout_net()

                self._log_info('$$$ 重启网格完成')
                # 最后将相关变量归位
                self._reset_functional_vars()
                return

        start_t = self._running_loop.time()
        # account_orders_list, account_orders_list_id = await self._my_executor.get_open_orders(self.symbol_name)
        account_open_orders = await self._my_executor.get_open_orders_beta(self.symbol_name)
        end_t = self._running_loop.time()
        elapsed_t_ms = int((end_t - start_t) * 1000)
        self._log_info('>>> 获取账户挂单耗时: {} ms'.format(elapsed_t_ms))

        # 每隔固定时间，检查挂单数量合理性
        self._reasonable_order_num_estimate()

        account_orders_list = [each_info['stg_id'] for each_info in account_open_orders]
        account_orders_list_id = [str(each_info['server_id']) for each_info in account_open_orders]
        # 重新更新部分成交挂单信息
        self.partially_filled_orders = {}
        for each_info in account_open_orders:
            if each_info['size'] != each_info['left_qty']:
                self.partially_filled_orders[each_info['stg_id']] = abs(each_info['left_qty'])

        stg_open_orders: list[str] = [each_order['id'] for each_order in self.open_buy_orders] + [each_order['id'] for each_order in self.open_sell_orders]
        # 剔除特殊挂单
        market_ioc_buy, market_ioc_sell = self.gen_id(self.MARKET_ORDER_ID, self.BUY), self.gen_id(self.MARKET_ORDER_ID, self.SELL)
        for each_i, each_stg_id in enumerate(account_orders_list):
            if market_ioc_buy == each_stg_id:
                account_orders_list.pop(each_i)
                account_orders_list_id.pop(each_i)
            elif market_ioc_sell == each_stg_id:
                account_orders_list.pop(each_i)
                account_orders_list_id.pop(each_i)

        if len(account_orders_list) == len(stg_open_orders):
            self._log_info('$$$ 快速判断无需修正挂单')
            self._need_fix_order = False
            return

        # 勤快方法
        exist_redundant_order, exist_missing_order = False, False
        for each_index, each_account_order_id in enumerate(account_orders_list):
            if each_account_order_id not in stg_open_orders:
                real_id = account_orders_list_id[each_index]
                self._log_info('$$$ 检测到多余挂单，撤销挂单\t\tid: {:<12}\tid: {:<10}'.format(real_id, each_account_order_id))
                exist_redundant_order = True

                cancel_cmd = Token.ORDER_INFO.copy()
                cancel_cmd['symbol'] = self.symbol_name
                cancel_cmd['id'] = real_id
                asyncio.create_task(self.command_transmitter(trans_command=cancel_cmd, token=Token.TO_CANCEL))

        for each_stg_order_id in stg_open_orders:
            if each_stg_order_id not in account_orders_list:
                self._log_info('$$$ 检测到缺失挂单，补充挂单\t\t\tid: {:<10}'.format(each_stg_order_id))
                exist_missing_order = True

                posting_order = Token.ORDER_INFO.copy()
                posting_order['symbol'] = self.symbol_name
                posting_order['id'] = each_stg_order_id
                posting_order['price'] = self.all_grid_price[self.parse_id(each_stg_order_id)[0]]
                posting_order['side'] = self.parse_id(each_stg_order_id)[1]
                posting_order['quantity'] = self.grid_each_qty
                asyncio.create_task(self.command_transmitter(trans_command=posting_order, token=Token.TO_POST_POC))

        if exist_redundant_order or exist_missing_order:
            self._log_info('$$$ 修正挂单任务完成')
        else:
            self._log_info('$$$ 所有挂单正常，无需修正挂单')

        self._need_fix_order = False

    async def _order_fixer(self, first_waiting_time: int = 300, interval_time: int = 1200) -> None:
        """
        该协程是一个一直循环运行的任务，每等待一段时间，执行修正挂单任务
        :return:
        """
        self._log_info('$$$ 360挂单卫士已开启')
        await asyncio.sleep(first_waiting_time)

        while True:
            self._log_info('$$$ 挂单卫士: 例行修正挂单')
            if self._need_fix_order:
                self._log_info('$$$ 挂单卫士: 已有挂单修正任务，不干扰')
            else:
                self._need_fix_order = True
            await asyncio.sleep(interval_time)

    async def _dealing_partial_order(self, order_data_dict: dict) -> bool:
        """
        用于处理部分成交的订单，操作：
        如果该订单已被记录，则根据交易量判断订单是否全部完成，已完成则删除记录，未完成则更新信息
        如果未被记录，则增添记录
        :param order_data_dict: 部分成交订单的订单信息
        :return: True, 订单已全部完成，交给处理。False, 订单未全部完成，继续等待，不操作
        """
        fully_fulfilled = False

        filled_qty = int(abs(order_data_dict['quantity']))

        if order_data_dict['side'] == self.BUY:
            self._account_position_theory += filled_qty
        else:
            self._account_position_theory -= filled_qty

        partial_order_id = order_data_dict['id']
        if partial_order_id in self.partially_filled_orders.keys():

            ini_left_qty = self.partially_filled_orders[partial_order_id]

            left_qty = ini_left_qty - filled_qty
            if left_qty > 0:
                self.partially_filled_orders[partial_order_id] = left_qty
                self._log_info('订单再次部分成交!\t\t价格: {:<12}\tid: {:<10}'.format(order_data_dict['price'], partial_order_id))
                self._log_info('剩余 {} 张'.format(left_qty))
            elif left_qty == 0:
                # 订单已完成
                self.partially_filled_orders.pop(partial_order_id)
                # self.partially_orders_indices_list.remove(self.parse_id(partial_order_id)[0])

                fully_fulfilled = True
            else:
                self._log_info('error: left qty < 0, plz check code!')
                self._log_info('{} : {} = {} - {}'.format(partial_order_id, left_qty, ini_left_qty, filled_qty))
                # 在极高频的情况下，有可能会出现这种情况，比如adjusting order 维护不到位导致普通挂单数量不正常，此时也剔除该记录
                self.partially_filled_orders.pop(partial_order_id)
                # self.partially_orders_indices_list.remove(self.parse_id(partial_order_id)[0])

        else:
            left_qty = int(self.grid_each_qty) - filled_qty
            if left_qty < 0:
                self._log_info('error: got an normal order but traded quantity abnormal !')
                self._log_info('order: {}, filled qty: {}'.format(partial_order_id, filled_qty))
                return False
            self.partially_filled_orders[partial_order_id] = left_qty
            # self.partially_orders_indices_list.append(self.parse_id(partial_order_id)[0])
            # self.partially_orders_indices_list.sort()

            self._log_info('\n订单部分成交!!\t\t价格: {:<12}\tid: {:<10}'.format(order_data_dict['price'], partial_order_id))
            self._log_info('剩余 {} 张'.format(left_qty))

        return fully_fulfilled

    async def _dealing_ENTRY_ORDER(self, order_data_dict: dict) -> None:
        """
        处理入场挂单，计算挂单剩余数量，如果为0，则表示全部成交，开启网格
        :param order_data_dict:
        :return:
        """
        if self.trigger_start:
            filled_size: int = abs(order_data_dict['quantity'])  # 对于非线性做多，入场挂单为做多挂单，数量为正数，其实不需要abs
            self._ENTRY_ORDER_qty_left = self._ENTRY_ORDER_qty_left - filled_size
            if self._ENTRY_ORDER_qty_left > 0:
                self._log_info('~~~ 触发挂单部分成交 {} 张，已完成 {} %'.format(str(filled_size), round(self.filling_quantity - self._ENTRY_ORDER_qty_left) / self.filling_quantity))
            else:
                # 完全成交，开启网格
                self._log_info('\n\n~~~ 触发挂单完全成交!\n\n')

                asyncio.create_task(self._start_strategy())

                fee_dict = await self._my_executor.get_symbol_trade_fee(self.symbol_name)
                self.symbol_maker_fee = fee_dict['maker_fee']
                self.symbol_taker_fee = fee_dict['taker_fee']
                self._log_info('maker fee rate: {}'.format(self.symbol_maker_fee))
                self._log_info('taker fee rate: {}'.format(self.symbol_taker_fee))

                adding_volume = calc(calc(self.filling_quantity, self.symbol_quantity_min_step, '*'), self.entry_grid_price, '*')
                self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
                self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

                self._account_position_theory += self.filling_quantity

        else:
            self._log_info('received entry order id while not trigger start! plz check code')

    async def _dealing_MARKET_ORDER(self, order_data_dict: dict) -> None:
        """
        处理所有市价挂单，市价挂单一般分为多个部分成交收到，此处做简易处理
        :param order_data_dict:
        :return:
        """
        filled_size: int = abs(order_data_dict['quantity'])
        self._MARKET_ORDER_qty_left = self._MARKET_ORDER_qty_left - filled_size
        self._MARKET_ORDER_value = calc(self._MARKET_ORDER_value, calc(filled_size, float(order_data_dict['price']), '*'), '+')
        if self._MARKET_ORDER_qty_left > 0:
            self._log_info('\n市价请求成交中，已完成 {} %'.format(str(round((self._MARKET_ORDER_qty_target - self._MARKET_ORDER_qty_left) / self._MARKET_ORDER_qty_target * 100, 1))))
        elif self._MARKET_ORDER_qty_left == 0:
            avg_price = calc(self._MARKET_ORDER_value, self._MARKET_ORDER_qty_target, '/')
            self._log_info('\n市价挂单全部成交! 成交均价: {}\n'.format(str(avg_price)))
            # todo: 在此处更新累计统计信息
            self._MARKET_ORDER_qty_target = 0
            self._MARKET_ORDER_value = 0
        else:
            self._log_info('error: actual filled market qty over target qty, plz check code and trade status!')

    async def _dealing_adjusting_order(self, order_data_dict: dict) -> bool:
        """
        处理修正仓位的特殊挂单，保存剩余仓位修正数量
        :param order_data_dict:
        :return:
        """
        order_fully_fulfilled = False

        filled_qty: int = abs(order_data_dict['quantity'])
        self._adjusting_qty_left = self._adjusting_qty_left - filled_qty

        if self._adjusting_order_side == self.BUY:
            self._account_position_theory += filled_qty
        else:
            self._account_position_theory -= filled_qty

        if self._adjusting_qty_left == 0:
            # 结束仓位修正并维护网格
            self._log_info('\n### 修正挂单完全成交，仓位修正完成!!! ###\n')       # todo: may be too frequently to delete

            self.adjusting_index = self._pre_adjusting_index = -1
            self._adjusting_qty_target = self._adjusting_qty_left = 0
            self._need_adjust_pos = False
            order_fully_fulfilled = True

        elif self._adjusting_qty_left < 0:
            self._log_info('\n ##### 修正挂单统计有误! 剩余数量小于零')
            self._log_info('\n ##### this_qty: {}\ttarget: {}\tleft: {}'.format(filled_qty, self._adjusting_qty_target, self._adjusting_qty_left))

            # todo 暂且也如此，摆烂
            self.adjusting_index = self._pre_adjusting_index = -1
            self._adjusting_qty_target = self._adjusting_qty_left = 0
            self._need_adjust_pos = False
            order_fully_fulfilled = True

        else:
            # 仓位修正未完成
            self._log_info('### 修正挂单部分成交')
            self._log_info('### target: {}, left: {}'.format(self._adjusting_qty_target, self._adjusting_qty_left))
            self._log_info('### 修正进度:\t已完成/总数\t{}/{}'.format(str(self._adjusting_qty_target - self._adjusting_qty_left), self._adjusting_qty_target))

        return order_fully_fulfilled

    async def temp_log_thinking(self):
        """
        未完全成交导致仓位漂移，修正方法：
        增加未完全成交订单id时，对该list进行排序，每次挂单成交或驳回，c index发生变化时
        都会判断列表的头尾两个id与c index的距离，如果超过某个固定长度，则认为该订单未完全成交，需要修正该订单导致的仓位偏移
        用一个变量记录。

        维护挂单开关：每10分钟打开，
        检查仓位：每成交20挂单，打开
        修正仓位挂单：当 accum 不为0时，打开

        :return:
        """
        pass

    def _reset_functional_vars(self) -> None:
        """
        重置所有特殊功能相关变量
        :return:
        """
        # 挂单处理相关
        self._need_fix_order = False
        self.partially_filled_orders: dict[str, int] = {}
        self._cannot_check_open_orders = False

        # 仓位矫正相关
        self.adjusting_index = self._pre_adjusting_index = -1
        self._adjusting_qty_target = self._adjusting_qty_left = 0
        self._need_adjust_pos = False
        self._pre_save_acc_pos_dev = 0

        # 市价单
        self._MARKET_ORDER_qty_target = self._MARKET_ORDER_qty_left = 0
        self._MARKET_ORDER_value = 0

    def _additional_action(self) -> None:
        """
        触发器，用于启动coroutine
        :return:
        """
        asyncio.create_task(self._additional_action_task())

    async def _additional_action_task(self) -> None:
        """
        此时市场交易不剧烈，策略可以做出额外的操作，
        该方法属于半主动式策略
        功能：
            1. 如果需要修正挂单，则修正挂单

            2.1 如果存在特殊挂单，则判断特殊挂单是否离市价较近
            2.2 如果不存在特殊挂单，判断是否需要修正仓位，

        操作：
            1. 首先修正维护策略挂单
            2. 处理部分成交的挂单，偏离太远的纳入仓位偏移统计
            3. 处理仓位修正挂单

        注意：存在特殊挂单时，如果accumulated dev 因为其他原因又不为0，系统会等待adjusting order完成后，继续创建新的 adjusting order
        :return:
        """
        self._log_info('>>> ')
        if not self._is_trading:    # 因为此时有可能人工手动停止
            return
        if self._doing_delay_task:
            self._log_info('\n>>> 上锁，不重复开启延时任务')
            return
        self._doing_delay_task = True

        # 使用 try 模块避免可能的问题
        try:
            if self._need_fix_order:
                self._log_info('\n>>> switch: 检查当前挂单')
                await self._check_open_orders()       # 消耗约 100 ms
                # todo: 可以考虑分开写，使用两个延时器
                return

            if self.adjusting_index == -1:
                # 此时没有特殊挂单
                if self._need_adjust_pos:
                    self._log_info('\n>>> 需要修正仓位')
                    await self._check_position()      # 消耗约 100 ms

                    if self._accumulated_pos_deviation == 0:
                        self._log_info('### 账户实际仓位正确，不需要修正\n')
                        self._need_adjust_pos = False
                    else:
                        if self._accumulated_pos_deviation > 0:
                            # 需要增加买 1 挂单数量以修正仓位

                            if len(self.open_buy_orders) == 0:
                                # 由于该策略一般不会出现缺少卖挂单的情况，因此不判断卖挂单
                                self._log_info('### 当前无买挂单用于修正仓位')
                                if self.current_symbol_price <= self.present_bottom_index:
                                    self._log_info('### 价格低于下区间，市价修正仓位')
                                    asyncio.create_task(self._post_market_order(self.BUY, self._accumulated_pos_deviation))
                                    self._accumulated_pos_deviation = 0
                                else:
                                    self._log_info('### 等待下一回合修正')

                            else:
                                self._log_info('### 修正买1单')     # todo: test print to delete, 该输出过于频繁
                                adjusting_id = self.open_buy_orders[-1]['id']      # 买 1 订单
                                self.adjusting_index = self.parse_id(adjusting_id)[0]
                                self._adjusting_order_side = self.BUY
                                if adjusting_id in self.partially_filled_orders.keys():
                                    self._log_info('### 罕见: 部分成交挂单作为仓位修正挂单')
                                    self._adjusting_qty_target = self._adjusting_qty_left = int(self.partially_filled_orders[adjusting_id]) + int(self._accumulated_pos_deviation)
                                    self._log_info('\n>>> 设定修正买单数量 {} 张, id: {}'.format(self._adjusting_qty_target, adjusting_id))
                                    # 此后该部分成交挂单就交给特殊仓位修正挂单功能处理
                                    self.partially_filled_orders.pop(adjusting_id)
                                    # self.partially_orders_indices_list.remove(self.adjusting_index)
                                else:
                                    self._adjusting_qty_target = self._adjusting_qty_left = int(self.grid_each_qty) + int(self._accumulated_pos_deviation)
                                    self._log_info('\n>>> 设定修正买单数量 {} 张, id: {}'.format(self._adjusting_qty_target, adjusting_id))

                                adjusting_order = Token.ORDER_INFO.copy()
                                adjusting_order['symbol'] = self.symbol_name
                                adjusting_order['id'] = self.open_buy_orders[-1]['id']
                                adjusting_order['quantity'] = self._adjusting_qty_target
                                # 规零相关统计数据
                                self._pre_save_acc_pos_dev = self._accumulated_pos_deviation
                                self._accumulated_pos_deviation = 0
                                asyncio.create_task(self.command_transmitter(trans_command=adjusting_order, token=Token.AMEND_POC_QTY))
                        else:
                            # 需要增加卖 1 挂单数量以修正仓位
                            if len(self.open_sell_orders) == 0:
                                self._log_info('### 当前无卖挂单，等待下一回合')
                                return

                            self._log_info('### 修正卖1单')     # todo: test print to delete, 该输出过于频繁
                            adjusting_id = self.open_sell_orders[0]['id']     # 卖 1 订单
                            self.adjusting_index = self.parse_id(adjusting_id)[0]
                            self._adjusting_order_side = self.SELL
                            if adjusting_id in self.partially_filled_orders.keys():
                                self._log_info('### 罕见: 部分成交挂单作为仓位修正挂单')
                                self._adjusting_qty_target = self._adjusting_qty_left = int(self.partially_filled_orders[adjusting_id]) + int(abs(self._accumulated_pos_deviation))
                                self._log_info('\n>>> 设定修正卖单数量 {} 张, id: {}'.format(self._adjusting_qty_target, adjusting_id))
                                # 此后该部分成交挂单就交给特殊仓位修正挂单功能处理
                                self.partially_filled_orders.pop(adjusting_id)
                                # self.partially_orders_indices_list.remove(self.adjusting_index)
                            else:
                                self._adjusting_qty_target = self._adjusting_qty_left = int(self.grid_each_qty) + int(abs(self._accumulated_pos_deviation))
                                self._log_info('\n>>> 设定修正卖单数量 {} 张, id: {}'.format(self._adjusting_qty_target, adjusting_id))

                            adjusting_order = Token.ORDER_INFO.copy()
                            adjusting_order['symbol'] = self.symbol_name
                            adjusting_order['id'] = self.open_sell_orders[0]['id']
                            adjusting_order['quantity'] = -self._adjusting_qty_target
                            # 注意修改订单数量比较特殊，需要提供带符号的数量
                            self._pre_save_acc_pos_dev = self._accumulated_pos_deviation
                            self._accumulated_pos_deviation = 0
                            asyncio.create_task(self.command_transmitter(trans_command=adjusting_order, token=Token.AMEND_POC_QTY))

                else:
                    # status all good
                    # self._log_info('\n>>> 仓位状态正常')
                    pass

            else:
                self._log_info('\n>>> 检查特殊挂单')
                if abs(self.critical_index - self.adjusting_index) > min(10, self.min_buy_order_num, self.min_sell_order_num):        # todo: 测试市场，偏离10是否合理
                    self._log_info('### 修正挂单距离遥远，二次修正，请注意套利收益!')
                    if self.adjusting_index < self.critical_index:
                        self._log_info('### 再次修正买1单')
                        # 操作：将原有的adjusting index挂单撤销并重新挂网格单，然后修改现有买1单数量
                        if len(self.open_buy_orders) == 0:
                            self._log_info('### 无买单，取消修正')
                            return
                        self._pre_adjusting_index = self.adjusting_index

                        cancel_cmd = Token.ORDER_INFO.copy()
                        cancel_cmd['symbol'] = self.symbol_name
                        cancel_cmd['id'] = self.gen_id(self.adjusting_index, self.BUY)

                        asyncio.create_task(self.command_transmitter(trans_command=cancel_cmd, token=Token.TO_CANCEL))

                        re_adjusting_id = self.open_buy_orders[-1]['id']
                        self.adjusting_index = self.parse_id(re_adjusting_id)[0]

                        self._log_info('\n>>> 再次修正，设定修正买单数量 {} 张, id: {}'.format(self._adjusting_qty_left, re_adjusting_id))

                        adjust_order = Token.ORDER_INFO.copy()
                        adjust_order['symbol'] = self.symbol_name
                        adjust_order['id'] = self.open_buy_orders[-1]['id']
                        adjust_order['quantity'] = self._adjusting_qty_left

                        asyncio.create_task(self.command_transmitter(trans_command=adjust_order, token=Token.AMEND_POC_QTY))
                        # 撤销挂单以后，等待300ms再贴新挂单，策略提供了该时间空余
                        time.sleep(0.3)
                        repair_order = Token.ORDER_INFO.copy()
                        repair_order['symbol'] = self.symbol_name
                        repair_order['id'] = self.gen_id(self._pre_adjusting_index, self.BUY)
                        repair_order['price'] = self.all_grid_price[self._pre_adjusting_index]
                        repair_order['side'] = self.BUY
                        repair_order['quantity'] = self.grid_each_qty

                        asyncio.create_task(self.command_transmitter(trans_command=repair_order, token=Token.TO_POST_POC))
                    else:
                        self._log_info('### 再次修正卖1单')
                        if len(self.open_buy_orders) == 0:
                            self._log_info('### 无卖单，取消修正')
                            return
                        self._pre_adjusting_index = self.adjusting_index
                        cancel_cmd = Token.ORDER_INFO.copy()
                        cancel_cmd['symbol'] = self.symbol_name
                        cancel_cmd['id'] = self.gen_id(self.adjusting_index, self.SELL)

                        asyncio.create_task(self.command_transmitter(trans_command=cancel_cmd, token=Token.TO_CANCEL))

                        re_adjusting_id = self.open_sell_orders[0]['id']
                        self.adjusting_index = self.parse_id(re_adjusting_id)[0]

                        self._log_info('\n>>> 再次修正，设定修正卖单数量 {} 张, id: {}'.format(self._adjusting_qty_left, re_adjusting_id))

                        adjust_order = Token.ORDER_INFO.copy()
                        adjust_order['symbol'] = self.symbol_name
                        adjust_order['id'] = self.open_sell_orders[0]['id']
                        adjust_order['quantity'] = -self._adjusting_qty_left

                        asyncio.create_task(self.command_transmitter(trans_command=adjust_order, token=Token.AMEND_POC_QTY))

                        time.sleep(0.3)
                        repair_order = Token.ORDER_INFO.copy()
                        repair_order['symbol'] = self.symbol_name
                        repair_order['id'] = self.gen_id(self._pre_adjusting_index, self.SELL)
                        repair_order['price'] = self.all_grid_price[self._pre_adjusting_index]
                        repair_order['side'] = self.SELL
                        repair_order['quantity'] = self.grid_each_qty

                        asyncio.create_task(self.command_transmitter(trans_command=repair_order, token=Token.TO_POST_POC))
                else:
                    # adjusting order status okay
                    self._log_info('\n>>> 特殊挂单状态正常，距离 {}'.format(abs(self.critical_index - self.adjusting_index)))
                    pass

        finally:
            self._doing_delay_task = False

    # interaction methods
    async def report_receiver(self, recv_data_dict: dict, append_info: str = None) -> None:

        # 由于更新订单通道，现在部分成交将会被拆分收到信息
        if recv_data_dict['status'] == Token.ORDER_FILLED:
            # 收到策略订单id，根据订单类别，分别处理
            order_index, order_side = self.parse_id(recv_data_dict['id'])

            if order_index == self.ENTRY_ORDER_ID:
                await self._dealing_ENTRY_ORDER(recv_data_dict)

            elif order_index == self.MARKET_ORDER_ID:
                await self._dealing_MARKET_ORDER(recv_data_dict)

            elif order_index == self.adjusting_index:
                # 核心功能：仓位修复策略
                order_fulfilled = await self._dealing_adjusting_order(recv_data_dict)
                if order_fulfilled:
                    await self._maintain_grid_order(order_index, order_side, recv_data_dict['id'], append_info, order_filled=True)

            else:
                # 其他订单，维护网格
                order_qty: int = abs(recv_data_dict['quantity'])
                if order_qty == self.grid_each_qty:
                    if order_side == self.BUY:
                        self._account_position_theory += int(self.grid_each_qty)
                    else:
                        self._account_position_theory -= int(self.grid_each_qty)
                    await self._maintain_grid_order(order_index, order_side, recv_data_dict['id'], append_info, order_filled=True)
                else:
                    order_fulfilled = await self._dealing_partial_order(recv_data_dict)
                    if order_fulfilled:
                        await self._maintain_grid_order(order_index, order_side, recv_data_dict['id'], append_info, order_filled=True)

        elif recv_data_dict['status'] == Token.POST_SUCCESS:
            self._log_info('收到挂单成功信息\t\t价格: {:<12}\tid: {:<10}'.format(str(float(recv_data_dict['price'])), recv_data_dict['id']))

        elif recv_data_dict['status'] == Token.POC_SUCCESS:
            self._log_info('收到poc挂单成功信息\t\t价格: {:<12}\tid: {:<10}'.format(str(float(recv_data_dict['price'])), recv_data_dict['id']))

        elif recv_data_dict['status'] == Token.CANCEL_SUCCESS:
            self._log_info('收到撤单成功信息\t\t\t\tid: {:<10}'.format(recv_data_dict['id']))

        elif recv_data_dict['status'] == Token.CANCEL_POC_SUCCESS:
            self._log_info('收到poc撤单成功信息\t\t\t\tid: {:<10}'.format(recv_data_dict['id']))

        elif recv_data_dict['status'] == Token.PARTIALLY_FILLED:
            self._log_info('\nerror: invalid info received, plz check code\n')

        elif recv_data_dict['status'] == Token.ORDER_UPDATE:
            # 目前在该策略逻辑中，只有一种更新订单的情况即修改买1卖1订单的数量，其他的id都是部分成交，已由其他通道处理
            if self.adjusting_index == -1:
                pass
            else:
                order_index, order_side = self.parse_id(recv_data_dict['id'])
                if order_index == self.adjusting_index:
                    self._log_info(('调仓订单修改成功~\t\t价格: {:<12}\tid: {:<10}'.format(str(float(recv_data_dict['price'])), recv_data_dict['id'])))
                else:
                    pass

        elif recv_data_dict['status'] == Token.UNIDENTIFIED:
            pass
        elif recv_data_dict['status'] == Token.FAILED:
            pass
        elif recv_data_dict['status'] == Token.POST_FAILED:
            self._log_info('\n限价挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            self._log_info('失败信息: {}'.format(append_info))

        elif recv_data_dict['status'] == Token.POC_FAILED:
            self._log_info('\npoc挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            self._log_info('失败信息: {}'.format(append_info))

        elif recv_data_dict['status'] == Token.POC_REJECTED:
            # self._log_info('\npoc挂单失败，价格错位\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            self._log_info('\npoc挂单失败，价格错位\t\t系统时间 {}'.format(str(pd.to_datetime(self.gen_timestamp(), unit='ms') + pd.Timedelta(hours=8))))
            this_order_index, side = self.parse_id(recv_data_dict['id'])
            if side == self.BUY:
                self._accumulated_pos_deviation += self.grid_each_qty
            else:
                self._accumulated_pos_deviation -= self.grid_each_qty
            await self._maintain_grid_order(this_order_index, side, recv_data_dict['id'], append_info, order_filled=False)

        elif recv_data_dict['status'] == Token.CANCEL_FAILED:
            self._log_info('\n撤销挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            if append_info:
                self._log_info(append_info)

        elif recv_data_dict['status'] == Token.AMEND_POC_FAILED:
            if self.adjusting_index != -1:
                # todo: 此处失败原因：修改盘口挂单时，刚刚发送挂单请求，或者刚刚挂单成交，立马尝试修正
                if self._pre_adjusting_index == -1:
                    # 第一次修正挂单
                    self._log_info('\n##### 添加修正挂单失败 ##### 失败信息:')
                    self._log_info(append_info)
                    self._log_info('c index: {}\t a index: {}'.format(self.critical_index, self.adjusting_index))
                    self.adjusting_index = -1
                    # 使用加号，防止在请求期间存在其他的仓位偏移来源
                    self._accumulated_pos_deviation += self._pre_save_acc_pos_dev
                else:
                    self._log_info('\n##### 修改修正仓位挂单失败 ##### 失败信息:')
                    self._log_info(append_info)
                    self._log_info('c index: {}\t a index: {}\tpre a index: {}'.format(self.critical_index, self.adjusting_index, self._pre_adjusting_index))
                    # todo: 暂时先摆烂，尽量通过优化避免这种情况的出现
                    # self.adjusting_index = self._pre_adjusting_index
                    self.adjusting_index = self._pre_adjusting_index = -1

        elif recv_data_dict['status'] == Token.TEMP_TOKEN:
            pass

    async def command_transmitter(self, trans_command: dict = None, token: str = None) -> None:
        command_dict = Token.ORDER_INFO.copy()
        command_dict['symbol'] = self.symbol_name

        if token == Token.TO_POST_LIMIT:
            # todo: 是否有点冗余
            command_dict['id'] = trans_command['id']
            command_dict['price'] = trans_command['price']
            command_dict['side'] = trans_command['side']
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self._my_executor.command_receiver(command_dict))
        elif token == Token.TO_POST_POC:
            # todo: 需要将所有统一起来，目前只有此处修改，需要全局更改
            command_dict['id'] = trans_command['id']
            command_dict['price'] = trans_command['price']
            command_dict['side'] = trans_command['side']
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self._my_executor.command_receiver(command_dict))
        elif token == Token.TO_CANCEL:
            command_dict['id'] = trans_command['id']
            command_dict['status'] = token
            asyncio.create_task(self._my_executor.command_receiver(command_dict))
        elif token == Token.TO_POST_BATCH:
            asyncio.create_task(self._my_executor.command_receiver(trans_command))
        elif token == Token.TO_POST_BATCH_POC:
            asyncio.create_task(self._my_executor.command_receiver(trans_command))
        elif token == Token.TO_POST_MARKET:
            command_dict['side'] = trans_command['side']
            command_dict['id'] = self.gen_id(self.MARKET_ORDER_ID, trans_command['side'])
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self._my_executor.command_receiver(command_dict))
        elif token == Token.AMEND_POC_PRICE:
            command_dict['id'] = trans_command['id']
            command_dict['price'] = trans_command['price']
            command_dict['status'] = token
            asyncio.create_task(self._my_executor.command_receiver(command_dict))
        elif token == Token.AMEND_POC_QTY:
            command_dict['id'] = trans_command['id']
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self._my_executor.command_receiver(command_dict))
        elif token == Token.CANCEL_ALL:
            command_dict['status'] = token
            asyncio.create_task(self._my_executor.command_receiver(command_dict))
        elif token == Token.CLOSE_POSITION:
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self._my_executor.command_receiver(command_dict))
        elif token == Token.TEMP_TOKEN:
            command_dict['status'] = token
            asyncio.create_task(self._my_executor.command_receiver(command_dict))
        elif token is None:
            self._log_info('未定义命令类型，不发送')
        else:
            self._log_info('错误定义命令类型，不发送')

    async def ticker_receiver(self, recv_ticker_data: dict) -> None:
        """
        接受合约ticker数据 ♥
        盘口交易剧烈时，每1s收到一个ticker数据，
        盘口冷淡时，ticker数据时间间隔常常在2s及以上
        因此可以作为市场不活跃，可以额外操作的判断依据
        todo: 需要额外判断以防万一，一系列ticker价格中，偏差不超过网格价差，可以做出额外操作。以目前的ticker data来看，暂时不需要

        额外操作：
            1.维护挂单，每隔一段时间开启维护挂单需求
            2.修正仓位，每达成一定挂单成交数量，开启仓位修正需求
        :param recv_ticker_data:
        :return:
        """
        # 一般来说在策略开始前就已经在收听实时价格信息，因此已经更新一段时间
        self.previous_price = self.current_symbol_price
        self.current_symbol_price = recv_ticker_data['price']

        if self._is_trading:
            # 策略还在运行时，检查最新价格是否偏离过大，todo: 是否占用过多资源，暂时先这么用
            if self.all_grid_price[self.present_bottom_index] < self.current_symbol_price < self._x_grid_up_limit:
                # 新检测方法
                if self.critical_index >= 1:
                    if abs(calc(self.current_symbol_price, self.all_grid_price[self.critical_index], '-')) > \
                            5 * calc(self.all_grid_price[self.critical_index], self.all_grid_price[self.critical_index - 1], '-'):
                        self._log_info('$$$ 检测到价格偏离，未收到挂单成交信息')
                        self._log_info('$$$ 当前ticker价: {}\t\t网格critical价: {}'.format(self.current_symbol_price, self.all_grid_price[self.critical_index]))
                        self._need_fix_order = True

            elif self.current_symbol_price > self._x_grid_up_limit:
                self._log_info('检测到价格超出上边界!需要终止策略')
                asyncio.create_task(self._terminate_trading(reason='达到网格上边界'))

            # 添加价格维护，构造冗余
            await self._maintainer_by_price()

            # 如果订单成交迅速，ticker收信为 1s，判断也比较频繁
            if self._accumulated_pos_deviation != 0:
                self._need_adjust_pos = True

            # === 核心功能 === # 超过某个固定时间仍未收到ticker信息，则此时交易不剧烈，可以做额外操作
            if self._ticker_delay_timer:
                self._ticker_delay_timer.cancel()
            self._ticker_delay_timer = self._running_loop.call_later(self._ticker_delay_trigger_time, self._additional_action)

        # if self.developer_switch:
        #     self._reset_functional_vars()
        #     self.developer_switch = False
        #     self._log_info('\n!!! 重置相关任务变量 !!!\n')

    # tool methods
    def gen_id(self, self_index: int, side: str) -> str:
        self_id = self.stg_num + '_' + str.zfill(str(self_index), 8) + side
        return self_id

    @staticmethod
    def parse_id(client_id: str) -> tuple[int, str]:
        internal_client_id = client_id.split('_')[-1]
        try:
            order_index = int(internal_client_id[:8])
            order_side = internal_client_id[8:]
        except ValueError:
            order_index = -1
            order_side = client_id

        return order_index, order_side

    @staticmethod
    def unmatched_profit_calc(initial_index: int, current_index: int, all_prices: tuple[float | int], each_grid_qty: float,
                              init_pos_price: float, init_pos_qty: float, current_price: float) -> float:
        """
        新式便携计算器，可以计算超出区间的网格未配对盈亏
        该方法也能够用于计算非线性网格!
        :param initial_index: 初始的index
        :param current_index: 网格当前的index
        :param all_prices: 网格所有价格
        :param each_grid_qty: 每格数量，真实数量
        :param init_pos_price: 初始仓位价格
        :param init_pos_qty: 初始仓位数量，真实绝对数量，大于0代表买多，小于0做空
        :param current_price: 当前最新价格
        :return: 返回盈亏 和 平均持仓价格
        """
        if initial_index == -1:
            initial_index = len(all_prices) - 1
        if current_index == -1:
            current_index = len(all_prices) - 1

        part_1 = calc(calc(current_price, init_pos_price, '-'), init_pos_qty, '*')
        if current_index > initial_index + 1:
            price_slice = all_prices[initial_index + 1:current_index]
        elif current_index < initial_index - 1:
            price_slice = all_prices[current_index + 1:initial_index]
        else:
            price_slice = []

        part_2 = calc(-abs(calc(calc_sum(price_slice), calc(len(price_slice), current_price, '*'), '-')), each_grid_qty, '*')

        return calc(part_1, part_2, '+')

    def nonlinear_grid_price_calc(self, min_grid_step: float, max_grid_step: float, top_start_price: float,
                                  lower_price_limit: float, alpha: float) -> tuple[float | int]:
        """
        非线性网格价格计算器，计算下方缓冲区域的所有价格，间距增长使用幂函数
        计算思路：

            网格间距增量是从0到最大间距的一系列值，其分布符合幂函数
            将所有间距做离散函数积分，再加上基础网格距离，得到的总长度之和正好小于下方价差，即是需要的结果
            正好等于的过程中就定义了下方网格数量

        返回下方的所有网格价格
        :param min_grid_step: 套利网格价格
        :param max_grid_step: 最大网格间距
        :param top_start_price: 从这个价格开始使用非线性网格
        :param lower_price_limit: 策略下方价格界限
        :param alpha: 幂函数幂次项
        :return:
        """
        max_step_diff = calc(max_grid_step, min_grid_step, '-')

        avg_step_diff = max_step_diff / (1 + alpha)
        # 以理论计算的平均网格间距作为网格数量
        N_grids = int(lower_price_limit / avg_step_diff) if self.N_save == 0 else self.N_save
        iteration_time = 1
        while True:
            sum_grid_diffs, all_grid_diffs = self.discrete_integral(alpha, N_grids, max_step_diff)
            # sum_grid_steps = calc(calc(min_grid_step, N_grids, '*'), sum_grid_diffs, '+')
            sum_grid_steps = min_grid_step * N_grids + sum_grid_diffs
            # print(sum_grid_diffs, N_grids)

            if sum_grid_steps <= lower_price_limit < calc(sum_grid_steps, max_grid_step, '+'):
                # print(all_grid_diffs)
                print('iteration times: {}'.format(iteration_time))
                all_grid_steps = [calc(min_grid_step, each_price_diff, '+') for each_price_diff in all_grid_diffs]
                all_lower_prices = []
                each_price = top_start_price
                for each_grid_step in all_grid_steps:
                    each_price = calc(each_price, each_grid_step, '-')
                    all_lower_prices.append(each_price)
                return tuple(reversed(all_lower_prices))
                break
            else:
                if sum_grid_steps > lower_price_limit:
                    N_grids -= 1
                else:
                    N_grids += 1
                iteration_time += 1

            # for safety
            if iteration_time > 100000:
                raise ValueError('iteration times up to limit!!!')

    def discrete_integral(self, alpha: float, N: int, max_diff: float) -> tuple[float, list]:
        """
        转为本策略打造的幂函数离散积分计算器，区间给定 0-1, 从 1/N 到 1, 共 N 个数值
        :param alpha: 幂次项
        :param N: 离散点个数
        :param max_diff: 最大网格间距差
        :return: 返回规整好的总和，和所有网格差
        """

        x_series = np.linspace(1 / N, 1, N)
        all_diffs = np.power(x_series, alpha) * max_diff
        for index, _ in enumerate(all_diffs):
            all_diffs[index] = self.round_step_precision(all_diffs[index], self.symbol_price_min_step)
        # 这里的求和可能仍然存在精度问题，不过无关紧要
        # print(all_diffs)
        return float(np.sum(all_diffs)), list(all_diffs)

    @staticmethod
    def round_step_precision(price: float, step: float) -> float:
        """
        专门为该策略打造的四舍五入规整精度方法，只考虑大于0的情况
        :param price:
        :param step:
        :return:
        """
        price = Decimal(str(price))
        step = Decimal(str(step))
        mod = price % step
        if mod > step / 2:
            return float(price - mod + step)
        else:
            return float(price - mod)

    @staticmethod
    def gen_timestamp():
        return int(round(time.time() * 1000))

    def __del__(self):
        print('\n{}: {} nonlinear stair grid analyzer 实例被删除，释放资源\n'.format(self.stg_num, self.symbol_name))
        pass
