# -*- coding: utf-8 -*-
# @Time : 2023/1/9 8:44 
# @Author : 
# @File : test_trade_stream.py 
# @Software: PyCharm
import asyncio

from gate_ws import Configuration, Connection, WebSocketResponse
from gate_ws.spot import SpotPublicTradeChannel
from gate_ws.futures import FuturesUserTradesChannel, FuturesOrderChannel

api_key_gate = 'your_key'
api_secret_gate = 'your_secret'


# define your callback function on message received
def print_message(conn: Connection, response: WebSocketResponse):
    if response.error:
        print('error returned: ', response.error)
        conn.close()
        return
    print(response.result)


async def main():
    # initialize default connection, which connects to spot WebSocket V4
    # it is recommended to use one conn to initialize multiple channels
    conn = Connection(Configuration(app='futures', api_key=api_key_gate, api_secret=api_secret_gate))

    # subscribe to any channel you are interested into, with the callback function
    channel = FuturesOrderChannel(conn, print_message)
    channel.subscribe(['account_number', 'JASMY_USDT'])

    # start the client
    await conn.run()


if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    loop.run_until_complete(main())
    loop.close()
