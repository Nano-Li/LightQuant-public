# -*- coding: utf-8 -*-
# @Time : 2023/1/30 9:21 
# @Author : 
# @File : round_step_size.py 
# @Software: PyCharm
from typing import Union
from decimal import Decimal


def round_step_size(quantity: Union[float, Decimal], step_size: Union[float, Decimal], upward: bool = False) -> float:
    """Rounds a given quantity to a specific step size
    按照给定的精度规整数字，多余的部分去掉
    如果 数字小于精度，返回精度
    :param quantity: required
    :param step_size: required
    :param upward: False: 多余部分去除, True: 多余部分向上取值
    :return: decimal
    """
    if quantity >= 0:
        if quantity < step_size:
            return step_size
        else:
            quantity = Decimal(str(quantity))
            step_size = Decimal(str(step_size))
            if upward:
                if float(quantity % step_size) == 0:
                    return float(quantity)
                else:
                    return float(quantity - quantity % step_size + step_size)
            else:
                return float(quantity - quantity % step_size)

    else:
        if abs(quantity) < step_size:
            return -step_size
        else:
            quantity = Decimal(str(quantity))
            step_size = Decimal(str(step_size))
            if upward:
                if float(quantity % step_size) == 0:
                    return float(quantity)
                else:
                    return float(quantity - quantity % step_size - step_size)
            else:
                return float(quantity - quantity % step_size)


if __name__ == '__main__':
    print(round_step_size(-56.5, 0.1, upward=True))
    print(round_step_size(0.0101, 0.01))
    print(round_step_size(26900, 1000, upward=True))
