# -*- coding: utf-8 -*-
# @Time : 2023/1/17 10:04 
# @Author : 
# @File : MainWindow.py 
# @Software: PyCharm
"""
最终的交易主窗口，只有该文件定义与实际策略的交互
"""
import os
import sys

import time
import json
import asyncio
from PyQt5 import sip
from PyQt5.QtCore import pyqtSignal, pyqtBoundSignal
from PyQt5.QtGui import QFont, QCloseEvent
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QTabBar, QPushButton, QFrame, QTabWidget, QTextBrowser, QMessageBox
)

from LightQuant.Executor import Executor
from LightQuant.Analyzer import Analyzer
from .TradeUI import TradeUI, RunningStgColumn, StoppedStgColumn
from .OtherWidgets import CreateUIWindow, InputApiDialog, WrongParamInputDialog, ParamRefInfoWindow
from .stg_param_widgets.BaseParamWindow import ParamWidget
from .WindowToken import WindowToken as WTOKEN

# todo: 只有此处导入所有执行者类，添加api接口时需要修改此处，是否有更方便方法。不在函数内导包，因为影响程序速度
from LightQuant.hands.GateMarginExecutor import GateMarginExecutor
from LightQuant.hands.GateFuturesExecutor import GateFuturesExecutor
# todo: 只有此处导入所有策略分析类，添加新策略时需要修改此处
from LightQuant.strategy.GateAnalyzer.ArithmeticGridMargin import ArithmeticGridAnalyzerMargin
from LightQuant.strategy.GateAnalyzer.ArithmeticGridFutures import ArithmeticGridAnalyzerFutures
from LightQuant.strategy.GateAnalyzer.HighFreqTriggerGridFuturesT import HighFreqTriggerGridAnalyzerFuturesT
from LightQuant.strategy.GateAnalyzer.NonlinearStairGridFuturesBeta import NonlinearStairGridAnalyzerFuturesBeta
from LightQuant.strategy.GateAnalyzer.SmartGridFutures import SmartGridAnalyzerFutures
from LightQuant.strategy.GateAnalyzer.SmartFundGridFutures import SmartFundGridAnalyzerFutures
# todo: 只有此处导入所有策略参数输入窗口，添加新策略时需要修改此处
from .stg_param_widgets.ArithmeticGridParam import ArithmeticGridParam
# from .stg_param_widgets.StairGridParam import StairGridParam
from .stg_param_widgets.ArithmeticTriggerGridParam import ArithmeticTriggerGridParam
from .stg_param_widgets.NonlinearStairGridParam import NonlinearStairGridParam
from .stg_param_widgets.SmartGridParam import SmartGridParam


class CreatingUIWindow(CreateUIWindow):
    """
    新建策略时，弹出的 dialog 窗口
    """
    # todo: 在此创建具体的类实例
    def __init__(self):
        super().__init__()

        self._set_selection()

    def _set_selection(self):
        """
        根据实际的接口添加下拉框选项
        :return:
        """
        # todo: 添加api接口时亦需修改此处
        self.api_selector.addItem('Gate 现货')
        self.api_selector.addItem('Gate 合约')
        self.api_selector.addItem('Gate 合约-复原')

    def return_executor_instance(self) -> tuple[Executor, bool]:
        """
        返回所选择的api接口 实例，以及是否是复原策略ui
        :return:
        """
        # print('返回函数被调用一次')
        # todo: 只有此处关联所有执行者类，添加api接口时需要修改此处
        if self.api_selector.currentIndex() == 0:
            return GateMarginExecutor(), False
        elif self.api_selector.currentIndex() == 1:
            return GateFuturesExecutor(), False
        elif self.api_selector.currentIndex() == 2:
            return GateFuturesExecutor(), True
        else:
            print('未定义的选择')

    def closeEvent(self, a0: QCloseEvent) -> None:
        print('添加 ui 窗口被关闭')


class DetailBrowser(QTextBrowser):
    """
    展示策略详细信息的文本浏览器
    """
    def __init__(self, init_text: str = ''):
        super().__init__()
        self.setText(init_text)

        self._init_setting()

    def _init_setting(self):
        browser_font = QFont()
        browser_font.setFamily('Aria')
        browser_font.setPixelSize(12)

        self.setFont(browser_font)

    def __del__(self):
        print('detail browser 实例被删除')


class OrderBrowser(QTextBrowser):
    """
    展示订单详情的文本浏览器
    """
    def __init__(self, init_text: str = ''):
        super().__init__()
        self.setText(init_text)

        self._init_setting()

    def _init_setting(self):
        self.document().setMaximumBlockCount(500)

        browser_font = QFont()
        browser_font.setFamily('Aria')
        browser_font.setPixelSize(12)

        self.setFont(browser_font)

    def __del__(self):
        print('order browser 实例被删除')


class RunningStgCol(RunningStgColumn):
    """
    正在运行策略控件
    """
    signal_emitter_col: pyqtBoundSignal = pyqtSignal(str)

    def __init__(self, bound_analyzer: Analyzer, param_window: ParamWidget):
        super().__init__()
        self.bound_analyzer: Analyzer = bound_analyzer
        self.param_input_window: ParamWidget = param_window
        self.param_input_window.signal_emitter_param.connect(self._signal_receiver_param)
        self.ref_info_window = ParamRefInfoWindow()
        self.ref_info_window.move(960, 160)
        # 只需要移动一次，后续位置由用户自己给定
        self.param_window_moved = False

        self.detail_browser: DetailBrowser = DetailBrowser()
        self.order_browser: OrderBrowser = OrderBrowser()

    def _column_select(self) -> None:
        if self._is_selected:
            # print('{} column unselect'.format(self.symbol_name))
            self.turn_unselected_frame_mode()
            self.signal_emitter_col.emit(WTOKEN.encode_stg_num(self.stg_num, WTOKEN.COLUMN_UNSELECTED))
        else:
            # print('{} column selected'.format(self.symbol_name))
            self.turn_selected_frame_mode()
            self.signal_emitter_col.emit(WTOKEN.encode_stg_num(self.stg_num, WTOKEN.COLUMN_SELECTED))

    def set_column_name(self):
        self.symbol_name = self.bound_analyzer.symbol_name
        self.text_symbol_name.setText(self.symbol_name)

    def _signal_receiver_param(self, info: int) -> None:
        """
        对参数输入窗口按钮发送的信号做出相应
        :param info:
        :return:
        """
        if info == WTOKEN.PARAM_VALIDATION:
            print('合理参数')
            check_input_return = self.param_input_window.check_inputs()
            if check_input_return['okay']:
                input_param_dict = self.param_input_window.get_input_params()
                # print('\n\n传入参数')
                # for key, value in input_param_dict.items():
                #     print(key, ': ', value)

                asyncio.create_task(self._replace_input_params(input_param_dict))
            else:
                error_window = WrongParamInputDialog()
                error_window.set_error_text(check_input_return['msg'])
                error_window.exec()

        elif info == WTOKEN.PARAM_REF_WINDOW:
            print('信息参考')
            check_input_return = self.param_input_window.check_inputs()
            if check_input_return['okay']:
                input_param_dict = self.param_input_window.get_input_params()
                asyncio.create_task(self._pop_ref_info_window(input_param_dict))
            else:
                error_window = WrongParamInputDialog()
                error_window.set_error_text(check_input_return['msg'])
                error_window.exec()
        elif info == WTOKEN.PARAM_CONFIRM:
            print('确认参数')
            # todo: 有可能合理了参数后就直接confirm，此时ref_info_window没有得到参考信息，如果后续需要参考，则会缺失信息，需要加一步获得参考信息
            good_params = self.param_input_window.get_input_params()
            self.bound_analyzer.confirm_params(good_params)
            if self.stg_num:
                # 已被添加进策略栏，只需要修改 analyzer 参数
                print('param window 确认参数，已修改')
            else:
                # 没有获得 stg num，未被添加，需要请求添加
                self.signal_emitter_col.emit(WTOKEN.COLUMN_ADD_REQUEST)
            self.param_input_window.hide()
        elif info == WTOKEN.PARAM_WINDOW_CLOSE:
            if self.stg_num:
                # 已被添加进策略栏，关闭参数窗口不做操作
                print('关闭 param window, 不操作')
            else:
                # 没有获得 stg num，未被添加，直接连带全部删除
                sip.delete(self.param_input_window)
                self.param_input_window = None
                sip.delete(self.ref_info_window)
                self.ref_info_window = None
                self.bound_analyzer = None
                # del self.bound_analyzer
                self.detail_browser = None
                self.order_browser = None

                self.signal_emitter_col.emit(WTOKEN.COLUMN_DELETE_REQUEST)
        else:
            print('未定义的窗口信号')

    async def _replace_input_params(self, param_dict: dict) -> dict:
        """
        点击合理参数后，将经 Analyzer 分析并替换的参数显示在 param window
        :param param_dict:
        :return:
        """
        new_param_dict = await self.bound_analyzer.validate_param(param_dict)
        # print('\n\n返回参数')
        # for key, value in new_param_dict.items():
        #     print(key, ': ', value)
        self.param_input_window.update_text(new_param_dict)
        # 只有analyzer判断参数合理，才能开启确认按钮
        if new_param_dict['valid']:
            self.param_input_window.btn_confirm_param.setEnabled(True)
        return new_param_dict

    async def _pop_ref_info_window(self, param_dict: dict) -> None:
        """
        弹出参考信息窗口，此前也需要合理参数
        :param param_dict:
        :return:
        """
        new_param_dict = await self._replace_input_params(param_dict)
        # 如果analyzer判断参数不合理，则不会弹出信息窗口
        if new_param_dict['valid']:
            ref_info = await self.bound_analyzer.param_ref_info(new_param_dict)
            self.ref_info_window.set_ref_info(ref_info)
            self.ref_info_window.show()
            if not self.param_window_moved:
                self.param_input_window.move(560, 160)
                self.param_window_moved = True

    def _start_running(self):
        """
        点击按钮，开始运行策略，参数窗口只读状态
        :return:
        """
        super()._start_running()
        self.bound_analyzer.start()
        self.param_input_window.set_readonly()

    def set_running_state(self):
        """
        策略恢复后，设置控件为running状态
        :return:
        """
        super()._start_running()
        self.param_input_window.set_readonly()

    def _change_params(self):
        """
        策略未开始，可以修改参数；策略开始后，只能查看参数，只需要显示param window即可
        :return:
        """
        self.param_input_window.show()
        if self._started:
            self.ref_info_window.show()

    def _stop_running(self) -> None:
        """
        人为点击按钮，停止运行策略
        :return:
        """
        # 如果是被选中的col, 需要设置为未被选中 todo: 已修改位置
        # if self._is_selected:
        #     self.signal_emitter_col.emit(WTOKEN.encode_stg_num(self.stg_num, WTOKEN.COLUMN_UNSELECTED))
        self.bound_analyzer.stop()
        # 给一点顿挫感
        time.sleep(0.5)

    def adjust_selection_mode(self) -> None:
        """
        如果策略停止，且在trade region是被选中的状态，需要先回归到未被选中的状态
        :return:
        """
        if self._is_selected:
            self.signal_emitter_col.emit(WTOKEN.encode_stg_num(self.stg_num, WTOKEN.COLUMN_UNSELECTED))

    def update_trade_info(self, showing_info: str) -> None:
        self.detail_browser.setText(showing_info)

    def update_trade_orders(self, appending_info: str) -> None:
        self.order_browser.append(appending_info)


class StoppedStgCol(StoppedStgColumn):
    """
    已停止的策略控件
    """
    signal_emitter_col: pyqtBoundSignal = pyqtSignal(str)

    def __init__(self, bound_analyzer: Analyzer, param_window: ParamWidget, info_window: ParamRefInfoWindow):
        super().__init__()
        self.bound_analyzer: Analyzer = bound_analyzer
        self.param_input_window: ParamWidget = param_window
        self.param_ref_window: ParamRefInfoWindow = info_window
        # todo: 可以再保存 ref_info_window
        # 不需要连接按钮，因为不需要使用按钮
        # 该行代码可以用于测试running col实例是否真实删除，确实已删除
        self.param_input_window.signal_emitter_param.disconnect()

    def initialize(self):
        self.symbol_name = self.bound_analyzer.symbol_name
        self.text_symbol_name.setText(self.symbol_name)
        asyncio.create_task(self.show_profit())
        # print('stopped col has:')
        # print(self.bound_analyzer)
        # print(self.param_input_window)

    def _column_select(self) -> None:
        if self._is_selected:
            self.turn_unselected_frame_mode()
            self.signal_emitter_col.emit(WTOKEN.encode_stg_num(self.stg_num, WTOKEN.COLUMN_UNSELECTED))
        else:
            self.turn_selected_frame_mode()
            self.signal_emitter_col.emit(WTOKEN.encode_stg_num(self.stg_num, WTOKEN.COLUMN_SELECTED))

    def _check_detail(self):
        """

        :return:
        """
        # todo: 暂时只给出查看参数和参考信息的功能
        self.param_input_window.show()
        self.param_ref_window.show()

    def _delete_record(self):
        """
        发送删除col请求
        :return:
        """
        if self._is_selected:
            self.signal_emitter_col.emit(WTOKEN.encode_stg_num(self.stg_num, WTOKEN.COLUMN_UNSELECTED))

        self.bound_analyzer = None
        sip.delete(self.param_input_window)
        self.param_input_window = None
        sip.delete(self.param_ref_window)
        self.param_ref_window = None
        # todo: sip.delete(self.ref_info_window)

        self.signal_emitter_col.emit(WTOKEN.encode_stg_num(self.stg_num, WTOKEN.COLUMN_DELETE_REQUEST))

    async def show_profit(self):
        profit_text = await self.bound_analyzer.show_final_statistics()
        self.num_stg_profit.setText(profit_text)

    # def __del__(self):
    #     super().__del__()


class FailedStgCol(StoppedStgCol):
    """
    恢复失败的策略，放在停止策略栏中，不执行显示收益任务
    """

    def initialize(self):
        self.symbol_name = self.bound_analyzer.symbol_name
        self.text_symbol_name.setText(self.symbol_name)


class TradingUI(TradeUI):
    """
    连接单个执行者的交易ui
    同时负责策略间沟通等
    """

    # noinspection PyTypeChecker
    def __init__(self, bound_executor: Executor):
        super().__init__()
        self.executor = bound_executor

        # 存储layout 中的 column
        self._running_column_layout = self.trading_window.column_layout
        self._stopped_column_layout = self.traded_window.column_layout

        self._detail_browser_widget = self.detail_region.all_browsers
        self._order_browser_widget = self.order_region.all_browsers
        # 存储所有 column, 使用与executor相同的策略识别号
        self._running_stg_cols: dict[str, RunningStgCol] = {}
        self._stopped_stg_cols: dict[str, StoppedStgCol] = {}
        # 存储所有右边信息 TextBrowser()
        self._detail_browsers: dict[str, DetailBrowser] = {}
        self._order_browsers: dict[str, OrderBrowser] = {}
        # 工具变量，知晓当前选中的 column
        self._selected_running_col: str = None
        self._selected_stopped_col: str = None
        # 临时存储变量，在新建策略时暂时保存实例
        self._new_running_col: RunningStgCol = None

        self.api_input_dialog: InputApiDialog = None

        self.api_connected: bool = False

        self._set_selection()
        self._add_detail_browser('init', DetailBrowser())
        self._add_order_browser('init', OrderBrowser())
        self._update_btn_status()

    def _set_selection(self):
        # todo: 临时用的方法，更新策略时也需更新
        self.stg_selector.addItem('基础网格')
        self.stg_selector.addItem('挂单触发网格')
        self.stg_selector.addItem('智能调仓Beta旧')
        # self.stg_selector.addItem('最优网格旧策略')
        self.stg_selector.addItem('智能调仓网格')
        self.stg_selector.addItem('新-智能资金调仓')

    def _pop_connect_api_dialog(self):
        self.api_input_dialog = InputApiDialog()
        self.api_input_dialog.signal_emitter.connect(self._signal_receiver_api_dialog)
        self.api_input_dialog.exec()

    def _signal_receiver_api_dialog(self, info: int) -> None:
        """
        对dialog信号做出相应
        :return:
        """
        if info == WTOKEN.API_INPUT_CONFIRM:
            # print('收到窗口确认信号')
            self._connect_api()

        elif info == WTOKEN.API_INPUT_CLOSE:
            # print('收到窗口关闭信号')
            sip.delete(self.api_input_dialog)
            self.api_input_dialog = None
        else:
            print('未定义的window token')

    def _connect_api(self) -> None:
        """
        连接交易所的api接口
        :return:
        """
        # self.api_input_dialog.btn_confirm.setEnabled(False)
        success = True
        if self.api_input_dialog.use_file():
            file_name = self.api_input_dialog.get_api_file_name()
            success = self.executor.read_api_params(file_name)
        else:
            api_key, api_secret, user_id = self.api_input_dialog.get_api_info()
            self.executor.acquire_api_params(api_key, api_secret, user_id)

        if not success:
            self.api_input_dialog.response_failure()
            # self.api_input_dialog.btn_confirm.setEnabled(True)
            return
        # todo: 此处有逻辑冗余，是开发时无法检测 gate api参数是否真实正确留下的问题
        if success:
            self.api_input_dialog.close()
            # 此处启动整个executor, 然后可以开启策略
            self.executor.initialize(self)
            self.api_connected = True
            self._update_btn_status()
        else:
            self.api_input_dialog.response_failure()
            # self.api_input_dialog.btn_confirm.setEnabled(True)

    def _update_btn_status(self) -> None:
        """
        控制相关按钮状态，包括api连接按钮，使符合逻辑
        连接api，则可创建策略，断开，不可
        该函数在修改api状态之后调用
        :return:
        """
        # todo: 加入column 是否有stg的判断，需要修改
        if self.api_connected:
            self.btn_connect_api.setEnabled(False)
            # self.btn_disconnect_api.setEnabled(True)

            self.btn_create_stg.setEnabled(True)
            self.btn_shutdown_all.setEnabled(True)

            # 没有运行中的策略，可以断开api
            if len(self._running_stg_cols) == 0:
                self.btn_disconnect_api.setEnabled(True)
            else:
                self.btn_disconnect_api.setEnabled(False)

        else:
            self.btn_connect_api.setEnabled(True)
            self.btn_disconnect_api.setEnabled(False)

            self.btn_create_stg.setEnabled(False)
            self.btn_shutdown_all.setEnabled(False)

    def _return_analyzer_instance(self) -> tuple[Analyzer, ParamWidget]:
        """
        返回选择的策略 Analyzer 实例, 包括与 实际策略对应的 参数输入窗口
        :return:
        """
        # todo: 只有此处关联 实际策略 与选项，添加策略时需要修改此处
        if self.stg_selector.currentIndex() == 0:
            # 根据 executor 类型返回 analyzer 类型
            if self.executor.NAME == 'Gate 现货':
                return ArithmeticGridAnalyzerMargin(), ArithmeticGridParam()
            elif self.executor.NAME == 'Gate 合约':
                return ArithmeticGridAnalyzerFutures(), ArithmeticGridParam()
        # elif self.stg_selector.currentIndex() == 1:
        #     if self.executor.NAME == 'Gate 现货':
        #         return StairGridAnalyzerMargin(), StairGridParam()
        #     elif self.executor.NAME == 'Gate 合约':
        #         return StairGridAnalyzerFutures(), StairGridParam()
        #         # todo: test here, 是否有根据实际窗口定义不同选项的方法
        #         print('不存在的策略')
        elif self.stg_selector.currentIndex() == 1:
            if self.executor.NAME == 'Gate 现货':
                return ArithmeticGridAnalyzerMargin(), ArithmeticGridParam()
            elif self.executor.NAME == 'Gate 合约':
                return HighFreqTriggerGridAnalyzerFuturesT(), ArithmeticTriggerGridParam()
        elif self.stg_selector.currentIndex() == 2:
            if self.executor.NAME == 'Gate 现货':
                return ArithmeticGridAnalyzerMargin(), ArithmeticGridParam()
            elif self.executor.NAME == 'Gate 合约':
                return NonlinearStairGridAnalyzerFuturesBeta(), NonlinearStairGridParam()
        elif self.stg_selector.currentIndex() == 3:
            if self.executor.NAME == 'Gate 现货':
                return ArithmeticGridAnalyzerMargin(), ArithmeticGridParam()
            elif self.executor.NAME == 'Gate 合约':
                return SmartGridAnalyzerFutures(), SmartGridParam()
        elif self.stg_selector.currentIndex() == 4:
            if self.executor.NAME == 'Gate 现货':
                return ArithmeticGridAnalyzerMargin(), ArithmeticGridParam()
            elif self.executor.NAME == 'Gate 合约':
                return SmartFundGridAnalyzerFutures(), SmartGridParam()
        else:
            print('未定义的选项')

    def _create_stg(self):
        # todo: 该逻辑下暂时没有中途保存功能，如果中途x掉则会删除实例，不保存已输入参数
        new_analyzer_instance, new_param_window = self._return_analyzer_instance()
        # analyzer 首先单向绑定 executor 以获取信息
        new_analyzer_instance.initialize(my_executor=self.executor)
        self._new_running_col = RunningStgCol(bound_analyzer=new_analyzer_instance, param_window=new_param_window)
        new_analyzer_instance.bound_column(self._new_running_col)
        self._new_running_col.signal_emitter_col.connect(self._signal_receiver_running_col)
        self._new_running_col.param_input_window.show()
        self._block_window()
        # del new_analyzer_instance
        # del new_param_window

    def _shutdown_all_stg(self):
        pass

    def _disconnect_api(self):
        self.executor.abort_connection()
        self.api_connected = False
        self._update_btn_status()
        # time.sleep(1)

    def _statistic_all_stg(self):
        pass

    def _clear_all_stg(self):
        pass

    def _add_running_stg_col(self):
        """
        将参数合理的 Analyzer 及相应column添加到面板中，准备启动策略
        :return:
        """
        stg_token = self.executor.add_strategy(self._new_running_col.bound_analyzer)
        self._new_running_col.bound_analyzer.acquire_token(stg_token)
        self._new_running_col.stg_num = stg_token
        self._new_running_col.set_column_name()
        self._running_column_layout.addWidget(self._new_running_col)
        self._running_stg_cols[stg_token] = self._new_running_col
        # todo: work here, add layout
        self._add_detail_browser(stg_num=stg_token, browser=self._new_running_col.detail_browser)
        self._add_order_browser(stg_num=stg_token, browser=self._new_running_col.order_browser)
        # 不需要将signal.connect, 因为创建col实例时已经连接过一次了
        # print(self._running_stg_cols)
        self._update_btn_status()

    def transfer_column(self, trans_stg_num: str):
        """
        收到executor的信息，转移column实例
        操作：

            0. 调整 col 的选中状态
            1. 断开running col的pyqt signal 连接
            2. 新建stopped col实例
            3. 将col保存的实例移交
            4. 重新编写字典

        :param trans_stg_num:
        :return:
        """
        transferring_col = self._running_stg_cols[trans_stg_num]
        transferring_col.adjust_selection_mode()

        transferring_analyzer = transferring_col.bound_analyzer
        transferring_param_window = transferring_col.param_input_window
        transferring_info_window = transferring_col.ref_info_window
        # transferring_detail_browser = transferring_col.detail_browser
        # transferring_order_browser = transferring_col.order_browser       # 根据 stg_num 将 browser 与 column 产生弱连接，暂不需要直接连接
        # 下行代码可以测试running col是否真的没了
        transferring_col.signal_emitter_col.disconnect()
        new_stopped_col = StoppedStgCol(
            bound_analyzer=transferring_analyzer,
            param_window=transferring_param_window,
            info_window=transferring_info_window
        )
        new_stopped_col.signal_emitter_col.connect(self._signal_receiver_stopped_col)
        new_stopped_col.stg_num = trans_stg_num
        new_stopped_col.initialize()

        transferring_col.bound_analyzer = None
        self._running_stg_cols.pop(trans_stg_num)
        self._running_column_layout.removeWidget(transferring_col)
        sip.delete(transferring_col)
        # del transferring_col
        self._stopped_stg_cols[trans_stg_num] = new_stopped_col
        self._stopped_column_layout.addWidget(new_stopped_col)

        self._update_btn_status()

    def _delete_stopped_column(self, delete_stg_num: str) -> None:
        """
        删除已结束的策略记录
        :param delete_stg_num:
        :return:
        """
        # todo: 重要！！！ Analyzer 实例未被删除，需要debug ！！！
        deleting_column = self._stopped_stg_cols[delete_stg_num]

        self.executor.delete_strategy(delete_stg_num)
        self._stopped_stg_cols.pop(delete_stg_num)
        self._stopped_column_layout.removeWidget(deleting_column)
        sip.delete(deleting_column)

        self._del_detail_browser(stg_num=delete_stg_num)
        self._del_order_browser(stg_num=delete_stg_num)

    def _add_detail_browser(self, stg_num: str, browser: DetailBrowser) -> None:
        """
        添加右上角信息窗口
        :param stg_num:
        :return:
        """
        self._detail_browsers[stg_num] = browser
        self._detail_browser_widget.addWidget(browser)

    def _add_order_browser(self, stg_num: str, browser: OrderBrowser) -> None:
        """
        添加右下角订单窗口
        :param stg_num:
        :return:
        """
        self._order_browsers[stg_num] = browser
        self._order_browser_widget.addWidget(browser)

    def _del_detail_browser(self, stg_num: str) -> None:
        self._detail_browser_widget.removeWidget(self._detail_browsers[stg_num])
        self._detail_browsers.pop(stg_num)

    def _del_order_browser(self, stg_num: str) -> None:
        self._order_browser_widget.removeWidget(self._order_browsers[stg_num])
        self._order_browsers.pop(stg_num)

    def _signal_receiver_running_col(self, info: str) -> None:
        """
        响应running column 发出的信号
        该方法有实现策略间通讯的潜力
        :param info:
        :return:
        """
        print(info)
        emit_stg_num, emit_info = WTOKEN.decode_stg_num(info)
        if emit_info == WTOKEN.COLUMN_SELECTED:
            if self._selected_running_col:
                self._running_stg_cols[emit_stg_num].turn_selected_frame_mode()
                self._running_stg_cols[self._selected_running_col].turn_unselected_frame_mode()

                self._selected_running_col = emit_stg_num
            elif self._selected_stopped_col:
                self._running_stg_cols[emit_stg_num].turn_selected_frame_mode()
                self._stopped_stg_cols[self._selected_stopped_col].turn_unselected_frame_mode()

                self._selected_stopped_col = None
                self._selected_running_col = emit_stg_num
            else:
                self._selected_running_col = emit_stg_num
            self._detail_browser_widget.setCurrentWidget(self._detail_browsers[emit_stg_num])
            self._order_browser_widget.setCurrentWidget(self._order_browsers[emit_stg_num])
        elif emit_info == WTOKEN.COLUMN_UNSELECTED:
            if emit_stg_num == self._selected_running_col:
                self._selected_running_col = None
            else:
                # todo: if test good, delete
                print('逻辑不合理!')
                print(emit_stg_num)
                print(self._selected_running_col)
            self._detail_browser_widget.setCurrentWidget(self._detail_browsers['init'])
            self._order_browser_widget.setCurrentWidget(self._order_browsers['init'])
        elif emit_info == WTOKEN.COLUMN_BLOCK_REQUEST:
            self._block_window()
        elif emit_info == WTOKEN.COLUMN_ENABLE_REQUEST:
            pass
        elif emit_info == WTOKEN.COLUMN_DELETE_REQUEST:
            sip.delete(self._new_running_col)
            # noinspection PyTypeChecker
            self._new_running_col: RunningStgCol = None
            self._enable_window()
            # print(self._new_running_col, type(self._new_running_col))     # 该行代码在哪个位置都输出None, None Type, 此时new_running_col指针已空
        elif emit_info == WTOKEN.COLUMN_ADD_REQUEST:
            # 同样只有 临时存储的col 实例会发出该信号
            self._add_running_stg_col()
            # noinspection PyTypeChecker
            self._new_running_col: RunningStgCol = None
            self._enable_window()
        elif emit_info == WTOKEN.COLUMN_TRANSFER_REQUEST:
            # 策略停止后，需要转移col, 使用executor得到的信息，而不是下属汇报的信息
            # todo: running col的signal需要断开并重连，用什么办法? 1. 重新声明实例 2. 手动断开重连 signal.disconnect()
            pass

    def _signal_receiver_stopped_col(self, info: str) -> None:
        """
        响应 stopped column 发出的信号
        :param info:
        :return:
        """
        print(info)
        emit_stg_num, emit_info = WTOKEN.decode_stg_num(info)
        if emit_info == WTOKEN.COLUMN_SELECTED:
            if self._selected_stopped_col:
                self._stopped_stg_cols[emit_stg_num].turn_selected_frame_mode()
                self._stopped_stg_cols[self._selected_stopped_col].turn_unselected_frame_mode()

                self._selected_stopped_col = emit_stg_num
            elif self._selected_running_col:
                self._stopped_stg_cols[emit_stg_num].turn_selected_frame_mode()
                self._running_stg_cols[self._selected_running_col].turn_unselected_frame_mode()

                self._selected_running_col = None
                self._selected_stopped_col = emit_stg_num
            else:
                self._selected_stopped_col = emit_stg_num
            self._detail_browser_widget.setCurrentWidget(self._detail_browsers[emit_stg_num])
            self._order_browser_widget.setCurrentWidget(self._order_browsers[emit_stg_num])
        elif emit_info == WTOKEN.COLUMN_UNSELECTED:
            if emit_stg_num == self._selected_stopped_col:
                self._selected_stopped_col = None
            else:
                print('逻辑不合理')
            self._detail_browser_widget.setCurrentWidget(self._detail_browsers['init'])
            self._order_browser_widget.setCurrentWidget(self._order_browsers['init'])
        elif emit_info == WTOKEN.COLUMN_DELETE_REQUEST:
            # 停止的策略，点击删除记录，会发出此信息，
            self._delete_stopped_column(emit_stg_num)


class TradingRecoverUI(TradingUI):
    """
    继承于常规的交易UI，连接api时自动读取trading_statistics的策略信息并尝试复原策略
    目前恢复方法仅支持Gate合约，使用user_id区分不同账户策略     # todo: 适用于各个交易所的办法
    """

    stg_data_path = 'trading_statistics'

    def __init__(self, bound_executor: Executor):
        super().__init__(bound_executor)
        self.finish_recovering = False

    def _connect_api(self) -> None:
        """
        只需要修改该方法即可
        连接api后，自动读取文件，并一个个恢复策略
        :return:
        """
        super()._connect_api()
        # 只有最开始连接api时恢复策略
        if not self.finish_recovering:
            asyncio.create_task(self._recover_every_stg())

    async def _recover_every_stg(self) -> None:
        """
        尝试一个一个修复策略，成功修复的策略将会添加到运行栏中
        修复过程中，不允许用户操作，恢复完成后，ui界面和普通交易ui功能一样     # todo: backup 保存数据操作
        :return:
        """
        # 首先关闭用户操作，等待修复
        self._block_window()
        user_id = self.executor.return_user_id()
        stg_data_files = [f for f in os.listdir(self.stg_data_path) if f.endswith('.json')]
        for each_json_file in stg_data_files:
            with open(os.path.join(self.stg_data_path, each_json_file), 'r', encoding='utf-8') as file:
                each_stg_data: dict = json.load(file)
            # 此处限定是本账户以及合约交易
            if each_stg_data['channel'] == 'futures' and each_stg_data['user_id'] == user_id:
                # 遍历所有的策略选项以匹配正确的策略，在这个过程中会不断创建个删除策略实例
                new_analyzer_instance, new_param_window = None, None
                for i in range(self.stg_selector.count()):
                    self.stg_selector.setCurrentIndex(i)
                    # 重启策略时，也是实例化一个新的策略对象
                    check_analyzer_instance, check_param_window = self._return_analyzer_instance()
                    # 使用策略名称匹配，如果名称相同，则使用该实例恢复策略
                    if check_analyzer_instance.STG_NAME == each_stg_data['stg_name']:
                        new_analyzer_instance, new_param_window = check_analyzer_instance, check_param_window
                        print('{} 策略匹配成功'.format(each_stg_data['stg_name']))
                        break
                    else:
                        continue
                        # time.sleep(3)

                if new_analyzer_instance is None:
                    print('{} 文件未匹配到对应策略'.format(each_json_file))
                    continue

                # analyzer 单向绑定 executor 以获取信息
                new_analyzer_instance.initialize(my_executor=self.executor)
                self._new_running_col = RunningStgCol(bound_analyzer=new_analyzer_instance, param_window=new_param_window)
                new_analyzer_instance.bound_column(self._new_running_col)
                # 需要额外设置策略合约名称，如此才能给定控件名称
                new_analyzer_instance.symbol_name = each_stg_data['symbol_name']
                # 需要连接，因为需要结束策略
                self._new_running_col.signal_emitter_col.connect(self._signal_receiver_running_col)

                self._add_running_stg_col()
                time.sleep(0.8)
                self._new_running_col.set_running_state()
                # 随后重启策略
                successfully_restarted = await new_analyzer_instance.restart(stg_info=each_stg_data, save_file_name=each_json_file)
                # 顺便显示参数，如果有参考信息，那更好
                show_param_dict = new_analyzer_instance.return_params()
                if 'ref_info_texts' in each_stg_data.keys():
                    self._new_running_col.ref_info_window.set_ref_info(each_stg_data['ref_info_texts'])
                new_param_window.update_text(show_param_dict)
                if not successfully_restarted:
                    print('{} {} 策略重启失败'.format(new_analyzer_instance.symbol_name, new_analyzer_instance.STG_NAME))
                    # 添加至策略结束栏
                    new_analyzer_instance.restart_failed()
                else:
                    print('{} {} 策略重启成功'.format(new_analyzer_instance.symbol_name, new_analyzer_instance.STG_NAME))
            else:
                continue

        # 当所有操作完成以后，允许用户操作
        self._enable_window()


class FinalWindow(QWidget):
    """
    最终与交易员交互的终端界面
    不同的 tab 连接不同的 Executor,可以实现同时连接不同API
    """

    def __init__(self):
        super().__init__()
        # noinspection PyTypeChecker
        self.page_tab: QTabWidget = None
        # 项目的总 event loop
        self._main_loop = asyncio.get_running_loop()

        # 存储所有子窗口
        self._creating_ui_dialog: CreateUIWindow = CreatingUIWindow()
        self.ui_series_num = 1

        # 存储所有按钮
        self.btn_add_page: QPushButton = QPushButton()
        self.btn_confirm_api_selection = self._creating_ui_dialog.btn_confirm
        # 标签数量，不包括添加按钮
        self.tabs_num = 0
        # 存储所有TradeUI界面
        # self._TradingUI_tabs: dict[str, TradingUI] = {}

        self._init_setting()
        self._relate_btn()

    def _init_setting(self):
        self.resize(1400, 800)
        self.showMaximized()

        main_container = QHBoxLayout()
        main_container.setContentsMargins(2, 0, 2, 2)

        temp_font = QFont()
        temp_font.setFamily('Aria')
        temp_font.setPixelSize(12)

        self.page_tab = QTabWidget()
        self.page_tab.setFont(temp_font)
        self.page_tab.setTabsClosable(True)
        self.page_tab.setMovable(True)
        # self.main_page_tab.setDocumentMode(True)
        # self.main_page_tab.setStyleSheet("QTabWidget::pane{border-width:-2px;}")
        # self.main_page_tab.resize(1000, 800)

        temp_font.setPixelSize(16)
        self.btn_add_page.setText('+')
        self.btn_add_page.setFont(temp_font)
        self.btn_add_page.setFixedWidth(30)
        self.btn_add_page.setMinimumHeight(16)
        self.btn_add_page.clicked.connect(self._pop_add_page_dialog)

        self.page_tab.addTab(QFrame(), '')
        self.page_tab.tabCloseRequested.connect(self._delete_single_ui)

        self.page_tab.setTabEnabled(0, False)
        self.page_tab.tabBar().setTabButton(0, QTabBar.RightSide, self.btn_add_page)

        main_container.addWidget(self.page_tab)
        self.setLayout(main_container)

    def _relate_btn(self) -> None:
        """
        连接所需要的子窗口按钮
        :return:
        """
        self.btn_confirm_api_selection.clicked.connect(self._add_trading_page)

    def _pop_add_page_dialog(self) -> None:
        # 此间用户执行选择操作
        self._creating_ui_dialog.exec()

    def _add_trading_page(self) -> None:
        """
        新增一交易界面
        :return:
        """
        new_executor_ins, need_recover = self._creating_ui_dialog.return_executor_instance()
        if new_executor_ins:
            print(new_executor_ins.NAME)
            new_executor_ins.set_stg_series(self.ui_series_num)
            self.ui_series_num += 1

            # 在此处定义一个新 UI 界面实例, 创建时就完成了executor的初始化工作
            if need_recover:
                new_ui_win = TradingRecoverUI(new_executor_ins)
            else:
                new_ui_win = TradingUI(new_executor_ins)

            new_tab = QFrame()
            new_tab_layout = QHBoxLayout()
            new_tab_layout.setContentsMargins(0, 0, 0, 0)
            new_tab_layout.addWidget(new_ui_win)
            new_tab.setLayout(new_tab_layout)

            self.page_tab.insertTab(self.tabs_num, new_tab, '  {:^12}'.format(new_executor_ins.NAME))
            self.page_tab.setCurrentIndex(self.tabs_num)

            self.tabs_num += 1

        self._creating_ui_dialog.close()

    def _delete_single_ui(self, delete_index: int) -> None:
        """
        删除单个交易UI
        :param delete_index:
        :return:
        """
        # todo: UI 实例没有被立即删除，需要debug
        print('删除index : {}'.format(delete_index))
        showing_index = self.page_tab.currentIndex()
        # print('current showing index = {}'.format(showing_index))

        delete_widget = self.page_tab.widget(delete_index)
        # noinspection PyTypeChecker
        current_ui: TradingUI = delete_widget.layout().itemAt(0).widget()
        # 可以删除，才能删除，否则不操作
        if current_ui.api_connected:
            print('api 未断开，不能删除')
            return
        else:
            # 切换显示窗口
            if showing_index == delete_index and showing_index != 0:
                self.page_tab.setCurrentIndex(showing_index - 1)

            # sip.delete(current_ui)   # todo: 该行暂时不需要，但是，连接了api再断开的tradingUI，没有办法删除干净，需要debug
            self.page_tab.removeTab(delete_index)
            sip.delete(delete_widget)

            self.tabs_num -= 1
        # self.page_tab.setCurrentIndex()

    def closeEvent(self, a0: QCloseEvent) -> None:
        # todo: debug here, why exit code not 0 ?
        # print(self._main_loop, id(self._main_loop))
        # self._main_loop.stop()
        # print(self._main_loop, id(self._main_loop))
        # self._main_loop.close()
        # print(self._main_loop, id(self._main_loop))

        result = QMessageBox.question(self, '确认关闭', '策略正在运行测试中，请不要关闭!!!', QMessageBox.Yes | QMessageBox.No)
        if result == QMessageBox.Yes:
            # a0.accept()
            a0.ignore()
            # 通知服务器的代码省略，这里不是重点...
        else:
            a0.ignore()
        # print('关闭总窗口')
        # sys.exit()

    # def close(self) -> bool:
    #     return False


if __name__ == '__main__':
    import qdarkstyle
    from PyQt5.QtWidgets import QApplication

    test_app = QApplication(sys.argv)
    test_app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    test_window = FinalWindow()
    test_window.show()
    test_app.exec()
