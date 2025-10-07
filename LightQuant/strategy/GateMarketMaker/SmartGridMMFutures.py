# -*- coding: utf-8 -*-
# @Time : 2024/2/10 19:59
# @Author : 
# @File : SmartGridMMFutures.py 
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
from LightQuant.strategy.GateMarketMaker.Operator import Operator
from LightQuant.protocols.BinanceToken import BinanceToken as Token


class SmartGridMarketMakerAnalyzer(Analyzer):
    """
    做市策略
    """

    STG_NAME = '高频做市智能网格'

    BUY: str = 'BUY'
    SELL: str = 'SELL'

    MARKET_ORDER_ID = 99999999  # 市价下单的id，taker成交
    ENTRY_ORDER_ID = 99999998  # 触发挂单id

    param_dict: dict = {
        'symbol_name': None,
        'up_price': None,
        'leverage': None,
        'trigger_start': None,  # 是否用挂单触发, True/False
        'pending_trigger_price': None,

        'grid_price_step': None,
        'filling_step': None,
        'lower_step': None,
        'filling_fund': None,  # 设定补仓资金，按照现货计算

        'short_ratio': None,  # 初始空单比例
        'account_num': None,  # 子账号数量
    }

    def __init__(self) -> None:
        super().__init__()
        # ==================== 策略参数保存 ==================== #
        self.symbol_name = None
        # self.grid_price_step = None
        # self.grid_each_qty = None
        self.up_limit_price = None  # 该上界为实值，是最顶端网格价格
        # self.filling_quantity = None  # 理论上填单网格数量*每格数量 即可得到该变量
        self.symbol_leverage = None

        self.trigger_start: bool = False
        self.trigger_price = None

        self.grid_price_step = None  # 等差网格间距
        self.filling_step_ratio = None  # 等比填仓比例，单位为1
        self.lower_space_ratio = None  # 下方空间比例
        self.filling_fund = None  # 每次填仓资金

        self._account_num = None
        self.short_ratio = None  # 一部分多单不买入，相当于做空的比例

        # 输入相关，仅作为临时存储
        self._x_grid_up_limit = None
        self._x_leverage = None
        self._x_trigger_start = False
        self._x_trigger_price = None
        self._x_price_abs_step = None
        self._x_filling_step = None
        self._x_lower_step = None
        self._x_filling_fund = None

        self._x_short_ratio = None

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
        # 所有网格的价格，由index索引，考虑到无限网格可能会很大，该元祖会随着网格抬升自动添加，每个价格不包括base index
        self.all_grid_price: tuple = ()
        # 所有网格的数量，于gate而言，指的是合约张数，tuple(int)，与楼上有相似的维护机制，
        self.all_grid_quantity: tuple = ()
        # 当前网格数量(动态减少), 统计用
        self.each_grid_quantity: int = 0
        # 需要补仓的价格index， 当 critical_index 属于其中时，执行补仓操作，补仓后，删除index以实现到达位置只补仓一次的功能，该列表随着策略运行会增加index
        self.indices_of_filling: list = []
        # 所有filling_price下方的网格价格，不包括base index，长度最终和楼上一样
        # self.all_lower_prices: list[tuple] = []
        # 对冲需求：0仓位index
        self.zero_pos_index = 0
        # 当前处在第几级台阶，即已经补了多少次仓位
        self.present_stair_num = 0
        # 当前需要补仓的index
        self.present_step_up_index = 0
        # 当前补仓price
        self.present_step_up_price = 0
        # 当前最低网格index，即下方区间底部的index
        self.present_bottom_index = 0
        self.present_bottom_price = 0
        # 当前基准index
        self.present_base_index = 0
        # 自动补单的网格数量间隔，不包括base index，但是这个计算是理论上的，实际有可能因为间距过密，数量更少，因此每次都要重新计算
        # self.filling_grid_step_num = 0
        # 下方网格数量，包括基准入场网格
        # self.lower_grid_step_num = 0  # 两者相加就是做多网格的 网格总数-1
        # 当前保存了几个网格的参数
        self.saved_stair_num = 0

        # 上方是动态变量，以下是静态变量
        # 网格总数量，仅参考用，意义不大
        self.grid_total_num = 0
        self.max_index = 0
        # 所有做多网格的基准入场价格，不包括策略入场价，在一开始就计算清楚
        self.all_filling_prices: list[float] = []
        # 所有补仓数量，适应gate张数，根据网格数量微调，随台阶上涨
        self.all_filling_quantities: list[int] = []
        # 从入场网格到最上方价格的所有网格数量，包括入场的 entry index，用处不大
        self.up_grid_num = 0
        # 台阶数量，对应后续可能的最多补仓数量
        self.stairs_total_num = 0
        # 上方先计算多少个台阶作为缓冲,需要大于等于1
        self.upper_buffer_steps_num = 5
        # 入场时对标网格的价格
        self.entry_grid_price = 0
        self.entry_index = 0
        # 初始市价买入数量, gate合约张数
        self.entry_grid_qty = 0

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

        # ==================== 策略统计相关变量 ==================== #
        # 当前最新价格，实时更新，要求最新
        self.current_symbol_price = 0

        # 存储所有网格的买入卖出数量，用于计算套利收益，长度和网格数量，价格一致，同时更新
        self._all_grid_buy_num: list[int] = []
        self._all_grid_sell_num: list[int] = []

        # 策略开始前，账户存量仓位，策略结束后，需要回归该数字
        self._init_account_position: int = 0
        # 理论累计计算的现货仓位
        self._account_position_theory: int = 0
        # 根据当前位置，导出的正确的应有的仓位
        self._current_valid_position: int = 0

        # 每个台阶做多利润，长度为台阶数+1，最后为不完全台阶的收益
        self._each_stair_profit: list[float] = []

        # 维持策略所需要的最少资金
        self.account_fund_demand: float = 0

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

        # ==================== 特殊功能相关变量 ==================== #

        # 入场触发挂单剩余数量
        self._ENTRY_ORDER_qty_left: int = 0
        # 市价挂单目标量和剩余量，均为正数表示绝对数量，用于记忆市价挂单交易数量作为比对，该功能不完全必要
        self._MARKET_ORDER_qty_left: int = 0
        self._MARKET_ORDER_qty_target: int = 0
        self._MARKET_ORDER_value = 0  # 市价成交，已完成价值，用于最后求平均值

        # 前一个最新ticker价格
        self.previous_price = 0

        # 定时器，反复重置以达到核心功能
        # noinspection PyTypeChecker
        self._ticker_delay_timer: asyncio.TimerHandle = None
        # 等待时间 delay，如果超过该delay仍没有收到下一次ticker信息，则做出额外判断和操作
        self._ticker_delay_trigger_time: float = 1.2
        # 协程锁，防止重复开启协程任务
        self._doing_delay_task: bool = False

        # ==================== 其他变量 ==================== #
        # noinspection PyTypeChecker
        self._my_logger: LogRecorder = None

        self._is_trading = False

        # 是否在等待挂单
        self._is_waiting = False

        # 点击停止次数
        self.manually_stop_request_time: int = 0
        # 用户已经强制终止
        self.force_stopped: bool = False
        # 保存最后的参考信息
        self._save_ref_info_text: str = ''

        # # 使用多少个子账号进行交易
        # self._account_num: int = 0
        # noinspection PyTypeChecker
        self._my_operator: Operator = None

    def initialize(self, my_executor: Executor) -> None:
        # 绑定 executor, 注意这里的executor是连接主账户的executor，仅用于获得参考信息
        super().initialize(my_executor)
        return

    def return_acc_num(self) -> int:
        return self._account_num

    def return_fund_demand(self) -> float:
        return 100

    def acquire_operator(self, operator: Operator) -> None:
        self._my_operator = operator

    def sub_initialize(self):
        self._my_operator.start_all_subscription()
        self._my_operator.change_leverage(self.symbol_leverage)
        time.sleep(0.5)

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
        self._x_leverage = validated_params['leverage']
        self._x_trigger_start = validated_params['trigger_start']
        self._x_trigger_price = validated_params['pending_trigger_price']
        self._x_price_abs_step = validated_params['grid_abs_step']
        self._x_filling_step = validated_params['filling_step']
        self._x_lower_step = validated_params['lower_step']
        self._x_filling_fund = validated_params['filling_fund']
        self._account_num = int(validated_params['account_num'])
        self._x_short_ratio = validated_params['short_ratio']

        symbol_exist = await self._get_trading_rule(validated_params['symbol_name'])

        if symbol_exist:
            self.current_symbol_price = await self._my_executor.get_current_price(validated_params['symbol_name'])

            # 判断杠杆数是否合理
            if self._x_leverage == '':
                self._x_leverage = 20
            if self._x_leverage > self.symbol_max_leverage or self._x_leverage < 1:
                self._x_leverage = str(self._x_leverage) + '杠杆数值超限'
                param_valid = False

            # 判断触发价是否合理
            if param_valid and self._x_trigger_start:
                self._x_trigger_price = round_step_size(self._x_trigger_price, self.symbol_price_min_step)

                if self._x_trigger_price >= self.current_symbol_price:
                    self._x_trigger_price = str(self._x_trigger_price) + '触发价高于市场价'
                    param_valid = False

                if param_valid:
                    if abs(self._x_trigger_price - self.current_symbol_price) >= self.current_symbol_price * self.symbol_order_price_div:
                        self._x_trigger_price = str(self._x_trigger_price) + '触发价过低，不能挂单'
                        param_valid = False

            if self._x_trigger_start:
                entry_price = self._x_trigger_price
            else:
                entry_price = self.current_symbol_price

            # 判断并规则上界价格，由于实际网格价格的存在，该上界价格为虚值，实际以网格最大价格为准
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

            # 套利部分，首先设定默认值
            if param_valid:
                if self._x_price_abs_step == '':
                    self._x_price_abs_step = 1
                if self._x_filling_step == '':
                    self._x_filling_step = 2
                if self._x_lower_step == '':
                    self._x_lower_step = 5

                # 设定数字精度，降低计算难度
                self._x_price_abs_step = round_step_size(self._x_price_abs_step, self.symbol_price_min_step)
                self._x_filling_step = round(self._x_filling_step, 2)
                self._x_lower_step = round(self._x_lower_step, 2)
                # 计算上下方网格数量
                # up_grid_num = int(np.floor(np.log(1 + self._x_filling_step / 100) / np.log(1 + self._x_price_abs_step / 100)))  # 不计算base网格，算上顶部价格的网格，由于实际网格是用顶部网格代替最高价格，所以数量不变
                # low_grid_num = int(np.floor(np.log(1 - self._x_lower_step / 100) / np.log(1 - self._x_price_abs_step / 100)))
                up_grid_num = int(self._x_filling_step * entry_price / self._x_price_abs_step)
                low_grid_num = int(self._x_lower_step * entry_price / self._x_price_abs_step)
                # print('上方网格数量:{}\t下方网格数量:{}'.format(up_grid_num, low_grid_num))

                # 补仓次数需要大于1
                if self._x_grid_up_limit <= round_step_size(calc(entry_price, calc(1, calc(calc(self._x_filling_step, calc(self._x_price_abs_step, 2, '*'), '+'), 100, '/'), '+'),
                                                                 '*'), self.symbol_price_min_step):  # 补仓点位 + 2 * 网格比例间距，上界价格大于该价格
                    self._x_grid_up_limit = str(self._x_grid_up_limit) + '补仓次数小于1'
                    param_valid = False

                if up_grid_num < 5:
                    self._x_filling_step = str(self._x_filling_step) + '上方空间不足'
                    param_valid = False
                elif low_grid_num < 5:
                    self._x_lower_step = str(self._x_lower_step) + '下方空间不足'
                    param_valid = False

                if param_valid:
                    if self._x_lower_step >= 100:
                        self._x_lower_step = str(self._x_lower_step) + '价格不能为负'
                        param_valid = False

                # 最后判断金额大小，使用最高补单价格判断最低金额
                if param_valid:
                    filling_times = int(np.floor(np.log(self._x_grid_up_limit / entry_price) / np.log(1 + self._x_filling_step / 100)))
                    max_filling_price = self.round_step_precision(entry_price * (1 + self._x_filling_step / 100) ** filling_times, self.symbol_price_min_step)
                    max_up_grid_num = int(max_filling_price * (self._x_filling_step / 100) / self._x_price_abs_step)
                    min_fund_demand = calc(max_filling_price, calc(max_up_grid_num, self.symbol_quantity_min_step, '*'), '*')
                    # print('最低金额需求: {} USDT'.format(min_fund_demand))
                    # 最低资金加1美刀，保险
                    self._x_filling_fund = max(self._x_filling_fund, min_fund_demand + 1)

                    self._x_short_ratio = round(self._x_short_ratio, 2)
                    if not 0 <= self._x_short_ratio <= 0.5:
                        self._x_short_ratio = str(self._x_short_ratio) + '做空比例不合理'  # 否则最后一阶，初始没有做多，全是做空
                        param_valid = False

            # 多账号部分
            if param_valid:
                if self._account_num <= 0:
                    self._account_num = str(self._account_num) + '账户数量错误'
                    param_valid = False

        else:
            validated_params['symbol_name'] += '未查询到该合约'
            param_valid = False

        validated_params['up_price'] = self._x_grid_up_limit
        validated_params['leverage'] = self._x_leverage
        validated_params['trigger_start'] = self._x_trigger_start
        validated_params['pending_trigger_price'] = self._x_trigger_price
        validated_params['grid_abs_step'] = self._x_price_abs_step
        validated_params['filling_step'] = self._x_filling_step
        validated_params['lower_step'] = self._x_lower_step
        validated_params['filling_fund'] = self._x_filling_fund
        validated_params['account_num'] = self._account_num
        validated_params['short_ratio'] = self._x_short_ratio
        validated_params['valid'] = param_valid

        return validated_params

    async def param_ref_info(self, valid_params_dict: dict) -> str:
        symbol_name = valid_params_dict['symbol_name']

        info_texts: str = """\n"""
        info_texts += '*** {} ***\n'.format('=' * 32)
        self.current_symbol_price = await self._my_executor.get_current_price(symbol_name)

        self.derive_functional_variables()

        # 使用东八区时间
        info_texts += '\n当前时间: {}\n'.format(str(pd.to_datetime(self.gen_timestamp(), unit='ms') + pd.Timedelta(hours=8)))
        info_texts += '\n合约名称: {}\t\t\t当前价格: {}\n'.format(symbol_name, str(self.current_symbol_price))
        if self.trigger_start:
            info_texts += '\n\t\t\t\t触发价格: {}\n'.format(str(self.trigger_price))

        # 计算一些参考数据，套利利润
        each_grid_profit = calc(self.grid_price_step, calc(self.all_grid_quantity[self.entry_index], self.symbol_quantity_min_step, '*'), '*')
        filling_margin_occupation = calc(calc(calc(self.entry_grid_qty, self.symbol_quantity_min_step, '*'), self.entry_grid_price, '*'), self.symbol_leverage, '/')
        # 经过计算，由于策略的等比性质，不同台阶位置的套利区间底部保证金占用和策略亏损(相同回撤比例)基本相同
        max_margin_cost = calc(calc(calc(sum(self.all_grid_quantity[self.present_bottom_index + 1:self.zero_pos_index + 1]),
                                         self.symbol_quantity_min_step, '*'), self.present_bottom_price, '*'), self.symbol_leverage, '/')
        # 给出参考亏损，即台阶底部亏损
        max_loss_ref = self.unmatched_profit_calc(
            initial_index=self.entry_index + 1,
            current_index=0,
            all_prices=self.all_grid_price,
            all_quantities=self.all_grid_quantity,
            init_pos_price=self.entry_grid_price,
            init_pos_qty=self.entry_grid_qty,
            current_price=self.all_grid_price[0]
        )
        # 维持策略所需账户资金
        self._reasonable_order_num_estimate()
        # init_buy_order_num, init_sell_order_num = int((self.max_buy_order_num + self.min_buy_order_num) / 2), int((self.max_sell_order_num + self.min_sell_order_num) / 2)
        order_margin = calc(calc(calc(calc_sum(self.all_grid_price[self.entry_index - self.max_buy_order_num:self.entry_index]),
                                      calc_sum(self.all_grid_quantity[self.entry_index + 1:self.entry_index + self.max_sell_order_num + 1]), '+'),
                                 calc(self.all_grid_quantity[self.entry_index], self.symbol_quantity_min_step, '*'), '*'), self.symbol_leverage, '/')
        self.account_fund_demand = calc(calc(max_margin_cost, abs(max_loss_ref), '+'), order_margin, '+')
        # 列出回调不同比例时的策略亏损
        list_callback_ratio = [0.01, 0.02, 0.05, 0.08, 0.1]
        list_critical_indices = [0] * len(list_callback_ratio)
        list_prices = [round_step_size(calc(self.entry_grid_price, 1 - each_ratio, '*'), self.symbol_price_min_step) for each_ratio in list_callback_ratio]
        list_callback_losses = [0.] * len(list_callback_ratio)
        list_fund_demand = [0.] * len(list_callback_ratio)
        for p_index, _ in enumerate(self.all_grid_price):
            for _index, _price in enumerate(list_prices):
                if self.all_grid_price[p_index] <= _price < self.all_grid_price[p_index + 1]:
                    list_critical_indices[_index] = p_index
        # print(list_prices, '\n', list_critical_indices)
        for index in range(len(list_callback_losses)):
            list_callback_losses[index] = self.unmatched_profit_calc(
                initial_index=self.entry_index,
                current_index=list_critical_indices[index],
                all_prices=self.all_grid_price,
                all_quantities=self.all_grid_quantity,
                init_pos_price=self.entry_grid_price,
                init_pos_qty=self.entry_grid_qty,
                current_price=list_prices[index]
            )
            each_margin_cost = calc(calc(calc(sum(self.all_grid_quantity[list_critical_indices[index] + 1:self.zero_pos_index + 1]),
                                         self.symbol_quantity_min_step, '*'), list_prices[index], '*'), self.symbol_leverage, '/')
            list_fund_demand[index] = calc(calc(each_margin_cost, abs(list_callback_losses[index]), '+'), order_margin, '+')
        print('done calculation')
        info_texts += '\n网格总数量\t\t{:<8}\n'.format(str(self.grid_total_num))
        info_texts += '套利区间网格数量\t\t{} + {}\n'.format(str(self.present_base_index), str(self.present_step_up_index - self.present_base_index + 1))
        info_texts += '等差网格间距\t\t{:<8}\n'.format(self.grid_price_step)
        info_texts += '全程补仓次数\t\t{:<8}\t\t次\n'.format(str(self.stairs_total_num))

        info_texts += '\n每格套利利润\t\t{}\t\t{:<8}\n'.format(each_grid_profit, symbol_name[-4:])
        info_texts += '每阶做多收益\t\t{:<8}\t\t{:<8}\n'.format(round(self._each_stair_profit[0], 3), symbol_name[-4:])
        info_texts += '全程做多收益\t\t{:<8}\t\t{:<8}\n'.format(round(calc_sum(self._each_stair_profit), 3), symbol_name[-4:])

        info_texts += '\n使用子账号数量\t\t{}\t个\n'.format(self._account_num)
        info_texts += '挂单价格范围:\t\t下方  {}\t上方  {}\n'.format(calc(self.grid_price_step, self.max_buy_order_num, '*'), calc(self.grid_price_step, self.max_sell_order_num, '*'))

        info_texts += '\n补仓占用保证金\t\t{:<8}\t\t{:<8}\n'.format(str(round(filling_margin_occupation, 2)), symbol_name[-4:])
        info_texts += '挂单占用保证金\t\t{:<8}\t\t{:<8}\n'.format(str(round(order_margin, 2)), symbol_name[-4:])
        info_texts += '最大仓位保证金\t\t{:<8}\t\t{:<8}\n'.format(str(round(max_margin_cost, 2)), symbol_name[-4:])

        info_texts += '\n策略资金需求\t\t{:<8}\t\t{:<8}\t（账户最低资金）\n'.format(str(round(self.account_fund_demand, 2)), symbol_name[-4:])

        info_texts += '\n\n区间底部亏损\t\t{:<8}\t\t{:<8}\n'.format(str(round(max_loss_ref, 2)), symbol_name[-4:])

        info_texts += '\n补仓位价格回调\t\t策略亏损\t\t账户资金需求'
        # for index, each_fund_callback in enumerate(list_callback_losses):
        for each_ratio, each_fund_callback, each_fund_demand in zip(list_callback_ratio, list_callback_losses, list_fund_demand):
            info_texts += '\n{:>8} %\t\t{:>8}\t\t{:>8}\t{}'.format(str(100 * each_ratio), str(round(each_fund_callback, 2)),
                                                                   str(round(each_fund_demand, 2)), symbol_name[-4:])

        info_texts += '\n\n*** {} ***'.format('=' * 32)

        # 最后保存参考信息，以供恢复策略时使用
        self._save_ref_info_text = info_texts
        return info_texts

    def confirm_params(self, input_params: dict) -> None:
        self.symbol_name = input_params['symbol_name']

    def return_params(self) -> dict:
        stg_params = self.param_dict.copy()

        stg_params['symbol_name'] = self.symbol_name
        stg_params['up_price'] = self._x_grid_up_limit
        stg_params['leverage'] = self._x_leverage
        stg_params['trigger_start'] = self._x_trigger_start
        stg_params['pending_trigger_price'] = self._x_trigger_price
        stg_params['grid_abs_step'] = self._x_price_abs_step
        stg_params['filling_step'] = self._x_filling_step
        stg_params['lower_step'] = self._x_lower_step
        stg_params['filling_fund'] = self._x_filling_fund
        stg_params['account_num'] = self._account_num
        stg_params['short_ratio'] = self._x_short_ratio
        stg_params['valid'] = True

        return stg_params

    def derive_functional_variables(self, assign_entry_price: float = 0) -> None:
        """
        计算策略运行需要的相关变量
        策略实现方法：每达到补仓点位，相当于重新开启了一个等差做多网格
        因此首先计算所有补仓价格，然后以该补仓价格为基准计算等比网格价格
        网格间距变化方法：首先保存上方大量范围的网格价格，并另外存储每个台阶下方的网格价格
        当台阶上升时，使用类似非线性网格的逻辑更新所有网格价格，保持index不变，下方多余位置，以0填充
        :param assign_entry_price:
        :return:
        """
        self.symbol_leverage = self._x_leverage
        self.up_limit_price = self._x_grid_up_limit
        self.trigger_start = self._x_trigger_start
        self.trigger_price = self._x_trigger_price

        self.grid_price_step = self._x_price_abs_step
        self.filling_step_ratio = calc(self._x_filling_step, 100, '/')
        self.lower_space_ratio = calc(self._x_lower_step, 100, '/')
        self.filling_fund = self._x_filling_fund

        self.short_ratio = self._x_short_ratio

        # 根据当前价格，给出 entry price，最新价格在参考信息和 策略开始运行两处都会使用，如果挂单触发，则为触发价格
        if self.trigger_start:
            self.entry_grid_price = self.trigger_price
        elif assign_entry_price != 0:
            self.entry_grid_price = assign_entry_price
        else:
            self.entry_grid_price = self.current_symbol_price
        # print('entry price: {}'.format(self.entry_grid_price))

        # 首先计算所有补仓价格
        self.all_filling_prices = list(self.isometric_grid_calc(
            base_price=self.entry_grid_price,
            grid_ratio=self.filling_step_ratio,
            boundary_price=self.up_limit_price
        ))[1:]
        # 如果最后一个补仓价格完全等于上边界价格，则剔除该价格
        if self.all_filling_prices[-1] == self.up_limit_price:
            self.all_filling_prices.pop(-1)
        # print('prices of filling: {}'.format(self.all_filling_prices))
        self.stairs_total_num = len(self.all_filling_prices)
        # 再计算一阶网格价格
        # up_grid_price = self.isometric_grid_calc(self.entry_grid_price, self.grid_step_ratio, self.all_filling_prices[0])
        # down_grid_price = self.isometric_grid_calc(self.entry_grid_price, self.grid_step_ratio,
        #                                            self.round_step_precision(self.entry_grid_price * (1 - self.lower_space_ratio), self.symbol_price_min_step))[:-1]
        up_grid_price = self.arithmetic_grid_calc(self.entry_grid_price, self.grid_price_step, self.all_filling_prices[0])
        down_grid_price = self.arithmetic_grid_calc(self.entry_grid_price, self.grid_price_step,
                                                    self.round_step_precision(self.entry_grid_price * (1 - self.lower_space_ratio), self.symbol_price_min_step))[:-1]
        up_grid_price[-1] = self.all_filling_prices[0]
        # self.filling_grid_step_num = len(up_grid_price) - 1  # 减去base index
        # self.lower_grid_step_num = len(down_grid_price)

        self.all_grid_price = tuple(down_grid_price + up_grid_price)
        # print('初始做多网格:\n{}'.format(self.all_grid_price))

        # 计算网格总数
        # last_stair_grid_num = int(np.floor(np.log(self._x_grid_up_limit / self.all_filling_prices[-1]) / np.log(1 + self.grid_step_ratio)))  # 不包括base index，也不包括上界价格
        self.up_grid_num = int(calc(calc(self._x_grid_up_limit, self.entry_grid_price, '-'), self.grid_price_step, '/')) + 1
        self.grid_total_num = self.up_grid_num + len(down_grid_price)
        self.max_index = self.grid_total_num - 1

        # 更新相关index
        self.present_stair_num = 0
        self.present_bottom_index = 0
        self.present_base_index = len(down_grid_price)
        self.present_step_up_index = len(self.all_grid_price) - 1
        self.indices_of_filling = [self.present_step_up_index, ]
        # 更新其他动态变量
        self.present_bottom_price = self.all_grid_price[self.present_bottom_index]
        self.present_step_up_price = self.all_grid_price[self.present_step_up_index]

        self.entry_index = self.present_base_index
        self.critical_index = self.entry_index
        self.zero_pos_index = self.present_base_index + int((self.present_step_up_index - self.present_base_index) * (1 - self.short_ratio))

        # # 这里添加一项保险，filling fund使用实时的最小值去更新，如果确认参数后，价格上涨较快，到用户点击开始运行时最小资金需求又提高了，则会触发该代码
        # int((self._x_grid_up_limit - max_filling_price) / self._x_price_abs_step)
        # real_time_min_fund = calc(self.all_filling_prices[-1], calc(self.filling_grid_step_num, self.symbol_quantity_min_step, '*'), '*')
        # # todo: 此处不能_log_info,可以考虑写一个弹窗，全局提醒用
        # self.filling_fund = max(self.filling_fund, real_time_min_fund)

        # 计算所有补仓数量
        # self.all_filling_quantities = [int(calc(self.filling_fund, calc(each_fill_price, self.symbol_quantity_min_step, '*'), '/'))
        #                                for each_fill_price in self.all_filling_prices]
        # print('quantities of filling: {}'.format(self.all_filling_quantities))

        # 再计算一阶网格数量，根据网格数量，计算一共有多少张，然后平均分配到网格
        # up_grid_qty = self.unequal_grid_qty_calc(base_price=self.entry_grid_price, grid_num=self.filling_grid_step_num, fund=self.filling_fund)
        # down_grid_qty = [up_grid_qty[0]] * (self.lower_grid_step_num + 1)  # 包含 base index
        # self.all_grid_quantity = tuple(down_grid_qty + up_grid_qty)
        # self.entry_grid_qty = sum(up_grid_qty)
        # print('len prices = {}, len qty = {}'.format(len(self.all_grid_price), len(self.all_grid_quantity)))
        self.each_grid_quantity = self.grid_qty_calc(self.entry_grid_price, len(up_grid_price) - 1, self.filling_fund)
        self.all_grid_quantity = tuple([self.each_grid_quantity, ] * len(self.all_grid_price))
        # self.entry_grid_qty = self.each_grid_quantity * (len(up_grid_price) - 1)
        self.entry_grid_qty = sum(self.all_grid_quantity[self.present_base_index:self.zero_pos_index])
        self.all_filling_quantities = [self.entry_grid_qty, ]
        print(f'初始数量: {self.entry_grid_qty}')
        # 更新初始统计变量
        self._all_grid_buy_num = [0] * len(self.all_grid_price)
        self._all_grid_sell_num = [0] * len(self.all_grid_price)
        self._each_stair_profit = [self.unmatched_profit_calc(
            initial_index=self.entry_index,
            current_index=self.present_step_up_index,
            all_prices=self.all_grid_price,
            all_quantities=self.all_grid_quantity,
            init_pos_price=self.all_grid_price[self.entry_index],
            init_pos_qty=self.entry_grid_qty,
            current_price=self.all_grid_price[self.indices_of_filling[0]]
        )]

        # self.all_lower_prices = [tuple(self.isometric_grid_calc(
        #     self.all_filling_prices[0],
        #     self.grid_step_ratio,
        #     self.round_step_precision(self.all_filling_prices[0] * (1 - self.lower_space_ratio), self.symbol_price_min_step))[:-1])]
        self.saved_stair_num = 0
        # 台阶增长，计算至超出当前挂单最大范围
        # add_num = int(self.symbol_order_price_div / self.filling_step_ratio) + 1
        # print('初始缓冲 {} 阶'.format(add_num))
        # for i in range(add_num):
        #     self._add_buffer_vars()
        while self.saved_stair_num < self.stairs_total_num:
            self._add_buffer_vars()
        print(f'save stair: {self.saved_stair_num}')
        # if self._my_operator:
        #     self._my_operator.deliver_grid_param(grid_prices=self.all_grid_price, grid_quantities=self.all_grid_quantity)

    def derive_valid_position(self) -> None:
        if self.critical_index == self.indices_of_filling[0]:
            # 过于偶然，放弃判断，等待下一次判断
            return

        base_position = sum(self.all_grid_quantity[self.present_base_index + 1:self.zero_pos_index + 1])

        if self.critical_index >= self.present_base_index:
            # 虚拟成交全为卖单
            div_position = -sum(self.all_grid_quantity[self.present_base_index + 1:self.critical_index + 1])
        else:
            # 虚拟成交全为买单
            div_position = sum(self.all_grid_quantity[self.critical_index + 1:self.present_base_index + 1])

        self._current_valid_position = base_position + div_position

        if self._current_valid_position < 0 and abs(self._current_valid_position) > self.entry_grid_qty:
            # if abs(self._current_valid_position) > self.entry_grid_qty:
            raise ValueError(f'仓位数值不合理 valid pos: {self._current_valid_position}')

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
            # self._my_preserver.stop_preserving()

            self._my_executor.stop_single_contract_order_subscription(self.symbol_name)
            self._my_executor.stop_single_contract_ticker_subscription(self.symbol_name)
            self._my_executor.strategy_stopped(self.stg_num)

            # todo: 此处或许应该在基类中定义
            self._bound_running_column = None
        else:
            asyncio.create_task(self._terminate_trading(reason='人工手动结束'))

    def start(self) -> None:
        self._my_logger = LogRecorder()
        self._my_logger.open_file(self.symbol_name)
        # self._my_preserver = Preserver()
        # self._my_preserver.acquire_user_id(self._my_executor.return_user_id())
        # self._my_preserver.open_file(self.symbol_name)

        asyncio.create_task(self._my_executor.change_symbol_leverage(self.symbol_name, self.symbol_leverage))

        if self.trigger_start:
            self._pre_update_text_task = asyncio.create_task(self._pre_update_detail_info(interval_time=1))

            self.derive_functional_variables()

            maker_order = Token.ORDER_INFO.copy()
            maker_order['symbol'] = self.symbol_name
            maker_order['id'] = self.gen_id(self.ENTRY_ORDER_ID, self.BUY)
            maker_order['price'] = self.entry_grid_price
            maker_order['side'] = self.BUY
            maker_order['quantity'] = self.entry_grid_qty
            self._log_info('~~~ 触发挂单下单\n')
            # asyncio.create_task(self.command_transmitter(trans_command=maker_order, token=Token.TO_POST_POC))
            self._my_operator.deliver_entry_order(entry_price=self.entry_grid_price, entry_qty=self.entry_grid_qty,
                                                  from_index=self.present_base_index, to_index=self.zero_pos_index)

            self._ENTRY_ORDER_qty_left = self.entry_grid_qty
            self._trading_statistics['waiting_start_time'] = self.gen_timestamp()
            self._log_info('开始监听数据，等待触发条件')
            self._is_waiting = True

        else:
            asyncio.create_task(self._start_strategy())

    async def _start_strategy(self):
        self._is_waiting = False
        self._is_trading = True
        self._log_info('智能做市网格 策略开始')

        fee_dict = await self._my_executor.get_symbol_trade_fee(self.symbol_name)
        self.symbol_maker_fee = fee_dict['maker_fee']
        self.symbol_taker_fee = fee_dict['taker_fee']
        self._log_info('maker fee rate: {}'.format(self.symbol_maker_fee))
        self._log_info('taker fee rate: {}'.format(self.symbol_taker_fee))
        self._my_operator.set_trade_fee(maker_fee=self.symbol_maker_fee, taker_fee=self.symbol_taker_fee)
        self._my_operator.start_stg()

        self._reasonable_order_num_estimate()

        if self.trigger_start:
            self._pre_update_text_task.cancel()
        else:
            pass

        self._update_text_task = asyncio.create_task(self._update_detail_info(interval_time=1))

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
            await self._post_market_order(self.BUY, self.entry_grid_qty)

        # 2. 开始撒网
        asyncio.create_task(self._layout_net())

    # strategy basic methods
    def _grid_stair_step_up(self) -> None:
        if self.present_stair_num >= self.stairs_total_num:
            raise ValueError('已达到策略台阶上限，不可调用')
            return
        # upward_grid_num = self.present_step_up_index - self.present_base_index

        # self.all_grid_price = (0,) * (self.indices_of_filling[0] - len(self.all_lower_prices[self.present_stair_num])) + \
        #                       self.all_lower_prices[self.present_stair_num] + self.all_grid_price[self.indices_of_filling[0]:]

        self.present_base_index = self.present_step_up_index
        up_grid_num = int(calc(calc(self.all_grid_price[self.present_base_index], self.filling_step_ratio, '*'), self.grid_price_step, '/'))
        self.present_step_up_index += up_grid_num
        down_grid_num = int(calc(calc(self.all_grid_price[self.present_base_index], self.lower_space_ratio, '*'), self.grid_price_step, '/'))
        self.present_bottom_index = self.present_base_index - down_grid_num
        # 如果大于max index，数值多少无所谓了
        self.present_step_up_index = self.indices_of_filling[1] if self.present_stair_num < (self.stairs_total_num - 1) else self.present_base_index + up_grid_num
        self.zero_pos_index = self.present_base_index + int((self.present_step_up_index - self.present_base_index) * (1 - self.short_ratio))

        self.present_step_up_price = self.all_filling_prices[self.present_stair_num + 1] if self.present_stair_num < (self.stairs_total_num - 1) else \
            self.round_step_precision(calc(self.all_filling_prices[-1], 1 + self.filling_step_ratio, '*'), self.symbol_price_min_step)  # 超出上界的台阶价格
        self.present_bottom_price = self.all_grid_price[self.present_bottom_index]

        # self.all_grid_quantity = (0,) * self.present_bottom_index + self.all_grid_quantity[self.present_bottom_index:]
        self.all_grid_quantity = (0,) * self.present_bottom_index + \
                                 (self.all_grid_quantity[self.present_base_index + 1],) * (self.present_base_index + 1 - self.present_bottom_index) + \
                                 self.all_grid_quantity[self.present_base_index + 1:]

        # 增添统计数据，并更新
        self._trading_statistics['realized_profit'] = calc(self._trading_statistics['realized_profit'], self._each_stair_profit[self.present_stair_num], '+')
        self._all_grid_sell_num[:self.present_base_index + 1] = [0] * (self.present_base_index + 1)
        # todo: 对于子账号，订单套利并统计，需要重新计算

        self.present_stair_num += 1
        self.indices_of_filling.pop(0)
        self._add_buffer_vars()

        print('传参给子账号')
        self._my_operator.deliver_grid_param(grid_prices=self.all_grid_price, grid_quantities=self.all_grid_quantity)
        self.send_index()

    def _add_buffer_vars(self) -> None:
        # if self.saved_stair_num > self.stairs_total_num:
        #     raise ValueError('策略保存已达到网格上限')
        if self.saved_stair_num == self.stairs_total_num:
            return
        # add_grid_price = ()
        if self.saved_stair_num == self.stairs_total_num - 1:
            add_grid_price = self.arithmetic_grid_calc(self.all_filling_prices[self.saved_stair_num], self.grid_price_step, self.up_limit_price)[1:]  # 需要剔除base
            if len(add_grid_price) == 0:
                # 如果补仓价格再往上一个网格，就超出边界，则直接添加一个边界价格的网格
                add_grid_price.append(self.up_limit_price)
            else:
                add_grid_price[-1] = self.up_limit_price
            # up_step_low_prices = ()
            # filling_grid_num = self.filling_grid_step_num  # 该变量，使得最高台阶时，每格数量仍然合理
            filling_grid_num = len(self.arithmetic_grid_calc(self.all_filling_prices[-1], self.grid_price_step, self.all_filling_prices[-1] * (1 + self.filling_step_ratio))) - 1

        elif self.saved_stair_num < self.stairs_total_num - 1:
            add_grid_price = self.arithmetic_grid_calc(self.all_filling_prices[self.saved_stair_num],
                                                       self.grid_price_step, self.all_filling_prices[self.saved_stair_num + 1])[1:]
            add_grid_price[-1] = self.all_filling_prices[self.saved_stair_num + 1]
            # up_step_low_prices = tuple(self.isometric_grid_calc(
            #     self.all_filling_prices[self.saved_stair_num + 1],
            #     self.grid_step_ratio,
            #     self.round_step_precision(self.all_filling_prices[self.saved_stair_num + 1] * (1 - self.lower_space_ratio), self.symbol_price_min_step))[:-1])  # 不包括base

            filling_grid_num = len(add_grid_price)

        else:
            raise ValueError('增加缓冲价格有误，存储台阶数量计算错误')
            return

        # 切片以使得长度相等
        # add_grid_qty = tuple(self.unequal_grid_qty_calc(self.all_filling_prices[self.saved_stair_num], filling_grid_num, self.filling_fund))[:len(add_grid_price)]
        add_grid_qty = tuple([self.grid_qty_calc(self.all_filling_prices[self.saved_stair_num], filling_grid_num, self.filling_fund), ] * filling_grid_num)
        add_filling_qty = int(sum(add_grid_qty) * (1 - self.short_ratio))
        add_grid_qty = add_grid_qty[:len(add_grid_price)]

        self.all_grid_price += tuple(add_grid_price)
        self.all_grid_quantity += add_grid_qty
        # if not up_step_low_prices == ():
        #     self.all_lower_prices.append(up_step_low_prices)
        self.indices_of_filling.append(self.indices_of_filling[-1] + filling_grid_num)  # 会超出max index
        self.all_filling_quantities.append(add_filling_qty)
        self.max_index = len(self.all_grid_price) - 1
        self._all_grid_buy_num += [0] * len(add_grid_price)
        self._all_grid_sell_num += [0] * len(add_grid_price)
        self._each_stair_profit.append(self.unmatched_profit_calc(
            initial_index=self.indices_of_filling[-2],
            current_index=self.indices_of_filling[-1] if self.saved_stair_num < self.stairs_total_num - 1 else self.max_index,
            all_prices=self.all_grid_price,
            all_quantities=self.all_grid_quantity,
            init_pos_price=self.all_grid_price[self.indices_of_filling[-2]],
            init_pos_qty=add_grid_qty[-1] * int(len(add_grid_qty) * (1 - self.short_ratio)),
            current_price=self.all_grid_price[self.indices_of_filling[-1]] if self.saved_stair_num < self.stairs_total_num - 1 else self.up_limit_price
        ))

        self.saved_stair_num += 1
        # 简单粗暴直接最后一次赋值
        if self._my_operator and self.saved_stair_num == self.stairs_total_num:
            print('传参给子账号')
            self._my_operator.deliver_grid_param(grid_prices=self.all_grid_price, grid_quantities=self.all_grid_quantity)

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
        self._log_info('\n开始多账号撒网\n')
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
                        'quantity': self.all_grid_quantity[self.parse_id(each['id'])[0] + 1],  # todo: 对于+1后续再检查
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
                        'quantity': self.all_grid_quantity[self.parse_id(each['id'])[0]],
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
        # 新策略根据账户数量设定挂单数量.注意：只限用于100挂单限制的btc，做多方向，空单更多
        # self.max_buy_order_num = self.max_sell_order_num = int(self.symbol_orders_limit_num * 0.8 / 2) * self._account_num
        self.max_buy_order_num = int(self.symbol_orders_limit_num * 0.6 / 2) * self._account_num
        self.max_sell_order_num = int(self.symbol_orders_limit_num * 1.2 / 2) * self._account_num
        # self.min_buy_order_num = self.min_sell_order_num = int(self.symbol_orders_limit_num * 0.4 / 2) * self._account_num
        self.min_buy_order_num = int(self.symbol_orders_limit_num * 0.3 / 2) * self._account_num
        self.min_sell_order_num = int(self.symbol_orders_limit_num * 0.6 / 2) * self._account_num
        # self.buffer_buy_num = self.buffer_sell_num = max(10, int(self.min_buy_order_num / 2))
        self.buffer_buy_num = max(10, int(self.min_buy_order_num / 2))
        self.buffer_sell_num = max(10, int(self.min_sell_order_num / 2))

    async def _post_market_order(self, market_side: str, market_qty: int) -> None:
        # 该方法仅适用于策略市价补仓!
        # await self.send_index()
        command = Token.ORDER_INFO.copy()
        command['side'] = market_side
        command['quantity'] = market_qty
        self._log_info('市价下单 {} 张'.format(market_qty))
        # await self.command_transmitter(trans_command=command, token=Token.TO_POST_MARKET)
        self._MARKET_ORDER_qty_target = self._MARKET_ORDER_qty_left = market_qty
        self._my_operator.deliver_market_order(market_side, market_qty, self.present_base_index, self.zero_pos_index)

        if market_side == self.BUY:
            self._account_position_theory += market_qty
        elif market_side == self.SELL:
            self._account_position_theory -= market_qty

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
            # filled_sell_num = this_order_index - self.critical_index
            # self._trading_statistics['filled_sell_order_num'] += filled_sell_num
            # adding_volume = calc_sum([calc(each_price, calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'), '*') for each_price in
            #                           self.all_grid_price[self.critical_index + 1:this_order_index + 1]])
            # self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
            # self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

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
                    # self._trading_statistics['filled_sell_order_num'] += instant_post_num
                    # adding_volume = calc_sum([calc(each_price, calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'), '*') for each_price in
                    #                           self.all_grid_price[self.critical_index + 1:this_order_index + 1]])
                    # self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
                    # self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

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
                                posting_order['quantity'] = self.all_grid_quantity[self.parse_id(each_info['id'])[0] + 1]
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
                                    'quantity': self.all_grid_quantity[self.parse_id(each_info['id'])[0] + 1],
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
                    # self._trading_statistics['filled_buy_order_num'] += instant_post_num
                    # adding_volume = calc_sum([calc(each_price, calc(self.grid_each_qty, self.symbol_quantity_min_step, '*'), '*') for each_price in
                    #                           self.all_grid_price[this_order_index:self.critical_index]])
                    # self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
                    # self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

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
                                posting_order['quantity'] = self.all_grid_quantity[self.parse_id(each_info['id'])[0]]
                                self._log_info('挂卖  {:2} 单\t\t\t价格: {:<12}\tid: {:<10}'.format(str(each_num + 1), posting_order['price'], posting_order['id']))

                                # if this_order_index % 2 == 0:
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
                                    'quantity': self.all_grid_quantity[self.parse_id(each_info['id'])[0]],
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
                                posting_order['quantity'] = self.all_grid_quantity[self.parse_id(each_info['id'])[0] + 1]
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
                                    'quantity': self.all_grid_quantity[self.parse_id(each_info['id'])[0] + 1],
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
                                posting_order['quantity'] = self.all_grid_quantity[self.parse_id(each_info['id'])[0]]
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
                                    'quantity': self.all_grid_quantity[self.parse_id(each_info['id'])[0]],
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

        # 3.检查买卖单数量并维护其边界挂单，补单全用batch order
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
                    # self._cancel_partial_order_check(each_info['id'])
                    # if each_info['id'] in self.partially_filled_orders.keys():
                    #     traded_qty = int(self.grid_each_qty) - self.partially_filled_orders[each_info['id']]
                    #     self._accumulated_pos_deviation -= traded_qty
                    #     self.partially_filled_orders.pop(each_info['id'])

            elif open_buy_orders_num < self.min_buy_order_num:
                if open_buy_orders_num == 0:
                    endpoint_index = self.critical_index
                else:
                    endpoint_index = self.parse_id(self.open_buy_orders[0]['id'])[0]

                # 在超高频网格当中，可能一下子现存订单就非常少，需要一次补充很多挂单     # todo: 在未来的Ultra策略中可以优化
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
                                'quantity': self.all_grid_quantity[self.parse_id(_info['id'])[0] + 1],
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
                    # self._cancel_partial_order_check(each_info['id'])

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
                                'quantity': self.all_grid_quantity[self.parse_id(_info['id'])[0]],
                            } for _info in filling_post_batch
                        ]
                        filling_batch_cmd['status'] = Token.TO_POST_BATCH_POC
                        await self.command_transmitter(trans_command=filling_batch_cmd, token=Token.TO_POST_BATCH_POC)

        # 4.最后根据需要更新相关变量
        if (self._trading_statistics['filled_buy_order_num'] + self._trading_statistics['filled_sell_order_num']) % 40 == 0:
            self._need_adjust_pos = True

    async def _maintainer_by_price(self) -> None:
        """
        根据实时价格维护网格，操作：市价下单，撤销挂单并重新挂买单
        :return:
        """
        if self.current_symbol_price >= self.present_step_up_price:
            self._log_info('\n>>> 价格触发，台阶向上移动\t触发价格: {}\n'.format(self.present_step_up_price))
            # 首先市价下单
            await self._post_market_order(self.BUY, self.all_filling_quantities[self.present_stair_num])
            # 更新关键变量
            self._grid_stair_step_up()
            # 重新挂买单
            asyncio.create_task(self._repost_under_orders())

    async def _maintainer_by_index(self, trigger_index: int) -> None:
        """
        由于网格策略逻辑，该方法调用与网格维护之前，判断挂单成交后，首先维护台阶，再维护网格挂单
        :param trigger_index: 成交或驳回的订单id
        :return:
        """
        if trigger_index >= self.present_step_up_index:
            self._log_info('\n>>> 挂单触发，台阶向上移动\t触发价格: {}\t触发网格: {}'.format(self.present_step_up_price, trigger_index))
            # 首先市价下单
            await self._post_market_order(self.BUY, self.all_filling_quantities[self.present_stair_num])
            # 更新关键变量
            self._grid_stair_step_up()
            # 重新挂买单
            asyncio.create_task(self._repost_under_orders())

    async def _repost_under_orders(self) -> None:
        """
        当网格到达补仓点位时，下方的等比网格数量需要修改
        因此撤销所有买单，并重新挂买单。
        台阶维护操作发生在网格维护之前，因此读取open buy orders的所有index，筛选(c index - base index 之间)并重新挂单即可
        由于有延时操作，该方法使用创建协程任务调用。该方法在高频时可能会存在撤单失败和挂单失败的情况
        :return:
        """
        # 首先获取所有index
        repost_buy_indices = [self.parse_id(each_order['id'])[0] for each_order in self.open_buy_orders]
        # 如果买单跨越网格下界，删除多余网格
        if self.present_bottom_index >= repost_buy_indices[0]:
            over_border_num = repost_buy_indices.index(self.present_bottom_index)
            self.open_buy_orders = self.open_buy_orders[over_border_num:]
            # repost_buy_indices = repost_buy_indices[over_border_num:]
        repost_buy_orders = self.open_buy_orders.copy()

        # 撤销挂单，使用open buy变量即可
        for each_info in reversed(self.open_buy_orders):
            cancel_cmd = Token.ORDER_INFO.copy()
            cancel_cmd['symbol'] = self.symbol_name
            cancel_cmd['id'] = each_info['id']
            await self.command_transmitter(trans_command=cancel_cmd, token=Token.TO_CANCEL)

        # 撤单后停顿
        await asyncio.sleep(0.5)
        # 重新撒网下部分，由于时间停顿，使用复制变量操作
        while True:
            if len(repost_buy_orders) == 0:
                break
            filling_post_batch, repost_buy_orders = repost_buy_orders[:self._batch_orders_num], repost_buy_orders[self._batch_orders_num:]
            filling_batch_cmd = Token.BATCH_ORDER_INFO.copy()
            filling_batch_cmd['orders'] = [
                {
                    'symbol': self.symbol_name,
                    'id': _info['id'],
                    'price': self.all_grid_price[self.parse_id(_info['id'])[0]],
                    'side': self.BUY,
                    'quantity': self.all_grid_quantity[self.parse_id(_info['id'])[0]],
                } for _info in filling_post_batch
            ]
            filling_batch_cmd['status'] = Token.TO_POST_BATCH_POC
            await self.command_transmitter(trans_command=filling_batch_cmd, token=Token.TO_POST_BATCH_POC)

    async def _terminate_trading(self, reason: str = '') -> None:
        if not self._is_trading:
            self._log_info('--- 策略正在停止，请稍等。。。')
            self.manually_stop_request_time += 1
            self._log_info(str(self.manually_stop_request_time))
            # 点击次数多，用户强行终止
            if self.manually_stop_request_time >= 10:
                self._log_info('--- 用户强行终止策略，请自行平仓和撤销挂单')
                if isinstance(self._update_text_task, asyncio.Task):
                    self._update_text_task.cancel()

                self.force_stopped = True
                self._my_logger.close_file()
                # self._my_preserver.stop_preserving()
                self._my_executor.stop_single_contract_order_subscription(self.symbol_name)
                self._my_executor.stop_single_contract_ticker_subscription(self.symbol_name)
                self._my_executor.strategy_stopped(self.stg_num)
                # self._bound_running_column = None
            return
        self._is_trading = False

        if isinstance(self._update_text_task, asyncio.Task):
            self._update_text_task.cancel()

        cancel_cmd, close_cmd = Token.ORDER_INFO.copy(), Token.ORDER_INFO.copy()
        cancel_cmd['symbol'], close_cmd['symbol'] = self.symbol_name, self.symbol_name

        await asyncio.sleep(0.8)  # 此处延时是为了确保能撤销所有挂单，防止撤单和挂单同时请求，最后出现还剩一单挂着的情况
        await self.command_transmitter(trans_command=cancel_cmd, token=Token.CANCEL_ALL)
        await self._update_trading_statistics()
        await asyncio.sleep(1)

        self._log_info('--- 市价平仓')
        self._log_info('--- 主账户不统计平仓带来的手续费和交易量')

        await self.command_transmitter(trans_command=close_cmd, token=Token.CLOSE_POSITION)

        self._log_info('--- 终止策略，终止原因: {}'.format(reason))
        await self._update_detail_info(only_once=True)

        if not self.force_stopped:
            self._my_logger.close_file()
            # self._my_preserver.stop_preserving()
            self._my_executor.stop_single_contract_order_subscription(self.symbol_name)
            self._my_executor.stop_single_contract_ticker_subscription(self.symbol_name)
            self._my_executor.strategy_stopped(self.stg_num)

            # self._bound_running_column = None

        self._my_operator.terminate()

    async def _update_trading_statistics(self) -> None:
        """
        更新策略统计数据，需要计算已套利收益，未实现盈亏和总收益。已做多收益在台阶上升时已统计
        :return:
        """
        # 计算套利收益
        add_matched_profit = 0
        # 注意：由于我们需要同时访问当前和下一个网格，循环将停止在倒数第二个元素
        for i in range(len(self.all_grid_price) - 1):
            # 计算每个网格的成交对数
            matched_num = min(self._all_grid_buy_num[i], self._all_grid_sell_num[i + 1])
            # 更新买卖成交次数
            self._all_grid_buy_num[i] -= matched_num
            self._all_grid_sell_num[i + 1] -= matched_num
            # 如果存在成交对，计算套利收益
            if matched_num > 0:
                profit_per_pair = calc(calc(calc(self.all_grid_price[i + 1], self.all_grid_price[i], '-'),
                                            calc(self.all_grid_quantity[i + 1], self.symbol_quantity_min_step, '*'), '*'), matched_num, '*')
                # profit_per_pair = (self.all_grid_price[i + 1] - self.all_grid_price[i]) * self.all_grid_quantity[i + 1] * matched_num
                add_matched_profit = calc(add_matched_profit, profit_per_pair, '+')
            elif matched_num < 0:
                raise ValueError('成交对数小于0，统计错误!!!')
        self._trading_statistics['matched_profit'] = calc(self._trading_statistics['matched_profit'], add_matched_profit, '+')

        # 用最新实时价格计算未配对盈亏
        unmatched_profit = self.unmatched_profit_calc(
            initial_index=self.present_base_index,
            current_index=self.critical_index,
            all_prices=self.all_grid_price,
            all_quantities=self.all_grid_quantity,
            init_pos_price=self.all_grid_price[self.present_base_index],
            init_pos_qty=self.entry_grid_qty if self.present_stair_num == 0 else self.all_filling_quantities[self.present_stair_num - 1],
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
            # self._update_column_text()
            self._save_strategy_data()

            start_t = pd.to_datetime(self._trading_statistics['strategy_start_time'], unit='ms')
            current_t = pd.to_datetime(self.gen_timestamp(), unit='ms')
            running_time = current_t - start_t
            days: int = running_time.days
            seconds: int = running_time.seconds
            hours, seconds = int(seconds / 3600), seconds % 3600
            minutes, seconds = int(seconds / 60), seconds % 60

            showing_texts = '智能调仓网格 统计信息:'
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
            # showing_texts += '\n\n修正仓位挂单:\t\t{}\n'.format(False if self.adjusting_index == -1 else True)
            showing_texts += '\n\n当前正确仓位:\t\t{:<10}张\n\n'.format(self._current_valid_position)
            # showing_texts += '累计计算仓位:\t\t{:<10}张\n'.format(self._account_position_theory)
            # showing_texts += '累计仓位偏移:\t\t{:<10}张\n\n'.format(self._accumulated_pos_deviation)
            # showing_texts += '部分成交订单:\t\t{:<10}个挂单\n\n'.format(len(self.partially_filled_orders))

            showing_texts += '-' * 58
            showing_texts += '\n\n卖单挂单成交次数:\t{:<10}\n'.format(str(self._trading_statistics['filled_sell_order_num']))
            showing_texts += '买单挂单成交次数:\t{:<10}\n\n'.format(str(self._trading_statistics['filled_buy_order_num']))
            showing_texts += '-' * 58
            showing_texts += '\n\n已补仓次数:\t\t{} / {}\n'.format(self.present_stair_num, self.stairs_total_num)
            showing_texts += '当前套利区间:\t\t{:<10} ~  {:<10}\n'.format(self.present_bottom_price, self.present_step_up_price)
            showing_texts += '\n总达成交易量:\t\t{:<20}\t{}\n\n'.format(str(self._trading_statistics['achieved_trade_volume']), self.symbol_name[-4:])
            showing_texts += '-' * 58
            showing_texts += '\n\n套利收益:\t\t{:<20}\t{}\n'.format(self._trading_statistics['matched_profit'], self.symbol_name[-4:])
            showing_texts += '做多收益:\t\t{:<20}\t{}\n'.format(self._trading_statistics['realized_profit'], self.symbol_name[-4:])

            # 如果价格下冲超出下边界，提示一下
            if self.current_symbol_price <= self.present_bottom_price:
                showing_texts += '未实现盈亏:\t\t{:<20}\t{} (价格走出下区间!)\n'.format(
                    self._trading_statistics['unrealized_profit'], self.symbol_name[-4:])
            else:
                showing_texts += '未实现盈亏:\t\t{:<20}\t{}\n'.format(self._trading_statistics['unrealized_profit'], self.symbol_name[-4:])
            showing_texts += '\n交易手续费:\t\t{:<20}\t{}\n\n'.format(self._trading_statistics['total_trading_fees'], self.symbol_name[-4:])
            showing_texts += '-' * 58
            showing_texts += '\n\n策略净收益:\t\t{:<20}\t{}\n\n'.format(self._trading_statistics['final_profit'], self.symbol_name[-4:])
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

            showing_texts = '智能调仓网格 等待触发中。。。'
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

    def _save_strategy_data(self) -> None:
        pass

    async def restart(self, stg_info: dict, save_file_name: str) -> bool:
        pass

    def restart_failed(self) -> None:
        pass

    # functional methods
    async def _check_position(self) -> None:
        pass

    async def _check_open_orders(self) -> None:
        pass

    async def _dealing_ENTRY_ORDER(self, order_data_dict: dict) -> None:
        """
        处理入场挂单，计算挂单剩余数量，如果为0，则表示全部成交，开启网格
        成交后添加统计信息
        :param order_data_dict:
        :return:
        """
        if self.trigger_start:
            filled_size: int = abs(order_data_dict['quantity'])  # 对于非线性做多，入场挂单为做多挂单，数量为正数，其实不需要abs
            self._ENTRY_ORDER_qty_left = self._ENTRY_ORDER_qty_left - filled_size
            if self._ENTRY_ORDER_qty_left > 0:
                self._log_info('~~~ 触发挂单部分成交 {} 张，已完成 {} %'.format(str(filled_size), round(self.entry_grid_qty - self._ENTRY_ORDER_qty_left) / self.entry_grid_qty))
            else:
                # 完全成交，开启网格
                self._log_info('\n\n~~~ 触发挂单完全成交!\n\n')

                asyncio.create_task(self._start_strategy())

                fee_dict = await self._my_executor.get_symbol_trade_fee(self.symbol_name)
                self.symbol_maker_fee = fee_dict['maker_fee']
                self.symbol_taker_fee = fee_dict['taker_fee']
                self._log_info('maker fee rate: {}'.format(self.symbol_maker_fee))
                self._log_info('taker fee rate: {}'.format(self.symbol_taker_fee))

                adding_volume = calc(calc(self.entry_grid_qty, self.symbol_quantity_min_step, '*'), self.entry_grid_price, '*')
                self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
                self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

                self._account_position_theory += self.entry_grid_qty

        else:
            self._log_info('received entry order id while not trigger start! plz check code')

    async def _dealing_MARKET_ORDER(self, order_data_dict: dict) -> None:
        """
        处理所有市价挂单，市价挂单一般分为多个部分成交收到，此处做简易处理
        同时更新统计信息：交易量、交易手续费
        :param order_data_dict:
        :return:
        """
        filled_size: int = abs(order_data_dict['quantity'])
        filled_price: float = float(order_data_dict['price'])
        # 更新统计信息，此处信息最准确
        adding_volume = calc(calc(filled_size, self.symbol_quantity_min_step, '*'), filled_price, '*')
        self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
        self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_taker_fee, '*'), '+')

        self._MARKET_ORDER_qty_left = self._MARKET_ORDER_qty_left - filled_size
        self._MARKET_ORDER_value = calc(self._MARKET_ORDER_value, calc(filled_size, filled_price, '*'), '+')
        if self._MARKET_ORDER_qty_left > 0:
            self._log_info(
                '\n市价请求成交中，已完成 {} %'.format(str(round((self._MARKET_ORDER_qty_target - self._MARKET_ORDER_qty_left) / self._MARKET_ORDER_qty_target * 100, 1))))
        elif self._MARKET_ORDER_qty_left == 0:
            avg_price = calc(self._MARKET_ORDER_value, self._MARKET_ORDER_qty_target, '/')
            self._log_info('\n市价挂单全部成交! 成交均价: {}\n'.format(str(avg_price)))
            # todo: 在此处更新累计统计信息
            self._MARKET_ORDER_qty_target = 0
            self._MARKET_ORDER_value = 0
        else:
            self._log_info('error: actual filled market qty over target qty, plz check code and trade status!')

    def _reset_functional_vars(self) -> None:
        # 市价单
        self._MARKET_ORDER_qty_target = self._MARKET_ORDER_qty_left = 0
        self._MARKET_ORDER_value = 0

    # interaction methods
    # noinspection PyMethodOverriding
    async def report_receiver(self, recv_data_dict: dict, acc_num: int, append_info: str = None) -> None:

        # 由于更新订单通道，现在部分成交将会被拆分收到信息
        if recv_data_dict['status'] == Token.ORDER_FILLED:
            # 收到策略订单id，根据订单类别，分别处理
            order_index, order_side = self.parse_id(recv_data_dict['id'])

            if order_index == self.ENTRY_ORDER_ID:
                await self._dealing_ENTRY_ORDER(recv_data_dict)

            elif order_index == self.MARKET_ORDER_ID:
                await self._dealing_MARKET_ORDER(recv_data_dict)

            else:
                # 其他普通订单，维护网格。判断成交数量是否为原始网格数量，如果是，则直接维护网格，如果不是，则先判断部分成交再维护网格
                order_qty: int = abs(recv_data_dict['quantity'])  # 这一部分相当于 dealing normal fulfilled order
                if order_side == self.BUY:
                    self._account_position_theory += order_qty
                    # 更新订单成交数统计，交易量和手续费
                    self._all_grid_buy_num[order_index] += 1
                    self._trading_statistics['filled_buy_order_num'] += 1
                    add_volume = calc(calc(self.all_grid_quantity[order_index + 1], self.symbol_quantity_min_step, '*'), self.all_grid_price[order_index], '*')
                    self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], add_volume, '+')
                    self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(add_volume, self.symbol_maker_fee, '*'), '+')

                else:
                    self._account_position_theory -= order_qty
                    self._all_grid_sell_num[order_index] += 1
                    self._trading_statistics['filled_sell_order_num'] += 1
                    add_volume = calc(calc(self.all_grid_quantity[order_index], self.symbol_quantity_min_step, '*'), self.all_grid_price[order_index], '*')
                    self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], add_volume, '+')
                    self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(add_volume, self.symbol_maker_fee, '*'), '+')

                await self._maintainer_by_index(order_index)
                await self._maintain_grid_order(order_index, order_side, recv_data_dict['id'], append_info, order_filled=True)

        elif recv_data_dict['status'] == Token.POST_SUCCESS:
            self._log_info('账户{} 收到挂单成功信息\t\t价格: {:<12}\tid: {:<10}'.format(acc_num, str(float(recv_data_dict['price'])), recv_data_dict['id']))

        elif recv_data_dict['status'] == Token.POC_SUCCESS:
            self._log_info('账户{} 收到poc挂单成功信息\t\t价格: {:<12}\tid: {:<10}'.format(acc_num, str(float(recv_data_dict['price'])), recv_data_dict['id']))

        elif recv_data_dict['status'] == Token.CANCEL_SUCCESS:
            self._log_info('收到撤单成功信息\t\t\t\tid: {:<10}'.format(recv_data_dict['id']))

        elif recv_data_dict['status'] == Token.CANCEL_POC_SUCCESS:
            self._log_info('账户{} 收到poc撤单成功信息\t\t\t\tid: {:<10}'.format(acc_num, recv_data_dict['id']))

        elif recv_data_dict['status'] == Token.PARTIALLY_FILLED:
            self._log_info('\nerror: invalid info received, plz check code\n')

        elif recv_data_dict['status'] == Token.ORDER_UPDATE:  # 对于gate服务器，该收信有可能是订单部分成交或订单修改成功
            raise ValueError('暂未处理仓位修正功能，不会出现该情况')

        elif recv_data_dict['status'] == Token.UNIDENTIFIED:
            pass
        elif recv_data_dict['status'] == Token.FAILED:
            pass
        elif recv_data_dict['status'] == Token.POST_FAILED:
            self._log_info('\n限价挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            self._log_info('失败信息: {}'.format(append_info))

        elif recv_data_dict['status'] == Token.POC_FAILED:
            self._log_info('\n账户{} poc挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(acc_num, recv_data_dict['price'], recv_data_dict['id']))
            self._log_info('失败信息: {}'.format(append_info))

        elif recv_data_dict['status'] == Token.POC_REJECTED:
            self._log_info('\n账户{} poc挂单失败，价格错位\t\t系统时间 {}'.format(acc_num, str(pd.to_datetime(self.gen_timestamp(), unit='ms') + pd.Timedelta(hours=8))))
            this_order_index, side = self.parse_id(recv_data_dict['id'])

            await self._maintainer_by_index(this_order_index)
            await self._maintain_grid_order(this_order_index, side, recv_data_dict['id'], append_info, order_filled=False)

        elif recv_data_dict['status'] == Token.CANCEL_FAILED:
            self._log_info('\n账户{} 撤销挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(acc_num, recv_data_dict['price'], recv_data_dict['id']))
            if append_info:
                self._log_info(append_info)

        elif recv_data_dict['status'] == Token.AMEND_POC_FAILED:
            raise ValueError('暂未处理仓位修正功能，不会出现该情况2')

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
            asyncio.create_task(self._my_operator.command_receiver(command_dict))
        elif token == Token.TO_POST_POC:
            # todo: 需要将所有统一起来，目前只有此处修改，需要全局更改
            command_dict['id'] = trans_command['id']
            command_dict['price'] = trans_command['price']
            command_dict['side'] = trans_command['side']
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self._my_operator.command_receiver(command_dict))
        elif token == Token.TO_CANCEL:
            command_dict['id'] = trans_command['id']
            command_dict['status'] = token
            asyncio.create_task(self._my_operator.command_receiver(command_dict))
        elif token == Token.TO_POST_BATCH:
            asyncio.create_task(self._my_operator.command_receiver(trans_command))
        elif token == Token.TO_POST_BATCH_POC:
            # print('总领需要批量挂单')
            asyncio.create_task(self._my_operator.command_receiver(trans_command))
        elif token == Token.TO_POST_MARKET:
            # print('总领需要市价挂单')
            command_dict['side'] = trans_command['side']
            command_dict['id'] = self.gen_id(self.MARKET_ORDER_ID, trans_command['side'])
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self._my_operator.command_receiver(command_dict))
        elif token == Token.AMEND_POC_PRICE:
            command_dict['id'] = trans_command['id']
            command_dict['price'] = trans_command['price']
            command_dict['status'] = token
            asyncio.create_task(self._my_operator.command_receiver(command_dict))
        elif token == Token.AMEND_POC_QTY:
            command_dict['id'] = trans_command['id']
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self._my_operator.command_receiver(command_dict))
        elif token == Token.CANCEL_ALL:
            command_dict['status'] = token
            asyncio.create_task(self._my_operator.command_receiver(command_dict))
        elif token == Token.CLOSE_POSITION:
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self._my_operator.command_receiver(command_dict))
        elif token == Token.TEMP_TOKEN:
            command_dict['status'] = token
            asyncio.create_task(self._my_operator.command_receiver(command_dict))
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
            self.send_index()

            # === 高频缓冲功能 === # 超过某个固定时间仍未收到ticker信息，则此时交易不剧烈，可以做额外操作
            if self._ticker_delay_timer:
                self._ticker_delay_timer.cancel()
            self._ticker_delay_timer = self._running_loop.call_later(self._ticker_delay_trigger_time, self.delay_task)

            if self.current_symbol_price > self._x_grid_up_limit:
                self._log_info('检测到价格超出上边界!需要终止策略')
                asyncio.create_task(self._terminate_trading(reason='达到网格上边界'))

            # 添加价格维护，构造冗余
            await self._maintainer_by_price()

            # 如果订单成交迅速，ticker收信为 1s，判断也比较频繁
            # if self._accumulated_pos_deviation != 0:
            #     self._need_adjust_pos = True

        # if self.developer_switch:
        #     self._reset_functional_vars()
        #     self.developer_switch = False
        #     self._log_info('\n!!! 重置相关任务变量 !!!\n')
        # raise ValueError('test error')

    async def book_ticker_receiver(self, recv_book_ticker: dict) -> None:
        ask_price = float(recv_book_ticker['a'])
        bid_price = float(recv_book_ticker['b'])
        await self._my_operator.send_best_price(ask_price, bid_price)

    def send_index(self):
        asyncio.create_task(self._my_operator.ticker_sender(self.critical_index, self.present_base_index, self.zero_pos_index, self.present_step_up_index, self.current_symbol_price))
        # await self._my_operator.ticker_sender(self.critical_index, self.present_base_index, self.zero_pos_index, self.present_step_up_index)

    def delay_task(self):
        self._log_info('>>> ')
        asyncio.create_task(self._my_operator.tick_sender())

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

    def isometric_grid_calc(self, base_price: float, grid_ratio: float, boundary_price: float) -> list[float]:
        """
        计算等比网格的网格价格，自动使用合约价格精度规整
        :param base_price: 网格基准价格，通常为市价买入价格
        :param grid_ratio: 网格间距百分比，绝对数值
        :param boundary_price: 边界价格，计算小于等于该边界的网格价格
        :return: 返回存储网格价格的list，包括最开始的base_price，包括边界价格
        """
        all_price = []
        n_count = 0  # 保险，防止死循环
        if boundary_price > base_price:
            # 计算上方网格价格
            while True:
                each_grid_price = self.round_step_precision(base_price * (1 + grid_ratio) ** n_count, self.symbol_price_min_step)
                if each_grid_price <= boundary_price:
                    all_price.append(each_grid_price)
                else:
                    break
                n_count += 1
                if n_count >= 99999999:
                    raise ValueError('计算上方网格价格迭代次数过多!')
                    break
        elif boundary_price < base_price:
            # 计算下方网格价格
            while True:
                each_grid_price = self.round_step_precision(base_price * (1 - grid_ratio) ** n_count, self.symbol_price_min_step)
                if each_grid_price >= boundary_price:
                    all_price.insert(0, each_grid_price)
                else:
                    break
                n_count += 1
                if n_count >= 99999999:
                    raise ValueError('计算下方网格价格迭代次数过多!')
                    break

        else:
            raise ValueError('网格价格区间范围为0')
        # 防止太密的价格导致网格价格重复
        return sorted(set(all_price))

    @staticmethod
    def arithmetic_grid_calc(base_price: float, step_price: float, boundary_price: float) -> list[float]:
        all_price = []
        n_count = 0  # 保险，防止死循环
        if boundary_price > base_price:
            # 计算上方网格价格
            while True:
                each_grid_price = calc(base_price, calc(n_count, step_price, '*'), '+')
                if each_grid_price <= boundary_price:
                    all_price.append(each_grid_price)
                else:
                    break
                n_count += 1
                if n_count >= 99999999:
                    raise ValueError('计算上方网格价格迭代次数过多!')
                    break
        elif boundary_price < base_price:
            # 计算下方网格价格
            while True:
                each_grid_price = calc(base_price, calc(n_count, step_price, '*'), '-')
                if each_grid_price >= boundary_price:
                    all_price.insert(0, each_grid_price)
                else:
                    break
                n_count += 1
                if n_count >= 99999999:
                    raise ValueError('计算下方网格价格迭代次数过多!')
                    break

        return all_price

    def unequal_grid_qty_calc(self, base_price: float, grid_num: int, fund: float) -> list[int]:
        """
        根据资金平均分配原则，将网格数量平均分配到每个网格
        :param base_price:
        :param grid_num:
        :param fund:
        :return: 基于gate服务器开发，返回整数列表
        """
        deliver_qty = int(calc(fund, calc(base_price, self.symbol_quantity_min_step, '*'), '/'))
        if deliver_qty < grid_num:
            raise ValueError('分配资金不足，参数错误，网格数量小于1')
        elif grid_num <= 0:
            raise ValueError('网格数量为0，无法计算')

        # 每个网格基础分配的数量
        base_quantity = deliver_qty // grid_num
        # 需要额外分配的数量
        extra_quantity = deliver_qty % grid_num
        # 分配数量到每个网格
        quantities = [base_quantity + 1 if i < extra_quantity else base_quantity for i in range(grid_num)]

        return quantities

    def grid_qty_calc(self, base_price: float, grid_num: int, fund: float) -> int:
        # 返回数量相等的网格
        total_qty = int(calc(fund, calc(base_price, self.symbol_quantity_min_step, '*'), '/'))
        each_qty = int(total_qty / grid_num)
        if each_qty <= 0:
            # raise ValueError('每格挂单数量小于等于0')
            print('每格挂单数量小于等于0')
            return 1
        else:
            return each_qty

    def unmatched_profit_calc(self, initial_index: int, current_index: int, all_prices: tuple[float], all_quantities: tuple[int],
                              init_pos_price: float, init_pos_qty: int, current_price: float) -> float:
        """
        便携计算器，可以计算超出区间的网格未配对盈亏，数量自动使用合约规则精度
        该方法也能够用于计算非线性网格+非均等网格数量
        :param initial_index: 初始的index
        :param current_index: 网格当前的index
        :param all_prices: 网格所有价格
        :param all_quantities: 所有网格数量，gate合约张数
        :param init_pos_price: 初始仓位价格
        :param init_pos_qty: 初始仓位数量，gate合约张数，大于0代表买多，小于0做空
        :param current_price: 当前最新价格
        :return:
        """
        if len(all_prices) != len(all_quantities):  # todo: delete if test good，测试计算器正确性，使用工具
            raise ValueError('价格和数量list长度不等，无法计算盈亏')
            return 0
        if initial_index == -1:
            initial_index = len(all_prices) - 1
        if current_index == -1:
            current_index = len(all_prices) - 1

        # 第一部分考虑无网格时的持仓盈亏
        part_1 = calc(calc(current_price, init_pos_price, '-'), calc(init_pos_qty, self.symbol_quantity_min_step, '*'), '*')
        # 第二部分计算未配对网格仓位带来的盈亏
        if current_index > initial_index + 1:
            price_slice = all_prices[initial_index + 1:current_index + 1]  # 索引时，index可以超出范围
            qty_slice = [calc(each_sheet_num, self.symbol_quantity_min_step, '*') for each_sheet_num in all_quantities[initial_index + 1:current_index + 1]]
            # qty_slice = all_quantities[initial_index + 1:current_index + 1]
        elif current_index < initial_index - 1:  # 重要! 需要注意买单的数量为 c index + 1
            price_slice = all_prices[current_index:initial_index]
            qty_slice = [calc(each_sheet_num, self.symbol_quantity_min_step, '*') for each_sheet_num in all_quantities[current_index + 1:initial_index + 1]]
            # qty_slice = all_quantities[current_index:initial_index]
        else:
            price_slice = qty_slice = []

        # part_2 = -abs(calc_sum(each_price * each_qty) - total_qty * current_price)        第二部分计算网格带来的盈亏
        part_2 = -abs(calc(calc_sum([calc(each_price, each_qty, '*') for each_price, each_qty in zip(price_slice, qty_slice)]),
                           calc(calc_sum(qty_slice), current_price, '*'), '-'))

        return calc(part_1, part_2, '+')

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
        print('\n{}: {} market maker grid analyzer 实例被删除，释放资源\n'.format(self.stg_num, self.symbol_name))
