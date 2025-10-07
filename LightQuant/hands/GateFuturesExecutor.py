# -*- coding: utf-8 -*-
# @Time : 2023/1/26 22:03 
# @Author : 
# @File : GateFuturesExecutor.py 
# @Software: PyCharm
import re
import time
import json
import typing
import asyncio
import numpy as np
import pandas as pd
from typing import Union
from LightQuant.Recorder import LogRecorder
from LightQuant.Executor import Executor
from LightQuant.Analyzer import Analyzer
from LightQuant.protocols.BinanceToken import BinanceToken as Token

import gate_api
from gate_api.exceptions import ApiException, GateApiException
from gate_api import FuturesOrder, FuturesOrderAmendment
import gate_ws
from gate_ws.futures import FuturesOrderChannel, FuturesTickerChannel, FuturesUserTradesChannel, FuturesPublicTradeChannel, FuturesBookTickerChannel
from gate_ws.api import AsyncOrderClient, GateWebsocketApiError


class GateFuturesExecutor(Executor):
    """
    Gate执行者类，负责对接到Gate api的具体操作
    处理U本位合约的socket信息，一个类实例处理一个U本位合约的交易数据

    """
    NAME = 'Gate 合约'

    # noinspection PyTypeChecker
    def __init__(self) -> None:
        super(GateFuturesExecutor, self).__init__()

        self._client = None
        self._syncclient = None  # 非异步client

        self._order_client: gate_api.FuturesApi = None
        # 钱包接口
        self._wallet_client: gate_api.WalletApi = None
        self._websocket_channel_order: FuturesOrderChannel = None
        self._websocket_channel_ticker: FuturesTickerChannel = None
        self._websocket_channel_trade: FuturesUserTradesChannel = None
        self._websocket_channel_public_trade: FuturesPublicTradeChannel = None
        self._websocket_channel_book_ticker: FuturesBookTickerChannel = None

        self._websocket_connection: gate_ws.Connection = None
        # todo: 进行更好的封装，只需要一个connection即可pingpong
        # self._websocket_client_connection: ClientConnection = None
        self._async_client: AsyncOrderClient = None

        self.gathered_connection = None
        # 该变量用于确保只创建一次连接
        self._connected = False

        self._api_key = None
        self._api_secret = None
        self._user_id = 0

        self._time_out = None

        # 用于存储不确定是否成功的请求 {'self_orderid': timestamp_when_posted}
        # todo: 添加循环检错功能
        self._unidentified_pending_order = {}
        self._unidentified_cancel_order = {}

        # binance socket manager 类
        self._socket_manager = None
        # 合约用户数据流
        self._user_futures_socket = None
        # symbol ticker socket
        self._symbol_ticker_socket = None

        # 当前处理的合约
        # self._current_trading_symbol = None

        # starting methods

    def initialize(self, main_UI) -> None:
        # todo: 类提示
        super().initialize(main_UI)
        self._recorder = LogRecorder()
        self._recorder.open_file('GateExecutor')
        print('初始化gate连接')
        print(id(self._event_loop))
        asyncio.create_task(self.create_connection())
        asyncio.create_task(self.engine_start())
        print('创建任务完成')

    def acquire_api_params(self, key: str, secret: str, user_id: str) -> None:
        self._api_key = key
        self._api_secret = secret
        self._user_id = user_id

    def read_api_params(self, file_name: str = None) -> bool:
        """
        从 txt 中读取 api 及其密钥
        :return: 返回是否成功读取
        """
        done = True

        if file_name is None:
            print('请选择GATE API参数文件')
            done = False

        try:
            with open(file_name, 'r', encoding='utf-8') as params_file:
                params_content = params_file.read()
        except Exception as e:
            print(str(e))
            print((str(type(e))))
            done = False

        try:
            self._api_key = re.findall(r'api_key=(.*?)\n', params_content)[0].replace(' ', '')
            self._api_secret = re.findall(r'api_secret=(.*?)\n', params_content)[0].replace(' ', '')
            self._user_id = re.findall(r'user_id=(.*?)\n', params_content)[0].replace(' ', '')
        except Exception as e:
            print(str(e))
            print((str(type(e))))
            done = False

        return done

    def return_user_id(self) -> int:
        return self._user_id

    def close_api(self) -> None:
        """
        临时方法，关闭连接并保存文件
        :return:
        """
        self._recorder.close_file()

    # single-use methods
    async def create_connection(self) -> bool:
        """
        在策略开始前操作，被 Analyzer 调用一次
        开始与 Gate 服务器的连接
        操作：创建 client 等一些初始操作
        :return:
        """
        print('{} 创建通道连接'.format(str(self)))
        if self._connected:
            return True
        # todo: client创建成功
        success = True
        try:
            api_cfg = gate_api.Configuration(
                host="https://api.gateio.ws/api/v4",
                key=self._api_key,
                secret=self._api_secret
            )
            gate_api_client = gate_api.ApiClient(api_cfg)
            self._order_client = gate_api.FuturesApi(gate_api_client)
            self._wallet_client = gate_api.WalletApi(gate_api_client)

            ws_cfg = gate_ws.Configuration(app='futures', settle='usdt', api_key=self._api_key, api_secret=self._api_secret, ping_interval=10)
            self._websocket_connection = gate_ws.Connection(ws_cfg)
            self._websocket_channel_order = FuturesOrderChannel(self._websocket_connection, callback=self._user_order_socket_receiver)
            self._websocket_channel_ticker = FuturesTickerChannel(conn=self._websocket_connection, callback=self._ticker_socket_receiver)
            self._websocket_channel_trade = FuturesUserTradesChannel(conn=self._websocket_connection, callback=self._user_trade_socket_receiver)

            self._websocket_channel_public_trade = FuturesPublicTradeChannel(conn=self._websocket_connection, callback=self._public_trade_socket_receiver)
            self._websocket_channel_book_ticker = FuturesBookTickerChannel(conn=self._websocket_connection, callback=self._book_ticker_socket_receiver)

            # self._websocket_client_connection = ClientConnection(ws_cfg)
            self._async_client = AsyncOrderClient(conn=self._websocket_connection, callback=self._user_order_api_receiver)
            self._async_client.login(key=self._api_key, secret=self._api_secret)
            print('client创建成功')

            # todo: gate connection error test
        except Exception as e:
            print('未知原因导致与 gate 连接的客户端创建失败')
            # self._my_logger.log_error_exit(e)
            print('\n', '*' * 59)
            print('>>>>> 程序出错\n错误类型: {}\n错误内容: {}'.format(str(type(e)), e))
            print('*' * 59, '\n')
            success = False

        return success

    def abort_connection(self) -> None:
        """
        断开与gate服务器的一切通讯
        :return:
        """
        self._connecasted = False
        self._websocket_connection.close()
        # self._websocket_client_connection.close()

    async def engine_start(self) -> None:
        """

        :return:
        """
        if self._connected:
            return
        await super().engine_start()
        self._connected = True
        print('connect gate api')
        await self._websocket_connection.run()
        # await self._websocket_client_connection.run()

        # tasks: typing.List[asyncio.Task] = list()
        #
        # tasks.append(self._event_loop.create_task(self._websocket_connection.run()))
        # tasks.append(self._event_loop.create_task(self._websocket_client_connection.run()))
        # self.gathered_connection = asyncio.gather(*tasks)
        # await self.gathered_connection

        print('结束gate连接')

    async def get_symbol_info(self, symbol_name: str) -> Union[dict, None]:
        """
        在策略开始前，被 Analyzer 调用一次
        获取交易合约的基本信息
        :param symbol_name: 合约名
        :return:
        """
        if symbol_name is None:
            print('未设置合约名')
            return None

        symbol_info_dict = {}

        try:
            info_res = self._order_client.get_futures_contract(settle='usdt', contract=symbol_name)
        except GateApiException as ex:
            if ex.label == 'CONTRACT_NOT_FOUND':
                return None
            else:
                raise Exception('查询合约信息错误')

        symbol_info_dict['price_min_step'] = float(info_res.order_price_round)
        symbol_info_dict['qty_min_step'] = float(info_res.quanto_multiplier)
        symbol_info_dict['max_leverage'] = int(info_res.leverage_max)
        symbol_info_dict['order_price_deviate'] = float(info_res.order_price_deviate)
        symbol_info_dict['orders_limit'] = info_res.orders_limit

        return symbol_info_dict

    async def get_current_price(self, symbol_name: str) -> float:
        """
        在开始策略时，被 Analyzer 调用一次
        获取合约当前价格
        :param symbol_name: 合约名
        :return:
        """
        ticker_res = self._order_client.list_futures_tickers(settle='usdt', contract=symbol_name)
        return float(ticker_res[0].last)

    async def change_symbol_leverage(self, symbol_name: str, leverage: int) -> None:
        """
        更改某个合约的杠杆数目
        :param symbol_name:
        :param leverage: 杠杆数
        :return:
        """
        try:
            lev_res = self._order_client.update_position_leverage(
                settle='usdt',
                contract=symbol_name,
                leverage='0',
                cross_leverage_limit=str(leverage)
            )
        except Exception as e:
            print('杠杆调整失败，请检查 response:\n')
            print(e)
            print(type(e))
            return

        print('成功调整杠杆')

    async def get_symbol_position(self, symbol_name: str) -> Union[int, float]:
        """
        查询当前合约仓位
        :param symbol_name:
        :return:
        """
        info_res = self._order_client.get_position(settle='usdt', contract=symbol_name)
        return info_res.size

    def get_all_accounts_balance(self, uid_list: list[int]) -> list[dict]:
        uid_param = ', '.join(str(each_id) for each_id in uid_list)
        info_res = self._wallet_client.list_sub_account_futures_balances(sub_uid=uid_param)
        info = [
            {
                'available': float(each_res.available['usdt'].available),
                'order_margin': float(each_res.available['usdt'].order_margin),
                'pos_margin': float(each_res.available['usdt'].position_margin),
                'total': float(each_res.available['usdt'].total),

            } for each_res in info_res
        ]

        return info

    def get_symbol_position_with_io(self, symbol_name: str) -> Union[int, float]:
        """
        非协程版本的获账户仓位函数，运行该函数会等待网络io
        在服务器上测试，网络io等待延时大概在80ms
        :param symbol_name:
        :return:
        """
        info_res = self._order_client.get_position(settle='usdt', contract=symbol_name)
        return info_res.size

    async def get_symbol_trade_fee(self, symbol_name: str) -> dict:
        """
        查询某个合约交易手续费
        :param symbol_name:
        :return:
        """
        trade_fee: dict = {
            'maker_fee': 0,
            'taker_fee': 0
        }
        try:
            fee_res = self._wallet_client.get_trade_fee(currency_pair=symbol_name, settle='usdt')

            trade_fee['maker_fee'] = float(fee_res.futures_maker_fee)
            trade_fee['taker_fee'] = float(fee_res.futures_taker_fee)

        except GateApiException as ex:
            print("获取交易手续费失败, label: %s, message: %s\n" % (ex.label, ex.message))

        return trade_fee

    async def get_open_orders(self, symbol_name: str) -> tuple[list[str], list[str]]:
        """
        获得某个合约的所有open orders
        :param symbol_name:
        :return: 策略id list, 真实id list
        """
        open_orders_stg_id = []
        open_orders_real_id = []
        orders_res = self._order_client.list_futures_orders(
            settle='usdt',
            contract=symbol_name,
            status='open',
            # limit=100,
            # offset=0,
        )
        for each_order_ins in orders_res:
            strategy_id = each_order_ins.text[2:]
            real_id = str(each_order_ins.id)

            open_orders_stg_id.append(strategy_id)
            open_orders_real_id.append(real_id)

        return open_orders_stg_id, open_orders_real_id

    async def get_open_orders_beta(self, symbol_name: str) -> list[dict]:
        """
        beta策略版使用，获取更详细订单信息
        :param symbol_name:
        :return:
        """
        orders_res = self._order_client.list_futures_orders(
            settle='usdt',
            contract=symbol_name,
            status='open',
        )
        acc_open_orders = []
        for each_order_ins in orders_res:
            acc_open_orders.append(
                {
                    'stg_id': each_order_ins.text[2:],      # str
                    'server_id': each_order_ins.id,         # int id
                    'price': each_order_ins.price,          # str
                    'size': each_order_ins.size,            # int with +-
                    'left_qty': each_order_ins.left         # int with +-
                }
            )

        return acc_open_orders

    def get_single_order(self, order_id: str) -> tuple[bool, float, int]:
        # 临时方法，检查单个挂单是否存在及其价格
        try:
            single_res = self._order_client.get_futures_order(
                settle='usdt',
                order_id='t-' + order_id
            )
        except GateApiException as api_err:
            if api_err.label == 'CLIENT_ID_NOT_FOUND':
                return False, 0., 0
            else:
                raise api_err
        except Exception as other_err:
            raise other_err
        # print(single_res)
        if single_res.status == 'open':
            price = float(single_res.price)
            size = single_res.size
            return True, price, size
        else:
            return False, 0., 0

    def get_open_orders_with_io(self, symbol_name: str) -> tuple[list[str], list[str]]:
        """
        非协程版获取当前合约订单，
        延时在100ms左右
        :param symbol_name:
        :return:
        """
        open_orders_stg_id = []
        open_orders_real_id = []
        orders_res = self._order_client.list_futures_orders(
            settle='usdt',
            contract=symbol_name,
            status='open',
        )
        for each_order_ins in orders_res:
            strategy_id = each_order_ins.text[2:]
            real_id = str(each_order_ins.id)

            open_orders_stg_id.append(strategy_id)
            open_orders_real_id.append(real_id)

        return open_orders_stg_id, open_orders_real_id

    # todo: 新增的查询子账号及转账方法
    def get_sub_account_futures_balance(self, user_id: int) -> float:
        # 返回usdt余额
        print('查询{}账户余额'.format(user_id))
        balance_res = self._wallet_client.list_sub_account_futures_balances(sub_uid=user_id)
        # print(balance_res)
        usdt_balance = balance_res[0].available['usdt'].total
        if usdt_balance is None:
            usdt_balance = 0
        else:
            usdt_balance = float(usdt_balance)
        return usdt_balance

    def transfer_fund(self, user_id: int, fund: float, direction: str = 'to'):
        if fund <= 0:
            raise ValueError('转移资金为0')
        sub_account_transfer = gate_api.SubAccountTransfer(
            currency='USDT',
            sub_account=str(user_id),
            direction=direction,
            amount=str(fund),
            sub_account_type='futures'
        )
        self._wallet_client.transfer_with_sub_account(sub_account_transfer)

    # ## ==================================== all streams ==================================== ## #
    async def _user_order_socket_receiver(self, conn: gate_ws.Connection, res: gate_ws.WebSocketResponse) -> None:
        """
        不断监听服务器返回的用户数据
        :return:
        """
        if res.error:
            print('用户订单频道  gate服务器返回报错信息: ', res.error)
            return

        # user_info_dict = json.loads(res.body)
        user_info_dict = res.msg
        if user_info_dict['event'] == 'update':
            result_list = user_info_dict['result']
            for _, each_result in enumerate(result_list):
                await self._handle_user_futures_order_data(each_result)

        elif user_info_dict['event'] == 'subscribe':
            print('成功订阅合约订单信息')

        elif user_info_dict['event'] == 'unsubscribe':
            print('成功取消合约订阅信息')

        else:
            print('其他未记录的websocket事件类型:')
            print(str(user_info_dict))

    async def _user_order_api_receiver(self, action_status: dict) -> None:
        """
        监听api返回订单情况
        :param action_status:
        :return:
        """
        await self._handle_api_futures_order_data(action_status)

    async def _user_trade_socket_receiver(self, conn: gate_ws.Connection, res: gate_ws.WebSocketResponse) -> None:
        """
        监听返回用户订单成交数据
        :param conn:
        :param res:
        :return:
        """
        if res.error:
            print('用户私有成交频道  gate服务器返回报错信息: ', res.error)
            return

        # trade_info_dict = json.loads(res.body)
        trade_info_dict = res.msg
        # print(trade_info_dict)
        if trade_info_dict['event'] == 'update':
            result_list = trade_info_dict['result']
            for _, each_result in enumerate(result_list):
                # 从此刻开始，协程函数都是使用 await, 确保收信时，不会有两个协程同时调用策略变量
                await self._handle_user_futures_trade_data(each_result)

        elif trade_info_dict['event'] == 'subscribe':
            print('成功订阅合约订单信息')

        elif trade_info_dict['event'] == 'unsubscribe':
            print('成功取消合约订阅信息')

        else:
            print('其他未记录的websocket事件类型:')
            print(str(trade_info_dict))

    def start_single_contract_order_subscription(self, contract_name: str) -> None:
        """
        每创建一个策略，需要开启监听一个合约信息
        :param contract_name:
        :return:
        """
        try:
            # self._websocket_channel_order.subscribe([self._user_id, contract_name])
            self._websocket_channel_trade.subscribe([self._user_id, contract_name])
        except Exception as ex:
            print(ex)
            print(type(ex))
        print('开启合约数据监听 {}'.format(contract_name))

    def stop_single_contract_order_subscription(self, contract_name: str) -> None:
        """
        策略结束后，停止监听信息
        :param contract_name:
        :return:
        """
        # self._websocket_channel_order.unsubscribe([self._user_id, contract_name])
        self._websocket_channel_trade.unsubscribe([self._user_id, contract_name])
        print('关闭合约数据监听 {}'.format(contract_name))

    async def _ticker_socket_receiver(self, conn: gate_ws.Connection, ticker_res: gate_ws.WebSocketResponse) -> None:
        """
        持续获得从gate服务器订阅的合约ticker信息，即最新价格
        :return:
        """
        if ticker_res.error:
            print('合约ticker频道  gate服务器返回报错信息: ', ticker_res.error)
            return

        ticker_info_dict = ticker_res.msg
        if ticker_info_dict['event'] == 'update':
            symbol_ticker = ticker_info_dict['result'][0]
            await self._handle_futures_ticker_data(symbol_ticker)

            # result_list = ticker_info_dict['result']
            # for _, each_result in enumerate(result_list):
            #     await self._handle_spot_ticker_data(each_result)

        elif ticker_info_dict['event'] == 'subscribe':
            print('成功订阅合约ticker信息')

        elif ticker_info_dict['event'] == 'unsubscribe':
            print('成功取消合约ticker信息')

        else:
            print('其他未记录的ticker socket事件类型:')
            print(str(ticker_info_dict))

    def start_single_contract_ticker_subscription(self, contract_name: str) -> None:
        """
        开启监听一个合约ticker信息
        :param contract_name:
        :return:
        """
        self._websocket_channel_ticker.subscribe([contract_name])
        print('开启合约ticker数据监听 {}'.format(contract_name))

    def stop_single_contract_ticker_subscription(self, contract_name: str) -> None:
        """
        关闭一个合约ticker信息
        :param contract_name:
        :return:
        """
        self._websocket_channel_ticker.unsubscribe([contract_name])
        print('关闭合约ticker数据监听 {}'.format(contract_name))

    async def _public_trade_socket_receiver(self, conn: gate_ws.Connection, public_trade_res: gate_ws.WebSocketResponse) -> None:
        """
        获得共有成交信息，即盘口成交信息
        :param public_trade_res:
        :return:
        """
        if public_trade_res.error:
            print('共有成交频道  gate服务器返回报错信息: ', public_trade_res.error)
            return

        # public_trade_info = json.loads(public_trade_res.body)
        public_trade_info = public_trade_res.msg
        if public_trade_info['event'] == 'update':
            symbol_trade_info = public_trade_info['result'][0]
            await self._handle_futures_public_trade_data(symbol_trade_info)

        elif public_trade_info['event'] == 'subscribe':
            print('成功订阅合约公有成交信息')

        elif public_trade_info['event'] == 'unsubscribe':
            print('成功取消合约公有成交信息')

        else:
            print('其他未记录的public trade socket事件类型:')
            print(str(public_trade_info))

    async def _book_ticker_socket_receiver(self, conn: gate_ws.Connection, book_ticker_res: gate_ws.WebSocketResponse) -> None:
        """
        获取最佳买卖价信息
        :param conn:
        :param book_ticker_res:
        :return:
        """
        if book_ticker_res.error:
            print('共有成交频道  gate服务器返回报错信息: ', book_ticker_res.error)
            return

        book_ticker_info = book_ticker_res.msg
        if book_ticker_info['event'] == 'update':
            symbol_book_ticker_info: dict = book_ticker_info['result']
            await self._handle_futures_book_ticker_data(symbol_book_ticker_info)

        elif book_ticker_info['event'] == 'subscribe':
            print('成功订阅合约最佳买卖价信息')

        elif book_ticker_info['event'] == 'unsubscribe':
            print('成功取消合约最佳买卖价信息')

        else:
            print('其他未记录的public trade socket事件类型:')
            print(str(book_ticker_info))

    def start_single_contract_public_trade_subscription(self, contract_name: str) -> None:
        self._websocket_channel_public_trade.subscribe([contract_name])
        print('开启合约public trade数据监听 {}'.format(contract_name))

    def stop_single_contract_public_trade_subscription(self, contract_name: str) -> None:
        self._websocket_channel_public_trade.unsubscribe([contract_name])
        print('关闭合约public trade数据监听 {}'.format(contract_name))

    def start_single_contract_book_ticker_subscription(self, contract_name: str) -> None:
        self._websocket_channel_book_ticker.subscribe([contract_name])
        print('开启合约book ticker数据监听 {}'.format(contract_name))

    def stop_single_contract_book_ticker_subscription(self, contract_name: str) -> None:
        self._websocket_channel_book_ticker.unsubscribe([contract_name])
        print('关闭合约book ticker数据监听 {}'.format(contract_name))

    def temp_reconnect(self) -> None:
        print('\n\ndoing urgent task!! ')
        tmp_symbol_list = [each_ana.symbol_name for each_ana in self._running_strategies.values()]
        for each_symbol_name in tmp_symbol_list:
            self.stop_single_contract_order_subscription(each_symbol_name)
            self.stop_single_contract_ticker_subscription(each_symbol_name)

        print('all stop connection, waiting...')
        time.sleep(5)
        for each_symbol_name in tmp_symbol_list:
            self.start_single_contract_order_subscription(each_symbol_name)
            self.start_single_contract_ticker_subscription(each_symbol_name)

        print('all reconnected')

        # print(self._running_strategies)
        # print(len(self._running_strategies))
        #
        # for each_id, each_ana in self._running_strategies.items():
        #     print(each_id, each_ana.symbol_name)
        #
        # self._connected = False
        # asyncio.create_task(self.create_connection())
        # asyncio.create_task(self._websocket_connection.run())

    async def temp_place_order(self):
        print('\n临时功能测试')
        command1 = Token.ORDER_INFO.copy()
        command1['symbol'] = 'BTC_USDT'
        command1['id'] = 'test-sdk'
        command1['price'] = 70000
        command1['side'] = 'BUY'
        command1['quantity'] = 2

        command2 = Token.ORDER_INFO.copy()
        command2['symbol'] = 'BTC_USDT'
        command2['id'] = 'test-sdk'
        command2['price'] = 71000
        command2['side'] = 'SELL'
        command2['quantity'] = 2

        BATCH_ORDER_INFO = {
            'orders': [command1, command2],
            'status': 'to_post_batch'
        }
        # cancel_cmd = Token.ORDER_INFO.copy()
        # cancel_cmd['symbol'] = 'BTC_USDT'
        # cancel_cmd['id'] = 'ui1stg4_000008'
        # cancel_cmd['price'] = 43500
        # cancel_cmd['quantity'] = 3

        # await self._change_poc_order_price(cancel_cmd)
        await self._post_poc_batch_orders(BATCH_ORDER_INFO)

    async def temp_amend_order(self):
        btc_amend = gate_api.FuturesOrderAmendment(
            price='42500',
        )
        for i in range(500):
            print('info sent time: {}'.format(int(1000 * time.time())))
            # await asyncio.sleep(0.005)
            self._async_client.amend_order(
                amend_text='t-test_poc_amend',
                amend_info=btc_amend
            )

    # ## ==================================== all streams ==================================== ## #

    # handling data methods
    async def _handle_user_futures_order_data(self, order_data: dict) -> None:
        """
        根据得到的用户数据，分析判断是否需要上报及其他操作

        订单状态包括
            _new        新挂单
            filled      订单成交
            cancelled   撤销订单

        操作：
            收到挂单成交的信息，交给联络员上报
            收到挂单成功和撤单成功的信息，自行处理

        :param order_data:
        :return:
        """
        order_status = order_data['finish_as']

        report_data_dict = Token.ORDER_INFO.copy()
        report_data_dict['symbol'] = order_data['contract']
        # todo:多策略时，在此洗去stg信息，似乎不需要
        report_data_dict['id'] = order_data['text'][2:]
        report_data_dict['price'] = order_data['price']
        report_data_dict['side'] = 'BUY' if order_data['size'] > 0 else 'SELL'
        report_data_dict['quantity'] = order_data['size']

        if order_status == 'filled':
            return
            # # 挂单成交，需要上报
            # # todo: test lag
            # current_timestamp = int(round(time.time() * 1000))
            # filled_timestamp = order_data['finish_time_ms']
            # # filled_time = pd.to_datetime(filled_timestamp, unit='ms')
            # append_info = '\n订单成交，成交时间 {}'.format(str(pd.to_datetime(filled_timestamp, unit='ms') + pd.Timedelta(hours=8)))
            # # print('\n订单成交，成交时间 {}'.format(str(pd.to_datetime(filled_timestamp, unit='ms'))))
            # append_info += '\n反应延时: {}'.format(current_timestamp - filled_timestamp)
            # # print('反应延时: {}'.format(current_timestamp - filled_timestamp))
            # # print(json.dumps(user_data))
            # if order_data['tif'] == 'ioc':
            #     report_data_dict['price'] = order_data['fill_price']
            #
            # await self.reporter(report_data=report_data_dict, token=Token.ORDER_FILLED, appending_info=append_info)
        elif order_status == '_new':
            # print('收到挂单成功信息')
            # print('收到挂单成功信息\t\t价格: {:<12}\tid: {:<10}'.format(user_data['o']['p'], user_data['o']['c']))
            # 已有判断挂单成功的方法(request 返回)，暂不需要使用
            # print('撮合时间: {}'.format(str(user_data['T'])))
            # print('事件时间: {}'.format(str(user_data['E'])))
            if order_data['tif'] == 'poc':
                await self.reporter(report_data=report_data_dict, token=Token.POC_SUCCESS)
            else:
                await self.reporter(report_data=report_data_dict, token=Token.POST_SUCCESS)
            # todo: 自己处理该信息
            pass
        elif order_status == 'cancelled':
            if order_data['tif'] == 'poc':
                await self.reporter(report_data=report_data_dict, token=Token.CANCEL_POC_SUCCESS)
            else:
                await self.reporter(report_data=report_data_dict, token=Token.CANCEL_SUCCESS)
            # todo: 计算操作时间
        elif order_status == '_update':
            # append_info = 'left={}'.format(order_data['left'])
            # await self.reporter(report_data=report_data_dict, token=Token.PARTIALLY_FILLED, appending_info=append_info)
            await self.reporter(report_data=report_data_dict, token=Token.ORDER_UPDATE)

        else:
            print('暂未处理的订单状态: {}'.format(order_status))
            print(order_data)

    async def _handle_api_futures_order_data(self, action_status: dict) -> None:
        """
        根据订单执行情况做出执行判断
        :param action_status:
        :return:
        """
        report_data_dict = Token.ORDER_INFO.copy()
        order_info = action_status['result']
        if action_status['channel'] == 'futures.order_place' or action_status['channel'] == 'futures.order_batch_place':
            # print('\n###确认挂单成功')

            report_data_dict['symbol'] = order_info['contract']
            report_data_dict['id'] = order_info['text'][2:]
            report_data_dict['price'] = order_info['price']
            report_data_dict['side'] = 'BUY' if order_info['size'] > 0 else 'SELL'
            report_data_dict['quantity'] = order_info['size']

            if action_status['success']:
                if order_info['tif'] == 'poc':
                    await self.reporter(report_data=report_data_dict, token=Token.POC_SUCCESS)
                else:
                    # todo: 市价挂单的成交也会作为挂单成功返回并输出信息, ioc
                    await self.reporter(report_data=report_data_dict, token=Token.POST_SUCCESS)
            else:
                error: GateWebsocketApiError = action_status['error']
                if order_info['tif'] == 'poc':
                    if error.label == 'ORDER_POC_IMMEDIATE':
                        await self.reporter(report_data=report_data_dict, token=Token.POC_REJECTED)
                    else:
                        await self.reporter(report_data=report_data_dict, token=Token.POC_FAILED, appending_info=str(error))
                else:
                    await self.reporter(report_data=report_data_dict, token=Token.POST_FAILED, appending_info=str(error))

        # elif action_status['channel'] == 'futures.order_batch_place':
        #     pass
        elif action_status['channel'] == 'futures.order_cancel':
            # print('\n###确认撤单成功')
            report_data_dict['id'] = order_info['text'][2:]

            if action_status['success']:
                if order_info['tif'] == 'poc':
                    await self.reporter(report_data=report_data_dict, token=Token.CANCEL_POC_SUCCESS)
                else:
                    await self.reporter(report_data=report_data_dict, token=Token.CANCEL_SUCCESS)
            else:
                error: GateWebsocketApiError = action_status['error']
                await self.reporter(report_data=report_data_dict, token=Token.CANCEL_FAILED, appending_info=str(error))
        elif action_status['channel'] == 'futures.order_amend':
            # print('\n###确认修改成功')
            report_data_dict['id'] = order_info['text'][2:]

            if action_status['success']:
                # todo: token 可以更新，此处只是兼容旧系统
                await self.reporter(report_data=report_data_dict, token=Token.ORDER_UPDATE)
            else:
                # todo: 当前交易系统只修改poc挂单
                await self.reporter(report_data=report_data_dict, token=Token.AMEND_POC_FAILED, appending_info=str(action_status['error']))

        elif action_status['channel'] == 'futures.login':
            if action_status['success']:
                print('下单api登录成功')
            else:
                raise ConnectionError('下单api登录失败')

    async def _handle_user_futures_trade_data(self, order_data: dict) -> None:
        """
        根据用户得到的私有成交数据，上报订单成交信息
        :param order_data:
        :return:
        """
        report_data_dict = Token.ORDER_INFO.copy()
        report_data_dict['symbol'] = order_data['contract']
        report_data_dict['id'] = order_data['text'][2:]
        report_data_dict['price'] = order_data['price']
        report_data_dict['side'] = 'BUY' if order_data['size'] > 0 else 'SELL'
        report_data_dict['quantity'] = order_data['size']

        current_timestamp = int(round(time.time() * 1000))
        filled_timestamp = order_data['create_time_ms']
        append_info = '\n订单成交，成交时间 {}'.format(str(pd.to_datetime(filled_timestamp, unit='ms') + pd.Timedelta(hours=8)))
        append_info += '\n反应延时: {}'.format(current_timestamp - filled_timestamp)

        await self.reporter(report_data=report_data_dict, token=Token.ORDER_FILLED, appending_info=append_info)

    async def _handle_futures_ticker_data(self, ticker_data: dict) -> None:
        """
        根据得到的合约ticker数据，分析判断是否需要上报及其他操作
        :param ticker_data: https://www.gate.io/docs/developers/apiv4/ws/zh_CN/#server-notification
        :return:
        """
        # ticker_symbol_name = ticker_data['currency_pair']
        report_ticker_data = Token.TICKER_INFO.copy()
        report_ticker_data['symbol'] = ticker_data['contract']
        report_ticker_data['price'] = float(ticker_data['last'])

        await self.ticker_reporter(ticker_data=report_ticker_data)

    async def _handle_futures_public_trade_data(self, trade_data: dict) -> None:
        """
        上报合约共有成交数据
        :param trade_data:
        :return:
        """
        report_trade_data = Token.PUBLIC_TRADE_INFO.copy()
        # report_trade_data['event_time'] = pd.to_datetime(trade_data['create_time_ms'], unit='ms') + pd.Timedelta(hours=8)
        report_trade_data['event_time'] = trade_data['create_time_ms']      # 使用真实时间戳，数据处理由策略来完成
        report_trade_data['symbol'] = trade_data['contract']
        report_trade_data['price'] = float(trade_data['price'])

        await self.public_trade_reporter(public_trade_data=report_trade_data)

    async def _handle_futures_book_ticker_data(self, book_data: dict) -> None:
        await self.book_ticker_reporter(book_ticker_data=book_data)

    # interaction methods with Analyzer
    async def reporter(self, report_data: dict = None, token: str = None, appending_info: str = None) -> None:
        """
        与 Analyzer 通信的唯一发送渠道
        :param report_data: 需要整合的订单数据
        :param token: 上报该信息的理由，规范化令牌
        :param appending_info: 额外信息
        :return: None
        """
        order_id = report_data['id']  # todo: 是否需要洗去UI_num信息
        stg_num = self._parse_stg_num(order_id)
        if stg_num:
            report_data['status'] = token
            try:
                reporting_analyzer: Analyzer = self._running_strategies[stg_num]
            except KeyError:
                print('收到信息: '.format(report_data))
                print('{} :该策略已停止，不上报 '.format(stg_num))
                return

            if token == Token.ORDER_FILLED:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data, append_info=appending_info)
            elif token == Token.POST_SUCCESS:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data)
            elif token == Token.POC_SUCCESS:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data)
            elif token == Token.CANCEL_SUCCESS:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data)
            elif token == Token.CANCEL_POC_SUCCESS:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data)
            elif token == Token.PARTIALLY_FILLED:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data, append_info=appending_info)
            elif token == Token.ORDER_UPDATE:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data)
            elif token == Token.UNIDENTIFIED:
                pass
            elif token == Token.FAILED:
                pass
            elif token == Token.POST_FAILED:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data)
            elif token == Token.POC_FAILED:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data, append_info=appending_info)
            elif token == Token.POC_REJECTED:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data)
            elif token == Token.CANCEL_FAILED:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data, append_info=appending_info)
            elif token == Token.AMEND_POC_FAILED:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data, append_info=appending_info)
            elif token == Token.AMEND_NONEXISTENT_POC:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data, append_info=appending_info)

            elif token == Token.TEMP_TOKEN:
                # report_data_dict['status'] = token
                # await self._my_analyzer.report_receiver(recv_data_dict=report_data_dict)
                pass
            elif token is None:
                print('未定义上报理由，不上报')
            else:
                print('错误定义上报理由，不上报')

        else:
            # 非自定策略产生的order id      # todo: 用某种形式记录
            print('非策略产生的订单id: {}'.format(order_id))
            print(report_data)
            pass

    async def command_receiver(self, recv_command: dict) -> None:
        """
        终端执行函数

        该方法是 BinanceExecutor 具体执行方法的总调度
        负责执行从 Analyzer 收到的命令，与 Analyzer 通信的唯一接受渠道

        不需要等待io时，调用该函数使用 create task
        该函数只使用 await 执行操作

        :param recv_command: 收到的规范化命令
        :return: None
        """
        # todo: 未成功处理
        # if recv_command['status'] == Token.TO_POST_LIMIT:
        #     await self._post_limit_order_sync(recv_command)
        # elif recv_command['status'] == Token.TO_POST_POC:
        #     await self._post_poc_order_sync(recv_command)
        # elif recv_command['status'] == Token.TO_CANCEL:
        #     await self._post_cancel_order_sync(recv_command)
        # elif recv_command['status'] == Token.TO_POST_BATCH:
        #     await self._post_limit_batch_orders_sync(recv_command)
        # elif recv_command['status'] == Token.TO_POST_BATCH_POC:
        #     await self._post_poc_batch_orders_sync(recv_command)
        # elif recv_command['status'] == Token.TO_POST_MARKET:
        #     await self._post_market_order_sync(recv_command)
        # elif recv_command['status'] == Token.AMEND_POC_PRICE:
        #     await self._change_poc_order_price_sync(recv_command)
        # elif recv_command['status'] == Token.AMEND_POC_QTY:
        #     await self._change_poc_order_qty_sync(recv_command)
        # elif recv_command['status'] == Token.CANCEL_ALL:
        #     await self._cancel_all_orders(recv_command)
        # elif recv_command['status'] == Token.CLOSE_POSITION:
        #     await self._close_position_sync(recv_command)
        # elif recv_command['status'] == Token.TEMP_TOKEN:
        #     print('Executor 执行临时命令')
        #     pass
        # else:
        #     print('未定义命令类型，不执行')

        if recv_command['status'] == Token.TO_POST_LIMIT:
            await self._post_limit_order(recv_command)
        elif recv_command['status'] == Token.TO_POST_POC:
            await self._post_poc_order(recv_command)
        elif recv_command['status'] == Token.TO_CANCEL:
            await self._post_cancel_order(recv_command)
        elif recv_command['status'] == Token.TO_POST_BATCH:
            await self._post_limit_batch_orders(recv_command)
        elif recv_command['status'] == Token.TO_POST_BATCH_POC:
            await self._post_poc_batch_orders(recv_command)
        elif recv_command['status'] == Token.TO_POST_MARKET:
            await self._post_market_order(recv_command)
        elif recv_command['status'] == Token.AMEND_POC_PRICE:
            await self._change_poc_order_price(recv_command)
        elif recv_command['status'] == Token.AMEND_POC_QTY:
            await self._change_poc_order_qty(recv_command)
        elif recv_command['status'] == Token.CANCEL_ALL:
            await self._cancel_all_orders(recv_command)
        elif recv_command['status'] == Token.CLOSE_POSITION:
            await self._close_position(recv_command)
        elif recv_command['status'] == Token.TEMP_TOKEN:
            print('Executor 执行临时命令')
            pass
        else:
            print('未定义命令类型，不执行')

    async def ticker_reporter(self, ticker_data: dict) -> None:
        """
        向 analyzer发送 ticker信息
        :return:
        """
        # todo: 临时分辨办法，后续修改，使用 { 'eth_usdt': ['UI3stg6', ] } 字典方法分辨
        symbol_name = ticker_data['symbol']
        for each_stg_num in self._running_strategies.keys():
            each_analyzer: Analyzer = self._running_strategies[each_stg_num]
            if each_analyzer.symbol_name == symbol_name:
                await each_analyzer.ticker_receiver(recv_ticker_data=ticker_data)

    async def public_trade_reporter(self, public_trade_data: dict) -> None:
        """
        向 analyzer 发送 公有成交信息
        :param public_trade_data:
        :return:
        """
        # todo: 临时分辨方法，同上
        symbol_name = public_trade_data['symbol']
        for each_stg_num in self._running_strategies.keys():
            each_analyzer: Analyzer = self._running_strategies[each_stg_num]
            if each_analyzer.symbol_name == symbol_name:
                await each_analyzer.public_trade_receiver(recv_trade_data=public_trade_data)

    async def book_ticker_reporter(self, book_ticker_data: dict) -> None:
        # todo: 暂时不分辨，
        for each_stg_num, each_analyzer in self._running_strategies.items():
            await each_analyzer.book_ticker_receiver(recv_book_data=book_ticker_data)

    # core function methods
    async def _post_market_order_sync(self, command: dict):
        """
        市价单
        :param command:
        :return:
        """
        futures_order = FuturesOrder(
            contract=command['symbol'],
            size=int(command['quantity']) if command['side'] == 'BUY' else -int(command['quantity']),
            price='0',
            tif='ioc',  # 认为ioc代表市价单
            text='t-' + command['id']
        )
        try:
            response = self._order_client.create_futures_order(settle='usdt', futures_order=futures_order)
            # print('市价下单返回')
            # print(response)

        except GateApiException as api_error:

            print('市价下单失败，请检查 GateApiException 信息')
            print('label: {}, msg: {}\n'.format(str(api_error.label), api_error.message))

            print(command['symbol'], command['side'], command['quantity'], command['id'])

            # break
        except ApiException as e:
            print("Exception when calling FuturesApi -> create_futures_order: %s\n" % e)
        except Exception as other_error:
            print('\n### 市价下单时，出现其他未预知的错误类型 ###错误类型: {}\n错误信息: {}\n'.format
                  (str(type(other_error)), other_error))
            print(command['symbol'], command['side'], command['quantity'], command['id'])
            # break

    async def _post_market_order(self, command: dict):
        """
        异步市价下单
        :param command:
        :return:
        """
        market_order = FuturesOrder(
            contract=command['symbol'],
            size=int(command['quantity']) if command['side'] == 'BUY' else -int(command['quantity']),
            price='0',
            tif='ioc',  # ioc代表市价单
            text='t-' + command['id']
        )
        self._async_client.create_order(market_order)

    async def _post_limit_order_sync(self, command: dict):
        """
        使用异步 client 下限价单
        :param command:
        :return:
        """
        success = True
        # print('在 {} 价位挂单'.format(command['price']))
        futures_order = FuturesOrder(
            contract=command['symbol'],
            size=int(command['quantity']) if command['side'] == 'BUY' else -int(command['quantity']),
            price=np.format_float_positional(command['price'], trim='-'),
            tif='gtc',  # 认为gtc代表限价单
            text='t-' + command['id']
        )
        # for _ in range(5):
        try:
            response = self._order_client.create_futures_order(settle='usdt', futures_order=futures_order)

        except GateApiException as api_error:

            print('\n限价挂单错误\t\t\t价格: {:<12}\tid: {:<10}\t\t挂单失败，请检查 GateApiException 信息'.format(str(command['price']), command['id']))
            print('label: {}, msg: {}\n'.format(str(api_error.label), api_error.message))

            print(command['symbol'], command['side'], command['quantity'], command['price'], command['id'])

            success = False

            # break
        except ApiException as e:
            print("Exception when calling FuturesApi -> create_futures_order: %s\n" % e)
            success = False
        except Exception as other_error:
            print('\n### 下限价单时，出现其他未预知的错误类型 ###错误类型: {}\n错误信息: {}\n'.format
                  (str(type(other_error)), other_error))
            print(command['symbol'], command['side'], command['quantity'], command['price'], command['id'])
            success = False
            # break

        if not success:
            await self.reporter(report_data=command, token=Token.POST_FAILED)
            pass

    async def _post_poc_order_sync(self, command: dict):
        """
        poc挂单，返回两种失败信息
        :param command:
        :return:
        """
        success = True
        error_msg = ''

        futures_order = FuturesOrder(
            contract=command['symbol'],
            size=int(command['quantity']) if command['side'] == 'BUY' else -int(command['quantity']),
            price=np.format_float_positional(command['price'], trim='-'),
            tif='poc',
            text='t-' + command['id']
        )
        # for _ in range(5):
        try:
            response = self._order_client.create_futures_order(settle='usdt', futures_order=futures_order)

        except GateApiException as api_error:

            # 对于poc价格问题导致的挂单失败，使用特殊的返回渠道
            if api_error.label == 'ORDER_POC_IMMEDIATE':
                await self.reporter(report_data=command, token=Token.POC_REJECTED)
                return

            print('\npoc挂单错误\t\t\t价格: {:<12}\tid: {:<10}\t\t挂单失败，请检查 GateApiException 信息'.format(str(command['price']), command['id']))
            error_msg = 'label: {}, msg: {}\n'.format(str(api_error.label), api_error.message)
            print(error_msg)

            print(command['symbol'], command['side'], command['quantity'], command['price'], command['id'])

            success = False

            # break
        except ApiException as e:
            error_msg = "Exception when calling FuturesApi -> create_futures_order: {}\n".format(e)
            print(error_msg)
            success = False
        except Exception as other_error:
            error_msg = '\n### 下限价poc单时，出现其他未预知的错误类型 ###错误类型: {}\n错误信息: {}\n'.format(str(type(other_error)), other_error)
            print(error_msg)
            print(command['symbol'], command['side'], command['quantity'], command['price'], command['id'])
            success = False
            # break

        if not success:
            await self.reporter(report_data=command, token=Token.POC_FAILED, appending_info=error_msg)
            pass

    async def _post_poc_order(self, command: dict):
        """
        异步发送poc挂单请求
        :param command:
        :return:
        """
        poc_order = FuturesOrder(
            contract=command['symbol'],
            size=int(command['quantity']) if command['side'] == 'BUY' else -int(command['quantity']),
            price=np.format_float_positional(command['price'], trim='-'),
            tif='poc',
            text='t-' + command['id']
        )
        self._async_client.create_order(poc_order)

    async def _change_poc_order_price_sync(self, command: dict):
        """
        修改单个poc挂单的价格
        :param command:
        :return:
        """
        success = True
        # print('在 {} 价位挂单'.format(command['price']))
        order_patch = FuturesOrderAmendment(
            # size=None,
            price=np.format_float_positional(command['price'], trim='-')
        )
        # for _ in range(5):
        try:
            amend_response = self._order_client.amend_futures_order(
                settle='usdt',
                order_id='t-' + command['id'],
                futures_order_amendment=order_patch
            )

        except GateApiException as api_error:
            if api_error.label == 'ORDER_NOT_FOUND':
                await self.reporter(report_data=command, token=Token.AMEND_NONEXISTENT_POC)
            else:
                print('\n修改挂单错误\t\t\t价格: {:<12}\tid: {:<10}\t\t修改失败，请检查 GateApiException 信息'.format(str(command['price']), command['id']))
                print('label: {}, msg: {}\n'.format(str(api_error.label), api_error.message))
            success = False

            # break
        except ApiException as e:
            print("Exception when calling FuturesApi -> create_futures_order: %s\n" % e)
            success = False
        except Exception as other_error:
            print('\n### 修改订单时，出现其他未预知的错误类型 ###错误类型: {}\n错误信息: {}\n'.format
                  (str(type(other_error)), other_error))
            print(command['symbol'], command['side'], command['quantity'], command['price'], command['id'])
            success = False
            # break

        if not success:
            print('\n修改poc挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(command['price'], command['id']))
            # await self.reporter(report_data=command, token=Token.POC_FAILED)
            # todo: 是否需要？
            pass

    async def _change_poc_order_price(self, command: dict):
        order_patch = FuturesOrderAmendment(
            price=np.format_float_positional(command['price'], trim='-')
        )
        self._async_client.amend_order(
            order_id='t-' + command['id'],
            amend_info=order_patch
        )

    async def _change_poc_order_qty_sync(self, command: dict):
        """
        修改单个poc挂单的价格
        :param command:
        :return:
        """
        success = True
        error_msg = ''

        order_patch = FuturesOrderAmendment(
            size=int(command['quantity']),
        )
        # for _ in range(5):
        try:
            amend_response = self._order_client.amend_futures_order(
                settle='usdt',
                order_id='t-' + command['id'],
                futures_order_amendment=order_patch
            )

        except GateApiException as api_error:
            print('\n修改挂单错误\t\t\t价格: {:<12}\tid: {:<10}\t\t挂单失败，请检查 GateApiException 信息'.format(str(command['price']), command['id']))
            error_msg = 'label: {}, msg: {}\n'.format(str(api_error.label), api_error.message)
            print(error_msg)
            success = False

            # break
        except ApiException as e:
            error_msg = "Exception when calling FuturesApi -> create_futures_order: {}\n".format(e)
            print(error_msg)
            success = False
        except Exception as other_error:
            error_msg = '\n### 修改订单时，出现其他未预知的错误类型 ###错误类型: {}\n错误信息: {}\n'.format(str(type(other_error)), other_error)
            print(error_msg)
            print(command['symbol'], command['side'], command['quantity'], command['price'], command['id'])
            success = False

        if not success:
            await self.reporter(report_data=command, token=Token.AMEND_POC_FAILED, appending_info=error_msg)
            pass

    async def _change_poc_order_qty(self, command: dict):
        order_patch = FuturesOrderAmendment(
            size=int(command['quantity']),
        )
        self._async_client.amend_order(
            order_id='t-' + command['id'],
            amend_info=order_patch
        )

    async def _post_limit_batch_orders_sync(self, batch_command: dict):
        """
        目前只能用 sync client 下达批量单     # todo: 改源码？
        :param batch_command:
        :return:
        """
        # todo: 失败维护
        orders_list = batch_command['orders']
        batch_order_params = [
            # {
            #     'symbol': orders_list[index]['symbol'],
            #     'side': orders_list[index]['side'],
            #     'type': 'LIMIT',
            #     'quantity': str(orders_list[index]['quantity']),
            #     'timeInForce': 'GTC',
            #     'price': str(orders_list[index]['price']),
            #     'newClientOrderId': orders_list[index]['id'],
            FuturesOrder(
                contract=orders_list[index]['symbol'],
                size=int(orders_list[index]['quantity']) if orders_list[index]['side'] == 'BUY' else -int(orders_list[index]['quantity']),
                price=np.format_float_positional(orders_list[index]['price'], trim='-'),
                tif='gtc',
                text='t-' + orders_list[index]['id']
            ) for index, _ in enumerate(orders_list)

        ]
        response_list = self._order_client.create_batch_futures_order(settle='usdt', futures_order=batch_order_params)
        for each_index, each_res in enumerate(response_list):
            if not each_res.succeeded:
                print('{} 价位 挂单失败\nlabel: {}\ndetail: {}'.format(str(orders_list[each_index]['price']), each_res.label, each_res.detail))
                failure_info = Token.ORDER_INFO.copy()
                failure_info['symbol'] = orders_list[each_index]['symbol']
                failure_info['price'] = orders_list[each_index]['price']
                failure_info['id'] = orders_list[each_index]['id']
                await self.reporter(report_data=failure_info, token=Token.POST_FAILED)
            else:
                pass

    async def _post_poc_batch_orders_sync(self, batch_command: dict):
        """
        批量挂poc挂单
        :param batch_command:
        :return:
        """
        orders_list = batch_command['orders']
        batch_order_params = [
            FuturesOrder(
                contract=orders_list[index]['symbol'],
                size=int(orders_list[index]['quantity']) if orders_list[index]['side'] == 'BUY' else -int(orders_list[index]['quantity']),
                price=np.format_float_positional(orders_list[index]['price'], trim='-'),
                tif='poc',
                text='t-' + orders_list[index]['id']
            ) for index, _ in enumerate(orders_list)
        ]
        response_list = self._order_client.create_batch_futures_order(settle='usdt', futures_order=batch_order_params)
        for each_index, each_res in enumerate(response_list):
            if not each_res.succeeded:
                failure_info = Token.ORDER_INFO.copy()
                failure_info['symbol'] = orders_list[each_index]['symbol']
                failure_info['price'] = orders_list[each_index]['price']
                failure_info['id'] = orders_list[each_index]['id']
                # 首先检查特殊错误
                if each_res.label == 'ORDER_POC_IMMEDIATE':
                    await self.reporter(report_data=failure_info, token=Token.POC_REJECTED)
                else:
                    error_msg = 'label: {}\ndetail: {}'.format(each_res.label, each_res.detail)
                    print('{} 价位 poc挂单失败\nlabel: {}\ndetail: {}'.format(str(orders_list[each_index]['price']), each_res.label, each_res.detail))
                    await self.reporter(report_data=failure_info, token=Token.POC_FAILED, appending_info=error_msg)

    async def _post_poc_batch_orders(self, batch_command: dict):
        """
        异步批量挂单
        :param batch_command:
        :return:
        """
        orders_list = batch_command['orders']
        batch_order_params = [
            FuturesOrder(
                contract=orders_list[index]['symbol'],
                size=int(orders_list[index]['quantity']) if orders_list[index]['side'] == 'BUY' else -int(orders_list[index]['quantity']),
                price=np.format_float_positional(orders_list[index]['price'], trim='-'),
                tif='poc',
                text='t-' + orders_list[index]['id']
            ) for index, _ in enumerate(orders_list)
        ]
        self._async_client.create_batch_order(batch_order_params)

    async def _post_cancel_order_sync(self, command: dict):
        """
        异步发送取消订单请求，只需要订单id参数
        :param command:
        :return:
        """
        success = True
        error_msg = ''
        # todo: 此处用了一个临时判断，使可以使用真实id撤单
        try:
            response = self._order_client.cancel_futures_order(
                settle='usdt',
                order_id='t-' + command['id'] if '_' in command['id'] else command['id'],
            )
        except GateApiException as api_error:
            if api_error.label == 'ORDER_NOT_FOUND':
                error_msg = '{}, 不存在该挂单'.format(api_error.message)

            print('id: {} 撤单失败\n'.format(command['id']))
            print('label: {}, msg: {}\n'.format(str(api_error.label), api_error.message))
            success = False

        except ApiException as e:
            print("Exception when calling FuturesApi -> create_futures_order: %s\n" % e)
            success = False
        except Exception as other_error:
            print('\n### 撤单时，出现其他未预知的错误类型 ###错误类型: {}\n错误信息: {}\n'.format
                  (str(type(other_error)), other_error))
            success = False

        if not success:
            # test_analyzer._log_info('\n撤销挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(command['price'], command['id']))
            await self.reporter(report_data=command, token=Token.CANCEL_FAILED, appending_info=error_msg)
            pass

    async def _post_cancel_order(self, command: dict):
        self._async_client.cancel_order(
            user_order_id='t-' + command['id']
        )

    async def _post_cancel_batch_orders(self, batch_command: dict):
        """
        目前该功能无法使用
        :param batch_command:
        :return:
        """

    async def _cancel_all_orders(self, command: dict) -> None:
        """
        撤销所有挂单  todo: test client
        :param command:
        :return:
        """
        try:
            cancel_res = self._order_client.cancel_futures_orders(settle='usdt', contract=command['symbol'])
        except GateApiException as api_error:
            print('撤销所有挂单失败，请检查 GateApiException 信息')
            print('label: {}, msg: {}\n'.format(str(api_error.label), api_error.message))

            # break
        except ApiException as e:
            print("Exception when calling FuturesApi -> create_futures_order: %s\n" % e)
        except Exception as other_error:
            print('\n### 下限价单时，出现其他未预知的错误类型 ###错误类型: {}\n错误信息: {}\n'.format
                  (str(type(other_error)), other_error))
            # break

    async def _close_position_sync(self, command: dict) -> None:
        """
        平掉当前仓位，需要 command 包含数量信息
        :param command:
        :return:
        """
        symbol_name = command['symbol']
        # market_qty = float(command['quantity'])
        futures_order = FuturesOrder(
            contract=command['symbol'],
            size=0,  # 0 代表平仓
            price='0',
            close=True,
            tif='ioc',
            text='t-close_position'
        )

        try:
            close_res = self._order_client.create_futures_order(settle='usdt', futures_order=futures_order)
            if close_res.status == 'finished':
                print('成功市价平仓，数量 {} 张'.format(str(close_res.size)))
            else:
                # 实际上不会出现这种情况，而是退跳到报错
                print('买平仓失败')

        except GateApiException as api_error:

            print('市价平仓失败，请检查 GateApiException 信息')
            print('label: {}, msg: {}\n'.format(str(api_error.label), api_error.message))
        except ApiException as e:
            print("Exception when calling FuturesApi -> create_futures_order: %s\n" % e)
        except Exception as other_error:
            print('\n### 市价平仓时，出现其他未预知的错误类型 ###错误类型: {}\n错误信息: {}\n'.format
                  (str(type(other_error)), other_error))

    async def _close_position(self, command: dict) -> None:
        close_order = FuturesOrder(
            contract=command['symbol'],
            size=0,  # 0 代表平仓
            price='0',
            close=True,
            tif='ioc',
            text='t-close_position'
        )
        self._async_client.create_order(close_order)

    # tool methods
    def _parse_stg_num(self, client_order_id: str) -> Union[str | bool]:
        """
        从自定义的订单id中解析出 stg_num
        :param client_order_id: stg23_00058BUY
        :return: stg编号，若非自定的订单id 则返回False
        """
        stg_num = client_order_id.split('_')[0]
        if stg_num[:self.STG_SERIES_LEN] == self.STG_SERIES:
            return stg_num
        else:
            return False


if __name__ == '__main__':
    # test codes
    executor = GateFuturesExecutor()
    res = executor.read_api_params('../gate_api.txt')
    print(res)
    # noinspection PyProtectedMember
    print(executor._api_secret)
