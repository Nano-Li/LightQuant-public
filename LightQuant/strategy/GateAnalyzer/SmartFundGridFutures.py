# -*- coding: utf-8 -*-
# @Time : 2024/3/22 9:49
# @Author : 
# @File : SmartFundGridFutures.py 
# @Software: PyCharm
import asyncio
import numpy as np
import pandas as pd
from LightQuant.tools.calc import calc, calc_sum
from LightQuant.tools.round_step_size import round_step_size
from .SmartGridFutures import SmartGridAnalyzerFutures


class SmartFundGridAnalyzerFutures(SmartGridAnalyzerFutures):
    """
    适用于所有合约的新智能调仓，采用等比网格
    采用 80% 递减资金投资
    """

    STG_NAME = '智能资金调仓网格'

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

    def __init__(self):
        super().__init__()

        # 增添额外变量
        self.fund_decrease_ratio = 0.8

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

            # 判断杠杆数是否合理
            if self._x_leverage > self.symbol_max_leverage:
                self._x_leverage = str(self._x_leverage) + '杠杆数值超限'
                param_valid = False

            # 判断触发价是否合理
            if param_valid and self._x_trigger_start:
                self._x_trigger_price = round_step_size(self._x_trigger_price, self.symbol_price_min_step)

                if self._x_trigger_price >= self.current_symbol_price:
                    self._x_trigger_price = str(self._x_trigger_price) + '触发价高于市场价'
                    param_valid = False

                if param_valid:
                    if abs(self._x_trigger_price - self.current_symbol_price) >= self.current_symbol_price * self.symbol_order_price_div:
                        self._x_trigger_price = str(self._x_trigger_price) + '触发价过低，不能挂单'
                        param_valid = False

            if self._x_trigger_start:
                entry_price = self._x_trigger_price
            else:
                entry_price = self.current_symbol_price

            # 判断并规则上界价格，由于实际网格价格的存在，该上界价格为虚值，实际以网格最大价格为准
            if param_valid:
                if self._x_trigger_start:
                    if self._x_grid_up_limit <= self._x_trigger_price:
                        self._x_grid_up_limit = str(self._x_grid_up_limit) + '上界低于触发价'
                        param_valid = False
                    else:
                        self._x_grid_up_limit = round_step_size(self._x_grid_up_limit, self.symbol_price_min_step)
                else:
                    if self._x_grid_up_limit <= self.current_symbol_price:
                        self._x_grid_up_limit = str(self._x_grid_up_limit) + '当前价高于上界'
                        param_valid = False
                    else:
                        self._x_grid_up_limit = round_step_size(self._x_grid_up_limit, self.symbol_price_min_step)

            # 套利部分，首先设定默认值
            if param_valid:
                if self._x_price_rel_step == '':
                    self._x_price_rel_step = 0.5
                if self._x_filling_step == '':
                    self._x_filling_step = 20
                if self._x_lower_step == '':
                    self._x_lower_step = 30

                # 设定数字精度，降低计算难度
                self._x_price_rel_step = round_step_size(self._x_price_rel_step, 0.0001)  # 百万分之一
                self._x_filling_step = round(self._x_filling_step, 2)
                self._x_lower_step = round(self._x_lower_step, 2)
                # 如果输入0，则使用最小精度
                self._x_price_rel_step = max(self._x_price_rel_step, round_step_size(self.symbol_price_min_step / entry_price, 0.0001))
                # 计算上下方网格数量
                up_grid_num = int(np.floor(np.log(1 + self._x_filling_step / 100) / np.log(1 + self._x_price_rel_step / 100)))  # 不计算base网格，算上顶部价格的网格，由于实际网格是用顶部网格代替最高价格，所以数量不变
                try:
                    low_grid_num = int(np.floor(np.log(1 - self._x_lower_step / 100) / np.log(1 - self._x_price_rel_step / 100)))
                except ValueError as Ve:
                    print(Ve)
                    print(f'lower_step = {self._x_lower_step}, price_step = {self._x_price_rel_step}')
                    raise Ve
                # print('上方网格数量:{}\t下方网格数量:{}'.format(up_grid_num, low_grid_num))

                # 补仓次数需要大于1
                if self._x_grid_up_limit <= round_step_size(calc(entry_price, calc(1, calc(calc(self._x_filling_step, calc(self._x_price_rel_step, 2, '*'), '+'), 100, '/'), '+'),
                                                                 '*'), self.symbol_price_min_step):  # 补仓点位 + 2 * 网格比例间距，上界价格大于该价格
                    self._x_grid_up_limit = str(self._x_grid_up_limit) + '补仓次数小于1'
                    param_valid = False

                if up_grid_num < 5:
                    self._x_filling_step = str(self._x_filling_step) + '上方空间不足'
                    param_valid = False
                elif low_grid_num < 5:
                    self._x_lower_step = str(self._x_lower_step) + '下方空间不足'
                    param_valid = False

                if param_valid:
                    if self._x_lower_step >= 100:
                        self._x_lower_step = str(self._x_lower_step) + '价格不能为负'
                        param_valid = False

                # 最后判断金额大小，使用最高补单价格判断最低金额
                if param_valid:
                    filling_times = int(np.floor(np.log(self._x_grid_up_limit / entry_price) / np.log(1 + self._x_filling_step / 100)))
                    max_filling_price = self.round_step_precision(entry_price * (1 + self._x_filling_step / 100) ** filling_times, self.symbol_price_min_step)
                    min_fund_demand = calc(max_filling_price, calc(up_grid_num, self.symbol_quantity_min_step, '*'), '*')
                    init_fund_demand = min_fund_demand * ((1 / self.fund_decrease_ratio) ** filling_times)
                    # print('最低金额需求: {} USDT'.format(min_fund_demand))
                    # 最低资金加一美刀，保险
                    self._x_filling_fund = max(self._x_filling_fund, round(init_fund_demand + 1, 2))

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
        if self.trigger_start:
            info_texts += '\n\t\t\t\t触发价格: {}\n'.format(str(self.trigger_price))

        # 计算一些参考数据，套利利润
        present_grid_step = calc(self.all_grid_price[self.entry_index + 1], self.all_grid_price[self.entry_index], '-')
        present_grid_precision_multi = int(calc(present_grid_step, self.symbol_price_min_step, '/'))  # 当前网格间距精度倍数
        each_grid_profit_low = calc(calc(self.all_grid_price[self.entry_index + 1], self.all_grid_price[self.entry_index], '-'),
                                    calc(self.all_grid_quantity[self.entry_index + 1], self.symbol_quantity_min_step, '*'), '*')
        each_grid_profit_high = calc(calc(self.all_grid_price[self.present_step_up_index], self.all_grid_price[self.present_step_up_index - 1], '-'),
                                     calc(self.all_grid_quantity[self.present_step_up_index], self.symbol_quantity_min_step, '*'), '*')
        filling_margin_occupation = calc(calc(calc(self.entry_grid_qty, self.symbol_quantity_min_step, '*'), self.entry_grid_price, '*'), self.symbol_leverage, '/')
        # 经过计算，由于策略的等比性质，不同台阶位置的套利区间底部保证金占用和策略亏损(相同回撤比例)基本相同
        max_margin_cost = calc(calc(calc(sum(self.all_grid_quantity[self.present_bottom_index + 1:self.present_step_up_index + 1]),
                                         self.symbol_quantity_min_step, '*'), self.present_bottom_price, '*'), self.symbol_leverage, '/')
        # 给出参考亏损，即台阶底部亏损
        max_loss_ref = self.unmatched_profit_calc(
            initial_index=self.entry_index + 1,
            current_index=0,
            all_prices=self.all_grid_price,
            all_quantities=self.all_grid_quantity,
            init_pos_price=self.entry_grid_price,
            init_pos_qty=self.entry_grid_qty,
            current_price=self.all_grid_price[0]
        )
        # 维持策略所需账户资金
        self._reasonable_order_num_estimate()
        order_margin = calc(calc(calc(calc_sum([calc(each_pri, each_qty, '*') for each_pri, each_qty in zip(self.all_grid_price[self.entry_index - self.max_buy_order_num:self.entry_index], self.all_grid_quantity[self.entry_index - self.max_buy_order_num:self.entry_index])]),
                                      calc_sum([calc(each_pri, each_qty, '*') for each_pri, each_qty in zip(self.all_grid_price[self.entry_index + 1:self.entry_index + self.max_sell_order_num + 1], self.all_grid_quantity[self.entry_index + 1:self.entry_index + self.max_sell_order_num + 1])]), '+'), self.symbol_quantity_min_step, '*'), self.symbol_leverage, '/')
        # self.account_fund_demand = calc(max_margin_cost, abs(max_loss_ref), '+')
        self.account_fund_demand = calc(calc(max_margin_cost, abs(max_loss_ref), '+'), order_margin, '+')
        # 列出回调不同比例时的策略亏损
        list_callback_ratio = [0.05, 0.1, 0.2, 0.3, 0.5]
        list_critical_indices = [0] * len(list_callback_ratio)
        list_prices = [round_step_size(calc(self.entry_grid_price, 1 - each_ratio, '*'), self.symbol_price_min_step) for each_ratio in list_callback_ratio]
        list_callback_losses = [0.] * len(list_callback_ratio)
        for p_index, _ in enumerate(self.all_grid_price):
            for _index, _price in enumerate(list_prices):
                if self.all_grid_price[p_index] <= _price < self.all_grid_price[p_index + 1]:
                    list_critical_indices[_index] = p_index
        # print(list_prices, '\n', list_critical_indices)
        for index in range(len(list_callback_losses)):
            list_callback_losses[index] = self.unmatched_profit_calc(
                initial_index=self.entry_index,
                current_index=list_critical_indices[index],
                all_prices=self.all_grid_price,
                all_quantities=self.all_grid_quantity,
                init_pos_price=self.entry_grid_price,
                init_pos_qty=self.entry_grid_qty,
                current_price=list_prices[index]
            )

        info_texts += '\n网格总数量\t\t{:<8}\n'.format(str(self.grid_total_num))
        info_texts += '套利区间网格数量\t\t{} + {}\n'.format(str(self.filling_grid_step_num), str(self.lower_grid_step_num))
        info_texts += '当前网格间距\t\t{:<8}\t\t（ {} 倍精度 ）\n'.format(np.format_float_positional(present_grid_step, trim='-'), str(present_grid_precision_multi))
        info_texts += '全程补仓次数\t\t{:<8}\t\t次\n'.format(str(self.stairs_total_num))

        info_texts += '\n每格套利利润\t\t{} ~ {}\t{:<8}\n'.format(each_grid_profit_low, each_grid_profit_high, symbol_name[-4:])
        info_texts += '每阶做多收益\t\t{:<8}\t\t{:<8}\n'.format(str(self._each_stair_profit[0]), symbol_name[-4:])
        info_texts += '全程做多收益\t\t{:<8}\t\t{:<8}\n'.format(str(calc(self._each_stair_profit[0], self.stairs_total_num, '*')), symbol_name[-4:])

        info_texts += '\n初始占用保证金\t\t{:<8}\t\t{:<8}\n'.format(str(round(filling_margin_occupation, 2)), symbol_name[-4:])
        info_texts += '初始挂单保证金\t\t{:<8}\t\t{:<8}\n'.format(str(round(order_margin, 2)), symbol_name[-4:])
        info_texts += '最大持仓保证金\t\t{:<8}\t\t{:<8}\n'.format(str(round(max_margin_cost, 2)), symbol_name[-4:])

        info_texts += '\n区间底部资金需求\t\t{:<8}\t\t{:<8}\t（账户建议资金）\n'.format(str(round(self.account_fund_demand, 2)), symbol_name[-4:])

        info_texts += '\n\n区间底部亏损\t\t{:<8}\t\t{:<8}\n'.format(str(round(max_loss_ref, 2)), symbol_name[-4:])

        info_texts += '\n{}\n'.format('-' * 24)

        info_texts += '入场位价格回调\t\t策略亏损'
        for index, each_fund_callback in enumerate(list_callback_losses):
            info_texts += '\n{:>8} %\t\t{:>8}\t{}'.format(str(100 * list_callback_ratio[index]), str(round(each_fund_callback, 2)), symbol_name[-4:])

        info_texts += '\n\n{}\n'.format('-' * 24)

        info_texts += '最高补仓位价格回调\t\t策略亏损'
        for index, each_fund_callback in enumerate(list_callback_losses):
            info_texts += '\n{:>8} %\t\t{:>8}\t{}'.format(str(100 * list_callback_ratio[index]),
                                                          str(round(each_fund_callback * self.fund_decrease_ratio ** self.stairs_total_num, 2)), symbol_name[-4:])

        info_texts += '\n\n注：每次补仓，保证金占用、回调亏损 递减 {}%'.format(round(100 * self.fund_decrease_ratio, 2))

        info_texts += '\n\n*** {} ***'.format('=' * 32)

        # 最后保存参考信息，以供恢复策略时使用
        self._save_ref_info_text = info_texts
        return info_texts

    def derive_functional_variables(self, assign_entry_price: float = 0) -> None:
        """
        计算策略运行需要的相关变量
        策略实现方法：每达到补仓点位，相当于重新开启了一个等比做多网格
        因此首先计算所有补仓价格，然后以该补仓价格为基准计算等比网格价格
        网格间距变化方法：首先保存上方大量范围的网格价格，并另外存储每个台阶下方的网格价格
        当台阶上升时，使用类似非线性网格的逻辑更新所有网格价格，保持index不变，下方多余位置，以0填充
        :param assign_entry_price:
        :return:
        """
        self.symbol_leverage = self._x_leverage
        self.up_limit_price = self._x_grid_up_limit
        self.trigger_start = self._x_trigger_start
        self.trigger_price = self._x_trigger_price

        self.grid_step_ratio = calc(self._x_price_rel_step, 100, '/')
        self.filling_step_ratio = calc(self._x_filling_step, 100, '/')
        self.lower_space_ratio = calc(self._x_lower_step, 100, '/')
        self.filling_fund = self._x_filling_fund

        # 根据当前价格，给出 entry price，最新价格在参考信息和 策略开始运行两处都会使用，如果挂单触发，则为触发价格
        if self.trigger_start:
            self.entry_grid_price = self.trigger_price
        elif assign_entry_price != 0:
            self.entry_grid_price = assign_entry_price
        else:
            self.entry_grid_price = self.current_symbol_price
        # print('entry price: {}'.format(self.entry_grid_price))

        # 首先计算所有补仓价格
        self.all_filling_prices = list(self.isometric_grid_calc(
            base_price=self.entry_grid_price,
            grid_ratio=self.filling_step_ratio,
            boundary_price=self.up_limit_price
        ))[1:]
        # 如果最后一个补仓价格完全等于上边界价格，则剔除该价格
        if self.all_filling_prices[-1] == self.up_limit_price:
            self.all_filling_prices.pop(-1)
        # self.all_filling_quantities = [int(calc(self.filling_fund, calc(each_fill_price, self.symbol_quantity_min_step, '*'), '/'))
        #                                for each_fill_price in self.all_filling_prices]
        # print('prices of filling: {}'.format(self.all_filling_prices))
        self.stairs_total_num = len(self.all_filling_prices)
        # 再计算一阶网格价格
        up_grid_price = self.isometric_grid_calc(self.entry_grid_price, self.grid_step_ratio, self.all_filling_prices[0])
        down_grid_price = self.isometric_grid_calc(self.entry_grid_price, self.grid_step_ratio,
                                                   self.round_step_precision(self.entry_grid_price * (1 - self.lower_space_ratio), self.symbol_price_min_step))[:-1]
        up_grid_price[-1] = self.all_filling_prices[0]
        self.filling_grid_step_num = len(up_grid_price) - 1  # 减去base index
        self.lower_grid_step_num = len(down_grid_price)

        self.all_grid_price = tuple(down_grid_price + up_grid_price)
        # print('初始做多网格:\n{}'.format(self.all_grid_price))

        # 计算网格总数
        last_stair_grid_num = int(np.floor(np.log(self._x_grid_up_limit / self.all_filling_prices[-1]) / np.log(1 + self.grid_step_ratio)))  # 不包括base index，也不包括上界价格
        self.grid_total_num = last_stair_grid_num + self.stairs_total_num * self.filling_grid_step_num + self.lower_grid_step_num + 1
        self.max_index = self.grid_total_num - 1

        # 更新相关index
        self.present_stair_num = 0
        self.present_bottom_index = 0
        self.present_base_index = self.lower_grid_step_num
        self.present_step_up_index = self.present_base_index + self.filling_grid_step_num
        self.indices_of_filling = [self.present_step_up_index, ]
        # 更新其他动态变量
        self.present_bottom_price = self.all_grid_price[self.present_bottom_index]
        self.present_step_up_price = self.all_grid_price[self.present_step_up_index]

        self.entry_index = self.present_base_index
        self.critical_index = self.entry_index

        # # 这里添加一项保险，filling fund使用实时的最小值去更新，如果确认参数后，价格上涨较快，到用户点击开始运行时最小资金需求又提高了，则会触发该代码
        # real_time_min_fund = calc(self.all_filling_prices[-1], calc(self.filling_grid_step_num, self.symbol_quantity_min_step, '*'), '*')
        # # todo: 此处不能_log_info,可以考虑写一个弹窗，全局提醒用
        # self.filling_fund = max(self.filling_fund, real_time_min_fund)

        # 计算所有补仓数量，修改为资金比例递减
        # self.all_filling_quantities = [int(calc(self.filling_fund, calc(each_fill_price, self.symbol_quantity_min_step, '*'), '/'))
        #                                for each_fill_price in self.all_filling_prices]
        self.all_filling_quantities = [int(calc(self.filling_fund * (self.fund_decrease_ratio ** (i + 1)), calc(each_fill_price, self.symbol_quantity_min_step, '*'), '/'))
                                       for i, each_fill_price in enumerate(self.all_filling_prices)]
        # print('quantities of filling: {}'.format(self.all_filling_quantities))

        # 再计算一阶网格数量，根据网格数量，计算一共有多少张，然后平均分配到网格
        up_grid_qty = self.unequal_grid_qty_calc(base_price=self.entry_grid_price, grid_num=self.filling_grid_step_num, fund=self.filling_fund)
        down_grid_qty = [up_grid_qty[0]] * (self.lower_grid_step_num + 1)  # 包含 base index
        self.all_grid_quantity = tuple(down_grid_qty + up_grid_qty)
        self.entry_grid_qty = sum(up_grid_qty)
        # print('len prices = {}, len qty = {}'.format(len(self.all_grid_price), len(self.all_grid_quantity)))

        # 更新初始统计变量
        self._all_grid_buy_num = [0] * len(self.all_grid_price)
        self._all_grid_sell_num = [0] * len(self.all_grid_price)
        self._each_stair_profit = [self.unmatched_profit_calc(
            initial_index=self.entry_index,
            current_index=self.present_step_up_index,
            all_prices=self.all_grid_price,
            all_quantities=self.all_grid_quantity,
            init_pos_price=self.all_grid_price[self.entry_index],
            init_pos_qty=self.entry_grid_qty,
            current_price=self.all_grid_price[self.indices_of_filling[0]]
        )]

        self.all_lower_prices = [tuple(self.isometric_grid_calc(
            self.all_filling_prices[0],
            self.grid_step_ratio,
            self.round_step_precision(self.all_filling_prices[0] * (1 - self.lower_space_ratio), self.symbol_price_min_step))[:-1])]
        self.saved_stair_num = 0
        # print(self.all_lower_prices)
        # 台阶增长，计算至超出当前挂单最大范围
        add_num = int(self.symbol_order_price_div / self.filling_step_ratio) + 1
        # print('初始缓冲 {} 阶'.format(add_num))
        for i in range(add_num):
            self._add_buffer_vars()
