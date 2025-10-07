# -*- coding: utf-8 -*-
# @Time : 2023/12/6 16:10
# @Author : 
# @File : SmartGridParam.py 
# @Software: PyCharm
import re
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QFrame, QLabel, QLineEdit, QCheckBox
)
from .BaseParamWindow import ParamWidget


class SmartGridParam(ParamWidget):
    """
    智能调仓网格参数
    """

    param_dict: dict = {
        'symbol_name': None,
        'up_price': None,
        'leverage': None,
        'trigger_start': None,  # 是否用挂单触发, True/False
        'pending_trigger_price': None,

        'grid_rel_step': None,
        'filling_step': None,
        'lower_step': None,
        'filling_fund': None    # 设定补仓资金
    }

    # noinspection PyTypeChecker
    def __init__(self):
        super().__init__()

        self.label_relative_hint: QLabel = None
        self.label_filling_price_hint: QLabel = None
        self.label_lower_price_hint: QLabel = None
        self.label_USDT_hint: QLabel = None
        self.select_pending_trigger: QCheckBox = None

        self.input_symbol_name: QLineEdit = None
        self.input_up_price: QLineEdit = None
        self.input_leverage: QLineEdit = None
        self.input_pending_trigger: QLineEdit = None

        self.input_grid_rel_step: QLineEdit = None
        self.input_filling_step: QLineEdit = None
        self.input_lower_step: QLineEdit = None
        self.input_filling_fund: QLineEdit = None

        self._init_setting()

    def _init_setting(self):
        # self.setWindowFlags(Qt.WindowStaysOnTopHint)    # 测试用功能
        self.setFixedSize(400, 460)  # 增加了窗体的高度以适应更多的输入行
        self.setWindowTitle('智能调仓网格参数')

        main_frame = QFrame(self)
        main_frame.setGeometry(10, 10, 380, 440)
        main_frame.setFrameStyle((QFrame.Panel | QFrame.Raised))

        temp_font = QFont()
        temp_font.setFamily('SimSun')           # todo: 使用全局字体设置
        temp_font.setPixelSize(16)

        # ====================================== 基础参数 ====================================== #
        frame_basic_param = QFrame(main_frame)
        frame_basic_param.setGeometry(20, 20, 340, 151)  # 减少了高度以反映删除的一行输入
        frame_basic_param.setFrameStyle((QFrame.Box | QFrame.Plain))
        frame_basic_param.setObjectName('frame_basic_param')
        frame_basic_param.setStyleSheet("QFrame#frame_basic_param{border-radius: 0px}")

        label_x = 25
        select_x = 12
        input_x = 170
        hint_x = 302
        label_width = 80
        input_width = 150
        row_height = 24

        # 合约名称
        label_symbol_name = QLabel('合约名称', frame_basic_param)
        label_symbol_name.setFont(temp_font)
        label_symbol_name.setGeometry(label_x, 20, label_width, row_height)
        self.input_symbol_name = QLineEdit(frame_basic_param)
        self.input_symbol_name.setFont(temp_font)
        self.input_symbol_name.setGeometry(input_x, 20, input_width, row_height)
        self.input_symbol_name.textEdited.connect(self._disable_confirm_btn)

        # 上界价格
        label_up_price = QLabel('上界价格', frame_basic_param)
        label_up_price.setFont(temp_font)
        label_up_price.setGeometry(label_x, 50, label_width, row_height)
        self.input_up_price = QLineEdit(frame_basic_param)
        self.input_up_price.setFont(temp_font)
        self.input_up_price.setGeometry(input_x, 50, input_width, row_height)
        self.input_up_price.textEdited.connect(self._disable_confirm_btn)

        # 合约杠杆
        label_symbol_leverage = QLabel('合约杠杆', frame_basic_param)
        label_symbol_leverage.setFont(temp_font)
        label_symbol_leverage.setGeometry(label_x, 80, label_width, row_height)
        self.input_leverage = QLineEdit(frame_basic_param)
        self.input_leverage.setFont(temp_font)
        self.input_leverage.setGeometry(input_x, 80, input_width, row_height)
        self.input_leverage.textEdited.connect(self._disable_confirm_btn)

        # 挂单触发
        self.select_pending_trigger = QCheckBox('挂单触发', frame_basic_param)
        self.select_pending_trigger.setFont(temp_font)
        self.select_pending_trigger.setGeometry(select_x, 110, label_width + 40, row_height)
        self.select_pending_trigger.stateChanged.connect(
            lambda: (self.input_pending_trigger.setEnabled(True),
                     self._disable_confirm_btn())
            if self.select_pending_trigger.isChecked()
            else (self.input_pending_trigger.setEnabled(False),
                  self._disable_confirm_btn())
        )

        # 挂单触发价格
        self.input_pending_trigger = QLineEdit(frame_basic_param)
        self.input_pending_trigger.setFont(temp_font)
        self.input_pending_trigger.setGeometry(input_x, 110, input_width, row_height)
        self.input_pending_trigger.textEdited.connect(self._disable_confirm_btn)
        self.input_pending_trigger.setEnabled(False)

        # ====================================== 功能参数 ====================================== #
        label_function_param = QLabel('设定套利区间', main_frame)
        label_function_param.setGeometry(50, 160, 80, 24)

        frame_function_param = QFrame(main_frame)
        frame_function_param.setGeometry(20, 170, 340, 151)  # 根据需要调整位置和大小
        frame_function_param.setFrameStyle((QFrame.Box | QFrame.Plain))
        frame_function_param.setObjectName('frame_function_param')
        frame_function_param.setStyleSheet("QFrame#frame_function_param{border-radius: 0px}")
        frame_function_param.lower()

        # 网格间距
        label_grid_rel_step = QLabel('网格间距', frame_function_param)
        label_grid_rel_step.setFont(temp_font)
        label_grid_rel_step.setGeometry(label_x, 20, label_width, row_height)
        self.input_grid_rel_step = QLineEdit(frame_function_param)
        self.input_grid_rel_step.setFont(temp_font)
        self.input_grid_rel_step.setGeometry(input_x, 20, input_width, row_height)
        self.input_grid_rel_step.textEdited.connect(self._disable_confirm_btn)
        self.label_relative_hint = QLabel('%', frame_function_param)
        self.label_relative_hint.setFont(temp_font)
        self.label_relative_hint.setGeometry(hint_x, 20, 20, 24)
        self.label_relative_hint.setStyleSheet("QLabel{background-color: transparent;}")

        # 补仓价差
        label_filling_step = QLabel('补仓点位（涨）', frame_function_param)
        label_filling_step.setFont(temp_font)
        label_filling_step.setGeometry(label_x, 50, label_width + 30, row_height)
        self.input_filling_step = QLineEdit(frame_function_param)
        self.input_filling_step.setFont(temp_font)
        self.input_filling_step.setGeometry(input_x, 50, input_width, row_height)
        self.input_filling_step.textEdited.connect(self._disable_confirm_btn)
        self.label_filling_price_hint = QLabel('%', frame_function_param)
        self.label_filling_price_hint.setFont(temp_font)
        self.label_filling_price_hint.setGeometry(hint_x, 50, 20, 24)
        self.label_filling_price_hint.setStyleSheet("QLabel{background-color: transparent;}")

        # 下方价差
        label_lower_step = QLabel('下方空间（跌）', frame_function_param)
        label_lower_step.setFont(temp_font)
        label_lower_step.setGeometry(label_x, 80, label_width + 30, row_height)
        self.input_lower_step = QLineEdit(frame_function_param)
        self.input_lower_step.setFont(temp_font)
        self.input_lower_step.setGeometry(input_x, 80, input_width, row_height)
        self.input_lower_step.textEdited.connect(self._disable_confirm_btn)
        self.label_lower_price_hint = QLabel('%', frame_function_param)
        self.label_lower_price_hint.setFont(temp_font)
        self.label_lower_price_hint.setGeometry(hint_x, 80, 20, 24)
        self.label_lower_price_hint.setStyleSheet("QLabel{background-color: transparent;}")

        # 补仓金额
        label_filling_fund = QLabel('补仓金额', frame_function_param)
        label_filling_fund.setFont(temp_font)
        label_filling_fund.setGeometry(label_x, 110, label_width, row_height)
        self.input_filling_fund = QLineEdit(frame_function_param)
        self.input_filling_fund.setFont(temp_font)
        self.input_filling_fund.setGeometry(input_x, 110, input_width, row_height)
        self.input_filling_fund.textEdited.connect(self._disable_confirm_btn)
        self.label_USDT_hint = QLabel('U', frame_function_param)
        self.label_USDT_hint.setFont(temp_font)
        self.label_USDT_hint.setGeometry(hint_x, 110, 20, 24)
        self.label_USDT_hint.setStyleSheet("QLabel{background-color: transparent;}")

        # ====================================== 按钮部分 ====================================== #
        frame_buttons = QFrame(main_frame)
        frame_buttons.setGeometry(20, 320, 340, 100)
        frame_buttons.setFrameStyle((QFrame.Box | QFrame.Plain))
        frame_buttons.setObjectName('frame_buttons')
        frame_buttons.setStyleSheet("QFrame#frame_buttons{border-radius: 0px}")

        self.btn_validate_param.setParent(frame_buttons)
        self.btn_validate_param.setFont(temp_font)
        self.btn_validate_param.setGeometry(20, 20, 130, 30)

        self.btn_ref_info.setParent(frame_buttons)
        self.btn_ref_info.setFont(temp_font)
        self.btn_ref_info.setGeometry(180, 20, 140, 30)

        self.btn_confirm_param.setParent(frame_buttons)
        self.btn_confirm_param.setFont(temp_font)
        self.btn_confirm_param.setGeometry(20, 60, 300, 30)
        self.btn_confirm_param.setEnabled(False)

    def check_inputs(self) -> dict:
        status_return = {
            'okay': True,
            'msg': ''
        }
        all_okay = True
        error_msg = ''

        input_symbol_name = self.input_symbol_name.text()
        input_up_price = self.input_up_price.text()
        input_leverage = self.input_leverage.text()
        input_pending_trigger = self.input_pending_trigger.text()
        input_grid_rel_step = self.input_grid_rel_step.text()
        input_filling_step = self.input_filling_step.text()
        input_lower_step = self.input_lower_step.text()
        input_filling_fund = self.input_filling_fund.text()

        # 检查合约名称
        result = re.match(r'^[0-9a-zA-Z_]+$', input_symbol_name)
        if not result:
            all_okay = False
            error_msg += '合约名称输入有误\n\n'

        # 检查上界价格
        if not self._valid_num(input_up_price):
            all_okay = False
            error_msg += '上界价格输入错误\n\n'

        # 检查合约杠杆
        if not self._valid_num(input_leverage):
            all_okay = False
            error_msg += '合约杠杆输入错误\n\n'
        else:
            leverage = int(float(input_leverage))
            if not (leverage >= 1):
                all_okay = False
                error_msg += '合约杠杆数值过小\n\n'

        # 检查挂单触发价格
        if self.select_pending_trigger.isChecked() and not self._valid_num(input_pending_trigger):
            all_okay = False
            error_msg += '挂单触发价格输入错误\n\n'

        # 检查比例间距
        if not self._valid_num_or_empty(input_grid_rel_step):
            all_okay = False
            error_msg += '比例间距输入错误\n\n'

        # 检查补仓价差
        if not self._valid_num_or_empty(input_filling_step):
            all_okay = False
            error_msg += '补仓价差输入错误\n\n'

        # 检查下方价差
        if not self._valid_num_or_empty(input_lower_step):
            all_okay = False
            error_msg += '下方价差输入错误\n\n'

        # 检查补仓金额
        if not self._valid_num_or_empty(input_filling_fund):
            all_okay = False
            error_msg += '补仓金额输入错误\n\n'

        if all_okay:
            return status_return
        else:
            status_return['okay'] = all_okay
            status_return['msg'] = error_msg
            return status_return

    def get_input_params(self) -> dict:
        input_param_dict = self.param_dict.copy()

        input_param_dict['symbol_name'] = self.input_symbol_name.text()
        input_param_dict['up_price'] = float(self.input_up_price.text())
        input_param_dict['leverage'] = int(float(self.input_leverage.text()))
        input_param_dict['trigger_start'] = self.select_pending_trigger.isChecked()
        input_param_dict['pending_trigger_price'] = float(self.input_pending_trigger.text()) if self.select_pending_trigger.isChecked() else ''
        # 对于比例间距、补仓价差和下方价差，如果输入为空，则保留空字符串，否则转换为float
        input_param_dict['grid_rel_step'] = '' if self.input_grid_rel_step.text() == '' else float(self.input_grid_rel_step.text())
        input_param_dict['filling_step'] = '' if self.input_filling_step.text() == '' else float(self.input_filling_step.text())
        input_param_dict['lower_step'] = '' if self.input_lower_step.text() == '' else float(self.input_lower_step.text())
        input_param_dict['filling_fund'] = float(self.input_filling_fund.text()) if self.input_filling_fund.text() else 0.0

        return input_param_dict

    def update_text(self, updated_params: dict) -> None:

        self.input_symbol_name.setText(str(updated_params['symbol_name']))
        self.input_up_price.setText(str(updated_params['up_price']))
        self.input_leverage.setText(str(updated_params['leverage']))
        self.input_pending_trigger.setText(str(updated_params['pending_trigger_price']))
        self.input_grid_rel_step.setText(str(updated_params['grid_rel_step']))
        self.input_filling_step.setText(str(updated_params['filling_step']))
        self.input_lower_step.setText(str(updated_params['lower_step']))
        self.input_filling_fund.setText(str(updated_params['filling_fund']))

    def _valid_num_or_empty(self, match_text: str) -> bool:
        """
        检查输入文本是否为空或者是一个合理的数字。
        :param match_text: 要检查的文本
        :return: 如果文本为空或者是一个合理的数字，返回True；否则返回False
        """
        if match_text == '':
            return True
        else:
            return self._valid_num(match_text)


if __name__ == '__main__':
    import sys
    import qdarkstyle
    from PyQt5.QtWidgets import QApplication
    from qdarkstyle.light.palette import LightPalette

    app = QApplication(sys.argv)

    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    # app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt5', palette=LightPalette()))

    w = SmartGridParam()
    w.show()
    app.exec()
