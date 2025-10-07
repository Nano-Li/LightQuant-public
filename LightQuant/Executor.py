# -*- coding: utf-8 -*-
# @Time : 2023/1/26 21:23 
# @Author : 
# @File : Executor.py 
# @Software: PyCharm
import asyncio
from typing import Union
from .Recorder import LogRecorder
from .ui.TradeUI import TradeUI


class Executor:
    # todo: important!!!!!!!!!!!!!!!!!! 当前由于策略识别号的逻辑，应该无法使用同一个api接口使用多个executor
    NAME = 'api接口'

    # noinspection PyTypeChecker
    def __init__(self) -> None:
        self.STG_SERIES = 'stg'
        self.STG_SERIES_LEN = len(self.STG_SERIES)

        self._event_loop: asyncio.BaseEventLoop = None
        self._recorder: LogRecorder = None

        self._bound_UI: TradeUI = None
        # 正在运行的策略
        self._running_strategies: dict = {}
        # 已失效的策略
        self._disabled_strategies: dict = {}

        # 存在的策略序列号，使用专门的函数维护，回收利用
        self._using_stg_num = []
        self._disabled_stg_num = []
        self._expired_stg_num = []

    def initialize(self, main_UI: TradeUI) -> None:
        """
        初始化，实现与 main ui绑定
        :param main_UI:
        :return:
        """
        self._bound_UI = main_UI
        # 整个线程的 event loop 在此
        self._event_loop = asyncio.get_running_loop()

    def set_stg_series(self, ui_series_num: int) -> None:
        self.STG_SERIES = 'U{}S'.format(str(ui_series_num))
        self.STG_SERIES_LEN = len(self.STG_SERIES)

    def manually_set_stg_series(self, stg_token: str):
        # 手动设置，非自动
        self.STG_SERIES = stg_token
        self.STG_SERIES_LEN = len(self.STG_SERIES)

    def acquire_api_params(self, key: str, secret: str, user_id: str) -> None:
        pass

    def read_api_params(self, file_name: str = None) -> bool:
        pass

    def return_user_id(self) -> int:
        pass

    # single-use methods
    async def create_connection(self) -> bool:
        pass

    def abort_connection(self) -> None:
        pass

    async def engine_start(self) -> None:
        """
        event_loop 需要运行的主函数，代表程序开始
        :return:
        """
        print('开始执行策略')
        pass

    async def get_symbol_info(self, symbol_name: str) -> Union[dict, None]:
        pass

    async def get_current_price(self, symbol_name: str) -> float:
        pass

    async def change_symbol_leverage(self, symbol_name: str, leverage: int) -> None:
        pass

    async def get_symbol_position(self, symbol_name: str) -> Union[int, float]:
        pass

    def get_symbol_position_with_io(self, symbol_name: str) -> Union[int, float]:
        # todo: 是否将两个统一起来
        pass

    async def get_current_asset_qty(self, symbol_name: str) -> float:
        pass

    async def get_symbol_trade_fee(self, symbol_name: str) -> dict:
        pass

    async def get_open_orders(self, symbol_name: str) -> tuple[list[str], list[str]]:
        pass

    async def get_open_orders_beta(self, symbol_name: str) -> list[dict]:
        pass

    def get_open_orders_with_io(self, symbol_name: str) -> tuple[list[str], list[str]]:
        pass

    # ## ==================================== all streams ==================================== ## #
    def start_single_contract_order_subscription(self, contract_name: str) -> None:
        pass

    def stop_single_contract_order_subscription(self, contract_name: str) -> None:
        pass

    def start_single_contract_ticker_subscription(self, contract_name: str) -> None:
        pass

    def stop_single_contract_ticker_subscription(self, contract_name: str) -> None:
        pass

    def start_single_contract_public_trade_subscription(self, contract_name: str) -> None:
        pass

    def stop_single_contract_public_trade_subscription(self, contract_name: str) -> None:
        pass

    def start_single_contract_book_ticker_subscription(self, contract_name: str) -> None:
        pass

    def stop_single_contract_book_ticker_subscription(self, contract_name: str) -> None:
        pass

    # ## ==================================== all streams ==================================== ## #

    # interaction methods with Analyzer
    async def reporter(self, order_data: dict = None, token: str = None, appending_info: str = None) -> None:
        pass

    async def command_receiver(self, recv_command: dict) -> None:
        pass

    async def ticker_reporter(self, ticker_data: dict) -> None:
        pass

    async def public_trade_reporter(self, public_trade_data: dict) -> None:
        pass

    # core function methods
    async def _post_market_order(self, command: dict):
        pass

    async def _post_limit_order(self, command: dict):
        pass

    async def _post_poc_order(self, command: dict):
        pass

    async def _change_poc_order_price(self, command: dict):
        pass

    async def _change_poc_order_qty(self, command: dict):
        pass

    async def _post_limit_batch_orders(self, batch_command: dict):
        pass

    async def _post_poc_batch_orders(self, batch_command: dict):
        pass

    async def _post_cancel_order(self, command: dict):
        pass

    async def _post_cancel_batch_orders(self, batch_command: dict):
        pass

    async def _cancel_all_orders(self, command: dict) -> None:
        pass

    async def _close_position(self, command: dict) -> None:
        pass

    # UI interaction methods
    def add_strategy(self, stg_analyzer) -> str:
        """
        为执行者添加一个需要运行的策略
        返回该策略的策略识别编号
        :param stg_analyzer:
        :return: 策略识别号码 e.g. stg1
        """
        new_stg_code = self._gen_stg_num()
        self._running_strategies[new_stg_code] = stg_analyzer
        return new_stg_code

    def disable_strategy(self, stg_code: str):
        """
        终止一个正在运行的策略，保留该策略资源，方便事后查询信息
        注意：形式终止，该方法需要在实际终止之后
        :param stg_code:
        :return:
        """
        if stg_code not in self._running_strategies:
            print('*' * 30, '\n\n', '严重警告：框架错误，尝试废除不在运行的策略', '\n\n', '*' * 30)
            raise KeyError

        disabled_analyzer = self._running_strategies.pop(stg_code)
        self._disabled_strategies[stg_code] = disabled_analyzer
        self._disable_stg_num(stg_code)

    def delete_strategy(self, stg_code: str):
        """
        删除一个策略，并释放资源，释放该策略代号，以便重新利用
        删除后将无法再查看该策略相关统计信息
        :param stg_code:
        :return:
        """
        if stg_code not in self._disabled_strategies:
            print('*' * 30, '\n\n', '严重警告：框架错误，尝试删除不存在的策略', '\n\n', '*' * 30)
            raise KeyError

        self._disabled_strategies.pop(stg_code)
        self._remove_stg_num(stg_code)

    def strategy_stopped(self, stg_num: str):
        """
        策略或主动或被动结束，执行下一步操作
        :param stg_num:
        :return:
        """
        self.disable_strategy(stg_num)
        self._bound_UI.transfer_column(stg_num)

    # tool methods
    def _gen_stg_num(self) -> str:
        """
        根据策略序列维护规则，生成一个策略代号
        :return:
        """
        if len(self._expired_stg_num):
            reuse_num = self._expired_stg_num.pop(0)
        else:
            reuse_num = int(len(self._using_stg_num) + len(self._disabled_stg_num) + 1)

        self._using_stg_num.append(reuse_num)

        self._using_stg_num.sort()

        stg_code = self.STG_SERIES + str(reuse_num)

        # print('\nusing stg nums: {}'.format(self._using_stg_num))
        # print('stopped stg nums: {}'.format(self._disabled_stg_num))
        # print('deleted stg nums: {}\n'.format(self._expired_stg_num))
        return stg_code

    def _disable_stg_num(self, stg_code: str) -> None:
        """
        根据策略维护规则，废除一个策略代号，放进废除代号list
        该动作表示一个策略主动或被动的停止
        :param stg_code:
        :return:
        """
        disable_num = int(stg_code[len(self.STG_SERIES):])
        try:
            self._using_stg_num.remove(disable_num)
        except ValueError:
            print('*' * 30, '\n\n', '严重警告：框架错误，尝试废除不存在的序列代号', '\n\n', '*' * 30)
            raise ValueError

        self._disabled_stg_num.append(disable_num)
        self._disabled_stg_num.sort()

        # print('\nusing stg nums: {}'.format(self._using_stg_num))
        # print('stopped stg nums: {}'.format(self._disabled_stg_num))
        # print('deleted stg nums: {}\n'.format(self._expired_stg_num))

    def _remove_stg_num(self, stg_code: str) -> None:
        """
        根据策略序列维护规则，将一个策略代号从废除代号list中取出，并丢进垃圾桶
        该动作表示ui界面中将一个灰色废除的策略 X 掉
        :param stg_code:
        :return:
        """
        remove_num = int(stg_code[len(self.STG_SERIES):])
        try:
            self._disabled_stg_num.remove(remove_num)
        except ValueError:
            print('*' * 30, '\n\n', '严重警告：框架错误，尝试删除不存在的序列代号', '\n\n', '*' * 30)
            raise ValueError

        self._expired_stg_num.append(remove_num)
        self._expired_stg_num.sort()

        # print('\nusing stg nums: {}'.format(self._using_stg_num))
        # print('stopped stg nums: {}'.format(self._disabled_stg_num))
        # print('deleted stg nums: {}\n'.format(self._expired_stg_num))

    def __del__(self):
        print('executor 实例被删除')


if __name__ == '__main__':
    test_executor = Executor()

    test_executor._gen_stg_num()
    test_executor._gen_stg_num()
    test_executor._gen_stg_num()

    test_executor._using_stg_num
    test_executor._disable_stg_num('stg2')

    test_executor._gen_stg_num()
    test_executor._gen_stg_num()

    test_executor._remove_stg_num('stg2')

    test_executor._disable_stg_num('stg1')

    test_executor._gen_stg_num()
    test_executor._gen_stg_num()

    test_executor._disable_stg_num('stg3')
    test_executor._remove_stg_num('stg3')

    test_executor._gen_stg_num()
    test_executor._gen_stg_num()

    print('end')