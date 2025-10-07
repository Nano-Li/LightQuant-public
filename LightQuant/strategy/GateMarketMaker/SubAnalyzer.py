# -*- coding: utf-8 -*-
# @Time : 2024/2/13 19:16
# @Author : 
# @File : SubAnalyzer.py 
# @Software: PyCharm
import asyncio
from LightQuant.Executor import Executor
from LightQuant.Recorder import LogRecorder
from LightQuant.protocols.BinanceToken import BinanceToken as Token
from LightQuant.tools.calc import calc, calc_sum
from LightQuant.ui.TradeUI import SubAccountColumn


class SubAnalyzer:
    """
    子账号使用的子模块，存储主策略传入的部分网格参数
    仓位的检查与矫正，由子模块内部执行
    子模块上报操作结果，并得到总策略命令返回。
    """
    ACCOUNT_TOKEN = 'A'

    BUY: str = 'BUY'
    SELL: str = 'SELL'

    MARKET_ORDER_ID = 99999999  # 市价下单的id，taker成交
    ENTRY_ORDER_ID = 99999998  # 触发挂单id
    ADJUST_ORDER_ID = 99999996

    # noinspection PyTypeChecker
    def __init__(self):
        self.ACCOUNT_SERIES: str = ''
        self.STG_SERIES: str = ''
        self.STG_SERIES_len: int = 0
        # 编译而成
        self.stg_token: str = ''

        self._running_loop: asyncio.BaseEventLoop = None
        self.sub_executor: Executor = None
        self._bound_column: SubAccountColumn = None

        self._my_operator = None

        self._logger: LogRecorder = None

        # 网格 策略 参数
        self.symbol_name = None
        self.sub_grid_prices: tuple[float | int] = ()
        self.sub_grid_quantities: tuple[int | float] = ()

        # 最新价格
        self.current_price: float = 0

        # 最佳买卖价
        self.ask_price: float = 0.0     # 卖1价格
        self.bid_price: float = 0.0

        # 策略功能简单参数
        self.c_index = 0
        self.base_index = 0
        self.zero_index = 0  # 全局0仓位index
        self.up_index = 0
        # 自己网格的当前index
        self.near_index = 0

        self._valid_pos = 0
        self._theory_pos = 0

        # 市价单和触发挂单
        # 入场触发挂单剩余数量
        self._ENTRY_ORDER_qty_left: int = 0
        # 市价挂单目标量和剩余量，均为正数表示绝对数量，用于记忆市价挂单交易数量作为比对
        self._MARKET_ORDER_qty_left: int = 0
        # self._MARKET_ORDER_qty_target: int = 0
        # self._MARKET_ORDER_value = 0  # 市价成交，已完成价值，用于最后求平均值

        # 维护功能参数
        # 部分成交订单处理  {'id': int}   order_id, left_quantity   注意买卖挂单数量均用绝对值储存
        self.partially_filled_orders: dict[str, int] = {}

        self._accumulated_pos_deviation: int = 0
        self._pre_save_acc_pos_dev: int = 0

        # self.adjusting_index: int = -1
        self._exist_adjust_order: bool = False
        # 由此衍生的变量
        self._adjust_order_side: str = self.BUY
        self._adjust_qty_left: int = 0
        self._adjust_qty_target: int = 0
        # 处理修改订单数量失败时，需要使用的变量，存储修改特殊订单位置时，前一个特殊订单的id，归零时一起归零
        # self._pre_adjusting_index: int = -1

        # 定期检查仓位
        self._need_check_pos: bool = False
        # 充当开关作用，表示需要特殊挂单以修正仓位
        self._need_adjust_pos: bool = False

        # 协程锁，防止重复开启协程任务
        self._doing_delay_task: bool = False

        self._loop_adjust_pos_task: asyncio.Task = None

        # 策略统计简单参数
        self.margin_occupy = 0
        # 存储所有网格的买入卖出数量，用于计算套利收益，长度和网格数量，价格一致，同时更新
        # self._all_grid_buy_num: list[int] = []
        # self._all_grid_sell_num: list[int] = []

        self._trading_statistics: dict = {
            'waiting_start_time': None,
            'strategy_start_time': None,
            # 子账号统计了订单成交次数
            'filled_buy_order_num': 0,
            'filled_sell_order_num': 0,
            # 子账号统计了交易量
            'achieved_trade_volume': 0,
            # 已实现的网格套利利润
            'matched_profit': 0,
            # 已实现做多利润
            'realized_profit': 0,
            # 未实现盈亏
            'unrealized_profit': 0,
            # 子账号统计了手续费
            'total_trading_fees': 0,
            # 该策略最终净收益
            'final_profit': 0
        }

        # 交易规则简单参数
        self.symbol_price_min_step = None
        self.symbol_quantity_min_step = None
        self.symbol_max_leverage = None
        self.symbol_min_notional = None
        self.symbol_order_price_div = None
        self.symbol_orders_limit_num = None
        # 手续费
        self.symbol_maker_fee = 0
        self.symbol_taker_fee = 0

    def initialize(self, sub_executor: Executor, operator, column: SubAccountColumn, series: str, stg_series: str) -> None:
        self.sub_executor = sub_executor
        self._my_operator = operator
        self._bound_column = column
        self._logger = LogRecorder()
        self._logger.log_file_path = 'trading_account_logs'

        self.ACCOUNT_SERIES = series
        self.STG_SERIES = stg_series
        self.STG_SERIES_len = len(self.STG_SERIES)
        # U02S005A008
        # self.stg_token = self.STG_SERIES + self.ACCOUNT_TOKEN + str(self.ACCOUNT_SERIES).zfill(3)

        self.sub_executor.set_stg_series(1)  # 保持sub executor 和 主账号 executor 标签一致的临时方法，因为传送id时没有进行加工 也就是说，这会导致，只能使用一个账号开一个策略
        # 这句话的含义是告诉executor 这是第一个ui，实际的stgtoken是有主账号executor创建的，todo 这也导致，运行该策略时只能运行第一个ui
        # self.sub_executor.manually_set_stg_series(self.stg_token)
        # noinspection PyTypeChecker
        self.sub_executor.initialize(FakeTradeUI())
        self.stg_token = self.sub_executor.add_strategy(self)

        self._logger.open_file(self.ACCOUNT_SERIES)

        self._running_loop = asyncio.get_running_loop()
        asyncio.create_task(self.update_account_info(interval_time=1))
        self._log_account_info(f'账号 {self.ACCOUNT_SERIES} 初始化完成\nstg_token: {self.stg_token}')

    def set_symbol_info(self, symbol_name: str, info_dict: dict):
        """
        获得交易合约名称和交易规则信息
        :param info_dict:
        :param symbol_name:
        :return:
        """
        self.symbol_name = symbol_name

        self.symbol_price_min_step = info_dict['price_min_step']
        self.symbol_quantity_min_step = info_dict['qty_min_step']
        self.symbol_max_leverage = info_dict['max_leverage']
        self.symbol_min_notional = info_dict['min_notional']
        self.symbol_order_price_div = info_dict['price_div']
        self.symbol_orders_limit_num = info_dict['order_limit_num']

    def get_fee(self, maker_fee: float, taker_fee: float):
        self.symbol_maker_fee = maker_fee
        self.symbol_taker_fee = taker_fee

    def ticker_subscription(self):
        self.sub_executor.start_single_contract_ticker_subscription(self.symbol_name)

    def book_ticker_subscription(self):
        self.sub_executor.start_single_contract_book_ticker_subscription(self.symbol_name)

    def start_subscription(self):
        self.sub_executor.start_single_contract_order_subscription(self.symbol_name)

    def change_leverage(self, leverage: int):
        asyncio.create_task(self.sub_executor.change_symbol_leverage(self.symbol_name, leverage))

    def start(self):
        # pass
        self._loop_adjust_pos_task = asyncio.create_task(self.loop_adjust_pos())

    async def loop_adjust_pos(self, interval_time: int = 60):
        while True:
            self._need_check_pos = True
            self._log_account_info('>>> 例行仓位修正任务')
            await asyncio.sleep(interval_time)

    async def loop_check_open_orders(self, interval_time: int = 1200):
        pass

    async def update_account_statistics(self):
        self.derive_valid_position()
        pass

    async def update_account_info(self, interval_time: int = 3):

        while True:
            await self.update_account_statistics()

            showing_texts = f'账号 {self.ACCOUNT_SERIES} 信息:\nuser_id: {self.sub_executor.return_user_id()}'
            showing_texts += '\n\n*** {} ***\n'.format('=' * 51)
            showing_texts += f'c price: \t{self.current_price}\n'
            showing_texts += f'c index: \t{self.c_index}\n'
            showing_texts += f'base index: \t{self.base_index}\n'
            showing_texts += f'zero index: \t{self.zero_index}\n'
            showing_texts += f'up index: \t{self.up_index}\n'

            showing_texts += '-' * 36
            showing_texts += '\n\n修正仓位挂单:\t\t{}\n'.format(True if self._exist_adjust_order else False)
            showing_texts += '\n\n当前正确仓位:\t\t{:<10}张\n'.format(self._valid_pos)
            showing_texts += '累计计算仓位:\t\t{:<10}张\n'.format(self._theory_pos)
            showing_texts += '累计仓位偏移:\t\t{:<10}张\n\n'.format(self._accumulated_pos_deviation)
            showing_texts += '部分成交订单:\t\t{:<10}个挂单\n\n'.format(len(self.partially_filled_orders))
            showing_texts += '-' * 36

            showing_texts += '\n\n卖单挂单成交次数:\t{:<10}\n'.format(str(self._trading_statistics['filled_sell_order_num']))
            showing_texts += '买单挂单成交次数:\t{:<10}\n\n'.format(str(self._trading_statistics['filled_buy_order_num']))
            showing_texts += '-' * 36
            showing_texts += '\n\n账号交易量:\t\t{:<20}\t{}\n'.format(str(self._trading_statistics['achieved_trade_volume']), self.symbol_name[-4:])
            showing_texts += '\n账号手续费:\t\t{:<20}\t{}\n\n'.format(self._trading_statistics['total_trading_fees'], self.symbol_name[-4:])
            showing_texts += '\n\n*** {} ***\n\n'.format('=' * 51)

            self._bound_column.update_account_info(showing_info=showing_texts)

            await asyncio.sleep(interval_time)

    def update_account_balance(self, asset: str, margin: str):
        self._bound_column.renew_account_info(asset, margin)

    def _log_account_info(self, update_line: str, *args: str) -> None:
        self._bound_column.update_account_orders(update_line)
        self._logger.log_print(update_line)

        for each_content in args:
            self._bound_column.update_account_orders(each_content)
            self._logger.log_print(update_line)

    def get_stg_param_info(self, symbol_name: str, sub_grid_price: tuple, sub_grid_quantity: tuple):
        """
        子账号获得分派的交易策略信息，报告网格价格和数量，交易规则，
        :return:
        """
        self.symbol_name = symbol_name
        self.sub_grid_prices = sub_grid_price
        self.sub_grid_quantities = sub_grid_quantity

        # self._all_grid_buy_num = [0, ] * len(sub_grid_price)
        # self._all_grid_sell_num = self._all_grid_buy_num.copy()

    def append_stg_param_info(self, append_grid_price: tuple, append_grid_qty: tuple):
        """
        智能调仓，添加策略信息
        :return:
        """
        self.sub_grid_prices += append_grid_price
        self.sub_grid_quantities += append_grid_qty

        # add_num = [0, ] * len(append_grid_price)
        # self._all_grid_buy_num += add_num
        # self._all_grid_sell_num += add_num

    def stop_strategy(self):
        if isinstance(self._loop_adjust_pos_task, asyncio.Task):
            self._loop_adjust_pos_task.cancel()
        self.sub_executor.strategy_stopped(self.stg_token)
        self._logger.close_file()

    def derive_valid_position(self):

        base_position = sum(self.sub_grid_quantities[self.base_index + 1:self.zero_index + 1])

        if self.c_index >= self.base_index:
            # 虚拟成交全为卖单
            div_position = -sum(self.sub_grid_quantities[self.base_index + 1:self.c_index + 1])
        else:
            # 虚拟成交全为买单
            div_position = sum(self.sub_grid_quantities[self.c_index + 1:self.base_index + 1])

        self._valid_pos = base_position + div_position

        # if self._valid_pos == 0:
        #     raise ValueError('test debug')
        # if self._valid_pos < 0:
        #     raise ValueError('仓位小于0，不合逻辑!!!')

    def _cancel_partial_order_check(self, order_id: str) -> None:
        """
        每次撤销挂单时，调用此函数，以修正部分成交挂单带来的仓位影响
        操作：判断该挂单是否记录为部分成交挂单，根据挂单方向和订单原数量修正仓位
        :return:
        """
        if order_id in self.partially_filled_orders.keys():
            order_index, order_side = self.parse_id(order_id)
            if order_side == self.BUY:
                traded_qty = self.sub_grid_quantities[order_index] - self.partially_filled_orders[order_id]
                self._accumulated_pos_deviation -= traded_qty
            elif order_side == self.SELL:
                traded_qty = self.sub_grid_quantities[order_index] - self.partially_filled_orders[order_id]
                self._accumulated_pos_deviation += traded_qty
            self.partially_filled_orders.pop(order_id)

    async def post_market_order(self, market_side: str, market_qty: int) -> None:
        command = Token.ORDER_INFO.copy()
        command['side'] = market_side
        command['quantity'] = market_qty
        self._log_account_info('分派市价下单 {} 张'.format(market_qty))
        self._MARKET_ORDER_qty_left = market_qty
        await self.command_receiver(trans_command=command, token=Token.TO_POST_MARKET)

    async def post_entry_order(self, price: float, qty: int):

        maker_order = Token.ORDER_INFO.copy()
        maker_order['symbol'] = self.symbol_name
        maker_order['id'] = self.gen_id(self.ENTRY_ORDER_ID, self.BUY)
        maker_order['price'] = price
        maker_order['side'] = self.BUY
        maker_order['quantity'] = qty
        self._log_account_info('~~~ 子账号触发挂单下单\n')
        # asyncio.create_task(self.command_transmitter(trans_command=maker_order, token=Token.TO_POST_POC))
        self._ENTRY_ORDER_qty_left = abs(qty)
        await self.command_receiver(trans_command=maker_order, token=Token.TO_POST_POC)

    async def _check_position(self):
        start_t = self._running_loop.time()
        current_account_qty = await self.sub_executor.get_symbol_position(self.symbol_name)
        end_t = self._running_loop.time()
        elapsed_t_ms = int((end_t - start_t) * 1000)
        self._log_account_info('>>> 获取仓位耗时: {} ms'.format(elapsed_t_ms))

        self.derive_valid_position()
        self._log_account_info('\n### 检查仓位:')
        # self._log_account_info('### 账户初始仓位:\t\t{}\t张'.format(self._init_account_position))
        self._log_account_info('### 累计理论当前仓位:\t\t{}\t张'.format(self._theory_pos))
        self._log_account_info('### 账户实际当前仓位:\t\t{}\t张\n'.format(current_account_qty))
        # 这两行不相等，说明正向理论计算当前仓位存在遗漏或者偏差

        partial_order_pos_dev: int = 0
        if len(self.partially_filled_orders) > 0:
            self._log_account_info('### 计算部分成交挂单...')
            for each_id, each_qty in self.partially_filled_orders.items():
                if self.parse_id(each_id)[1] == self.BUY:
                    # 部分买单成交表示需要立即卖出，因此为负数
                    partial_order_pos_dev -= each_qty
                else:
                    partial_order_pos_dev += each_qty

        # self._log_account_info('### 除去已知偏差后:\t\t{}\t张'.format(str(self._theory_pos + self._accumulated_pos_deviation)))
        self._log_account_info('### 策略当前正确仓位:\t\t{}\t张'.format(self._valid_pos))
        self._log_account_info('### 当前矫正后仓位: \t\t{}\t张'.format(str(current_account_qty + self._accumulated_pos_deviation + partial_order_pos_dev)))
        # 后两行如果不相等，则表示反向计算累计仓位偏移不完备，存在未知的仓位偏移来源

        fix_qty = int(current_account_qty + self._accumulated_pos_deviation + partial_order_pos_dev - self._valid_pos)
        # fix_qty 大于 0 表示 修正后 账户多余仓位，小于0 表示 修正后 账户缺少仓位

        if fix_qty == 0:
            self._log_account_info('\n### 无额外仓位偏移')
        else:
            self._log_account_info('\n##### 存在未知来源的仓位偏移 #####')
            if fix_qty > 0:
                self._log_account_info('##### 账户多余仓位 {} 张 #####'.format(str(fix_qty)))
            else:
                self._log_account_info('##### 账户缺失仓位 {} 张 #####'.format(str(abs(fix_qty))))

            self._accumulated_pos_deviation -= fix_qty

    async def _deal_ENTRY_order(self, order_data_dict: dict) -> None:
        filled_size: int = abs(order_data_dict['quantity'])
        filled_price: float = float(order_data_dict['price'])
        self._ENTRY_ORDER_qty_left = self._ENTRY_ORDER_qty_left - filled_size

        self._log_account_info('~~~ 触发挂单成交 {} 张，剩余 {} 张'.format(str(filled_size), self._ENTRY_ORDER_qty_left))

        adding_volume = calc(calc(filled_size, self.symbol_quantity_min_step, '*'), filled_price, '*')
        self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
        self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')
        # 假设都是多单
        self._theory_pos += filled_size

    async def _deal_MARKET_order(self, order_data_dict: dict) -> None:
        filled_size: int = abs(order_data_dict['quantity'])
        filled_price: float = float(order_data_dict['price'])
        self._MARKET_ORDER_qty_left = self._MARKET_ORDER_qty_left - filled_size

        self._log_account_info('~~~ 市价挂单成交 {} 张，剩余 {} 张'.format(str(filled_size), self._MARKET_ORDER_qty_left))

        adding_volume = calc(calc(filled_size, self.symbol_quantity_min_step, '*'), filled_price, '*')
        self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
        self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_taker_fee, '*'), '+')
        # 假设都是多单
        self._theory_pos += filled_size

    async def _deal_partial_order(self, order_data_dict: dict) -> bool:
        """
        用于处理部分成交的订单
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
            self._theory_pos += filled_qty
        elif order_side == self.SELL:
            self._theory_pos -= filled_qty
        else:
            raise ValueError('parsed unknown side info!')

        if partial_order_id in self.partially_filled_orders:

            ini_left_qty = self.partially_filled_orders[partial_order_id]

            left_qty = ini_left_qty - filled_qty
            if left_qty > 0:
                self.partially_filled_orders[partial_order_id] = left_qty
                self._log_account_info('订单再次部分成交!\t\t价格: {:<12}\tid: {:<10}'.format(order_data_dict['price'], partial_order_id))
                self._log_account_info('剩余 {} 张'.format(left_qty))
            elif left_qty == 0:
                # 订单已完成
                self.partially_filled_orders.pop(partial_order_id)

                fully_fulfilled = True
            else:
                self._log_account_info('error: left qty < 0, plz check code!')
                self._log_account_info('{} : {} = {} - {}'.format(partial_order_id, left_qty, ini_left_qty, filled_qty))
                # 在极高频的情况下，有可能会出现这种情况，比如adjusting order 维护不到位导致普通挂单数量不正常，此时也剔除该记录
                self.partially_filled_orders.pop(partial_order_id)

        else:
            # left_qty = self.sub_grid_quantities[order_index + 1] - filled_qty if order_side == self.BUY else self.sub_grid_quantities[order_index] - filled_qty
            # 临时方法，实时上在多账号模型中不能出现不均匀的网格数量
            left_qty = self.sub_grid_quantities[order_index] - filled_qty
            if left_qty < 0:
                self._log_account_info('error: got a normal order but traded quantity abnormal !')
                self._log_account_info('order: {}, filled qty: {}, order qty: {}'.format(partial_order_id, filled_qty, self.sub_grid_quantities[order_index]))
                return False
            self.partially_filled_orders[partial_order_id] = left_qty
            self._log_account_info('\n订单部分成交!!\t\t价格: {:<12}\tid: {:<10}'.format(order_data_dict['price'], partial_order_id))
            self._log_account_info('剩余 {} 张'.format(left_qty))

        return fully_fulfilled
    # 
    # async def _deal_adjusting_order(self, order_data_dict: dict) -> bool:
    #     """
    #     处理修正仓位的特殊挂单，保存剩余仓位修正数量
    #     :param order_data_dict:
    #     :return:
    #     """
    #     order_fully_fulfilled = False
    # 
    #     filled_qty: int = abs(order_data_dict['quantity'])
    #     filled_price: float = float(order_data_dict['price'])
    #     # 更新统计信息，此处信息最准确
    #     adding_volume = calc(calc(filled_qty, self.symbol_quantity_min_step, '*'), filled_price, '*')
    #     self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
    #     self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')
    # 
    #     self._adjusting_qty_left = self._adjusting_qty_left - filled_qty
    # 
    #     if self._adjusting_order_side == self.BUY:
    #         self._theory_pos += filled_qty
    #     else:
    #         self._theory_pos -= filled_qty
    # 
    #     if self._adjusting_qty_left == 0:
    #         # 结束仓位修正并维护网格
    #         self._log_account_info('\n### 修正挂单完全成交，仓位修正完成!!! ###\n')
    # 
    #         self.adjusting_index = self._pre_adjusting_index = -1
    #         self._adjusting_qty_target = self._adjusting_qty_left = 0
    #         self._need_adjust_pos = False
    #         order_fully_fulfilled = True
    # 
    #     elif self._adjusting_qty_left < 0:
    #         self._log_account_info('\n ##### 修正挂单统计有误! 剩余数量小于零')
    #         self._log_account_info('\n ##### this_qty: {}\ttarget: {}\tleft: {}'.format(filled_qty, self._adjusting_qty_target, self._adjusting_qty_left))
    # 
    #         # todo 暂且也如此，摆烂
    #         self.adjusting_index = self._pre_adjusting_index = -1
    #         self._adjusting_qty_target = self._adjusting_qty_left = 0
    #         self._need_adjust_pos = False
    #         order_fully_fulfilled = True
    # 
    #     else:
    #         pass
    #         # 仓位修正未完成
    #         self._log_account_info('### 修正挂单部分成交')
    #         self._log_account_info('### target: {}, left: {}'.format(self._adjusting_qty_target, self._adjusting_qty_left))
    #         self._log_account_info('### 修正进度:\t已完成/总数\t{}/{}'.format(str(self._adjusting_qty_target - self._adjusting_qty_left), self._adjusting_qty_target))
    # 
    #     return order_fully_fulfilled

    async def _deal_ADJUST_order(self, order_data_dict: dict) -> None:
        order_fully_fulfilled = False

        filled_qty: int = abs(order_data_dict['quantity'])
        filled_price: float = float(order_data_dict['price'])
        # 更新统计信息，此处信息最准确
        adding_volume = calc(calc(filled_qty, self.symbol_quantity_min_step, '*'), filled_price, '*')
        self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
        self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

        self._adjust_qty_left = self._adjust_qty_left - filled_qty

        if self._adjust_order_side == self.BUY:
            self._theory_pos += filled_qty
        else:
            self._theory_pos -= filled_qty

        if self._adjust_qty_left == 0:
            # 结束仓位修正并维护网格
            self._log_account_info('\n### 修正挂单完全成交，仓位修正完成!!! ###\n')
            
            self._adjust_qty_target = 0
            order_fully_fulfilled = True

        elif self._adjust_qty_left < 0:
            self._log_account_info('\n ##### 修正挂单统计有误! 剩余数量小于零')
            self._log_account_info('\n ##### this_qty: {}\ttarget: {}\tleft: {}'.format(filled_qty, self._adjust_qty_target, self._adjust_qty_left))

            # todo 暂且也如此，摆烂
            self._adjust_qty_target = self._adjust_qty_left = 0
            order_fully_fulfilled = True

        else:
            # 仓位修正未完成
            self._log_account_info('### 修正挂单部分成交')
            self._log_account_info('### target: {}, left: {}'.format(self._adjust_qty_target, self._adjust_qty_left))
            self._log_account_info('### 修正进度:\t已完成/总数\t{}/{}'.format(str(self._adjust_qty_target - self._adjust_qty_left), self._adjust_qty_target))

        if order_fully_fulfilled:
            self._exist_adjust_order = False

    async def report_receiver(self, recv_data_dict: dict, append_info: str = None) -> None:
        """
        得到每个executor的返回信息，理论上executor直接绑定的analyzer,新策略绑定的是这个sub analyzer
        并使用了一样的函数名称来截断订单信息返回，由于是使用重复的函数名称，参数名称也需要一样

        拦截信息并分析，做出相关统计
        :param append_info:
        :param recv_data_dict:
        :return:
        """

        if recv_data_dict['status'] == Token.ORDER_FILLED:
            # 收到策略订单id，根据订单类别，分别处理
            order_index, order_side = self.parse_id(recv_data_dict['id'])

            if order_index == self.ENTRY_ORDER_ID:
                await self._deal_ENTRY_order(recv_data_dict)
                await self._my_operator.report_receiver(recv_data_dict, append_info)

            elif order_index == self.MARKET_ORDER_ID:
                await self._deal_MARKET_order(recv_data_dict)
                await self._my_operator.report_receiver(recv_data_dict, append_info)

            # elif order_index == self.adjusting_index:
            #     # 高频关键功能：仓位修复策略
            #     order_fulfilled = await self._deal_adjusting_order(recv_data_dict)
            #     if order_fulfilled:
            #         # 更新订单成交数统计
            #         if order_side == self.BUY:
            #             # self._all_grid_buy_num[order_index] += 1
            #             self._trading_statistics['filled_buy_order_num'] += 1
            #         else:
            #             # self._all_grid_sell_num[order_index] += 1
            #             self._trading_statistics['filled_sell_order_num'] += 1
            #         await self._my_operator.report_receiver(recv_data_dict, append_info)

            elif order_index == self.ADJUST_ORDER_ID:
                await self._deal_ADJUST_order(recv_data_dict)

            else:
                # 其他普通订单，维护网格。判断成交数量是否为原始网格数量，如果是，则直接维护网格，如果不是，则先判断部分成交再维护网格
                order_qty: int = abs(recv_data_dict['quantity'])  # 这一部分相当于 dealing normal fulfilled order
                order_fully_fulfilled = False
                if order_side == self.BUY:
                    if order_qty == self.sub_grid_quantities[order_index]:
                        order_fully_fulfilled = True
                        self._theory_pos += order_qty
                        # 更新订单成交数统计，交易量和手续费
                        # self._all_grid_buy_num[order_index] += 1
                        self._trading_statistics['filled_buy_order_num'] += 1
                        add_volume = calc(calc(self.sub_grid_quantities[order_index], self.symbol_quantity_min_step, '*'), self.sub_grid_prices[order_index], '*')
                        self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], add_volume, '+')
                        self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(add_volume, self.symbol_maker_fee, '*'), '+')

                else:
                    if order_qty == self.sub_grid_quantities[order_index]:
                        order_fully_fulfilled = True
                        self._theory_pos -= order_qty

                        # self._all_grid_sell_num[order_index] += 1
                        self._trading_statistics['filled_sell_order_num'] += 1
                        add_volume = calc(calc(self.sub_grid_quantities[order_index], self.symbol_quantity_min_step, '*'), self.sub_grid_prices[order_index], '*')
                        self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], add_volume, '+')
                        self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(add_volume, self.symbol_maker_fee, '*'), '+')

                # 如果订单完全成交，直接维护网格。如果部分成交，额外判断逻辑
                if order_fully_fulfilled:
                    self._log_account_info('\n订单成交\tid: {}'.format(recv_data_dict['id']))
                    self._log_account_info(append_info.split('\n')[1])
                    await self._my_operator.report_receiver(recv_data_dict, append_info)
                else:
                    order_fulfilled = await self._deal_partial_order(recv_data_dict)
                    if order_fulfilled:
                        # 更新订单成交数统计
                        if order_side == self.BUY:
                            # self._all_grid_buy_num[order_index] += 1
                            self._trading_statistics['filled_buy_order_num'] += 1
                        else:
                            # self._all_grid_sell_num[order_index] += 1
                            self._trading_statistics['filled_sell_order_num'] += 1
                        self._log_account_info('\n订单成交\tid: {}'.format(recv_data_dict['id']))
                        self._log_account_info(append_info.split('\n')[1])
                        await self._my_operator.report_receiver(recv_data_dict, append_info)

        elif recv_data_dict['status'] == Token.POST_SUCCESS:
            await self._my_operator.report_receiver(recv_data_dict, append_info)

        elif recv_data_dict['status'] == Token.POC_SUCCESS:
            self._log_account_info('挂单成功\tid: {}'.format(recv_data_dict['id']))
            await self._my_operator.report_receiver(recv_data_dict, append_info)

        elif recv_data_dict['status'] == Token.CANCEL_SUCCESS:
            await self._my_operator.report_receiver(recv_data_dict, append_info)

        elif recv_data_dict['status'] == Token.CANCEL_POC_SUCCESS:
            order_index, order_side = self.parse_id(recv_data_dict['id'])
            if order_index == self.ADJUST_ORDER_ID:
                self._log_account_info('>>> 成功取消仓位修正挂单')
            else:
                await self._my_operator.report_receiver(recv_data_dict, append_info)

        elif recv_data_dict['status'] == Token.PARTIALLY_FILLED:
            await self._my_operator.report_receiver(recv_data_dict, append_info)

        elif recv_data_dict['status'] == Token.ORDER_UPDATE:  # 对于gate服务器，该收信有可能是订单部分成交或订单修改成功
            # 目前在该策略逻辑中，只有一种更新订单的情况即修改买1 卖1 订单的数量，其他的id都是部分成交，已由其他通道处理
            self._log_account_info('undefined condition!')
            pass
            # if self.adjusting_index == -1:
            #     pass
            # else:
            #     order_index, order_side = self.parse_id(recv_data_dict['id'])
            #     if order_index == self.adjusting_index:
            #         self._log_account_info(('调仓订单修改成功~\t\t价格: {:<12}\tid: {:<10}'.format(str(float(recv_data_dict['price'])), recv_data_dict['id'])))
            #     else:
            #         pass

        elif recv_data_dict['status'] == Token.UNIDENTIFIED:
            pass
        elif recv_data_dict['status'] == Token.FAILED:
            pass
        elif recv_data_dict['status'] == Token.POST_FAILED:
            await self._my_operator.report_receiver(recv_data_dict, append_info)

        elif recv_data_dict['status'] == Token.POC_FAILED:
            await self._my_operator.report_receiver(recv_data_dict, append_info)

        elif recv_data_dict['status'] == Token.POC_REJECTED:
            # self._log_account_info('\npoc挂单失败，价格错位\t\t系统时间 {}'.format(str(pd.to_datetime(self.gen_timestamp(), unit='ms') + pd.Timedelta(hours=8))))
            this_order_index, side = self.parse_id(recv_data_dict['id'])
            if this_order_index == self.ADJUST_ORDER_ID:
                self._exist_adjust_order = False
                self._need_adjust_pos = True
                self._log_account_info('### 添加修正仓位挂单被驳回, id: {}'.format(recv_data_dict['id']))
                self._accumulated_pos_deviation += self._pre_save_acc_pos_dev
            else:
                if side == self.BUY:
                    self._accumulated_pos_deviation += self.sub_grid_quantities[this_order_index]
                    self._log_account_info('{}买挂单被驳回!\t\t价格: {:<12}\tid: {:<10}'.format
                                           (chr(12288), str(self.sub_grid_prices[this_order_index]), recv_data_dict['id']))
                else:
                    self._accumulated_pos_deviation -= self.sub_grid_quantities[this_order_index]
                    self._log_account_info('{}卖挂单被驳回!\t\t价格: {:<12}\tid: {:<10}'.format
                                           (chr(12288), str(self.sub_grid_prices[this_order_index]), recv_data_dict['id']))
                await self._my_operator.report_receiver(recv_data_dict, append_info)

        elif recv_data_dict['status'] == Token.CANCEL_FAILED:
            await self._my_operator.report_receiver(recv_data_dict, append_info)

        elif recv_data_dict['status'] == Token.AMEND_POC_FAILED:
            self._log_account_info('undefined condition')

        else:
            raise ValueError('command undefined token transferred!')

        # ======================= useless code
        # order_id, order_side = self.parse_id(recv_data_dict['id'])
        # # todo: 市价挂单与触发挂单并不知道是来自于哪个账号，只有在总策略总统计数量时会记录
        # if order_id == self.ENTRY_ORDER_ID:
        #     await self._my_operator.report_receiver(recv_data_dict, append_info)
        # elif order_id == self.MARKET_ORDER_ID:
        #     await self._my_operator.report_receiver(recv_data_dict, append_info)
        # else:
        #     await self._my_operator.report_receiver(recv_data_dict, append_info)

    async def command_receiver(self, trans_command: dict = None, token: str = None) -> None:
        command_dict = Token.ORDER_INFO.copy()
        command_dict['symbol'] = self.symbol_name

        if token == Token.TO_POST_LIMIT:
            command_dict['id'] = trans_command['id']
            command_dict['price'] = trans_command['price']
            command_dict['side'] = trans_command['side']
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self.sub_executor.command_receiver(command_dict))
        elif token == Token.TO_POST_POC:
            command_dict['id'] = trans_command['id']
            command_dict['price'] = trans_command['price']
            command_dict['side'] = trans_command['side']
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            # if self.parse_id(command_dict['id'])[0] == self.ADJUST_ORDER_ID:
            #     self._log_account_info('收到发送盘口订单任务')
            #     self._log_account_info(str(command_dict))
            asyncio.create_task(self.sub_executor.command_receiver(command_dict))
        elif token == Token.TO_CANCEL:
            self._cancel_partial_order_check(trans_command['id'])
            command_dict['id'] = trans_command['id']
            command_dict['status'] = token
            asyncio.create_task(self.sub_executor.command_receiver(command_dict))
        elif token == Token.TO_POST_BATCH:
            asyncio.create_task(self.sub_executor.command_receiver(trans_command))
        elif token == Token.TO_POST_BATCH_POC:
            asyncio.create_task(self.sub_executor.command_receiver(trans_command))
        elif token == Token.TO_POST_MARKET:
            command_dict['side'] = trans_command['side']
            command_dict['id'] = self.gen_id(self.MARKET_ORDER_ID, trans_command['side'])
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self.sub_executor.command_receiver(command_dict))
        elif token == Token.AMEND_POC_PRICE:
            command_dict['id'] = trans_command['id']
            command_dict['price'] = trans_command['price']
            command_dict['status'] = token
            asyncio.create_task(self.sub_executor.command_receiver(command_dict))
        elif token == Token.AMEND_POC_QTY:
            command_dict['id'] = trans_command['id']
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self.sub_executor.command_receiver(command_dict))
        elif token == Token.CANCEL_ALL:
            command_dict['status'] = token
            asyncio.create_task(self.sub_executor.command_receiver(command_dict))
        elif token == Token.CLOSE_POSITION:
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self.sub_executor.command_receiver(command_dict))
        elif token == Token.TEMP_TOKEN:
            command_dict['status'] = token
            asyncio.create_task(self.sub_executor.command_receiver(command_dict))
        elif token is None:
            raise ValueError('未定义命令类型，不发送')
        else:
            raise ValueError('错误定义命令类型，不发送')

    async def ticker_receiver(self, recv_ticker_data: dict) -> None:
        # 同样使用了同名称拦截
        await self._my_operator.ticker_receiver(recv_ticker_data)

    async def book_ticker_receiver(self, recv_book_data: dict) -> None:
        await self._my_operator.book_ticker_receiver(recv_book_data)

    async def get_best_price(self, ask: float, bid: float) -> None:
        # 最高速的请求
        self.ask_price, self.bid_price = ask, bid

        if self._accumulated_pos_deviation != 0:
            self._need_adjust_pos = True

        if self._need_adjust_pos:
            await self._adjust_pos_task()
            self._need_adjust_pos = False

    async def _adjust_pos_task(self) -> None:
        """
        极快速的响应仓位偏移，不会发送请求检查仓位，直接根据统计信息修正仓位
        一般可以快速修正订单驳回
        在延迟任务中调用此方法，可以修正未知仓位偏移
        :return:
        """
        # if self._need_adjust_pos:
        #
        # else:
        #     pass
        if self._exist_adjust_order:
            return
        else:
            self._log_account_info('\n>>> 执行仓位修正')
            if self._accumulated_pos_deviation == 0:
                self._log_account_info('>>> 统计仓位偏移为0，请检查交易情况!')
                self._need_adjust_pos = False
                return

            elif self._accumulated_pos_deviation > 0:
                # 添加盘口买挂单
                self._log_account_info('### 发送盘口买挂单')
                self._adjust_qty_target = self._adjust_qty_left = int(abs(self._accumulated_pos_deviation))
                self._adjust_order_side = self.BUY
                self._exist_adjust_order = True

                adjust_order = Token.ORDER_INFO.copy()
                adjust_order['symbol'] = self.symbol_name
                adjust_order['id'] = self.gen_id(self.ADJUST_ORDER_ID, self.BUY)
                adjust_order['price'] = self.bid_price
                adjust_order['side'] = self._adjust_order_side
                adjust_order['quantity'] = self._adjust_qty_target
                
                self._pre_save_acc_pos_dev = self._accumulated_pos_deviation
                self._accumulated_pos_deviation = 0

                await self.command_receiver(trans_command=adjust_order, token=Token.TO_POST_POC)

            else:
                # 添加盘口卖单
                self._log_account_info('### 发送盘口卖挂单')
                self._adjust_qty_target = self._adjust_qty_left = int(abs(self._accumulated_pos_deviation))
                self._adjust_order_side = self.SELL
                self._exist_adjust_order = True

                adjust_order = Token.ORDER_INFO.copy()
                adjust_order['symbol'] = self.symbol_name
                adjust_order['id'] = self.gen_id(self.ADJUST_ORDER_ID, self.SELL)
                adjust_order['price'] = self.ask_price
                adjust_order['side'] = self._adjust_order_side
                adjust_order['quantity'] = self._adjust_qty_target

                self._pre_save_acc_pos_dev = self._accumulated_pos_deviation
                self._accumulated_pos_deviation = 0

                await self.command_receiver(trans_command=adjust_order, token=Token.TO_POST_POC)

    async def get_ticker(self, c_index: int, b_index: int, z_index: int, u_index: int, c_price: float) -> None:
        self.c_index = c_index
        self.base_index = b_index
        self.zero_index = z_index
        self.up_index = u_index
        self.current_price = c_price
        # 如果订单成交迅速，ticker收信为 1s，判断也比较频繁
        # if self._accumulated_pos_deviation != 0:
        #     self._need_adjust_pos = True

        # if self.developer_switch:
        #     self._reset_functional_vars()
        #     self.developer_switch = False
        #     self._log_account_info('\n!!! 重置相关任务变量 !!!\n')
        # raise ValueError('test error')

    async def get_tick(self) -> None:
        """
        自上而下收到延迟tick信息
        :return:
        """
        asyncio.create_task(self._delay_task())

    async def _delay_task(self) -> None:
        self._log_account_info('>>> ')

        if self._doing_delay_task:
            self._log_account_info('\n>>> 上锁，不重复开启延时任务')
            return
        self._doing_delay_task = True

        # 使用 try 模块避免可能的问题
        try:
            # if self._need_fix_order:
            #     self._log_account_info('\n>>> switch: 检查当前挂单')
            #     await self._check_open_orders()  # 消耗约 100 ms
            #     # todo: 可以考虑分开写，使用两个延时器
            #     return
            pass

            if self._exist_adjust_order:
                self._log_account_info('\n>>> 检查调仓挂单')
                # todo: post
                start_t = self._running_loop.time()
                exist, order_price, order_size = self.sub_executor.get_single_order(self.gen_id(self.ADJUST_ORDER_ID, self._adjust_order_side))
                # exist, order_price, order_size = await self._running_loop.run_in_executor(
                #     self._executor_pool,
                #     self.sub_executor.get_single_order,
                #     self.gen_id(self.ADJUST_ORDER_ID, self._adjust_order_side)
                # )
                end_t = self._running_loop.time()
                elapsed_t_ms = int((end_t - start_t) * 1000)
                self._log_account_info('>>> 检查订单耗时: {} ms'.format(elapsed_t_ms))

                if exist:
                    if abs(calc(order_price, self.current_price, '-')) <= 120:
                        self._log_account_info(f'>>> 调仓挂单正常\t价格: {order_price}\t\t数量: {order_size}')
                    else:
                        self._log_account_info(f'>>> 调仓挂单过远，取消，请注意套利收益')

                        if self._adjust_order_side == self.BUY:
                            self._accumulated_pos_deviation += self._adjust_qty_left
                        else:
                            self._accumulated_pos_deviation -= self._adjust_qty_left

                        self._exist_adjust_order = False
                        self._adjust_qty_target = self._adjust_qty_left = 0

                        cancel_adjust = Token.ORDER_INFO.copy()
                        cancel_adjust['symbol'] = self.symbol_name
                        cancel_adjust['id'] = self.gen_id(self.ADJUST_ORDER_ID, self._adjust_order_side)
                        await self.command_receiver(trans_command=cancel_adjust, token=Token.TO_CANCEL)

                        await asyncio.sleep(0.2)
                        self._need_adjust_pos = True
                else:
                    self._log_account_info('\n>>> 调仓挂单不存在!')
                    self._adjust_qty_target = self._adjust_qty_left = 0
                    self._exist_adjust_order = False

            else:
                if self._need_check_pos:
                    if self._exist_adjust_order:
                        return
                    self._log_account_info('\n>>> 需要检查仓位')
                    await self._check_position()  # 消耗约 100 ms

                    if self._accumulated_pos_deviation == 0:
                        self._log_account_info('### 账户实际仓位正确，不需要修正\n')
                    else:
                        await self._adjust_pos_task()
                    self._need_check_pos = False

                else:
                    # 常规正常情况，不存在修正挂单也不需要修正仓位
                    pass

        finally:
            self._doing_delay_task = False

    # tool methods
    def gen_id(self, self_index: int, side: str) -> str:
        self_id = self.stg_token + '_' + str.zfill(str(self_index), 8) + side
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


class FakeTradeUI:
    def transfer_column(self, stg_num):
        # 什么都不做的方法
        pass
