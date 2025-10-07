# -*- coding: utf-8 -*-
# @Time : 2023/9/5 9:31
# @Author : 
# @File : test_save_order_stream.py 
# @Software: PyCharm
import asyncio
import json
from pathlib import Path

from gate_ws import Configuration, Connection, WebSocketResponse
from gate_ws.futures import FuturesOrderChannel

api_key_gate = 'your_key'
api_secret_gate = 'your_secret'

# Define your callback function on message received
def print_message(conn: Connection, response: WebSocketResponse):
    if response.error:
        print('error returned: ', response.error)
        conn.close()
        return
    print(response.result)
    with open('order_data_FITFI.json', 'a') as f:
        json.dump(response.result, f)
        f.write(",\n")


async def main():
    # Create JSON file if not exists
    if not Path('order_data_FITFI.json').is_file():
        with open('order_data_FITFI.json', 'w') as f:
            f.write("[\n")

    # Initialize default connection
    conn = Connection(Configuration(app='futures', api_key=api_key_gate, api_secret=api_secret_gate))

    # Subscribe to the channel
    channel = FuturesOrderChannel(conn, print_message)
    channel.subscribe(['account_number', 'FITFI_USDT'])

    # Start the client
    await conn.run()

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    loop.run_until_complete(main())
    loop.close()
    # Close the JSON array
    with open('order_data_FITFI.json', 'a') as f:
        f.write("]\n")
