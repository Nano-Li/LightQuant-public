# -*- coding: utf-8 -*-
# @Time : 2024/2/10 20:00
# @Author : 
# @File : Operator.py 
# @Software: PyCharm
import time
import asyncio
from LightQuant.Analyzer import Analyzer
from LightQuant.Executor import Executor
from LightQuant.protocols.BinanceToken import BinanceToken as Token
from LightQuant.ui.TradeUI import SubAccountColumn
from .SubAnalyzer import SubAnalyzer


class Operator(object):
    """
    丞相，操作员，一人之下，万人之上
    负责解析挂单index，判断给哪个账户并进行调度
    """

    MARKET_ORDER_ID = 99999999  # 市价下单的id，taker成交
    ENTRY_ORDER_ID = 99999998  # 触发挂单id

    def __init__(self):
        self.analyzer = None
        # 用于存储所有子账号子分析模块
        # self.executors: list[Executor] = []
        self.sub_analyzers: list[SubAnalyzer] = []
        self.account_num: int = 0

        self.save_grid_prices = ()
        self.save_grid_quantities = ()

    def initialize(self, analyzer: Analyzer, executor_list: list[Executor], account_cols: dict[str, SubAccountColumn]):
        if len(executor_list) != len(account_cols):
            raise IndexError('字典长度和列表长度不一致')
        self.analyzer = analyzer
        # 分配子模块以执行者
        self.sub_analyzers = [SubAnalyzer() for _ in range(len(executor_list))]
        self.account_num = len(self.sub_analyzers)
        if self.account_num <= 1:
            raise ValueError('子账户数目小于2, 策略不成立')
        # for e_executor in executor_list:
        #     e_executor.set_stg_series(1)  # 保持标签一致的临时方法， 也就是说，这会导致，只能使用一个账号开一个策略
        #     # noinspection PyTypeChecker
        #     e_executor.initialize(FakeTradeUI())
        #     e_executor.add_strategy(self)

        for each_analyzer, each_executor, (each_series, each_col) in zip(self.sub_analyzers, executor_list, account_cols.items()):
            each_analyzer.initialize(
                sub_executor=each_executor,
                operator=self,
                column=each_col,
                series=each_series,  # 从1开始，第几个账号, 001
                stg_series=self.analyzer.stg_num
            )
            # noinspection PyUnresolvedReferences
            symbol_info = {
                'price_min_step': self.analyzer.symbol_price_min_step,
                'qty_min_step': self.analyzer.symbol_quantity_min_step,
                'max_leverage': self.analyzer.symbol_max_leverage,
                'min_notional': self.analyzer.symbol_min_notional,
                'price_div': self.analyzer.symbol_order_price_div,
                'order_limit_num': self.analyzer.symbol_orders_limit_num,
            }
            each_analyzer.set_symbol_info(symbol_name=self.analyzer.symbol_name, info_dict=symbol_info)

        # time.sleep(1)
        # print('\n完成初始化')

    def start_all_subscription(self):
        # for e_executor in self.executors:
        #
        #     # 开启订阅，注意：主账号不能做btc交易
        #     print('{}开启订阅'.format(str(e_executor)))
        #     e_executor.start_single_contract_order_subscription(self.analyzer.symbol_name)
        #     # e_executor.start_single_contract_ticker_subscription(self.symbol_name)
        for each_analyzer in self.sub_analyzers:
            each_analyzer.start_subscription()
        self.sub_analyzers[0].ticker_subscription()
        self.sub_analyzers[1].book_ticker_subscription()

    def change_leverage(self, leverage: int):
        # 修改每一个账号的杠杆
        for each_analyzer in self.sub_analyzers:
            each_analyzer.change_leverage(leverage)

    def set_trade_fee(self, maker_fee: float, taker_fee: float):
        for each_analyzer in self.sub_analyzers:
            each_analyzer.get_fee(maker_fee=maker_fee, taker_fee=taker_fee)

    def start_stg(self):
        for each_analyzer in self.sub_analyzers:
            each_analyzer.start()

    def deliver_market_order(self, market_side: str, market_qty: int, from_index: int, to_index: int) -> None:
        # 按照挂单分配计算市价下单数量，分配给每个子账号
        single_qty = self.save_grid_quantities[from_index + 1]
        # 计算每个子对象的元素数量
        total_elements = to_index - from_index
        base_count = total_elements // self.account_num
        remainder = total_elements % self.account_num
        # 初始化每个子对象的总和
        market_quantities = [base_count * single_qty] * self.account_num
        # 处理余数
        for i in range(remainder):
            market_quantities[i] += single_qty
        if sum(market_quantities) != market_qty:
            raise ValueError('总量与分配量不相等')
        # for each_qty, each_analyzer in zip(market_quantities, self.sub_analyzers):
        #     each_analyzer.
        market_tasks = [each_analyzer.post_market_order(market_side, each_qty) for each_qty, each_analyzer in zip(market_quantities, self.sub_analyzers)]
        asyncio.gather(*market_tasks)

    def deliver_entry_order(self, entry_price: float, entry_qty: int, from_index: int, to_index: int) -> None:
        single_qty = self.save_grid_quantities[from_index + 1]
        # 计算每个子对象的元素数量
        total_elements = to_index - from_index
        base_count = total_elements // self.account_num
        remainder = total_elements % self.account_num
        # 初始化每个子对象的总和
        entry_quantities = [base_count * single_qty] * self.account_num
        # 处理余数
        for i in range(remainder):
            entry_quantities[i] += single_qty
        if sum(entry_quantities) != entry_qty:
            raise ValueError('总量与分配量不相等')
        entry_tasks = [each_analyzer.post_entry_order(entry_price, each_qty) for each_qty, each_analyzer in zip(entry_quantities, self.sub_analyzers)]
        asyncio.gather(*entry_tasks)

    def deliver_grid_param(self, grid_prices: tuple[float], grid_quantities: tuple[int]):
        self.save_grid_prices = grid_prices
        self.save_grid_quantities = grid_quantities

        for sub_index in range(self.account_num):
            sub_grid_price = [self.save_grid_prices[i] if i % self.account_num == sub_index else 0 for i in range(len(self.save_grid_prices))]
            sub_grid_quantity = [self.save_grid_quantities[i] if i % self.account_num == sub_index else 0 for i in range(len(self.save_grid_quantities))]
            sub_analyzer = self.sub_analyzers[sub_index]
            sub_analyzer.get_stg_param_info(symbol_name=self.analyzer.symbol_name, sub_grid_price=tuple(sub_grid_price), sub_grid_quantity=tuple(sub_grid_quantity))

    def append_grid_param(self, add_grid_prices: tuple[float], add_grid_quantities: tuple[int]):
        # 确定新增元素的起始索引
        start_index = len(self.save_grid_prices)
        # 更新保存的价格和数量列表
        self.save_grid_prices += add_grid_prices
        self.save_grid_quantities += add_grid_quantities

        for sub_index in range(self.account_num):
            add_sub_prices = [add_grid_prices[i] if (i + start_index) % self.account_num == sub_index else 0 for i in range(len(add_grid_prices))]
            add_sub_quantities = [add_grid_quantities[i] if (i + start_index) % self.account_num == sub_index else 0 for i in range(len(add_grid_quantities))]
            sub_analyzer = self.sub_analyzers[sub_index]
            sub_analyzer.append_stg_param_info(append_grid_price=tuple(add_sub_prices), append_grid_qty=tuple(add_sub_quantities))

    def terminate(self):
        # todo: 需要取消监听
        for each_analyzer in self.sub_analyzers:
            each_analyzer.stop_strategy()

    def _update_all_account_balance(self):
        # noinspection PyProtectedMember
        accounts_balance = self.analyzer._my_executor.get_all_accounts_balance([each_ana.sub_executor.return_user_id() for each_ana in self.sub_analyzers])

        for each_ana, each_balance in zip(self.sub_analyzers, accounts_balance):
            each_ana.update_account_balance(
                asset=str(round(each_balance['total'], 5)),
                margin=str(round(each_balance['order_margin'] + each_balance['pos_margin'], 5)),
            )

    def check_account_open_orders(self):
        pass

    async def command_receiver(self, command: dict):
        """
        根据来自总策略的订单发送请求，调度子账号执行
        :param command:
        :return:
        """
        token = command['status']

        # todo: 暂时只做出了策略需要的poc挂单
        if token == Token.TO_POST_POC:
            # print('调度员收到挂单请求')
            # 入场挂单需要拆开操作
            order_index, order_side = self.parse_id(command['id'])
            if order_index == self.ENTRY_ORDER_ID:
                total_qty = command['quantity']
                qty_per_acc = self._deliver_qty(total_qty, self.account_num)
                for _i, e_analyzer in enumerate(self.sub_analyzers):
                    each_command = command.copy()
                    each_command['quantity'] = qty_per_acc[_i]
                    # print('执行者 {} 执行挂单请求'.format(str(e_analyzer)))
                    asyncio.create_task(e_analyzer.command_receiver(each_command, token=token))
            else:
                sub_analyzer = self.sub_analyzers[self.return_sub_index(order_index)]
                # print('执行者 {} 执行挂单请求'.format(str(sub_analyzer)))
                asyncio.create_task(sub_analyzer.command_receiver(command, token=token))
                pass
        elif token == Token.TO_POST_BATCH_POC:
            # 暂时将batch order 分解为单个poc请求
            # print('调度员收到批量挂单请求')
            for each_single_cmd in command['orders']:
                order_index, order_side = self.parse_id(each_single_cmd['id'])
                each_single_cmd['status'] = Token.TO_POST_POC
                sub_analyzer = self.sub_analyzers[self.return_sub_index(order_index)]
                # print('执行者 {} 执行挂单请求, order index : {}'.format(str(sub_analyzer), str(order_index)))
                asyncio.create_task(sub_analyzer.command_receiver(each_single_cmd, token=token))
            pass
        elif token == Token.TO_POST_MARKET:
            total_qty = command['quantity']
            qty_per_acc = self._deliver_qty(total_qty, self.account_num)
            for _i, e_analyzer in enumerate(self.sub_analyzers):
                each_command = command.copy()
                each_command['quantity'] = qty_per_acc[_i]
                # print('执行者 {} 执行市价挂单请求'.format(str(e_analyzer)))
                asyncio.create_task(e_analyzer.command_receiver(each_command, token=token))
        elif token == Token.CANCEL_ALL:
            for each_analyzer in self.sub_analyzers:
                asyncio.create_task(each_analyzer.command_receiver(command, token=token))
        elif token == Token.CLOSE_POSITION:
            for each_analyzer in self.sub_analyzers:
                asyncio.create_task(each_analyzer.command_receiver(command, token=token))
        else:
            # 其余的订单，只需根据id，发送到对应的子账号即可
            order_index, order_side = self.parse_id(command['id'])
            sub_analyzer = self.sub_analyzers[self.return_sub_index(order_index)]
            asyncio.create_task(sub_analyzer.command_receiver(command, token=token))

    async def report_receiver(self, recv_data_dict: dict, append_info: str = None) -> None:
        """
        得到每个executor的返回信息，理论上executor直接绑定的analyzer,新策略绑定的是这个operator
        并使用了一样的函数名称来截断订单信息返回，由于是使用重复的函数名称，参数名称也需要一样
        :param append_info:
        :param recv_data_dict:
        :return:
        """

        order_id, order_side = self.parse_id(recv_data_dict['id'])
        # todo: 市价挂单与触发挂单并不知道是来自于哪个账号，只有在总策略总统计数量时会记录
        if order_id == self.ENTRY_ORDER_ID:
            await self.analyzer.report_receiver(recv_data_dict, 0, append_info)
        elif order_id == self.MARKET_ORDER_ID:
            await self.analyzer.report_receiver(recv_data_dict, 0, append_info)
        else:
            acc_id = self.return_sub_index(order_id)
            if recv_data_dict['status'] == Token.ORDER_FILLED:
                append_info = '\n账号 {}'.format(acc_id + 1) + append_info
                await self.analyzer.report_receiver(recv_data_dict, 0, append_info)
            else:
                await self.analyzer.report_receiver(recv_data_dict, acc_id + 1, append_info)

    async def ticker_receiver(self, ticker_data: dict) -> None:
        """
        只接受来自第一个子账号的ticker信息
        :param ticker_data:
        :return:
        """
        await self.analyzer.ticker_receiver(ticker_data)

    async def ticker_sender(self, c_index: int, base_index: int, z_index, up_index: int, c_price: float) -> None:
        # 定时发送ticker信息
        sub_tasks = [each_ana.get_ticker(c_index, base_index, z_index, up_index, c_price) for each_ana in self.sub_analyzers]
        await asyncio.gather(*sub_tasks)

    async def tick_sender(self) -> None:
        # 发送一个主动信息给所有子账号（延时任务）
        sub_tasks = [each_ana.get_tick() for each_ana in self.sub_analyzers]
        await asyncio.gather(*sub_tasks)
        self._update_all_account_balance()

    async def send_best_price(self, ask_price: float, bid_price: float) -> None:
        sub_tasks = [each_ana.get_best_price(ask_price, bid_price) for each_ana in self.sub_analyzers]
        await asyncio.gather(*sub_tasks)

    async def book_ticker_receiver(self, book_data: dict) -> None:
        await self.analyzer.book_ticker_receiver(book_data)

    # tool
    def return_sub_index(self, order_index: int) -> int:
        # 根据订单id返回子账号索引
        return order_index % self.account_num

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
    def _deliver_qty(total_qty: int, account_num: int) -> list[int]:
        """
        临时平均分配触发挂单的数量，尽可能平均
        :param total_qty:
        :param account_num:
        :return:
        """
        # 每个网格基础分配的数量
        base_quantity = total_qty // account_num
        # 需要额外分配的数量
        extra_quantity = total_qty % account_num
        # 分配数量到每个网格
        quantities = [base_quantity + 1 if i < extra_quantity else base_quantity for i in range(account_num)]

        return quantities


