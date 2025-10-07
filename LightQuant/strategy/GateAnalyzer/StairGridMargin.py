# -*- coding: utf-8 -*-
# @Time : 2023/2/21 11:10
# @Author : 
# @File : StairGridMargin.py 
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


class StairGridAnalyzerMargin(Analyzer):
    """
    自动补仓看多网格，对接杠杆现货
    合约每上升一定的价格，自动买入仓位
    """

    STG_NAME = '智能调仓网格'

    BUY: str = 'BUY'
    SELL: str = 'SELL'

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

    def __init__(self) -> None:
        super().__init__()
        # ==================== 策略参数保存 ==================== #
        self.symbol_name = None
        self.grid_price_step = None
        self.grid_each_qty = None
        self.filling_quantity = None  # 理论上填单网格数量*每格数量 即可得到该变量
        # 输入相关，仅作为临时存储
        self._x_grid_up_limit = None
        self._x_price_abs_step = None
        self._x_price_rel_step = None
        self._x_filling_price_step = None
        self._x_lower_price_limit = None  # 下方买单价差，防止价格下落时仓位过重
        self._x_filling_quantity = None
        self._x_filling_fund = None
        self._x_each_grid_qty = None

        # ==================== 合约交易规则变量 ==================== #
        self.symbol_price_min_step = None
        self.symbol_quantity_min_step = None
        self.symbol_min_notional = None
        self.symbol_min_order_qty = None
        # 手续费
        self.symbol_maker_fee = 0
        self.symbol_taker_fee = 0

        # ==================== 策略功能相关变量 ==================== #
        self.critical_index = 0
        # 所有网格的价格，由index索引，考虑到无限网格可能会很大，该元祖会随着网格抬升自动添加
        self.all_grid_price: tuple = ()
        # 需要补仓的价格index， 当 critical_index 属于其中时，执行补仓操作，补仓后，删除index以实现到达位置只补仓一次的功能
        self.indices_of_filling: list = []
        # 网格总数量，仅参考用，意义不大
        self.grid_total_num = 0
        self.max_index = 0
        # 上方网格数量，包括 entry index，用处不大
        self.up_grid_num = 0
        # 台阶数量，对应后续可能的最多补仓数量
        self.stairs_total_num = 0
        # 当前处在第几级台阶，即已经补了多少次仓位
        self.present_stair_num = 0
        # 当前最低网格index
        self.present_bottom_index = 0
        # 入场时对标网格的价格
        self.entry_grid_price = 0
        self.entry_index = 0
        # 当前最新价格，实时更新，要求最新
        self.current_symbol_price = 0
        # 自动补单的网格数量间隔
        self.filling_grid_step_num = 0
        # 下方最大网格数量
        self.lower_grid_max_num = 0
        # 设置买卖单最大挂单数量，及最小数量
        self.max_sell_order_num = 12
        self.max_buy_order_num = 30
        self.min_sell_order_num = 5
        self.min_buy_order_num = 10
        # 缓冲数量，单边网格数量过少或过多时增减的网格数量
        self.buffer_buy_num = 3
        self.buffer_sell_num = 5
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

        # 市价下单锁，为True时，不能自动修正仓位
        self._market_order_lock: bool = False

        # todo: 临时功能实现
        # 累计待处理的maker市价单数量
        self._accumulated_market_quantities: list[float] = []
        # 使用一个开关，实现当收到服务器ticker信息时，立刻开启poc下单
        self._maker_market_switch_on: bool = False      # 功能总开关，打开时，会根据参数逐步实现功能
        self._maker_market_lock: bool = False
        self._exist_market_poc_order: bool = False      # 是否存在最新价格附近的poc挂单
        # self._first_post_poc: bool = False              #
        self._posted_change_poc_order: bool = False     # 当前收到的update信息是否是由订单修改造成的，false则代表poc订单部分成交

        self._previous_price = 0
        self._target_maker_side = self.BUY
        self._target_maker_quantity = 0
        self._finished_maker_quantity = 0
        self._finished_maker_value = 0          # 成交价值，用于计算成交均价

        # ==================== 策略统计相关变量 ==================== #
        # # 初始现货仓位，是策略开始时的市价下单，不包括账户开始时存量现货
        # self._initial_position_qty = 0
        # self._initial_position_price = 0
        # 策略开始前，账户存量现货，策略结束后，需要回归该数字
        self._init_account_spot_qty = 0
        # 理论累计计算的现货仓位，可能不需要，可以随时由critical index 和 initial_qty 导出
        self._spot_position_qty_theory = 0
        # 根据当前位置，导出的正确的应有的仓位
        self._current_valid_position = 0

        # 每个台阶做多利润
        self._each_stair_profit = 0

        self._trading_statistics: dict = {
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
            self.symbol_max_mkt_qty = 0
            self.symbol_price_min_step = self.symbol_info['price_min_step']
            self.symbol_quantity_min_step = self.symbol_info['qty_min_step']
            self.symbol_min_notional = self.symbol_info['min_notional']
            self.symbol_min_order_qty = self.symbol_info['min_order_qty']
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

        self._x_grid_up_limit = validated_params['up_price']
        dul_selection = validated_params['dul_selection']
        self._x_price_abs_step = validated_params['price_abs_step']
        self._x_price_rel_step = validated_params['price_rel_step']
        self._x_filling_price_step = validated_params['filling_price_step']
        self._x_lower_price_limit = validated_params['lower_price_limit']
        tri_selection = validated_params['tri_selection']
        self._x_filling_quantity = validated_params['filling_quantity']
        self._x_filling_fund = validated_params['filling_fund']
        self._x_each_grid_qty = validated_params['filling_grid_qty']

        # print('\n获得参数')
        # for key, value in validated_params.items():
        #     print(key, ': ', value)

        symbol_exist = await self._get_trading_rule(validated_params['symbol_name'])

        if symbol_exist:
            self.current_symbol_price = await self._my_executor.get_current_price(validated_params['symbol_name'])

            if self._x_grid_up_limit <= self.current_symbol_price:
                self._x_grid_up_limit = str(self._x_grid_up_limit) + '当前价高于上界'
                param_valid = False
            else:
                self._x_grid_up_limit = round_step_size(self._x_grid_up_limit, self.symbol_price_min_step)

                if dul_selection == 2:
                    self._x_price_abs_step = calc(calc(self._x_price_rel_step, 100, '/'), self.current_symbol_price, '*')
                self._x_price_abs_step = round_step_size(self._x_price_abs_step, self.symbol_price_min_step)

                self._x_price_rel_step = calc(calc(self._x_price_abs_step, self.current_symbol_price, '/'), 100, '*')
                self._x_price_rel_step = round_step_size(self._x_price_rel_step, 0.00001)

                # self._x_filling_price_step = round_step_size(self._x_filling_price_step, self.symbol_price_min_step)
                # self._x_lower_price_limit = round_step_size(self._x_lower_price_limit, self.symbol_price_min_step)

                self.filling_grid_step_num = int(self._x_filling_price_step / self._x_price_abs_step)
                self.lower_grid_max_num = int(self._x_lower_price_limit / self._x_price_abs_step)

                if self.filling_grid_step_num >= 5:
                    self._x_filling_price_step = calc(self.filling_grid_step_num, self._x_price_abs_step, '*')
                else:
                    self._x_filling_price_step = str(self._x_filling_price_step) + '补仓价差过小'
                    param_valid = False

                if param_valid:
                    if self._x_filling_price_step >= (self._x_grid_up_limit - self.current_symbol_price):
                        self._x_filling_price_step = str(self._x_filling_price_step) + '补仓次数小于1'
                        param_valid = False

                if self.lower_grid_max_num >= 3:
                    self._x_lower_price_limit = calc(self.lower_grid_max_num, self._x_price_abs_step, '*')
                else:
                    self._x_lower_price_limit = str(self._x_lower_price_limit) + '下方价差过小'
                    param_valid = False

                # 该逻辑下最小仓位是一个格子的仓位
                if param_valid:  # 上边没有问题才判断之后的
                    if tri_selection == 1:
                        self._x_each_grid_qty = self._x_filling_quantity / self.filling_grid_step_num
                    elif tri_selection == 2:
                        self._x_filling_quantity = self._x_filling_fund / self.current_symbol_price
                        self._x_each_grid_qty = self._x_filling_quantity / self.filling_grid_step_num
                    elif tri_selection == 3:
                        pass
                    self._x_each_grid_qty = round_step_size(self._x_each_grid_qty, self.symbol_quantity_min_step)
                    self._x_filling_quantity = calc(self.filling_grid_step_num, self._x_each_grid_qty, '*')
                    self._x_filling_fund = calc(self.current_symbol_price, self._x_filling_quantity, '*')

                    # min notional
                    if calc(self.current_symbol_price * 0.95, self._x_each_grid_qty, '*') <= self.symbol_min_notional:
                        # 每次下单小于最小价值，下单不会成功
                        self._x_each_grid_qty = str(self._x_each_grid_qty) + '低于最小价值'
                        param_valid = False

                    if param_valid:
                        if self._x_each_grid_qty < self.symbol_min_order_qty:
                            # 每次下单小于最小价值，下单不会成功
                            self._x_each_grid_qty = str(self._x_each_grid_qty) + '低于最小数量'
                            param_valid = False

        else:
            validated_params['symbol_name'] += '未查询到该合约'
            param_valid = False

        validated_params['up_price'] = self._x_grid_up_limit
        validated_params['price_abs_step'] = self._x_price_abs_step
        validated_params['price_rel_step'] = self._x_price_rel_step
        validated_params['filling_price_step'] = self._x_filling_price_step
        validated_params['lower_price_limit'] = self._x_lower_price_limit
        validated_params['filling_quantity'] = self._x_filling_quantity
        validated_params['filling_fund'] = self._x_filling_fund
        validated_params['filling_grid_qty'] = self._x_each_grid_qty
        validated_params['valid'] = param_valid

        return validated_params

    async def param_ref_info(self, valid_param_dict: dict) -> str:
        symbol_name = valid_param_dict['symbol_name']

        info_texts: str = """\n"""
        info_texts += '*** {} ***\n'.format('=' * 32)
        self.current_symbol_price = await self._my_executor.get_current_price(symbol_name)
        info_texts += '\n当前时间: {}\n'.format(str(pd.to_datetime(self.gen_timestamp(), unit='ms')))
        info_texts += '\n合约名称: {}\t\t\t当前价格: {}\n'.format(symbol_name, str(self.current_symbol_price))

        self.derive_functional_variables()
        # 初次近场的价格及下方的所有价格
        stair_0_prices = list(self.all_grid_price[:self.entry_index + 1])
        # last_filling_index = self.indices_of_filling[-1]
        last_stair_bottom_price = \
            calc(self.entry_grid_price, calc(self.grid_price_step, (self.indices_of_filling[-1] - self.lower_grid_max_num - self.entry_index), '*'), '+')
        # todo: test this price
        # print('入场价:\t\t{}'.format(self.entry_grid_price))
        # print('最高台阶最低价:\t{}'.format(last_stair_bottom_price))
        # 最后一次补仓的价格及下方的所有价格
        stair_last_prices = [calc(last_stair_bottom_price, calc(self.grid_price_step, i, '*'), '+') for i in range(self.lower_grid_max_num + 1)]
        # print('最高台阶最高价:\t{}'.format(stair_last_prices[-1]))

        min_filling_fund_consume = calc(self.filling_quantity, self.current_symbol_price, '*')
        max_filling_fund_consume = calc(self.filling_quantity, stair_last_prices[-1], '*')

        max_holding_quantity = calc(self.filling_quantity, calc(self.grid_each_qty, self.lower_grid_max_num, '*'), '+')

        min_max_fund_consume = calc(min_filling_fund_consume, calc(calc_sum(stair_0_prices[:-1]), self.grid_each_qty, '*'), '+')
        max_max_fund_consume = calc(max_filling_fund_consume, calc(calc_sum(stair_last_prices[:-1]), self.grid_each_qty, '*'), '+')

        # init_account_spot_requirement = 0
        # if self.max_buy_order_num > self.filling_grid_step_num:
        #     init_account_spot_requirement = calc((self.max_buy_order_num - self.filling_grid_step_num), self.grid_each_qty, '*')
        init_account_spot_requirement = calc((self.max_sell_order_num + 3), self.grid_each_qty, '*')

        suggested_account_fund_low = max(0.9 * min_max_fund_consume, 1.2 * max_filling_fund_consume)
        suggested_account_fund_high = 0.8 * max_max_fund_consume

        info_texts += '\n网格总数量\t\t{:<8}\n'.format(str(self.grid_total_num))
        info_texts += '调仓间隔网格数量\t\t{:<8}\n'.format(str(self.filling_grid_step_num))
        info_texts += '最多补仓次数\t\t{:<8}\n'.format(str(self.stairs_total_num))

        info_texts += '\n网格价差占比\t\t{:<8}\t{:<8}\n'.format(str(round(self.grid_price_step / self.current_symbol_price * 100, 6)), '%')
        info_texts += '每格套利利润\t\t{:<8}\t{:<8}\n'.format((str(calc(self.grid_each_qty, self.grid_price_step, '*'))), symbol_name[-4:])

        info_texts += '\n补仓买入数量\t\t{:<8}\t\t{:<8}\n'.format(str(self.filling_quantity), symbol_name[:-4].replace('_', ''))
        info_texts += '补仓花费金额\t\t{:<8}\t\t{:<8}\t最小\n'.format(str(round(min_filling_fund_consume, 2)), symbol_name[-4:])
        info_texts += '          \t\t\t{:<8}\t\t{:<8}\t最大\n'.format(str(round(max_filling_fund_consume, 2)), symbol_name[-4:])

        info_texts += '\n最大持有仓位\t\t{:<8}\t\t{:<8}\n'.format(str(max_holding_quantity), symbol_name[:-4].replace('_', ''))
        info_texts += '最大持仓花费\t\t{:<8}\t\t{:<8}\t最小\n'.format(str(round(min_max_fund_consume, 2)), symbol_name[-4:])
        info_texts += '          \t\t\t{:<8}\t\t{:<8}\t最大\n'.format(str(round(max_max_fund_consume, 2)), symbol_name[-4:])

        info_texts += '\n初始要求现货持有\t\t{:<8}\t\t{:<8}\n'.format(str(init_account_spot_requirement), symbol_name[:-4].replace('_', ''))

        info_texts += '\n建议账户资金\t\t{:<16}~ {:<16}\t$\n'.format(str(round(suggested_account_fund_low, 2)), str(round(suggested_account_fund_high, 2)))
        info_texts += '\n*** {} ***'.format('=' * 32)

        return info_texts

    def confirm_params(self, input_params: dict) -> None:
        """

        :param input_params:
        :return:
        """
        # 按照当前逻辑，此时本地保存的均是合理的参数，只有symbol name信息传递
        self.symbol_name = input_params['symbol_name']
        # self.grid_price_step = self._x_price_abs_step
        # self.grid_each_qty = self._x_each_grid_qty
        # self.filling_quantity = self._x_filling_quantity
        # self.derive_functional_variables()

        # self._x_grid_up_limit = input_params['up_price']
        # self._x_price_abs_step = input_params['price_abs_step']
        # self._x_price_rel_step = input_params['price_rel_step']
        # self._x_filling_price_step = input_params['filling_price_step']
        # self._x_lower_price_limit = input_params['lower_price_limit']
        # self._x_filling_quantity = input_params['filling_quantity']
        # self._x_filling_fund = input_params['filling_fund']
        # self._x_each_grid_qty = input_params['filling_grid_qty']
        self._my_executor.start_single_contract_order_subscription(self.symbol_name)
        self._my_executor.start_single_contract_ticker_subscription(self.symbol_name)

    def derive_functional_variables(self) -> None:
        """
        根据本地保存的输入参数，导出并存储策略运行所需要的变量
        在弹出参考信息，和策略点击开始运行 两处，都要使用，在得到当前价格后使用
        :return:
        """
        self.grid_price_step = self._x_price_abs_step
        self.grid_each_qty = self._x_each_grid_qty
        self.filling_quantity = self._x_filling_quantity
        # 根据当前价格，给出 entry price，最新价格在参考信息和 策略开始运行两处都会使用
        high_price = calc(self._x_grid_up_limit, round_step_size(calc(self._x_grid_up_limit, self.current_symbol_price, '-'), self.grid_price_step), '-')
        low_price = calc(high_price, self.grid_price_step, '-')
        if high_price - self.current_symbol_price <= self.grid_price_step / 2:
            self.entry_grid_price = high_price
        else:
            self.entry_grid_price = low_price
        self.entry_index = self.lower_grid_max_num
        self.critical_index = self.entry_index
        # 从入场网格到最上方价格的所有网格数量，包括入场的entry index
        self.up_grid_num = int(calc(self._x_grid_up_limit, self.entry_grid_price, '-') / self.grid_price_step) + 1
        self.grid_total_num = self.up_grid_num + self.lower_grid_max_num
        self.max_index = self.grid_total_num - 1
        add_index = self.entry_index
        self.indices_of_filling.clear()
        while True:
            add_index += self.filling_grid_step_num
            if add_index < self.max_index:
                self.indices_of_filling.append(add_index)
            else:
                break
        # print('补仓index: ', self.indices_of_filling)
        self.stairs_total_num = len(self.indices_of_filling)

        bottom_price = calc(self.entry_grid_price, calc(self.grid_price_step, self.lower_grid_max_num, '*'), '-')
        # 此处计算从最底部到 entry index 的所有价格
        self.all_grid_price = tuple(calc(bottom_price, calc(self.grid_price_step, i, '*'), '+') for i in range(self.lower_grid_max_num + 1))
        self._add_stair(add_num=int(self.max_sell_order_num / self.filling_grid_step_num) + 2)  # 初始时使用的 prices

        self._each_stair_profit = self.unmatched_profit_calc(
            initial_index=self.entry_index,
            current_index=self.indices_of_filling[0],
            all_prices=self.all_grid_price,
            each_grid_qty=self.grid_each_qty,
            init_pos_price=self.entry_grid_price,
            init_pos_qty=self.filling_quantity
        )
        # print('\n\n每个台阶实现利润: {} $'.format(self._each_stair_profit))
        # print('critical_index = {}'.format(self.critical_index))
        # print(str(self.current_symbol_price))
        # print(str(self.all_grid_price[self.critical_index]))

    def derive_valid_position(self) -> None:
        """
        根据当前的index，得到当前理论所需仓位
        :return:
        """
        if self.present_stair_num < self.stairs_total_num:
            if self.critical_index == self.indices_of_filling[0]:
                self._current_valid_position = self.filling_quantity
            else:
                self._current_valid_position = calc((self.indices_of_filling[0] - self.critical_index), self.grid_each_qty, '*')
        else:
            self._current_valid_position = calc((self.max_index - self.critical_index), self.grid_each_qty, '*')

        # 最后加上账户初始仓位
        self._current_valid_position = calc(self._current_valid_position, self._init_account_spot_qty, '+')

    def acquire_token(self, stg_code: str) -> None:
        # todo: 考虑添加至基类
        self.stg_num = stg_code
        self.stg_num_len = len(stg_code)

    # def start(self) -> None:
    #     pass

    def stop(self) -> None:
        asyncio.create_task(self._terminate_trading(reason='人工手动结束'))
        # asyncio.create_task(self._terminate_maker_market())

    async def _start_strategy(self):
        """
        程序开始操作，整个程序的起点
        :return:
        """
        self._is_trading = True
        self._log_info('智能调仓网格策略开始')

        # 开启数据统计
        self._update_text_task = asyncio.create_task(self._update_detail_info(interval_time=1))
        fee_dict = await self._my_executor.get_symbol_trade_fee(self.symbol_name)
        self.symbol_maker_fee = fee_dict['maker_fee']
        self.symbol_taker_fee = fee_dict['taker_fee']
        self._log_info('maker fee rate: {}'.format(self.symbol_maker_fee))
        self._log_info('taker fee rate: {}'.format(self.symbol_taker_fee))

        self._init_account_spot_qty = await self._my_executor.get_current_asset_qty(self.symbol_name)
        self._log_info('策略前账户现货仓位 {}'.format(self._init_account_spot_qty))
        self._spot_position_qty_theory = self._init_account_spot_qty

        # 开始撒网
        asyncio.create_task(self._layout_net())

        # self._trading_statistics['strategy_start_time'] = self.gen_timestamp()
        # self._target_maker_side = self.BUY
        # self._target_maker_quantity = self.filling_quantity
        # self._maker_market_switch_on = True

    # strategy methods
    def _add_stair(self, add_num: int = 1) -> None:
        """
        动态的添加所有网格价格（因为无限网格的数量可能达到几十万，一次性计算完成需要耗费太多时间，所以用动态分批次添加）
        :param add_num: 添加的台阶数量
        :return:
        """
        end_price = self.all_grid_price[-1]
        # 实际上，由于max_index的存在，就算添加的网格价格超出了界限，也没关系
        range_end_index = len(self.all_grid_price) + self.filling_grid_step_num * add_num - 1
        if range_end_index <= self.max_index:
            max_range = self.filling_grid_step_num * add_num + 1
        else:
            max_range = self.grid_total_num - len(self.all_grid_price) + 1

        add_grid_price = tuple(calc(end_price, calc(self.grid_price_step, i, '*'), '+') for i in range(1, max_range))
        self.all_grid_price += add_grid_price

    async def _maker_market_post(self) -> None:
        """
        根据已经设置的一些参数，实现maker市价单功能，发送信息部分

        操作：

            1. 如果存在已有挂单，且价格远离期望，则修改现有挂单价格
            2. 如果存在已有挂单，而价格不变，则不操作
            3. 如果没有挂单，则在最新价格附近挂单

        :return:
        """
        # if self._maker_market_lock:
        #     self._log_info('存在锁，不更新maker市价单')
        #     return
        # # 开启锁，该锁在直到需要更新挂单时，才会关闭
        # self._maker_market_lock = True
        price_step = self.symbol_price_min_step
        if self._exist_market_poc_order:
            if self.current_symbol_price == self._previous_price:
                # 价格相等，等待成交，不操作
                self._log_info('价格 {} 不变，等待吃单'.format(self.current_symbol_price))
                pass
            else:
                if self._target_maker_side == self.BUY and self.current_symbol_price > self._previous_price:
                    self._log_info('价格上漂，修改订单追多')
                    # todo : work here, do
                    new_price = calc(self.current_symbol_price, price_step, '-')
                    self._log_info('当前最新价格:\t{}'.format(self.current_symbol_price))
                    self._log_info('修改订单价格:\t{}'.format(new_price))

                    amend_order = Token.ORDER_INFO.copy()
                    amend_order['symbol'] = self.symbol_name
                    amend_order['id'] = self.gen_id(99999998, self._target_maker_side)
                    amend_order['price'] = new_price
                    self._posted_change_poc_order = True
                    await self.command_transmitter(trans_command=amend_order, token=Token.AMEND_POC_PRICE)
                elif self._target_maker_side == self.SELL and self.current_symbol_price < self._previous_price:
                    self._log_info('价格下落，修改订单追空')
                    new_price = calc(self.current_symbol_price, price_step, '+')
                    self._log_info('当前最新价格:\t{}'.format(self.current_symbol_price))
                    self._log_info('修改订单价格:\t{}'.format(new_price))

                    amend_order = Token.ORDER_INFO.copy()
                    amend_order['symbol'] = self.symbol_name
                    amend_order['id'] = self.gen_id(99999998, self._target_maker_side)
                    amend_order['price'] = new_price
                    self._posted_change_poc_order = True
                    await self.command_transmitter(trans_command=amend_order, token=Token.AMEND_POC_PRICE)
                elif self._target_maker_side == self.BUY and self.current_symbol_price == calc(self._previous_price, price_step, '-'):
                    self._log_info('买挂单正在成交中')
                elif self._target_maker_side == self.SELL and self.current_symbol_price == calc(self._previous_price, price_step, '+'):
                    self._log_info('卖挂单正在成交中')
                else:
                    # todo 此时也要修改挂单，因为存在修改挂单失败的情况
                    self._log_info('价格吃回挂单价，不合理, current_price = {}\tprevious_price = {}'.format(self.current_symbol_price, self._previous_price))
                    if self._target_maker_side == self.BUY:
                        self._log_info('价格变化，修改多单')
                        new_price = calc(self.current_symbol_price, price_step, '-')
                        self._log_info('当前最新价格:\t{}'.format(self.current_symbol_price))
                        self._log_info('修改订单价格:\t{}'.format(new_price))

                        amend_order = Token.ORDER_INFO.copy()
                        amend_order['symbol'] = self.symbol_name
                        amend_order['id'] = self.gen_id(99999998, self._target_maker_side)
                        amend_order['price'] = new_price
                        self._posted_change_poc_order = True
                        await self.command_transmitter(trans_command=amend_order, token=Token.AMEND_POC_PRICE)
                    elif self._target_maker_side == self.SELL:
                        self._log_info('价格变化，修改空单')
                        new_price = calc(self.current_symbol_price, price_step, '+')
                        self._log_info('当前最新价格:\t{}'.format(self.current_symbol_price))
                        self._log_info('修改订单价格:\t{}'.format(new_price))

                        amend_order = Token.ORDER_INFO.copy()
                        amend_order['symbol'] = self.symbol_name
                        amend_order['id'] = self.gen_id(99999998, self._target_maker_side)
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
            maker_order['id'] = self.gen_id(99999998, self._target_maker_side)
            maker_order['price'] = post_price
            maker_order['side'] = self._target_maker_side
            maker_order['quantity'] = self.filling_quantity
            self._log_info('\n\nmaker市价下单')
            self._log_info('下单时合约价格:\t{}'.format(self.current_symbol_price))
            self._log_info('下单价格:\t\t{}'.format(maker_order['price']))
            await self.command_transmitter(trans_command=maker_order, token=Token.TO_POST_POC)

            self._exist_market_poc_order = True

    async def _layout_net(self):
        self._trading_statistics['strategy_start_time'] = self.gen_timestamp()
        self.current_symbol_price = await self._my_executor.get_current_price(self.symbol_name)
        self.derive_functional_variables()
        if not (self.current_symbol_price < self._x_grid_up_limit):
            self._log_info('价格在范围外，需要手动终止策略')
            return

        # maker 市价下单
        self._target_maker_side = self.BUY
        self._target_maker_quantity = self.filling_quantity
        self._maker_market_switch_on = True
        # await asyncio.sleep(3)  # 等待一定时间买入

        # 布撒网格，使用batch order操作
        ini_buy_order_num = round((self.min_buy_order_num + self.max_buy_order_num) / 2)
        ini_sell_order_num = round((self.min_sell_order_num + self.max_sell_order_num) / 2)
        self.open_buy_orders = [
            {
                'id': self.gen_id(_index, self.BUY),
                'status': 'NEW',
                'time': self.gen_timestamp()
            } for _index in range(max(0, self.critical_index - ini_buy_order_num), self.critical_index)
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
            temp_buy_indices, temp_post_buy = temp_buy_indices[:-5], temp_buy_indices[-5:]
            temp_sell_indices, temp_post_sell = temp_sell_indices[5:], temp_sell_indices[:5]
            if len(temp_post_buy):
                batch_buy_command = Token.BATCH_ORDER_INFO.copy()
                batch_buy_command['orders'] = [
                    {
                        'symbol': self.symbol_name,
                        'id': each['id'],
                        'price': self.all_grid_price[self.parse_id(each['id'])[0]],
                        'side': self.BUY,
                        'quantity': self.grid_each_qty,
                        'status': Token.TO_POST_LIMIT
                    } for each in temp_post_buy
                ]
                await self.command_transmitter(trans_command=batch_buy_command, token=Token.TO_POST_BATCH)
            if len(temp_post_sell):
                batch_sell_command = Token.BATCH_ORDER_INFO.copy()
                batch_sell_command['orders'] = [
                    {
                        'symbol': self.symbol_name,
                        'id': each['id'],
                        'price': self.all_grid_price[self.parse_id(each['id'])[0]],
                        'side': self.SELL,
                        'quantity': self.grid_each_qty,
                        'status': Token.TO_POST_LIMIT
                    } for each in temp_post_sell
                ]
                await self.command_transmitter(trans_command=batch_sell_command, token=Token.TO_POST_BATCH)

            if len(temp_buy_indices) == 0 and len(temp_sell_indices) == 0:
                break
            # # 减缓撒网速度
            # await asyncio.sleep(0.3)

    async def _maintain_test_maker(self, order_info: dict, append_info: str) -> None:
        """
        todo: 该函数用于测试 maker 市价下单功能
        用于维护maker市价单部分成交后的功能
        属于收到信息部分
        :return:
        """
        self._log_info('维护信息:\n')
        # this_quantity = float(order_info['quantity'])
        left_quantity = float(append_info.split('=')[-1])
        this_quantity = calc(calc(self._target_maker_quantity, self._finished_maker_quantity, '-'), left_quantity, '-')
        self._finished_maker_quantity = calc(self._target_maker_quantity, left_quantity, '-')
        percent = round(self._finished_maker_quantity / self._target_maker_quantity * 100, 3)
        deal_price = float(order_info['price'])
        adding_volume = calc(this_quantity, deal_price, '*')
        self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
        self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')
        self._finished_maker_value = calc(self._finished_maker_value, adding_volume, '+')

        self._log_info('本次成交数量: {}'.format(this_quantity))
        self._log_info('目标进度\t{} / {}\t{} %'.format(self._finished_maker_quantity, self._target_maker_quantity, percent))

    async def _maintain_grid_order(self, data_dict: dict, append_info: str = None) -> None:
        """
        维护调仓网格，在原有网格维护的逻辑上，添加补仓功能
        :param data_dict: 规范化订单信息
        :param append_info:
        :return:
        """
        filled_order_id = data_dict['id']
        this_order_index, this_order_side = self.parse_id(filled_order_id)

        # 最先考虑maker市价单
        if this_order_index == 99999998:
            # todo: 测试用id
            # await self._maintain_test_maker()
            self._log_info('\n\nmaker市价单完全成交')
            # 完全成交，目的已达成，最终统计，并归零参数

            adding_quantity = calc(self._target_maker_quantity, self._finished_maker_quantity, '-')
            deal_price = float(data_dict['price'])
            adding_volume = calc(adding_quantity, deal_price, '*')
            self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
            self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')
            self._finished_maker_value = calc(self._finished_maker_value, adding_volume, '+')
            avg_deal_price = calc(self._finished_maker_value, self._target_maker_quantity, '/')
            self._log_info('成交均价:\t{}'.format(avg_deal_price))

            self._maker_market_switch_on = False
            self._target_maker_quantity = 0
            self._target_maker_side = None
            self._finished_maker_quantity = 0
            self._finished_maker_value = 0
            self._exist_market_poc_order = False
            return

        if not self._is_trading:
            self._log_info('交易结束，不继续维护网格 order_id: {}'.format(filled_order_id))
            return

        # 1.市价单以及网格上边界退出
        if append_info:
            self._log_info(append_info)
        self._log_info('维护网格\t\t\t网格位置 = {}'.format(self.critical_index))
        # 以 critical index 为基准进行维护

        if this_order_index == 99999999:
            # todo 市价下单的index, 只需要统计信息，不需要维护网格，因此用一个统一的数字
            self._log_info('\n市价挂单成交')
            return

        elif this_order_index == self.max_index:
            self._log_info('达到网格上边界，退出策略')

            self.open_sell_orders = []
            filled_sell_num = this_order_index - self.critical_index
            self._trading_statistics['filled_sell_order_num'] += filled_sell_num
            adding_volume = calc_sum([calc(each_price, self.grid_each_qty, '*') for each_price in
                                      self.all_grid_price[self.critical_index + 1:this_order_index + 1]])
            self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
            self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

            self._spot_position_qty_theory = calc(self._spot_position_qty_theory, calc(filled_sell_num, self.grid_each_qty, '*'), '-')

            self.critical_index = this_order_index

            # await self._terminate_trading(reason='达到网格上边界')
            asyncio.create_task(self._terminate_trading(reason='达到网格上边界'))
            return

        elif this_order_index == -1:
            self._log_info('unknown client_id: {}\nplz check code'.format(this_order_side))
            return

        # 2.根据成交情况在中心填补买卖单
        filled_indices = []     # 用于判断是否需要补单
        if this_order_index > self.critical_index:
            # 只有价格向上冲到位置才需要补单
            filled_indices = [_i for _i in range(self.critical_index + 1, this_order_index + 1)]
            # 高价位的订单成交
            if this_order_side == self.SELL:
                # 上方卖单成交，维护网格
                # 需要瞬间补上的订单数量
                instant_post_num = this_order_index - self.critical_index
                self._trading_statistics['filled_sell_order_num'] += instant_post_num
                adding_volume = calc_sum([calc(each_price, self.grid_each_qty, '*') for each_price in
                                          self.all_grid_price[self.critical_index + 1:this_order_index + 1]])
                self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
                self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

                self._spot_position_qty_theory = calc(self._spot_position_qty_theory, calc(instant_post_num, self.grid_each_qty, '*'), '-')
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
                        instant_post_batch, instant_post_buy = instant_post_buy[:5], instant_post_buy[5:]

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
                        self._log_info('批量挂买单')
                        await self.command_transmitter(trans_command=batch_order, token=Token.TO_POST_BATCH)

                self.critical_index = this_order_index

            elif this_order_side == self.BUY:
                # 上方买单成交，出现快速行情，已经提前反应
                self._log_info('{}买 -{:2} 订单成交\t\t价格: {:<12}\tid: {:<10}\t\t已提前做出反应'.format
                               (chr(12288), str(this_order_index - self.critical_index), str(self.all_grid_price[this_order_index]), filled_order_id))
                # self._log_info('买 -{} 订单成交，价格 {} ,已提前做出反应'.format(str(this_order_index - self.critical_index), str(self.all_grid_price[this_order_index])))
            else:
                self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

        elif this_order_index < self.critical_index:
            # 低价位的订单成交
            if this_order_side == self.BUY:
                # 下方买单成交，维护网格
                instant_post_num = self.critical_index - this_order_index
                self._trading_statistics['filled_buy_order_num'] += instant_post_num
                adding_volume = calc_sum([calc(each_price, self.grid_each_qty, '*') for each_price in
                                          self.all_grid_price[this_order_index:self.critical_index]])
                self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
                self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

                self._spot_position_qty_theory = calc(calc(instant_post_num, self.grid_each_qty, '*'), self._spot_position_qty_theory, '+')
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
                            # self._log_info('在 {} 价位挂卖单, id: {}'.format((str(posting_order['price'])), posting_order['id']))
                            await self.command_transmitter(trans_command=posting_order, token=Token.TO_POST_POC)
                        break
                    else:
                        instant_post_batch, instant_post_sell = instant_post_sell[:5], instant_post_sell[5:]

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
                        self._log_info('批量挂卖单')
                        await self.command_transmitter(trans_command=batch_order, token=Token.TO_POST_BATCH)

                self.critical_index = this_order_index

            elif this_order_side == self.SELL:
                # 下方卖单成交，出现快速行情，已经提前反应
                self._log_info('{}卖 -{:2} 订单成交\t\t价格: {:<12}\tid: {:<10}\t\t已提前做出反应'.format
                               (chr(12288), str(self.critical_index - this_order_index), str(self.all_grid_price[this_order_index]), filled_order_id))
                # self._log_info('卖 -{} 订单成交，价格 {} ,已提前做出反应'.format(str(this_order_index - self.critical_index), str(self.all_grid_price[this_order_index])))
            else:
                self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

        else:
            # self._log_info('unexpected case that order at critical_index is filled, plz recheck\nid: {}'.format(filled_order_id))
            if this_order_side == self.BUY:
                self._log_info('{}买  {:2} 订单成交\t\t价格: {:<12}\tid: {:<10}\t\t延迟有点大'.format
                               (chr(12288), str(0), str(self.all_grid_price[this_order_index]), filled_order_id))
            elif this_order_side == self.SELL:
                self._log_info('{}卖  {:2} 订单成交\t\t价格: {:<12}\tid: {:<10}\t\t延迟有点大'.format
                               (chr(12288), str(0), str(self.all_grid_price[this_order_index]), filled_order_id))
            else:
                self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

        # 3.在特定位置补充仓位，撤销多余挂单
        filled_time = 0
        for each_filled_index in filled_indices:
            # todo: 此处判断可以提升效率
            if each_filled_index in self.indices_of_filling:
                if each_filled_index == self.indices_of_filling[0]:
                    # 正常达到台阶位置，正常补单
                    self._log_info('\n达到调仓点位 {}，市价补仓\t{}\t{}\n'.format(
                        str.zfill(str(each_filled_index), 8), self.filling_quantity, self.symbol_name[:-4].replace('_', '')))

                    if filled_time == 0:
                        # command = Token.ORDER_INFO.copy()
                        # command['side'] = self.BUY
                        # command['quantity'] = self.filling_quantity
                        # await self.command_transmitter(trans_command=command, token=Token.TO_POST_MARKET)
                        # self._market_locker_task = asyncio.create_task(self._market_order_locker())

                        self._spot_position_qty_theory = calc(self._spot_position_qty_theory, self.filling_quantity, '+')

                        if self._maker_market_switch_on:
                            self._log_info('存在maker市价任务，延后补仓')
                            self._accumulated_market_quantities.append(self.filling_quantity)
                        else:
                            self._target_maker_quantity = self.filling_quantity
                            self._target_maker_side = self.BUY
                            self._maker_market_switch_on = True

                        # 理论计算的交易量
                        # adding_volume = calc(self.filling_quantity, self.all_grid_price[each_filled_index], '*')
                        # self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
                        # self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_taker_fee, '*'), '+')
                    else:
                        self._log_info('\n行情剧烈，一次跨越多个补单点位\n')
                        self._log_info(str(filled_indices))

                    # 如果一次成交很多挂单，则只补仓一次
                    filled_time += 1

                    self._add_stair()
                    # 删除该index，防止重复补仓
                    self.indices_of_filling.pop(0)
                    self.present_stair_num += 1
                    self.present_bottom_index += self.filling_grid_step_num

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

                else:
                    # 没有正常达到台阶，可能出现跨级现象
                    self._log_info('\n存在台阶跨越，请检查成交挂单\n')
                    pass

        # 4.检查买卖单数量并维护其边界挂单，补单全用batch order
        # 买单挂单维护
        if len(self.open_buy_orders) > self.max_buy_order_num:
            post_cancel, self.open_buy_orders = self.open_buy_orders[:self.buffer_buy_num], self.open_buy_orders[self.buffer_buy_num:]
            for each_info in post_cancel:
                cancel_cmd = Token.ORDER_INFO.copy()
                cancel_cmd['symbol'] = self.symbol_name
                cancel_cmd['id'] = each_info['id']
                await self.command_transmitter(trans_command=cancel_cmd, token=Token.TO_CANCEL)

        elif 0 < len(self.open_buy_orders) < self.min_buy_order_num:
            endpoint_index = self.parse_id(self.open_buy_orders[0]['id'])[0]
            if endpoint_index > self.present_bottom_index:
                # <= 时，下方挂单已经达到下边界，不补充挂单
                filling_post_buy: list = [
                    {
                        'id': self.gen_id(each_index, self.BUY),
                        'status': 'NEW',
                        'time': self.gen_timestamp()
                    } for each_index in range(max(self.present_bottom_index, endpoint_index - self.buffer_buy_num), endpoint_index)
                ]
                self.open_buy_orders = filling_post_buy + self.open_buy_orders
                while True:
                    if len(filling_post_buy) == 0:
                        break
                    filling_post_batch, filling_post_buy = filling_post_buy[:5], filling_post_buy[5:]
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
                    await self.command_transmitter(trans_command=filling_batch_cmd, token=Token.TO_POST_BATCH)

        # 卖单挂单维护
        if len(self.open_sell_orders) > self.max_sell_order_num:
            self.open_sell_orders, post_cancel = self.open_sell_orders[:-self.buffer_sell_num], self.open_sell_orders[-self.buffer_sell_num:]
            for each_info in post_cancel:
                cancel_cmd = Token.ORDER_INFO.copy()
                cancel_cmd['symbol'] = self.symbol_name
                cancel_cmd['id'] = each_info['id']
                await self.command_transmitter(trans_command=cancel_cmd, token=Token.TO_CANCEL)

        elif 0 < len(self.open_sell_orders) < self.min_sell_order_num:
            endpoint_index = self.parse_id(self.open_sell_orders[-1]['id'])[0]
            if endpoint_index < self.max_index:
                # 否则已经达到边界，不补充挂单
                filling_post_sell: list = [
                    {
                        'id': self.gen_id(each_index, self.SELL),
                        'status': 'NEW',
                        'time': self.gen_timestamp()
                    } for each_index in range(endpoint_index + 1, min(self.max_index, endpoint_index + self.buffer_sell_num) + 1)
                ]
                self.open_sell_orders = self.open_sell_orders + filling_post_sell
                while True:
                    if len(filling_post_sell) == 0:
                        break
                    filling_post_batch, filling_post_sell = filling_post_sell[:5], filling_post_sell[5:]
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
                    await self.command_transmitter(trans_command=filling_batch_cmd, token=Token.TO_POST_BATCH)

        # 5.最后根据需要更新统计信息
        if (self._trading_statistics['filled_buy_order_num'] + self._trading_statistics['filled_sell_order_num']) % 10 == 0:
            # todo: 存在问题，有没有一种可能，导致一直是else，且任务没有实际运行，直接同样用市价下单锁就完事了！！！，不整这么复杂，检查以完成的task能否再cancel不报错
            # if not self._fix_position_task:
            #     self._fix_position_task = asyncio.create_task(self._fix_position())
            # else:
            #     self._log_info('存在校验仓差任务，不开启新任务')
            # todo: 测试新逻辑
            if self._fix_position_task:
                self._fix_position_task: asyncio.coroutine
                if self._fix_position_task.done():
                    # 旧任务已完成，再次执行
                    self._fix_position_task = asyncio.create_task(self._fix_position())
                else:
                    self._log_info('存在执行中的校验仓差任务，不开启新任务')
            else:
                self._log_info('首次开启校验仓差任务')
                self._fix_position_task = asyncio.create_task(self._fix_position())

    async def _terminate_maker_market(self) -> None:
        """
        同样以maker形式市价平仓
        :return:
        """
        if not self._is_trading:
            return

        self._update_text_task.cancel()
        self._log_info('maker市价平仓')
        if self._target_maker_side == self.BUY:
            self._target_maker_side = self.SELL
        else:
            self._target_maker_side == self.BUY
        self._target_maker_quantity = self.filling_quantity
        self._maker_market_switch_on = True
        self._log_info('再度开启开关')
        await self._update_trading_statistics()

        # 循环等待直到全部完成
        while True:
            await asyncio.sleep(1)
            if not self._maker_market_switch_on:
                self._is_trading = False
                break

        self._log_info('终止策略，终止原因: 停止测试')
        await self._update_detail_info(only_once=True)

        self._my_logger.close_file()

        self._my_executor.stop_single_contract_order_subscription(self.symbol_name)
        self._my_executor.stop_single_contract_ticker_subscription(self.symbol_name)
        self._my_executor.strategy_stopped(self.stg_num)
        self._bound_running_column = None

    async def _terminate_trading(self, reason: str = '') -> None:
        if not self._is_trading:
            return
        self._is_trading = False

        self._update_text_task.cancel()
        if self._market_locker_task:
            self._market_locker_task.cancel()
        if self._fix_position_task:
            self._log_info('停止仓位修正任务')
            self._fix_position_task.cancel()

        cancel_cmd, close_cmd = Token.ORDER_INFO.copy(), Token.ORDER_INFO.copy()
        cancel_cmd['symbol'], close_cmd['symbol'] = self.symbol_name, self.symbol_name

        await asyncio.sleep(0.8)  # 此处延时是为了确保能撤销所有挂单，防止撤单和挂单同时请求，最后出现还剩一单挂着的情况
        await self.command_transmitter(trans_command=cancel_cmd, token=Token.CANCEL_ALL)
        await self._update_trading_statistics()
        await asyncio.sleep(3)
        # todo: 这里有可能将maker市价单也取消掉，导致策略无法停止

        self._log_info('市价平仓')
        self._log_info('策略开始前账户现货仓位:\t{}\t{}'.format(self._init_account_spot_qty, self.symbol_name[:-4].replace('_', '')))
        self._log_info('累计理论计算当前现货仓位:\t{}\t{}'.format(self._spot_position_qty_theory, self.symbol_name[:-4].replace('_', '')))
        # 此处的qty意在传递一个信息，即策略开始前的仓位
        current_qty = await self._my_executor.get_current_asset_qty(self.symbol_name)
        self._log_info('账户实际当前现货仓位:\t{}\t{}'.format(current_qty, self.symbol_name[:-4].replace('_', '')))
        close_qty = round_step_size(calc(current_qty, self._init_account_spot_qty, '-'), self.symbol_quantity_min_step, upward=False)
        if close_qty != 0:
            # self._log_info('实际市价平掉仓位 {}'.format(str(close_qty)))
            # close_cmd['quantity'] = abs(close_qty)
            # close_cmd['side'] = self.SELL if (close_qty > 0) else self.BUY
            # close_cmd['id'] = 'close-position'
            # await self.command_transmitter(trans_command=close_cmd, token=Token.TO_POST_MARKET)

            if self._maker_market_switch_on:
                self._log_info('存在maker市价任务，延后平仓')
                self._accumulated_market_quantities.append(self.filling_quantity)
                # 等待现有任务全部完成
                while True:
                    await asyncio.sleep(1)
                    if not self._maker_market_switch_on:
                        self._log_info('现有任务已完成，执行最后市价任务')
                        break

            self._log_info('实际市价平掉仓位 {}'.format(str(close_qty)))
            self._target_maker_quantity = abs(close_qty)
            self._target_maker_side = self.SELL if (close_qty > 0) else self.BUY
            self._maker_market_switch_on = True

            # 循环等待只到平仓任务完成
            while True:
                await asyncio.sleep(1)
                if not self._maker_market_switch_on:
                    self._log_info('maker市价平仓完成')
                    break

            # 理论计算的交易量
            # adding_volume = calc(self.filling_quantity, self.all_grid_price[self.critical_index], '*')
            # self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
            # self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_taker_fee, '*'), '+')

        else:
            self._log_info('实际不需要市价平仓')

        self._log_info('终止策略，终止原因: {}'.format(reason))
        await self._update_detail_info(only_once=True)

        self._my_logger.close_file()

        self._my_executor.stop_single_contract_order_subscription(self.symbol_name)
        self._my_executor.stop_single_contract_ticker_subscription(self.symbol_name)
        self._my_executor.strategy_stopped(self.stg_num)

        # todo: 此处或许应该在基类中定义
        self._bound_running_column = None

    async def _update_trading_statistics(self) -> None:

        filled_trading_pair = min(self._trading_statistics['filled_buy_order_num'], self._trading_statistics['filled_sell_order_num'])
        self._trading_statistics['matched_profit'] = calc(calc(filled_trading_pair, self.grid_price_step, '*'), self.grid_each_qty, '*')

        self._trading_statistics['realized_profit'] = calc(self._each_stair_profit, self.present_stair_num, '*')

        stair_entry_index = self.lower_grid_max_num + self.filling_grid_step_num * self.present_stair_num
        unmatched_profit = self.unmatched_profit_calc(
            initial_index=stair_entry_index,
            current_index=self.critical_index,
            all_prices=self.all_grid_price,
            each_grid_qty=self.grid_each_qty,
            init_pos_price=self.all_grid_price[stair_entry_index],
            init_pos_qty=self.filling_quantity
        )
        self._trading_statistics['unrealized_profit'] = unmatched_profit

        self._trading_statistics['final_profit'] = calc(calc(calc(self._trading_statistics['matched_profit'], self._trading_statistics['realized_profit'], '+'),
                                                             self._trading_statistics['unrealized_profit'], '+'), self._trading_statistics['total_trading_fees'], '-')

    async def _market_order_locker(self, lock_time: int = 60) -> None:
        """
        该协程函数实现一个市价下单锁的功能
        协程运行过程中，不能市价调整仓位
        :param lock_time: 锁定时间
        :return:
        """
        if self._market_order_lock:
            return
        else:
            self._market_order_lock = True
            await asyncio.sleep(lock_time)
            self._market_order_lock = False

    async def _fix_position(self) -> None:
        """
        自动修正仓位，每成交一定数量的挂单，自动修正仓位
        :return:
        """
        # 自动修仓函数可能与维护网格时的市价下单冲突，
        # 即维护网格市价下单还没执行完成，仓位修正功能重复市价下单，
        # 方法：使用一个市价下单锁，独立协程，sleep时间，期间不能修正仓位市价下单
        if self._market_order_lock:
            self._log_info('\n市价下单锁，不开启仓位修正任务\n')
            self._fix_position_task = None
            return

        current_qty = await self._my_executor.get_current_asset_qty(self.symbol_name)

        self.derive_valid_position()
        self._log_info('\n执行仓位修正:')
        self._log_info('账户初始仓位:\t\t\t{}\t{}'.format(self._init_account_spot_qty, self.symbol_name[:-4].replace('_', '')))
        self._log_info('累计理论当前仓位:\t\t{}\t{}'.format(self._spot_position_qty_theory, self.symbol_name[:-4].replace('_', '')))
        self._log_info('策略要求当前仓位:\t\t{}\t{}'.format(self._current_valid_position, self.symbol_name[:-4].replace('_', '')))
        self._log_info('账户实际当前仓位:\t\t{}\t{}'.format(current_qty, self.symbol_name[:-4].replace('_', '')))

        fix_position_cmd = Token.ORDER_INFO.copy()
        fix_qty = round_step_size(calc(current_qty, self._current_valid_position, '-'), self.symbol_quantity_min_step, upward=False)
        # 小一点的差别就不管了
        if abs(fix_qty) > 2.4 * self.grid_each_qty:
            self._log_info('存在仓位差\t\t{}\t校验仓位中......'.format(fix_qty))
            verify_qty_list = []
            for _ in range(2):
                await asyncio.sleep(10)
                c_qty = await self._my_executor.get_current_asset_qty(self.symbol_name)
                self.derive_valid_position()
                d_qty = round_step_size(calc(c_qty, self._current_valid_position, '-'), self.symbol_quantity_min_step, upward=False)
                verify_qty_list.append(d_qty)

            all_equal = True
            for each_qty_def in verify_qty_list:
                if fix_qty != each_qty_def:
                    all_equal = False

            self._log_info('\n校验仓位差{} {}'.format(str(fix_qty), str(verify_qty_list)))
            if all_equal:
                if self._maker_market_switch_on:
                    self._log_info('正在运行市价maker下单任务，暂不修正仓位')
                else:
                    self._log_info('maker市价修正仓位\t\t{}\n'.format(str(fix_qty)))
                    self._target_maker_quantity = abs(fix_qty)
                    self._target_maker_side = self.SELL if (fix_qty > 0) else self.BUY
                    self._maker_market_switch_on = True
                # fix_position_cmd['quantity'] = abs(fix_qty)
                # fix_position_cmd['side'] = self.SELL if (fix_qty > 0) else self.BUY
                # fix_position_cmd['id'] = 'close-position'
                # await self.command_transmitter(trans_command=fix_position_cmd, token=Token.TO_POST_MARKET)
            else:
                self._log_info('仓位差校验未通过，不修正仓位，请检查订单情况\n')

        else:
            self._log_info('无需修正仓位\n')

    async def _update_detail_info(self, interval_time: int = 1, only_once: bool = False) -> None:

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
            top_price = self.all_grid_price[(self.lower_grid_max_num + self.present_stair_num * self.filling_grid_step_num)]

            showing_texts = '智能调仓网格 统计信息:'
            showing_texts += '\n\n*** {} ***\n\n'.format('=' * 51)

            if days == 0:
                showing_texts += '交易统计\t\t运行时间\t\t{}:{}:{}\n\n'.format(str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2))
            else:
                showing_texts += '交易统计\t\t运行时间\t\t{} day\t{}:{}:{}\n\n'.format(
                    str(days), str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2))
            # showing_texts += '交易统计:\t\t当前时间 {}\n\n'.format(str(str(pd.to_datetime(self.gen_timestamp(), unit='ms'))))
            showing_texts += '-' * 58
            showing_texts += '\n\n卖单挂单成交次数:\t{:<10}\n'.format(str(self._trading_statistics['filled_sell_order_num']))
            showing_texts += '买单挂单成交次数:\t{:<10}\n\n'.format(str(self._trading_statistics['filled_buy_order_num']))
            showing_texts += '-' * 58
            showing_texts += '\n\n已补仓次数:\t\t{} / {}\n'.format(self.present_stair_num, self.stairs_total_num)
            showing_texts += '当前套利区间:\t\t{:<10} ~  {:<10}\n'.format(bottom_price, top_price)
            showing_texts += '\n已达成交易量:\t\t{:<20}\t{}\n\n'.format(str(self._trading_statistics['achieved_trade_volume']), self.symbol_name[-4:])
            showing_texts += '-' * 58
            showing_texts += '\n\n已实现套利:\t\t{:<20}\t{}\n'.format(self._trading_statistics['matched_profit'], self.symbol_name[-4:])
            showing_texts += '已达成盈亏:\t\t{:<20}\t{}\n'.format(self._trading_statistics['realized_profit'], self.symbol_name[-4:])

            # 如果价格下冲超出下边界，则改统计信息可能不起作用
            if self.critical_index == self.present_bottom_index:
                showing_texts += '未实现盈亏:\t\t{:<20}\t{} (价格走出下区间价 {}，无法统计)\n\n'.format(
                    self._trading_statistics['unrealized_profit'], self.symbol_name[-4:], self.all_grid_price[self.present_bottom_index])
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

        temp_text = """
*** =================================================== ***

交易统计		运行时间		00:01:25

----------------------------------------------------------

卖单挂单成交次数:	13        
买单挂单成交次数:	67        

----------------------------------------------------------

已达成交易量:		334.24864           	USDT

----------------------------------------------------------

已实现套利:		0.00026             	USDT
未配对盈亏:		-0.09882            	USDT (价格走出下区间，无法统计，仅做参考)
交易手续费:		0.299702            	USDT

策略净收益:		-0.398262           	USDT

*** =================================================== ***
"""

    def _update_column_text(self):
        """
        更新 column 显示的策略收益
        :return:
        """
        # todo: 考虑使用pandas
        self._bound_running_column.update_profit_text(
            matched_profit=str(self._trading_statistics['matched_profit']),
            unmatched_profit=str(self._trading_statistics['unrealized_profit'])
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
            # todo: 临时修改，后续需要拓展到整个框架
            await self._maintain_grid_order(recv_data_dict, append_info)
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
            if this_order_index == 99999998:
                if self._posted_change_poc_order:
                    self._log_info('\npoc挂单修改成功\t\t价格: {:<12}\tid: {:<10}'.format(str(float(recv_data_dict['price'])), recv_data_dict['id']))
                    self._posted_change_poc_order = False
                else:
                    # poc 部分成交
                    self._log_info('\nmaker市价单部分成交!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
                    await self._maintain_test_maker(recv_data_dict, append_info)
            else:
                self._log_info('订单部分成交!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            pass
        elif recv_data_dict['status'] == Token.UNIDENTIFIED:
            pass
        elif recv_data_dict['status'] == Token.FAILED:
            pass
        elif recv_data_dict['status'] == Token.POST_FAILED:
            self._log_info('\n限价挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            pass
        elif recv_data_dict['status'] == Token.POC_FAILED:
            self._log_info('\npoc挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            this_order_index, side = self.parse_id(recv_data_dict['id'])
            if this_order_index == 99999998:
                self._exist_market_poc_order = False
                self._log_info('maker市价挂单失败，重新维护')
            pass
        elif recv_data_dict['status'] == Token.CANCEL_FAILED:
            self._log_info('\n撤销挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            pass
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
            command_dict['id'] = self.gen_id(99999999, trans_command['side'])
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
        # todo: test
        # 一般来说在策略开始前就已经在收听实时价格信息，因此已经更新一段时间
        self._previous_price = self.current_symbol_price
        self.current_symbol_price = recv_ticker_data['price']

        # if self._my_logger:
        #     self._log_info('合约最新价:\t{}'.format(str(self.current_symbol_price)))
        if len(self._accumulated_market_quantities) > 0:
            self._log_info('执行已累计的补仓任务')
            add_quantity = calc_sum(self._accumulated_market_quantities)
            self._target_maker_quantity = abs(add_quantity)
            self._target_maker_side == self.BUY if add_quantity > 0 else self.SELL
            self._accumulated_market_quantities.clear()
            self._maker_market_switch_on = True

        if self._maker_market_switch_on:
            # asyncio.create_task(self._test_maker())
            await self._maker_market_post()

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
                              init_pos_price: float = 0, init_pos_qty: float = 0) -> float:
        """
        便携计算器，用于计算网格未配对盈亏
        计算方法：将盈利拆分成一个初始仓位的单向买多(卖空)和一个中性网格的盈利
        :param initial_index: 初始的index
        :param current_index: 目标价位的index
        :param all_prices: 网格所有价格
        :param each_grid_qty: 每格数量，真实数量
        :param init_pos_price: 初始仓位价格
        :param init_pos_qty: 初始仓位数量，真实绝对数量，大于0代表买多，小于0做空
        :return:
        """
        grid_price_step = calc(all_prices[1], all_prices[0], '-')
        if current_index == -1:
            current_index = len(all_prices) - 1

        part_1 = calc(calc(all_prices[current_index], init_pos_price, '-'), init_pos_qty, '*')

        part_2 = - abs(current_index - initial_index) * (abs(current_index - initial_index) - 1) / 2
        part_2 = calc(calc(each_grid_qty, grid_price_step, '*'), part_2, '*')

        return calc(part_1, part_2, '+')

    @staticmethod
    def gen_timestamp():
        return int(round(time.time() * 1000))

    def __del__(self):
        print('\n{}: {} stair analyzer 实例被删除，释放资源\n'.format(self.stg_num, self.symbol_name))
        pass
