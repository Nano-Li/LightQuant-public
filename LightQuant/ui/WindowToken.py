# -*- coding: utf-8 -*-
# @Time : 2023/1/27 21:08 
# @Author : 
# @File : WindowToken.py 
# @Software: PyCharm


class WindowToken:
    """
    定义一些窗口通讯常量
    """
    # api input 通信常量
    API_INPUT_CLOSE = 90
    API_INPUT_CONFIRM = 91

    # param_input_window 与 column 通信常量
    PARAM_VALIDATION = 80
    PARAM_REF_WINDOW = 81
    PARAM_CONFIRM = 82
    PARAM_WINDOW_CLOSE = 84

    # column 与 TradeUI 通信常量，由于通讯需要，使用字符串形式
    COLUMN_SELECTED = '01'
    COLUMN_UNSELECTED = '00'
    COLUMN_ADD_REQUEST = '13'
    COLUMN_TRANSFER_REQUEST = '14'  # not use
    COLUMN_BLOCK_REQUEST = '20'
    COLUMN_ENABLE_REQUEST = '21'
    COLUMN_DELETE_REQUEST = '41'

    # encoding_identification: str = '.'

    @staticmethod
    def encode_stg_num(stg_num: str, transfer_signal: str) -> str:
        """
        将策略识别号 stg num 编译进传输信号当中
        此处相当于定义了信号协议
        只有 TradeUI 与 Col 实例间通讯需要使用该方法
        :param stg_num:
        :param transfer_signal:
        :return:
        """
        encoded_signal = stg_num + '.' + transfer_signal
        return encoded_signal

    @staticmethod
    def decode_stg_num(encoded_signal: str) -> tuple[str, str]:
        """
        将 stg num 解密
        :param encoded_signal:
        :return: stg_num, signal_info
        """
        if '.' in encoded_signal:
            decoded = encoded_signal.split('.')
            return decoded[0], decoded[1]
        else:
            # 没有编译，直接返回
            return 'None', encoded_signal

    def __init__(self):
        pass


if __name__ == '__main__':
    print(WindowToken.PARAM_REF_WINDOW)
