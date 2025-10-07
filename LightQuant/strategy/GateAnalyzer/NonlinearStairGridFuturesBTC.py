# -*- coding: utf-8 -*-
# @Time : 2023/7/21 10:35
# @Author : 
# @File : NonlinearStairGridFuturesBTC.py
# @Software: PyCharm
import time
import asyncio
import numpy as np
import pandas as pd
from decimal import Decimal
from LightQuant.Recorder import LogRecorder
from LightQuant.tools.calc import calc, calc_sum
from LightQuant.tools.round_step_size import round_step_size
from LightQuant.Analyzer import Analyzer
from LightQuant.Executor import Executor
from LightQuant.protocols.BinanceToken import BinanceToken as Token


class NonlinearStairGridAnalyzerFuturesBTC(Analyzer):
    """
    自动补仓看多网格的升级版，下方网格间距非线性增加
    BTC专用版，包含完整附加功能：
    1.定时修正挂单
    2.可选挂单触发入场
    3.检测仓位偏移
    4.maker市价单功能(暂时关闭)
    """

    STG_NAME = '非线性智能调仓'

    BUY: str = 'BUY'
    SELL: str = 'SELL'

    MAKER_MARKET_ID = 99999997  # 调整仓位时使用的id
    MAKER_FILLING_ID = 99999998  # 补仓时使用的id，该订单要求价格不能偏移过多
    MARKET_ORDER_ID = 99999999  # 市价下单的id，taker成交

    ENTRY_ORDER_ID = 99999996  # 触发挂单id

    param_dict: dict = {
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
        # self.symbol_min_order_qty = None
        # 手续费
        self.symbol_maker_fee = 0
        self.symbol_taker_fee = 0

        # ==================== 策略功能相关变量 ==================== #
        self._pre_update_text_task: asyncio.coroutine = None

        self.critical_index = 0
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

        # 临时增加：partially filled 订单处理
        self.partially_filled_orders: dict[str, int] = {}
        # {'id': int}   order_id, left_quantity

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

        # 入场触发挂单剩余数量
        self._ENTRY_ORDER_qty_left = 0

        # beta test function
        # noinspection PyTypeChecker
        self._delay_action: asyncio.TimerHandle = None

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
        self._market_locker_task: asyncio.coroutine = None
        self._fix_position_task: asyncio.coroutine = None

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

    async def validate_param(self, input_params: dict) -> dict:
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

            if self._x_grid_up_limit <= self.current_symbol_price:
                self._x_grid_up_limit = str(self._x_grid_up_limit) + '当前价高于上界'
                param_valid = False
            else:
                self._x_grid_up_limit = round_step_size(self._x_grid_up_limit, self.symbol_price_min_step)

            if param_valid:
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
                if self.trigger_start:
                    if self._x_lower_buffer_price_limit + self._x_lower_price_step >= self.trigger_price:
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
        percentage_prices = [round_step_size(calc(virtual_current_price, 0.95, '*'), self.symbol_price_min_step), round_step_size(calc(virtual_current_price, 0.9, '*'), self.symbol_price_min_step),
                             round_step_size(calc(virtual_current_price, 0.8, '*'), self.symbol_price_min_step), round_step_size(calc(virtual_current_price, 0.7, '*'), self.symbol_price_min_step)]
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
        tmp_prices = list(reversed(self.all_grid_price))[:-1]       # 按顺序递减的价格
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

    def derive_functional_variables(self) -> None:
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
        else:
            high_price = calc(self._x_grid_up_limit, round_step_size(calc(self._x_grid_up_limit, self.current_symbol_price, '-'), self.grid_price_step), '-')
            low_price = calc(high_price, self.grid_price_step, '-')
            if high_price - self.current_symbol_price <= self.grid_price_step / 2:
                self.entry_grid_price = high_price
            else:
                self.entry_grid_price = low_price

        # print(self.entry_grid_price)
        self.lower_step_price = calc(self.entry_grid_price, self._x_lower_price_step, '-')
        self.up_grid_num = int(calc(calc(self._x_grid_up_limit, self.entry_grid_price, '-'), self.grid_price_step, '/')) + 1
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
            self._current_valid_position = calc((self.max_index - self.critical_index), self.grid_each_qty, '*')

        if self._current_valid_position < 0:
            raise ValueError('仓位小于0，不合逻辑!!!')

    def acquire_token(self, stg_code: str) -> None:
        # todo: 考虑添加至基类
        self.stg_num = stg_code
        self.stg_num_len = len(stg_code)

    def stop(self) -> None:
        if self._is_waiting:

            self._log_info('~~~ 停止触发等待\n')
            self._pre_update_text_task.cancel()

            maker_order = Token.ORDER_INFO.copy()
            maker_order['symbol'] = self.symbol_name
            maker_order['id'] = self.gen_id(self.ENTRY_ORDER_ID, self.BUY)
            asyncio.create_task(self.command_transmitter(trans_command=maker_order, token=Token.TO_CANCEL))

            self._my_logger.close_file()

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
        self._log_info('非线性智能调仓网格策略开始')

        if self.symbol_orders_limit_num == 30:
            self._log_info('\n*** ================================= ***\n')
            self._log_info('请注意该合约挂单数量限制为 30 ! \n已自动减少缓冲网格数量，请留意交易情况!')
            self._log_info('\n*** ================================= ***\n')
            self.min_buy_order_num, self.max_buy_order_num = 6, 12
            self.min_sell_order_num, self.max_sell_order_num = 6, 12
            self.buffer_buy_num, self.buffer_sell_num = 3, 3
        elif self.symbol_orders_limit_num == 50:
            self._log_info('\n*** ================================= ***\n')
            self._log_info('请注意该合约挂单数量限制为 30 ! \n已自动减少缓冲网格数量，请留意交易情况!')
            self._log_info('\n*** ================================= ***\n')
            self.min_buy_order_num, self.max_buy_order_num = 10, 20
            self.min_sell_order_num, self.max_sell_order_num = 10, 20
            self.buffer_buy_num, self.buffer_sell_num = 5, 5

        if self.trigger_start:
            self._pre_update_text_task.cancel()
        else:
            fee_dict = await self._my_executor.get_symbol_trade_fee(self.symbol_name)
            self.symbol_maker_fee = fee_dict['maker_fee']
            self.symbol_taker_fee = fee_dict['taker_fee']
            self._log_info('maker fee rate: {}'.format(self.symbol_maker_fee))
            self._log_info('taker fee rate: {}'.format(self.symbol_taker_fee))

        self._update_text_task = asyncio.create_task(self._update_detail_info(interval_time=3))

        # try:
        #     self._init_account_position = await self._my_executor.get_symbol_position(self.symbol_name)
        # except Exception as e:
        #     self._log_info('获取账户仓位出错!!!')
        #     self._log_info(str(e))
        #     self._log_info(str(type(e)))
        #     self._init_account_position = 0
        #
        # self._log_info('策略前账户仓位: {} 张'.format(self._init_account_position))
        # self._account_position_theory = self._init_account_position
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

        # 1. 设置初始 maker 市价买入数量
        if not self.trigger_start:
            # self._target_maker_side = self.BUY
            # self._target_maker_quantity = self.filling_quantity
            # self._maker_market_switch_on = True
            command = Token.ORDER_INFO.copy()
            command['side'] = self.BUY
            command['quantity'] = self.filling_quantity
            self._log_info('市价下单 {} 张'.format(self.filling_quantity))
            await self.command_transmitter(trans_command=command, token=Token.TO_POST_MARKET)

            self._account_position_theory += self.filling_quantity

            adding_volume = calc(calc(self.filling_quantity, self.symbol_quantity_min_step, '*'), self.current_symbol_price, '*')
            self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
            self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_taker_fee, '*'), '+')

        # 2. 开始撒网
        asyncio.create_task(self._layout_net())

        # 3. 开启维护挂单任务
        self._fix_order_task = asyncio.create_task(self._order_fixer(interval_time=600))

    # strategy methods
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

        # print(calc(self.present_step_up_price, self.filling_price_step, '+'))
        # self.present_step_up_price = self.all_grid_price[self.present_step_up_index]
        self.present_step_up_price = calc(self.present_step_up_price, self.filling_price_step, '+')  # 因为有可能超出上边界，此时该价格没有记录
        self.lower_step_price = self.all_grid_price[self.present_low_step_index]
        # print(self.present_step_up_price)

    async def _maker_market_post(self) -> None:
        """
        根据已经设置的一些参数，实现maker市价单功能，发送信息部分

        操作：

            1. 如果存在已有挂单，且价格远离期望，则修改现有挂单价格
                如果修改失败，则根据下一轮最新价，继续修改 todo: to this
            2. 如果存在已有挂单，而价格不变，则不操作
            3. 如果没有挂单，则在最新价格附近挂单

        :return:
        """

        price_step = self.symbol_price_min_step
        if self._exist_market_poc_order:
            if self.current_symbol_price == self.previous_price:
                # 价格相等，等待成交，不操作
                self._log_info('=== 价格 {} 不变，等待吃单'.format(self.current_symbol_price))
                pass
            else:
                if self._target_maker_side == self.BUY and self.current_symbol_price > self.previous_price:
                    self._log_info('=== 价格上漂，修改订单追多')
                    new_price = calc(self.current_symbol_price, price_step, '-')
                    self._log_info('=== 当前最新价格:\t{}'.format(self.current_symbol_price))
                    self._log_info('=== 修改订单价格:\t{}'.format(new_price))

                    amend_order = Token.ORDER_INFO.copy()
                    amend_order['symbol'] = self.symbol_name
                    amend_order['id'] = self.gen_id(self.MAKER_MARKET_ID, self._target_maker_side)
                    amend_order['price'] = new_price
                    self._posted_change_poc_order = True
                    await self.command_transmitter(trans_command=amend_order, token=Token.AMEND_POC_PRICE)
                elif self._target_maker_side == self.SELL and self.current_symbol_price < self.previous_price:
                    self._log_info('=== 价格下落，修改订单追空')
                    new_price = calc(self.current_symbol_price, price_step, '+')
                    self._log_info('=== 当前最新价格:\t{}'.format(self.current_symbol_price))
                    self._log_info('=== 修改订单价格:\t{}'.format(new_price))

                    amend_order = Token.ORDER_INFO.copy()
                    amend_order['symbol'] = self.symbol_name
                    amend_order['id'] = self.gen_id(self.MAKER_MARKET_ID, self._target_maker_side)
                    amend_order['price'] = new_price
                    self._posted_change_poc_order = True
                    await self.command_transmitter(trans_command=amend_order, token=Token.AMEND_POC_PRICE)
                elif self._target_maker_side == self.BUY and self.current_symbol_price == calc(self.previous_price, price_step, '-'):
                    self._log_info('=== 买挂单正在成交中')
                elif self._target_maker_side == self.SELL and self.current_symbol_price == calc(self.previous_price, price_step, '+'):
                    self._log_info('=== 卖挂单正在成交中')
                else:
                    # 此时也要修改挂单，因为存在修改挂单失败的情况
                    self._log_info('=== 价格吃回挂单价，不合理, current_price = {}\tprevious_price = {}'.format(self.current_symbol_price, self.previous_price))
                    # self._exist_market_poc_order = False
                    # self._log_info('=== 动态测试')
                    # return
                    if self._target_maker_side == self.BUY:
                        self._log_info('=== 价格变化，修改多单')
                        new_price = calc(self.current_symbol_price, price_step, '-')
                        self._log_info('=== 当前最新价格:\t{}'.format(self.current_symbol_price))
                        self._log_info('=== 修改订单价格:\t{}'.format(new_price))

                        amend_order = Token.ORDER_INFO.copy()
                        amend_order['symbol'] = self.symbol_name
                        amend_order['id'] = self.gen_id(self.MAKER_MARKET_ID, self._target_maker_side)
                        amend_order['price'] = new_price
                        self._posted_change_poc_order = True
                        await self.command_transmitter(trans_command=amend_order, token=Token.AMEND_POC_PRICE)
                    elif self._target_maker_side == self.SELL:
                        self._log_info('=== 价格变化，修改空单')
                        new_price = calc(self.current_symbol_price, price_step, '+')
                        self._log_info('=== 当前最新价格:\t{}'.format(self.current_symbol_price))
                        self._log_info('=== 修改订单价格:\t{}'.format(new_price))

                        amend_order = Token.ORDER_INFO.copy()
                        amend_order['symbol'] = self.symbol_name
                        amend_order['id'] = self.gen_id(self.MAKER_MARKET_ID, self._target_maker_side)
                        amend_order['price'] = new_price
                        self._posted_change_poc_order = True
                        await self.command_transmitter(trans_command=amend_order, token=Token.AMEND_POC_PRICE)

        else:
            # 不存在挂单，在最新价挂单
            if self._target_maker_side == self.BUY:
                post_price = calc(self.current_symbol_price, self.symbol_price_min_step, '-')
            elif self._target_maker_side == self.SELL:
                post_price = calc(self.current_symbol_price, self.symbol_price_min_step, '+')
            else:
                self._log_info('poc post side not defined!')
                post_price = 0

            maker_order = Token.ORDER_INFO.copy()
            maker_order['symbol'] = self.symbol_name
            maker_order['id'] = self.gen_id(self.MAKER_MARKET_ID, self._target_maker_side)
            maker_order['price'] = post_price
            maker_order['side'] = self._target_maker_side
            maker_order['quantity'] = self._target_maker_quantity
            self._log_info('\n\n=== maker市价下单')
            self._log_info('=== 下单时合约价格:\t{}'.format(self.current_symbol_price))
            self._log_info('=== 下单价格:\t\t{}'.format(maker_order['price']))
            await self.command_transmitter(trans_command=maker_order, token=Token.TO_POST_POC)

            self._exist_market_poc_order = True

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

    async def _maintain_maker_market(self, order_info: dict, append_info: str) -> None:
        """
        根据 maker 市价单的返回信息，更新统计信息
        属于收到信息并统计
        maker 市价单完全成交，由主方法执行
        :param order_info:
        :param append_info:
        :return:
        """
        self._log_info('=== 维护信息:')
        # this_quantity = float(order_info['quantity'])
        left_quantity = abs(int(append_info.split('=')[-1]))
        if self._target_maker_quantity == 0:
            self._log_info('=== 信息滞后，不处理')
            return
        # this_quantity = calc(calc(self._target_maker_quantity, self._finished_maker_quantity, '-'), left_quantity, '-')
        this_quantity = self._target_maker_quantity - self._finished_maker_quantity - left_quantity
        self._finished_maker_quantity = self._target_maker_quantity - left_quantity
        percent = round(self._finished_maker_quantity / self._target_maker_quantity * 100, 3)
        deal_price = float(order_info['price'])
        adding_volume = calc(calc(this_quantity, self.symbol_quantity_min_step, '*'), deal_price, '*')
        self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
        self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')
        if self._target_maker_side == self.BUY:
            self._account_position_theory += this_quantity
        else:
            self._account_position_theory -= this_quantity
        self._finished_maker_value = calc(self._finished_maker_value, adding_volume, '+')

        self._log_info('=== 本次成交数量: {} 张'.format(this_quantity))
        self._log_info('=== 目标进度\t{} / {} 张\t{} %'.format(self._finished_maker_quantity, self._target_maker_quantity, percent))

    async def _maintain_grid_order(self, this_order_index: int, this_order_side: str, filled_order_id: str, append_info: str = None, order_filled: bool = True) -> None:
        # filled_order_id = data_dict['id']
        # this_order_index, this_order_side = self.parse_id(filled_order_id)

        # 0.最先考虑maker市价单，和进场触发挂单
        # if this_order_index == self.MAKER_MARKET_ID:
        #     self._log_info('\n\n=== maker市价单完全成交')
        #     # 完全成交，目的已达成，最终统计，并归零参数
        #
        #     adding_quantity = calc(self._target_maker_quantity, self._finished_maker_quantity, '-')
        #     deal_price = float(data_dict['price'])
        #     adding_volume = calc(calc(adding_quantity, self.symbol_quantity_min_step, '*'), deal_price, '*')
        #     self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
        #     self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')
        #     if self._target_maker_side == self.BUY:
        #         self._account_position_theory += adding_quantity
        #     else:
        #         self._account_position_theory -= adding_quantity
        #
        #     self._finished_maker_value = calc(self._finished_maker_value, adding_volume, '+')
        #     avg_deal_price = calc(self._finished_maker_value, calc(self._target_maker_quantity, self.symbol_quantity_min_step, '*'), '/')
        #     self._log_info('=== 成交均价:\t{}'.format(avg_deal_price))
        #
        #     self._maker_market_switch_on = False
        #     self._target_maker_quantity = 0
        #     self._target_maker_side = None
        #     self._finished_maker_quantity = 0
        #     self._finished_maker_value = 0
        #     self._exist_market_poc_order = False
        #     return
        #
        # elif this_order_index == self.ENTRY_ORDER_ID:
        #
        #     return
        #
        # elif this_order_index == self.MARKET_ORDER_ID:
        #     # self._log_info('\n\n 市价挂单完全成交!\n\n')
        #     self._log_info('\n\n市价挂单成交!!\t\t价格: {:<12}\tid: {:<10}\n\n'.format(str(data_dict['price']), filled_order_id))
        #     # todo: 可以修正 trading_statistics
        #     return

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

            self._account_position_theory = calc(self._account_position_theory, calc(filled_sell_num, self.grid_each_qty, '*'), '-')

            self.critical_index = this_order_index

            asyncio.create_task(self._terminate_trading(reason='达到网格上边界'))
            return

        elif this_order_index == -1:
            self._log_info('unknown client_id: {}\nplz check code'.format(this_order_side))
            return

        # 2.根据成交或是poc驳回，维护网格
        if order_filled:
            # ============================== 2.1 订单成交类型 ==============================
            filled_indices = []  # 用于判断是否需要补单
            if this_order_index > self.critical_index:
                # 只有价格向上冲到位置才需要补单
                filled_indices = [_i for _i in range(self.critical_index + 1, this_order_index + 1)]
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

                    self._account_position_theory -= self.grid_each_qty
                    self._log_info('{}卖  {:2} 订单成交\t\t价格: {:<12}\tid: {:<10}'.format
                                   (chr(12288), str(instant_post_num), str(self.all_grid_price[this_order_index]), filled_order_id))
                    # self._log_info('卖 {} 订单成交，价格 {}'.format(str(instant_post_num), str(self.all_grid_price[this_order_index])))
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
                    self._account_position_theory += self.grid_each_qty
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

                    self._account_position_theory += self.grid_each_qty
                    self._log_info('{}买  {:2} 订单成交\t\t价格: {:<12}\tid: {:<10}'.format
                                   (chr(12288), str(instant_post_num), str(self.all_grid_price[this_order_index]), filled_order_id))
                    # self._log_info('买 {} 订单成交，价格 {}'.format(str(instant_post_num), str(self.all_grid_price[this_order_index])))
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
                                # self._log_info('在 {} 价位挂卖单, id: {}'.format((str(posting_order['price'])), posting_order['id']))
                                # if this_order_index % 10 == 0:
                                #     self._log_info('___test error___')
                                #     raise ValueError('test error')
                                # else:
                                #     self._log_info('___test good___')
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
                    self._account_position_theory -= self.grid_each_qty
                    self._log_info('{}卖 -{:2} 订单成交\t\t价格: {:<12}\tid: {:<10}\t\t已提前做出反应'.format
                                   (chr(12288), str(self.critical_index - this_order_index), str(self.all_grid_price[this_order_index]), filled_order_id))
                else:
                    self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

            else:
                # self._log_info('unexpected case that order at critical_index is filled, plz recheck\nid: {}'.format(filled_order_id))
                if this_order_side == self.BUY:
                    self._account_position_theory += self.grid_each_qty
                    self._log_info('{}买  {:2} 订单成交\t\t价格: {:<12}\tid: {:<10}\t\t延迟有点大'.format
                                   (chr(12288), str(0), str(self.all_grid_price[this_order_index]), filled_order_id))
                elif this_order_side == self.SELL:
                    self._account_position_theory -= self.grid_each_qty
                    self._log_info('{}卖  {:2} 订单成交\t\t价格: {:<12}\tid: {:<10}\t\t延迟有点大'.format
                                   (chr(12288), str(0), str(self.all_grid_price[this_order_index]), filled_order_id))
                else:
                    self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

            # # *.在特定位置补充仓位，撤销多余挂单
            # filled_time = 0
            # for each_filled_index in filled_indices:
            #     # todo: 此处判断可以提升效率
            #     if each_filled_index in self.indices_of_filling:
            #         if each_filled_index == self.indices_of_filling[0]:
            #             # 正常达到台阶位置，正常补单
            #             self._log_info('\n达到调仓点位 {}，市价补仓\t{}\t张\n'.format(
            #                 str.zfill(str(each_filled_index), 8), self.filling_quantity))
            #
            #             if filled_time == 0:
            #
            #                 if self._maker_market_switch_on:
            #                     self._log_info('存在maker市价任务，延后补仓')
            #                     self._accumulated_market_quantity += self.filling_quantity
            #                 else:
            #                     self._target_maker_quantity = self.filling_quantity
            #                     self._target_maker_side = self.BUY
            #                     self._maker_market_switch_on = True
            #
            #             else:
            #                 self._log_info('\n行情剧烈，一次跨越多个补单点位\n')
            #                 self._log_info(str(filled_indices))
            #
            #             # 如果一次成交很多挂单，则只补仓一次
            #             filled_time += 1
            #
            #             self._add_stair()
            #             # 删除该index，防止重复补仓
            #             self.indices_of_filling.pop(0)
            #             self.present_stair_num += 1
            #             self.present_bottom_index += self.filling_grid_step_num
            #
            #             # 删除多余挂单
            #             endpoint_index = self.parse_id(self.open_buy_orders[0]['id'])[0]
            #             if endpoint_index < self.present_bottom_index:
            #                 cancel_num = self.present_bottom_index - endpoint_index
            #                 post_cancel, self.open_buy_orders = self.open_buy_orders[:cancel_num], self.open_buy_orders[cancel_num:]
            #                 # todo: 可能有一次性撤销挂单非常多的情况，gate还好，币安则要额外判断
            #                 for each_info in post_cancel:
            #                     cancel_cmd = Token.ORDER_INFO.copy()
            #                     cancel_cmd['symbol'] = self.symbol_name
            #                     cancel_cmd['id'] = each_info['id']
            #                     await self.command_transmitter(trans_command=cancel_cmd, token=Token.TO_CANCEL)

        else:
            # ============================== 2.2 订单驳回类型 ==============================
            if this_order_index > self.critical_index:
                # 高价位的卖挂单被驳回
                if this_order_side == self.SELL:
                    # 上方卖单驳回，维护网格
                    # 需要瞬间补上的订单数量
                    instant_reject_num = this_order_index - self.critical_index

                    self._accumulated_market_quantity -= self.grid_each_qty

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
                    self._accumulated_market_quantity += self.grid_each_qty
                    self._log_info('{}买 -{:2} 订单被驳回!\t\t价格: {:<12}\tid: {:<10}\t\t已提前做出反应'.format
                                   (chr(12288), str(this_order_index - self.critical_index), str(self.all_grid_price[this_order_index]), filled_order_id))
                else:
                    self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

            elif this_order_index < self.critical_index:
                # 低价位的订单成交
                if this_order_side == self.BUY:
                    # 下方买单驳回，维护网格
                    instant_reject_num = self.critical_index - this_order_index

                    self._accumulated_market_quantity += self.grid_each_qty

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
                                # self._log_info('在 {} 价位挂卖单, id: {}'.format((str(posting_order['price'])), posting_order['id']))
                                # self._log_info('在 {} 价位挂卖单, id: {}'.format((str(posting_order['price'])), posting_order['id']))
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
                    self._accumulated_market_quantity -= self.grid_each_qty
                    self._log_info('{}卖 -{:2} 订单被驳回!\t\t价格: {:<12}\tid: {:<10}\t\t已提前做出反应'.format
                                   (chr(12288), str(self.critical_index - this_order_index), str(self.all_grid_price[this_order_index]), filled_order_id))
                else:
                    self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

            else:
                # self._log_info('unexpected case that order at critical_index is filled, plz recheck\nid: {}'.format(filled_order_id))
                if this_order_side == self.BUY:
                    self._accumulated_market_quantity += self.grid_each_qty
                    self._log_info('{}买  {:2} 订单被驳回!\t\t价格: {:<12}\tid: {:<10}\t\t请检查订单'.format
                                   (chr(12288), str(0), str(self.all_grid_price[this_order_index]), filled_order_id))
                elif this_order_side == self.SELL:
                    self._accumulated_market_quantity -= self.grid_each_qty
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

            if self._fix_position_task:
                self._fix_position_task: asyncio.coroutine
                if self._fix_position_task.done():
                    # 旧任务已完成，再次执行
                    self._fix_position_task = asyncio.create_task(self._fix_position())
                else:
                    self._log_info('### 存在执行中的校验仓差任务，不开启新任务')
            else:
                self._log_info('### 首次开启校验仓差任务')
                self._fix_position_task = asyncio.create_task(self._fix_position())

    async def _maintainer_by_price(self) -> None:
        """
        根据价格实时维护网格
        :return:
        """
        if self.current_symbol_price >= self.present_step_up_price:
            self._log_info('\n>>> 价格触发，台阶向上移动\t触发价格: {}\n'.format(self.present_step_up_price))
            self.indices_of_filling.pop(0)
            # 需要向上移动区间
            # if self._maker_market_switch_on:
            #     # 添加到任务栏
            #     self._accumulated_market_quantity += self.filling_quantity
            #     self._log_info('存在maker市价任务，延后补仓')
            # else:
            #     self._target_maker_side = self.BUY
            #     self._target_maker_quantity = self.filling_quantity
            #     self._maker_market_switch_on = True
            command = Token.ORDER_INFO.copy()
            command['side'] = self.BUY
            command['quantity'] = self.filling_quantity
            self._log_info('市价下单 {} 张'.format(self.filling_quantity))
            await self.command_transmitter(trans_command=command, token=Token.TO_POST_MARKET)

            self._account_position_theory += self.filling_quantity

            adding_volume = calc(calc(self.filling_quantity, self.symbol_quantity_min_step, '*'), self.current_symbol_price, '*')
            self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
            self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_taker_fee, '*'), '+')

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

            self._grid_stair_step_up()

    async def _maintainer_by_index(self) -> None:
        """
        根据index实时维护网格
        :return:
        """
        if self.critical_index >= self.present_step_up_index:
            self._log_info('\n>>> 挂单触发，台阶向上移动\t触发价格: {}\n'.format(self.present_step_up_price))
            self.indices_of_filling.pop(0)

            # if self._maker_market_switch_on:
            #     # 添加到任务栏
            #     self._accumulated_market_quantity += self.filling_quantity
            #     self._log_info('存在maker市价任务，延后补仓')
            # else:
            #     self._target_maker_side = self.BUY
            #     self._target_maker_quantity = self.filling_quantity
            #     self._maker_market_switch_on = True
            command = Token.ORDER_INFO.copy()
            command['side'] = self.BUY
            command['quantity'] = self.filling_quantity
            self._log_info('市价下单 {} 张'.format(self.filling_quantity))
            await self.command_transmitter(trans_command=command, token=Token.TO_POST_MARKET)

            self._account_position_theory += self.filling_quantity

            adding_volume = calc(calc(self.filling_quantity, self.symbol_quantity_min_step, '*'), self.current_symbol_price, '*')
            self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
            self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_taker_fee, '*'), '+')

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

            self._grid_stair_step_up()

    async def _maintainer_for_maker_emergency(self) -> None:
        pass

    async def _terminate_trading(self, reason: str = '') -> None:
        if not self._is_trading:
            self._log_info('--- 策略正在停止，请稍等。。。')
            self.manually_stop_request_time += 1
            self._log_info(str(self.manually_stop_request_time))
            # 点击次数多，用户强行终止
            if self.manually_stop_request_time >= 10:
                self._log_info('--- 用户强行终止策略，请自行平仓和撤销挂单')
                self._update_text_task.cancel()
                if self._market_locker_task:
                    self._market_locker_task.cancel()

                self.force_stopped = True
                self._my_logger.close_file()
                self._my_executor.stop_single_contract_order_subscription(self.symbol_name)
                self._my_executor.stop_single_contract_ticker_subscription(self.symbol_name)
                self._my_executor.strategy_stopped(self.stg_num)
                self._bound_running_column = None
            return
        self._is_trading = False

        if self._fix_position_task:
            self._log_info('--- 停止仓位修正任务')
            self._fix_position_task.cancel()

        # if self._maker_market_switch_on:
        #     self._log_info('--- 存在maker市价任务，延后终止')
        #     # 等待现有任务全部完成
        #     while True:
        #         await asyncio.sleep(1)
        #         if not self._maker_market_switch_on:
        #             self._log_info('--- 现有任务已完成，执行策略终止任务')
        #             break

        self._update_text_task.cancel()
        if self._market_locker_task:
            self._market_locker_task.cancel()

        cancel_cmd, close_cmd = Token.ORDER_INFO.copy(), Token.ORDER_INFO.copy()
        cancel_cmd['symbol'], close_cmd['symbol'] = self.symbol_name, self.symbol_name

        await asyncio.sleep(0.8)  # 此处延时是为了确保能撤销所有挂单，防止撤单和挂单同时请求，最后出现还剩一单挂着的情况
        await self.command_transmitter(trans_command=cancel_cmd, token=Token.CANCEL_ALL)
        await self._update_trading_statistics()
        await asyncio.sleep(1)

        self._log_info('--- 市价平仓')
        self._log_info('--- 策略开始前账户仓位:\t{}\t张'.format(self._init_account_position))
        # self._log_info('--- 累计理论计算当前仓位:\t{}\t张'.format(self._account_position_theory))
        current_position = await self._my_executor.get_symbol_position(self.symbol_name)
        self._log_info('--- 账户实际当前现货仓位:\t{}\t张'.format(current_position))

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

    async def _fix_position(self) -> None:
        """
        每隔一段时间，自动修正仓位
        todo: 仓位偏差较小和较大时，需要不同的判断方法，仓位偏差较大，需要修正的需求较大
        :return:
        """
        if self._maker_market_switch_on:
            self._log_info('### 存在市价下单任务，暂不校验仓位')
            return
        current_qty = await self._my_executor.get_symbol_position(self.symbol_name)

        self.derive_valid_position()
        self._log_info('\n### 执行仓位修正:')
        self._log_info('### 账户初始仓位:\t\t{}\t张'.format(self._init_account_position))
        self._log_info('### 累计理论当前仓位:\t\t{}\t张'.format(self._account_position_theory))
        self._log_info('### 除去偏差后:\t\t{}\t张'.format(str(self._account_position_theory + self._accumulated_market_quantity)))
        self._log_info('### 策略要求当前仓位:\t\t{}\t张'.format(self._current_valid_position))
        self._log_info('### 账户实际当前仓位:\t\t{}\t张'.format(current_qty))

        fix_qty = int(current_qty + self._accumulated_market_quantity - self._current_valid_position)
        # 小一点的差别就不管了
        if abs(fix_qty) > 5 * self.grid_each_qty:
            self._log_info('### 存在仓位差\t\t{}\t校验仓位中......'.format(fix_qty))
            verify_qty_list = []
            for _ in range(2):
                await asyncio.sleep(5)
                c_qty = await self._my_executor.get_symbol_position(self.symbol_name)
                self.derive_valid_position()
                # d_qty = round_step_size(calc(c_qty, self._current_valid_position, '-'), self.symbol_quantity_min_step, upward=False)
                d_qty = int(c_qty + self._accumulated_market_quantity - self._current_valid_position)
                verify_qty_list.append(d_qty)

            all_equal = True
            for each_qty_def in verify_qty_list:
                if verify_qty_list[0] != each_qty_def:
                    all_equal = False

            self._log_info('\n### 校验仓位差{} {}'.format(str(fix_qty), str(verify_qty_list)))
            if all_equal:

                fix_qty = verify_qty_list[0]  # todo: 临时测试判断结果

                self._log_info('### 需要市价修正仓位\t\t{}\n'.format(str(fix_qty)))
                self._accumulated_market_quantity -= fix_qty

            else:
                self._log_info('### 仓位差校验未通过，不修正仓位，请检查订单情况\n')

        else:
            self._log_info('### 无需修正仓位\n')

    async def _fix_open_orders(self) -> None:
        """
        修正挂单

        操作：
            1. 如果价格偏离记录价格较多，则说明挂单非常失败，直接撤销所有挂单，并重新layout

            否则
            2. 如果没有偏移，则
                获取实际挂单id list

                2.1 先检查实际挂单，剔除账户上的多余挂单
                2.2 再使用理论记录的挂单，补充缺少挂单

        :return:
        """
        # todo: 临时方法，大概存在优化方案，优化挂单维护的逻辑，减少判断次数
        if not self._is_trading:
            self._log_info('$$$ 策略结束，不修正挂单')
            return
        if self._executing_order_fixing:
            self._log_info('$$$ 正在修正挂单，不开启新任务')
            return
        self._log_info('$$$ 开始修正挂单')
        self._executing_order_fixing = True

        # 1. 价格偏移较大情况
        if self.all_grid_price[self.present_bottom_index] < self.current_symbol_price < self._x_grid_up_limit:
            if abs(self.current_symbol_price - self.all_grid_price[self.critical_index]) > 1.5 * self.grid_max_step:
                self._log_info('$$$ 价格偏离较大: 最新价 {}; 策略价 {}, 直接重新开启网格!'.format(self.current_symbol_price, self.all_grid_price[self.critical_index]))
                # 关停maker市价功能
                if self._maker_market_switch_on:
                    self._maker_market_switch_on = False
                    self._target_maker_quantity = 0
                    self._target_maker_side = None
                    self._finished_maker_quantity = 0
                    self._finished_maker_value = 0
                    self._exist_market_poc_order = False

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
                self._exist_failed_order_request = False
                self._need_fix_order = False
                self._executing_order_fixing = False
                return

        # 2. 价格无偏移情况
        account_orders_list, account_orders_list_id = await self._my_executor.get_open_orders(self.symbol_name)
        stg_open_orders: list[str] = [each_order['id'] for each_order in self.open_buy_orders] + [each_order['id'] for each_order in self.open_sell_orders]
        # 剔除特殊挂单
        market_buy_id, market_sell_id = self.gen_id(self.MAKER_MARKET_ID, self.BUY), self.gen_id(self.MAKER_MARKET_ID, self.SELL)
        market_ioc_buy, market_ioc_sell = self.gen_id(self.MARKET_ORDER_ID, self.BUY), self.gen_id(self.MARKET_ORDER_ID, self.SELL)
        for each_i, each_stg_id in enumerate(account_orders_list):
            if market_buy_id == each_stg_id:
                account_orders_list.pop(each_i)
                account_orders_list_id.pop(each_i)
            elif market_sell_id == each_stg_id:
                account_orders_list.pop(each_i)
                account_orders_list_id.pop(each_i)
            elif market_ioc_buy == each_stg_id:
                account_orders_list.pop(each_i)
                account_orders_list_id.pop(each_i)
            elif market_ioc_sell == each_stg_id:
                account_orders_list.pop(each_i)
                account_orders_list_id.pop(each_i)

        if not self._exist_failed_order_request:
            if len(account_orders_list) == len(stg_open_orders):
                self._log_info('$$$ 快速判断无需修正挂单')
                self._need_fix_order = False
                self._executing_order_fixing = False
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
                await self.command_transmitter(trans_command=cancel_cmd, token=Token.TO_CANCEL)

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
                await self.command_transmitter(trans_command=posting_order, token=Token.TO_POST_POC)

        if exist_redundant_order or exist_missing_order:
            self._log_info('$$$ 修正挂单任务完成')
        else:
            self._log_info('$$$ 所有挂单正常，无需修正挂单')

        # 最后将相关变量归位
        self._exist_failed_order_request = False
        self._need_fix_order = False
        self._executing_order_fixing = False

    async def _order_fixer(self, first_waiting_time: int = 300, interval_time: int = 300) -> None:
        """
        该协程是一个一直循环运行的任务，每等待一段时间，执行修正挂单任务
        :return:
        """
        self._log_info('$$$ 360挂单卫士已开启')
        await asyncio.sleep(first_waiting_time)

        while True:
            # await self._fix_open_orders()
            self._log_info('$$$ 挂单卫士: 例行修正挂单')
            if self._need_fix_order:
                self._log_info('$$$ 挂单卫士: 已有挂单修正任务，不干扰')
            else:
                self._need_fix_order = True
            await asyncio.sleep(interval_time)

    async def _update_detail_info(self, interval_time: int = 5, only_once: bool = False) -> None:
        if not only_once:
            await asyncio.sleep(3)

        while True:
            await self._update_trading_statistics()
            self._update_column_text()

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

            showing_texts = '非线性智能调仓 统计信息:'
            showing_texts += '\n\n*** {} ***\n\n'.format('=' * 51)

            if days == 0:
                showing_texts += '交易统计\t\t运行时间\t\t{}:{}:{}\n\n'.format(str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2))
            else:
                showing_texts += '交易统计\t\t运行时间\t\t{} day\t{}:{}:{}\n\n'.format(
                    str(days), str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2))
            # showing_texts += '交易统计:\t\t当前时间 {}\n\n'.format(str(str(pd.to_datetime(self.gen_timestamp(), unit='ms'))))
            # todo: 临时测试参考信息
            self.derive_valid_position()
            showing_texts += '-' * 58
            showing_texts += '\n\n策略记忆价格:\t{:<10}\n'.format(str(self.all_grid_price[self.critical_index]))
            showing_texts += '合约最新价格:\t{:<10}\n\n'.format(str(self.current_symbol_price))
            showing_texts += '-' * 58
            showing_texts += '\n\n执行maker任务:\t{}\n'.format(True if self._maker_market_switch_on else False)
            showing_texts += '当前正确仓位:\t\t{:<10}张\n'.format(self._current_valid_position)
            showing_texts += '累计计算仓位:\t\t{:<10}张\n'.format(self._account_position_theory)
            showing_texts += '累计仓位偏移:\t\t{:<10}张\n\n'.format(self._accumulated_market_quantity)

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

    async def _pre_update_detail_info(self, interval_time: int = 5) -> None:
        """
        策略还在等待时更新的信息，提升交互感
        给交易员更好的交易体验
        :param interval_time:
        :return:
        """
        while True:

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
        await self._update_trading_statistics()
        return str(self._trading_statistics['final_profit'])

    async def _dealing_partial_order(self, order_data_dict: dict) -> bool:
        """
        用于处理部分成交的订单，操作：
        如果该订单已被记录，则根据交易量判断订单是否全部完成，已完成则删除记录，未完成则更新信息
        如果未被记录，则增添记录
        :param order_data_dict: 部分成交订单的订单信息
        :return: True, 订单已全部完成，交给处理。False, 订单未全部完成，继续等待，不操作
        """
        fully_fulfilled = False
        # for each_id, left_qty in self.partially_filled_orders.items():
        #     if order_data_dict['id'] in
        partial_order_id = order_data_dict['id']
        if partial_order_id in self.partially_filled_orders.keys():

            ini_left_qty = self.partially_filled_orders[partial_order_id]
            filled_qty = int(abs(order_data_dict['quantity']))
            left_qty = ini_left_qty - filled_qty
            if left_qty > 0:
                self.partially_filled_orders[partial_order_id] = left_qty
                self._log_info('订单再次部分成交!\t\t价格: {:<12}\tid: {:<10}'.format(order_data_dict['price'], partial_order_id))
                self._log_info('剩余 {} 张'.format(left_qty))
            elif left_qty == 0:
                # 订单已完成
                self.partially_filled_orders.pop(partial_order_id)
                fully_fulfilled = True
            else:
                self._log_info('error: left qty < 0, plz check code!')

        else:
            left_qty = int(self.grid_each_qty) - abs(order_data_dict['quantity'])
            self.partially_filled_orders[partial_order_id] = left_qty
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
            filled_size: int = abs(order_data_dict['quantity'])      # 对于非线性做多，入场挂单为做多挂单，数量为正数，其实不需要abs
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
                # self._log_info('\ntheory position: {}\n'.format(self._account_position_theory))

        else:
            self._log_info('received entry order id while not trigger start! plz check code')

    def _test_delay(self, c_price: float) -> None:
        if not self._is_trading:
            self._log_info('策略已结束，不执行延时操作')
            return

        self._log_info('\n{} , ticker delay over 2 sec'.format(c_price))
        # print('\n{} , ticker delay over 2 sec'.format(c_price))

    # interaction methods
    async def report_receiver(self, recv_data_dict: dict, append_info: str = None) -> None:

        if recv_data_dict['status'] == Token.ORDER_FILLED:
            # 传入的id是客户端的自定订单id
            # 根据订单id，分门别类操作
            order_index, order_side = self.parse_id(recv_data_dict['id'])

            if order_index == self.MAKER_MARKET_ID:
                self._log_info('currently do not maintain maker market order')
                pass

            elif order_index == self.ENTRY_ORDER_ID:
                await self._dealing_ENTRY_ORDER(recv_data_dict)

            elif order_index == self.MARKET_ORDER_ID:
                # 市价挂单暂时不需要操作
                self._log_info('\n\n市价挂单成交!!\t\t价格: {:<12}\t数量: {:<6} 张\n\n'.format(str(recv_data_dict['price']), str(abs(recv_data_dict['quantity']))))

            else:
                # 其他订单，维护网格
                order_qty: int = abs(recv_data_dict['quantity'])
                if order_qty == self.grid_each_qty:
                    await self._maintain_grid_order(order_index, order_side, recv_data_dict['id'], append_info, order_filled=True)
                else:
                    order_fulfilled = await self._dealing_partial_order(recv_data_dict)
                    if order_fulfilled:
                        await self._maintain_grid_order(order_index, order_side, recv_data_dict['id'], append_info, order_filled=True)
                pass
            # await self._maintain_grid_order(recv_data_dict, append_info, order_filled=True)

        elif recv_data_dict['status'] == Token.POST_SUCCESS:
            self._log_info('收到挂单成功信息\t\t价格: {:<12}\tid: {:<10}'.format(str(float(recv_data_dict['price'])), recv_data_dict['id']))
            pass
        elif recv_data_dict['status'] == Token.POC_SUCCESS:
            self._log_info('收到poc挂单成功信息\t\t价格: {:<12}\tid: {:<10}'.format(str(float(recv_data_dict['price'])), recv_data_dict['id']))
            pass
        elif recv_data_dict['status'] == Token.CANCEL_SUCCESS:
            self._log_info('收到撤单成功信息\t\t\t\tid: {:<10}'.format(recv_data_dict['id']))
            pass
        elif recv_data_dict['status'] == Token.CANCEL_POC_SUCCESS:
            self._log_info('收到poc撤单成功信息\t\t\t\tid: {:<10}'.format(recv_data_dict['id']))
            pass
        elif recv_data_dict['status'] == Token.PARTIALLY_FILLED:
            # order_id = recv_data_dict['id']
            # this_order_index, this_order_side = self.parse_id(order_id)
            # if this_order_index == self.MAKER_MARKET_ID:
            #     if self._posted_change_poc_order:
            #         self._log_info('\n=== maker市价单修改成功\t\t价格: {:<12}\tid: {:<10}'.format(str(float(recv_data_dict['price'])), recv_data_dict['id']))
            #         self._posted_change_poc_order = False
            #     else:
            #         # poc 部分成交
            #         self._log_info('\n=== maker市价单部分成交!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            #         await self._maintain_maker_market(recv_data_dict, append_info)
            # else:
            #     self._log_info('订单部分成交!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            pass
        elif recv_data_dict['status'] == Token.UNIDENTIFIED:
            pass
        elif recv_data_dict['status'] == Token.FAILED:
            pass
        elif recv_data_dict['status'] == Token.POST_FAILED:
            self._log_info('\n限价挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            this_order_index, side = self.parse_id(recv_data_dict['id'])
            if this_order_index == self.MAKER_MARKET_ID:
                self._exist_market_poc_order = False
                self._log_info('=== maker市价挂单失败，重新维护')
            pass
        elif recv_data_dict['status'] == Token.POC_FAILED:
            self._log_info('\npoc挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            self._log_info('失败信息: {}'.format(append_info))
            this_order_index, side = self.parse_id(recv_data_dict['id'])
            if this_order_index == self.MAKER_MARKET_ID:
                self._exist_market_poc_order = False
                self._log_info('=== maker市价挂单失败，重新维护')
            else:
                # todo: 出现由于其他情况导致普通poc挂单失败的情况(一般是挂单维护问题导致的挂单数量超50， 或者 请求次数过多) 此处做一个暂时的记录
                self._exist_failed_order_request = True
                # if append_info == 'label: TOO_MANY_ORDERS\ndetail: limit 50':
                #     # todo: 此时该合约挂单数量超过50，需要立即修正挂单，属于临时方法，且貌似只有batch order有这个报错返回
                #     self._log_info('$$$ 检测到挂单数量超过50，需要立刻修正挂单')
                #     self._need_fix_order = True
            pass
        elif recv_data_dict['status'] == Token.POC_REJECTED:
            # todo: new maintain method
            this_order_index, side = self.parse_id(recv_data_dict['id'])
            if this_order_index == self.MAKER_MARKET_ID:
                self._exist_market_poc_order = False
                self._log_info('=== maker市价挂单失败，重新维护')
            else:
                self._log_info('\npoc挂单失败，价格错位\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
                await self._maintain_grid_order(this_order_index, side, recv_data_dict['id'], append_info, order_filled=False)
                # try:
                #     await self._maintain_grid_order(recv_data_dict, append_info, order_filled=False)
                # except Exception:
                #     self._log_info('___maintain rejected order, raise ERROR!!!___')
            pass
        elif recv_data_dict['status'] == Token.CANCEL_FAILED:
            self._log_info('\n撤销挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            if append_info:
                self._log_info(append_info)
            self._exist_failed_order_request = True
            pass
        elif recv_data_dict['status'] == Token.AMEND_NONEXISTENT_POC:
            this_order_index, side = self.parse_id(recv_data_dict['id'])
            if this_order_index == self.MAKER_MARKET_ID:
                self._exist_market_poc_order = False
                self._log_info('=== 尝试修改maker市价单时，发现该挂单不存在!!! 需要重新挂单')
            else:
                self._log_info('\n修改poc挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
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
        接受合约ticker数据
        该方法还可以作为主动更新动力来源
        :param recv_ticker_data:
        :return:
        """
        # 一般来说在策略开始前就已经在收听实时价格信息，因此已经更新一段时间
        self.previous_price = self.current_symbol_price
        self.current_symbol_price = recv_ticker_data['price']

        # todo: 累加任务
        # if self._accumulated_market_quantity != 0:
        #     if abs(self._accumulated_market_quantity) > 12 * self.grid_each_qty:
        #         self._log_info('*** 累计maker市价单仓位较大，需要市价交易')
        #         if not self._maker_market_switch_on:
        #             self._log_info('*** 市价执行已累计仓位 {} 张'.format(self._accumulated_market_quantity))
        #             self._target_maker_side = self.BUY if self._accumulated_market_quantity > 0 else self.SELL
        #             self._target_maker_quantity = abs(self._accumulated_market_quantity)
        #             self._maker_market_switch_on = True
        #             self._accumulated_market_quantity = 0

        # 策略还在运行时，检查最新价格是否偏离过大，
        if self._is_trading:
            if self.all_grid_price[self.present_bottom_index] < self.current_symbol_price < self._x_grid_up_limit:
                if abs(calc(self.current_symbol_price, self.all_grid_price[self.critical_index], '-')) > 1.2 * self.grid_max_step:
                    self._log_info('$$$ 检测到价格偏离过大，策略挂单出现问题')
                    self._need_fix_order = True
            elif self.current_symbol_price > self._x_grid_up_limit:
                self._log_info('检测到价格超出上边界!需要终止策略')
                asyncio.create_task(self._terminate_trading(reason='达到网格上边界'))

            # 添加价格维护，构造冗余
            await self._maintainer_by_price()

        # 开启maker市价开关，需要使用功能，临时取消这个功能
        # if self._maker_market_switch_on:
        #     # asyncio.create_task(self._test_maker())
        #     await self._maker_market_post()

        # 收到修正挂单请求，修正账户挂单
        if self._need_fix_order:
            # 当前价与前一个价格相等时，修正挂单，此时或许挂单变化不大
            if self.previous_price == self.current_symbol_price:
                self._log_info('$$$ price equal, create a fix order coroutine')
                asyncio.create_task(self._fix_open_orders())

        # Beta test
        if self._is_trading:
            if self._delay_action:
                self._delay_action.cancel()
            self._delay_action = self._running_loop.call_later(2, self._test_delay, self.current_symbol_price)

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
