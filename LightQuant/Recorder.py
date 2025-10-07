# -*- coding: utf-8 -*-
# @Time : 2023/1/26 21:24 
# @Author : 
# @File : Recorder.py 
# @Software: PyCharm

import os
import sys
from datetime import datetime


class LogRecorder:
    # todo: 新增日期文件夹功能
    log_file_path = 'trading_logs'

    def __init__(self):
        self._writing_file = None

    def open_file(self, file_name: str) -> None:
        """
        创建文件，自动选择目录和名称
        :param file_name: 文件名，建议用 symbol name
        :return:
        """
        # 确保文件夹存在
        if not os.path.exists(self.log_file_path):
            os.makedirs(self.log_file_path)

        if '.txt' in file_name:
            file_name = file_name.split('.')[0]

        base_path = os.path.join(self.log_file_path, datetime.now().strftime('%Y-%m-%d_%H-%M_') + file_name)
        full_path = base_path + '.txt'
        # 一分钟内开多个log, 自动重复处理
        repetition_num = 1
        while os.path.exists(full_path):
            full_path = base_path + '_{}'.format(repetition_num) + '.txt'
            repetition_num += 1

        self._writing_file = open(full_path, 'w', encoding='utf-8')
        self.log_print('开始记录', datetime.now().strftime('%Y-%m-%d  %H:%M:%S  %f'))

    def close_file(self) -> None:
        if self._writing_file is not None:
            self._writing_file.close()
        else:
            print('未创建记录文件txt, 无需close')

    def log_print(self, print_content, *args) -> None:
        """
        将交易日志写入文件，旧版print功能已弃用
        :param print_content:
        :param args: str补充文本
        :return:
        """
        if self._writing_file is None:
            print('未创建文件！！！')       # todo: raise Exception

        self._writing_file.write(str(print_content))
        self._writing_file.write('\n')
        for each_content in args:
            self._writing_file.write(str(each_content))
            self._writing_file.write('\n')

    def log_error_exit(self, exception: BaseException) -> None:
        """
        输出程序的报错，并结束程序
        :param exception: 错误类型
        :return:
        """
        self.log_print('\n', '*' * 59)
        self.log_print('>>>>> 程序出错\n错误类型: {}\n错误内容: {}'.format(str(type(exception)), exception))
        self.log_print('*' * 59, '\n')

        self.close_file()
        # sys.exit()

    def exit_program(self) -> None:
        """
        实现sys.exit() 功能
        需要先关闭文件
        :return:
        """
        self.close_file()
        sys.exit()


if __name__ == '__main__':
    test_loger = LogRecorder()
    test_loger.open_file('TEST_symbol')
    test_loger.log_print('test content')
    test_loger.close_file()
