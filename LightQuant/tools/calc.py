# -*- coding: utf-8 -*-
# @Time : 2023/1/30 9:20 
# @Author : 
# @File : calc.py 
# @Software: PyCharm
import sys
from typing import Union
from decimal import Decimal


def calc(number_1: Union[int, float], number_2: Union[int, float], operation: str) -> Union[float, int]:
    number_1 = float(number_1)
    number_2 = float(number_2)

    if operation == '+':
        return float(Decimal(str(number_1)) + Decimal(str(number_2)))
    elif operation == '-':
        return float(Decimal(str(number_1)) - Decimal(str(number_2)))
    elif operation == '*':
        return float(Decimal(str(number_1)) * Decimal(str(number_2)))
    elif operation == '/':
        return float(Decimal(str(number_1)) / Decimal(str(number_2)))
    elif operation == '%':
        return float(Decimal(str(number_1)) % Decimal(str(number_2)))
    else:
        print('input error')
        sys.exit()


def calc_sum(number_list: list[Union[int, float]]) -> Union[float, int]:
    sum_num = 0
    for each_num in number_list:
        sum_num = calc(sum_num, each_num, '+')

    return sum_num


if __name__ == '__main__':
    # test code
    print(calc(5, 5, '%'))
    print(calc_sum([0.0001] * 50))
