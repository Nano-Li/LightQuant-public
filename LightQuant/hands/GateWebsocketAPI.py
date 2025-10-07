# -*- coding: utf-8 -*-
# @Time : 2024/1/13 22:47
# @Author : 
# @File : GateWebsocketAPI.py
# @Software: PyCharm
import ssl
import time
import json
import hmac
import asyncio
import hashlib
import logging
import websockets
from gate_ws.client import Configuration, Connection, WebSocketRequest
from gate_api import FuturesOrder, FuturesOrderAmendment


class GateWebsocketApiError(Exception):

    def __init__(self, label, message):
        self.label = label
        self.message = message

    def __str__(self):
        return 'code: %d, message: %s' % (self.label, self.message)


class WebSocketApiResponse(object):

    def __init__(self, response: str):
        res_info: dict = json.loads(response)

        if res_info.get('request_id'):
            self.request_id = res_info.get('request_id')

            self.header: dict = res_info.get('header')
            self.status_code = self.header.get('status')
            self.response_time = self.header.get('response_time')
            self.channel = self.header.get('channel')
            # self.event = self.header.get('api')
            # self.client_id = self.header.get('client_id')

            self.data: dict = res_info.get('data')
            self.error = None
            self.result = None
            if self.data.get('errs'):
                self.error = GateWebsocketApiError(self.data['errs']['label'], self.data['errs']['message'])
            else:
                self.result = self.data.get('result')

        else:
            self.channel = res_info.get('channel')


class WebSocketApiRequest(WebSocketRequest):

    pass


class ClientConnection(Connection):

    async def _read(self, conn: websockets.WebSocketClientProtocol):
        async for msg in conn:
            print('\n收到服务器信息: \n', msg, '\n', type(msg))
            response = WebSocketApiResponse(msg)
            callback = self.channels.get(response.channel, self.cfg.default_callback)
            if callback is not None:
                if asyncio.iscoroutinefunction(callback):
                    # 注意这里是使用创建协程方法而不是await方法执行回调函数
                    self.event_loop.create_task(callback(self, response))
                else:
                    self.event_loop.run_in_executor(self.cfg.pool, callback, self, response)
            else:
                print('\ncall back function not defined!\n')


class FuturesAsyncClient:
    # todo: 使用自己的风格
    name = 'api'
    require_auth = False

    def __init__(self, conn: Connection, callback=None):
        self.conn = conn
        self.callback = callback
        self.cfg = self.conn.cfg
        self.conn.register(self.name, callback)         # todo: 这行代码没用，只是定义了event

    def message(self, channel, req_param, time_now):
        message = "%s\n%s\n%s\n%d" % ("api", channel, req_param, time_now)
        return message

    def login(self, key: str, secret: str) -> None:
        channel_login = "futures.login"
        req_param = ""
        time_now = int(time.time())

        req_login_payload = {
            "api_key": key,
            "signature": hmac.new(secret.encode("utf8"), self.message(channel=channel_login, req_param=req_param, time_now=time_now).encode("utf8"),
                                  hashlib.sha512).hexdigest(),
            "timestamp": "%d" % time_now,
            "req_id": "self_sdk_id"
        }
        print(req_login_payload)

        # noinspection PyTypeChecker
        self.conn.send_msg(WebSocketRequest(
            cfg=self.cfg,
            channel=channel_login,
            event=self.name,
            payload=req_login_payload,
            require_auth=False
        ))

    def create_order(self, order_info: FuturesOrder):
        if not isinstance(order_info, FuturesOrder):
            raise Exception

        req_payload = {
            "req_id": "00006",
            "req_param": {
                "contract": order_info.contract,
                "size": order_info.size,
                "price": order_info.price,
                "tif": order_info.tif,
                "text": order_info.text
            },
            # "req_param": {
            #     "contract": "BTC_USDT",
            #     "size": -2,
            #     "price": "46000.0",
            #     "tif": "poc",
            #     "text": 't-test_poc_order'
            # }
        }

        # noinspection PyTypeChecker
        self.conn.send_msg(WebSocketRequest(
            cfg=self.cfg,
            channel='futures.order_place',
            event=self.name,
            payload=req_payload,
            require_auth=self.require_auth
        ))

    def amend_order(self, amend_text: str, amend_info: FuturesOrderAmendment):
        if not isinstance(amend_info, FuturesOrderAmendment):
            raise Exception
        # todo: 需要根据情况选择价格还是数量
        amend_payload = {
            "req_id": "test-request-ws",
            "req_param": {
                "order_id": amend_text,
                "price": amend_info.price
            },
        }

        self.conn.send_msg(WebSocketRequest(
            cfg=self.cfg,
            channel='futures.order_amend',
            event=self.name,
            payload=amend_payload,
            require_auth=self.require_auth
        ))


