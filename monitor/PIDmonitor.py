# -*- coding: utf-8 -*-
# @Time : 2024/3/14 9:43
# @Author : 
# @File : PIDmonitor.py
# @Software: PyCharm
import hmac
import hashlib
import base64
import requests
import urllib.parse

import sys
import psutil
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QTextEdit, QLineEdit, QPushButton, QVBoxLayout, QWidget, QMessageBox)
from PyQt5.QtCore import QThread, pyqtSignal
import qdarkstyle


def send_dingding_message(message):
    base_url = 'https://oapi.dingtalk.com/robot/send'
    access_token = '841306def13107d4810fa9a39d66658de2d30d3cd348ef705d5a789ed0c6daa5'
    # gen secret url
    timestamp = str(round(time.time() * 1000))
    secret = 'SEC09d6a6decae4b8117f7470f98ba2a67bdb084618ae42c1f035912d3337d46c51'
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


class MonitorThread(QThread):
    update_signal = pyqtSignal(str)

    def __init__(self, pid):
        super(MonitorThread, self).__init__()
        self.pid = pid

    def run(self):
        if not self.check_process(self.pid):
            self.update_signal.emit("错误：进程不在运行。")
            return

        self.update_signal.emit(f"开始监控进程 {self.pid}。")
        while True:
            if not self.check_process(self.pid):
                send_dingding_message('system PID stopped! plz check server and trading status')
                self.update_signal.emit(f"进程 {self.pid} 已停止运行。")
                break
            else:
                time.sleep(5)

    @staticmethod
    def check_process(pid):
        """检查指定PID的进程是否存在"""
        try:
            psutil.Process(pid)
            return True
        except psutil.NoSuchProcess:
            return False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.monitor_thread = None
        self.setWindowTitle('进程监控')
        self.setGeometry(100, 100, 600, 400)

        layout = QVBoxLayout()
        self.pid_input = QLineEdit()
        self.pid_input.setPlaceholderText("请输入进程PID")
        self.start_button = QPushButton("开始监控")
        self.start_button.clicked.connect(self.start_monitoring)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)

        layout.addWidget(self.pid_input)
        layout.addWidget(self.start_button)
        layout.addWidget(self.log_text)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self._is_monitoring = False

    def start_monitoring(self):
        if self._is_monitoring:
            self.update_log('正在执行监控任务')
            return
        try:
            pid = int(self.pid_input.text())
            if pid <= 0:
                self.update_log('PID 应该是一个正整数。')
                return
        except ValueError:
            self.update_log('输入错误')
            return
        self.monitor_thread = MonitorThread(pid)
        self.monitor_thread.update_signal.connect(self.update_log)
        self.monitor_thread.start()

    def update_log(self, message):
        if '开始监控' in message:
            self._is_monitoring = True
        self.log_text.append(message)

    def closeEvent(self, event):
        # 弹出确认关闭的对话框
        reply = QMessageBox.question(self, '确认', '确认关闭进程监控？', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            event.accept()  # 接受关闭事件，关闭窗口
            sys.exit(-1)
        else:
            event.ignore()  # 忽略关闭事件，窗口不会关闭


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec_())
