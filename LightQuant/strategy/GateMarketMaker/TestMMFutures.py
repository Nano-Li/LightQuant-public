# -*- coding: utf-8 -*-
# @Time : 2024/2/11 1:00
# @Author : 
# @File : TestMMFutures.py 
# @Software: PyCharm
import time
import asyncio
import numpy as np
import pandas as pd
from decimal import Decimal
from LightQuant.tools.calc import calc, calc_sum
from LightQuant.tools.round_step_size import round_step_size
from LightQuant.Analyzer import Analyzer
from LightQuant.Executor import Executor
from LightQuant.protocols.BinanceToken import BinanceToken as Token
from LightQuant.strategy.GateAnalyzer.SmartGridFutures import SmartGridAnalyzerFutures
from LightQuant.strategy.GateMarketMaker.Operator import Operator


class TestMarketMakerAnalyzer(SmartGridAnalyzerFutures):
    """
    修改框架，测试多账号运行情况
    """

    def __init__(self):
        super().__init__()

        # 使用多少个子账号进行交易
        self.sub_account_num: int = 5
        # noinspection PyTypeChecker
        self._my_operator: Operator = None

    def acquire_operator(self, operator: Operator) -> None:
        self._my_operator = operator

    def return_acc_num(self) -> int:
        # return self.sub_account_num
        return 5

    def return_fund_demand(self) -> float:
        return 100
        # return self.account_fund_demand

    def confirm_params(self, input_params: dict) -> None:
        self.symbol_name = input_params['symbol_name']
        print('主账号不订阅')
        # self._my_executor.start_single_contract_order_subscription(self.symbol_name)
        # self._my_executor.start_single_contract_ticker_subscription(self.symbol_name)

    def derive_functional_variables(self, assign_entry_price: float = 0) -> None:
        super().derive_functional_variables(assign_entry_price)

        # 额外调用调度员传给子账号参数 todo: 只有在最后开始策略时才有必要传参数，其余不必要
        if self._my_operator:
            self._my_operator.deliver_grid_param(grid_prices=self.all_grid_price, grid_quantities=self.all_grid_quantity)

    def _add_buffer_vars(self) -> None:
        """
        由于需要使用函数内局部变量，直接覆写父类方法
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
        add_grid_qty = tuple(self.unequal_grid_qty_calc(self.all_filling_prices[self.saved_stair_num], filling_grid_num, self.filling_fund))[:len(add_grid_price)]

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

        if self._my_operator:
            self._my_operator.append_grid_param(add_grid_prices=tuple(add_grid_price), add_grid_quantities=add_grid_qty)

    def sub_initialize(self):
        self._my_operator.start_all_subscription()
        self._my_operator.change_leverage(self.symbol_leverage)
        time.sleep(0.5)

    async def _start_strategy(self):
        self._is_waiting = False
        self._is_trading = True
        self._log_info('密集做市网格 策略开始')

        # todo: 不管是否是重复查询了
        fee_dict = await self._my_executor.get_symbol_trade_fee(self.symbol_name)
        self.symbol_maker_fee = fee_dict['maker_fee']
        self.symbol_taker_fee = fee_dict['taker_fee']
        self._log_info('maker fee rate: {}'.format(self.symbol_maker_fee))
        self._log_info('taker fee rate: {}'.format(self.symbol_taker_fee))
        self._my_operator.set_trade_fee(maker_fee=self.symbol_maker_fee, taker_fee=self.symbol_taker_fee)

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

        # 3. 开启维护挂单任务
        self._fix_order_task = asyncio.create_task(self._order_fixer(interval_time=180))

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

    async def _terminate_trading(self, reason: str = '') -> None:
        await super()._terminate_trading(reason)
        self._my_operator.terminate()

    def _reasonable_order_num_estimate(self):
        # 新策略根据账户数量设定挂单数量.注意：只限用于100挂单限制的btc
        self.max_buy_order_num = self.max_sell_order_num = int(self.symbol_orders_limit_num * 0.8 / 2) * self.sub_account_num
        self.min_buy_order_num = self.min_sell_order_num = int(self.symbol_orders_limit_num * 0.4 / 2) * self.sub_account_num
        self.buffer_buy_num = self.buffer_sell_num = max(10, int(self.min_buy_order_num / 2))

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

            elif order_index == self.adjusting_index:
                # 高频关键功能：仓位修复策略
                raise ValueError('主策略不修正仓位，逻辑错误')

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
            if side == self.BUY:
                self._accumulated_pos_deviation += self.all_grid_quantity[this_order_index + 1]
            else:
                self._accumulated_pos_deviation -= self.all_grid_quantity[this_order_index]
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
            print('总领需要批量挂单')
            asyncio.create_task(self._my_operator.command_receiver(trans_command))
        elif token == Token.TO_POST_MARKET:
            print('总领需要市价挂单')
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

    def send_index(self):
        asyncio.create_task(self._my_operator.ticker_sender(self.critical_index, self.present_base_index, self.present_step_up_index))

    def delay_task(self):
        self._log_info('>>> ')
        asyncio.create_task(self._my_operator.tick_sender())

    # tool methods

    # todo: gen_id 和 parse id 没有修改，因此在下一步操作中会额外解析，这会带来额外计算量，亟需优化改进

