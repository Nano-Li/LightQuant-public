# -*- coding: utf-8 -*-
# @Time : 2023/1/30 9:23 
# @Author : 
# @File : ArithmeticGridParam.py 
# @Software: PyCharm
# from PyQt5 import QtWidgets
import re
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QFrame, QLabel, QRadioButton, QCheckBox, QLineEdit

from .BaseParamWindow import ParamWidget


class ArithmeticGridParam(ParamWidget):
    """
    高级等差网格的参数输入窗口
    """

    param_dict: dict = {
        'symbol_name': None,
        'grid_side': None,
        'up_price': None,
        'down_price': None,
        # 三选一中选择哪个，分别用 int 1, 2, 3 表示
        'tri_selection': None,
        'price_abs_step': None,
        'price_rel_step': None,
        'grid_total_num': None,
        'each_grid_qty': None,
        'leverage': None,

        'need_advance': None,  # bool
        # 二选一中选择哪个，分别用 int 1, 2 表示，0表示都不选
        'dul_selection': None,
        'target_ratio': None,
        'target_price': None,
        'up_boundary_stop': None,  # bool
        'low_boundary_stop': None,  # bool

        'need_stop_loss': None,  # bool
        'max_profit': None,
        'min_profit': None,
    }

    # noinspection PyTypeChecker
    def __init__(self):
        super().__init__()

        self.frame_advance_param: QFrame = None
        self.frame_stop_loss_param: QFrame = None

        self.enable_advance_param: QCheckBox = None
        self.enable_stop_loss_param: QCheckBox = None

        self.label_relative_hint: QLabel = None
        self.select_price_abs_step: QRadioButton = None
        self.select_price_rel_step: QRadioButton = None
        self.select_grid_total_num: QRadioButton = None
        self.select_target_ratio: QCheckBox = None
        self.select_target_price: QCheckBox = None
        self.select_up_price_stop: QCheckBox = None
        self.select_down_price_stop: QCheckBox = None

        self.input_symbol_name: QLineEdit = None
        self.select_side_buy: QCheckBox = None
        self.select_side_sell: QCheckBox = None
        self.select_side_mid: QCheckBox = None
        self.input_up_price: QLineEdit = None
        self.input_down_price: QLineEdit = None
        self.input_price_abs_step: QLineEdit = None
        self.input_price_rel_step: QLineEdit = None
        self.input_grid_total_num: QLineEdit = None
        self.input_each_grid_qty: QLineEdit = None
        self.input_symbol_leverage: QLineEdit = None

        self.input_target_ratio: QLineEdit = None
        self.input_target_price: QLineEdit = None
        self.input_take_profit: QLineEdit = None
        self.input_stop_loss: QLineEdit = None

        # 在基类定义
        # self.btn_validate_param: QPushButton = None
        # self.btn_ref_info: QPushButton = None
        # self.btn_confirm_param: QPushButton = None

        self._init_setting()
        # self._update_widget_status()

    def _init_setting(self):
        # self.setWindowFlags(Qt.WindowStaysOnTopHint)  # 测试用功能
        self.setFixedSize(400, 700)
        self.setWindowTitle('等差网格参数')

        main_frame = QFrame(self)
        main_frame.setGeometry(10, 10, 380, 680)
        main_frame.setFrameStyle((QFrame.Panel | QFrame.Raised))
        # main_frame.setFrameStyle((QFrame.NoFrame | QFrame.Raised))

        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(16)

        # ====================================== 基本参数 ====================================== #
        frame_basic_param = QFrame(main_frame)
        frame_basic_param.setGeometry(20, 20, 340, 301)
        frame_basic_param.setFrameStyle((QFrame.Box | QFrame.Plain))
        frame_basic_param.setObjectName('frame_basic_param')
        frame_basic_param.setStyleSheet("QFrame#frame_basic_param{border-radius: 0px}")
        frame_basic_param.lower()

        label_x = 25
        label_symbol_name = QLabel('合约名称', frame_basic_param)
        label_symbol_name.setFont(temp_font)
        label_symbol_name.setGeometry(label_x, 20, 80, 24)
        self.input_symbol_name = QLineEdit(frame_basic_param)
        self.input_symbol_name.setFont(temp_font)
        self.input_symbol_name.setGeometry(170, 20, 150, 24)
        self.input_symbol_name.textEdited.connect(self._disable_confirm_btn)

        label_grid_side = QLabel('网格方向', frame_basic_param)
        label_grid_side.setFont(temp_font)
        label_grid_side.setGeometry(label_x, 50, 80, 24)
        self.select_side_buy = QCheckBox('做多', frame_basic_param)
        self.select_side_buy.setGeometry(150, 50, 50, 24)
        self.select_side_buy.clicked.connect(
            lambda: (self.select_side_sell.setChecked(False),
                     self.select_side_mid.setChecked(False),
                     self._update_widget_status(),
                     self._disable_confirm_btn())
            if self.select_side_buy.isChecked()
            else (self._update_widget_status(),
                  self._disable_confirm_btn())
        )
        self.select_side_sell = QCheckBox('做空', frame_basic_param)
        self.select_side_sell.setGeometry(210, 50, 50, 24)
        self.select_side_sell.clicked.connect(
            lambda: (self.select_side_buy.setChecked(False),
                     self.select_side_mid.setChecked(False),
                     self._update_widget_status(),
                     self._disable_confirm_btn())
            if self.select_side_sell.isChecked()
            else (self._update_widget_status(),
                  self._disable_confirm_btn())
        )
        self.select_side_mid = QCheckBox('中性', frame_basic_param)
        self.select_side_mid.setGeometry(270, 50, 50, 24)
        self.select_side_mid.clicked.connect(
            lambda: (self.select_side_buy.setChecked(False),
                     self.select_side_sell.setChecked(False),
                     self._update_widget_status(),
                     self._disable_confirm_btn())
            if self.select_side_mid.isChecked()
            else (self._update_widget_status(),
                  self._disable_confirm_btn())
        )

        label_up_price = QLabel('上限价格', frame_basic_param)
        label_up_price.setFont(temp_font)
        label_up_price.setGeometry(label_x, 80, 80, 24)
        self.input_up_price = QLineEdit(frame_basic_param)
        self.input_up_price.setFont(temp_font)
        self.input_up_price.setGeometry(170, 80, 150, 24)
        self.input_up_price.textEdited.connect(self._disable_confirm_btn)

        label_down_price = QLabel('下限价格', frame_basic_param)
        label_down_price.setFont(temp_font)
        label_down_price.setGeometry(label_x, 110, 80, 24)
        self.input_down_price = QLineEdit(frame_basic_param)
        self.input_down_price.setFont(temp_font)
        self.input_down_price.setGeometry(170, 110, 150, 24)
        self.input_down_price.textEdited.connect(self._disable_confirm_btn)

        # todo: 使用 qdarkstyle 反而会导致不对齐, 需要手动设置stylesheet 对齐文字
        radio_x = 12
        self.select_price_abs_step = QRadioButton('数值价差', frame_basic_param)
        self.select_price_abs_step.setFont(temp_font)
        self.select_price_abs_step.setGeometry(radio_x, 140, 88, 24)
        self.select_price_abs_step.setChecked(True)  # 经过测试，radio button 只有初始设置状态有效，动态调整状态无效
        self.select_price_abs_step.toggled.connect(
            lambda: (self.input_price_abs_step.setEnabled(True),
                     self._disable_confirm_btn())
            if self.select_price_abs_step.isChecked()
            else (self.input_price_abs_step.setEnabled(False),
                  self._disable_confirm_btn())
        )
        self.input_price_abs_step = QLineEdit(frame_basic_param)
        self.input_price_abs_step.setFont(temp_font)
        self.input_price_abs_step.setGeometry(170, 140, 150, 24)
        self.input_price_abs_step.textEdited.connect(self._disable_confirm_btn)

        self.select_price_rel_step = QRadioButton('比例价差', frame_basic_param)
        self.select_price_rel_step.setFont(temp_font)
        self.select_price_rel_step.setGeometry(radio_x, 170, 88, 24)
        self.select_price_rel_step.toggled.connect(
            lambda: (self.input_price_rel_step.setEnabled(True),
                     self.label_relative_hint.setEnabled(True),
                     self._disable_confirm_btn())
            if self.select_price_rel_step.isChecked()
            else (self.input_price_rel_step.setEnabled(False),
                  self.label_relative_hint.setEnabled(False),
                  self._disable_confirm_btn())
        )
        self.input_price_rel_step = QLineEdit(frame_basic_param)
        self.input_price_rel_step.setFont(temp_font)
        self.input_price_rel_step.setGeometry(170, 170, 150, 24)
        self.input_price_rel_step.setEnabled(False)
        self.input_price_rel_step.textEdited.connect(self._disable_confirm_btn)
        self.label_relative_hint = QLabel('%', frame_basic_param)
        self.label_relative_hint.setFont(temp_font)
        self.label_relative_hint.setGeometry(302, 170, 16, 24)
        self.label_relative_hint.setStyleSheet("QLabel{background-color: transparent;}")
        self.label_relative_hint.setEnabled(False)
        # todo: 此处使用qdarkstyle会导致文本位置变化，考虑使用lineedit文本提示 QLabel.setPlaceholderText('text hint')

        self.select_grid_total_num = QRadioButton('网格总数', frame_basic_param)
        self.select_grid_total_num.setFont(temp_font)
        self.select_grid_total_num.setGeometry(radio_x, 200, 88, 24)
        self.select_grid_total_num.toggled.connect(
            lambda: (self.input_grid_total_num.setEnabled(True),
                     self._disable_confirm_btn())
            if self.select_grid_total_num.isChecked()
            else (self.input_grid_total_num.setEnabled(False),
                  self._disable_confirm_btn())
        )
        self.input_grid_total_num = QLineEdit(frame_basic_param)
        self.input_grid_total_num.setFont(temp_font)
        self.input_grid_total_num.setGeometry(170, 200, 150, 24)
        self.input_grid_total_num.setEnabled(False)
        self.input_grid_total_num.textEdited.connect(self._disable_confirm_btn)

        label_each_grid_qty = QLabel('每格数量', frame_basic_param)
        label_each_grid_qty.setFont(temp_font)
        label_each_grid_qty.setGeometry(label_x, 230, 80, 24)
        self.input_each_grid_qty = QLineEdit(frame_basic_param)
        self.input_each_grid_qty.setFont(temp_font)
        self.input_each_grid_qty.setGeometry(170, 230, 150, 24)
        self.input_each_grid_qty.textEdited.connect(self._disable_confirm_btn)

        label_symbol_leverage = QLabel('合约杠杆', frame_basic_param)
        label_symbol_leverage.setFont(temp_font)
        label_symbol_leverage.setGeometry(label_x, 260, 80, 24)
        self.input_symbol_leverage = QLineEdit(frame_basic_param)
        self.input_symbol_leverage.setFont(temp_font)
        self.input_symbol_leverage.setGeometry(170, 260, 150, 24)
        self.input_symbol_leverage.textEdited.connect(self._disable_confirm_btn)

        # ====================================== 高级选项 ====================================== #
        self.enable_advance_param = QCheckBox('高级', main_frame)
        self.enable_advance_param.setGeometry(60, 310, 45, 24)
        # self.enable_advance_param.raise_()
        self.enable_advance_param.setChecked(False)
        self.enable_advance_param.stateChanged.connect(
            lambda: (self.frame_advance_param.setEnabled(True),
                     self._disable_confirm_btn())
            if self.enable_advance_param.isChecked()
            else (self.frame_advance_param.setEnabled(False),
                  self._disable_confirm_btn())
        )
        # todo: 理论上，高级选项框不选择时，应该清空高级框内的数据，该任务由 参数修正 完成
        self.frame_advance_param = QFrame(main_frame)
        self.frame_advance_param.setGeometry(20, 320, 340, 151)
        self.frame_advance_param.setFrameStyle((QFrame.Box | QFrame.Plain))
        self.frame_advance_param.setObjectName('frame_advance_param')
        self.frame_advance_param.setStyleSheet("QFrame#frame_advance_param{border-radius: 0px}")
        self.frame_advance_param.setEnabled(False)
        self.frame_advance_param.lower()

        self.select_target_ratio = QCheckBox('看多(空)比例', self.frame_advance_param)
        self.select_target_ratio.setFont(temp_font)
        self.select_target_ratio.setGeometry(radio_x, 20, 118, 24)
        self.select_target_ratio.setChecked(False)
        self.select_target_ratio.stateChanged.connect(
            lambda: (self.input_target_ratio.setEnabled(True),
                     self.select_target_price.setChecked(False),
                     self._disable_confirm_btn())
            if self.select_target_ratio.isChecked()
            else (self.input_target_ratio.setEnabled(False),
                  self._disable_confirm_btn())
        )
        # self.select_target_ratio.clicked.connect(self._update_widget_status)
        self.input_target_ratio = QLineEdit(self.frame_advance_param)
        self.input_target_ratio.setFont(temp_font)
        self.input_target_ratio.setGeometry(170, 20, 150, 24)
        self.input_target_ratio.setEnabled(False)
        self.input_target_ratio.textEdited.connect(self._disable_confirm_btn)

        self.select_target_price = QCheckBox('看多(空)价位', self.frame_advance_param)
        self.select_target_price.setFont(temp_font)
        self.select_target_price.setGeometry(radio_x, 50, 118, 24)
        self.select_target_price.setChecked(False)
        self.select_target_price.stateChanged.connect(  # todo: 输入框unable 后，文字仍然保留，在参数修正按钮中清除
            lambda: (self.input_target_price.setEnabled(True),
                     self.select_target_ratio.setChecked(False),
                     self._disable_confirm_btn())
            if self.select_target_price.isChecked()
            else (self.input_target_price.setEnabled(False),
                  self._disable_confirm_btn)
        )
        # self.select_target_price.stateChanged.connect(self._update_widget_status)
        self.input_target_price = QLineEdit(self.frame_advance_param)
        self.input_target_price.setFont(temp_font)
        self.input_target_price.setGeometry(170, 50, 150, 24)
        self.input_target_price.setEnabled(False)
        self.input_target_price.textEdited.connect(self._disable_confirm_btn)

        self.select_up_price_stop = QCheckBox('上边界终止', self.frame_advance_param)
        self.select_up_price_stop.setFont(temp_font)
        self.select_up_price_stop.setGeometry(radio_x, 80, 108, 24)
        self.select_up_price_stop.clicked.connect(self._disable_confirm_btn)

        self.select_down_price_stop = QCheckBox('下边界终止', self.frame_advance_param)
        self.select_down_price_stop.setFont(temp_font)
        self.select_down_price_stop.setGeometry(radio_x, 110, 108, 24)
        self.select_down_price_stop.clicked.connect(self._disable_confirm_btn)

        # ====================================== 止盈止损 ====================================== #
        self.enable_stop_loss_param = QCheckBox('止盈止损', main_frame)
        self.enable_stop_loss_param.setGeometry(60, 460, 70, 24)
        # self.enable_stop_loss_param.raise_()
        self.enable_stop_loss_param.setChecked(False)
        self.enable_stop_loss_param.stateChanged.connect(
            lambda: (self.frame_stop_loss_param.setEnabled(True),
                     self._disable_confirm_btn())
            if self.enable_stop_loss_param.isChecked()
            else (self.frame_stop_loss_param.setEnabled(False),
                  self._disable_confirm_btn())
        )
        self.frame_stop_loss_param = QFrame(main_frame)
        self.frame_stop_loss_param.setGeometry(20, 470, 340, 91)
        self.frame_stop_loss_param.setFrameStyle((QFrame.Box | QFrame.Plain))
        self.frame_stop_loss_param.setObjectName('frame_stop_loss_param')
        self.frame_stop_loss_param.setStyleSheet("QFrame#frame_stop_loss_param{border-radius: 0px}")
        self.frame_stop_loss_param.setEnabled(False)
        self.frame_stop_loss_param.lower()

        label_take_profit = QLabel('策略止盈', self.frame_stop_loss_param)
        label_take_profit.setFont(temp_font)
        label_take_profit.setGeometry(label_x, 20, 80, 24)
        self.input_take_profit = QLineEdit(self.frame_stop_loss_param)
        self.input_take_profit.setFont(temp_font)
        self.input_take_profit.setGeometry(170, 20, 150, 24)
        self.input_take_profit.textEdited.connect(self._disable_confirm_btn)

        label_stop_loss = QLabel('策略止损', self.frame_stop_loss_param)
        label_stop_loss.setFont(temp_font)
        label_stop_loss.setGeometry(label_x, 50, 80, 24)
        self.input_stop_loss = QLineEdit(self.frame_stop_loss_param)
        self.input_stop_loss.setFont(temp_font)
        self.input_stop_loss.setGeometry(170, 50, 150, 24)
        self.input_stop_loss.textEdited.connect(self._disable_confirm_btn)

        # ====================================== 按钮部分 ====================================== #
        frame_buttons = QFrame(main_frame)
        frame_buttons.setGeometry(20, 560, 340, 100)
        frame_buttons.setFrameStyle((QFrame.Box | QFrame.Plain))
        frame_buttons.setObjectName('frame_buttons')
        frame_buttons.setStyleSheet("QFrame#frame_buttons{border-radius: 0px}")

        # self.btn_validate_param = QPushButton('参数修正', frame_buttons)
        self.btn_validate_param.setParent(frame_buttons)
        self.btn_validate_param.setFont(temp_font)
        self.btn_validate_param.setGeometry(20, 20, 130, 30)
        # self.btn_validate_param.clicked.connect(self.set_readonly)
        # self.btn_ref_info = QPushButton('信息参考', frame_buttons)
        self.btn_ref_info.setParent(frame_buttons)
        self.btn_ref_info.setFont(temp_font)
        self.btn_ref_info.setGeometry(180, 20, 140, 30)
        # self.btn_confirm_param = QPushButton('确认参数', frame_buttons)
        self.btn_confirm_param.setParent(frame_buttons)
        self.btn_confirm_param.setFont(temp_font)
        self.btn_confirm_param.setGeometry(20, 60, 300, 30)
        self.btn_confirm_param.setEnabled(False)

    def _update_widget_status(self) -> None:
        """
        在每次点击相关控件后，更新控件的可选择状态
        :return:
        """
        # print('update status')
        if self.select_side_mid.isChecked():
            self.select_target_ratio.setChecked(False)
            self.select_target_ratio.setEnabled(False)
            self.select_target_price.setChecked(False)
            self.select_target_price.setEnabled(False)
        else:
            self.select_target_ratio.setEnabled(True)
            self.select_target_price.setEnabled(True)

    def reset_all(self) -> None:
        """
        将窗口恢复出厂设置
        :return:
        """
        self.input_symbol_name.clear()
        self.select_side_buy.setChecked(False)
        self.select_side_sell.setChecked(False)
        self.select_side_mid.setChecked(False)
        self.input_up_price.clear()
        self.input_down_price.clear()
        self.input_price_abs_step.clear()
        self.input_price_rel_step.clear()
        self.input_grid_total_num.clear()
        self.input_each_grid_qty.clear()
        self.input_symbol_leverage.clear()
        self.input_target_ratio.clear()
        self.input_target_price.clear()
        self.input_take_profit.clear()
        self.input_stop_loss.clear()

        self.select_price_abs_step.setChecked(True)
        self.select_price_rel_step.setChecked(False)
        self.select_grid_total_num.setChecked(False)

        self.select_target_ratio.setChecked(False)
        self.select_target_price.setChecked(False)
        self.select_up_price_stop.setChecked(False)
        self.select_down_price_stop.setChecked(False)
        self.enable_advance_param.setChecked(False)
        self.enable_stop_loss_param.setChecked(False)

        self.btn_confirm_param.setEnabled(False)

    def check_inputs(self) -> dict:
        """
        检查等差网格输入参数
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
        input_down_price = self.input_down_price.text()
        input_price_abs_step = self.input_price_abs_step.text()
        input_price_rel_step = self.input_price_rel_step.text()
        input_grid_total_num = self.input_grid_total_num.text()
        input_each_grid_qty = self.input_each_grid_qty.text()
        input_symbol_leverage = self.input_symbol_leverage.text()
        input_target_ratio = self.input_target_ratio.text()
        input_target_price = self.input_target_price.text()
        input_take_profit = self.input_take_profit.text()
        input_stop_loss = self.input_stop_loss.text()

        result = re.match(r'^[0-9a-zA-Z_]+$', input_symbol_name)
        if not result:
            all_okay = False
            error_msg += '合约名称输入有误\n\n'

        if (not self.select_side_buy.isChecked()) and (not self.select_side_sell.isChecked()) and (not self.select_side_mid.isChecked()):
            all_okay = False
            error_msg += '未选择网格方向\n\n'

        if not self._valid_num(input_up_price):
            all_okay = False
            error_msg += '上限价格输入错误\n\n'

        if not self._valid_num(input_down_price):
            all_okay = False
            error_msg += '下限价格输入错误\n\n'

        if self.select_price_abs_step.isChecked():
            if not self._valid_num(input_price_abs_step):
                all_okay = False
                error_msg += '数值价差输入错误\n\n'
        elif self.select_price_rel_step.isChecked():
            if not self._valid_num(input_price_rel_step):
                all_okay = False
                error_msg += '比例价差输入错误\n\n'
        elif self.select_grid_total_num.isChecked():
            if not self._valid_num(input_grid_total_num):
                all_okay = False
                error_msg += '网格总数输入错误\n\n'
            else:
                grid_total_num = int(input_grid_total_num)
                if grid_total_num < 5:
                    all_okay = False
                    error_msg += '网格数量数值过小\n'

        if not self._valid_num(input_symbol_leverage):
            all_okay = False
            error_msg += '合约杠杆输入错误\n\n'
        else:
            leverage = int(float(input_symbol_leverage))
            if not (leverage >= 1):
                all_okay = False
                error_msg += '合约杠杆数值过小\n'

        if not self._valid_num(input_each_grid_qty):
            all_okay = False
            error_msg += '每格数量输入错误\n\n'

        if self.enable_advance_param.isChecked():
            if self.select_target_ratio.isChecked():
                if not self._valid_num(input_target_ratio):
                    all_okay = False
                    error_msg += '看多(空)比例输入错误\n\n'
            elif self.select_target_price.isChecked():
                if not self._valid_num(input_target_price):
                    all_okay = False
                    error_msg += '看多(空)价位输入错误\n\n'

        if self.enable_stop_loss_param.isChecked():
            if input_take_profit != '':
                if not self._valid_num(input_take_profit):
                    all_okay = False
                    error_msg += '策略止盈输入错误\n\n'
            if input_stop_loss != '':
                if not self._valid_num(input_stop_loss):
                    all_okay = False
                    error_msg += '策略止损输入错误\n\n'

        if all_okay:
            return status_return
        else:
            status_return['okay'] = all_okay
            status_return['msg'] = error_msg
            return status_return

    def remove_redundant(self) -> None:
        """
        根据选择内容，移除多余输入
        :return: 
        """
        if self.select_side_mid.isChecked():
            self.select_target_ratio.setChecked(False)
            self.select_target_price.setChecked(False)
            self.input_target_ratio.clear()
            self.input_target_price.clear()

        # 反正三项都最后都会更新，不需要清除
        # if not self.select_price_abs_step.isChecked():
        #     self.input_price_abs_step.clear()
        # if not self.select_price_rel_step.isChecked():
        #     self.input_price_rel_step.clear()
        # if not self.select_grid_total_num.isChecked():
        #     self.input_grid_total_num.clear()

        if not self.enable_advance_param.isChecked():
            self.select_target_ratio.setChecked(False)
            self.select_target_price.setChecked(False)
            self.input_target_ratio.clear()
            self.input_target_price.clear()
            self.select_up_price_stop.setChecked(False)
            self.select_down_price_stop.setChecked(False)

        if not self.enable_stop_loss_param.isChecked():
            self.input_take_profit.clear()
            self.input_stop_loss.clear()

        if self.select_target_ratio.isChecked() or \
                self.select_target_price.isChecked() or \
                self.select_up_price_stop.isChecked() or \
                self.select_down_price_stop.isChecked():
            pass
        else:
            self.enable_advance_param.setChecked(False)

        if len(self.input_take_profit.text()) == 0 and len(self.input_stop_loss.text()) == 0:
            self.enable_stop_loss_param.setChecked(False)

    def get_input_params(self) -> dict:
        input_param_dict = self.param_dict.copy()

        input_param_dict['symbol_name'] = self.input_symbol_name.text()
        input_param_dict['grid_side'] = self._get_side()
        input_param_dict['up_price'] = float(self.input_up_price.text())
        input_param_dict['down_price'] = float(self.input_down_price.text())
        input_param_dict['tri_selection'] = self._get_tri_selection()
        input_param_dict['price_abs_step'] = float(self.input_price_abs_step.text()) if self.select_price_abs_step.isChecked() else ''
        input_param_dict['price_rel_step'] = float(self.input_price_rel_step.text()) if self.select_price_rel_step.isChecked() else ''
        input_param_dict['grid_total_num'] = int(self.input_grid_total_num.text()) if self.select_grid_total_num.isChecked() else ''
        input_param_dict['each_grid_qty'] = float(self.input_each_grid_qty.text())
        input_param_dict['leverage'] = int(float(self.input_symbol_leverage.text()))
        input_param_dict['need_advance'] = True if self.enable_advance_param.isChecked() else False
        input_param_dict['dul_selection'] = self._get_dul_selection()
        input_param_dict['target_ratio'] = float(self.input_target_ratio.text()) if self.select_target_ratio.isChecked() else ''
        input_param_dict['target_price'] = float(self.input_target_price.text()) if self.select_target_price.isChecked() else ''
        input_param_dict['up_boundary_stop'] = True if self.select_up_price_stop.isChecked() else False
        input_param_dict['low_boundary_stop'] = True if self.select_down_price_stop.isChecked() else False
        input_param_dict['need_stop_loss'] = True if self.enable_stop_loss_param.isChecked() else False
        input_param_dict['max_profit'] = float(self.input_take_profit.text()) if len(self.input_take_profit.text()) > 0 else ''
        input_param_dict['min_profit'] = float(self.input_stop_loss.text()) if len(self.input_stop_loss.text()) > 0 else ''

        return input_param_dict

    def update_text(self, updated_params: dict) -> None:
        """
        根据新的参数字典，更新显示的文字
        :param updated_params:
        :return:
        """
        # todo: use pandas
        # todo: check redundant
        self.input_symbol_name.setText(updated_params['symbol_name'])
        self.input_up_price.setText(str(updated_params['up_price']))
        self.input_down_price.setText(str(updated_params['down_price']))
        # self.input_.setText(str(updated_params['tri_selection']))
        self.input_price_abs_step.setText(str(updated_params['price_abs_step']))
        self.input_price_rel_step.setText(str(updated_params['price_rel_step']))
        self.input_grid_total_num.setText(str(updated_params['grid_total_num']))
        self.input_each_grid_qty.setText(str(updated_params['each_grid_qty']))
        self.input_symbol_leverage.setText(str(updated_params['leverage']))
        # self.input_.setText(str(updated_params['need_advance']))
        # self.input_.setText(str(updated_params['dul_selection']))
        self.input_target_ratio.setText(str(updated_params['target_ratio']))
        self.input_target_price.setText(str(updated_params['target_price']))
        # self.input_.setText(str(updated_params['need_stop_loss']))
        self.input_take_profit.setText(str(updated_params['max_profit']))
        self.input_stop_loss.setText(str(updated_params['min_profit']))

    def _get_side(self):
        # todo: 考虑用统一的 token 定义做多做空
        if self.select_side_buy.isChecked():
            return 'BUY'
        elif self.select_side_sell.isChecked():
            return 'SELL'
        elif self.select_side_mid.isChecked():
            return 'MID'

    def _get_tri_selection(self) -> int:
        if self.select_price_abs_step.isChecked():
            return 1
        elif self.select_price_rel_step.isChecked():
            return 2
        elif self.select_grid_total_num.isChecked():
            return 3

    def _get_dul_selection(self) -> int:
        if self.select_target_ratio.isChecked():
            return 1
        elif self.select_target_price.isChecked():
            return 2
        else:
            return 0


if __name__ == '__main__':
    import sys
    import qdarkstyle
    from PyQt5.QtWidgets import QApplication
    from qdarkstyle.light.palette import LightPalette

    app = QApplication(sys.argv)

    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    # app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt5', palette=LightPalette()))

    w = ArithmeticGridParam()
    w.show()
    app.exec()
