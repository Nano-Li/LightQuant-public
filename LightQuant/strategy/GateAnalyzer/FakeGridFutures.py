# -*- coding: utf-8 -*-
# @Time : 2024/3/11 10:36
# @Author : 
# @File : FakeGridFutures.py 
# @Software: PyCharm
import time
import asyncio
import sys
import pandas as pd
from decimal import Decimal
from LightQuant.Preserver import Preserver
from LightQuant.Recorder import LogRecorder
from LightQuant.tools.calc import calc, calc_sum
from LightQuant.tools.round_step_size import round_step_size
from LightQuant.Analyzer import Analyzer
from LightQuant.Executor import Executor
from LightQuant.protocols.BinanceToken import BinanceToken as Token


class FakeGridAnalyzerFutures(Analyzer):

    STG_NAME = '内存占用测试'

    BUY: str = 'BUY'
    SELL: str = 'SELL'

    param_dict: dict = {
        'symbol_name': None,
        'up_price': None,
        'leverage': None,
        'trigger_start': None,  # 是否用挂单触发, True/False
        'pending_trigger_price': None,

        'grid_rel_step': None,
        'filling_step': None,
        'lower_step': None,
        'filling_fund': None  # 设定补仓资金，按照现货计算
    }

    def __init__(self) -> None:
        super().__init__()
        # ==================== 策略参数保存 ==================== #
        self.symbol_name = None
        self.up_limit_price = None  # 该上界为实值，是最顶端网格价格
        self.symbol_leverage = None

        self.trigger_start: bool = False
        self.trigger_price = None

        self.grid_step_ratio = None  # 等比网格比例，单位为1
        self.filling_step_ratio = None  # 等比填仓比例，单位为1
        self.lower_space_ratio = None  # 下方空间比例
        self.filling_fund = None  # 每次填仓资金

        # 输入相关，仅作为临时存储
        self._x_grid_up_limit = None
        self._x_leverage = None
        self._x_trigger_start = False
        self._x_trigger_price = None
        self._x_price_rel_step = None
        self._x_filling_step = None
        self._x_lower_step = None
        self._x_filling_fund = None

        # ==================== 合约交易规则变量 ==================== #
        self.symbol_price_min_step = None
        self.symbol_quantity_min_step = None
        self.symbol_max_leverage = None
        self.symbol_min_notional = None
        self.symbol_order_price_div = None
        self.symbol_orders_limit_num = None
        # 手续费
        self.symbol_maker_fee = 0
        self.symbol_taker_fee = 0

        # ==================== 策略功能相关变量 ==================== #
        # noinspection PyTypeChecker
        self._update_text_task: asyncio.Task = None

        # ==================== 策略统计相关变量 ==================== #
        # 当前最新价格，实时更新，要求最新
        self.current_symbol_price = 0
        self._trading_statistics: dict = {
            'waiting_start_time': None,
            'strategy_start_time': None,
            'filled_buy_order_num': 0,
            'filled_sell_order_num': 0,
            # 已达成交易量
            'achieved_trade_volume': 0,
            # 已实现的网格套利利润
            'matched_profit': 0,
            # 已实现做多利润
            'realized_profit': 0,
            # 未实现盈亏
            'unrealized_profit': 0,
            # 交易手续费
            'total_trading_fees': 0,
            # 该策略最终净收益
            'final_profit': 0
        }

        # ==================== 特殊功能相关变量 ==================== #

        # 定时器，反复重置以达到核心功能
        # noinspection PyTypeChecker
        self._ticker_delay_timer: asyncio.TimerHandle = None
        # 等待时间 delay，如果超过该delay仍没有收到下一次ticker信息，则做出额外判断和操作
        self._ticker_delay_trigger_time: float = 1.2
        # 协程锁，防止重复开启协程任务
        self._doing_delay_task: bool = False

        # ==================== 其他变量 ==================== #
        self._is_trading = False
        # 点击停止次数
        self.manually_stop_request_time: int = 0
        # 用户已经强制终止
        self.force_stopped: bool = False
        # 保存最后的参考信息
        self._save_ref_info_text: str = ''

    def initialize(self, my_executor: Executor) -> None:
        # 绑定 executor
        super().initialize(my_executor)
        return

    # starting methods
    async def _get_trading_rule(self, symbol_name: str) -> bool:
        """
        获取交易规则
        :return: True, 表示查询到该合约并成功存储规则. False, 表示未查询到该合约
        """
        self.symbol_info = await self._running_loop.create_task(self._my_executor.get_symbol_info(symbol_name))
        if self.symbol_info is None:
            return False
        else:
            # 获得合约交易规则
            self.symbol_price_min_step = self.symbol_info['price_min_step']
            self.symbol_quantity_min_step = self.symbol_info['qty_min_step']
            self.symbol_max_leverage = self.symbol_info['max_leverage']
            self.symbol_min_notional = 0
            self.symbol_order_price_div = self.symbol_info['order_price_deviate']
            self.symbol_orders_limit_num = self.symbol_info['orders_limit']
            return True

    async def validate_param(self, input_params: dict, acquire_params: bool = True) -> dict:
        validated_params = input_params.copy()
        param_valid = True

        validated_params['symbol_name'] = input_params['symbol_name'].upper()
        if 'USDT' in validated_params['symbol_name']:
            if '_' not in validated_params['symbol_name']:
                validated_params['symbol_name'] = validated_params['symbol_name'].split('USDT')[0] + '_' + 'USDT'
        else:
            validated_params['symbol_name'] += '合约名称有误'
            validated_params['valid'] = False
            return validated_params

        self._x_grid_up_limit = validated_params['up_price']
        self._x_leverage = validated_params['leverage']
        self._x_trigger_start = validated_params['trigger_start']
        self._x_trigger_price = validated_params['pending_trigger_price']
        self._x_price_rel_step = validated_params['grid_rel_step']
        self._x_filling_step = validated_params['filling_step']
        self._x_lower_step = validated_params['lower_step']
        self._x_filling_fund = validated_params['filling_fund']

        symbol_exist = await self._get_trading_rule(validated_params['symbol_name'])

        if symbol_exist:
            self.current_symbol_price = await self._my_executor.get_current_price(validated_params['symbol_name'])

        else:
            validated_params['symbol_name'] += '未查询到该合约'
            param_valid = False

        validated_params['up_price'] = self._x_grid_up_limit
        validated_params['leverage'] = self._x_leverage
        validated_params['trigger_start'] = self._x_trigger_start
        validated_params['pending_trigger_price'] = self._x_trigger_price
        validated_params['grid_rel_step'] = self._x_price_rel_step
        validated_params['filling_step'] = self._x_filling_step
        validated_params['lower_step'] = self._x_lower_step
        validated_params['filling_fund'] = self._x_filling_fund
        validated_params['valid'] = param_valid

        return validated_params

    async def param_ref_info(self, valid_params_dict: dict) -> str:
        symbol_name = valid_params_dict['symbol_name']

        info_texts: str = """\n"""
        info_texts += '*** {} ***\n'.format('=' * 32)
        self.current_symbol_price = await self._my_executor.get_current_price(symbol_name)

        self.derive_functional_variables()

        # 使用东八区时间
        info_texts += '\n当前时间: {}\n'.format(str(pd.to_datetime(self.gen_timestamp(), unit='ms') + pd.Timedelta(hours=8)))
        info_texts += '\n合约名称: {}\t\t\t当前价格: {}\n'.format(symbol_name, str(self.current_symbol_price))

        info_texts += '\n\n*** {} ***'.format('=' * 32)

        # 最后保存参考信息，以供恢复策略时使用
        self._save_ref_info_text = info_texts
        return info_texts

    def confirm_params(self, input_params: dict) -> None:
        self.symbol_name = input_params['symbol_name']

        self._my_executor.start_single_contract_order_subscription(self.symbol_name)
        self._my_executor.start_single_contract_ticker_subscription(self.symbol_name)

    def return_params(self) -> dict:
        """
        返回策略参数，此时策略参数是正确的，恢复策略用
        :return:
        """
        stg_params = self.param_dict.copy()

        stg_params['symbol_name'] = self.symbol_name
        stg_params['up_price'] = self._x_grid_up_limit
        stg_params['leverage'] = self._x_leverage
        stg_params['trigger_start'] = self._x_trigger_start
        stg_params['pending_trigger_price'] = self._x_trigger_price
        stg_params['grid_rel_step'] = self._x_price_rel_step
        stg_params['filling_step'] = self._x_filling_step
        stg_params['lower_step'] = self._x_lower_step
        stg_params['filling_fund'] = self._x_filling_fund
        stg_params['valid'] = True

        return stg_params

    def derive_functional_variables(self, assign_entry_price: float = 0) -> None:
        pass

    def derive_valid_position(self) -> None:
        pass

    def stop(self) -> None:
        asyncio.create_task(self._terminate_trading(reason='人工手动结束'))

    def start(self) -> None:
        """
        start 函数连接按钮，由于不确定是挂单还是直接入场，因此改写父类方法

        操作：
            1. 如果触发挂单，则提交触发挂单并等待触发

            2. 如果直接开启，则市价下单并开启策略

        :return:
        """
        self._my_logger = LogRecorder()
        self._my_logger.open_file(self.symbol_name)
        self._my_preserver = Preserver()
        self._my_preserver.acquire_user_id(self._my_executor.return_user_id())
        self._my_preserver.open_file(self.symbol_name)  # todo: 改写并测试继承方法，使代码更美观

        # asyncio.create_task(self._my_executor.change_symbol_leverage(self.symbol_name, self.symbol_leverage))

        asyncio.create_task(self._start_strategy())

    async def _start_strategy(self):
        self._is_waiting = False
        self._is_trading = True
        self._log_info('智能调仓网格 策略开始')

        self._reasonable_order_num_estimate()

        fee_dict = await self._my_executor.get_symbol_trade_fee(self.symbol_name)
        self.symbol_maker_fee = fee_dict['maker_fee']
        self.symbol_taker_fee = fee_dict['taker_fee']
        self._log_info('maker fee rate: {}'.format(self.symbol_maker_fee))
        self._log_info('taker fee rate: {}'.format(self.symbol_taker_fee))

        self._update_text_task = asyncio.create_task(self._update_detail_info(interval_time=1))

        self._init_account_position = 0

        self._trading_statistics['strategy_start_time'] = self.gen_timestamp()
        if self.trigger_start:
            self.current_symbol_price = self.trigger_price
        else:
            self.current_symbol_price = await self._my_executor.get_current_price(self.symbol_name)
            # 如果直接入场，在此得到策略参数
            self.derive_functional_variables()
        self._log_info('策略开始合约价格: {}'.format(self.current_symbol_price))

        # 1. 设置初始市价买入数量
        # if not self.trigger_start:
        #     await self._post_market_order(self.BUY, self.entry_grid_qty)

        # 2. 开始撒网
        asyncio.create_task(self._layout_net())

        # 3. 开启维护挂单任务
        # self._fix_order_task = asyncio.create_task(self._order_fixer(interval_time=180))

    # strategy basic methods
    def _grid_stair_step_up(self) -> None:
        pass

    def _add_buffer_vars(self) -> None:
        pass

    async def _layout_net(self):
        self.open_buy_orders = [
            {
                'id': self.gen_id(_index, self.BUY),
                'status': 'NEW',
                'time': self.gen_timestamp()
            } for _index in range(30)
        ]
        self.open_sell_orders = [
            {
                'id': self.gen_id(_index, self.SELL),
                'status': 'NEW',
                'time': self.gen_timestamp()
            } for _index in range(30, 60)
        ]
        self._log_info('\n假装撒网\n')

    def _reasonable_order_num_estimate(self):
        pass

    async def _maintain_grid_order(self, this_order_index: int, this_order_side: str, filled_order_id: str, append_info: str = None, order_filled: bool = True) -> None:
        pass

    async def _terminate_trading(self, reason: str = '') -> None:
        if not self._is_trading:
            self._log_info('--- 策略正在停止，请稍等。。。')
            self.manually_stop_request_time += 1
            self._log_info(str(self.manually_stop_request_time))
            # 点击次数多，用户强行终止
            if self.manually_stop_request_time >= 10:
                self._log_info('--- 用户强行终止策略，请自行平仓和撤销挂单')
                if isinstance(self._update_text_task, asyncio.Task):
                    self._update_text_task.cancel()

                self.force_stopped = True
                self._my_logger.close_file()
                self._my_preserver.stop_preserving()
                self._my_executor.stop_single_contract_order_subscription(self.symbol_name)
                self._my_executor.stop_single_contract_ticker_subscription(self.symbol_name)
                self._my_executor.strategy_stopped(self.stg_num)
                self._bound_running_column = None
            return
        self._is_trading = False

        cancel_cmd, close_cmd = Token.ORDER_INFO.copy(), Token.ORDER_INFO.copy()
        cancel_cmd['symbol'], close_cmd['symbol'] = self.symbol_name, self.symbol_name

        self._log_info('--- 终止策略，终止原因: {}'.format(reason))
        await self._update_detail_info(only_once=True)

        if not self.force_stopped:
            self._my_logger.close_file()
            self._my_preserver.stop_preserving()
            self._my_executor.stop_single_contract_order_subscription(self.symbol_name)
            self._my_executor.stop_single_contract_ticker_subscription(self.symbol_name)
            self._my_executor.strategy_stopped(self.stg_num)

            # todo: 此处或许应该在基类中定义
            self._bound_running_column = None

    async def _update_detail_info(self, interval_time: int = 3, only_once: bool = False) -> None:
        if not only_once:
            await asyncio.sleep(3)

        while True:
            self._update_column_text()
            self._save_strategy_data()

            start_t = pd.to_datetime(self._trading_statistics['strategy_start_time'], unit='ms')
            current_t = pd.to_datetime(self.gen_timestamp(), unit='ms')
            running_time = current_t - start_t
            days: int = running_time.days
            seconds: int = running_time.seconds
            hours, seconds = int(seconds / 3600), seconds % 3600
            minutes, seconds = int(seconds / 60), seconds % 60

            showing_texts = '智能调仓网格 统计信息:'
            showing_texts += '\n\n*** {} ***\n\n'.format('=' * 51)

            if days == 0:
                showing_texts += '交易统计\t\t运行时间\t\t{}:{}:{}\n\n'.format(str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2))
            else:
                showing_texts += '交易统计\t\t运行时间\t\t{} day\t{}:{}:{}\n\n'.format(
                    str(days), str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2))
            # showing_texts += '交易统计:\t\t当前时间 {}\n\n'.format(str(str(pd.to_datetime(self.gen_timestamp(), unit='ms'))))
            self.derive_valid_position()
            showing_texts += '-' * 58
            showing_texts += '合约最新价格:\t{:<10}\n\n'.format(str(self.current_symbol_price))
            showing_texts += '-' * 58

            showing_texts += '*** {} ***\n\n'.format('=' * 51)

            self._bound_running_column.update_trade_info(showing_texts)

            if only_once:
                return

            await asyncio.sleep(interval_time)

    def _update_column_text(self):
        """
        更新 column 显示的策略收益
        :return:
        """
        # todo: sys
        self._bound_running_column.update_profit_text(
            matched_profit='字节占用',
            unmatched_profit=str(sys.getsizeof(self))
        )

    async def show_final_statistics(self) -> str:
        return str(0)

    def _save_strategy_data(self) -> None:
        stg_param_dict = {
            'symbol_name': self.symbol_name,
            'up_price': self._x_grid_up_limit,
            'leverage': self._x_leverage,
            'trigger_start': self._x_trigger_start,  # 是否用挂单触发, True/False
            'pending_trigger_price': self._x_trigger_price,

            'grid_rel_step': self._x_price_rel_step,
            'filling_step': self._x_filling_step,
            'lower_step': self._x_lower_step,
            'filling_fund': self._x_filling_fund
        }

        strategy_info = {
            'channel': 'futures',
            'stg_name': self.STG_NAME,
            'symbol_name': self.symbol_name,
            'stg_params': stg_param_dict,
            'stg_entry_price': None,
            'present_stair_num': None,
            'current_symbol_price': self.current_symbol_price,
            'stg_statistics': self._trading_statistics,
            'is_waiting': self._is_waiting,
            'is_trading': self._is_trading,
            'ref_info_texts': self._save_ref_info_text
        }
        self._my_preserver.preserve_strategy_info(strategy_info)

    def _additional_action(self) -> None:
        """
        触发器，用于启动coroutine
        :return:
        """
        asyncio.create_task(self._additional_action_task())

    async def _additional_action_task(self) -> None:
        """
        此时市场交易不剧烈，策略可以做出额外的操作，
        该方法属于半主动式策略
        功能：
            1. 如果需要修正挂单，则修正挂单

            2.1 如果存在特殊挂单，则判断特殊挂单是否离市价较近
            2.2 如果不存在特殊挂单，判断是否需要修正仓位，

        操作：
            1. 首先修正维护策略挂单
            2. 处理部分成交的挂单，偏离太远的纳入仓位偏移统计
            3. 处理仓位修正挂单

        注意：存在特殊挂单时，如果accumulated dev 因为其他原因又不为0，系统会等待adjusting order完成后，继续创建新的 adjusting order
        :return:
        """
        self._log_info('>>> ')
        if not self._is_trading:  # 因为此时有可能人工手动停止
            return
        if self._doing_delay_task:
            self._log_info('\n>>> 上锁，不重复开启延时任务')
            return
        self._doing_delay_task = True

        # 使用 try 模块避免可能的问题
        try:
            self._log_info(f'\n>>> 当前合约价格: {self.current_symbol_price}')

        finally:
            self._doing_delay_task = False

    async def ticker_receiver(self, recv_ticker_data: dict) -> None:

        self.current_symbol_price = recv_ticker_data['price']

        if self._is_trading:

            # === 高频仓位功能 === # 超过某个固定时间仍未收到ticker信息，则此时交易不剧烈，可以做额外操作
            if self._ticker_delay_timer:
                self._ticker_delay_timer.cancel()
            self._ticker_delay_timer = self._running_loop.call_later(self._ticker_delay_trigger_time, self._additional_action)

        # if self.developer_switch:
        #     self._reset_functional_vars()
        #     self.developer_switch = False
        #     self._log_info('\n!!! 重置相关任务变量 !!!\n')
        # raise ValueError('test error')

    # tool methods
    def gen_id(self, self_index: int, side: str) -> str:
        self_id = self.stg_num + '_' + str.zfill(str(self_index), 8) + side
        return self_id

    @staticmethod
    def parse_id(client_id: str) -> tuple[int, str]:
        internal_client_id = client_id.split('_')[-1]
        try:
            order_index = int(internal_client_id[:8])
            order_side = internal_client_id[8:]
        except ValueError:
            order_index = -1
            order_side = client_id

        return order_index, order_side

    @staticmethod
    def round_step_precision(price: float, step: float) -> float:
        """
        专门为该策略打造的四舍五入规整精度方法，只考虑大于0的情况
        :param price:
        :param step:
        :return:
        """
        price = Decimal(str(price))
        step = Decimal(str(step))
        mod = price % step
        if mod > step / 2:
            return float(price - mod + step)
        else:
            return float(price - mod)

    @staticmethod
    def gen_timestamp():
        return int(round(time.time() * 1000))

    def __del__(self):
        print('\n{}: {} smart grid analyzer 实例被删除，释放资源\n'.format(self.stg_num, self.symbol_name))
        pass
