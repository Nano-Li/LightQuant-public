# -*- coding: utf-8 -*-
# @Time : 2023/1/17 9:27 
# @Author : 
# @File : main.py 
# @Software: PyCharm
"""
整个项目的主程序，运行该程序
"""
import os
import sys
import asyncio

import time
import hmac
import hashlib
import base64
import requests
import urllib.parse

import logging
import traceback
import qdarkstyle
from quamash import QEventLoop
from PyQt5 import QtCore, QtGui
from PyQt5.QtWidgets import QApplication
from qdarkstyle.light.palette import LightPalette
from LightQuant.ui.MainWindow import FinalWindow
from LightQuant.sysout import PrintWindow


# 创建日志记录器
logger = logging.getLogger('trade_logger')
logger.setLevel(logging.ERROR)
# 创建写入文件处理器
file_handler = logging.FileHandler('system_err.log', encoding='utf-8')
file_handler.setLevel(logging.ERROR)
file_handler.setFormatter(logging.Formatter('\n\n%(asctime)s - %(levelname)s:%(name)s:%(message)s'))
# 创建输出控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.ERROR)
console_handler.setFormatter(logging.Formatter('\n\n%(asctime)s - %(levelname)s:%(name)s:%(message)s'))
# 将两个处理器添加到日志记录器
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# 控制消息发送频率
last_send_time = 0


def can_send_message():
    global last_send_time
    current_time = int(time.time())
    # 如果当前时间和最后一次发送的时间差大于等于10分钟，返回True
    if current_time - last_send_time >= 300:  # 600秒等于10分钟
        last_send_time = current_time  # 更新最后一次发送时间
        return True
    return False


def send_dingding_message(message):
    base_url = 'https://oapi.dingtalk.com/robot/send'
    access_token = 'your_dingding_token'
    # gen secret url
    timestamp = str(round(time.time() * 1000))
    secret = 'your_dingding_secret'
    secret_enc = secret.encode('utf-8')
    string_to_sign = '{}\n{}'.format(timestamp, secret)
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))

    webhook_url = f'{base_url}?access_token={access_token}&timestamp={timestamp}&sign={sign}'

    headers = {'Content-Type': 'application/json;charset=utf-8'}
    json_data = {
        "msgtype": "text",
        "text": {
            "content": message
        }
    }
    response = requests.post(webhook_url, json=json_data, headers=headers)
    return response


# noinspection PyProtectedMember
def handle_trade_error(loop, context):
    # 重写事件循环异常处理机制
    message = context.get('message')
    if not message:
        message = 'Unhandled exception in event loop'
    exception = context.get('exception')
    if exception is not None:
        exc_info = (type(exception), exception, exception.__traceback__)
    else:
        exc_info = False
    if 'source_traceback' not in context and loop._current_handle is not None and loop._current_handle._source_traceback:
        context['handle_traceback'] = loop._current_handle._source_traceback
    log_lines = [message]
    for key in sorted(context):
        if key in {'message', 'exception'}:
            continue
        value = context[key]
        if key == 'source_traceback':
            tb = ''.join(traceback.format_list(value))
            value = 'Object created at (most recent call last):\n'
            value += tb.rstrip()
        elif key == 'handle_traceback':
            tb = ''.join(traceback.format_list(value))
            value = 'Handle created at (most recent call last):\n'
            value += tb.rstrip()
        else:
            value = repr(value)
        log_lines.append(f'{key}: {value}')

    logger.error('\n交易任务出错\n'.join(log_lines), exc_info=exc_info)
    if can_send_message():
        # print('do not send')
        send_dingding_message('Main server trading error detected! plz check server and account status!')
    else:
        print('detected server error, do not send msg')


if __name__ == '__main__':
    app = QApplication(sys.argv)

    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    # app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt5', palette=LightPalette()))
    # app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt5'))
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)

    main_loop = QEventLoop(app)
    main_loop.set_exception_handler(handle_trade_error)
    asyncio.set_event_loop(main_loop)
    # noinspection PyProtectedMember, PyUnresolvedReferences
    asyncio.events._set_running_loop(main_loop)
    trade_window = FinalWindow()
    print_window = PrintWindow()
    trade_window.show()
    print_window.show()

    print(f'当前进程PID: {os.getpid()}')

    main_loop.run_forever()
    app.exec()

