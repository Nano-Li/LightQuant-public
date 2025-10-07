# -*- coding: utf-8 -*-
# @Time : 2023/1/26 22:03 
# @Author : 
# @File : GateMarginExecutor.py 
# @Software: PyCharm
import re
import sys
import time
import json
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
from gate_api import Order, OrderPatch
import gate_ws
from gate_ws.spot import SpotOrderChannel, SpotTickerChannel


class GateMarginExecutor(Executor):
    """
    Gate执行者类，负责对接到Gate api的具体操作
    处理U本位合约的socket信息，一个类实例处理一个U本位合约的交易数据

    """
    NAME = 'Gate 现货'

    # noinspection PyTypeChecker
    def __init__(self) -> None:
        super(GateMarginExecutor, self).__init__()

        self._client = None
        self._syncclient = None  # 非异步client

        # noinspection PyTypeChecker
        self._order_client: gate_api.SpotApi = None
        # noinspection PyTypeChecker
        self._margin_client: gate_api.MarginApi = None
        # 钱包接口
        # noinspection PyTypeChecker
        self._wallet_client: gate_api.WalletApi = None
        self._websocket_client_order: SpotOrderChannel = None
        self._websocket_client_ticker: SpotTickerChannel = None
        # noinspection PyTypeChecker
        self._websocket_connection: gate_ws.Connection = None
        # 该变量用于确保只创建一次连接
        self._connected = False

        self._api_key = None
        self._api_secret = None
        self._user_id = 0

        # 第一次连接的测试变量 # todo: not useful
        self._first_connect_test = False
        self._api_param_validate = False

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
        # todo: 类提示, mainwindow
        super().initialize(main_UI)
        self._recorder = LogRecorder()
        self._recorder.open_file('GateExecutor')
        print('初始化gate连接')
        # self._event_loop.run_until_complete(self.create_connection())
        # 不使用 run_until_complete 因为这会导致eventloop变成关闭状态
        asyncio.create_task(self.create_connection())
        asyncio.create_task(self.engine_start())

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
            self._order_client = gate_api.SpotApi(gate_api_client)
            self._margin_client = gate_api.MarginApi(gate_api_client)
            self._wallet_client = gate_api.WalletApi(gate_api_client)

            ws_cfg = gate_ws.Configuration(api_key=self._api_key, api_secret=self._api_secret)
            self._websocket_connection = gate_ws.Connection(ws_cfg)
            self._websocket_client_order = SpotOrderChannel(conn=self._websocket_connection, callback=self._user_socket_receiver)
            self._websocket_client_ticker = SpotTickerChannel(conn=self._websocket_connection, callback=self._ticker_socket_receiver)
            print('client创建成功')

            # todo: gate connection error test
            # success = await self._test_api_validation()

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
        self._connected = False
        self._websocket_connection.close()

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

        print('结束gate连接')

    async def _test_api_validation(self) -> bool:
        """
        gate 交易所特有方法
        因为如果输入错误api参数，只有在开启单个合约数据监听时才能检测到
        因此在最开始连接api时，尝试订阅btc_usdt用户数据，以达到检测目的
        :return:
        """
        api_validate = False
        self._first_connect_test = True
        test_contract = 'BTC_USDT'
        self.start_single_contract_order_subscription(test_contract)
        # todo: 使用循环等待一段时间的方法测试连接，也许有更好方法，暂时没有较好办法测试api参数正确性，该方法不使用
        for _ in range(300):
            if not self._first_connect_test:
                print('{} times looped'.format(_))
                if self._api_param_validate:
                    api_validate = True
                else:
                    api_validate = False
                await self._websocket_connection.close()
                break
            await asyncio.sleep(0.1)

        return api_validate

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
            info_res = self._order_client.get_currency_pair(currency_pair=symbol_name)
        except GateApiException as ex:
            if ex.label == 'INVALID_CURRENCY':
                return None
            else:
                raise Exception('查询合约信息错误')

        symbol_info_dict['price_min_step'] = float('1e-{}'.format(info_res.precision))
        symbol_info_dict['qty_min_step'] = float('1e-{}'.format(info_res.amount_precision))
        symbol_info_dict['min_notional'] = 0 if info_res.min_quote_amount is None else float(info_res.min_quote_amount)
        symbol_info_dict['min_order_qty'] = 0 if info_res.min_base_amount is None else float(info_res.min_base_amount)

        return symbol_info_dict

    async def get_current_price(self, symbol_name: str) -> float:
        """
        在开始策略时，被 Analyzer 调用一次
        获取合约当前价格
        :param symbol_name: 合约名
        :return:
        """
        ticker_res = self._order_client.list_tickers(currency_pair=symbol_name)
        return float(ticker_res[0].last)

    async def get_current_asset_qty(self, symbol_name: str) -> float:
        """
        获取当前账户中有多少现货
        :return:
        """
        info_res = self._margin_client.list_margin_accounts(currency_pair=symbol_name)
        all_qty = float(info_res[0].base.available) + float(info_res[0].base.locked)
        return all_qty

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

            trade_fee['maker_fee'] = float(fee_res.maker_fee)
            trade_fee['taker_fee'] = float(fee_res.taker_fee)

        except GateApiException as ex:
            print("获取交易手续费失败, label: %s, message: %s\n" % (ex.label, ex.message))

        return trade_fee

    # ## ==================================== all streams ==================================== ## #
    async def _user_socket_receiver(self, conn: gate_ws.Connection, order_res: gate_ws.WebSocketResponse) -> None:
        """
        不断监听服务器返回的用户数据
        :return:
        """
        if order_res.error:
            print('gate服务器返回报错信息: ', order_res.error)
            return

        order_info_dict = json.loads(order_res.body)
        if order_info_dict['event'] == 'update':
            result_list = order_info_dict['result']
            for _, each_result in enumerate(result_list):
                await self._handle_user_spot_data(each_result)

        elif order_info_dict['event'] == 'subscribe':
            print('成功订阅合约订单信息')

        elif order_info_dict['event'] == 'unsubscribe':
            print('成功取消合约订阅信息')

        else:
            print('其他未记录的websocket事件类型:')
            print(str(order_info_dict))

    def start_single_contract_order_subscription(self, contract_name: str) -> None:
        """
        每创建一个策略，需要开启监听一个合约信息
        :param contract_name:
        :return:
        """
        # try:
        self._websocket_client_order.subscribe([contract_name])
        # except Exception as ex:
        #     print(ex)
        #     print(type(ex))
        print('开启合约数据监听 {}'.format(contract_name))

    def stop_single_contract_order_subscription(self, contract_name: str) -> None:
        """
        策略结束后，停止监听信息
        :param contract_name:
        :return:
        """
        self._websocket_client_order.unsubscribe([contract_name])
        print('关闭合约数据监听 {}'.format(contract_name))

    async def _ticker_socket_receiver(self, conn: gate_ws.Connection, ticker_res: gate_ws.WebSocketResponse) -> None:
        """
        持续获得从gate服务器订阅的合约ticker信息，即最新价格
        :return:
        """
        if ticker_res.error:
            print('gate服务器返回报错信息: ', ticker_res.error)
            return

        ticker_info_dict = json.loads(ticker_res.body)
        if ticker_info_dict['event'] == 'update':
            symbol_ticker = ticker_info_dict['result']
            await self._handle_spot_ticker_data(symbol_ticker)

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
        self._websocket_client_ticker.subscribe([contract_name])
        print('开启合约ticker数据监听 {}'.format(contract_name))

    def stop_single_contract_ticker_subscription(self, contract_name: str) -> None:
        """
        关闭一个合约ticker信息
        :param contract_name:
        :return:
        """
        self._websocket_client_ticker.unsubscribe([contract_name])
        print('关闭合约ticker数据监听 {}'.format(contract_name))

    # ## ==================================== all streams ==================================== ## #

    # handling data methods
    async def _handle_user_spot_data(self, order_data: dict) -> None:
        """
        根据得到的用户数据，分析判断是否需要上报及其他操作

        负责将 user_data 整合为规范化的上报信息，并上报

        订单状态包括
            put         新挂单
            finish      成交或撤单

        操作：
            收到挂单成交的信息，交给联络员上报
            收到挂单成功和撤单成功的信息，自行处理

        :param order_data:
        :return:
        """
        order_status = order_data['event']

        report_data_dict = Token.ORDER_INFO.copy()
        report_data_dict['symbol'] = order_data['currency_pair']
        report_data_dict['id'] = order_data['text'][2:]
        report_data_dict['price'] = order_data['price']
        report_data_dict['side'] = order_data['side'].upper()
        report_data_dict['quantity'] = order_data['amount']

        if order_status == 'finish':
            if order_data['filled_total'] == '0':
                if order_data['time_in_force'] == 'poc':
                    await self.reporter(report_data=report_data_dict, token=Token.CANCEL_POC_SUCCESS)
                else:
                    await self.reporter(report_data=report_data_dict, token=Token.CANCEL_SUCCESS)
            else:
                # 挂单成交，需要上报
                current_timestamp = int(round(time.time() * 1000))
                filled_timestamp = int(order_data['update_time_ms'])
                # filled_time = pd.to_datetime(filled_timestamp, unit='ms')
                append_info = '\n订单成交，成交时间\t{}'.format(str(pd.to_datetime(filled_timestamp, unit='ms')))
                # print('\n订单成交，成交时间 {}'.format(str(pd.to_datetime(filled_timestamp, unit='ms'))))
                append_info += '\n反应延时: {}'.format(current_timestamp - filled_timestamp)
                # print('反应延时: {}'.format(current_timestamp - filled_timestamp))
                # print(json.dumps(user_data))

                await self.reporter(report_data=report_data_dict, token=Token.ORDER_FILLED, appending_info=append_info)
        elif order_status == 'put':
            # print('收到挂单成功信息')
            # print('收到挂单成功信息\t\t价格: {:<12}\tid: {:<10}'.format(user_data['o']['p'], user_data['o']['c']))
            # 已有判断挂单成功的方法(request 返回)，暂不需要使用
            # print('撮合时间: {}'.format(str(user_data['T'])))
            # print('事件时间: {}'.format(str(user_data['E'])))
            if order_data['time_in_force'] == 'poc':
                await self.reporter(report_data=report_data_dict, token=Token.POC_SUCCESS)
            else:
                await self.reporter(report_data=report_data_dict, token=Token.POST_SUCCESS)
            # todo: 自己处理该信息
            pass
        # elif order_status == 'cancelled':
        #     print('收到撤单成功信息')
        elif order_status == 'update':
            # print('\n订单部分成交!!!')
            # print(json.dumps(user_data))
            # todo: 上报
            append_info = 'left={}'.format(order_data['left'])
            await self.reporter(report_data=report_data_dict, token=Token.PARTIALLY_FILLED, appending_info=append_info)
            # print('订单更新: _update, 需要检查')
            # print(order_data)
        else:
            print('暂未处理的订单状态: {}'.format(order_status))
            print(order_data)

    async def _handle_spot_ticker_data(self, ticker_data: dict) -> None:
        """
        根据得到的合约ticker数据，分析判断是否需要上报及其他操作
        :param ticker_data: https://www.gate.io/docs/developers/apiv4/ws/zh_CN/#server-notification
        :return:
        """
        # ticker_symbol_name = ticker_data['currency_pair']
        report_ticker_data = Token.TICKER_INFO.copy()
        report_ticker_data['symbol'] = ticker_data['currency_pair']
        report_ticker_data['price'] = float(ticker_data['last'])

        await self.ticker_reporter(ticker_data=report_ticker_data)

    # interaction methods with Analyzer
    async def reporter(self, report_data: dict = None, token: str = None, appending_info: str = None) -> None:
        """
        与 Analyzer 通信的唯一发送渠道
        :param report_data: 规范化的订单数据
        :param token: 上报该信息的理由，规范化令牌
        :param appending_info: 额外信息
        :return: None
        """
        order_id = report_data['id']
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
            elif token == Token.UNIDENTIFIED:
                pass
            elif token == Token.FAILED:
                pass
            elif token == Token.POST_FAILED:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data)
            elif token == Token.POC_FAILED:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data)
            elif token == Token.CANCEL_FAILED:
                await reporting_analyzer.report_receiver(recv_data_dict=report_data)

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
        if recv_command['status'] == Token.TO_POST_LIMIT:
            await self._post_limit_order(recv_command)
        elif recv_command['status'] == Token.TO_POST_POC:
            await self._post_poc_order(recv_command)
        elif recv_command['status'] == Token.TO_CANCEL:
            await self._post_cancel_order(recv_command)
        elif recv_command['status'] == Token.TO_POST_BATCH:
            await self._post_limit_batch_orders(recv_command)
        elif recv_command['status'] == Token.TO_POST_MARKET:
            await self._post_market_order(recv_command)
        elif recv_command['status'] == Token.AMEND_POC_PRICE:
            await self._change_poc_order_price(recv_command)
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

    # core function methods
    async def _post_market_order(self, command: dict):
        """
        使用异步 client 下市价单
        :param command:
        :return:
        """
        # todo: 此处的计算可能会存在问题，精度等
        current_price = await self.get_current_price(command['symbol'])
        delta_price = current_price / 8

        order_instance = Order(
            # 此处使用偏移价位的限价单，实现市价单的功能，并能控制交易数量
            currency_pair=command['symbol'],
            type='limit',
            account='margin',
            side=command['side'].lower(),
            amount=np.format_float_positional(command['quantity'], trim='-'),
            price=str(current_price + delta_price) if command['side'] == 'BUY' else str(current_price - delta_price),
            time_in_force='gtc',
            text='t-' + command['id']
        )
        # print('\n市价单', order_instance)
        try:
            response = self._order_client.create_order(order_instance)
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

    async def _post_limit_order(self, command: dict):
        """
        使用异步 client 下限价单
        :param command:
        :return:
        """
        success = True
        print('谁 tm 让你挂gtc挂单了\t{}\t{}'.format(command['price'], command['id']))
        order_instance = Order(
            currency_pair=command['symbol'],
            type='limit',
            account='margin',
            side=command['side'].lower(),
            amount=np.format_float_positional(command['quantity'], trim='-'),
            price=str(command['price']),
            time_in_force='gtc',
            text='t-' + command['id']
        )
        # for _ in range(5):
        try:
            response = self._order_client.create_order(order_instance)

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
            # test_analyzer._log_info('\n限价挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(command['price'], command['id']))
            await self.reporter(report_data=command, token=Token.POST_FAILED)
            pass

    async def _post_poc_order(self, command: dict):
        """
        使用异步 client 下限价单
        :param command:
        :return:
        """
        success = True
        # print('在 {} 价位挂单'.format(command['price']))
        order_instance = Order(
            currency_pair=command['symbol'],
            type='limit',
            account='margin',
            side=command['side'].lower(),
            amount=np.format_float_positional(command['quantity'], trim='-'),
            price=str(command['price']),
            time_in_force='poc',
            text='t-' + command['id']
        )
        # for _ in range(5):
        try:
            response = self._order_client.create_order(order_instance)

        except GateApiException as api_error:
            if api_error.label == 'POC_FILL_IMMEDIATELY':
                print('\npoc挂单价格错位\t\t价格: {:<12}\tid: {:<10}'.format(command['price'], command['id']))

                print('尝试获取当前价格')
                # current_price = self.get_current_price(symbol_name=command['symbol'])
                # print('\n事后当前最新价格\t\t价格: {:<12}'.format(current_price))
                pass

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
            # test_analyzer._log_info('\n限价挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(command['price'], command['id']))
            await self.reporter(report_data=command, token=Token.POC_FAILED)
            pass

    async def _change_poc_order_price(self, command: dict):
        """
        修改poc订单
        :param command:
        :return:
        """
        success = True
        # print('在 {} 价位挂单'.format(command['price']))
        order_patch = OrderPatch(
            # amount=None,
            price=str(command['price'])
        )
        # for _ in range(5):
        try:
            amend_response = self._order_client.amend_order(
                order_id='t-' + command['id'],
                currency_pair=command['symbol'],
                order_patch=order_patch
            )

        except GateApiException as api_error:

            print('\n修改挂单错误\t\t\t价格: {:<12}\tid: {:<10}\t\t挂单失败，请检查 GateApiException 信息'.format(str(command['price']), command['id']))
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

    async def _post_limit_batch_orders(self, batch_command: dict):
        """
        目前只能用 sync client 下达批量单     # todo: 改源码？
        :param batch_command:
        :return:
        """
        # todo: 临时改成poc，后续需要修改框架
        orders_list = batch_command['orders']
        batch_order_params = [
            # FuturesOrder(
            #     contract=orders_list[index]['symbol'],
            #     size=int(orders_list[index]['quantity']) if orders_list[index]['side'] == 'BUY' else -int(orders_list[index]['quantity']),
            #     price=np.format_float_positional(orders_list[index]['price'], trim='-'),
            #     tif='gtc',
            #     text='t-' + orders_list[index]['id']
            # ) for index, _ in enumerate(orders_list)
            Order(
                currency_pair=orders_list[index]['symbol'],
                type='limit',
                account='margin',
                side=orders_list[index]['side'].lower(),
                amount=np.format_float_positional(orders_list[index]['quantity'], trim='-'),
                price=str(orders_list[index]['price']),
                time_in_force='poc',
                text='t-' + orders_list[index]['id']
            ) for index, _ in enumerate(orders_list)

        ]
        response_list = self._order_client.create_batch_orders(batch_order_params)
        for each_index, each_res in enumerate(response_list):
            if not each_res.succeeded:
                print('{} 价位 挂单失败\nlabel: {}\ndetail: {}'.format(str(orders_list[each_index]['price']), each_res.label, each_res.message))
                # test_analyzer._log_info('\n批量挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(orders_list[each_index]['price'], orders_list[each_index]['id']))
                failure_info = Token.ORDER_INFO.copy()
                failure_info['symbol'] = orders_list[each_index]['symbol']
                failure_info['price'] = orders_list[each_index]['price']
                failure_info['id'] = orders_list[each_index]['id']
                await self.reporter(report_data=failure_info, token=Token.POC_FAILED)
            else:
                pass

    async def _post_cancel_order(self, command: dict):
        """
        撤销单个订单
        :param command:
        :return:
        """
        success = True
        try:
            response = self._order_client.cancel_order(
                order_id='t-' + command['id'],
                currency_pair=command['symbol'],
                account='margin'
            )
        except GateApiException as api_error:

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
            await self.reporter(report_data=command, token=Token.CANCEL_FAILED)
            pass

    async def _post_cancel_batch_orders(self, batch_command: dict):
        """
        目前暂时不使用该功能
        :param batch_command:
        :return:
        """
        pass

    async def _cancel_all_orders(self, command: dict) -> None:
        """
        撤销所有挂单  todo: test client
        :param command:
        :return:
        """
        try:
            cancel_res = self._order_client.cancel_orders(command['symbol'], account='margin')
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

    async def _close_position(self, command: dict) -> None:
        """
        平掉当前仓位，需要 command 包含数量信息
        :param command:
        :return:
        """
        # 传入了数量及方向信息，直接调用市价函数
        await self._post_market_order(command)

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
    executor = GateMarginExecutor()
    res = executor.read_api_params('../gate_api.txt')
    print(res)
    # noinspection PyProtectedMember
    print(executor._api_secret)
