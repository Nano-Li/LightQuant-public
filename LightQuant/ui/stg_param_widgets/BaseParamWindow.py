# -*- coding: utf-8 -*-
# @Time : 2023/1/25 19:46 
# @Author : 
# @File : BaseParamWindow.py 
# @Software: PyCharm
import re
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, pyqtBoundSignal, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QBoxLayout,
    QDockWidget, QLabel, QPushButton, QScrollArea, QSplitter,
    QComboBox, QGroupBox, QTextBrowser
)
from PyQt5 import sip, QtGui

from ..WindowToken import WindowToken as WTOKEN


class ParamWidget(QWidget):
    """
    所有策略参数输入窗口的基类，定义公有方法
    """
    signal_emitter_param: pyqtBoundSignal = pyqtSignal(int)

    # noinspection PyTypeChecker
    def __init__(self):
        super().__init__()

        # 即所有的参数输入窗格 都要包含这三个按钮
        self.btn_validate_param: QPushButton = QPushButton('参数修正')
        self.btn_ref_info: QPushButton = QPushButton('信息参考')
        self.btn_confirm_param: QPushButton = QPushButton('确认参数')

        self.btn_validate_param.clicked.connect(self._param_validate)
        self.btn_ref_info.clicked.connect(self._param_ref_info)
        self.btn_confirm_param.clicked.connect(self._param_confirm)
        # todo: temp method test
        # self.btn_ref_info.clicked.connect(lambda: self.btn_confirm_param.setEnabled(True))

    def _init_setting(self):
        pass

    def _param_validate(self):
        self.remove_redundant()
        self.signal_emitter_param.emit(WTOKEN.PARAM_VALIDATION)
        pass

    def _param_ref_info(self):
        self.remove_redundant()
        self.signal_emitter_param.emit(WTOKEN.PARAM_REF_WINDOW)
        pass

    def _param_confirm(self):
        self.signal_emitter_param.emit(WTOKEN.PARAM_CONFIRM)
        pass

    def check_inputs(self) -> dict:
        pass

    def remove_redundant(self) -> None:
        pass

    def get_input_params(self) -> dict:
        pass

    def update_text(self, updated_params: dict) -> None:
        pass

    def _disable_confirm_btn(self):
        if self.btn_confirm_param.isEnabled():
            self.btn_confirm_param.setEnabled(False)

    def set_readonly(self) -> None:
        """
        修改为只读状态，用于策略运行后只能查看参数
        :return:
        """
        self.setEnabled(False)

    def set_editable(self) -> None:
        self.setEnabled(True)

    def closeEvent(self, a0: QtGui.QCloseEvent) -> None:
        print('param window 触发close event')
        self.signal_emitter_param.emit(WTOKEN.PARAM_WINDOW_CLOSE)

    def __del__(self):
        print('Param Window 实例被删除')

    @staticmethod
    def _valid_num(match_text: str) -> bool:
        """
        检查输入数字是否合理，为小数或整数即合理，包括科学计数法
        :param match_text: ♣
        :return:
        """
        result1 = re.match(r'^[0-9]*\.?[0-9]+$', match_text)
        result2 = re.match(r'^[0-9]+\.?[0-9]*$', match_text)
        result3 = re.match(r'^[+-]?[\d]+([.][\d]+)?([Ee][+-]?[\d]+)?$', match_text)
        if result1 or result2 or result3:
            return True
        else:
            return False

