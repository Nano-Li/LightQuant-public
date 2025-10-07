# -*- coding: utf-8 -*-
# @Time : 2023/12/6 11:17
# @Author : 
# @File : SmartGridFutures.py 
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


class SmartGridAnalyzerFutures(Analyzer):
    """
    适用于所有合约的智能调仓，采用等比网格，该策略可以成为终极智能调仓的先导版
    包含基本功能：
        1.可选挂单触发
        2.poc高频挂单，支持高频策略
        3.定时检查并维护仓位和挂单
        4.仓位矫正功能
        5.智能处理累计部分成交挂单
        6.价格偏离预警
    添加额外功能：
        1.等比网格策略，长期更合理
        2.设置每阶补仓，买入金额相同，补仓价格同样按照百分比
        3.影藏的自动填充参数功能
    特殊：
        1.非均匀网格数量的实现：使用列表存储所有网格数量，由于max index 不会挂买单
          卖单使用c index，而买单使用c index+1，如此和初始买入一定数量，达到补仓位全部卖出的逻辑对应
          如此使用一个列表可以同时存储买卖网格数量。未实现盈亏和策略正确仓位也需要重新考量
    """

    STG_NAME = '智能调仓网格'

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

        'grid_rel_step': None,
        'filling_step': None,
        'lower_step': None,
        'filling_fund': None  # 设定补仓资金，按照现货计算
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

        self.grid_step_ratio = None  # 等比网格比例，单位为1
        self.filling_step_ratio = None  # 等比填仓比例，单位为1
        self.lower_space_ratio = None  # 下方空间比例
        self.filling_fund = None  # 每次填仓资金

        # 输入相关，仅作为临时存储
        self._x_grid_up_limit = None
        self._x_leverage = None
        self._x_trigger_start = False
        self._x_trigger_price = None
        self._x_price_rel_step = None
        self._x_filling_step = None
        self._x_lower_step = None
        self._x_filling_fund = None

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
        # 所有网格的数量，于gate而言，指的是合约张数，tuple(int)，与楼上有相似的维护机制，由于买卖单机制，该tuple的0 index没有作用
        self.all_grid_quantity: tuple = ()
        # 需要补仓的价格index， 当 critical_index 属于其中时，执行补仓操作，补仓后，删除index以实现到达位置只补仓一次的功能，该列表随着策略运行会增加index
        self.indices_of_filling: list = []
        # 所有filling_price下方的网格价格，不包括base index，长度最终和楼上一样
        self.all_lower_prices: list[tuple] = []
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
        self.filling_grid_step_num = 0
        # 下方网格数量，包括基准入场网格
        self.lower_grid_step_num = 0  # 两者相加就是做多网格的 网格总数-1
        # 当前保存了几个网格的参数
        self.saved_stair_num = 0

        # 上方是动态变量，以下是静态变量
        # 网格总数量，仅参考用，意义不大
        self.grid_total_num = 0
        self.max_index = 0
        # 所有做多网格的基准入场价格，不包括策略入场价，在一开始就计算清楚
        self.all_filling_prices: list[float] = []
        # 所有补仓数量，适应gate张数
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
        # 初始买入数量, gate合约张数
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
        # 部分成交订单处理  {'id': int}   order_id, left_quantity   注意买卖挂单数量均用绝对值储存
        self.partially_filled_orders: dict[str, int] = {}
        # 按大小顺序？存储部分成交订单index list, 用于判断距离并定时处理
        self.partially_orders_indices_list: list[int] = []

        # 策略需要马上修正挂单，该变量也充当类似开关功能
        self._need_fix_order: bool = False
        # noinspection PyTypeChecker
        self._fix_order_task: asyncio.Task = None
        # 设置一个锁，该锁为True时，策略正在调整挂单，此时不允许检查挂单
        self._cannot_check_open_orders: bool = False

        # 入场触发挂单剩余数量
        self._ENTRY_ORDER_qty_left: int = 0
        # 市价挂单目标量和剩余量，均为正数表示绝对数量，用于记忆市价挂单交易数量作为比对，该功能不完全必要
        self._MARKET_ORDER_qty_left: int = 0
        self._MARKET_ORDER_qty_target: int = 0
        self._MARKET_ORDER_value = 0  # 市价成交，已完成价值，用于最后求平均值

        # 前一个最新ticker价格
        self.previous_price = 0

        # ============ 策略调仓功能 ============ # 修正仓位订单id，-1代表当前没有需要修正的挂单
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

        # ==================== 其他变量 ==================== #
        # noinspection PyTypeChecker
        self._my_logger: LogRecorder = None

        self._is_trading = False  # todo: 修改至基类

        # 是否在等待挂单
        self._is_waiting = False

        # 点击停止次数
        self.manually_stop_request_time: int = 0
        # 用户已经强制终止
        self.force_stopped: bool = False
        # 保存最后的参考信息
        self._save_ref_info_text: str = ''

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
        self._x_leverage = validated_params['leverage']
        self._x_trigger_start = validated_params['trigger_start']
        self._x_trigger_price = validated_params['pending_trigger_price']
        self._x_price_rel_step = validated_params['grid_rel_step']
        self._x_filling_step = validated_params['filling_step']
        self._x_lower_step = validated_params['lower_step']
        self._x_filling_fund = validated_params['filling_fund']

        symbol_exist = await self._get_trading_rule(validated_params['symbol_name'])

        if symbol_exist:
            self.current_symbol_price = await self._my_executor.get_current_price(validated_params['symbol_name'])

            # 判断杠杆数是否合理
            if self._x_leverage > self.symbol_max_leverage:
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
                if self._x_price_rel_step == '':
                    self._x_price_rel_step = 0.5
                if self._x_filling_step == '':
                    self._x_filling_step = 20
                if self._x_lower_step == '':
                    self._x_lower_step = 30

                # 设定数字精度，降低计算难度
                self._x_price_rel_step = round_step_size(self._x_price_rel_step, 0.0001)  # 百万分之一
                self._x_filling_step = round(self._x_filling_step, 2)
                self._x_lower_step = round(self._x_lower_step, 2)
                # 如果输入0，则使用最小精度
                self._x_price_rel_step = max(self._x_price_rel_step, round_step_size(self.symbol_price_min_step / entry_price, 0.0001))
                # 计算上下方网格数量
                up_grid_num = int(np.floor(np.log(1 + self._x_filling_step / 100) / np.log(1 + self._x_price_rel_step / 100)))  # 不计算base网格，算上顶部价格的网格，由于实际网格是用顶部网格代替最高价格，所以数量不变
                try:
                    low_grid_num = int(np.floor(np.log(1 - self._x_lower_step / 100) / np.log(1 - self._x_price_rel_step / 100)))
                except ValueError as Ve:
                    print(Ve)
                    print(f'lower_step = {self._x_lower_step}, price_step = {self._x_price_rel_step}, symbol = {validated_params["symbol_name"]}')
                    raise Ve
                # print('上方网格数量:{}\t下方网格数量:{}'.format(up_grid_num, low_grid_num))

                # 补仓次数需要大于1
                if self._x_grid_up_limit <= round_step_size(calc(entry_price, calc(1, calc(calc(self._x_filling_step, calc(self._x_price_rel_step, 2, '*'), '+'), 100, '/'), '+'),
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
                    min_fund_demand = calc(max_filling_price, calc(up_grid_num, self.symbol_quantity_min_step, '*'), '*')
                    # print('最低金额需求: {} USDT'.format(min_fund_demand))
                    # 最低资金加一美刀，保险
                    self._x_filling_fund = max(self._x_filling_fund, min_fund_demand + 1)

        else:
            validated_params['symbol_name'] += '未查询到该合约'
            param_valid = False

        validated_params['up_price'] = self._x_grid_up_limit
        validated_params['leverage'] = self._x_leverage
        validated_params['trigger_start'] = self._x_trigger_start
        validated_params['pending_trigger_price'] = self._x_trigger_price
        validated_params['grid_rel_step'] = self._x_price_rel_step
        validated_params['filling_step'] = self._x_filling_step
        validated_params['lower_step'] = self._x_lower_step
        validated_params['filling_fund'] = self._x_filling_fund
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
        present_grid_step = calc(self.all_grid_price[self.entry_index + 1], self.all_grid_price[self.entry_index], '-')
        present_grid_precision_multi = int(calc(present_grid_step, self.symbol_price_min_step, '/'))  # 当前网格间距精度倍数
        each_grid_profit_low = calc(calc(self.all_grid_price[self.entry_index + 1], self.all_grid_price[self.entry_index], '-'),
                                    calc(self.all_grid_quantity[self.entry_index + 1], self.symbol_quantity_min_step, '*'), '*')
        each_grid_profit_high = calc(calc(self.all_grid_price[self.present_step_up_index], self.all_grid_price[self.present_step_up_index - 1], '-'),
                                     calc(self.all_grid_quantity[self.present_step_up_index], self.symbol_quantity_min_step, '*'), '*')
        filling_margin_occupation = calc(calc(calc(self.entry_grid_qty, self.symbol_quantity_min_step, '*'), self.entry_grid_price, '*'), self.symbol_leverage, '/')
        # 经过计算，由于策略的等比性质，不同台阶位置的套利区间底部保证金占用和策略亏损(相同回撤比例)基本相同
        max_margin_cost = calc(calc(calc(sum(self.all_grid_quantity[self.present_bottom_index + 1:self.present_step_up_index + 1]),
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
        order_margin = calc(calc(calc(calc_sum([calc(each_pri, each_qty, '*') for each_pri, each_qty in zip(self.all_grid_price[self.entry_index - self.max_buy_order_num:self.entry_index], self.all_grid_quantity[self.entry_index - self.max_buy_order_num:self.entry_index])]),
                                      calc_sum([calc(each_pri, each_qty, '*') for each_pri, each_qty in zip(self.all_grid_price[self.entry_index + 1:self.entry_index + self.max_sell_order_num + 1], self.all_grid_quantity[self.entry_index + 1:self.entry_index + self.max_sell_order_num + 1])]), '+'), self.symbol_quantity_min_step, '*'), self.symbol_leverage, '/')
        # self.account_fund_demand = calc(max_margin_cost, abs(max_loss_ref), '+')
        self.account_fund_demand = calc(calc(max_margin_cost, abs(max_loss_ref), '+'), order_margin, '+')
        # 列出回调不同比例时的策略亏损
        list_callback_ratio = [0.05, 0.1, 0.2, 0.3, 0.5]
        list_critical_indices = [0] * len(list_callback_ratio)
        list_prices = [round_step_size(calc(self.entry_grid_price, 1 - each_ratio, '*'), self.symbol_price_min_step) for each_ratio in list_callback_ratio]
        list_callback_losses = [0.] * len(list_callback_ratio)
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

        info_texts += '\n网格总数量\t\t{:<8}\n'.format(str(self.grid_total_num))
        info_texts += '套利区间网格数量\t\t{} + {}\n'.format(str(self.filling_grid_step_num), str(self.lower_grid_step_num))
        info_texts += '当前网格间距\t\t{:<8}\t\t（ {} 倍精度 ）\n'.format(np.format_float_positional(present_grid_step, trim='-'), str(present_grid_precision_multi))
        info_texts += '全程补仓次数\t\t{:<8}\t\t次\n'.format(str(self.stairs_total_num))

        info_texts += '\n每格套利利润\t\t{} ~ {}\t{:<8}\n'.format(each_grid_profit_low, each_grid_profit_high, symbol_name[-4:])
        info_texts += '每阶做多收益\t\t{:<8}\t\t{:<8}\n'.format(str(self._each_stair_profit[0]), symbol_name[-4:])
        info_texts += '全程做多收益\t\t{:<8}\t\t{:<8}\n'.format(str(calc(self._each_stair_profit[0], self.stairs_total_num, '*')), symbol_name[-4:])

        info_texts += '\n补仓占用保证金\t\t{:<8}\t\t{:<8}\n'.format(str(round(filling_margin_occupation, 2)), symbol_name[-4:])
        info_texts += '挂单占用保证金\t\t{:<8}\t\t{:<8}\n'.format(str(round(order_margin, 2)), symbol_name[-4:])
        info_texts += '最大持仓保证金\t\t{:<8}\t\t{:<8}\n'.format(str(round(max_margin_cost, 2)), symbol_name[-4:])

        info_texts += '\n区间底部资金需求\t\t{:<8}\t\t{:<8}\t（账户建议资金）\n'.format(str(round(self.account_fund_demand, 2)), symbol_name[-4:])

        info_texts += '\n\n区间底部亏损\t\t{:<8}\t\t{:<8}\n'.format(str(round(max_loss_ref, 2)), symbol_name[-4:])

        info_texts += '\n补仓位价格回调\t\t策略亏损'
        for index, each_fund_callback in enumerate(list_callback_losses):
            info_texts += '\n{:>8} %\t\t{:>8}\t{}'.format(str(100 * list_callback_ratio[index]), str(round(each_fund_callback, 2)), symbol_name[-4:])

        info_texts += '\n\n*** {} ***'.format('=' * 32)

        # 最后保存参考信息，以供恢复策略时使用
        self._save_ref_info_text = info_texts
        return info_texts

    def confirm_params(self, input_params: dict) -> None:
        self.symbol_name = input_params['symbol_name']

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
        stg_params['leverage'] = self._x_leverage
        stg_params['trigger_start'] = self._x_trigger_start
        stg_params['pending_trigger_price'] = self._x_trigger_price
        stg_params['grid_rel_step'] = self._x_price_rel_step
        stg_params['filling_step'] = self._x_filling_step
        stg_params['lower_step'] = self._x_lower_step
        stg_params['filling_fund'] = self._x_filling_fund
        stg_params['valid'] = True

        return stg_params

    def derive_functional_variables(self, assign_entry_price: float = 0) -> None:
        """
        计算策略运行需要的相关变量
        策略实现方法：每达到补仓点位，相当于重新开启了一个等比做多网格
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

        self.grid_step_ratio = calc(self._x_price_rel_step, 100, '/')
        self.filling_step_ratio = calc(self._x_filling_step, 100, '/')
        self.lower_space_ratio = calc(self._x_lower_step, 100, '/')
        self.filling_fund = self._x_filling_fund

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
        # self.all_filling_quantities = [int(calc(self.filling_fund, calc(each_fill_price, self.symbol_quantity_min_step, '*'), '/'))
        #                                for each_fill_price in self.all_filling_prices]
        # print('prices of filling: {}'.format(self.all_filling_prices))
        self.stairs_total_num = len(self.all_filling_prices)
        # 再计算一阶网格价格
        up_grid_price = self.isometric_grid_calc(self.entry_grid_price, self.grid_step_ratio, self.all_filling_prices[0])
        down_grid_price = self.isometric_grid_calc(self.entry_grid_price, self.grid_step_ratio,
                                                   self.round_step_precision(self.entry_grid_price * (1 - self.lower_space_ratio), self.symbol_price_min_step))[:-1]
        up_grid_price[-1] = self.all_filling_prices[0]
        self.filling_grid_step_num = len(up_grid_price) - 1  # 减去base index
        self.lower_grid_step_num = len(down_grid_price)

        self.all_grid_price = tuple(down_grid_price + up_grid_price)
        # print('初始做多网格:\n{}'.format(self.all_grid_price))

        # 计算网格总数
        last_stair_grid_num = int(np.floor(np.log(self._x_grid_up_limit / self.all_filling_prices[-1]) / np.log(1 + self.grid_step_ratio)))  # 不包括base index，也不包括上界价格
        self.grid_total_num = last_stair_grid_num + self.stairs_total_num * self.filling_grid_step_num + self.lower_grid_step_num + 1
        self.max_index = self.grid_total_num - 1

        # 更新相关index
        self.present_stair_num = 0
        self.present_bottom_index = 0
        self.present_base_index = self.lower_grid_step_num
        self.present_step_up_index = self.present_base_index + self.filling_grid_step_num
        self.indices_of_filling = [self.present_step_up_index, ]
        # 更新其他动态变量
        self.present_bottom_price = self.all_grid_price[self.present_bottom_index]
        self.present_step_up_price = self.all_grid_price[self.present_step_up_index]

        self.entry_index = self.present_base_index
        self.critical_index = self.entry_index

        # 这里添加一项保险，filling fund使用实时的最小值去更新，如果确认参数后，价格上涨较快，到用户点击开始运行时最小资金需求又提高了，则会触发该代码
        real_time_min_fund = calc(self.all_filling_prices[-1], calc(self.filling_grid_step_num, self.symbol_quantity_min_step, '*'), '*')
        # todo: 此处不能_log_info,可以考虑写一个弹窗，全局提醒用
        self.filling_fund = max(self.filling_fund, real_time_min_fund)

        # 计算所有补仓数量
        self.all_filling_quantities = [int(calc(self.filling_fund, calc(each_fill_price, self.symbol_quantity_min_step, '*'), '/'))
                                       for each_fill_price in self.all_filling_prices]
        # print('quantities of filling: {}'.format(self.all_filling_quantities))

        # 再计算一阶网格数量，根据网格数量，计算一共有多少张，然后平均分配到网格
        up_grid_qty = self.unequal_grid_qty_calc(base_price=self.entry_grid_price, grid_num=self.filling_grid_step_num, fund=self.filling_fund)
        down_grid_qty = [up_grid_qty[0]] * (self.lower_grid_step_num + 1)  # 包含 base index
        self.all_grid_quantity = tuple(down_grid_qty + up_grid_qty)
        self.entry_grid_qty = sum(up_grid_qty)
        # print('len prices = {}, len qty = {}'.format(len(self.all_grid_price), len(self.all_grid_quantity)))

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

        self.all_lower_prices = [tuple(self.isometric_grid_calc(
            self.all_filling_prices[0],
            self.grid_step_ratio,
            self.round_step_precision(self.all_filling_prices[0] * (1 - self.lower_space_ratio), self.symbol_price_min_step))[:-1])]
        self.saved_stair_num = 0
        # print(self.all_lower_prices)
        # 台阶增长，计算至超出当前挂单最大范围
        add_num = int(self.symbol_order_price_div / self.filling_step_ratio) + 1
        # print('初始缓冲 {} 阶'.format(add_num))
        for i in range(add_num):
            self._add_buffer_vars()

    def derive_valid_position(self) -> None:
        """
        得到策略当前正确仓位，注意买卖单数量问题
        :return:
        """
        if self.critical_index == self.indices_of_filling[0]:
            # 过于偶然，放弃判断，等待下一次判断
            return

        if self.present_stair_num == 0:
            base_position = self.entry_grid_qty
        else:
            base_position = self.all_filling_quantities[self.present_stair_num - 1]

        if self.critical_index >= self.present_base_index:
            # 虚拟成交全为卖单
            div_position = -sum(self.all_grid_quantity[self.present_base_index + 1:self.critical_index + 1])
        else:
            # 虚拟成交全为买单
            div_position = sum(self.all_grid_quantity[self.critical_index + 1:self.present_base_index + 1])

        self._current_valid_position = base_position + div_position

        if self._current_valid_position < 0:
            raise ValueError('仓位小于0，不合逻辑!!!')

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
        self._my_preserver.open_file(self.symbol_name)  # todo: 改写并测试继承方法，使代码更美观

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
            asyncio.create_task(self.command_transmitter(trans_command=maker_order, token=Token.TO_POST_POC))

            self._ENTRY_ORDER_qty_left = self.entry_grid_qty
            self._trading_statistics['waiting_start_time'] = self.gen_timestamp()
            self._log_info('开始监听数据，等待触发条件')
            self._is_waiting = True

        else:
            asyncio.create_task(self._start_strategy())

    async def _start_strategy(self):
        self._is_waiting = False
        self._is_trading = True
        self._log_info('智能调仓网格 策略开始')

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
            await self._post_market_order(self.BUY, self.entry_grid_qty)

        # 2. 开始撒网
        asyncio.create_task(self._layout_net())

        # 3. 开启维护挂单任务
        self._fix_order_task = asyncio.create_task(self._order_fixer(interval_time=1200))

    # strategy basic methods
    def _grid_stair_step_up(self) -> None:
        """
        策略上升一个台阶，更新相关变量
        操作：

            更新所有网格数量(张)
            pop补仓index

            更新关键index 和price，作为判断标准
        :return:
        """
        if self.present_stair_num >= self.stairs_total_num:
            raise ValueError('已达到策略台阶上限，不可调用')
            return
        upward_grid_num = self.present_step_up_index - self.present_base_index

        self.all_grid_price = (0,) * (self.indices_of_filling[0] - len(self.all_lower_prices[self.present_stair_num])) + \
                              self.all_lower_prices[self.present_stair_num] + self.all_grid_price[self.indices_of_filling[0]:]

        self.all_grid_quantity = (0,) * (self.indices_of_filling[0] - len(self.all_lower_prices[self.present_stair_num])) + \
                                 (self.all_grid_quantity[self.indices_of_filling[0] + 1],) * (len(self.all_lower_prices[self.present_stair_num]) + 1) + \
                                 self.all_grid_quantity[self.indices_of_filling[0] + 1:]

        self.present_base_index += upward_grid_num
        self.present_bottom_index = self.present_base_index - len(self.all_lower_prices[self.present_stair_num])
        # 如果大于max index，数值多少无所谓了
        self.present_step_up_index = self.indices_of_filling[1] if self.present_stair_num < (self.stairs_total_num - 1) else self.present_base_index + self.filling_grid_step_num

        self.present_step_up_price = self.all_filling_prices[self.present_stair_num + 1] if self.present_stair_num < (self.stairs_total_num - 1) else \
            self.round_step_precision(calc(self.all_filling_prices[-1], 1 + self.filling_step_ratio, '*'), self.symbol_price_min_step)  # 超出上界的台阶价格
        self.present_bottom_price = self.all_grid_price[self.present_bottom_index]

        # 增添统计数据，并更新
        self._trading_statistics['realized_profit'] = calc(self._trading_statistics['realized_profit'], self._each_stair_profit[self.present_stair_num], '+')
        self._all_grid_sell_num[:self.present_base_index + 1] = [0] * (self.present_base_index + 1)

        self.present_stair_num += 1
        self.indices_of_filling.pop(0)
        self._add_buffer_vars()

    def _add_buffer_vars(self) -> None:
        """
        增加相关功能变量的长度，作为缓冲
        操作：
            添加所有网格价格，如果到达顶部，则使用上限价格作为最高网格价格
            添加所有网格数量
            添加所有下方价格
            添加补仓index
            添加买卖单累计列表长度
            添加每阶做多利润计算

        :return:
        """
        if self.saved_stair_num == self.stairs_total_num:
            return

        # add_grid_price = ()
        if self.saved_stair_num == self.stairs_total_num - 1:
            add_grid_price = self.isometric_grid_calc(self.all_filling_prices[self.saved_stair_num], self.grid_step_ratio, self.up_limit_price)[1:]  # 需要剔除base
            if len(add_grid_price) == 0:
                # 如果补仓价格再往上一个网格，就超出边界，则直接添加一个边界价格的网格
                add_grid_price.append(self.up_limit_price)
            else:
                add_grid_price[-1] = self.up_limit_price
            up_step_low_prices = ()
            filling_grid_num = self.filling_grid_step_num  # 该变量，使得最高台阶时，每格数量仍然合理

        elif self.saved_stair_num < self.stairs_total_num - 1:
            add_grid_price = self.isometric_grid_calc(self.all_filling_prices[self.saved_stair_num],
                                                      self.grid_step_ratio, self.all_filling_prices[self.saved_stair_num + 1])[1:]
            add_grid_price[-1] = self.all_filling_prices[self.saved_stair_num + 1]
            up_step_low_prices = tuple(self.isometric_grid_calc(
                self.all_filling_prices[self.saved_stair_num + 1],
                self.grid_step_ratio,
                self.round_step_precision(self.all_filling_prices[self.saved_stair_num + 1] * (1 - self.lower_space_ratio), self.symbol_price_min_step))[:-1])  # 不包括base

            filling_grid_num = len(add_grid_price)

        else:
            raise ValueError('增加缓冲价格有误，存储台阶数量计算错误')
            return

        # 切片以使得长度相等
        # add_grid_qty = tuple(self.unequal_grid_qty_calc(self.all_filling_prices[self.saved_stair_num], filling_grid_num, self.filling_fund))[:len(add_grid_price)]
        add_grid_qty = tuple(self.unequal_grid_qty_calc(
            base_price=self.all_filling_prices[self.saved_stair_num],
            grid_num=filling_grid_num,
            fund=calc(self.all_filling_prices[self.saved_stair_num], calc(self.all_filling_quantities[self.saved_stair_num], self.symbol_quantity_min_step, '*'), '*')
        ))[:len(add_grid_price)]

        self.all_grid_price += tuple(add_grid_price)
        self.all_grid_quantity += add_grid_qty
        if not up_step_low_prices == ():
            self.all_lower_prices.append(up_step_low_prices)
        self.indices_of_filling.append(self.indices_of_filling[-1] + filling_grid_num)  # 会超出max index
        self._all_grid_buy_num += [0] * len(add_grid_price)
        self._all_grid_sell_num += [0] * len(add_grid_price)
        self._each_stair_profit.append(self.unmatched_profit_calc(
            initial_index=self.indices_of_filling[-2],
            current_index=self.indices_of_filling[-1] if self.saved_stair_num < self.stairs_total_num - 1 else self.max_index,
            all_prices=self.all_grid_price,
            all_quantities=self.all_grid_quantity,
            init_pos_price=self.all_grid_price[self.indices_of_filling[-2]],
            init_pos_qty=sum(add_grid_qty),
            current_price=self.all_grid_price[self.indices_of_filling[-1]] if self.saved_stair_num < self.stairs_total_num - 1 else self.up_limit_price
        ))

        self.saved_stair_num += 1

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
                        'quantity': self.all_grid_quantity[self.parse_id(each['id'])[0] + 1],
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
        """
        根据当前价格，挂单数量限制，以及价格范围限制设置合理的最大挂单数量
        此时需要已知合约规则和当前价格
        警告：该方法未考虑非线性网格间距，只适用于线性网格       todo: 使用更好的方法
        :return:
        """
        if self.symbol_orders_limit_num != 100 and self.max_buy_order_num > int(self.symbol_orders_limit_num / 2):
            self._log_info('\n*** ================================= ***\n')
            self._log_info('请注意该合约挂单数量限制为 {} ! \n已自动减少缓冲网格数量，请留意交易情况!'.format(self.symbol_orders_limit_num))
            self._log_info('\n*** ================================= ***\n')
            self.max_buy_order_num = self.max_sell_order_num = int(self.symbol_orders_limit_num * 0.8 / 2)
            self.min_buy_order_num = self.min_sell_order_num = int(self.symbol_orders_limit_num * 0.4 / 2)
            self.buffer_buy_num = self.buffer_sell_num = max(3, int(self.min_buy_order_num / 2))

        price_div_demand_side_order_max_num = \
            int(self.current_symbol_price * self.symbol_order_price_div / calc(self.all_grid_price[self.critical_index + 1], self.all_grid_price[self.critical_index], '-'))
        if price_div_demand_side_order_max_num <= 0:
            raise ValueError('挂单数量不正确, {}'.format(self.symbol_name))
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
                    self._cancel_partial_order_check(each_info['id'])
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
                    self._cancel_partial_order_check(each_info['id'])
                    # if each_info['id'] in self.partially_filled_orders.keys():
                    #     traded_qty = int(self.grid_each_qty) - self.partially_filled_orders[each_info['id']]
                    #     self._accumulated_pos_deviation += traded_qty
                    #     self.partially_filled_orders.pop(each_info['id'])

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
        当网格到达补仓点位时，下方的等比网格数量和价格都需要修改
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

        # 判断修正仓位挂单，如果存在，则撤销
        if not self.adjusting_index == -1:
            if self.adjusting_index in repost_buy_indices:
                self.adjusting_index = -1
                # 使用加号，防止在请求期间存在其他的仓位偏移来源
                self._accumulated_pos_deviation += self._pre_save_acc_pos_dev
                self._log_info('##### 重新挂单，撤销仓位修正')

        # 撤销挂单，使用open buy变量即可
        for each_info in reversed(self.open_buy_orders):
            cancel_cmd = Token.ORDER_INFO.copy()
            cancel_cmd['symbol'] = self.symbol_name
            cancel_cmd['id'] = each_info['id']
            await self.command_transmitter(trans_command=cancel_cmd, token=Token.TO_CANCEL)
            self._cancel_partial_order_check(each_info['id'])
            # if each_info['id'] in self.partially_filled_orders.keys():
            #     traded_qty = int(self.grid_each_qty) - self.partially_filled_orders[each_info['id']]
            #     self._accumulated_pos_deviation -= traded_qty           # 部分成交买单，如此计算
            #     self.partially_filled_orders.pop(each_info['id'])
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
                if isinstance(self._fix_order_task, asyncio.Task):
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
            elif matched_num < 0:  # todo: delete if not happened
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
            self._update_column_text()
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
            showing_texts += '当前套利区间:\t\t{:<10} ~  {:<10}\n'.format(self.present_bottom_price, self.present_step_up_price)
            showing_texts += '\n已达成交易量:\t\t{:<20}\t{}\n\n'.format(str(self._trading_statistics['achieved_trade_volume']), self.symbol_name[-4:])
            showing_texts += '-' * 58
            showing_texts += '\n\n套利收益:\t\t{:<20}\t{}\n'.format(self._trading_statistics['matched_profit'], self.symbol_name[-4:])
            showing_texts += '做多收益:\t\t{:<20}\t{}\n'.format(self._trading_statistics['realized_profit'], self.symbol_name[-4:])

            # 如果价格下冲超出下边界，提示一下
            if self.current_symbol_price <= self.present_bottom_price:
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
        stg_param_dict = {
            'symbol_name': self.symbol_name,
            'up_price': self._x_grid_up_limit,
            'leverage': self._x_leverage,
            'trigger_start': self._x_trigger_start,  # 是否用挂单触发, True/False
            'pending_trigger_price': self._x_trigger_price,

            'grid_rel_step': self._x_price_rel_step,
            'filling_step': self._x_filling_step,
            'lower_step': self._x_lower_step,
            'filling_fund': self._x_filling_fund
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
            'is_trading': self._is_trading,
            'ref_info_texts': self._save_ref_info_text
        }
        self._my_preserver.preserve_strategy_info(strategy_info)

    async def restart(self, stg_info: dict, save_file_name: str) -> bool:
        """
        使用已保存的策略信息重新开启策略
        重启网格相当于开启了一个新的网格，并重新计算
        :return:
        """
        restart_success = True

        try:
            stg_params = stg_info['stg_params']
            stg_statistics = stg_info['stg_statistics']
            # 确保重启后，仍然能保存参考信息，用于下一次重启。因此策略可以无限制重启！
            self._save_ref_info_text = stg_info['ref_info_texts'] if 'ref_info_texts' in stg_info.keys() else ''

            self.symbol_name = stg_info['symbol_name']  # 在重启时也定义了实例的合约名称，此步多余
            # 获取新的记录参数实例
            self._my_logger = LogRecorder()
            self._my_logger.open_file(self.symbol_name)

            self._log_info('\n\\(✿◕‿◕)/ 智能调仓网格 策略重启!\n')

            # 策略初始参数
            self._x_grid_up_limit = stg_params['up_price']
            self._x_leverage = stg_params['leverage']
            self._x_trigger_start = stg_params['trigger_start']
            self._x_trigger_price = stg_params['pending_trigger_price']
            self._x_price_rel_step = stg_params['grid_rel_step']
            self._x_filling_step = stg_params['filling_step']
            self._x_lower_step = stg_params['lower_step']
            self._x_filling_fund = stg_params['filling_fund']

            # 由于一般而言策略重启间隔时间比较短，不开发恢复正在挂单等待的策略
            if stg_info['is_waiting']:
                # 重启挂单触发策略
                self._my_executor.start_single_contract_order_subscription(self.symbol_name)
                self._my_executor.start_single_contract_ticker_subscription(self.symbol_name)
                await self._get_trading_rule(self.symbol_name)

                trigger_price = float(self._x_trigger_price)
                self.derive_functional_variables(assign_entry_price=trigger_price)
                self.current_symbol_price = await self._my_executor.get_current_price(self.symbol_name)
                self._log_info('策略停止时合约价格\t{}\n当前合约价格\t\t{}'.format(str(stg_info['current_symbol_price']), str(self.current_symbol_price)))

                if self.current_symbol_price > trigger_price:
                    self._log_info('策略停止期间策略未触发，恢复触发等待')
                else:
                    self._log_info('策略停止期间策略已经触发，不恢复')
                    return False

                # # noinspection PyUnresolvedReferences
                # exist, order_price, order_size = self._my_executor.get_single_order(self.gen_id(self.ENTRY_ORDER_ID, self.BUY))
                # if exist and order_price == trigger_price:
                #     self._log_info('触发挂单状态正常，继续等待')
                # else:
                #     self._log_info('触发挂单状态异常，重新触发挂单')
                # 获得统计信息
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

                self._log_info('\n挂单策略恢复中。。。')
                # 设置合理挂单数量
                self._reasonable_order_num_estimate()

                self._my_preserver = Preserver()
                self._my_preserver.acquire_user_id(self._my_executor.return_user_id())
                self._my_preserver.use_existing_file(save_file_name)

                self._log_info('撤销并重新挂单')
                cancel_cmd = Token.ORDER_INFO.copy()
                cancel_cmd['symbol'] = self.symbol_name
                await self.command_transmitter(trans_command=cancel_cmd, token=Token.CANCEL_ALL)
                await asyncio.sleep(0.3)

                maker_order = Token.ORDER_INFO.copy()
                maker_order['symbol'] = self.symbol_name
                maker_order['id'] = self.gen_id(self.ENTRY_ORDER_ID, self.BUY)
                maker_order['price'] = self.entry_grid_price
                maker_order['side'] = self.BUY
                maker_order['quantity'] = self.entry_grid_qty
                self._log_info('~~~ 触发挂单下单\n')
                asyncio.create_task(self.command_transmitter(trans_command=maker_order, token=Token.TO_POST_POC))

                self._ENTRY_ORDER_qty_left = self.entry_grid_qty
                self._log_info('开始监听数据，等待触发条件')
                self._is_trading = False
                self._is_waiting = True

                self._reset_functional_vars()
                self._pre_update_text_task = asyncio.create_task(self._pre_update_detail_info(interval_time=1))

                return restart_success

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
                self._grid_stair_step_up()
            # 然后补充策略停止期间应该操作的台阶上移
            if self.current_symbol_price >= self._x_grid_up_limit:
                # 无意义的重启也需要添加进栏目，方便观察启动记录
                self._log_info('\n当前价已高于策略上限价格，无需重启策略')
                self._log_info('\n请手动平仓')
                return False
            else:
                while self._x_grid_up_limit > self.current_symbol_price >= self.present_step_up_price:
                    self._log_info('补充策略停止期间的台阶上移操作')
                    self._grid_stair_step_up()
            # 获得 c index
            self.critical_index = -1
            for each_index in range(1, len(self.all_grid_price)):
                if self.all_grid_price[each_index - 1] < self.current_symbol_price <= self.all_grid_price[each_index]:
                    self.critical_index = each_index
            # 有可能价格跌出最开始开单的下限
            if self.current_symbol_price <= self.all_grid_price[0]:
                self.critical_index = self.present_bottom_index
            if self.critical_index == -1:
                # 匹配价格失败
                self._log_info('未匹配到当前价格，c index失效')
                return False
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

            self._my_preserver = Preserver()
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
            # 虽然重启了，也让统计数据好看一些      todo: 同时更新参考信息
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
        current_account_qty = await self._my_executor.get_symbol_position(self.symbol_name)  # todo: 测试延时
        end_t = self._running_loop.time()
        elapsed_t_ms = int((end_t - start_t) * 1000)
        self._log_info('>>> 获取仓位耗时: {} ms'.format(elapsed_t_ms))

        self.derive_valid_position()
        self._log_info('\n### 执行仓位修正:')
        # self._log_info('### 账户初始仓位:\t\t{}\t张'.format(self._init_account_position))
        self._log_info('### 累计理论当前仓位:\t\t{}\t张'.format(self._account_position_theory))
        self._log_info('### 账户实际当前仓位:\t\t{}\t张\n'.format(current_account_qty))
        # 这两行不相等，说明正向理论计算当前仓位存在遗漏或者偏差

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
        # 此处最少约有100ms的延时

        # 1. 价格偏移较大情况
        if 1 <= self.critical_index <= self.max_index - 1:
            if abs(calc(self.current_symbol_price, self.all_grid_price[self.critical_index], '-')) > \
                    5 * calc(self.all_grid_price[self.critical_index + 1], self.all_grid_price[self.critical_index - 1], '-'):
                self._log_info('$$$ 价格偏离较大: 最新价 {}; 策略价 {}, 直接重新开启网格!'.format(self.current_symbol_price, self.all_grid_price[self.critical_index]))

                # 撤销所有挂单
                cancel_cmd = Token.ORDER_INFO.copy()
                cancel_cmd['symbol'] = self.symbol_name
                await self.command_transmitter(trans_command=cancel_cmd, token=Token.CANCEL_ALL)
                await asyncio.sleep(1)

                self.current_symbol_price = await self._my_executor.get_current_price(self.symbol_name)
                # 获得 c index
                for each_index in range(len(self.all_grid_price) - 1):
                    if self.all_grid_price[each_index] <= self.current_symbol_price < self.all_grid_price[each_index + 1]:
                        self.critical_index = each_index

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
                index, side = self.parse_id(each_stg_order_id)

                posting_order = Token.ORDER_INFO.copy()
                posting_order['symbol'] = self.symbol_name
                posting_order['id'] = each_stg_order_id
                posting_order['price'] = self.all_grid_price[index]
                posting_order['side'] = self.parse_id(each_stg_order_id)[1]
                posting_order['quantity'] = self.all_grid_quantity[index + 1] if side == self.BUY else self.all_grid_quantity[index]
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
        self._log_info('$$$ 挂单卫士已开启')
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
        并更新统计信息
        :param order_data_dict: 部分成交订单的订单信息
        :return: True, 订单已全部完成，交给处理。False, 订单未全部完成，继续等待，不操作
        """
        fully_fulfilled = False

        partial_order_id = order_data_dict['id']
        order_index, order_side = self.parse_id(partial_order_id)
        filled_qty = int(abs(order_data_dict['quantity']))
        filled_price: float = float(order_data_dict['price'])
        # 更新统计信息，此处信息最准确
        adding_volume = calc(calc(filled_qty, self.symbol_quantity_min_step, '*'), filled_price, '*')
        self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
        self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

        if order_side == self.BUY:
            self._account_position_theory += filled_qty
        elif order_side == self.SELL:
            self._account_position_theory -= filled_qty
        else:
            raise ValueError('parsed unknown side info!')

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

                fully_fulfilled = True
            else:
                self._log_info('error: left qty < 0, plz check code!')
                self._log_info('{} : {} = {} - {}'.format(partial_order_id, left_qty, ini_left_qty, filled_qty))
                # 在极高频的情况下，有可能会出现这种情况，比如adjusting order 维护不到位导致普通挂单数量不正常，此时也剔除该记录
                self.partially_filled_orders.pop(partial_order_id)

        else:
            left_qty = self.all_grid_quantity[order_index + 1] - filled_qty if order_side == self.BUY else self.all_grid_quantity[order_index] - filled_qty
            if left_qty < 0:
                self._log_info('error: got a normal order but traded quantity abnormal !')
                self._log_info('order: {}, filled qty: {}'.format(partial_order_id, filled_qty))
                return False
            self.partially_filled_orders[partial_order_id] = left_qty

            self._log_info('\n订单部分成交!!\t\t价格: {:<12}\tid: {:<10}'.format(order_data_dict['price'], partial_order_id))
            self._log_info('剩余 {} 张'.format(left_qty))

        return fully_fulfilled

    def _cancel_partial_order_check(self, order_id: str) -> None:
        """
        每次撤销挂单时，调用此函数，以修正部分成交挂单带来的仓位影响
        操作：判断该挂单是否记录为部分成交挂单，根据挂单方向和订单原数量修正仓位
        :return:
        """
        if order_id in self.partially_filled_orders.keys():
            order_index, order_side = self.parse_id(order_id)
            if order_side == self.BUY:
                traded_qty = self.all_grid_quantity[order_index + 1] - self.partially_filled_orders[order_id]
                self._accumulated_pos_deviation -= traded_qty
            elif order_side == self.SELL:
                traded_qty = self.all_grid_quantity[order_index] - self.partially_filled_orders[order_id]
                self._accumulated_pos_deviation += traded_qty
            self.partially_filled_orders.pop(order_id)

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

    async def _dealing_adjusting_order(self, order_data_dict: dict) -> bool:
        """
        处理修正仓位的特殊挂单，保存剩余仓位修正数量
        :param order_data_dict:
        :return:
        """
        order_fully_fulfilled = False

        filled_qty: int = abs(order_data_dict['quantity'])
        filled_price: float = float(order_data_dict['price'])
        # 更新统计信息，此处信息最准确
        adding_volume = calc(calc(filled_qty, self.symbol_quantity_min_step, '*'), filled_price, '*')
        self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
        self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

        self._adjusting_qty_left = self._adjusting_qty_left - filled_qty

        if self._adjusting_order_side == self.BUY:
            self._account_position_theory += filled_qty
        else:
            self._account_position_theory -= filled_qty

        if self._adjusting_qty_left == 0:
            # 结束仓位修正并维护网格
            self._log_info('\n### 修正挂单完全成交，仓位修正完成!!! ###\n')

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
        if not self._is_trading:  # 因为此时有可能人工手动停止
            return
        if self._doing_delay_task:
            self._log_info('\n>>> 上锁，不重复开启延时任务')
            return
        self._doing_delay_task = True

        # 使用 try 模块避免可能的问题
        try:
            if self._need_fix_order:
                self._log_info('\n>>> switch: 检查当前挂单')
                await self._check_open_orders()  # 消耗约 100 ms
                # todo: 可以考虑分开写，使用两个延时器
                return

            if self.adjusting_index == -1:
                # 此时没有特殊挂单
                if self._need_adjust_pos:
                    self._log_info('\n>>> 需要修正仓位')
                    await self._check_position()  # 消耗约 100 ms

                    if self._accumulated_pos_deviation == 0:
                        self._log_info('### 账户实际仓位正确，不需要修正\n')
                        self._need_adjust_pos = False
                    else:
                        if self._accumulated_pos_deviation > 0:
                            # 需要增加买 1 挂单数量以修正仓位

                            if len(self.open_buy_orders) == 0:
                                # 由于该策略一般不会出现缺少卖挂单的情况，因此不判断卖挂单
                                self._log_info('### 当前无买挂单用于修正仓位')
                                if self.current_symbol_price <= self.present_bottom_price:
                                    self._log_info('### 价格低于下区间，市价修正仓位')
                                    asyncio.create_task(self._post_market_order(self.BUY, self._accumulated_pos_deviation))
                                    self._accumulated_pos_deviation = 0
                                else:
                                    self._log_info('### 等待下一回合修正')

                            else:
                                self._log_info('### 修正买1单')  # todo: test print to delete, 该输出过于频繁
                                adjusting_id = self.open_buy_orders[-1]['id']  # 买 1 订单
                                self.adjusting_index = self.parse_id(adjusting_id)[0]
                                self._adjusting_order_side = self.BUY
                                if adjusting_id in self.partially_filled_orders.keys():
                                    self._log_info('### 罕见: 部分成交挂单作为仓位修正挂单')
                                    self._adjusting_qty_target = self._adjusting_qty_left = int(self.partially_filled_orders[adjusting_id]) + int(self._accumulated_pos_deviation)
                                    self._log_info('\n>>> 设定修正买单数量 {} 张, id: {}'.format(self._adjusting_qty_target, adjusting_id))
                                    # 此后该部分成交挂单就交给特殊仓位修正挂单功能处理
                                    self.partially_filled_orders.pop(adjusting_id)
                                else:
                                    self._adjusting_qty_target = self._adjusting_qty_left = self.all_grid_quantity[self.adjusting_index + 1] + int(self._accumulated_pos_deviation)
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
                                # 由于修正卖挂单的情况是仓位比预期大，因此等到高位再卖出，价格跌破区间时等待挂单
                                return

                            self._log_info('### 修正卖1单')  # todo: test print to delete, 该输出过于频繁
                            adjusting_id = self.open_sell_orders[0]['id']  # 卖 1 订单
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
                                self._adjusting_qty_target = self._adjusting_qty_left = self.all_grid_quantity[self.adjusting_index] + int(abs(self._accumulated_pos_deviation))
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
                self._log_info('\n>>> 检查调仓挂单')
                if abs(self.critical_index - self.adjusting_index) > min(10, self.min_buy_order_num, self.min_sell_order_num):  # todo: 测试市场，偏离10是否合理
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
                        repair_order['quantity'] = self.all_grid_quantity[self._pre_adjusting_index + 1]

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
                        repair_order['quantity'] = self.all_grid_quantity[self._pre_adjusting_index]

                        asyncio.create_task(self.command_transmitter(trans_command=repair_order, token=Token.TO_POST_POC))
                else:
                    # adjusting order status okay
                    self._log_info('\n>>> 调仓挂单状态正常，距离 {}'.format(abs(self.critical_index - self.adjusting_index)))
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
                # 高频关键功能：仓位修复策略
                order_fulfilled = await self._dealing_adjusting_order(recv_data_dict)
                if order_fulfilled:
                    # 更新订单成交数统计
                    if order_side == self.BUY:
                        self._all_grid_buy_num[order_index] += 1
                        self._trading_statistics['filled_buy_order_num'] += 1
                    else:
                        self._all_grid_sell_num[order_index] += 1
                        self._trading_statistics['filled_sell_order_num'] += 1
                    await self._maintainer_by_index(order_index)
                    await self._maintain_grid_order(order_index, order_side, recv_data_dict['id'], append_info, order_filled=True)

            else:
                # 其他普通订单，维护网格。判断成交数量是否为原始网格数量，如果是，则直接维护网格，如果不是，则先判断部分成交再维护网格
                order_qty: int = abs(recv_data_dict['quantity'])  # 这一部分相当于 dealing normal fulfilled order
                order_fully_fulfilled = False
                if order_side == self.BUY:
                    if order_qty == self.all_grid_quantity[order_index + 1]:
                        order_fully_fulfilled = True
                        self._account_position_theory += order_qty
                        # 更新订单成交数统计，交易量和手续费
                        self._all_grid_buy_num[order_index] += 1
                        self._trading_statistics['filled_buy_order_num'] += 1
                        add_volume = calc(calc(self.all_grid_quantity[order_index + 1], self.symbol_quantity_min_step, '*'), self.all_grid_price[order_index], '*')
                        self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], add_volume, '+')
                        self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(add_volume, self.symbol_maker_fee, '*'), '+')

                else:
                    if order_qty == self.all_grid_quantity[order_index]:
                        order_fully_fulfilled = True
                        self._account_position_theory -= order_qty

                        self._all_grid_sell_num[order_index] += 1
                        self._trading_statistics['filled_sell_order_num'] += 1
                        add_volume = calc(calc(self.all_grid_quantity[order_index], self.symbol_quantity_min_step, '*'), self.all_grid_price[order_index], '*')
                        self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], add_volume, '+')
                        self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(add_volume, self.symbol_maker_fee, '*'), '+')

                # 如果订单完全成交，直接维护网格。如果部分成交，额外判断逻辑
                if order_fully_fulfilled:
                    await self._maintainer_by_index(order_index)
                    await self._maintain_grid_order(order_index, order_side, recv_data_dict['id'], append_info, order_filled=True)
                else:
                    order_fulfilled = await self._dealing_partial_order(recv_data_dict)
                    if order_fulfilled:
                        # 更新订单成交数统计
                        if order_side == self.BUY:
                            self._all_grid_buy_num[order_index] += 1
                            self._trading_statistics['filled_buy_order_num'] += 1
                        else:
                            self._all_grid_sell_num[order_index] += 1
                            self._trading_statistics['filled_sell_order_num'] += 1
                        await self._maintainer_by_index(order_index)
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

        elif recv_data_dict['status'] == Token.ORDER_UPDATE:  # 对于gate服务器，该收信有可能是订单部分成交或订单修改成功
            # 目前在该策略逻辑中，只有一种更新订单的情况即修改买1 卖1 订单的数量，其他的id都是部分成交，已由其他通道处理
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
            raise ValueError(append_info)

        elif recv_data_dict['status'] == Token.POC_FAILED:
            self._log_info('\npoc挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            self._log_info('失败信息: {}'.format(append_info))
            if 'TOO_MANY_ORDERS' in append_info:
                self._log_info('\n挂单数量过多，需要检查挂单')
                self._need_fix_order = True
            raise ValueError(append_info)

        elif recv_data_dict['status'] == Token.POC_REJECTED:
            self._log_info('\npoc挂单失败，价格错位\t\t系统时间 {}'.format(str(pd.to_datetime(self.gen_timestamp(), unit='ms') + pd.Timedelta(hours=8))))
            this_order_index, side = self.parse_id(recv_data_dict['id'])
            if side == self.BUY:
                self._accumulated_pos_deviation += self.all_grid_quantity[this_order_index + 1]
            else:
                self._accumulated_pos_deviation -= self.all_grid_quantity[this_order_index]
            await self._maintainer_by_index(this_order_index)
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
                # 新检测方法，价格偏离c index两端网格距离之和的5倍，
                if 1 <= self.critical_index <= self.max_index - 1:
                    if abs(calc(self.current_symbol_price, self.all_grid_price[self.critical_index], '-')) > \
                            5 * calc(self.all_grid_price[self.critical_index + 1], self.all_grid_price[self.critical_index - 1], '-'):
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

            # === 高频仓位功能 === # 超过某个固定时间仍未收到ticker信息，则此时交易不剧烈，可以做额外操作
            if self._ticker_delay_timer:
                self._ticker_delay_timer.cancel()
            self._ticker_delay_timer = self._running_loop.call_later(self._ticker_delay_trigger_time, self._additional_action)

        # if self.developer_switch:
        #     self._reset_functional_vars()
        #     self.developer_switch = False
        #     self._log_info('\n!!! 重置相关任务变量 !!!\n')
        # raise ValueError('test error')

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
            # raise ValueError('分配资金不足，参数错误，网格数量小于1')
            if deliver_qty / grid_num > 0.95:
                # 说明可能是计算精度偏误
                print(f'分配资金接近最少资金，已自动修正: deliver_qty = {deliver_qty}, grid_num = {grid_num}')
                deliver_qty = grid_num
            else:
                raise ValueError(f'分配资金不足，参数错误，网格数量小于1. err_info: deliver_qty = {deliver_qty}, grid_num = {grid_num}')
        elif grid_num <= 0:
            raise ValueError('网格数量为0，无法计算')

        # 每个网格基础分配的数量
        base_quantity = deliver_qty // grid_num
        # 需要额外分配的数量
        extra_quantity = deliver_qty % grid_num
        # 分配数量到每个网格
        quantities = [base_quantity + 1 if i < extra_quantity else base_quantity for i in range(grid_num)]

        return quantities

    @staticmethod
    def unmatched_profit_calc_past(initial_index: int, current_index: int, all_prices: tuple[float | int], each_grid_qty: float,
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

        # 第一部分考虑无网格时的持仓盈亏
        part_1 = calc(calc(current_price, init_pos_price, '-'), init_pos_qty, '*')
        if current_index > initial_index + 1:
            price_slice = all_prices[initial_index + 1:current_index]
        elif current_index < initial_index - 1:
            price_slice = all_prices[current_index + 1:initial_index]
        else:
            price_slice = []

        # 第二部分计算网格持仓盈亏
        part_2 = calc(-abs(calc(calc_sum(price_slice), calc(len(price_slice), current_price, '*'), '-')), each_grid_qty, '*')

        return calc(part_1, part_2, '+')

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
        print('\n{}: {} smart grid analyzer 实例被删除，释放资源\n'.format(self.stg_num, self.symbol_name))
        pass
