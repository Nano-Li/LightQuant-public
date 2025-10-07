# -*- coding: utf-8 -*-
# @Time : 2023/1/26 21:41 
# @Author : 
# @File : Analyzer.py 
# @Software: PyCharm
import asyncio
from LightQuant.Executor import Executor
from LightQuant.Recorder import LogRecorder
from LightQuant.Preserver import Preserver
from .ui.TradeUI import RunningStgColumn, StoppedStgColumn


class Analyzer:

    STG_NAME = '策略模板'

    # noinspection PyTypeChecker
    def __init__(self) -> None:
        self.symbol_name = None
        self._running_loop: asyncio.BaseEventLoop = None
        self._update_text_task: asyncio.Task = None

        self._my_executor: Executor = None

        self._my_logger: LogRecorder = None
        self._my_preserver: Preserver = None

        self._bound_running_column: RunningStgColumn = None
        self._bound_stopped_column: StoppedStgColumn = None

        self.stg_num = None
        self.stg_num_len = None

        # 开发人员专用内部变量
        self.developer_switch = True

    def initialize(self, my_executor: Executor) -> None:
        """
        策略初始化，需要绑定Executor以获取交易所信息，
        由于可能关闭窗口，因此不获取recorder和 preserver
        :param my_executor:
        :return:
        """
        self._my_executor = my_executor
        self._running_loop = asyncio.get_running_loop()

    def bound_column(self, bound_column: RunningStgColumn) -> None:
        self._bound_running_column = bound_column

    async def validate_param(self, input_params: dict) -> dict:
        pass

    async def param_ref_info(self, valid_params_dict: dict) -> str:
        pass

    def confirm_params(self, input_params: dict) -> None:
        pass

    def return_params(self) -> dict:
        pass

    def acquire_token(self, stg_code: str) -> None:
        self.stg_num = stg_code
        self.stg_num_len = len(stg_code)

    def start(self) -> None:
        self._my_logger = LogRecorder()
        self._my_logger.open_file(self.symbol_name)
        self._my_preserver = Preserver()
        self._my_preserver.acquire_user_id(self._my_executor.return_user_id())
        self._my_preserver.open_file(self.symbol_name)
        self._log_info('网格策略初始化')
        asyncio.create_task(self._start_strategy())

    async def _start_strategy(self):
        print('策略开始')

    async def _update_detail_info(self, interval_time: int = 1) -> None:
        pass

    def _log_info(self, update_line: str, *args: str) -> None:
        self._bound_running_column.update_trade_orders(update_line)
        self._my_logger.log_print(update_line)

        for each_content in args:
            self._bound_running_column.update_trade_orders(each_content)
            self._my_logger.log_print(update_line)

    async def restart(self, stg_info: dict, save_file_name: str) -> bool:
        pass

    def restart_failed(self):
        pass

    # interaction methods
    async def report_receiver(self, recv_data_dict: dict, append_info: str = None) -> None:
        pass

    async def command_transmitter(self, trans_command: dict = None, token: str = None) -> None:
        pass

    async def ticker_receiver(self, recv_ticker_data: dict) -> None:
        pass

    async def public_trade_receiver(self, recv_trade_data: dict) -> None:
        pass

    async def show_statistics(self) -> tuple[str, str]:
        pass

    async def show_final_statistics(self) -> str:
        pass

    def stop(self) -> None:
        pass

    # async def report_receiver(self):
    #     pass


if __name__ == '__main__':
    pass
