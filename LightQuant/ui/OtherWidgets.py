# -*- coding: utf-8 -*-
# @Time : 2023/1/17 10:10 
# @Author : 
# @File : OtherWidgets.py 
# @Software: PyCharm
from PyQt5 import sip
from PyQt5.QtGui import QFont, QCloseEvent
from PyQt5.QtCore import Qt, pyqtSignal, pyqtBoundSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QBoxLayout, QTabBar, QDialog, QComboBox, QGroupBox, QListView, QPlainTextEdit,
    QLabel, QPushButton, QFrame, QScrollArea, QTabWidget, QTableWidget, QGraphicsView, QTextBrowser, QLineEdit, QCheckBox
)
# from PyQt5 import Qt
from LightQuant.Executor import Executor
from .WindowToken import WindowToken as WTOKEN


class CreateUIWindow(QDialog):
    # noinspection PyTypeChecker
    def __init__(self):
        super().__init__()
        # self.setWindowModality(Qt.ApplicationModal)

        self.btn_confirm: QPushButton = None
        self.api_selector: QComboBox = None

        self._init_setting()

    def _init_setting(self):
        self.setWindowTitle('添加交易界面')
        self.setFixedSize(280, 250)

        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(14)

        group_frame = QGroupBox('选择交易接口', self)
        group_frame.setFont(temp_font)
        group_frame.setGeometry(30, 30, 220, 190)
        # group_frame.setAlignment(Qt.AlignRight)       # todo: 标题居中不起作用?
        group_frame.setStyleSheet("QGroupBox::title {margin-top:6px; subcontrol-position: top center; left: 0px;}")

        # temp_font.setPixelSize(14)
        self.api_selector = QComboBox(group_frame)
        self.api_selector.setFont(temp_font)
        self.api_selector.setGeometry(50, 50, 120, 30)
        self.api_selector.setEditable(True)
        self.api_selector.lineEdit().setAlignment(Qt.AlignCenter)
        self.api_selector.lineEdit().setReadOnly(True)
        self.api_selector.setStyleSheet("QAbstractItemView::item {height: 20px;}")
        self.api_selector.setView(QListView())

        self.btn_confirm = QPushButton('确定', group_frame)
        self.btn_confirm.setFont(temp_font)
        self.btn_confirm.setGeometry(50, 120, 120, 30)

    def return_executor_instance(self) -> tuple[Executor, bool]:
        pass


class InputApiDialog(QDialog):
    """
    输入api参数弹出窗口，通过窗口间通讯方式实现通信
    """
    signal_emitter: pyqtBoundSignal = pyqtSignal(int)

    # noinspection PyTypeChecker
    def __init__(self):
        super().__init__()

        self.btn_confirm: QPushButton = None
        self.check_label: QCheckBox = None

        self.label_key: QLabel = None
        self.label_secret: QLabel = None
        self.label_id: QLabel = None

        self.input_key: QLineEdit = None
        self.input_secret: QLineEdit = None
        self.input_id: QLineEdit = None
        self.input_file_name: QLineEdit = None

        self._init_setting()

    def _init_setting(self):
        self.setWindowTitle('输入API参数')
        self.setFixedSize(370, 290)
        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(14)

        # 上半直接输入部分
        up_frame = QFrame(self)
        up_frame.setGeometry(30, 30, 310, 131)
        up_frame.setFrameStyle((QFrame.Box | QFrame.Plain))
        up_frame.setObjectName('up_frame')
        up_frame.setStyleSheet("QFrame#up_frame{border-radius: 0px}")

        self.label_key = QLabel('api_key', up_frame)
        self.label_key.setFont(temp_font)
        self.label_key.setGeometry(20, 20, 90, 24)
        self.label_secret = QLabel('api_secret', up_frame)
        self.label_secret.setFont(temp_font)
        self.label_secret.setGeometry(20, 56, 90, 24)
        self.label_id = QLabel('user_id', up_frame)
        self.label_id.setFont(temp_font)
        self.label_id.setGeometry(20, 92, 90, 24)

        self.input_key = QLineEdit(up_frame)
        self.input_key.setFont(temp_font)
        self.input_key.setGeometry(110, 20, 180, 24)
        self.input_secret = QLineEdit(up_frame)
        self.input_secret.setFont(temp_font)
        self.input_secret.setGeometry(110, 56, 180, 24)
        self.input_id = QLineEdit(up_frame)
        self.input_id.setFont(temp_font)
        self.input_id.setGeometry(110, 92, 180, 24)

        # 下半选择文件部分
        down_frame = QFrame(self)
        down_frame.setGeometry(30, 160, 310, 60)
        down_frame.setFrameStyle((QFrame.Box | QFrame.Plain))
        down_frame.setObjectName('down_frame')
        down_frame.setStyleSheet("QFrame#down_frame{border-radius: 0px}")

        temp_font.setPixelSize(12)
        self.check_label = QCheckBox('选择文件', down_frame)
        self.check_label.setFont(temp_font)
        self.check_label.setGeometry(20, 18, 90, 24)
        self.check_label.stateChanged.connect(self._set_input_model)
        temp_font.setPixelSize(14)

        self.input_file_name = QLineEdit(down_frame)
        self.input_file_name.setFont(temp_font)
        self.input_file_name.setGeometry(110, 18, 180, 24)
        self.input_file_name.setText('gate_api.txt')
        self.input_file_name.setEnabled(False)

        self.btn_confirm = QPushButton('确定', self)
        self.btn_confirm.setFont(temp_font)
        self.btn_confirm.setGeometry(210, 240, 120, 30)
        self.btn_confirm.clicked.connect(lambda: self.signal_emitter.emit(WTOKEN.API_INPUT_CONFIRM))

    def _set_input_model(self) -> None:
        """
        设置选项框的逻辑功能，输入方式
        :return:
        """
        if self.check_label.isChecked():
            self.label_key.setEnabled(False)
            self.label_secret.setEnabled(False)
            self.label_id.setEnabled(False)
            self.input_key.setEnabled(False)
            self.input_secret.setEnabled(False)
            self.input_id.setEnabled(False)
            self.input_file_name.setEnabled(True)
        else:
            self.label_key.setEnabled(True)
            self.label_secret.setEnabled(True)
            self.label_id.setEnabled(True)
            self.input_key.setEnabled(True)
            self.input_secret.setEnabled(True)
            self.input_id.setEnabled(True)
            self.input_file_name.setEnabled(False)

    def get_api_info(self) -> tuple[str, str, str]:
        text_api_key: str = self.input_key.text()
        text_api_secret: str = self.input_secret.text()
        text_user_id: str = self.input_id.text()

        return text_api_key, text_api_secret, text_user_id

    def get_api_file_name(self) -> str:
        return self.input_file_name.text()

    def use_file(self) -> bool:
        if self.check_label.isChecked():
            return True
        else:
            return False

    def response_failure(self) -> None:
        # 提示api连接失败
        self.input_key.setText('api连接失败')

    def closeEvent(self, a0: QCloseEvent) -> None:
        print('api输入窗口实例被关闭')
        self.signal_emitter.emit(WTOKEN.API_INPUT_CLOSE)

    def __del__(self):
        print('api输入窗口实例被删除')


class WrongParamInputDialog(QDialog):
    # todo: 调整好看一些
    def __init__(self):
        super().__init__()
        self.setFixedSize(260, 360)
        self.setWindowTitle('参数输入错误')
        self.error_info = QPlainTextEdit(self)
        self.init_ui()

    def init_ui(self):
        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(16)

        hint_text = QLabel('错误信息:', self)
        hint_text.setFont(temp_font)
        hint_text.setGeometry(20, 20, 80, 20)

        temp_font.setPixelSize(14)
        self.error_info.setReadOnly(True)
        self.error_info.setFont(temp_font)
        self.error_info.setGeometry(40, 50, 180, 250)

        ok_button = QPushButton('OK', self)
        ok_button.setFont(temp_font)
        ok_button.setGeometry(160, 320, 80, 24)
        ok_button.clicked.connect(self.close)

    def set_error_text(self, error_text: str) -> None:
        self.error_info.setPlainText(error_text)

    def __del__(self):
        print('参数错误提示窗口 实例 被删除')


class ParamRefInfoWindow(QWidget):

    temp_text = """
*** ========================================================== ***

合约名称: BTCBUSD			当前价格: 17442.99

critical index = 26
网格价差占比		0.0029    	%         
网格套利利润		0.0006    	BUSD      

初始现货花费		0.0312    	BTC       
初始现货仓位		0         	BTC       

初始资金花费		0         	BUSD      
初始资金仓位		544.221288	BUSD      

最大现货花费		0.216     	BTC       	于网格上边界
最大资金花费		0         	BUSD      	于网格下边界

上冲止损价差		30.5      
下冲止损价差		不触发止损     

*** ========================================================== ***
    """

    def __init__(self):
        super().__init__()
        self.setFixedSize(820, 700)
        self.setWindowTitle('网格参数详情参考')
        # self.setWindowFlags(Qt.WindowStaysOnTopHint)
        self.ref_info = QTextBrowser(self)
        self._init_setting()

    def _init_setting(self):
        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(16)

        self.ref_info.setFont(temp_font)
        self.ref_info.setGeometry(50, 40, 720, 580)

        ok_button = QPushButton('确认', self)
        ok_button.setFont(temp_font)
        ok_button.setGeometry(700, 640, 90, 30)
        ok_button.clicked.connect(self.close)

        # self.ref_info.setText(self.temp_text)

    def set_ref_info(self, info_str: str) -> None:
        self.ref_info.setText(info_str)
        # todo: 如果使用 dialog 方式，使该窗口在最前端，由于是在协程函数中使用方法exec()，
        #  会导致事件循环尝试操作该routine时报错，推测是quamash包未将用户操作等待视为io等待

    def __del__(self):
        print('参考信息窗口实例被删除')


if __name__ == '__main__':
    import sys
    import qdarkstyle
    from PyQt5 import QtCore, QtGui
    from PyQt5.QtWidgets import QApplication

    test_app = QApplication(sys.argv)
    test_app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    test_window = WrongParamInputDialog()
    test_window.show()
    test_app.exec()

