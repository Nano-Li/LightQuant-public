# -*- coding: utf-8 -*-
# @Time : 2023/1/17 10:06 
# @Author : 
# @File : TradeUI.py
# @Software: PyCharm
import time
import asyncio
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QBoxLayout,
    QDockWidget, QLabel, QPushButton, QScrollArea, QSplitter,
    QComboBox, QGroupBox, QTextBrowser, QListView, QStackedLayout
)
from PyQt5 import sip, QtGui


class RunningStgColumn(QGroupBox):

    # noinspection PyTypeChecker
    def __init__(self, symbol_name: str = None):
        super().__init__()
        self.symbol_name: str = symbol_name

        self.text_symbol_name: QLabel = None
        self.stg_num = None
        # 策略是否正在运行，策略是否被结束，用于控制相关按钮
        self._started = False
        # 所有按钮
        self.btn_start_stg = None
        self.btn_check_param = None
        self.btn_stop_stg = None
        # showing trading data
        self.num_matched_profit: QLabel = None
        self.num_unmatched_profit: QLabel = None

        # 设置点击响应
        self._is_selected = False
        self.clicked.connect(self._column_select)

        self._init_setting()

    def _init_setting(self):
        self.setFixedHeight(60)
        # self.setObjectName('stg_col_frame')
        # todo: further study, more styles
        # self.setStyleSheet("QWidget{border: 3px solid #FF0000;}")
        self.setStyleSheet("QGroupBox{margin-top:0px;} QGroupBox:title {margin-top:0px;}")
        # self.setStyleSheet("QGroupBox{margin-top:0px; border:1px solid gray;} QGroupBox:title {margin-top:0px;}")
        # self.setLineWidth(3)
        # self.setMidLineWidth(3)

        # 整体为水平布局
        column_layout = QHBoxLayout()
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(0)

        # ==================== 合约文字部分 ==================== #
        left_frame = QFrame(self)
        left_frame.setFixedSize(400, 48)
        # left_frame.setFrameStyle((QFrame.WinPanel | QFrame.Plain))

        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(20)

        self.text_symbol_name = QLabel(self.symbol_name, left_frame)
        self.text_symbol_name.setFont(temp_font)
        self.text_symbol_name.setGeometry(14, 9, 140, 30)

        temp_font.setPixelSize(12)
        text_matched_profit = QLabel('已套利：', left_frame)
        text_matched_profit.setFont(temp_font)
        text_matched_profit.setGeometry(180, 30, 50, 16)

        self.num_matched_profit = QLabel('0', left_frame)
        self.num_matched_profit.setFont(temp_font)
        self.num_matched_profit.setGeometry(230, 30, 60, 16)

        text_unmatched_profit = QLabel('未配对：', left_frame)
        text_unmatched_profit.setFont(temp_font)
        text_unmatched_profit.setGeometry(290, 30, 50, 16)

        self.num_unmatched_profit = QLabel('0', left_frame)
        self.num_unmatched_profit.setFont(temp_font)
        self.num_unmatched_profit.setGeometry(340, 30, 60, 16)

        # ==================== 右边按钮部分 ==================== #
        right_frame = QFrame()
        right_frame.setFixedSize(280, 48)

        temp_font.setPixelSize(12)
        self.btn_start_stg = QPushButton('开始运行', right_frame)
        self.btn_start_stg.setFont(temp_font)
        self.btn_start_stg.setAutoRepeat(False)
        self.btn_start_stg.setGeometry(10, 18, 75, 28)
        self.btn_start_stg.clicked.connect(self._start_running)
        self.btn_check_param = QPushButton('修改参数', right_frame)
        self.btn_check_param.setFont(temp_font)
        self.btn_check_param.setAutoRepeat(False)
        self.btn_check_param.setGeometry(100, 18, 75, 28)
        self.btn_check_param.clicked.connect(self._change_params)
        self.btn_stop_stg = QPushButton('停止策略', right_frame)
        self.btn_stop_stg.setFont(temp_font)
        self.btn_stop_stg.setEnabled(False)
        self.btn_stop_stg.setAutoRepeat(False)
        self.btn_stop_stg.setGeometry(190, 18, 75, 28)
        self.btn_stop_stg.clicked.connect(self._stop_running)

        column_layout.addWidget(left_frame)
        column_layout.addStretch()
        column_layout.addWidget(right_frame)

        self.setLayout(column_layout)
        self.setLayout(column_layout)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def _column_select(self) -> None:
        if self._is_selected:
            print('{} column unselect'.format(self.symbol_name))
            self.turn_unselected_frame_mode()
        else:
            print('{} column selected'.format(self.symbol_name))
            self.turn_selected_frame_mode()

    def turn_selected_frame_mode(self) -> None:
        """
        该方框被选中，转换为选中模式，需要在外部被调用
        :return:
        """
        self._is_selected = True
        self.setStyleSheet("QGroupBox{margin-top:0px; border:1px solid gray;} QGroupBox:title {margin-top:0px;}")

    def turn_unselected_frame_mode(self) -> None:
        """
        方框取消选中，转换为默认模式
        :return:
        """
        self._is_selected = False
        self.setStyleSheet("QGroupBox{margin-top:0px;} QGroupBox:title {margin-top:0px;}")

    def set_column_name(self):
        pass

    def _start_running(self):
        if self._started:
            return
        print('stg start running')
        self._started = True
        self.btn_start_stg.setEnabled(False)
        self.btn_start_stg.setText('正在运行')
        self.btn_check_param.setText('查看参数')
        self.btn_stop_stg.setEnabled(True)
        time.sleep(0.5)

    def _change_params(self):
        pass

    def _stop_running(self) -> None:
        print('stg stop running')

    async def renew_text(self, interval_time: int = 60):
        pass

    def update_profit_text(self, matched_profit: str, unmatched_profit: str) -> None:
        # todo: 该方法为 Analyzer 主动更新信息, 考虑是否使用 async
        self.num_matched_profit.setText(matched_profit)
        self.num_unmatched_profit.setText(unmatched_profit)

    def update_trade_info(self, showing_info: str) -> None:
        pass

    def update_trade_orders(self, appending_info: str) -> None:
        pass

    def __del__(self):
        print('Running stg column 实例被删除')


class StoppedStgColumn(QGroupBox):

    # noinspection PyTypeChecker
    def __init__(self, symbol_name: str = None):
        super().__init__()
        self.symbol_name = symbol_name
        self.text_symbol_name: QLabel = None
        self.stg_num = None

        # all buttons
        self.btn_stg_stopped: QPushButton = None
        self.btn_check_detail: QPushButton = None
        self.btn_del_record: QPushButton = None
        # showing data
        self.num_stg_profit: QLabel = None

        # 设置点击响应
        self._is_selected = False
        self.clicked.connect(self._column_select)

        self._init_setting()

    def _init_setting(self):
        self.setFixedHeight(60)
        self.setStyleSheet("QGroupBox{margin-top:0px;} QGroupBox:title {margin-top:0px;}")

        # 整体为水平布局
        column_layout = QHBoxLayout()
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(0)

        # ==================== 合约文字部分 ==================== #
        left_frame = QFrame(self)
        left_frame.setFixedSize(320, 48)

        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(20)

        self.text_symbol_name = QLabel(self.symbol_name, left_frame)
        self.text_symbol_name.setFont(temp_font)
        self.text_symbol_name.setGeometry(14, 9, 140, 30)

        temp_font.setPixelSize(12)
        text_stg_profit = QLabel('策略收益：', left_frame)
        text_stg_profit.setFont(temp_font)
        text_stg_profit.setGeometry(190, 30, 60, 16)

        self.num_stg_profit = QLabel('0', left_frame)
        self.num_stg_profit.setFont(temp_font)
        self.num_stg_profit.setGeometry(250, 30, 60, 16)

        # ==================== 右边按钮部分 ==================== #
        right_frame = QFrame()
        right_frame.setFixedSize(280, 48)

        temp_font.setPixelSize(12)
        self.btn_stg_stopped = QPushButton('已停止', right_frame)
        self.btn_stg_stopped.setFont(temp_font)
        self.btn_stg_stopped.setEnabled(False)
        self.btn_stg_stopped.setGeometry(10, 18, 75, 28)
        self.btn_check_detail = QPushButton('查看详情', right_frame)
        self.btn_check_detail.setFont(temp_font)
        self.btn_check_detail.setAutoRepeat(False)
        self.btn_check_detail.setGeometry(100, 18, 75, 28)
        self.btn_check_detail.clicked.connect(self._check_detail)
        self.btn_del_record = QPushButton('删除记录', right_frame)
        self.btn_del_record.setFont(temp_font)
        self.btn_del_record.setAutoRepeat(False)
        self.btn_del_record.setGeometry(190, 18, 75, 28)
        self.btn_del_record.clicked.connect(self._delete_record)

        column_layout.addWidget(left_frame)
        column_layout.addStretch()
        column_layout.addWidget(right_frame)

        self.setLayout(column_layout)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def _column_select(self) -> None:
        if self._is_selected:
            print('{} column unselect'.format(self.symbol_name))
            self.turn_unselected_frame_mode()
        else:
            print('{} column selected'.format(self.symbol_name))
            self.turn_selected_frame_mode()

    def turn_selected_frame_mode(self) -> None:
        """
        该方框被选中，转换为选中模式
        :return:
        """
        self._is_selected = True
        self.setStyleSheet("QGroupBox{margin-top:0px; border:1px solid gray;} QGroupBox:title {margin-top:0px;}")

    def turn_unselected_frame_mode(self) -> None:
        """
        方框取消选中，转换为默认模式
        :return:
        """
        self._is_selected = False
        self.setStyleSheet("QGroupBox{margin-top:0px;} QGroupBox:title {margin-top:0px;}")

    def _check_detail(self):
        pass

    def _delete_record(self):
        pass

    async def show_profit(self):
        pass

    def __del__(self):
        print('Stopped stg column 实例被删除')


class SubAccountColumn(QGroupBox):

    # noinspection PyTypeChecker
    def __init__(self, account_series: str = None):
        super().__init__()
        self.account_series: str = account_series

        self.text_account_name: QLabel = None
        # self.account_num = None
        # showing trading data
        self.num_total_asset: QLabel = None
        self.num_margin: QLabel = None

        # 设置点击响应
        self._is_selected = False
        self.clicked.connect(self._column_select)

        self._init_setting()

    def _init_setting(self):
        self.setFixedHeight(60)
        # self.setObjectName('stg_col_frame')
        # todo: further study, more styles
        # self.setStyleSheet("QWidget{border: 3px solid #FF0000;}")
        self.setStyleSheet("QGroupBox{margin-top:0px;} QGroupBox:title {margin-top:0px;}")
        # self.setStyleSheet("QGroupBox{margin-top:0px; border:1px solid gray;} QGroupBox:title {margin-top:0px;}")
        # self.setLineWidth(3)
        # self.setMidLineWidth(3)

        # 整体为水平布局
        column_layout = QHBoxLayout()
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(0)

        # ==================== 账号文字部分 ==================== #
        left_frame = QFrame(self)
        left_frame.setFixedSize(320, 48)
        # left_frame.setFrameStyle((QFrame.WinPanel | QFrame.Plain))

        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(20)

        self.text_symbol_name = QLabel(f'账号 {self.account_series}', left_frame)
        self.text_symbol_name.setFont(temp_font)
        self.text_symbol_name.setGeometry(14, 9, 140, 30)

        temp_font.setPixelSize(12)
        text_total_asset = QLabel('资产：', left_frame)
        text_total_asset.setFont(temp_font)
        text_total_asset.setGeometry(180, 30, 50, 16)

        self.num_total_asset = QLabel('0', left_frame)
        self.num_total_asset.setFont(temp_font)
        self.num_total_asset.setGeometry(230, 30, 60, 16)

        # ==================== 右边部分 ==================== #
        right_frame = QFrame()
        right_frame.setFixedSize(160, 48)

        temp_font.setPixelSize(12)
        text_margin = QLabel('保证金：', right_frame)
        text_margin.setFont(temp_font)
        text_margin.setGeometry(30, 30, 50, 16)

        self.num_margin = QLabel('0', right_frame)
        self.num_margin.setFont(temp_font)
        self.num_margin.setGeometry(80, 30, 60, 16)

        column_layout.addWidget(left_frame)
        column_layout.addStretch()
        column_layout.addWidget(right_frame)

        self.setLayout(column_layout)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def _column_select(self) -> None:
        if self._is_selected:
            self.turn_unselected_frame_mode()
        else:
            self.turn_selected_frame_mode()

    def turn_selected_frame_mode(self) -> None:
        """
        该方框被选中，转换为选中模式，需要在外部被调用
        :return:
        """
        self._is_selected = True
        self.setStyleSheet("QGroupBox{margin-top:0px; border:1px solid gray;} QGroupBox:title {margin-top:0px;}")

    def turn_unselected_frame_mode(self) -> None:
        """
        方框取消选中，转换为默认模式
        :return:
        """
        self._is_selected = False
        self.setStyleSheet("QGroupBox{margin-top:0px;} QGroupBox:title {margin-top:0px;}")

    def renew_account_info(self, asset: str, margin: str) -> None:
        self.num_total_asset.setText(asset)
        self.num_margin.setText(margin)

    def update_account_info(self, showing_info: str) -> None:
        pass

    def update_account_orders(self, appending_info: str) -> None:
        pass

    def __del__(self):
        print('Running stg column 实例被删除')


class DetailRegion(QDockWidget):
    """
    策略详情区域，显示单个策略的详细信息
    在主ui的右上方区域
    """

    def __init__(self):
        super().__init__('策略详情')
        self.setMinimumSize(200, 88)
        self.all_browsers = QStackedLayout()
        self.init_setting()

    def init_setting(self):
        self.setFeatures(QDockWidget.NoDockWidgetFeatures)

        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(14)

        content_frame = QFrame()

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)

        content_layout.addLayout(self.all_browsers)
        content_frame.setLayout(content_layout)
        self.setFont(temp_font)
        self.setWidget(content_frame)

#         temp_font.setPixelSize(12)
#         stg_info = QTextBrowser()
#         stg_info.setFont(temp_font)
#         test_txt = """
# ==============
# statistics
# ==============
#         """
#         stg_info.setText(test_txt)
#
#         self.setWidget(stg_info)


class OrderRegion(QDockWidget):
    """
    更新订单详情区域，显示单个策略的orders详情
    在主ui的右下方区域
    """

    def __init__(self):
        super().__init__('成交订单')
        self.setMinimumSize(200, 88)
        self.all_browsers = QStackedLayout()
        self.init_setting()

    def init_setting(self):
        self.setFeatures(QDockWidget.NoDockWidgetFeatures)

        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(14)

        content_frame = QFrame()

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)

        content_layout.addLayout(self.all_browsers)
        content_frame.setLayout(content_layout)
        self.setFont(temp_font)
        self.setWidget(content_frame)

#         temp_font.setPixelSize(12)
#         stg_info = QTextBrowser()
#         stg_info.setFont(temp_font)
#         test_txt = """\n\n\n
# ==============
# statistics
# ==============
#             """
#         stg_info.setText(test_txt)
#
#         self.setWidget(stg_info)


class TradingRegion(QVBoxLayout):
    # noinspection PyTypeChecker
    def __init__(self):
        super().__init__()
        self.setContentsMargins(8, 8, 8, 8)
        self.column_layout: QVBoxLayout = QVBoxLayout()
        self.column_layout.setAlignment(Qt.AlignTop)
        self.column_layout.setDirection(QBoxLayout.BottomToTop)
        # push buttons
        self.btn_connect_api: QPushButton = None
        self.stg_selector: QComboBox = None
        self.btn_create_stg: QPushButton = None
        self.btn_shutdown_all: QPushButton = None

        self.init_setting()

    def init_setting(self):
        # ==================== top ==================== #
        top_content = QHBoxLayout()

        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(16)
        # left title part
        left_part = QFrame()
        left_part.setFixedSize(180, 36)

        region_title = QLabel('运行策略', left_part)
        region_title.setFont(temp_font)
        region_title.setGeometry(3, 3, 80, 30)

        temp_font.setPixelSize(12)
        self.btn_connect_api = QPushButton('连接API', left_part)
        self.btn_connect_api.setFont(temp_font)
        self.btn_connect_api.setGeometry(88, 6, 80, 24)
        self.btn_connect_api.setAutoRepeat(False)

        # right btn part
        right_part = QFrame()
        right_part.setFixedSize(348, 36)

        self.stg_selector = QComboBox(right_part)
        # self.stg_selector.setParent(right_part)
        self.stg_selector.setFont(temp_font)
        self.stg_selector.setGeometry(10, 6, 120, 24)
        self.stg_selector.setEditable(True)
        self.stg_selector.lineEdit().setAlignment(Qt.AlignCenter)
        self.stg_selector.lineEdit().setReadOnly(True)
        self.stg_selector.setStyleSheet("QAbstractItemView::item {height: 24px;}")
        self.stg_selector.setView(QListView())
        # self.stg_selector.addItems(['等差网格', '等比网格'])

        self.btn_create_stg = QPushButton('新建策略', right_part)
        self.btn_create_stg.setFont(temp_font)
        self.btn_create_stg.setGeometry(144, 3, 90, 30)
        self.btn_create_stg.setAutoRepeat(False)
        # self.btn_create_stg.clicked.connect(self._create_new_stg)

        self.btn_shutdown_all = QPushButton('一键停止', right_part)
        self.btn_shutdown_all.setFont(temp_font)
        self.btn_shutdown_all.setGeometry(254, 3, 90, 30)
        self.btn_shutdown_all.setAutoRepeat(False)
        # self.btn_shutdown_all.clicked.connect(self._delete_a_stg)

        top_content.addWidget(left_part)
        top_content.addStretch()
        top_content.addWidget(right_part)

        # ==================== body ==================== #
        trading_window = QScrollArea()
        trading_window.setWidgetResizable(True)
        # trading_window.setMinimumWidth(450)
        trading_window.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        trading_window_frame = QFrame()
        self.column_layout.setContentsMargins(12, 12, 12, 12)
        self.column_layout.setSpacing(16)

        # for _ in range(12):
        #     each_stg_column = RunningStgColumn('DOGEUSDT')
        #     each_stg_column.stg_num = 'Stg' + str(_)
        #     self.column_layout.addWidget(each_stg_column)

        trading_window_frame.setLayout(self.column_layout)
        trading_window.setWidget(trading_window_frame)

        self.addLayout(top_content)
        self.addWidget(trading_window)

    def _create_new_stg(self):
        print('creat stg')
        add_stg = RunningStgColumn('APTUSDT')
        self.column_layout.addWidget(add_stg)

    def _delete_a_stg(self):
        print('deleted stg')
        last_item_index = self.column_layout.count() - 1
        if last_item_index < 0:
            print('列表为空，无法删除')
            return
        stg_col = self.column_layout.itemAt(last_item_index).widget()
        self.column_layout.removeWidget(stg_col)
        sip.delete(stg_col)


class TradedRegion(QVBoxLayout):
    # noinspection PyTypeChecker
    def __init__(self):
        super().__init__()
        self.setContentsMargins(8, 8, 8, 8)
        self.column_layout: QVBoxLayout = QVBoxLayout()
        self.column_layout.setAlignment(Qt.AlignTop)
        self.column_layout.setDirection(QBoxLayout.BottomToTop)

        self.btn_disconnect_api: QPushButton = None
        self.btn_statistic_all: QPushButton = None
        self.btn_clear_all: QPushButton = None

        self.init_setting()

    def init_setting(self):
        # ==================== top ==================== #
        top_content = QHBoxLayout()

        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(16)
        # left title part
        left_part = QFrame()
        left_part.setFixedSize(180, 36)

        region_title = QLabel('停止策略', left_part)
        region_title.setFont(temp_font)
        region_title.setGeometry(3, 3, 80, 30)

        temp_font.setPixelSize(12)
        self.btn_disconnect_api = QPushButton('断开API', left_part)
        self.btn_disconnect_api.setFont(temp_font)
        self.btn_disconnect_api.setGeometry(88, 6, 80, 24)
        self.btn_disconnect_api.setAutoRepeat(False)
        # right btn part
        right_part = QFrame()
        right_part.setFixedSize(214, 36)

        self.btn_statistic_all = QPushButton('综合统计', right_part)
        self.btn_statistic_all.setFont(temp_font)
        self.btn_statistic_all.setGeometry(10, 3, 90, 30)
        self.btn_statistic_all.setAutoRepeat(False)

        self.btn_clear_all = QPushButton('删除所有', right_part)
        self.btn_clear_all.setFont(temp_font)
        self.btn_clear_all.setGeometry(120, 3, 90, 30)
        self.btn_clear_all.setAutoRepeat(False)
        # self.btn_clear_all.clicked.connect(self._delete_all_col)

        top_content.addWidget(left_part)
        top_content.addStretch()
        top_content.addWidget(right_part)

        # ==================== body ==================== #
        trading_window = QScrollArea()
        trading_window.setWidgetResizable(True)
        trading_window.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        trading_window_frame = QFrame()
        self.column_layout.setContentsMargins(12, 12, 12, 12)
        self.column_layout.setSpacing(16)

        # for _ in range(6):
        #     each_stg_column = StoppedStgColumn('APTUSDT')
        #     each_stg_column.stg_num = 'strategy' + str(_)
        #     self.column_layout.addWidget(each_stg_column)

        trading_window_frame.setLayout(self.column_layout)
        trading_window.setWidget(trading_window_frame)

        self.addLayout(top_content)
        self.addWidget(trading_window)

    def _delete_all_col(self):
        print('deleted column')
        last_item_index = self.column_layout.count() - 1
        if last_item_index < 0:
            print('列表为空，无法删除')
            return
        stg_col = self.column_layout.itemAt(last_item_index).widget()
        self.column_layout.removeWidget(stg_col)
        # sip.delete(stg_col)


class TradeUI(QFrame):

    # noinspection PyTypeChecker
    def __init__(self):
        super().__init__()
        self.trading_window = TradingRegion()
        self.traded_window = TradedRegion()
        self.detail_region = DetailRegion()
        self.order_region = OrderRegion()
        # save all buttons
        self.btn_connect_api: QPushButton = None
        self.stg_selector: QComboBox = None
        self.btn_create_stg: QPushButton = None
        self.btn_shutdown_all: QPushButton = None

        self.btn_disconnect_api: QPushButton = None
        self.btn_statistic_all: QPushButton = None
        self.btn_clear_all: QPushButton = None

        self._set_buttons()

        self.init_ui()
        self.resize(1400, 800)
        # self.showMaximized()

        self.window_title = 'Trader'

    def init_ui(self):
        self.setObjectName('main_frame')
        # todo: set proper frame color
        # self.setStyleSheet("QFrame#main_frame{border:1px solid white;border-radius: 0px}")
        main_container = QHBoxLayout()
        main_container.setContentsMargins(0, 0, 0, 0)

        left_top = QFrame()
        left_top.setFrameShape((QFrame.Box | QFrame.Plain))
        left_top.setLayout(self.trading_window)

        left_bottom = QFrame()
        left_bottom.setFrameShape((QFrame.Box | QFrame.Plain))
        left_bottom.setLayout(self.traded_window)

        # right_top = QFrame()
        # right_top.setFrameShape(QFrame.StyledPanel)
        right_top = QFrame()
        right_top.setObjectName('right_top_region')
        right_top.setStyleSheet("QFrame#right_top_region{border-radius: 0px;}")
        right_top_layout = QVBoxLayout()
        right_top_layout.setContentsMargins(0, 0, 0, 0)
        right_top_layout.addWidget(self.detail_region)
        right_top.setLayout(right_top_layout)
        # right_top = DetailRegion()

        # right_bottom = QFrame()
        # right_bottom.setFrameShape(QFrame.StyledPanel)
        right_bottom = QFrame()
        right_bottom.setObjectName('right_bottom_region')
        right_bottom.setStyleSheet("QFrame#right_bottom_region{border-radius: 0px;}")
        right_bottom_layout = QVBoxLayout()
        right_bottom_layout.setContentsMargins(0, 2, 0, 0)
        right_bottom_layout.addWidget(self.order_region)
        right_bottom.setLayout(right_bottom_layout)
        # right_bottom = OrdersRegion()

        split_width = 3
        left_region = QFrame()
        left_region.setObjectName('left_main_region')
        left_region.setStyleSheet("QFrame#left_main_region{border-radius: 0px;}")
        left_region_layout = QVBoxLayout()
        left_region_layout.setContentsMargins(0, 0, 2, 0)

        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.setHandleWidth(split_width)
        left_splitter.addWidget(left_top)
        left_splitter.addWidget(left_bottom)
        left_splitter.setSizes([480, 320])

        left_region_layout.addWidget(left_splitter)
        left_region.setLayout(left_region_layout)

        right_region = QFrame()
        right_region.setObjectName('right_main_region')
        right_region.setStyleSheet("QFrame#right_main_region{border-radius: 0px;}")
        right_region_layout = QVBoxLayout()
        right_region_layout.setContentsMargins(2, 0, 0, 0)

        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.setHandleWidth(split_width)
        right_splitter.addWidget(right_top)
        right_splitter.addWidget(right_bottom)
        right_splitter.setSizes([350, 450])

        right_region_layout.addWidget(right_splitter)
        right_region.setLayout(right_region_layout)

        center_splitter = QSplitter(Qt.Horizontal)
        center_splitter.setHandleWidth(split_width)
        center_splitter.addWidget(left_region)
        center_splitter.addWidget(right_region)
        center_splitter.setSizes([960, 440])

        main_container.addWidget(center_splitter)
        self.setLayout(main_container)

    def _set_buttons(self):
        """
        存储并连接所有按钮控件
        :return:
        """
        self.btn_connect_api = self.trading_window.btn_connect_api
        self.stg_selector = self.trading_window.stg_selector
        self.btn_create_stg = self.trading_window.btn_create_stg
        self.btn_shutdown_all = self.trading_window.btn_shutdown_all
        self.btn_disconnect_api = self.traded_window.btn_disconnect_api
        self.btn_statistic_all = self.traded_window.btn_statistic_all
        self.btn_clear_all = self.traded_window.btn_clear_all

        self.btn_connect_api.clicked.connect(self._pop_connect_api_dialog)
        self.btn_create_stg.clicked.connect(self._create_stg)
        self.btn_shutdown_all.clicked.connect(self._shutdown_all_stg)

        self.btn_disconnect_api.clicked.connect(self._disconnect_api)
        self.btn_statistic_all.clicked.connect(self._statistic_all_stg)
        self.btn_clear_all.clicked.connect(self._clear_all_stg)

    def set_window_title(self, title: str = None) -> None:
        """
        设置主窗口名称
        :param title:
        :return:
        """
        if title:
            self.window_title = title
        self.setWindowTitle(self.window_title)

    def _block_window(self) -> None:
        """
        使窗口不可用，一般用于输入参数时
        :return:
        """
        self.setEnabled(False)

    def _enable_window(self) -> None:
        self.setEnabled(True)

    def _pop_connect_api_dialog(self):
        pass

    def _signal_receiver_api_dialog(self, info: int) -> None:
        pass

    def _create_stg(self):
        pass

    def _shutdown_all_stg(self):
        pass

    def _disconnect_api(self):
        pass

    def _statistic_all_stg(self):
        pass

    def _clear_all_stg(self):
        pass

    def _add_running_stg_col(self):
        pass

    def transfer_column(self, trans_stg_num: str):
        pass

    def _delete_stopped_column(self, delete_stg_num: str) -> None:
        pass

    def closeEvent(self, a0: QtGui.QCloseEvent) -> None:
        print('交易UI被关闭')
        super().closeEvent(a0)

    def __del__(self):
        print('交易UI被删除')    # todo: temp config to delete


class AccountRegion(QVBoxLayout):
    # noinspection PyTypeChecker
    def __init__(self):
        super().__init__()
        self.setContentsMargins(8, 8, 8, 8)
        self.column_layout: QVBoxLayout = QVBoxLayout()
        self.column_layout.setAlignment(Qt.AlignTop)
        self.column_layout.setDirection(QBoxLayout.BottomToTop)
        # push buttons
        self.btn_connect_api: QPushButton = None
        self.stg_selector: QComboBox = None
        self.btn_create_stg: QPushButton = None
        self.btn_change_param: QPushButton = None
        self.btn_initialize: QPushButton = None
        self.btn_start_stg: QPushButton = None
        self.btn_stop_stg: QPushButton = None

        self.init_setting()

    def init_setting(self):
        # ==================== top ==================== #
        top_content = QHBoxLayout()

        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(16)
        # left title part
        left_part = QFrame()
        left_part.setFixedSize(180, 36)

        region_title = QLabel('子账户列表', left_part)
        region_title.setFont(temp_font)
        region_title.setGeometry(3, 3, 80, 30)

        temp_font.setPixelSize(12)
        self.btn_connect_api = QPushButton('连接主账号API', left_part)
        self.btn_connect_api.setFont(temp_font)
        self.btn_connect_api.setGeometry(88, 6, 80, 24)
        self.btn_connect_api.setAutoRepeat(False)

        # right btn part
        right_part = QFrame()
        right_part.setFixedSize(600, 36)

        self.stg_selector = QComboBox(right_part)
        # self.stg_selector.setParent(right_part)
        self.stg_selector.setFont(temp_font)
        self.stg_selector.setGeometry(10, 6, 120, 24)
        self.stg_selector.setEditable(True)
        self.stg_selector.lineEdit().setAlignment(Qt.AlignCenter)
        self.stg_selector.lineEdit().setReadOnly(True)
        self.stg_selector.setStyleSheet("QAbstractItemView::item {height: 24px;}")
        self.stg_selector.setView(QListView())
        # self.stg_selector.addItems(['等差网格', '等比网格'])

        self.btn_create_stg = QPushButton('创建策略', right_part)
        self.btn_create_stg.setFont(temp_font)
        self.btn_create_stg.setGeometry(144, 3, 90, 30)
        self.btn_create_stg.setAutoRepeat(False)
        # self.btn_create_stg.clicked.connect(self._create_new_stg)

        self.btn_change_param = QPushButton('查看参数', right_part)
        self.btn_change_param.setFont(temp_font)
        self.btn_change_param.setGeometry(254, 3, 90, 30)
        self.btn_change_param.setAutoRepeat(False)

        self.btn_initialize = QPushButton('初始化', right_part)
        self.btn_initialize.setFont(temp_font)
        self.btn_initialize.setGeometry(356, 3, 90, 30)
        self.btn_initialize.setAutoRepeat(False)

        self.btn_start_stg = QPushButton('开始运行', right_part)
        self.btn_start_stg.setFont(temp_font)
        self.btn_start_stg.setGeometry(450, 3, 90, 30)
        self.btn_start_stg.setAutoRepeat(False)

        self.btn_stop_stg = QPushButton('停止', right_part)
        self.btn_stop_stg.setFont(temp_font)
        self.btn_stop_stg.setGeometry(520, 3, 60, 30)
        self.btn_stop_stg.setAutoRepeat(False)

        top_content.addWidget(left_part)
        top_content.addStretch()
        top_content.addWidget(right_part)

        # ==================== body ==================== #
        account_window = QScrollArea()
        account_window.setWidgetResizable(True)
        # trading_window.setMinimumWidth(450)
        account_window.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        account_window_frame = QFrame()
        self.column_layout.setContentsMargins(12, 12, 12, 12)
        self.column_layout.setSpacing(16)

        # for _ in range(12):
        #     each_stg_column = RunningStgColumn('DOGEUSDT')
        #     each_stg_column.stg_num = 'Stg' + str(_)
        #     self.column_layout.addWidget(each_stg_column)

        account_window_frame.setLayout(self.column_layout)
        account_window.setWidget(account_window_frame)

        self.addLayout(top_content)
        self.addWidget(account_window)


class MarketMakerUI(QFrame):
    """
    适用于多子账号架构的交易界面
    """
    # noinspection PyTypeChecker
    def __init__(self):
        super().__init__()
        self.account_window = AccountRegion()
        self.detail_region = DetailRegion()
        self.order_region = OrderRegion()
        # save all buttons
        self.btn_connect_api: QPushButton = None
        self.stg_selector: QComboBox = None
        self.btn_create_stg: QPushButton = None
        self.btn_change_param: QPushButton = None
        self.btn_initialize: QPushButton = None
        self.btn_start_stg: QPushButton = None
        self.btn_stop_stg: QPushButton = None

        self._set_buttons()

        self.init_ui()
        self.resize(1400, 800)
        # self.showMaximized()

        self.window_title = 'Trader'

    def init_ui(self):
        self.setObjectName('main_frame')
        # todo: set proper frame color
        # self.setStyleSheet("QFrame#main_frame{border:1px solid white;border-radius: 0px}")
        main_container = QHBoxLayout()
        main_container.setContentsMargins(0, 0, 0, 0)

        # left_top = QFrame()
        # left_top.setFrameShape((QFrame.Box | QFrame.Plain))
        # left_top.setLayout(self.trading_window)
        #
        # left_bottom = QFrame()
        # left_bottom.setFrameShape((QFrame.Box | QFrame.Plain))
        # left_bottom.setLayout(self.traded_window)

        # right_top = QFrame()
        # right_top.setFrameShape(QFrame.StyledPanel)
        right_top = QFrame()
        right_top.setObjectName('right_top_region')
        right_top.setStyleSheet("QFrame#right_top_region{border-radius: 0px;}")
        right_top_layout = QVBoxLayout()
        right_top_layout.setContentsMargins(0, 0, 0, 0)
        right_top_layout.addWidget(self.detail_region)
        right_top.setLayout(right_top_layout)
        # right_top = DetailRegion()

        # right_bottom = QFrame()
        # right_bottom.setFrameShape(QFrame.StyledPanel)
        right_bottom = QFrame()
        right_bottom.setObjectName('right_bottom_region')
        right_bottom.setStyleSheet("QFrame#right_bottom_region{border-radius: 0px;}")
        right_bottom_layout = QVBoxLayout()
        right_bottom_layout.setContentsMargins(0, 2, 0, 0)
        right_bottom_layout.addWidget(self.order_region)
        right_bottom.setLayout(right_bottom_layout)
        # right_bottom = OrdersRegion()

        split_width = 3
        left_region = QFrame()
        left_region.setObjectName('left_main_region')
        left_region.setStyleSheet("QFrame#left_main_region{border-radius: 0px;}")
        left_region_layout = QVBoxLayout()
        left_region_layout.setContentsMargins(0, 0, 2, 0)

        # left_splitter = QSplitter(Qt.Vertical)
        # left_splitter.setHandleWidth(split_width)
        # left_splitter.addWidget(left_top)
        # left_splitter.addWidget(left_bottom)
        # left_splitter.setSizes([480, 320])

        # left_region_layout.addWidget(left_splitter)
        left_region.setLayout(self.account_window)

        right_region = QFrame()
        right_region.setObjectName('right_main_region')
        right_region.setStyleSheet("QFrame#right_main_region{border-radius: 0px;}")
        right_region_layout = QVBoxLayout()
        right_region_layout.setContentsMargins(2, 0, 0, 0)

        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.setHandleWidth(split_width)
        right_splitter.addWidget(right_top)
        right_splitter.addWidget(right_bottom)
        right_splitter.setSizes([350, 450])

        right_region_layout.addWidget(right_splitter)
        right_region.setLayout(right_region_layout)

        center_splitter = QSplitter(Qt.Horizontal)
        center_splitter.setHandleWidth(split_width)
        center_splitter.addWidget(left_region)
        center_splitter.addWidget(right_region)
        center_splitter.setSizes([960, 440])

        main_container.addWidget(center_splitter)
        self.setLayout(main_container)

    def _set_buttons(self):
        """
        存储并连接所有按钮控件
        :return:
        """
        self.btn_connect_api = self.account_window.btn_connect_api
        self.stg_selector = self.account_window.stg_selector
        self.btn_create_stg = self.account_window.btn_create_stg
        self.btn_change_param = self.account_window.btn_change_param
        self.btn_initialize = self.account_window.btn_initialize
        self.btn_start_stg = self.account_window.btn_start_stg
        self.btn_stop_stg = self.account_window.btn_stop_stg

        self.btn_connect_api.clicked.connect(self._pop_connect_api_dialog)
        self.btn_create_stg.clicked.connect(self._create_stg)
        self.btn_change_param.clicked.connect(self._check_param)
        self.btn_initialize.clicked.connect(self._initialize_stg)
        self.btn_start_stg.clicked.connect(self._start_stg)
        self.btn_stop_stg.clicked.connect(self._stop_stg)

    def set_window_title(self, title: str = None) -> None:
        """
        设置主窗口名称
        :param title:
        :return:
        """
        if title:
            self.window_title = title
        self.setWindowTitle(self.window_title)

    def _block_window(self) -> None:
        """
        使窗口不可用，一般用于输入参数时
        :return:
        """
        self.setEnabled(False)

    def _enable_window(self) -> None:
        self.setEnabled(True)

    def _pop_connect_api_dialog(self):
        pass

    def _signal_receiver_api_dialog(self, info: int) -> None:
        pass

    def _create_stg(self):
        pass

    def _initialize_stg(self):
        pass

    def _check_param(self):
        pass

    def _start_stg(self):
        pass

    def _stop_stg(self):
        pass

    def _add_sub_account_col(self):
        pass

    def closeEvent(self, a0: QtGui.QCloseEvent) -> None:
        print('做市UI被关闭')
        super().closeEvent(a0)

    def __del__(self):
        print('做市UI被删除')    # todo: temp config to delete


if __name__ == '__main__':
    import sys
    import qdarkstyle
    from PyQt5 import QtCore, QtGui
    from PyQt5.QtWidgets import QApplication
    from qdarkstyle.light.palette import LightPalette

    app = QApplication(sys.argv)

    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    # app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt5', palette=LightPalette()))
    # app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt5'))
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)

    w = MarketMakerUI()
    w.show()
    app.exec()
