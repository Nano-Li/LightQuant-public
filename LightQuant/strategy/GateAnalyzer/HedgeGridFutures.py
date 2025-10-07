# -*- coding: utf-8 -*-
# @Time : 2023/4/7 14:32
# @Author : 
# @File : HedgeGridFutures.py 
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


class HedgeGridAnalyzerFutures(Analyzer):
    """
    对冲网格，网格数量上下无限延伸！
    采用仓位管理实现对冲，结合期权实现完美对冲
    """

    STG_NAME = '对冲量化网格'

    BUY: str = 'BUY'
    SELL: str = 'SELL'

    MAKER_MARKET_ID = 99999998
    MARKET_ORDER_ID = 99999999

    ENTRY_ORDER_ID = 99999997

    param_dict: dict = {
        'symbol_name': None,
        'up_price': None,
        # 二选一中选择哪个，分别用 int 1, 2 表示
        'dul_selection': None,
        'price_abs_step': None,
        'price_rel_step': None,
        'filling_price_step': None,
        'lower_price_limit': None,
        # 三选一中选择哪个，分别用 int 1, 2, 3 表示
        'tri_selection': None,
        'filling_quantity': None,
        'filling_fund': None,
        'filling_grid_qty': None,
        'leverage': None
    }

    # noinspection PyTypeChecker
    def __init__(self) -> None:
        super().__init__()
        # ==================== 策略参数保存 ==================== #
        self.symbol_name = None
        self.grid_price_step = None
        self.grid_each_qty = None
        self.running_price_range = None  # 套利区间大小
        self.up_price_step = None  # 向上移动价格单位
        self.down_price_step = None  # 向下移动价格单位
        self.symbol_leverage = None

        # todo: manage
        self.entry_price_div = 5   # 临时测试btc功能，入场挂单价格

        # 输入相关，仅作为临时存储
        self._x_grid_initial_range = None
        self._x_price_abs_step = None
        self._x_price_rel_step = None
        self._x_up_price_step = None
        self._x_down_price_step = None  # 下方移动价差
        self._x_filling_quantity = None
        self._x_filling_fund = None
        self._x_each_grid_qty = None
        self._x_leverage = None

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

        self.critical_index: CircularIndex = None
        # 由于循环操作，max index实际意义不大
        self.max_index: CircularIndex = None
        # 一些特殊点位的index，与价格共同实现功能，起冗余作用
        self.base_grid_index: CircularIndex = None
        self.step_up_index: CircularIndex = None
        self.step_down_index: CircularIndex = None
        # 区间边界index
        self._grid_up_limit_index: CircularIndex = None
        self._grid_down_limit_index: CircularIndex = None

        self.all_grid_price: LoopList = None
        # 规范后的入场价格，初始价格，定义后不发生改变
        self.initial_entry_price = 0
        # 网格基准价格，其上方和下方分别是网格需要上下移动的触发价格
        self.base_grid_price = 0
        # 网格上移价格，随着网格移动不断变化
        self.step_up_price = 0
        # 网格下移价格，与index共同作用，实现网格移动
        self.step_down_price = 0
        # 网格上下界价格，会随着网格不断移动
        self._grid_up_limit_price = 0
        self._grid_down_limit_price = 0

        # 价格上下留存区间数量，最好设置的稍大一些
        self._buffer_step_num = 10

        # 当前套利区间网格数量
        self.running_grid_num = 0  # 这里表示区间的网格间距数量，用于方便计算，真实数量需要+1
        # 上移网格数量单位
        self.up_step_grid_num = 0
        # 下移网格数量单位
        self.down_step_grid_num = 0
        # 网格总数量
        self.total_grid_num = 0  # 因为没有计算需求，这里计算真实数量

        self.initial_quantity = None  # 初始仓位数量
        self.filling_up_quantity = None  # 上移补仓数量
        self.filling_down_quantity = None  # 下移砍仓数量(卖出)

        # 当前区间位置相对于最初始位置的位移
        self.present_abs_running_range_pos = 0
        # 区间累计下移次数
        self.range_stepped_down_time = 0
        # 区间累计上移次数
        self.range_stepped_up_time = 0

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
        # 根据当前位置，导出的正确的应有的仓位
        self._current_valid_position: int = 0

        # 每次区间下移代价，仅做参考用
        self._each_shift_down_cost = 0
        # 每次上移亏损，不计算初始仓位带来的盈利，仅用作统计用
        self._each_shift_up_cost_virtual = 0
        # 每次区间下移，未配对盈亏计算修正，真实未配对盈亏=相对未配对盈亏-下移次数*每次下移修正
        self._each_shift_down_statistic_correction = 0

        # 参考期权买入数量
        self.hedge_demanded_options_qty = 0
        # 期权合约乘数，即一张期权标的0.01个BTC
        self._options_multiplier = 0.01
        # 期权价格
        self._options_price = 8.8

        self._trading_statistics: dict = {
            'waiting_start_time': None,
            'strategy_start_time': None,
            'filled_buy_order_num': 0,
            'filled_sell_order_num': 0,
            # 已达成交易量
            'achieved_trade_volume': 0,
            # 已实现的网格套利利润
            'matched_profit': 0,
            # 未实现盈亏
            'unmatched_profit': 0,
            # 区间下移导致的亏损修正
            'step_down_correction': 0,
            # 交易手续费
            'total_trading_fees': 0,
            # 该策略最终净收益
            'final_profit': 0
        }

        # 统计用的 price list，仅做计算用
        self._below_prices: tuple = ()
        self._upward_prices: tuple = ()
        self._up_step_prices: tuple = ()
        self._virtual_prices: tuple = ()

        # ==================== 其他变量 ==================== #
        # noinspection PyTypeChecker
        self._my_logger: LogRecorder = None

        # 存储所有 coroutine
        self._market_locker_task: asyncio.coroutine = None
        self._fix_position_task: asyncio.coroutine = None

        self.stg_num = None
        self.stg_num_len = None

        self._is_trading = False  # todo: 修改至基类

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
        # todo: 每次点击合理化参数，都会重新获取一遍交易规则，可优化
        # print('\n尝试获取交易规则')
        self.symbol_info = await self._running_loop.create_task(self._my_executor.get_symbol_info(symbol_name))
        if self.symbol_info is None:
            return False
        else:
            # 获得合约交易规则
            # todo: 测试如果保存会导致ui如何
            self.symbol_price_min_step = self.symbol_info['price_min_step']
            self.symbol_quantity_min_step = self.symbol_info['qty_min_step']
            self.symbol_max_leverage = self.symbol_info['max_leverage']
            self.symbol_min_notional = 0
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

        self._x_grid_initial_range = validated_params['up_price']
        dul_selection = validated_params['dul_selection']
        self._x_price_abs_step = validated_params['price_abs_step']
        self._x_price_rel_step = validated_params['price_rel_step']
        self._x_up_price_step = validated_params['filling_price_step']
        self._x_down_price_step = validated_params['lower_price_limit']
        tri_selection = validated_params['tri_selection']
        self._x_filling_quantity = validated_params['filling_quantity']
        self._x_filling_fund = validated_params['filling_fund']
        self._x_each_grid_qty = validated_params['filling_grid_qty']
        self._x_leverage = validated_params['leverage']  # 输入时已经是整数

        # print('\n获得参数')
        # for key, value in validated_params.items():
        #     print(key, ': ', value)

        symbol_exist = await self._get_trading_rule(validated_params['symbol_name'])

        if symbol_exist:
            self.current_symbol_price = await self._my_executor.get_current_price(validated_params['symbol_name'])

            if dul_selection == 2:
                self._x_price_abs_step = calc(calc(self._x_price_rel_step, 100, '/'), self.current_symbol_price, '*')
            self._x_price_abs_step = round_step_size(self._x_price_abs_step, self.symbol_price_min_step)

            self._x_price_rel_step = calc(calc(self._x_price_abs_step, self.current_symbol_price, '/'), 100, '*')
            self._x_price_rel_step = round_step_size(self._x_price_rel_step, 0.00001)

            self._x_grid_initial_range = round_step_size(self._x_grid_initial_range, self._x_price_abs_step)
            self._x_up_price_step = round_step_size(self._x_up_price_step, self._x_price_abs_step)
            self._x_down_price_step = round_step_size(self._x_down_price_step, self._x_price_abs_step)

            if self._x_grid_initial_range < self._x_up_price_step or self._x_grid_initial_range < self._x_down_price_step:
                self._x_grid_initial_range = str(self._x_grid_initial_range) + '区间太小'
                param_valid = False

            if tri_selection != 3:
                self._x_each_grid_qty = 1
            else:
                self._x_each_grid_qty = int(round_step_size(self._x_each_grid_qty, 1))

            # 判断杠杆数是否合理
            if self._x_leverage > self.symbol_max_leverage:
                self._x_leverage = str(self._x_leverage) + '杠杆数值超限'
                param_valid = False

        else:
            validated_params['symbol_name'] += '未查询到该合约'
            param_valid = False

        validated_params['up_price'] = self._x_grid_initial_range
        validated_params['price_abs_step'] = self._x_price_abs_step
        validated_params['price_rel_step'] = self._x_price_rel_step
        validated_params['filling_price_step'] = self._x_up_price_step
        validated_params['lower_price_limit'] = self._x_down_price_step
        validated_params['filling_quantity'] = ''
        validated_params['filling_fund'] = ''
        validated_params['filling_grid_qty'] = self._x_each_grid_qty
        validated_params['leverage'] = self._x_leverage
        validated_params['valid'] = param_valid

        return validated_params

    async def param_ref_info(self, valid_params_dict: dict) -> str:
        symbol_name = valid_params_dict['symbol_name']

        info_texts: str = """\n"""
        info_texts += '*** {} ***\n'.format('=' * 32)
        self.current_symbol_price = await self._my_executor.get_current_price(symbol_name)
        info_texts += '\n当前时间: {}\n'.format(str(pd.to_datetime(self.gen_timestamp(), unit='ms')))
        info_texts += '\n合约名称: {}\t\t\t当前价格: {}\n'.format(symbol_name, str(self.current_symbol_price))

        self.derive_functional_variables()

        # 初始占用保证金
        init_margin_cost = calc(calc(calc(self.initial_quantity, self.symbol_quantity_min_step, '*'), self.current_symbol_price, '*'), self.symbol_leverage, '/')
        # 最大持有仓位
        max_holding_position = self.initial_quantity + self.filling_down_quantity
        # 最大保证金占用
        max_margin_cost = calc(calc(calc(max_holding_position, self.symbol_quantity_min_step, '*'), self.current_symbol_price, '*'), self.symbol_leverage, '/')

        # 参考价格，没有实际意义，只做计算用
        ref_prices = tuple([calc(self.initial_entry_price, calc(self.grid_price_step, i, '*'), '+') for i in range(self.down_step_grid_num + 1)])
        # 区间下移代价
        # shift_down_cost = self.unmatched_profit_calc(
        #     initial_index=-1,
        #     current_index=0,
        #     all_prices=ref_prices,
        #     each_grid_qty=calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'),
        #     init_pos_price=ref_prices[-1],
        #     init_pos_qty=0,
        #     current_price=ref_prices[0]
        # )

        percent_norm_price = calc(self.current_symbol_price, 0.9, '*')
        target_price = self.initial_entry_price
        shifted_down_times = 0  # 假设下移次数
        while True:
            target_price = calc(target_price, self.down_price_step, '-')
            shifted_down_times += 1
            if target_price <= percent_norm_price:
                break
        percentage = 100 * calc(calc(self.current_symbol_price, target_price, '-'), self.initial_entry_price, '/')
        # 此时的假设账户浮亏
        account_loss_assumption = calc(calc(self._each_shift_down_cost, shifted_down_times, '*'),
                                       calc(calc(target_price, self.current_symbol_price, '-'), calc(self.initial_quantity, self.symbol_quantity_min_step, '*'), '*'), '+')

        # print('全程下移消费, 初始仓位亏损')
        # print('{}, {}'.format(calc(shift_down_cost, shifted_down_times, '*'),
        #                       calc(calc(target_price, self.current_symbol_price, '-'), calc(self.initial_quantity, self.symbol_quantity_min_step, '*'), '*')))

        # 对冲要求的期权数量 todo: 这里给定期权 multiplier = 0.01
        k_profit = self._options_multiplier
        k_loss = calc(account_loss_assumption, calc(target_price, self.current_symbol_price, '-'), '/')
        self.hedge_demanded_options_qty = calc(k_loss, k_profit, '/')
        # 建议账户资金量
        suggested_account_fund_low = calc(max_margin_cost, calc(abs(account_loss_assumption), 0.2, '*'), '+')
        suggested_account_fund_high = calc(max_margin_cost, calc(abs(account_loss_assumption), 0.5, '*'), '+')

        # 期权费占用资金比例参考
        each_options_cost = self._options_price
        total_stg_fund_demand = calc(suggested_account_fund_low, calc(each_options_cost, self.hedge_demanded_options_qty, '*'), '+')
        options_cost_percent_ref = 100 * calc(calc(each_options_cost, self.hedge_demanded_options_qty, '*'), total_stg_fund_demand, '/')

        info_texts += '\n区间网格数量\t\t{:<8}\n'.format(str(self.running_grid_num))
        info_texts += '上移网格数量\t\t{:<8}\n'.format(str(self.up_step_grid_num))
        info_texts += '下移网格数量\t\t{:<8}\n'.format(str(self.down_step_grid_num))

        info_texts += '\n网格价差占比\t\t{:<8}\t\t{:<8}\n'.format(str(round(self.grid_price_step / self.current_symbol_price * 100, 6)), '%')
        info_texts += '每格套利利润\t\t{:<8}\t\t{:<8}\n'.format(str(calc(calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'), self.grid_price_step, '*')), symbol_name[-4:])

        info_texts += '\n初始保证金占用\t\t{:<8}\t\t{:<8}\n'.format(str(init_margin_cost), symbol_name[-4:])
        info_texts += '初始仓位数量\t\t{:<8}\t\t{:<8}\t最小\n'.format(str(calc(self.initial_quantity, self.symbol_quantity_min_step, '*')), symbol_name[:-4].replace('_', ''))
        info_texts += '上移补仓数量\t\t{:<8}\t\t{:<8}\t最大\n'.format(str(calc(self.filling_up_quantity, self.symbol_quantity_min_step, '*')), symbol_name[:-4].replace('_', ''))
        info_texts += '下移砍仓数量\t\t{:<8}\t\t{:<8}\t最大\n'.format(str(calc(self.filling_down_quantity, self.symbol_quantity_min_step, '*')), symbol_name[:-4].replace('_', ''))

        info_texts += '\n最大持有仓位\t\t{:<8}\t\t{:<8}\n'.format(str(max_holding_position), '张')
        info_texts += '最大持仓保证金\t\t{:<8}\t\t{:<8}\t最小\n'.format(str(round(max_margin_cost, 2)), symbol_name[-4:])

        info_texts += '\n区间下移代价\t\t{:<8}\t\t{:<8}\n'.format(str(round(self._each_shift_down_cost, 2)), symbol_name[-4:])

        info_texts += '\n对冲要求:\n'
        info_texts += '买入看跌期权\t\t{:<8}\t\t张\n'.format(str(round(self.hedge_demanded_options_qty, 2)))

        info_texts += '\n标的物价格下跌 {} %  =\t{:<8}\t\t{:<8}\n'.format(str(round(percentage, 2)), str(calc(target_price, self.current_symbol_price, '-')), symbol_name[-4:])
        info_texts += '导致账户浮亏\t\t{:<8}\t\t{:<8}\n'.format(str(round(account_loss_assumption, 2)), symbol_name[-4:])

        info_texts += '\n建议账户资金\t\t{:<16}~ {:<16}\t$\n'.format(str(round(suggested_account_fund_low, 2)), str(round(suggested_account_fund_high, 2)))

        info_texts += '\n期权费占用策略资金比例参考\t{} %\n'.format(str(round(options_cost_percent_ref, 2)))

        info_texts += '\n*** {} ***'.format('=' * 32)

        return info_texts

    def confirm_params(self, input_params: dict) -> None:
        """
        确认参数
        :param input_params:
        :return:
        """
        # 按照当前逻辑，此时本地保存的均是合理的参数，只有symbol name信息传递
        self.symbol_name = input_params['symbol_name']

        self._my_executor.start_single_contract_order_subscription(self.symbol_name)
        self._my_executor.start_single_contract_ticker_subscription(self.symbol_name)

    def derive_functional_variables(self) -> None:
        """
        根据本地保存的输入参数，导出并存储策略运行所需要的变量
        在弹出参考信息，和策略点击开始运行 两处，都要使用，在得到当前价格后使用
        :return:
        """
        self.grid_price_step = self._x_price_abs_step
        self.grid_each_qty = int(self._x_each_grid_qty)
        self.running_price_range = self._x_grid_initial_range
        self.up_price_step = self._x_up_price_step
        self.down_price_step = self._x_down_price_step
        self.symbol_leverage = self._x_leverage

        # 计算上下网格部分
        self.running_grid_num = int(calc(self.running_price_range, self.grid_price_step, '/'))
        self.up_step_grid_num = int(calc(self.up_price_step, self.grid_price_step, '/'))
        self.down_step_grid_num = int(calc(self.down_price_step, self.grid_price_step, '/'))

        self.total_grid_num = self.running_grid_num + self.down_step_grid_num + self._buffer_step_num * (self.up_step_grid_num + self.down_step_grid_num) + 1

        self.filling_up_quantity = int(self.up_step_grid_num / 2) * self.grid_each_qty
        self.filling_down_quantity = self.down_step_grid_num * self.grid_each_qty
        self.initial_quantity = (self.running_grid_num - int(self.up_step_grid_num / 2)) * self.grid_each_qty

        # 计算价格和index部分
        # todo: manage
        # self.initial_entry_price = round_step_size(self.current_symbol_price, self.grid_price_step)
        self.initial_entry_price = calc(round_step_size(self.current_symbol_price, self.grid_price_step), self.entry_price_div, '-')
        self.base_grid_price = self.initial_entry_price
        # self.step_up_price = calc(self.base_grid_price, calc(self.grid_price_step, self.running_grid_num, '*'), '+')
        # self.step_down_price = calc(self.base_grid_price, calc(self.grid_price_step, self.down_step_grid_num, '*'), '-')

        self._grid_down_limit_price = calc(self.base_grid_price, calc(self.grid_price_step, self.down_step_grid_num * (self._buffer_step_num + 1), '*'), '-')
        # self._grid_up_limit_price = calc(self.base_grid_price, calc(self.grid_price_step, self.running_grid_num + self.up_step_grid_num * self._buffer_step_num, '*'), '+')

        self.all_grid_price = LoopList([calc(self._grid_down_limit_price, calc(self.grid_price_step, i, '*'), '+') for i in range(self.total_grid_num)])

        self.max_index = CircularIndex(value=self.total_grid_num - 1, max_val=self.total_grid_num - 1)

        self.base_grid_index = CircularIndex(value=self.down_step_grid_num * (self._buffer_step_num + 1), max_val=int(self.max_index))
        self.critical_index = self.base_grid_index.copy()

        self.step_up_index = self.base_grid_index + self.running_grid_num
        self.step_down_index = self.base_grid_index - self.down_step_grid_num

        self._grid_up_limit_index = CircularIndex(value=self.total_grid_num - 1, max_val=int(self.max_index))
        self._grid_down_limit_index = CircularIndex(value=0, max_val=int(self.max_index))

        self._grid_up_limit_price = self.all_grid_price[self.max_index]
        self.step_up_price = self.all_grid_price[self.step_up_index]
        self.step_down_price = self.all_grid_price[self.step_down_index]

        # 保存一个临时价格list，仅用于统计数据用，没有实际意义
        self._below_prices = tuple([each for each in self.all_grid_price[self.step_down_index:self.base_grid_index + 1]])
        self._upward_prices = tuple([each for each in self.all_grid_price[self.base_grid_index:self.step_up_index + 1]])
        self._up_step_prices = tuple([each for each in self.all_grid_price[self.step_up_index:self.step_up_index + self.up_step_grid_num + 1]])
        self._virtual_prices = tuple([each for each in self.all_grid_price[self.step_down_index:self.step_up_index + 1]])

        self._each_shift_down_cost = self.unmatched_profit_calc(
            initial_index=-1,
            current_index=0,
            all_prices=self._below_prices,
            each_grid_qty=calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'),
            init_pos_price=self._below_prices[-1],
            init_pos_qty=0,
            current_price=self._below_prices[0]
        )
        self._each_shift_down_statistic_correction = self.unmatched_profit_calc(
            initial_index=-1,
            current_index=0,
            all_prices=self._below_prices,
            each_grid_qty=calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'),
            init_pos_price=self._below_prices[-1],
            init_pos_qty=calc(self.initial_quantity, self.symbol_quantity_min_step, '*'),
            current_price=self._below_prices[0]
        )

        # print('base_price, step_up_price, step_down_price, up_limit_price, down_limit_price')
        # print(self.base_grid_price, self.step_up_price, self.step_down_price, self._grid_up_limit_price, self._grid_down_limit_price)
        # print(
        #     self.all_grid_price[self.base_grid_index],
        #     self.all_grid_price[self.step_up_index],
        #     self.all_grid_price[self.step_down_index],
        #     self.all_grid_price[self.max_index],
        #     self.all_grid_price[0]
        # )
        # print(
        #     self.base_grid_index,
        #     self.step_up_index,
        #     self.step_down_index,
        #     self.max_index,
        # )
        # print(len(self.all_grid_price))
        # print(self.max_index)
        # print(self.down_step_grid_num * (self._buffer_step_num + 1))

    def derive_valid_position(self) -> None:
        """
        以 base index 为基准得到正确的仓位，因此，base index 不能出错
        :return:
        """
        zero_pos_index = self.base_grid_index + (self.running_grid_num - int(self.up_step_grid_num / 2))
        if self.critical_index <= zero_pos_index:
            self._current_valid_position = calc(zero_pos_index - self.critical_index, self.grid_each_qty, '*')
        else:
            self._current_valid_position = -calc(self.critical_index - zero_pos_index, self.grid_each_qty, '*')

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
        由于入场手续费较多，使用挂单入场
        :return:
        """
        self._my_logger = LogRecorder()
        self._my_logger.open_file(self.symbol_name)

        asyncio.create_task(self._my_executor.change_symbol_leverage(self.symbol_name, self.symbol_leverage))

        self._pre_update_text_task = asyncio.create_task(self._pre_update_detail_info(interval_time=1))

        self.derive_functional_variables()

        maker_order = Token.ORDER_INFO.copy()
        maker_order['symbol'] = self.symbol_name
        maker_order['id'] = self.gen_id(self.ENTRY_ORDER_ID, self.BUY)
        maker_order['price'] = self.initial_entry_price
        maker_order['side'] = self.BUY
        maker_order['quantity'] = self.initial_quantity
        self._log_info('~~~ 触发挂单下单\n')
        asyncio.create_task(self.command_transmitter(trans_command=maker_order, token=Token.TO_POST_POC))

        self._trading_statistics['waiting_start_time'] = self.gen_timestamp()
        self._log_info('开始监听数据，等待触发条件')
        self._is_waiting = True

    async def _start_strategy(self):
        """
        程序开始操作，整个程序的起点
        :return:
        """
        self._is_waiting = False
        self._is_trading = True
        self._log_info('对冲量化网格策略开始')

        self._pre_update_text_task.cancel()

        self._update_text_task = asyncio.create_task(self._update_detail_info(interval_time=1))

        self._init_account_position = 0

        # self.derive_functional_variables()

        self._trading_statistics['strategy_start_time'] = self.gen_timestamp()
        # self.current_symbol_price = await self._my_executor.get_current_price(self.symbol_name)
        self.current_symbol_price = self.initial_entry_price
        self._log_info('策略开始合约价格: {}'.format(self.current_symbol_price))

        # 1. 设置初始 maker 市价买入数量
        # self._target_maker_side = self.BUY
        # self._target_maker_quantity = self.initial_quantity
        # self._maker_market_switch_on = True

        # 2. 开始撒网
        asyncio.create_task(self._layout_net())

        # 3. 开启维护挂单任务
        self._fix_order_task = asyncio.create_task(self._order_fixer(interval_time=60))

    # strategy methods
    def _grid_step_up(self) -> None:
        """
        达到补仓点位，整体网格区间上移一个单位
        :return:
        """
        grid_top_price = self.all_grid_price[self._grid_up_limit_index]
        self.all_grid_price[self._grid_up_limit_index + 1:self._grid_up_limit_index + self.up_step_grid_num + 1] = \
            [calc(grid_top_price, calc(self.grid_price_step, i + 1, '*'), '+') for i in range(self.up_step_grid_num)]

        # todo: 重写 += 方法
        self._grid_down_limit_index = self._grid_down_limit_index + self.up_step_grid_num
        self.step_down_index = self.step_down_index + self.up_step_grid_num
        self.base_grid_index = self.base_grid_index + self.up_step_grid_num
        self.step_up_index = self.step_up_index + self.up_step_grid_num
        self._grid_up_limit_index = self._grid_up_limit_index + self.up_step_grid_num

        self._grid_up_limit_price = self.all_grid_price[self._grid_up_limit_index]
        self.step_down_price = self.all_grid_price[self.step_down_index]
        self.base_grid_price = self.all_grid_price[self.base_grid_index]
        self.step_up_price = self.all_grid_price[self.step_up_index]
        self._grid_down_limit_price = self.all_grid_price[self._grid_down_limit_index]

        self.range_stepped_up_time += 1
        self.present_abs_running_range_pos += 1

    def _grid_step_down(self) -> None:
        """
        达到砍仓点位，整体网格区间下移一个单位
        :return:
        """
        grid_bottom_price = self.all_grid_price[self._grid_down_limit_index]
        self.all_grid_price[self._grid_down_limit_index - self.down_step_grid_num:self._grid_down_limit_index] = \
            [calc(grid_bottom_price, calc(self.grid_price_step, i, '*'), '-') for i in range(self.down_step_grid_num, 0, -1)]

        self._grid_down_limit_index = self._grid_down_limit_index - self.down_step_grid_num
        self.step_down_index = self.step_down_index - self.down_step_grid_num
        self.base_grid_index = self.base_grid_index - self.down_step_grid_num
        self.step_up_index = self.step_up_index - self.down_step_grid_num
        self._grid_up_limit_index = self._grid_up_limit_index - self.down_step_grid_num

        self._grid_up_limit_price = self.all_grid_price[self._grid_up_limit_index]
        self.step_down_price = self.all_grid_price[self.step_down_index]
        self.base_grid_price = self.all_grid_price[self.base_grid_index]
        self.step_up_price = self.all_grid_price[self.step_up_index]
        self._grid_down_limit_price = self.all_grid_price[self._grid_down_limit_index]

        self.range_stepped_down_time += 1
        self.present_abs_running_range_pos -= 1

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
        布撒初始网格， 使用batch order操作，布撒poc挂单
        :return:
        """
        ini_buy_order_num = round((self.min_buy_order_num + self.max_buy_order_num) / 2)
        ini_sell_order_num = round((self.min_sell_order_num + self.max_sell_order_num) / 2)
        self.open_buy_orders = [
            {
                'id': self.gen_id(_index, self.BUY),
                'status': 'NEW',
                'time': self.gen_timestamp()
            } for _index in CircularIndex.Crange(self.critical_index - ini_buy_order_num, self.critical_index)
        ]
        self.open_sell_orders = [
            {
                'id': self.gen_id(_index, self.SELL),
                'status': 'NEW',
                'time': self.gen_timestamp()
            } for _index in CircularIndex.Crange(self.critical_index + 1, self.critical_index + ini_sell_order_num + 1)
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
            # todo: 对于maker市价单功能，严格检查非同步方法
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

    async def _maintain_grid_order(self, data_dict: dict, append_info: str = None, order_filled: bool = True) -> None:
        filled_order_id = data_dict['id']
        this_order_index, this_order_side = self.parse_id(filled_order_id)
        # 使用特殊的index作为判断，实现循环功能
        this_order_index = CircularIndex(value=this_order_index, max_val=int(self.max_index))

        # 0.最先考虑maker市价单
        if this_order_index == self.MAKER_MARKET_ID:
            self._log_info('\n\n=== maker市价单完全成交')
            # 完全成交，目的已达成，最终统计，并归零参数

            adding_quantity = calc(self._target_maker_quantity, self._finished_maker_quantity, '-')
            deal_price = float(data_dict['price'])
            adding_volume = calc(calc(adding_quantity, self.symbol_quantity_min_step, '*'), deal_price, '*')
            self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
            self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')
            if self._target_maker_side == self.BUY:
                self._account_position_theory += adding_quantity
            else:
                self._account_position_theory -= adding_quantity

            self._finished_maker_value = calc(self._finished_maker_value, adding_volume, '+')
            avg_deal_price = calc(self._finished_maker_value, calc(self._target_maker_quantity, self.symbol_quantity_min_step, '*'), '/')
            self._log_info('=== 成交均价:\t{}'.format(avg_deal_price))

            self._maker_market_switch_on = False
            self._target_maker_quantity = 0
            self._target_maker_side = None
            self._finished_maker_quantity = 0
            self._finished_maker_value = 0
            self._exist_market_poc_order = False
            return

        elif this_order_index == self.MARKET_ORDER_ID:
            self._log_info('\n\n市价挂单成交!!\t\t价格: {:<12}\tid: {:<10}\n\n'.format(str(data_dict['price']), filled_order_id))
            # todo: fix trading statistics
            self._account_position_theory += data_dict['quantity']
            return

        elif this_order_index == self.ENTRY_ORDER_ID:
            self._log_info('\n\n~~~ 触发挂单完全成交!\n\n')

            asyncio.create_task(self._start_strategy())

            fee_dict = await self._my_executor.get_symbol_trade_fee(self.symbol_name)
            self.symbol_maker_fee = fee_dict['maker_fee']
            self.symbol_taker_fee = fee_dict['taker_fee']
            self._log_info('maker fee rate: {}'.format(self.symbol_maker_fee))
            self._log_info('taker fee rate: {}'.format(self.symbol_taker_fee))

            adding_volume = calc(calc(self.initial_quantity, self.symbol_quantity_min_step, '*'), self.initial_entry_price, '*')
            self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
            self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

            self._account_position_theory += self.initial_quantity

            return

        if not self._is_trading:
            self._log_info('交易结束，不继续维护网格 order_id: {}'.format(filled_order_id))
            return

        # 1. 提示信息，网格没有边界，不退出
        if append_info:
            self._log_info(append_info)
        self._log_info('维护网格\t\t\t网格位置 = {}'.format(self.critical_index))

        if this_order_index == -1:
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

                    self._account_position_theory -= self.grid_each_qty
                    self._log_info('{}卖  {:2} 订单成交\t\t价格: {:<12}\tid: {:<10}'.format
                                   (chr(12288), str(instant_post_num), str(self.all_grid_price[this_order_index]), filled_order_id))
                    # self._log_info('卖 {} 订单成交，价格 {}'.format(str(instant_post_num), str(self.all_grid_price[this_order_index])))
                    instant_post_buy: list = [
                        {
                            'id': self.gen_id(each_index, self.BUY),
                            'status': 'NEW',
                            'time': self.gen_timestamp()
                        } for each_index in CircularIndex.Crange(this_order_index - 1, self.critical_index - 1, -1)
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
                        } for each_index in CircularIndex.Crange(this_order_index + 1, self.critical_index + 1)
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

        # 3. 根据订单index，检查是否需要移动网格
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
                    endpoint_index = CircularIndex(value=self.parse_id(self.open_buy_orders[0]['id'])[0], max_val=int(self.max_index))

                # 在超高频网格当中，可能一下子现存订单就非常少，需要一次补充很多挂单
                instant_add_num = self.buffer_buy_num if (self.min_buy_order_num - open_buy_orders_num < self.buffer_buy_num) \
                    else self.max_buy_order_num - open_buy_orders_num - 5

                filling_post_buy: list = [
                    {
                        'id': self.gen_id(each_index, self.BUY),
                        'status': 'NEW',
                        'time': self.gen_timestamp()
                    } for each_index in CircularIndex.Crange(endpoint_index - instant_add_num, endpoint_index)
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
                    endpoint_index = CircularIndex(value=self.parse_id(self.open_sell_orders[-1]['id'])[0], max_val=int(self.max_index))

                # 在超高频网格当中，可能一下子现存订单就非常少，需要一次补充很多挂单
                instant_add_num = self.buffer_sell_num if (self.min_sell_order_num - open_sell_orders_num < self.buffer_sell_num) \
                    else self.max_sell_order_num - open_sell_orders_num - 5

                filling_post_sell: list = [
                    {
                        'id': self.gen_id(each_index, self.SELL),
                        'status': 'NEW',
                        'time': self.gen_timestamp()
                    } for each_index in CircularIndex.Crange(endpoint_index + 1, endpoint_index + instant_add_num + 1)
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
        if (self._trading_statistics['filled_buy_order_num'] + self._trading_statistics['filled_sell_order_num']) % 40 == 0:

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
        if self.current_symbol_price <= self.step_down_price:
            self._log_info('\n>>> 价格触发，向下移动区间\t触发价格: {}\n'.format(self.step_down_price))
            # print('{} <= {}'.format(self.current_symbol_price, self.step_down_price))
            # 需要向下移动区间
            command = Token.ORDER_INFO.copy()
            command['side'] = self.SELL
            command['quantity'] = self.filling_down_quantity
            self._log_info('市价下单 -{} 张'.format(self.filling_down_quantity))
            await self.command_transmitter(trans_command=command, token=Token.TO_POST_MARKET)

            adding_volume = calc(calc(self.filling_down_quantity, self.symbol_quantity_min_step, '*'), self.current_symbol_price, '*')
            self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
            self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_taker_fee, '*'), '+')

            self._grid_step_down()
            self._trading_statistics['step_down_correction'] = calc(self._trading_statistics['step_down_correction'], self._each_shift_down_statistic_correction, '+')

        elif self.current_symbol_price >= self.step_up_price:
            self._log_info('\n>>> 价格触发，向上移动区间\t触发价格: {}\n'.format(self.step_up_price))
            # print('{} >= {}'.format(self.current_symbol_price, self.step_up_price))
            command = Token.ORDER_INFO.copy()
            command['side'] = self.BUY
            command['quantity'] = self.filling_up_quantity
            self._log_info('市价下单 {} 张'.format(self.filling_up_quantity))
            await self.command_transmitter(trans_command=command, token=Token.TO_POST_MARKET)

            adding_volume = calc(calc(self.filling_up_quantity, self.symbol_quantity_min_step, '*'), self.current_symbol_price, '*')
            self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
            self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_taker_fee, '*'), '+')

            self._grid_step_up()

    async def _maintainer_by_index(self) -> None:
        """
        根据index实时维护网格
        操作：调整仓位，滚动价格list
        :return:
        """
        if self.critical_index <= self.step_down_index:
            self._log_info('\n>>> 索引触发，向下移动区间\t触发价格: {}\n'.format(self.all_grid_price[self.step_down_index]))
            # print('{} <= {}'.format(self.critical_index, self.step_down_index))
            # 需要向下移动区间
            command = Token.ORDER_INFO.copy()
            command['side'] = self.SELL
            command['quantity'] = self.filling_down_quantity
            self._log_info('市价下单 -{} 张'.format(self.filling_down_quantity))
            await self.command_transmitter(trans_command=command, token=Token.TO_POST_MARKET)

            adding_volume = calc(calc(self.filling_down_quantity, self.symbol_quantity_min_step, '*'), self.all_grid_price[self.critical_index], '*')
            self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
            self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_taker_fee, '*'), '+')

            self._grid_step_down()
            self._trading_statistics['step_down_correction'] = calc(self._trading_statistics['step_down_correction'], self._each_shift_down_statistic_correction, '+')

        elif self.critical_index >= self.step_up_index:
            self._log_info('\n>>> 索引触发，向上移动区间\t触发价格: {}\n'.format(self.all_grid_price[self.step_up_index]))
            # print('{} >= {}'.format(self.critical_index, self.step_up_index))
            command = Token.ORDER_INFO.copy()
            command['side'] = self.BUY
            command['quantity'] = self.filling_up_quantity
            self._log_info('市价下单 {} 张'.format(self.filling_up_quantity))
            await self.command_transmitter(trans_command=command, token=Token.TO_POST_MARKET)

            adding_volume = calc(calc(self.filling_up_quantity, self.symbol_quantity_min_step, '*'), self.all_grid_price[self.critical_index], '*')
            self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
            self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_taker_fee, '*'), '+')

            self._grid_step_up()

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

        if self._maker_market_switch_on:
            self._log_info('--- 存在maker市价任务，延后终止')
            # 等待现有任务全部完成
            while True:
                await asyncio.sleep(1)
                if not self._maker_market_switch_on:
                    self._log_info('--- 现有任务已完成，执行策略终止任务')
                    break

        self._update_text_task.cancel()
        if self._market_locker_task:
            self._market_locker_task.cancel()

        cancel_cmd, close_cmd = Token.ORDER_INFO.copy(), Token.ORDER_INFO.copy()
        cancel_cmd['symbol'], close_cmd['symbol'] = self.symbol_name, self.symbol_name

        await asyncio.sleep(0.8)  # 此处延时是为了确保能撤销所有挂单，防止撤单和挂单同时请求，最后出现还剩一单挂着的情况
        await self.command_transmitter(trans_command=cancel_cmd, token=Token.CANCEL_ALL)
        await self._update_trading_statistics()
        await asyncio.sleep(3)

        self._log_info('--- 市价平仓')
        self._log_info('--- 策略开始前账户仓位:\t{}\t张'.format(self._init_account_position))
        self._log_info('--- 累计理论计算当前仓位:\t{}\t张'.format(self._account_position_theory))
        current_position = await self._my_executor.get_symbol_position(self.symbol_name)
        self._log_info('--- 账户实际当前现货仓位:\t{}\t张'.format(current_position))
        # 需要大于10张
        close_qty = current_position - self._init_account_position
        if close_qty != 0:

            if self._maker_market_switch_on:
                self._log_info('--- 存在maker市价任务，延后平仓')
                if close_qty > 0:
                    self._accumulated_market_quantity -= close_qty
                else:
                    self._accumulated_market_quantity += close_qty
                # 等待现有任务全部完成
                while True:
                    await asyncio.sleep(1)
                    if not self._maker_market_switch_on:
                        self._log_info('--- 现有任务已完成，执行最后市价任务')
                        break

            self._log_info('--- 实际市价平掉仓位 {}'.format(str(close_qty)))
            self._target_maker_quantity = abs(close_qty)
            self._target_maker_side = self.SELL if (close_qty > 0) else self.BUY
            self._maker_market_switch_on = True

            # 循环等待只到平仓任务完成
            while True:
                await asyncio.sleep(1)
                if not self._maker_market_switch_on:
                    self._log_info('--- maker市价平仓完成')
                    break
                # else:
                #     self._log_info('--- 临时循环等待，测试用功能。。。')

        else:
            self._log_info('--- 实际不需要市价平仓')

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
        # todo: 未配对盈亏可以再过一遍
        filled_trading_pair = min(self._trading_statistics['filled_buy_order_num'], self._trading_statistics['filled_sell_order_num'])
        self._trading_statistics['matched_profit'] = calc(calc(filled_trading_pair, self.grid_price_step, '*'), calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'), '*')

        virtual_index = (self.critical_index - self.base_grid_index) + self.down_step_grid_num
        self._trading_statistics['unmatched_profit'] = self.unmatched_profit_calc(
            initial_index=self.down_step_grid_num,
            current_index=virtual_index,
            all_prices=self._virtual_prices,
            each_grid_qty=calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'),
            init_pos_price=self._virtual_prices[self.down_step_grid_num],
            init_pos_qty=calc(self.initial_quantity, self.symbol_quantity_min_step, '*'),
            current_price=self._virtual_prices[virtual_index]
        )

        self._trading_statistics['final_profit'] = calc(calc(calc(self._trading_statistics['matched_profit'], self._trading_statistics['unmatched_profit'], '+'),
                                                             self._trading_statistics['step_down_correction'], '+'), self._trading_statistics['total_trading_fees'], '-')

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
        if abs(self.current_symbol_price - self.all_grid_price[self.critical_index]) > 10 * self.grid_price_step:
            self._log_info('$$$ 价格偏离较大: 最新价 {}; 策略价 {}, 直接重新开启网格!'.format(self.current_symbol_price, self.all_grid_price[self.critical_index]))
            # 关停maker市价功能
            if self._maker_market_switch_on:
                self._maker_market_switch_on = False
                self._target_maker_quantity = 0
                self._target_maker_side = None
                self._finished_maker_quantity = 0
                self._finished_maker_value = 0
                self._exist_market_poc_order = False

            # 撤销所有挂单，并判断网格区间
            cancel_cmd = Token.ORDER_INFO.copy()
            cancel_cmd['symbol'] = self.symbol_name
            await self.command_transmitter(trans_command=cancel_cmd, token=Token.CANCEL_ALL)
            await self._maintainer_by_price()
            await asyncio.sleep(1)

            self.current_symbol_price = await self._my_executor.get_current_price(self.symbol_name)
            for each_index, each_grid_price in enumerate(self.all_grid_price):
                if each_grid_price <= self.current_symbol_price < (each_grid_price + self._x_price_abs_step):
                    if self.current_symbol_price - each_grid_price <= self._x_price_abs_step / 2:
                        self.critical_index = CircularIndex(value=each_index, max_val=int(self.max_index))
                    else:
                        self.critical_index = CircularIndex(value=each_index + 1, max_val=int(self.max_index))

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

            price_div = calc(calc(self.current_symbol_price, round_step_size(self.initial_entry_price, 1000, upward=True), '-'), 0, '+')
            options_profit = -calc(self._options_price, self.hedge_demanded_options_qty, '*')
            # options_profit = 0
            if price_div < 0:
                options_profit = calc(options_profit, round(abs(price_div)*self.hedge_demanded_options_qty*self._options_multiplier, 2), '+')
            hedge_profit = round(calc(self._trading_statistics['final_profit'], options_profit, '+'), 2)

            showing_texts = '对冲量化网格 统计信息:'
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
            showing_texts += '\n\n执行maker任务:\t{}\n'.format(True if self._maker_market_switch_on else False)
            showing_texts += '当前正确仓位:\t\t{:<10}张\n'.format(self._current_valid_position)
            showing_texts += '累计计算仓位:\t\t{:<10}张\n'.format(self._account_position_theory)
            showing_texts += '累计仓位偏移:\t\t{:<10}张\n\n'.format(self._accumulated_market_quantity)

            showing_texts += '-' * 58
            showing_texts += '\n\n卖单挂单成交次数:\t{:<10}\n'.format(str(self._trading_statistics['filled_sell_order_num']))
            showing_texts += '买单挂单成交次数:\t{:<10}\n'.format(str(self._trading_statistics['filled_buy_order_num']))
            showing_texts += '\n已达成交易量:\t\t{:<20}\t{}\n\n'.format(str(self._trading_statistics['achieved_trade_volume']), self.symbol_name[-4:])
            showing_texts += '-' * 58
            showing_texts += '\n\n区间移动次数:\t\t上移: {:<6} / 下移: {:<6}\n'.format(self.range_stepped_up_time, self.range_stepped_down_time)
            if self.present_abs_running_range_pos > 0:
                showing_texts += '当前区间位置:\t\t+{:<10}\n'.format(self.present_abs_running_range_pos)
            else:
                showing_texts += '当前区间位置:\t\t{:<10}\n'.format(self.present_abs_running_range_pos)
            showing_texts += '当前套利区间:\t\t{:<10} ~  {:<10}\n\n'.format(self.step_down_price, self.step_up_price)

            showing_texts += '-' * 58
            showing_texts += '\n\n已实现套利:\t\t{:<20}\t{}\n'.format(self._trading_statistics['matched_profit'], self.symbol_name[-4:])
            showing_texts += '未实现盈亏:\t\t{:<20}\t{}\n'.format(self._trading_statistics['unmatched_profit'], self.symbol_name[-4:])
            showing_texts += '区间移动修正:\t\t{:<20}\t{}\n'.format(self._trading_statistics['step_down_correction'], self.symbol_name[-4:])

            showing_texts += '\n交易手续费:\t\t{:<20}\t{}\n'.format(self._trading_statistics['total_trading_fees'], self.symbol_name[-4:])

            showing_texts += '\n策略净收益:\t\t{:<20}\t{}\n\n'.format(self._trading_statistics['final_profit'], self.symbol_name[-4:])
            showing_texts += '-' * 58
            showing_texts += '\n\n期权收益参考:\t\t{:<20}\t{}\n'.format(options_profit, self.symbol_name[-4:])
            showing_texts += '\n对冲收益参考:\t\t{:<20}\t{}\n\n'.format(hedge_profit, self.symbol_name[-4:])
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

            showing_texts = '对冲量化网格 等待触发中。。。'
            showing_texts += '\n\n*** {} ***\n\n'.format('=' * 51)

            if days == 0:
                showing_texts += '等待时间\t\t{}:{}:{}\n\n'.format(str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2))
            else:
                showing_texts += '等待时间\t\t{} day\t{}:{}:{}\n\n'.format(
                    str(days), str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2))

            showing_texts += '合约最新价格:\t{:<10}\n\n'.format(str(self.current_symbol_price))
            showing_texts += '网格触发价格:\t{:<10}\n\n'.format(str(self.initial_entry_price))

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
            matched_profit=str(self._trading_statistics['matched_profit']),
            unmatched_profit=str(self._trading_statistics['unmatched_profit'])
        )

    async def show_final_statistics(self) -> str:
        """
        策略结束后，输出最终统计信息
        :return:
        """
        await self._update_trading_statistics()
        return str(self._trading_statistics['final_profit'])

    # interaction methods
    async def report_receiver(self, recv_data_dict: dict, append_info: str = None) -> None:

        if recv_data_dict['status'] == Token.ORDER_FILLED:
            # 传入的id是客户端的自定订单id
            await self._maintain_grid_order(recv_data_dict, append_info, order_filled=True)
            # try:
            #     await self._maintain_grid_order(recv_data_dict, append_info, order_filled=True)
            # except Exception:
            #     self._log_info('___maintain filled order, raise ERROR!!!___')
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
            # todo: 临时方法，需要后续修改，因为无法区分市价maker单是修改的更新还是部分成交的更新
            order_id = recv_data_dict['id']
            this_order_index, this_order_side = self.parse_id(order_id)
            if this_order_index == self.MAKER_MARKET_ID:
                if self._posted_change_poc_order:
                    self._log_info('\n=== maker市价单修改成功\t\t价格: {:<12}\tid: {:<10}'.format(str(float(recv_data_dict['price'])), recv_data_dict['id']))
                    self._posted_change_poc_order = False
                else:
                    # poc 部分成交
                    self._log_info('\n=== maker市价单部分成交!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
                    await self._maintain_maker_market(recv_data_dict, append_info)
            else:
                self._log_info('订单部分成交!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
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
                if append_info == 'label: TOO_MANY_ORDERS\ndetail: limit 50':
                    # todo: 此时该合约挂单数量超过50，需要立即修正挂单，属于临时方法，且貌似只有batch order有这个报错返回
                    self._log_info('$$$ 检测到挂单数量超过50，需要立刻修正挂单')
                    self._need_fix_order = True
            pass
        elif recv_data_dict['status'] == Token.POC_REJECTED:
            # todo: new maintain method
            this_order_index, side = self.parse_id(recv_data_dict['id'])
            if this_order_index == self.MAKER_MARKET_ID:
                self._exist_market_poc_order = False
                self._log_info('=== maker市价挂单失败，重新维护')
            else:
                self._log_info('\npoc挂单失败，价格错位\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
                await self._maintain_grid_order(recv_data_dict, append_info, order_filled=False)
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
        if self._accumulated_market_quantity != 0:
            if abs(self._accumulated_market_quantity) > 12 * self.grid_each_qty:
                self._log_info('*** 累计maker市价单仓位较大，需要市价交易')
                if not self._maker_market_switch_on:
                    self._log_info('*** 市价执行已累计仓位 {} 张'.format(self._accumulated_market_quantity))
                    self._target_maker_side = self.BUY if self._accumulated_market_quantity > 0 else self.SELL
                    self._target_maker_quantity = abs(self._accumulated_market_quantity)
                    self._maker_market_switch_on = True
                    self._accumulated_market_quantity = 0

        # 策略还在运行时，检查最新价格是否偏离过大，
        if self._is_trading:
            if abs(calc(self.current_symbol_price, self.all_grid_price[self.critical_index], '-')) > 5 * self.grid_price_step:
                self._log_info('$$$ 检测到价格偏离过大，策略挂单出现问题')
                self._need_fix_order = True

            # 添加价格维护，构造冗余
            await self._maintainer_by_price()

        # 开启maker市价开关，需要使用功能
        if self._maker_market_switch_on:
            # asyncio.create_task(self._test_maker())
            await self._maker_market_post()

        # 收到修正挂单请求，修正账户挂单
        if self._need_fix_order:
            # 当前价与前一个价格相等时，修正挂单，此时或许挂单变化不大
            if self.previous_price == self.current_symbol_price:
                self._log_info('$$$ price equal, create a fix order coroutine')
                asyncio.create_task(self._fix_open_orders())

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

        # print('\n', initial_index, current_index, all_prices[:5], each_grid_qty, init_pos_price, init_pos_qty, current_price)

        return calc(part_1, part_2, '+')

    @staticmethod
    def gen_timestamp():
        return int(round(time.time() * 1000))

    def __del__(self):
        print('\n{}: {} hedge grid analyzer 实例被删除，释放资源\n'.format(self.stg_num, self.symbol_name))
        pass


class CircularIndex:
    """
    为了实现无限网格操作，使用一个循环索引！
    其功能为类似头尾相接的链表，重新定义加减法，大于小于方法
    """

    def __init__(self, value: int = 0, max_val: int = 100):
        """
        初始会定义索引值和最大索引值，最大值即为列表最大索引
        :param value:
        :param max_val:
        """
        self.value: int = value
        self.max_val: int = max_val

    def __add__(self, other):
        if isinstance(other, CircularIndex):
            add_value = other.value
        elif isinstance(other, int):
            add_value = other
        else:
            add_value = 0
        result = self.value + add_value
        if result > self.max_val:
            result = result % self.max_val - 1
        elif result < 0:
            # 转动不超过一圈
            result = result % self.max_val + 1

        new_index = CircularIndex()
        new_index.value = result
        new_index.max_val = self.max_val
        return new_index

    def __sub__(self, other):
        if isinstance(other, CircularIndex):
            left_value, right_value = self.value, other.value
            if abs(left_value - right_value) < self.max_val / 2:
                return left_value - right_value
            else:
                if left_value < right_value:
                    return self.max_val - abs(left_value - right_value) + 1
                else:
                    return left_value - right_value - self.max_val - 1
        elif isinstance(other, int):
            result = self.value - other
            if result > self.max_val:
                result = result % self.max_val - 1
            elif result < 0:
                result = result % self.max_val + 1
            return CircularIndex(value=result, max_val=self.max_val)
        else:
            raise ValueError('can not minus {} and {}'.format(type(self), type(other)))

    def __lt__(self, other):
        if isinstance(other, CircularIndex):
            if self - other < 0:
                return True
            else:
                return False
        else:
            raise ValueError('can not compare {} and {}'.format(type(self), type(other)))

    def __gt__(self, other):
        if isinstance(other, CircularIndex):
            if self - other > 0:
                return True
            else:
                return False
        else:
            raise ValueError('can not compare {} and {}'.format(type(self), type(other)))

    def __int__(self):
        return self.value

    def __index__(self):
        return self.value

    def copy(self):
        return CircularIndex(value=self.value, max_val=self.max_val)

    def __copy__(self):
        return CircularIndex(value=self.value, max_val=self.max_val)

    def __eq__(self, other):
        if isinstance(other, int):
            return self.value == other
        elif isinstance(other, CircularIndex):
            return self.value == other.value
        else:
            raise ValueError('can not compare {} and {}'.format(type(self), type(other)))

    def __ne__(self, other):
        return not self.__eq__(other)

    def __le__(self, other):
        return self.__lt__(other) or self.__eq__(other)

    def __ge__(self, other):
        return self.__gt__(other) or self.__eq__(other)

    def __repr__(self):
        return str(int(self))

    def __str__(self):
        return str(int(self))

    def __iadd__(self, other):
        self.value += other
        return self

    def __isub__(self, other):
        self.value -= other
        return self

    def __radd__(self, other):
        return self.__add__(other)

    def __hash__(self):
        return hash(int(self))

    @staticmethod
    def Crange(index_1, index_2, step: int = 1) -> list[int]:
        """
        自定义range方法
        :param index_1:
        :param index_2:
        :param step:
        :return: 根据需求，返回整数index列表
        """
        if isinstance(index_1, CircularIndex) and isinstance(index_2, CircularIndex):
            if not index_1.max_val == index_2.max_val:
                raise ValueError('max_val not match')
            if step == 0:
                raise ValueError('step is 0')

            index_list = []
            next_index = index_1
            while True:
                if step > 0 and next_index >= index_2:
                    break
                elif step < 0 and next_index <= index_2:
                    break

                index_list.append(next_index.value)
                next_index = next_index + step

            return index_list

        else:
            raise TypeError('index type not match!')


class LoopList(list):
    """
    重新定义新列表，用于存储价格
    重写切片索引方法，使类似于循环列表
    重写切片赋值方法，使实现循环功能
    """

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            if step == 1 and start > stop:
                return self[start:] + self[:stop]
            else:
                return super().__getitem__(index)

        else:
            return super().__getitem__(index)

    def __setitem__(self, index, value):
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            if step == 1 and start > stop:
                slice_num = len(self) - start
                self[start:] = value[:slice_num]
                self[:stop] = value[slice_num:]
            else:
                return super().__setitem__(index, value)

        else:
            return super().__setitem__(index, value)


if __name__ == '__main__':
    test_index_1 = CircularIndex(99, 100)
    test_index_2 = CircularIndex(3, 100)
    print(test_index_1 - test_index_2)
