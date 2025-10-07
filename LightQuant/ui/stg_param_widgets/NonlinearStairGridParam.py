# -*- coding: utf-8 -*-
# @Time : 2023/4/21 11:29
# @Author : 
# @File : NonlinearStairGridParam.py 
# @Software: PyCharm
import re
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QFont, QPixmap, QPainter, QPaintEvent
from PyQt5.QtWidgets import (
    QFrame, QLabel, QRadioButton, QButtonGroup, QLineEdit, QSlider, QCheckBox
)
from .BaseParamWindow import ParamWidget


class NonlinearStairGridParam(ParamWidget):
    """
    自动补仓网格参数输入窗口，新自动补仓网格
    下方网格间距非线性增加，可调整非线性参数
    """

    param_dict: dict = {
        'symbol_name': None,
        'up_price': None,
        'each_grid_qty': None,
        'leverage': None,
        'trigger_start': None,      # 是否用挂单触发, True/False
        'pending_trigger_price': None,

        # 二选一中选择哪个，分别用 int 1, 2 表示
        'dul_selection': None,
        'grid_abs_step': None,
        'grid_rel_step': None,
        'filling_price_step': None,
        'lower_price_step': None,

        'max_grid_step': None,
        'lower_buffer_price': None,
        # 非线性增长系数，为 1/10 ~ 1 ~ 10 共21个取值
        'alpha': None
    }

    # noinspection PyTypeChecker
    def __init__(self):
        super().__init__()

        self.label_relative_hint: QLabel = None
        self.select_grid_abs_step: QRadioButton = None
        self.select_grid_rel_step: QRadioButton = None
        self.select_pending_trigger: QCheckBox = None
        self.slider_alpha: QSlider = None

        self.input_symbol_name: QLineEdit = None
        self.input_up_price: QLineEdit = None
        self.input_each_grid_qty: QLineEdit = None
        self.input_leverage: QLineEdit = None
        self.input_pending_trigger: QLineEdit = None

        self.input_grid_abs_step: QLineEdit = None
        self.input_grid_rel_step: QLineEdit = None
        self.input_filling_price_step: QLineEdit = None
        self.input_lower_price_step: QLineEdit = None

        self.input_max_grid_step: QLineEdit = None
        self.input_lower_buffer_price: QLineEdit = None

        self._init_setting()

    def _init_setting(self):
        # self.setWindowFlags(Qt.WindowStaysOnTopHint)    # 测试用功能
        self.setFixedSize(400, 680)
        self.setWindowTitle('非线性智能调仓网格参数')

        main_frame = QFrame(self)
        main_frame.setGeometry(10, 10, 380, 660)
        main_frame.setFrameStyle((QFrame.Panel | QFrame.Raised))

        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(16)

        # ====================================== 基础参数 ====================================== #
        frame_basic_param = QFrame(main_frame)
        frame_basic_param.setGeometry(20, 20, 340, 181)
        frame_basic_param.setFrameStyle((QFrame.Box | QFrame.Plain))
        frame_basic_param.setObjectName('frame_basic_param')
        frame_basic_param.setStyleSheet("QFrame#frame_basic_param{border-radius: 0px}")

        label_x = 25
        select_x = 12
        label_symbol_name = QLabel('合约名称', frame_basic_param)
        label_symbol_name.setFont(temp_font)
        label_symbol_name.setGeometry(label_x, 20, 80, 24)
        self.input_symbol_name = QLineEdit(frame_basic_param)
        self.input_symbol_name.setFont(temp_font)
        self.input_symbol_name.setGeometry(170, 20, 150, 24)
        self.input_symbol_name.textEdited.connect(self._disable_confirm_btn)

        label_up_price = QLabel('上界价格', frame_basic_param)
        label_up_price.setFont(temp_font)
        label_up_price.setGeometry(label_x, 50, 80, 24)
        self.input_up_price = QLineEdit(frame_basic_param)
        self.input_up_price.setFont(temp_font)
        self.input_up_price.setGeometry(170, 50, 150, 24)
        self.input_up_price.textEdited.connect(self._disable_confirm_btn)

        label_each_grid_qty = QLabel('每格数量', frame_basic_param)
        label_each_grid_qty.setFont(temp_font)
        label_each_grid_qty.setGeometry(label_x, 80, 80, 24)
        self.input_each_grid_qty = QLineEdit(frame_basic_param)
        self.input_each_grid_qty.setFont(temp_font)
        self.input_each_grid_qty.setGeometry(170, 80, 150, 24)
        self.input_each_grid_qty.textEdited.connect(self._disable_confirm_btn)

        label_symbol_leverage = QLabel('合约杠杆', frame_basic_param)
        label_symbol_leverage.setFont(temp_font)
        label_symbol_leverage.setGeometry(label_x, 110, 80, 24)
        self.input_leverage = QLineEdit(frame_basic_param)
        self.input_leverage.setFont(temp_font)
        self.input_leverage.setGeometry(170, 110, 150, 24)
        self.input_leverage.textEdited.connect(self._disable_confirm_btn)

        self.select_pending_trigger = QCheckBox('挂单触发', frame_basic_param)
        self.select_pending_trigger.setFont(temp_font)
        self.select_pending_trigger.setGeometry(select_x, 140, 108, 24)
        self.select_pending_trigger.stateChanged.connect(
            lambda: (self.input_pending_trigger.setEnabled(True),
                     self._disable_confirm_btn())
            if self.select_pending_trigger.isChecked()
            else (self.input_pending_trigger.setEnabled(False),
                  self._disable_confirm_btn())
        )
        self.input_pending_trigger = QLineEdit(frame_basic_param)
        self.input_pending_trigger.setFont(temp_font)
        self.input_pending_trigger.setGeometry(170, 140, 150, 24)
        self.input_pending_trigger.textEdited.connect(self._disable_confirm_btn)
        self.input_pending_trigger.setEnabled(False)

        # ====================================== 套利部分 ====================================== #
        label_second_part = QLabel('线性区间', main_frame)
        label_second_part.setGeometry(60, 190, 60, 24)

        frame_second_part = QFrame(main_frame)
        frame_second_part.setGeometry(20, 200, 340, 151)
        frame_second_part.setFrameStyle((QFrame.Box | QFrame.Plain))
        frame_second_part.setObjectName('frame_second_part')
        frame_second_part.setStyleSheet("QFrame#frame_second_part{border-radius: 0px}")
        frame_second_part.lower()

        price_step_group = QButtonGroup(frame_second_part)
        radio_x = 12
        self.select_grid_abs_step = QRadioButton('网格间距', frame_second_part)
        self.select_grid_abs_step.setFont(temp_font)
        self.select_grid_abs_step.setGeometry(radio_x, 20, 88, 24)
        self.select_grid_abs_step.setChecked(True)  # 经过测试，radio button 只有初始设置状态有效，动态调整状态无效
        self.select_grid_abs_step.toggled.connect(
            lambda: (self.input_grid_abs_step.setEnabled(True),
                     self._disable_confirm_btn())
            if self.select_grid_abs_step.isChecked()
            else (self.input_grid_abs_step.setEnabled(False),
                  self._disable_confirm_btn())
        )
        self.input_grid_abs_step = QLineEdit(frame_second_part)
        self.input_grid_abs_step.setFont(temp_font)
        self.input_grid_abs_step.setGeometry(170, 20, 150, 24)
        self.input_grid_abs_step.textEdited.connect(self._disable_confirm_btn)

        pic0 = QLabel(frame_second_part)
        pic0.setGeometry(120, 20, 50, 24)
        pic0.setPixmap(QPixmap('./ui/pictures/formula_0.png'))

        self.select_grid_rel_step = QRadioButton('比例间距', frame_second_part)
        self.select_grid_rel_step.setFont(temp_font)
        self.select_grid_rel_step.setGeometry(radio_x, 50, 88, 24)
        self.select_grid_rel_step.toggled.connect(
            lambda: (self.input_grid_rel_step.setEnabled(True),
                     self.label_relative_hint.setEnabled(True),
                     self._disable_confirm_btn())
            if self.select_grid_rel_step.isChecked()
            else (self.input_grid_rel_step.setEnabled(False),
                  self.label_relative_hint.setEnabled(False),
                  self._disable_confirm_btn())
        )
        self.input_grid_rel_step = QLineEdit(frame_second_part)
        self.input_grid_rel_step.setFont(temp_font)
        self.input_grid_rel_step.setGeometry(170, 50, 150, 24)
        self.input_grid_rel_step.setEnabled(False)
        self.input_grid_rel_step.textEdited.connect(self._disable_confirm_btn)
        self.label_relative_hint = QLabel('%', frame_second_part)
        self.label_relative_hint.setFont(temp_font)
        self.label_relative_hint.setGeometry(302, 50, 16, 24)
        self.label_relative_hint.setStyleSheet("QLabel{background-color: transparent;}")
        self.label_relative_hint.setEnabled(False)

        price_step_group.addButton(self.select_grid_abs_step)
        price_step_group.addButton(self.select_grid_rel_step)

        input_max_grid_step = QLabel('补仓价差', frame_second_part)
        input_max_grid_step.setFont(temp_font)
        input_max_grid_step.setGeometry(label_x, 80, 80, 24)
        self.input_filling_price_step = QLineEdit(frame_second_part)
        self.input_filling_price_step.setFont(temp_font)
        self.input_filling_price_step.setGeometry(170, 80, 150, 24)
        self.input_filling_price_step.textEdited.connect(self._disable_confirm_btn)

        label_lower_price_step = QLabel('下方价差', frame_second_part)
        label_lower_price_step.setFont(temp_font)
        label_lower_price_step.setGeometry(label_x, 110, 80, 24)
        self.input_lower_price_step = QLineEdit(frame_second_part)
        self.input_lower_price_step.setFont(temp_font)
        self.input_lower_price_step.setGeometry(170, 110, 150, 24)
        self.input_lower_price_step.textEdited.connect(self._disable_confirm_btn)

        # ====================================== 缓冲部分 ====================================== #
        label_third_part = QLabel('非线性区间', main_frame)
        label_third_part.setGeometry(60, 340, 70, 24)

        frame_third_part = QFrame(main_frame)
        frame_third_part.setGeometry(20, 350, 340, 191)
        frame_third_part.setFrameStyle((QFrame.Box | QFrame.Plain))
        frame_third_part.setObjectName('frame_third_part')
        frame_third_part.setStyleSheet("QFrame#frame_third_part{border-radius: 0px}")
        frame_third_part.lower()

        label_x2 = 15
        label_max_grid_step = QLabel('最大网格间距', frame_third_part)
        label_max_grid_step.setFont(temp_font)
        label_max_grid_step.setGeometry(label_x2, 20, 120, 24)
        self.input_max_grid_step = QLineEdit(frame_third_part)
        self.input_max_grid_step.setFont(temp_font)
        self.input_max_grid_step.setGeometry(170, 20, 150, 24)
        self.input_max_grid_step.textEdited.connect(self._disable_confirm_btn)

        label_lower_buffer_price = QLabel('下方缓冲价差', frame_third_part)
        label_lower_buffer_price.setFont(temp_font)
        label_lower_buffer_price.setGeometry(label_x2, 50, 120, 24)
        self.input_lower_buffer_price = QLineEdit(frame_third_part)
        self.input_lower_buffer_price.setFont(temp_font)
        self.input_lower_buffer_price.setGeometry(170, 50, 150, 24)
        self.input_lower_buffer_price.textEdited.connect(self._disable_confirm_btn)
        # self.input_lower_buffer_price.textEdited.connect(
        #     lambda: print(self.slider_alpha.value())
        # )

        label_alpha_set = QLabel('增长系数', frame_third_part)
        label_alpha_set.setFont(temp_font)
        label_alpha_set.setGeometry(label_x2, 85, 80, 24)

        label_tick_1 = QLabel('1/10', frame_third_part)
        label_tick_1.setFont(temp_font)
        label_tick_1.setGeometry(95, 122, 40, 24)

        label_tick_2 = QLabel('1', frame_third_part)
        label_tick_2.setFont(temp_font)
        label_tick_2.setGeometry(206, 122, 20, 24)

        label_tick_3 = QLabel('10', frame_third_part)
        label_tick_3.setFont(temp_font)
        label_tick_3.setGeometry(301, 122, 30, 24)

        label_alpha_formula = QLabel('增长公式', frame_third_part)
        label_alpha_formula.setFont(temp_font)
        label_alpha_formula.setGeometry(label_x2, 154, 80, 24)

        pic1 = QLabel(frame_third_part)
        pic1.setGeometry(30, 123, 50, 24)
        pic1.setPixmap(QPixmap('./ui/pictures/formula_1.png'))

        pic2 = QLabel(frame_third_part)
        pic2.setGeometry(150, 152, 150, 30)
        pic2.setPixmap(QPixmap('./ui/pictures/formula_2.png'))

        self.slider_alpha = QSlider(frame_third_part)
        self.slider_alpha.setOrientation(Qt.Horizontal)
        self.slider_alpha.setGeometry(110, 85, 210, 24)
        self.slider_alpha.setMinimum(-9)
        self.slider_alpha.setMaximum(9)
        self.slider_alpha.setSingleStep(1)  # 设置步长值
        self.slider_alpha.setPageStep(1)
        self.slider_alpha.setTickInterval(1)  # 设置刻度间隔
        # self.slider_alpha.setTickPosition(QSlider.TicksBelow)  # 设置刻度位置，在下方
        self.slider_alpha.setValue(0)

        slider_ticks = FrameWithTick()
        slider_ticks.setParent(frame_third_part)
        slider_ticks.lower()
        slider_ticks.setGeometry(115, 110, 200, 8)

        # ====================================== 按钮部分 ====================================== #
        frame_buttons = QFrame(main_frame)
        frame_buttons.setGeometry(20, 540, 340, 100)
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
        input_each_grid_qty = self.input_each_grid_qty.text()
        input_symbol_leverage = self.input_leverage.text()
        input_pending_trigger = self.input_pending_trigger.text()
        input_grid_abs_step = self.input_grid_abs_step.text()
        input_grid_rel_step = self.input_grid_rel_step.text()
        input_filling_price_step = self.input_filling_price_step.text()
        input_lower_price_step = self.input_lower_price_step.text()
        input_max_grid_step = self.input_max_grid_step.text()
        input_lower_buffer_price = self.input_lower_buffer_price.text()

        result = re.match(r'^[0-9a-zA-Z_]+$', input_symbol_name)
        if not result:
            all_okay = False
            error_msg += '合约名称输入有误\n\n'

        if not self._valid_num(input_up_price):
            all_okay = False
            error_msg += '上界价格输入错误\n\n'

        if not self._valid_num(input_each_grid_qty):
            all_okay = False
            error_msg += '每格数量输入错误\n\n'

        if not self._valid_num(input_symbol_leverage):
            all_okay = False
            error_msg += '合约杠杆输入错误\n\n'
        else:
            leverage = int(float(input_symbol_leverage))
            if not (leverage >= 1):
                all_okay = False
                error_msg += '合约杠杆数值过小\n\n'

        if self.select_pending_trigger.isChecked():
            if not self._valid_num(input_pending_trigger):
                all_okay = False
                error_msg += '触发价格输入错误\n\n'

        if self.select_grid_abs_step.isChecked():
            if not self._valid_num(input_grid_abs_step):
                all_okay = False
                error_msg += '网格间距输入错误\n\n'
        elif self.select_grid_rel_step.isChecked():
            if not self._valid_num(input_grid_rel_step):
                all_okay = False
                error_msg += '比例间距输入错误\n\n'

        if not self._valid_num(input_filling_price_step):
            all_okay = False
            error_msg += '补仓价差输入错误\n\n'

        if not self._valid_num(input_lower_price_step):
            all_okay = False
            error_msg += '下方价差输入错误\n\n'

        if not self._valid_num(input_max_grid_step):
            all_okay = False
            error_msg += '最大网格间距输入错误\n\n'

        if not self._valid_num(input_lower_buffer_price):
            all_okay = False
            error_msg += '下方缓冲价差输入错误\n\n'

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
        input_param_dict['each_grid_qty'] = float(self.input_each_grid_qty.text())
        input_param_dict['leverage'] = int(float(self.input_leverage.text()))
        input_param_dict['trigger_start'] = True if self.select_pending_trigger.isChecked() else False
        input_param_dict['pending_trigger_price'] = float(self.input_pending_trigger.text()) if self.select_pending_trigger.isChecked() else ''
        input_param_dict['dul_selection'] = self._get_dul_selection()
        input_param_dict['grid_abs_step'] = float(self.input_grid_abs_step.text()) if self.select_grid_abs_step.isChecked() else ''
        input_param_dict['grid_rel_step'] = float(self.input_grid_rel_step.text()) if self.select_grid_rel_step.isChecked() else ''
        input_param_dict['filling_price_step'] = float(self.input_filling_price_step.text())
        input_param_dict['lower_price_step'] = float(self.input_lower_price_step.text())
        input_param_dict['max_grid_step'] = float(self.input_max_grid_step.text())
        input_param_dict['lower_buffer_price'] = float(self.input_lower_buffer_price.text())
        input_param_dict['alpha'] = self._get_alpha()

        return input_param_dict

    def update_text(self, updated_params: dict) -> None:

        self.input_symbol_name.setText(str(updated_params['symbol_name']))
        self.input_up_price.setText(str(updated_params['up_price']))
        self.input_each_grid_qty.setText(str(updated_params['each_grid_qty']))
        self.input_leverage.setText(str(updated_params['leverage']))
        self.input_pending_trigger.setText(str(updated_params['pending_trigger_price']))
        self.input_grid_abs_step.setText(str(updated_params['grid_abs_step']))
        self.input_grid_rel_step.setText(str(updated_params['grid_rel_step']))
        self.input_filling_price_step.setText(str(updated_params['filling_price_step']))
        self.input_lower_price_step.setText(str(updated_params['lower_price_step']))
        self.input_max_grid_step.setText(str(updated_params['max_grid_step']))
        self.input_lower_buffer_price.setText(str(updated_params['lower_buffer_price']))

    def _get_dul_selection(self) -> int:
        if self.select_grid_abs_step.isChecked():
            return 1
        elif self.select_grid_rel_step.isChecked():
            return 2

    def _get_alpha(self) -> float:
        """
        根据刻度值获取参数alpha值
        :return:
        """
        tick_value = self.slider_alpha.value()
        if tick_value >= 0:
            return tick_value + 1
        else:
            return 1 / (1 - tick_value)


class FrameWithTick(QFrame):
    """
    带有tick的面板，用于显示slider刻度
    """

    def __init__(self):
        super().__init__()

    def paintEvent(self, a0: QPaintEvent) -> None:
        painter = QPainter()
        painter.begin(self)

        # x_start = 0
        # y_start = 0
        # x_step = 11
        # y_height = 4
        # for i in range(19):
        #     painter.drawLine(x_start + i * x_step, y_start, x_start + i * x_step, y_start + y_height)
        tick_height = 3
        painter.drawLine(0, 0, 0, tick_height + 3)  # end
        painter.drawLine(12, 0, 12, tick_height)
        painter.drawLine(23, 0, 23, tick_height)
        painter.drawLine(34, 0, 34, tick_height)
        painter.drawLine(45, 0, 45, tick_height)
        painter.drawLine(56, 0, 56, tick_height)
        painter.drawLine(67, 0, 67, tick_height)
        painter.drawLine(78, 0, 78, tick_height)
        painter.drawLine(89, 0, 89, tick_height)
        painter.drawLine(100, 0, 100, tick_height + 3)  # mid
        painter.drawLine(111, 0, 111, tick_height)
        painter.drawLine(122, 0, 122, tick_height)
        painter.drawLine(133, 0, 133, tick_height)
        painter.drawLine(144, 0, 144, tick_height)
        painter.drawLine(155, 0, 155, tick_height)
        painter.drawLine(166, 0, 166, tick_height)
        painter.drawLine(177, 0, 177, tick_height)
        painter.drawLine(188, 0, 188, tick_height)
        painter.drawLine(199, 0, 199, tick_height + 3)  # end

        painter.end()


if __name__ == '__main__':
    import sys
    import qdarkstyle
    from PyQt5.QtWidgets import QApplication
    from qdarkstyle.light.palette import LightPalette

    app = QApplication(sys.argv)

    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    # app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt5', palette=LightPalette()))

    w = NonlinearStairGridParam()
    w.show()
    app.exec()
