# -*- coding: utf-8 -*-
# @Time : 2023/1/30 9:18 
# @Author : 
# @File : ArithmeticGridMargin.py
# @Software: PyCharm
import re
import sys
import time
import json
import asyncio
import pandas as pd
from LightQuant.Recorder import LogRecorder
from LightQuant.tools.calc import calc, calc_sum
from LightQuant.tools.round_step_size import round_step_size
from LightQuant.Analyzer import Analyzer
from LightQuant.Executor import Executor
from LightQuant.protocols.BinanceToken import BinanceToken as Token


class ArithmeticGridAnalyzerMargin(Analyzer):
    """
    等差网格策略，对接杠杆现货
    """
    STG_NAME = '等差网格'

    BUY: str = 'BUY'
    SELL: str = 'SELL'

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

    def __init__(self) -> None:
        super().__init__()
        self.symbol_name = None
        self.symbol_info = {}

        self.critical_index = 0
        self.all_grid_price = ()
        self.max_index = 0
        # 设置买卖单最大挂单数量，及最小数量
        self.max_buy_order_num = 20
        self.max_sell_order_num = 20
        self.min_buy_order_num = 10
        self.min_sell_order_num = 10
        # 缓冲数量，单边网格数量过少或过多时增减的网格数量
        self.buffer_num = 5

        # 定义了买卖单存储方式    todo:考虑自定义常量
        self.open_buy_orders = [{
            'id': '00032BUY',
            'status': 'NEW',
            'time': None
        }, ]
        self.open_sell_orders = [{
            'id': '00032SELL',
            'status': 'FILLED',
            'time': None
        }, ]

        self.account_leverage = None
        # 该合约交易规则
        self.symbol_max_mkt_qty = None
        self.symbol_price_min_step = None
        self.symbol_quantity_min_step = None
        self.symbol_min_notional = None
        self.symbol_min_order_qty = None

        # trading statistics
        self._initial_index = 0
        # 用于保存初始仓位和价格，并用于后续仓位修正，此处数量为绝对数量，不包括方向     # todo: 可以包括
        # 初始现货仓位，是策略开始时的市价下单，不包括账户开始时存量现货
        self._initial_position_qty = 0
        self._initial_position_price = 0
        # 策略开始前，账户存量现货，策略结束后，需要回归该数字
        self._init_account_spot_qty = 0
        # 理论计算的现货仓位，可能不需要，可以随时由critical index 和 initial_qty 导出
        self._spot_position_qty_theory = 0
        # 手续费
        self.symbol_maker_fee = 0
        self.symbol_taker_fee = 0
        # 持仓为 0 的index
        self._zero_pos_index = 0
        # todo:理论与实践之间的差异，仔细检查所有的统计，统一定义
        self._trading_statistics: dict = {
            'strategy_start_time': None,
            'filled_buy_order_num': 0,
            'filled_sell_order_num': 0,
            # 已达成交易量
            'achieved_trade_volume': 0,
            # 已实现的总套利利润
            'matched_profit': 0,
            # 套利净利润，此处减去手续费
            'net_profit': 0,
            # 未实现盈亏
            'unmatched_profit': 0,
            # 交易手续费
            'total_trading_fees': 0,
            # 该策略最终净收益
            'final_profit': 0
        }

        # todo: 网格参数变量
        self.grid_side = None
        self.grid_upper_limit = None
        self.grid_down_limit = None

        self.grid_quit_price = None

        # 等差网格 网格跳变价格或百分比，二选一
        self.grid_price_step = None
        self.grid_price_step_ratio = None

        self.grid_qty_per_order = None
        self.ini_trade_ratio = None

        self.grid_total_num = None

        # 上下边界是否终止策略
        self.up_boundary_stop = False
        self.low_boundary_stop = False

        # 策略止盈止损
        self.stg_max_profit = 0
        self.stg_min_profit = 0

        # others
        self._first_back = True
        self._online = True  # 如果判断断网则为 False
        self._is_trading = False  # todo: 修改至基类
        # self._test_mode = False
        self._layout_complete = False

        # noinspection PyTypeChecker
        self._my_logger: LogRecorder = None

        self.stg_num = None
        self.stg_num_len = None

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
        # todo: 每次点击合理化参数，都会重新获取一遍交易规则，可优化
        # print('\n尝试获取交易规则')
        self.symbol_info = await self._running_loop.create_task(self._my_executor.get_symbol_info(symbol_name))
        if self.symbol_info is None:
            return False
        else:
            # 获得合约交易规则
            # todo: 测试如果保存会导致ui如何
            self.symbol_max_mkt_qty = 0
            self.symbol_price_min_step = self.symbol_info['price_min_step']
            self.symbol_quantity_min_step = self.symbol_info['qty_min_step']
            self.symbol_min_notional = self.symbol_info['min_notional']
            self.symbol_min_order_qty = self.symbol_info['min_order_qty']
            return True

    async def validate_param(self, input_params: dict) -> dict:
        """
        根据 ui 界面输入的参数字典，合理化后返回正确的参数字典
        :param input_params:
        :return:
        """
        # todo: 可以在参数合理时就直接保存(弹出参考信息),确认即不做修改
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

        up_price = validated_params['up_price']
        down_price = validated_params['down_price']

        tri_selection = validated_params['tri_selection']
        price_abs_step = validated_params['price_abs_step']
        price_rel_step = validated_params['price_rel_step']
        grid_total_num = validated_params['grid_total_num']

        each_grid_qty = validated_params['each_grid_qty']

        dul_selection = validated_params['dul_selection']
        target_ratio = validated_params['target_ratio']
        target_price = validated_params['target_price']

        max_profit = validated_params['max_profit']
        min_profit = validated_params['min_profit']

        symbol_exist = await self._get_trading_rule(validated_params['symbol_name'])

        # todo: 是否可以更合理
        if symbol_exist:
            # 下一步判断
            # current_symbol_price = await self._running_loop.create_task(self._my_executor.get_spot_price(validated_params['symbol_name']))
            current_symbol_price = await self._my_executor.get_current_price(validated_params['symbol_name'])
            # print(self.symbol_price_min_step)
            # print(self.symbol_quantity_min_step)
            each_grid_qty = round_step_size(each_grid_qty, self.symbol_quantity_min_step)
            # 0.95 倍的下单价值需要合理，保留一定冗余
            if calc(current_symbol_price * 0.95, each_grid_qty, '*') <= self.symbol_min_notional:
                # 每次下单小于最小价值，下单不会成功
                each_grid_qty = str(each_grid_qty) + '低于最小价值'
                param_valid = False

            if param_valid:
                if each_grid_qty < self.symbol_min_order_qty:
                    # 每次下单小于最小价值，下单不会成功
                    each_grid_qty = str(each_grid_qty) + '低于最小数量'
                    param_valid = False

            if validated_params['need_stop_loss']:
                if min_profit != '':
                    if min_profit > 0:
                        min_profit = - min_profit
                if max_profit != '':
                    if max_profit < 0:
                        max_profit = abs(max_profit)

            if up_price <= down_price:
                up_price = str(up_price) + '价格数值有误'
                down_price = str(down_price) + '价格数值有误'
                param_valid = False
            else:
                if current_symbol_price >= up_price:
                    up_price = str(up_price) + '当前价格高于上限'
                    param_valid = False
                elif current_symbol_price <= down_price:
                    down_price = str(down_price) + '当前价格低于下限'
                    param_valid = False

                else:
                    if validated_params['grid_side'] == 'BUY':
                        up_price = round_step_size(up_price, self.symbol_price_min_step)
                    else:
                        down_price = round_step_size(down_price, self.symbol_price_min_step)

                    if tri_selection == 1:
                        price_abs_step = round_step_size(price_abs_step, self.symbol_price_min_step)
                    elif tri_selection == 2:
                        price_abs_step = calc(calc(price_rel_step, 100, '/'), current_symbol_price, '*')
                        price_abs_step = round_step_size(price_abs_step, self.symbol_price_min_step)
                    elif tri_selection == 3:
                        self.grid_total_num = grid_total_num
                        price_abs_step = calc(calc(up_price, down_price, '-'), (self.grid_total_num - 1), '/')
                        price_abs_step = round_step_size(price_abs_step, self.symbol_price_min_step, upward=True)
                    # 此处计算的是有多少个间隔，网格数量还要 +1
                    self.grid_total_num = int(int(calc(calc(up_price, down_price, '-'), self.symbol_price_min_step, '/')) /
                                              int(calc(price_abs_step, self.symbol_price_min_step, '/')))

                    if validated_params['grid_side'] == 'BUY':
                        down_price = calc(up_price, calc(self.grid_total_num, price_abs_step, '*'), '-')
                    else:
                        up_price = calc(down_price, calc(self.grid_total_num, price_abs_step, '*'), '+')
                    # 最终计算的网格总数，先保存着
                    self.grid_total_num += 1

                    # 网格数量有要求
                    grid_total_num = self.grid_total_num
                    if self.grid_total_num < 5:
                        grid_total_num = str(self.grid_total_num) + '网格数量过少'
                        param_valid = False

                    price_rel_step = calc(calc(price_abs_step, current_symbol_price, '/'), 100, '*')
                    price_rel_step = round_step_size(price_rel_step, 0.00001)

                    self.max_index = self.grid_total_num - 1
                    # todo: 此处体现了边合理化边保存的思想

                    # down_price = round_step_size(down_price, self.symbol_price_min_step)
                    # price_abs_step = round_step_size(price_abs_step, self.symbol_price_min_step)
                    # # 无论点 ui 哪个按钮，都会执行到该行代码
                    # self.grid_total_num = int(int(calc(calc(up_price, down_price, '-'), self.symbol_price_min_step, '/')) /
                    #                           int(calc(price_abs_step, self.symbol_price_min_step, '/')))
                    # up_price = calc(down_price, calc(self.grid_total_num, price_abs_step, '*'), '+')
                    # self.grid_total_num += 1
                    # self.max_index = self.grid_total_num - 1

            if validated_params['need_advance']:
                if dul_selection == 1:
                    target_ratio = abs(target_ratio)
                    if target_ratio > 1:
                        target_ratio = calc(target_ratio, 100, '/')
                    if validated_params['grid_side'] == 'BUY':
                        delta_price = calc(up_price, current_symbol_price, '-')
                        target_price = calc(calc(delta_price, target_ratio, '*'), current_symbol_price, '+')
                    else:
                        delta_price = calc(current_symbol_price, down_price, '-')
                        target_price = calc(current_symbol_price, calc(delta_price, target_ratio, '*'), '-')
                    target_price = round_step_size(target_price, self.symbol_price_min_step)
                elif dul_selection == 2:
                    target_price = round_step_size(target_price, self.symbol_price_min_step)
                    if validated_params['grid_side'] == 'BUY':
                        if not (current_symbol_price < target_price < up_price):
                            target_price = str(target_price) + '价格不合理'
                            param_valid = False
                        else:
                            delta_price = calc(up_price, current_symbol_price, '-')
                            target_ratio = delta_price / calc(up_price, down_price, '-')
                            target_ratio = round_step_size(target_ratio, 0.001)
                    else:
                        if not (down_price < target_price < current_symbol_price):
                            target_price = str(target_price) + '价格不合理'
                            param_valid = False
                        else:
                            delta_price = calc(current_symbol_price, down_price, '-')
                            target_ratio = delta_price / calc(up_price, down_price, '-')
                            target_ratio = round_step_size(target_ratio, 0.001)

        else:
            validated_params['symbol_name'] += '未查询到该合约'
            param_valid = False

        # validated_params['upper_price'] = up_price
        # validated_params['down_price'] = down_price
        # validated_params['price_step'] = price_abs_step
        # validated_params['grid_qty'] = each_grid_qty
        # validated_params['ini_ratio'] = ini_ratio
        # validated_params['min_profit'] = min_profit
        # validated_params['valid'] = param_valid

        # new
        validated_params['up_price'] = up_price
        validated_params['down_price'] = down_price
        # validated_params['tri_selection'] =
        validated_params['price_abs_step'] = price_abs_step
        validated_params['price_rel_step'] = price_rel_step
        validated_params['grid_total_num'] = grid_total_num
        validated_params['each_grid_qty'] = each_grid_qty
        # validated_params['dul_selection'] =
        validated_params['target_ratio'] = target_ratio
        validated_params['target_price'] = target_price
        validated_params['max_profit'] = max_profit
        validated_params['min_profit'] = min_profit
        validated_params['valid'] = param_valid

        return validated_params

    async def param_ref_info(self, valid_param_dict: dict) -> str:
        info_texts: str = """\n"""

        symbol_name = valid_param_dict['symbol_name']
        # upper_price = valid_param_dict['upper_price']
        down_price = valid_param_dict['down_price']
        price_abs_step = valid_param_dict['price_abs_step']
        each_grid_qty = valid_param_dict['each_grid_qty']
        ini_ratio = 1 if valid_param_dict['dul_selection'] == 0 else valid_param_dict['target_ratio']
        # leverage = valid_param_dict['leverage']
        # max_profit = valid_param_dict['max_profit']
        min_profit = valid_param_dict['min_profit']

        all_grid_price = tuple(calc(down_price, calc(price_abs_step, i, '*'), '+') for i in range(self.grid_total_num))

        info_texts += '*** {} ***\n'.format('=' * 32)
        current_symbol_price = await self._my_executor.get_current_price(symbol_name)
        info_texts += '\n当前时间: {}\n'.format(str(pd.to_datetime(self.gen_timestamp(), unit='ms')))
        info_texts += '\n合约名称: {}\t\t\t当前价格: {}\n'.format(symbol_name, str(current_symbol_price))

        for each_index, each_grid_price in enumerate(all_grid_price):
            if each_grid_price <= current_symbol_price < (each_grid_price + price_abs_step):
                if current_symbol_price - each_grid_price <= price_abs_step / 2:
                    self.critical_index = each_index
                else:
                    self.critical_index = each_index + 1

        info_texts += '\ncritical index = {}\n'.format(str(self.critical_index))
        info_texts += '\n网格总数量\t\t{:<8}\n'.format(str(self.grid_total_num))
        info_texts += '网格价差占比\t\t{:<8}\t{:<8}\n'.format(str(round(price_abs_step / current_symbol_price * 100, 4)), '%')
        info_texts += '网格套利利润\t\t{:<8}\t{:<8}\n'.format((str(calc(each_grid_qty, price_abs_step, '*'))), symbol_name[-4:])

        # 初始BTC花费/仓位
        ini_spot_cost, ini_spot_pos = 0, 0
        # 初始资金花费/仓位
        ini_cash_cost, ini_cash_pos = 0, 0
        # 保证金占用为 0 时的 index
        zero_margin_index = self.critical_index
        ini_order_num, ini_position_qty = 0, 0
        if ini_ratio > 0:
            if valid_param_dict['grid_side'] == self.BUY:
                ini_order_num = round(ini_ratio * (self.max_index - self.critical_index))
                ini_order_quantity = calc(each_grid_qty, ini_order_num, '*')
                ini_spot_pos = ini_order_quantity
                ini_cash_cost = calc(ini_order_quantity, current_symbol_price, '*')
                ini_position_qty = ini_order_quantity
                zero_margin_index = self.critical_index + ini_order_num
            elif valid_param_dict['grid_side'] == self.SELL:
                ini_order_num = round(ini_ratio * self.critical_index)
                ini_order_quantity = calc(each_grid_qty, ini_order_num, '*')
                ini_spot_cost = ini_order_quantity
                ini_cash_pos = calc(ini_order_quantity, current_symbol_price, '*')
                ini_position_qty = - ini_order_quantity
                zero_margin_index = self.critical_index - ini_order_num
            else:
                pass

        max_spot_cost = calc(each_grid_qty, len(all_grid_price[zero_margin_index + 1:]), '*')
        max_cash_cost = 0
        for each_price in all_grid_price[:zero_margin_index]:
            max_cash_cost = calc(calc(each_price, each_grid_qty, '*'), max_cash_cost, '+')

        # 开局价格单边冲出时，触发止损的价格
        up_stop_loss_price, down_stop_loss_price = 0, 0
        # todo: 本土化改造
        if min_profit != '':
            # print('min_profit = {}'.format(min_profit))
            for each_index in range(self.critical_index + 1, len(all_grid_price)):
                temp_profit = self.unmatched_profit_calc(self.critical_index, each_index, all_grid_price, each_grid_qty, current_symbol_price, ini_position_qty)
                # print('index = {}, profit = {}'.format(each_index, temp_profit))
                if temp_profit <= min_profit:
                    up_stop_loss_price = all_grid_price[each_index]
                    # print('上冲止损价：{}'.format(up_stop_loss_price))
                    break
            # print('向上遍历完成\n\n')

            for each_index in reversed(range(self.critical_index)):
                temp_profit = self.unmatched_profit_calc(self.critical_index, each_index, all_grid_price, each_grid_qty, current_symbol_price, ini_position_qty)
                # print('index = {}, profit = {}'.format(each_index, temp_profit))
                if temp_profit <= min_profit:
                    down_stop_loss_price = all_grid_price[each_index]
                    # print('下冲止损价：{}'.format(down_stop_loss_price))
                    break
            # print('向下遍历完成\n\n')

            # if zero_margin_index >= self.critical_index:
            #     part_1 = calc(calc(((zero_margin_index - self.critical_index + 1) * (zero_margin_index - self.critical_index) / 2), price_abs_step, '*'), each_grid_qty,
            #                   '*')
            #     for slice_index, slice_price in enumerate(all_grid_price[zero_margin_index + 1:]):
            #         part_2 = calc(calc((slice_index * (slice_index + 1) / 2), price_abs_step, '*'), each_grid_qty, '*')
            #         profit = calc(part_1, part_2, '-')
            #         if profit <= min_profit:
            #             up_stop_loss_price = slice_price
            #             break
            # else:
            #     for slice_index, slice_price in enumerate(all_grid_price[self.critical_index:]):
            #         part_1 = calc(calc((ini_order_num * slice_index), each_grid_qty, '*'), price_abs_step, '*')
            #         part_2 = calc(calc((slice_index * (slice_index - 1) / 2), price_abs_step, '*'), each_grid_qty, '*')
            #         profit = -calc(part_1, part_2, '+')
            #         if profit <= min_profit:
            #             up_stop_loss_price = slice_price
            #             break
            #
            # if zero_margin_index >= self.critical_index:
            #     for slice_index, slice_price in enumerate(reversed(all_grid_price[:self.critical_index + 1])):
            #         part_1 = calc(calc((ini_order_num * slice_index), each_grid_qty, '*'), price_abs_step, '*')
            #         part_2 = calc(calc((slice_index * (slice_index - 1) / 2), price_abs_step, '*'), each_grid_qty, '*')
            #         profit = -calc(part_1, part_2, '+')
            #         # self._log_info('{:<10}\t\t{:<10}'.format(profit, min_profit))
            #         if profit <= min_profit:
            #             down_stop_loss_price = slice_price
            #             break
            # else:
            #     part_1 = calc(calc(((self.critical_index - zero_margin_index + 1) * (self.critical_index - zero_margin_index) / 2), price_abs_step, '*'), each_grid_qty,
            #                   '*')
            #     for slice_index, slice_price in enumerate(reversed(all_grid_price[:zero_margin_index])):
            #         part_2 = calc(calc((slice_index * (slice_index + 1) / 2), price_abs_step, '*'), each_grid_qty, '*')
            #         profit = calc(part_1, part_2, '-')
            #         if profit <= min_profit:
            #             down_stop_loss_price = slice_price
            #             break

        if up_stop_loss_price == 0:
            up_stop_loss_price = '不触发止损'
        else:
            up_stop_loss_price = calc(up_stop_loss_price, all_grid_price[self.critical_index], '-')
        if down_stop_loss_price == 0:
            down_stop_loss_price = '不触发止损'
        else:
            down_stop_loss_price = calc(all_grid_price[self.critical_index], down_stop_loss_price, '-')

        info_texts += '\n初始现货花费\t\t{:<8}\t\t{:<8}\n'.format(str(ini_spot_cost), symbol_name[:-4])
        info_texts += '初始现货仓位\t\t{:<8}\t\t{:<8}\n'.format(str(ini_spot_pos), symbol_name[:-4])

        info_texts += '\n初始资金花费\t\t{:<8}\t\t{:<8}\n'.format(str(round(ini_cash_cost, 2)), symbol_name[-4:])
        info_texts += '初始资金仓位\t\t{:<8}\t\t{:<8}\n'.format(str(round(ini_cash_pos, 2)), symbol_name[-4:])

        # if zero_margin_index > self.critical_index:
        # ♥
        #     self._log_info('\n初始现货仓位\t\t{:<10}\t{:<10}'.format(str(0.0025), 'BTC'))
        #     self._log_info('\n初始资金花费\t\t{:<10}\t{:<10}'.format(str(458.6), 'BUSD'))

        info_texts += '\n最大现货花费\t\t{:<8}\t\t{:<8}\t于网格上边界\n'.format(str(max_spot_cost), symbol_name[:-4])
        info_texts += '最大资金花费\t\t{:<8}\t\t{:<8}\t于网格下边界\n'.format(str(round(max_cash_cost, 2)), symbol_name[-4:])

        info_texts += '\n上冲止损价差\t\t{:<8}\n'.format(str(up_stop_loss_price))
        info_texts += '下冲止损价差\t\t{:<8}\n'.format(str(down_stop_loss_price))
        info_texts += '\n*** {} ***'.format('=' * 32)

        return info_texts

    def confirm_params(self, input_params: dict) -> None:
        """
        最终确定参数，需要先执行参数合理化(由外部ui实现)
        :return:
        """
        self.symbol_name = input_params['symbol_name']
        self.grid_side = input_params['grid_side']
        self.grid_upper_limit = input_params['up_price']
        self.grid_down_limit = input_params['down_price']
        self.grid_price_step = input_params['price_abs_step']
        self.grid_qty_per_order = input_params['each_grid_qty']
        self.ini_trade_ratio = 1 if input_params['dul_selection'] == 0 else input_params['target_ratio']
        self.account_leverage = input_params['leverage']
        self.up_boundary_stop = input_params['up_boundary_stop']
        self.low_boundary_stop = input_params['low_boundary_stop']
        # todo: 本土化改造，可以直接修改策略
        if input_params['need_stop_loss']:
            self.stg_max_profit = 0 if input_params['max_profit'] == '' else input_params['max_profit']
            self.stg_min_profit = 0 if input_params['min_profit'] == '' else input_params['min_profit']
        else:
            self.stg_max_profit, self.stg_min_profit = 0, 0

        self._my_executor.start_single_contract_order_subscription(self.symbol_name)

    def acquire_token(self, stg_code: str) -> None:
        self.stg_num = stg_code
        self.stg_num_len = len(stg_code)

    def start(self) -> None:
        super().start()

    def stop(self) -> None:
        asyncio.create_task(self._terminate_trading(reason='人工手动结束'))

    def acquire_logger(self, my_logger: LogRecorder = None) -> None:
        """

        :param my_logger:
        :return:
        """
        if my_logger is None:
            print('未绑定logger')
            # sys.exit()

        self._my_logger = my_logger

    def provide_symbol_name(self) -> str:
        return self.symbol_name

    async def _start_strategy(self):
        """
        程序开始操作，整个程序的起点
        :return:
        """
        self._is_trading = True
        self._log_info('网格策略开始')
        # 等待 10s 启动
        self.all_grid_price = tuple(calc(self.grid_down_limit, calc(self.grid_price_step, i, '*'), '+') for i in range(self.grid_total_num))
        # self._log_info(self.all_grid_price)

        # 开启数据统计
        self._update_text_task = asyncio.create_task(self._update_detail_info(interval_time=1))
        fee_dict = await self._my_executor.get_symbol_trade_fee(self.symbol_name)
        self.symbol_maker_fee = fee_dict['maker_fee']
        self.symbol_taker_fee = fee_dict['taker_fee']

        await asyncio.sleep(0.2)
        # todo: 增加测试网格参数功能，提示所需占用保证金
        self._init_account_spot_qty = await self._my_executor.get_current_asset_qty(self.symbol_name)
        self._log_info('策略前账户现货仓位 {}'.format(self._init_account_spot_qty))
        self._spot_position_qty_theory = self._init_account_spot_qty
        # 第一步：开始撒网
        asyncio.create_task(self._layout_net())
        # await asyncio.sleep(0.3)
        # todo: 建议撒网后休息 5s , 期间按断网处理
        # 第二步：维护网格

    # strategy methods
    async def _layout_net(self):
        """
        策略第一步，在市价上下挂一定数量的挂单
        :return:
        """
        # todo: need to return?
        self._trading_statistics['strategy_start_time'] = self.gen_timestamp()
        current_symbol_price = await self._my_executor.get_current_price(self.symbol_name)
        # todo: temp strategy
        if not (self.grid_down_limit < current_symbol_price < self.grid_upper_limit):
            self._log_info('价格在范围外，需要手动终止策略')
            # todo: 初始的 critical index 所有可能情况需要判断
            # # sys.exit()
            return

        for each_index, each_grid_price in enumerate(self.all_grid_price):
            if each_grid_price <= current_symbol_price < (each_grid_price + self.grid_price_step):
                if current_symbol_price - each_grid_price <= self.grid_price_step / 2:
                    self.critical_index = each_index
                else:
                    self.critical_index = each_index + 1
        self._log_info('critical index = {}'.format(str(self.critical_index)))
        self._initial_index = self.critical_index
        self._zero_pos_index = self.critical_index

        if self.ini_trade_ratio > 0:
            # 市价下单
            ini_order_quantity = 0
            command = Token.ORDER_INFO.copy()
            if self.grid_side in ['BUY', 'Buy', 'buy']:
                ini_order_num = round(self.ini_trade_ratio * (self.max_index - self.critical_index))
                ini_order_quantity = calc(self.grid_qty_per_order, ini_order_num, '*')
                self._zero_pos_index += ini_order_num
                self._spot_position_qty_theory = calc(self._spot_position_qty_theory, ini_order_quantity, '+')
                # self._trading_statistics['filled_buy_order_num'] += ini_order_num
                command['side'] = self.BUY
                command['quantity'] = ini_order_quantity
            elif self.grid_side in ['SELL', 'Sell', 'sell']:
                ini_order_num = round(self.ini_trade_ratio * self.critical_index)
                ini_order_quantity = calc(self.grid_qty_per_order, ini_order_num, '*')
                self._zero_pos_index -= ini_order_num
                self._spot_position_qty_theory = calc(self._spot_position_qty_theory, ini_order_quantity, '-')
                # self._trading_statistics['filled_sell_order_num'] += ini_order_num
                command['side'] = self.SELL
                command['quantity'] = ini_order_quantity
            else:
                self._log_info('网格方向输入错误')
                # # sys.exit()
            self._log_info('市价下单数量: {}'.format(ini_order_quantity))
            await self.command_transmitter(trans_command=command, token=Token.TO_POST_MARKET)
            # todo: 此处为理论计算，存在获取实际数值的方法
            self._initial_position_price = current_symbol_price
            self._initial_position_qty = ini_order_quantity
            adding_volume = calc(ini_order_quantity, current_symbol_price, '*')
            self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
            self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_taker_fee, '*'), '+')
            print('init order qty = {}'.format(ini_order_quantity))
            print('初始计算成交量：{}'.format(self._trading_statistics['achieved_trade_volume']))

        # 布撒网格，使用batch order操作
        ini_buy_order_num = round((self.min_buy_order_num + self.max_buy_order_num) / 2)
        ini_sell_order_num = round((self.min_sell_order_num + self.max_sell_order_num) / 2)
        # ini_buy_price_list = self.all_grid_price[max(0, self.critical_index - ini_buy_order_num):self.critical_index]
        # ini_sell_price_list = self.all_grid_price[self.critical_index + 1:min(self.max_index, (self.critical_index + ini_sell_order_num + 1))]
        # todo: rethink a better method
        # self.open_buy_orders = [str.zfill(str(_index), 5) for _index in range(max(0, self.critical_index - ini_buy_order_num), self.critical_index)]
        # self.open_sell_orders = [str.zfill(str(_index), 5) for _index in range(self.critical_index + 1, min(self.max_index, (self.critical_index + ini_sell_order_num + 1)))]

        self.open_buy_orders = [
            {
                'id': self.gen_id(_index, self.BUY),
                'status': 'NEW',
                'time': self.gen_timestamp()
            } for _index in range(max(0, self.critical_index - ini_buy_order_num), self.critical_index)
        ]
        self.open_sell_orders = [
            {
                'id': self.gen_id(_index, self.SELL),
                'status': 'NEW',
                'time': self.gen_timestamp()
            } for _index in range(self.critical_index + 1, min(self.max_index, (self.critical_index + ini_sell_order_num + 1)))
        ]
        self._log_info('\n开始撒网\n')
        temp_buy_indices = [_each for _each in self.open_buy_orders]
        temp_sell_indices = [_each for _each in self.open_sell_orders]
        while True:
            temp_buy_indices, temp_post_buy = temp_buy_indices[:-5], temp_buy_indices[-5:]
            temp_sell_indices, temp_post_sell = temp_sell_indices[5:], temp_sell_indices[:5]
            # self._log_info(temp_post_buy, temp_post_sell)
            if len(temp_post_buy):
                batch_buy_command = Token.BATCH_ORDER_INFO.copy()
                batch_buy_command['orders'] = [
                    {
                        'symbol': self.symbol_name,
                        'id': each['id'],
                        'price': self.all_grid_price[self.parse_id(each['id'])[0]],
                        'side': self.BUY,
                        'quantity': self.grid_qty_per_order,
                        'status': Token.TO_POST_LIMIT
                    } for each in temp_post_buy
                ]
                await self.command_transmitter(trans_command=batch_buy_command, token=Token.TO_POST_BATCH)
            if len(temp_post_sell):
                batch_sell_command = Token.BATCH_ORDER_INFO.copy()
                batch_sell_command['orders'] = [
                    {
                        'symbol': self.symbol_name,
                        'id': each['id'],
                        'price': self.all_grid_price[self.parse_id(each['id'])[0]],
                        'side': self.SELL,
                        'quantity': self.grid_qty_per_order,
                        'status': Token.TO_POST_LIMIT
                    } for each in temp_post_sell
                ]
                await self.command_transmitter(trans_command=batch_sell_command, token=Token.TO_POST_BATCH)

            if len(temp_buy_indices) == 0 and len(temp_sell_indices) == 0:
                break
            # 减缓撒网速度
            await asyncio.sleep(0.3)

    async def _maintain_grid_order(self, filled_order_id: str, append_info: str = None) -> None:
        """
        策略第二步，挂单完成后，根据挂单成交情况不断维护挂单（网格策略）
        完全根据 receiver 信息做出响应
        注意：由于是 todo:断网重连策略
        # todo: 暂时只处理完全成交的理想情况，partially filled 待解决
        :return: None
        """
        if not self._is_trading:
            self._log_info('交易结束，不继续维护网格 order_id: {}'.format(filled_order_id))
            return

        if self._first_back:
            # 一个开关，只判断第一次
            if 'market' in filled_order_id:
                self._first_back = False
                return

        if append_info:
            self._log_info(append_info)
        self._log_info('维护网格\t\t\t\t网格位置 = {}'.format(self.critical_index))
        # 以 critical index 为基准进行维护
        this_order_index, this_order_side = self.parse_id(filled_order_id)

        if this_order_index == 0:
            if self.low_boundary_stop:
                self._log_info('达到网格下边界，退出策略')

                self.open_buy_orders = []
                filled_buy_num = self.critical_index - this_order_index
                self._trading_statistics['filled_buy_order_num'] += filled_buy_num
                adding_volume = calc_sum([calc(each_price, self.grid_qty_per_order, '*') for each_price in
                                          self.all_grid_price[this_order_index:self.critical_index]])
                self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
                self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

                self._spot_position_qty_theory = calc(self._spot_position_qty_theory, calc(filled_buy_num, self.grid_qty_per_order, '*'), '+')

                self.critical_index = this_order_index

                # await self._terminate_trading(reason='达到网格下边界')
                asyncio.create_task(self._terminate_trading(reason='达到网格下边界'))
                return

        elif this_order_index == self.max_index:
            if self.up_boundary_stop:
                self._log_info('达到网格上边界，退出策略')

                self.open_sell_orders = []
                # todo: 统计代码有些重复，可以优化
                filled_sell_num = this_order_index - self.critical_index
                self._trading_statistics['filled_sell_order_num'] += filled_sell_num
                adding_volume = calc_sum([calc(each_price, self.grid_qty_per_order, '*') for each_price in
                                          self.all_grid_price[self.critical_index + 1:this_order_index + 1]])
                self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
                self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

                self._spot_position_qty_theory = calc(self._spot_position_qty_theory, calc(filled_sell_num, self.grid_qty_per_order, '*'), '-')

                self.critical_index = this_order_index

                # await self._terminate_trading(reason='达到网格上边界')
                asyncio.create_task(self._terminate_trading(reason='达到网格上边界'))
                return

        elif this_order_index == -1:
            # todo: temp method
            self._log_info('unknown client_id: {}\nplz check code'.format(this_order_side))
            return

        """
        self._spot_position_qty_theory = calc(self._spot_position_qty_theory, calc(instant_post_num, self.grid_qty_per_order, '*'), '-')
        self._spot_position_qty_theory = calc(calc(instant_post_num, self.grid_qty_per_order, '*'), self._spot_position_qty_theory, '+')
        """
        # 第一步：根据成交情况在中心填补买卖单
        if this_order_index > self.critical_index:
            # 高价位的订单成交
            if this_order_side == self.SELL:
                # 上方卖单成交，维护网格
                # 需要瞬间补上的订单数量
                instant_post_num = this_order_index - self.critical_index
                self._trading_statistics['filled_sell_order_num'] += instant_post_num
                adding_volume = calc_sum([calc(each_price, self.grid_qty_per_order, '*') for each_price in
                                          self.all_grid_price[self.critical_index + 1:this_order_index + 1]])
                self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
                self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

                self._spot_position_qty_theory = calc(self._spot_position_qty_theory, calc(instant_post_num, self.grid_qty_per_order, '*'),  '-')
                self._log_info('{}卖  {:2} 订单成交\t\t价格: {:<12}\tid: {:<10}'.format
                                          (chr(12288), str(instant_post_num), str(self.all_grid_price[this_order_index]), filled_order_id))
                # self._log_info('卖 {} 订单成交，价格 {}'.format(str(instant_post_num), str(self.all_grid_price[this_order_index])))
                # todo: 测试好后撤销价格索引，提升效率
                instant_post_buy: list = [
                    {
                        'id': self.gen_id(each_index, self.BUY),
                        'status': 'NEW',
                        'time': self.gen_timestamp()
                    } for each_index in range(this_order_index - 1, self.critical_index - 1, -1)
                ]

                self.open_buy_orders = self.open_buy_orders + list(reversed(instant_post_buy))
                self.open_sell_orders = self.open_sell_orders[instant_post_num:]

                while True:
                    # todo: 如果2-5之间的情况频繁，考虑也用 batch order
                    if len(instant_post_buy) < 5:
                        for each_num, each_info in enumerate(instant_post_buy):
                            posting_order = Token.ORDER_INFO.copy()
                            posting_order['symbol'] = self.symbol_name
                            posting_order['id'] = each_info['id']
                            posting_order['price'] = self.all_grid_price[self.parse_id(each_info['id'])[0]]
                            posting_order['side'] = self.BUY
                            posting_order['quantity'] = self.grid_qty_per_order
                            self._log_info('挂买  {:2} 单\t\t\t价格: {:<12}\tid: {:<10}'.format(str(each_num + 1), posting_order['price'], posting_order['id']))
                            # self._log_info('在 {} 价位挂买单, id: {}'.format((str(posting_order['price'])), posting_order['id']))
                            await self.command_transmitter(trans_command=posting_order, token=Token.TO_POST_LIMIT)
                        break
                    else:
                        instant_post_batch, instant_post_buy = instant_post_buy[:5], instant_post_buy[5:]

                        batch_order = Token.BATCH_ORDER_INFO.copy()
                        batch_order['orders'] = [
                            {
                                'symbol': self.symbol_name,
                                'id': each_info['id'],
                                'price': self.all_grid_price[self.parse_id(each_info['id'])[0]],
                                'side': self.BUY,
                                'quantity': self.grid_qty_per_order,
                            } for each_info in instant_post_batch
                        ]
                        self._log_info('批量挂买单')
                        await self.command_transmitter(trans_command=batch_order, token=Token.TO_POST_BATCH)

                self.critical_index = this_order_index

            elif this_order_side == self.BUY:
                # 上方买单成交，出现快速行情，已经提前反应
                self._log_info('{}买 -{:2} 订单成交\t\t价格: {:<12}\tid: {:<10}\t\t已提前做出反应'.format
                                          (chr(12288), str(this_order_index - self.critical_index), str(self.all_grid_price[this_order_index]), filled_order_id))
                # self._log_info('买 -{} 订单成交，价格 {} ,已提前做出反应'.format(str(this_order_index - self.critical_index), str(self.all_grid_price[this_order_index])))
            else:
                self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

        elif this_order_index < self.critical_index:
            # 低价位的订单成交
            if this_order_side == self.BUY:
                # 下方买单成交，维护网格
                instant_post_num = self.critical_index - this_order_index
                self._trading_statistics['filled_buy_order_num'] += instant_post_num
                adding_volume = calc_sum([calc(each_price, self.grid_qty_per_order, '*') for each_price in
                                          self.all_grid_price[this_order_index:self.critical_index]])
                self._trading_statistics['achieved_trade_volume'] = calc(self._trading_statistics['achieved_trade_volume'], adding_volume, '+')
                self._trading_statistics['total_trading_fees'] = calc(self._trading_statistics['total_trading_fees'], calc(adding_volume, self.symbol_maker_fee, '*'), '+')

                self._spot_position_qty_theory = calc(calc(instant_post_num, self.grid_qty_per_order, '*'), self._spot_position_qty_theory, '+')
                self._log_info('{}买  {:2} 订单成交\t\t价格: {:<12}\tid: {:<10}'.format
                                          (chr(12288), str(instant_post_num), str(self.all_grid_price[this_order_index]), filled_order_id))
                # self._log_info('买 {} 订单成交，价格 {}'.format(str(instant_post_num), str(self.all_grid_price[this_order_index])))
                # todo: 测试好后撤销价格索引，提升效率
                instant_post_sell: list = [
                    {
                        'id': self.gen_id(each_index, self.SELL),
                        'status': 'NEW',
                        'time': self.gen_timestamp()
                    } for each_index in range(this_order_index + 1, self.critical_index + 1)
                ]

                self.open_buy_orders = self.open_buy_orders[:-instant_post_num]
                self.open_sell_orders = instant_post_sell + self.open_sell_orders

                while True:
                    if len(instant_post_sell) < 5:
                        for each_num, each_info in enumerate(instant_post_sell):
                            posting_order = Token.ORDER_INFO.copy()
                            posting_order['symbol'] = self.symbol_name
                            posting_order['id'] = each_info['id']
                            posting_order['price'] = self.all_grid_price[self.parse_id(each_info['id'])[0]]
                            posting_order['side'] = self.SELL
                            posting_order['quantity'] = self.grid_qty_per_order
                            self._log_info('挂卖  {:2} 单\t\t\t价格: {:<12}\tid: {:<10}'.format(str(each_num + 1), posting_order['price'], posting_order['id']))
                            # self._log_info('在 {} 价位挂卖单, id: {}'.format((str(posting_order['price'])), posting_order['id']))
                            # self._log_info('在 {} 价位挂卖单, id: {}'.format((str(posting_order['price'])), posting_order['id']))
                            await self.command_transmitter(trans_command=posting_order, token=Token.TO_POST_LIMIT)
                        break
                    else:
                        instant_post_batch, instant_post_sell = instant_post_sell[:5], instant_post_sell[5:]

                        batch_order = Token.BATCH_ORDER_INFO.copy()
                        batch_order['orders'] = [
                            {
                                'symbol': self.symbol_name,
                                'id': each_info['id'],
                                'price': self.all_grid_price[self.parse_id(each_info['id'])[0]],
                                'side': self.SELL,
                                'quantity': self.grid_qty_per_order,
                            } for each_info in instant_post_batch
                        ]
                        self._log_info('批量挂卖单')
                        await self.command_transmitter(trans_command=batch_order, token=Token.TO_POST_BATCH)

                self.critical_index = this_order_index

            elif this_order_side == self.SELL:
                # 下方卖单成交，出现快速行情，已经提前反应
                self._log_info('{}卖 -{:2} 订单成交\t\t价格: {:<12}\tid: {:<10}\t\t已提前做出反应'.format
                                          (chr(12288), str(self.critical_index - this_order_index), str(self.all_grid_price[this_order_index]), filled_order_id))
                # self._log_info('卖 -{} 订单成交，价格 {} ,已提前做出反应'.format(str(this_order_index - self.critical_index), str(self.all_grid_price[this_order_index])))
            else:
                self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

        else:
            # self._log_info('unexpected case that order at critical_index is filled, plz recheck\nid: {}'.format(filled_order_id))
            if this_order_side == self.BUY:
                self._log_info('{}买  {:2} 订单成交\t\t\t价格: {:<12}\tid: {:<10}\t\t延迟有点大'.format
                                          (chr(12288), str(0), str(self.all_grid_price[this_order_index]), filled_order_id))
            elif this_order_side == self.SELL:
                self._log_info('{}卖  {:2} 订单成交\t\t\t价格: {:<12}\tid: {:<10}\t\t延迟有点大'.format
                                          (chr(12288), str(0), str(self.all_grid_price[this_order_index]), filled_order_id))
            else:
                self._log_info('id is not unified form defined by analyzer, plz recheck\nid: {}'.format(filled_order_id))

        # 第二步：填补完成后，检查买卖单数量并维护其边界挂单，补单全用batch order
        # 买单挂单维护
        if len(self.open_buy_orders) > self.max_buy_order_num:
            post_cancel, self.open_buy_orders = self.open_buy_orders[:self.buffer_num], self.open_buy_orders[self.buffer_num:]
            for each_info in post_cancel:
                cancel_cmd = Token.ORDER_INFO.copy()
                cancel_cmd['symbol'] = self.symbol_name
                cancel_cmd['id'] = each_info['id']
                await self.command_transmitter(trans_command=cancel_cmd, token=Token.TO_CANCEL)

        elif 0 < len(self.open_buy_orders) < self.min_buy_order_num:
            endpoint_index = self.parse_id(self.open_buy_orders[0]['id'])[0]
            if endpoint_index > 0:
                # =0时已经达到边界，不补充挂单
                filling_post_buy: list = [
                    {
                        'id': self.gen_id(each_index, self.BUY),
                        'status': 'NEW',
                        'time': self.gen_timestamp()
                    } for each_index in range(max(0, endpoint_index - self.buffer_num), endpoint_index)
                ]
                self.open_buy_orders = filling_post_buy + self.open_buy_orders
                while True:
                    if len(filling_post_buy) == 0:
                        break
                    filling_post_batch, filling_post_buy = filling_post_buy[:5], filling_post_buy[5:]
                    filling_batch_cmd = Token.BATCH_ORDER_INFO.copy()
                    filling_batch_cmd['orders'] = [
                        {
                            'symbol': self.symbol_name,
                            'id': _info['id'],
                            'price': self.all_grid_price[self.parse_id(_info['id'])[0]],
                            'side': self.BUY,
                            'quantity': self.grid_qty_per_order,
                        } for _info in filling_post_batch
                    ]
                    await self.command_transmitter(trans_command=filling_batch_cmd, token=Token.TO_POST_BATCH)

        # 卖单挂单维护
        if len(self.open_sell_orders) > self.max_sell_order_num:
            self.open_sell_orders, post_cancel = self.open_sell_orders[:-self.buffer_num], self.open_sell_orders[-self.buffer_num:]
            for each_info in post_cancel:
                cancel_cmd = Token.ORDER_INFO.copy()
                cancel_cmd['symbol'] = self.symbol_name
                cancel_cmd['id'] = each_info['id']
                await self.command_transmitter(trans_command=cancel_cmd, token=Token.TO_CANCEL)

        elif 0 < len(self.open_sell_orders) < self.min_sell_order_num:
            endpoint_index = self.parse_id(self.open_sell_orders[-1]['id'])[0]
            if endpoint_index < self.max_index:
                # 否则已经达到边界，不补充挂单
                filling_post_sell: list = [
                    {
                        'id': self.gen_id(each_index, self.SELL),
                        'status': 'NEW',
                        'time': self.gen_timestamp()
                    } for each_index in range(endpoint_index + 1, min(self.max_index, endpoint_index + self.buffer_num) + 1)
                ]
                self.open_sell_orders = self.open_sell_orders + filling_post_sell
                while True:
                    if len(filling_post_sell) == 0:
                        break
                    filling_post_batch, filling_post_sell = filling_post_sell[:5], filling_post_sell[5:]
                    filling_batch_cmd = Token.BATCH_ORDER_INFO.copy()
                    filling_batch_cmd['orders'] = [
                        {
                            'symbol': self.symbol_name,
                            'id': _info['id'],
                            'price': self.all_grid_price[self.parse_id(_info['id'])[0]],
                            'side': self.SELL,
                            'quantity': self.grid_qty_per_order,
                        } for _info in filling_post_batch
                    ]
                    await self.command_transmitter(trans_command=filling_batch_cmd, token=Token.TO_POST_BATCH)

        # 第三步：每成交一定量的订单，判断止盈止损
        if (self._trading_statistics['filled_buy_order_num'] + self._trading_statistics['filled_sell_order_num']) % 10 == 0:
            # await self._update_trading_statistics()
            self._update_column_text()
            await self._take_profit_stop_loss()

    async def _update_trading_statistics(self):
        """
        更新统计数据
        :return:
        """
        filled_trading_pair = min(self._trading_statistics['filled_buy_order_num'], self._trading_statistics['filled_sell_order_num'])
        self._trading_statistics['matched_profit'] = calc(calc(filled_trading_pair, self.grid_price_step, '*'), self.grid_qty_per_order, '*')
        # 手算的，使用于等差网格
        if self.grid_side == self.BUY:
            unmatched_1 = calc(calc(self.all_grid_price[self.critical_index], self._initial_position_price, '-'), self._initial_position_qty, '*')
        elif self.grid_side == self.SELL:
            unmatched_1 = calc(calc(self._initial_position_price, self.all_grid_price[self.critical_index], '-'), self._initial_position_qty, '*')
        else:
            unmatched_1 = 0
        unmatched_2 = - abs(self.critical_index - self._initial_index) * (abs(self.critical_index - self._initial_index) - 1) / 2
        unmatched_2 = calc(unmatched_2, calc(self.grid_qty_per_order, self.grid_price_step, '*'), '*')

        self._trading_statistics['unmatched_profit'] = calc(unmatched_1, unmatched_2, '+')
        self._trading_statistics['final_profit'] = calc(calc(self._trading_statistics['matched_profit'], self._trading_statistics['unmatched_profit'], '+'),
                                                        self._trading_statistics['total_trading_fees'], '-')

    async def _take_profit_stop_loss(self):
        """
        判断策略收益情况，实现止盈止损
        :return:
        """

        total_profit = calc(self._trading_statistics['matched_profit'], self._trading_statistics['unmatched_profit'], '+')

        if self.stg_max_profit == 0:
            # 不止盈
            pass
        else:
            if total_profit >= self.stg_max_profit:
                self._log_info('达到预期收益，止盈，策略停止')
                # await self._terminate_trading(reason='策略止盈')
                # todo: await方法 似乎margin可以止盈，但是futures会出问题？测试。。
                asyncio.create_task(self._terminate_trading(reason='策略止盈'))

        if self.stg_min_profit == 0:
            # 不止损
            pass
        else:
            if total_profit <= self.stg_min_profit:
                self._log_info('触发止损，终止策略')
                # await self._terminate_trading(reason='策略止损')
                asyncio.create_task(self._terminate_trading(reason='策略止损'))

    def _update_column_text(self):
        """
        更新 column 显示的策略收益
        :return:
        """
        # todo: 考虑使用pandas
        self._bound_running_column.update_profit_text(
            matched_profit=str(self._trading_statistics['matched_profit']),
            unmatched_profit=str(self._trading_statistics['unmatched_profit'])
        )

    async def _terminate_trading(self, reason: str = '') -> None:
        """
        结束交易
        操作：取消所有挂单，买平当前仓位，todo: 并输出最终统计结果
        :return:
        """
        if not self._is_trading:
            # todo: 此处是防止用户乱点停止交易，或者停止过程中突然有其他原因停止
            return
        self._is_trading = False
        self._update_text_task.cancel()
        cancel_cmd, close_cmd = Token.ORDER_INFO.copy(), Token.ORDER_INFO.copy()
        cancel_cmd['symbol'], close_cmd['symbol'] = self.symbol_name, self.symbol_name

        await asyncio.sleep(0.8)  # todo: 此处延时是为了确保能撤销所有挂单，防止撤单和挂单同时请求，最后出现还剩一单挂着的情况
        await self.command_transmitter(trans_command=cancel_cmd, token=Token.CANCEL_ALL)
        await self._update_trading_statistics()
        await asyncio.sleep(3)

        self._log_info('市价平仓')
        self._log_info('策略开始前账户现货仓位:\t{}\t{}'.format(self._init_account_spot_qty, self.symbol_name[:-4]))
        self._log_info('累计理论计算当前现货仓位:\t{}\t{}'.format(self._spot_position_qty_theory, self.symbol_name[:-4]))
        # 此处的qty意在传递一个信息，即策略开始前的仓位
        current_qty = await self._my_executor.get_current_asset_qty(self.symbol_name)
        self._log_info('账户实际当前现货仓位:\t{}\t{}'.format(current_qty, self.symbol_name[:-4]))
        close_qty = round_step_size(calc(current_qty, self._init_account_spot_qty, '-'), self.symbol_quantity_min_step, upward=True)
        # todo: 下单可能小于min notional,需要处理
        if close_qty != 0:
            self._log_info('实际市价平掉仓位 {}'.format(str(close_qty)))
            close_cmd['quantity'] = abs(close_qty)
            close_cmd['side'] = self.SELL if (close_qty > 0) else self.BUY
            close_cmd['id'] = 'close-position'
            await self.command_transmitter(trans_command=close_cmd, token=Token.TO_POST_MARKET)
        else:
            self._log_info('实际不需要市价平仓')

        self._log_info('终止策略，终止原因: {}'.format(reason))
        await self._update_detail_info(only_once=True)

        self._my_logger.close_file()

        self._my_executor.stop_single_contract_order_subscription(self.symbol_name)
        self._my_executor.strategy_stopped(self.stg_num)

        # todo: 此处或许应该在基类中定义
        self._bound_running_column = None

    async def _update_detail_info(self, interval_time: int = 1, only_once: bool = False) -> None:
        """
        定时更新显示在窗口右上角的详细策略信息
        并更新
        :param interval_time: 更新间隔时间
        :param only_once: 表示该 coroutine 只运行一次便终止，用于策略停止后最后更新一次数据
        :return:
        """
        if self._first_back:
            await asyncio.sleep(5)

        while True:
            await self._update_trading_statistics()
            self._update_column_text()

            start_t = pd.to_datetime(self._trading_statistics['strategy_start_time'], unit='ms')
            current_t = pd.to_datetime(self.gen_timestamp(), unit='ms')
            running_time = current_t - start_t
            days: int = running_time.days
            seconds: int = running_time.seconds
            hours, seconds = int(seconds / 3600), seconds % 3600
            minutes, seconds = int(seconds / 60), seconds % 60

            showing_texts = '\n\n*** {} ***\n\n'.format('=' * 51)

            if days == 0:
                showing_texts += '交易统计\t\t运行时间\t\t{}:{}:{}\n\n'.format(str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2))
            else:
                showing_texts += '交易统计\t\t运行时间\t\t{} day\t{}:{}:{}\n\n'.format(
                    str(days), str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2))
            # showing_texts += '交易统计:\t\t当前时间 {}\n\n'.format(str(str(pd.to_datetime(self.gen_timestamp(), unit='ms'))))
            showing_texts += '-' * 58
            showing_texts += '\n\n卖单挂单成交次数:\t{:<10}\n'.format(str(self._trading_statistics['filled_sell_order_num']))
            showing_texts += '买单挂单成交次数:\t{:<10}\n\n'.format(str(self._trading_statistics['filled_buy_order_num']))
            showing_texts += '-' * 58
            showing_texts += '\n\n已达成交易量:\t\t{:<20}\t{}\n\n'.format(str(self._trading_statistics['achieved_trade_volume']), self.symbol_name[-4:])
            showing_texts += '-' * 58
            showing_texts += '\n\n已实现套利:\t\t{:<20}\t{}\n'.format(self._trading_statistics['matched_profit'], self.symbol_name[-4:])
            showing_texts += '未配对盈亏:\t\t{:<20}\t{}\n'.format(self._trading_statistics['unmatched_profit'], self.symbol_name[-4:])
            showing_texts += '交易手续费:\t\t{:<20}\t{}\n'.format(self._trading_statistics['total_trading_fees'], self.symbol_name[-4:])
            showing_texts += '\n策略净收益:\t\t{:<20}\t{}\n\n'.format(self._trading_statistics['final_profit'], self.symbol_name[-4:])
            showing_texts += '*** {} ***\n\n'.format('=' * 51)

            self._bound_running_column.update_trade_info(showing_texts)

            if only_once:
                return

            await asyncio.sleep(interval_time)
            await self._take_profit_stop_loss()

    async def _output_statistics(self, interval_time: int = 900) -> None:
        """
        交易数据统计，粗略统计买卖单成交次数，粗略计算已套利利润
        :param interval_time: 每次输出统计的时间间隔，默认 15 min
        :return:
        """
        if self._first_back:
            await asyncio.sleep(60)

        while True:
            if not self._is_trading:
                break
            start_t = pd.to_datetime(self._trading_statistics['strategy_start_time'], unit='ms')
            current_t = pd.to_datetime(self.gen_timestamp(), unit='ms')
            running_time = current_t - start_t
            days: int = running_time.days
            seconds: int = running_time.seconds
            hours, seconds = int(seconds / 3600), seconds % 3600
            minutes, seconds = int(seconds / 60), seconds % 60

            self._log_info('\n\n*** {} ***'.format('=' * 51))
            if days == 0:
                self._log_info('交易统计\t\t\t运行时间\t\t{}:{}:{}'.format(str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2)))
            else:
                self._log_info('交易统计\t\t\t运行时间\t\t{} day\t{}:{}:{}'.format(str(days), str(hours).zfill(2), str(minutes).zfill(2), str(seconds).zfill(2)))
            self._log_info('-' * 30)
            self._log_info('总成交次数: {}'.format(str(self._trading_statistics['filled_buy_order_num'] + self._trading_statistics['filled_sell_order_num'])))
            self._log_info('买单挂单成交次数: {}'.format(str(self._trading_statistics['filled_buy_order_num'])))
            self._log_info('卖单挂单成交次数: {}'.format(str(self._trading_statistics['filled_sell_order_num'])))
            self._log_info('-' * 30)
            self._log_info('已实现套利: {}  {}'.format(str(self._trading_statistics['matched_profit']), self.symbol_name[-4:]))
            self._log_info('未配对盈亏: {}  {}'.format(str(self._trading_statistics['unmatched_profit']), self.symbol_name[-4:]))
            self._log_info('*** {} ***\n\n'.format('=' * 51))
            await asyncio.sleep(interval_time)

    async def show_statistics(self) -> tuple[str, str]:
        """
        被动输出简易统计信息，显示在 ui 界面上
        :return: 已完成套利，未实现盈亏
        """
        # todo: 是否有办法修改为主动显示，即每次更新都会在ui上更新
        await self._update_trading_statistics()

        return str(self._trading_statistics['matched_profit']), str(self._trading_statistics['unmatched_profit'])

    async def show_final_statistics(self) -> str:
        """
        策略结束后，输出最终统计信息
        :return:
        """
        await self._update_trading_statistics()
        return str(self._trading_statistics['final_profit'])

    # interaction methods
    async def report_receiver(self, recv_data_dict: dict, append_info: str = None) -> None:
        """
        与 Executor 通信的唯一接收渠道
        负责接受信息并传达需要的命令
        :param recv_data_dict: 收到的规范化通信信息
        :param append_info:
        :return: None
        """
        if recv_data_dict['status'] == Token.ORDER_FILLED:
            # 传入的id是客户端的自定订单id
            await self._maintain_grid_order(recv_data_dict['id'], append_info)
        elif recv_data_dict['status'] == Token.POST_SUCCESS:
            # todo: log this
            self._log_info('收到挂单成功信息\t\t价格: {:<12}\tid: {:<10}'.format(str(float(recv_data_dict['price'])), recv_data_dict['id']))
            pass
        elif recv_data_dict['status'] == Token.CANCEL_SUCCESS:
            self._log_info('收到撤单成功信息\t\t\t\tid: {:<10}'.format(recv_data_dict['id']))
            pass
        elif recv_data_dict['status'] == Token.PARTIALLY_FILLED:
            # todo: handle this
            self._log_info('订单部分成交!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            pass
        elif recv_data_dict['status'] == Token.UNIDENTIFIED:
            pass
        elif recv_data_dict['status'] == Token.FAILED:
            pass
        elif recv_data_dict['status'] == Token.POST_FAILED:
            self._log_info('\n限价挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            pass
        elif recv_data_dict['status'] == Token.POC_FAILED:
            self._log_info('\npoc挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            pass
        elif recv_data_dict['status'] == Token.CANCEL_FAILED:
            self._log_info('\n撤销挂单失败!!!\t\t价格: {:<12}\tid: {:<10}'.format(recv_data_dict['price'], recv_data_dict['id']))
            pass
        elif recv_data_dict['status'] == Token.TEMP_TOKEN:
            # todo: temp command
            await self.command_transmitter(trans_command=recv_data_dict, token=Token.TEMP_TOKEN)

    async def command_transmitter(self, trans_command: dict = None, token: str = None) -> None:
        """
        与 Executor 通信的唯一发送渠道
        负责生成并传达规范化命令信息

        注意：该函数发送命令 只能使用 asyncio.create_task
        :param trans_command: 规范化命令信息
        :param token: 下达何种命令，规范化令牌
        :return: None
        """
        command_dict = Token.ORDER_INFO.copy()
        command_dict['symbol'] = self.symbol_name

        if token == Token.TO_POST_LIMIT:
            # todo: 是否有点冗余
            command_dict['id'] = trans_command['id']
            command_dict['price'] = trans_command['price']
            command_dict['side'] = trans_command['side']
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self._my_executor.command_receiver(command_dict))
        elif token == Token.TO_CANCEL:
            command_dict['id'] = trans_command['id']
            command_dict['status'] = token
            asyncio.create_task(self._my_executor.command_receiver(command_dict))
        elif token == Token.TO_POST_BATCH:
            asyncio.create_task(self._my_executor.command_receiver(trans_command))
        elif token == Token.TO_POST_MARKET:
            command_dict['side'] = trans_command['side']
            command_dict['id'] = '{}_{}-{}-{}'.format(self.stg_num, self.symbol_name, self.grid_side, 'market')
            command_dict['id'] = command_dict['id'][:28]  # 防止超出文本长度上线
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self._my_executor.command_receiver(command_dict))
        elif token == Token.CANCEL_ALL:
            command_dict['status'] = token
            asyncio.create_task(self._my_executor.command_receiver(command_dict))
        elif token == Token.CLOSE_POSITION:
            command_dict['quantity'] = trans_command['quantity']
            command_dict['status'] = token
            asyncio.create_task(self._my_executor.command_receiver(command_dict))
        elif token == Token.TEMP_TOKEN:
            command_dict['status'] = token
            asyncio.create_task(self._my_executor.command_receiver(command_dict))
        elif token is None:
            self._log_info('未定义命令类型，不发送')
        else:
            self._log_info('错误定义命令类型，不发送')

    # tool methods
    def gen_id(self, self_index: int, side: str) -> str:
        """
        生成分析者自定义(方便即可)订单 id
        :param self_index: 该order的价格index
        :param side: 方向，需要规范化输入
        :return:
        """
        self_id = self.stg_num + '_' + str.zfill(str(self_index), 5) + side
        return self_id

    @staticmethod
    def unmatched_profit_calc(initial_index: int, current_index: int, all_prices: tuple[float | int], each_gird_qty: float,
                              init_pos_price: float = 0, init_pos_qty: float = 0) -> float:
        """
        便携计算器，用于计算网格未配对盈亏
        计算方法：将盈利拆分成一个初始仓位的单向买多(卖空)和一个中性网格的盈利
        :param initial_index: 初始的index
        :param current_index: 目标价位的index
        :param all_prices: 网格所有价格
        :param each_gird_qty: 每格数量，真实数量
        :param init_pos_price: 初始仓位价格
        :param init_pos_qty: 初始仓位数量，真实绝对数量，大于0代表买多，小于0做空
        :return:
        """
        grid_price_step = calc(all_prices[1], all_prices[0], '-')
        if current_index == -1:
            current_index = len(all_prices) - 1

        part_1 = calc(calc(all_prices[current_index], init_pos_price, '-'), init_pos_qty, '*')

        part_2 = - abs(current_index - initial_index) * (abs(current_index - initial_index) - 1) / 2
        part_2 = calc(calc(each_gird_qty, grid_price_step, '*'), part_2, '*')

        return calc(part_1, part_2, '+')

    @staticmethod
    def id_in_order_list() -> tuple[bool, int]:
        pass

    @staticmethod
    def parse_id(client_id: str) -> tuple[int, str]:
        """
        解析自定义id中的index和side信息，先洗去stg_num信息
        [0]索引得到index
        :param client_id: stg8_00058BUY
        :return:
        """
        internal_client_id = client_id.split('_')[-1]
        try:
            order_index = int(internal_client_id[:5])
            order_side = internal_client_id[5:]
        except ValueError:
            order_index = -1
            order_side = client_id

        return order_index, order_side

    @staticmethod
    def gen_timestamp():
        return int(round(time.time() * 1000))

    def __del__(self):
        print('\n{}: {} analyzer 实例被删除，释放资源\n'.format(self.stg_num, self.symbol_name))
        pass


if __name__ == '__main__':
    test_analyzer = ArithmeticGridAnalyzerMargin()
    test_analyzer.acquire_token('stg8')
    print(test_analyzer.gen_id(88, 'BUY'))

