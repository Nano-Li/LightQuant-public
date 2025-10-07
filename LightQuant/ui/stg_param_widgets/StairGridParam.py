# -*- coding: utf-8 -*-
# @Time : 2023/2/21 9:59
# @Author : 
# @File : StairGridParam.py 
# @Software: PyCharm
import re
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QFrame, QLabel, QRadioButton, QButtonGroup, QLineEdit
)
from .BaseParamWindow import ParamWidget


class StairGridParam(ParamWidget):
    """
    自动补仓网格参数输入窗口
    """

    param_dict: dict = {
        'symbol_name': None,
        'up_price': None,
        # 二选一中选择哪个，分别用 int 1, 2 表示
        'dul_selection': None,
        'price_abs_step': None,
        'price_rel_step': None,
        'filling_price_step': None,
        'lower_price_limit': None,
        # 三选一中选择哪个，分别用 int 1, 2, 3 表示
        'tri_selection': None,
        'filling_quantity': None,
        'filling_fund': None,
        'filling_grid_qty': None,
        'leverage': None
    }

    # noinspection PyTypeChecker
    def __init__(self):
        super().__init__()

        self.label_relative_hint: QLabel = None
        self.select_price_abs_step: QRadioButton = None
        self.select_price_rel_step: QRadioButton = None
        self.select_filling_quantity: QRadioButton = None
        self.select_filling_fund: QRadioButton = None
        self.select_filling_grid_qty: QRadioButton = None

        self.input_symbol_name: QLineEdit = None
        self.input_up_price: QLineEdit = None
        self.input_price_abs_step: QLineEdit = None
        self.input_price_rel_step: QLineEdit = None
        self.input_filling_price_step: QLineEdit = None
        self.input_lower_price_limit: QLineEdit = None
        self.input_filling_quantity: QLineEdit = None
        self.input_filling_fund: QLineEdit = None
        self.input_filling_grid_qty: QLineEdit = None
        self.input_leverage: QLineEdit = None

        self._init_setting()

    def _init_setting(self):
        # self.setWindowFlags(Qt.WindowStaysOnTopHint)    # 测试用功能
        self.setFixedSize(400, 490)
        self.setWindowTitle('智能调仓网格参数')

        main_frame = QFrame(self)
        main_frame.setGeometry(10, 10, 380, 470)
        main_frame.setFrameStyle((QFrame.Panel | QFrame.Raised))

        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(16)

        # ====================================== 参数部分 ====================================== #
        frame_param_input = QFrame(main_frame)
        frame_param_input.setGeometry(20, 20, 340, 331)
        frame_param_input.setFrameStyle((QFrame.Box | QFrame.Plain))
        frame_param_input.setObjectName('frame_param_input')
        frame_param_input.setStyleSheet("QFrame#frame_param_input{border-radius: 0px}")

        label_x = 25
        label_symbol_name = QLabel('合约名称', frame_param_input)
        label_symbol_name.setFont(temp_font)
        label_symbol_name.setGeometry(label_x, 20, 80, 24)
        self.input_symbol_name = QLineEdit(frame_param_input)
        self.input_symbol_name.setFont(temp_font)
        self.input_symbol_name.setGeometry(170, 20, 150, 24)
        self.input_symbol_name.textEdited.connect(self._disable_confirm_btn)

        label_up_price = QLabel('上界价格', frame_param_input)
        label_up_price.setFont(temp_font)
        label_up_price.setGeometry(label_x, 50, 80, 24)
        self.input_up_price = QLineEdit(frame_param_input)
        self.input_up_price.setFont(temp_font)
        self.input_up_price.setGeometry(170, 50, 150, 24)
        self.input_up_price.textEdited.connect(self._disable_confirm_btn)

        price_step_group = QButtonGroup(frame_param_input)
        radio_x = 12
        self.select_price_abs_step = QRadioButton('网格价差', frame_param_input)
        self.select_price_abs_step.setFont(temp_font)
        self.select_price_abs_step.setGeometry(radio_x, 80, 88, 24)
        self.select_price_abs_step.setChecked(True)  # 经过测试，radio button 只有初始设置状态有效，动态调整状态无效
        self.select_price_abs_step.toggled.connect(
            lambda: (self.input_price_abs_step.setEnabled(True),
                     self._disable_confirm_btn())
            if self.select_price_abs_step.isChecked()
            else (self.input_price_abs_step.setEnabled(False),
                  self._disable_confirm_btn())
        )
        self.input_price_abs_step = QLineEdit(frame_param_input)
        self.input_price_abs_step.setFont(temp_font)
        self.input_price_abs_step.setGeometry(170, 80, 150, 24)
        self.input_price_abs_step.textEdited.connect(self._disable_confirm_btn)

        self.select_price_rel_step = QRadioButton('比例价差', frame_param_input)
        self.select_price_rel_step.setFont(temp_font)
        self.select_price_rel_step.setGeometry(radio_x, 110, 88, 24)
        self.select_price_rel_step.toggled.connect(
            lambda: (self.input_price_rel_step.setEnabled(True),
                     self.label_relative_hint.setEnabled(True),
                     self._disable_confirm_btn())
            if self.select_price_rel_step.isChecked()
            else (self.input_price_rel_step.setEnabled(False),
                  self.label_relative_hint.setEnabled(False),
                  self._disable_confirm_btn())
        )
        self.input_price_rel_step = QLineEdit(frame_param_input)
        self.input_price_rel_step.setFont(temp_font)
        self.input_price_rel_step.setGeometry(170, 110, 150, 24)
        self.input_price_rel_step.setEnabled(False)
        self.input_price_rel_step.textEdited.connect(self._disable_confirm_btn)
        self.label_relative_hint = QLabel('%', frame_param_input)
        self.label_relative_hint.setFont(temp_font)
        self.label_relative_hint.setGeometry(302, 110, 16, 24)
        self.label_relative_hint.setStyleSheet("QLabel{background-color: transparent;}")
        self.label_relative_hint.setEnabled(False)

        price_step_group.addButton(self.select_price_abs_step)
        price_step_group.addButton(self.select_price_rel_step)

        label_filling_price_step = QLabel('补仓价差', frame_param_input)
        label_filling_price_step.setFont(temp_font)
        label_filling_price_step.setGeometry(label_x, 140, 80, 24)
        self.input_filling_price_step = QLineEdit(frame_param_input)
        self.input_filling_price_step.setFont(temp_font)
        self.input_filling_price_step.setGeometry(170, 140, 150, 24)
        self.input_filling_price_step.textEdited.connect(self._disable_confirm_btn)

        label_lower_price_limit = QLabel('下方价差', frame_param_input)
        label_lower_price_limit.setFont(temp_font)
        label_lower_price_limit.setGeometry(label_x, 170, 80, 24)
        self.input_lower_price_limit = QLineEdit(frame_param_input)
        self.input_lower_price_limit.setFont(temp_font)
        self.input_lower_price_limit.setGeometry(170, 170, 150, 24)
        self.input_lower_price_limit.textEdited.connect(self._disable_confirm_btn)

        filling_amount_group = QButtonGroup(frame_param_input)
        self.select_filling_quantity = QRadioButton('初始仓位(数量)', frame_param_input)
        self.select_filling_quantity.setFont(temp_font)
        self.select_filling_quantity.setGeometry(radio_x, 200, 140, 24)
        self.select_filling_quantity.setChecked(True)  # 经过测试，radio button 只有初始设置状态有效，动态调整状态无效
        self.select_filling_quantity.toggled.connect(
            lambda: (self.input_filling_quantity.setEnabled(True),
                     self._disable_confirm_btn())
            if self.select_filling_quantity.isChecked()
            else (self.input_filling_quantity.setEnabled(False),
                  self._disable_confirm_btn())
        )
        self.input_filling_quantity = QLineEdit(frame_param_input)
        self.input_filling_quantity.setFont(temp_font)
        self.input_filling_quantity.setGeometry(170, 200, 150, 24)
        self.input_filling_quantity.textEdited.connect(self._disable_confirm_btn)

        self.select_filling_fund = QRadioButton('初始仓位(金额)', frame_param_input)
        self.select_filling_fund.setFont(temp_font)
        self.select_filling_fund.setGeometry(radio_x, 230, 140, 24)
        self.select_filling_fund.toggled.connect(
            lambda: (self.input_filling_fund.setEnabled(True),
                     self._disable_confirm_btn())
            if self.select_filling_fund.isChecked()
            else (self.input_filling_fund.setEnabled(False),
                  self._disable_confirm_btn())
        )
        self.input_filling_fund = QLineEdit(frame_param_input)
        self.input_filling_fund.setFont(temp_font)
        self.input_filling_fund.setGeometry(170, 230, 150, 24)
        self.input_filling_fund.setEnabled(False)
        self.input_filling_fund.textEdited.connect(self._disable_confirm_btn)

        self.select_filling_grid_qty = QRadioButton('每格数量', frame_param_input)
        self.select_filling_grid_qty.setFont(temp_font)
        self.select_filling_grid_qty.setGeometry(radio_x, 260, 88, 24)
        self.select_filling_grid_qty.toggled.connect(
            lambda: (self.input_filling_grid_qty.setEnabled(True),
                     self._disable_confirm_btn())
            if self.select_filling_grid_qty.isChecked()
            else (self.input_filling_grid_qty.setEnabled(False),
                  self._disable_confirm_btn())
        )
        self.input_filling_grid_qty = QLineEdit(frame_param_input)
        self.input_filling_grid_qty.setFont(temp_font)
        self.input_filling_grid_qty.setGeometry(170, 260, 150, 24)
        self.input_filling_grid_qty.setEnabled(False)
        self.input_filling_grid_qty.textEdited.connect(self._disable_confirm_btn)

        filling_amount_group.addButton(self.select_filling_quantity)
        filling_amount_group.addButton(self.select_filling_fund)
        filling_amount_group.addButton(self.select_filling_grid_qty)

        label_symbol_leverage = QLabel('合约杠杆', frame_param_input)
        label_symbol_leverage.setFont(temp_font)
        label_symbol_leverage.setGeometry(label_x, 290, 80, 24)
        self.input_leverage = QLineEdit(frame_param_input)
        self.input_leverage.setFont(temp_font)
        self.input_leverage.setGeometry(170, 290, 150, 24)
        self.input_leverage.textEdited.connect(self._disable_confirm_btn)

        # ====================================== 按钮部分 ====================================== #
        frame_buttons = QFrame(main_frame)
        frame_buttons.setGeometry(20, 350, 340, 100)
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
        """
        检查网格输入参数
        :return:
        """
        status_return = {
            'okay': True,
            'msg': ''
        }
        all_okay = True
        error_msg = ''

        input_symbol_name = self.input_symbol_name.text()
        input_up_price = self.input_up_price.text()
        input_price_abs_step = self.input_price_abs_step.text()
        input_price_rel_step = self.input_price_rel_step.text()
        input_filling_price_step = self.input_filling_price_step.text()
        input_lower_price_limit = self.input_lower_price_limit.text()
        input_filling_quantity = self.input_filling_quantity.text()
        input_filling_fund = self.input_filling_fund.text()
        input_filling_grid_qty = self.input_filling_grid_qty.text()
        input_symbol_leverage = self.input_leverage.text()

        result = re.match(r'^[0-9a-zA-Z_]+$', input_symbol_name)
        if not result:
            all_okay = False
            error_msg += '合约名称输入有误\n\n'

        if not self._valid_num(input_up_price):
            all_okay = False
            error_msg += '上界价格输入错误\n\n'

        if self.select_price_abs_step.isChecked():
            if not self._valid_num(input_price_abs_step):
                all_okay = False
                error_msg += '网格价差输入错误\n\n'
        elif self.select_price_rel_step.isChecked():
            if not self._valid_num(input_price_rel_step):
                all_okay = False
                error_msg += '比例价差输入错误\n\n'

        if not self._valid_num(input_filling_price_step):
            all_okay = False
            error_msg += '补仓价差输入错误\n\n'

        if not self._valid_num(input_lower_price_limit):
            all_okay = False
            error_msg += '下方价差输入错误\n\n'

        if self.select_filling_quantity.isChecked():
            if not self._valid_num(input_filling_quantity):
                all_okay = False
                error_msg += '初始仓位(数量)输入错误\n\n'
        elif self.select_filling_fund.isChecked():
            if not self._valid_num(input_filling_fund):
                all_okay = False
                error_msg += '初始仓位(金额)输入错误\n\n'
        elif self.select_filling_grid_qty.isChecked():
            if not self._valid_num(input_filling_grid_qty):
                all_okay = False
                error_msg += '每格数量输入错误\n\n'

        if not self._valid_num(input_symbol_leverage):
            all_okay = False
            error_msg += '合约杠杆输入错误\n\n'
        else:
            leverage = int(float(input_symbol_leverage))
            if not (leverage >= 1):
                all_okay = False
                error_msg += '合约杠杆数值过小\n'

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
        input_param_dict['dul_selection'] = self._get_dul_selection()
        input_param_dict['price_abs_step'] = float(self.input_price_abs_step.text()) if self.select_price_abs_step.isChecked() else ''
        input_param_dict['price_rel_step'] = float(self.input_price_rel_step.text()) if self.select_price_rel_step.isChecked() else ''
        input_param_dict['filling_price_step'] = float(self.input_filling_price_step.text())
        input_param_dict['lower_price_limit'] = float(self.input_lower_price_limit.text())
        input_param_dict['tri_selection'] = self._get_tri_selection()
        input_param_dict['filling_quantity'] = float(self.input_filling_quantity.text()) if self.select_filling_quantity.isChecked() else ''
        input_param_dict['filling_fund'] = float(self.input_filling_fund.text()) if self.select_filling_fund.isChecked() else ''
        input_param_dict['filling_grid_qty'] = float(self.input_filling_grid_qty.text()) if self.select_filling_grid_qty.isChecked() else ''
        input_param_dict['leverage'] = int(float(self.input_leverage.text()))

        return input_param_dict

    def update_text(self, updated_params: dict) -> None:
        self.input_symbol_name.setText(str(updated_params['symbol_name']))
        self.input_up_price.setText(str(updated_params['up_price']))
        self.input_price_abs_step.setText(str(updated_params['price_abs_step']))
        self.input_price_rel_step.setText(str(updated_params['price_rel_step']))
        self.input_filling_price_step.setText(str(updated_params['filling_price_step']))
        self.input_lower_price_limit.setText(str(updated_params['lower_price_limit']))
        self.input_filling_quantity.setText(str(updated_params['filling_quantity']))
        self.input_filling_fund.setText(str(updated_params['filling_fund']))
        self.input_filling_grid_qty.setText(str(updated_params['filling_grid_qty']))
        self.input_leverage.setText(str(updated_params['leverage']))

    def _get_dul_selection(self) -> int:
        if self.select_price_abs_step.isChecked():
            return 1
        elif self.select_price_rel_step.isChecked():
            return 2

    def _get_tri_selection(self) -> int:
        if self.select_filling_quantity.isChecked():
            return 1
        elif self.select_filling_fund.isChecked():
            return 2
        elif self.select_filling_grid_qty.isChecked():
            return 3


if __name__ == '__main__':
    import sys
    import qdarkstyle
    from PyQt5.QtWidgets import QApplication
    from qdarkstyle.light.palette import LightPalette

    app = QApplication(sys.argv)

    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    # app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt5', palette=LightPalette()))

    w = StairGridParam()
    w.show()
    app.exec()


