# -*- coding: utf-8 -*-
# @Time : 2023/11/17 16:51
# @Author : 
# @File : Preserver.py 
# @Software: PyCharm

import os
import json
from datetime import datetime


class Preserver:
    """
    功能效仿recorder，
    保存正在运行的策略的详细参数与统计信息
    当策略意外停止后，可以根据该信息继续运行策略

    需要记录的运行策略信息：
    策略统计信息，网格参数信息

    注意：这是一个保险策略，一般不会使用
    """

    _preserve_data_path = 'trading_statistics'
    _settled_stg_path = 'settled_strategies'

    def __init__(self):
        self._json_file = None
        # 使用user_id来作为策略复原分页标准  # todo: 是否有其他更优美的方法
        self._user_id: int = 0

    def acquire_user_id(self, user_id: int) -> None:
        self._user_id = user_id

    def open_file(self, file_name) -> None:
        # 确保文件夹存在
        if not os.path.exists(self._preserve_data_path):
            os.makedirs(self._preserve_data_path)

        # 构建基础的文件路径
        base_path = os.path.join(self._preserve_data_path, datetime.now().strftime('%Y-%m-%d_%H-%M-') + file_name)
        full_path = base_path + '.json'

        # 检查文件是否存在，如果存在，则添加一个递增的数字后缀
        repetition_num = 1
        while os.path.exists(full_path):
            full_path = base_path + '_{}'.format(repetition_num) + '.json'
            repetition_num += 1

        # 打开文件并保存到成员变量
        self._json_file = open(full_path, 'w', encoding='utf-8')

    def use_existing_file(self, file_name: str) -> None:
        # 使用现存的文件继续保存策略信息

        full_path = os.path.join(self._preserve_data_path, file_name)
        if os.path.exists(full_path):
            # 防止打开后清除问件内容
            self._json_file = open(full_path, 'w', encoding='utf-8')
        else:
            raise FileNotFoundError('策略信息文件 {} 不存在'.format(file_name))

    def _close_file(self) -> None:
        if self._json_file:
            self._json_file.close()
            self._json_file = None  # 重置为 None

    def preserve_strategy_info(self, stg_info: dict) -> None:
        """
        将交易策略的详细信息保存，保存时，会额外添加user id信息
        :param stg_info: 字典格式的策略信息
        :return:
        """
        write_stg_info = stg_info.copy()
        if self._json_file:
            # 添加user id作为标识符
            write_stg_info['user_id'] = self._user_id
            # 将文件指针移动到文件开头
            self._json_file.seek(0)
            # 将字典转换为JSON字符串
            json_data = json.dumps(write_stg_info, ensure_ascii=False, indent=4)
            # 将JSON数据写入文件，并覆盖旧数据
            self._json_file.write(json_data)
            # 清除文件内容超出当前写入内容的部分
            self._json_file.truncate()
        else:
            print('JSON文件未打开或已关闭')

    def stop_preserving(self) -> None:
        """
        策略结束后调用该函数，保存并关闭文件，将json信息移至保存文件夹
        :return:
        """
        # 在关闭文件之前获取文件名
        if self._json_file:
            file_name = self._json_file.name
            self._close_file()
        else:
            print('\n未创建json文件')
            return

        settled_path = os.path.join(self._preserve_data_path, self._settled_stg_path)
        # 检查并创建 'settled_strategies' 文件夹
        if not os.path.exists(settled_path):
            os.makedirs(settled_path)

        # 构建新的文件路径
        new_path = os.path.join(settled_path, os.path.basename(file_name))
        os.rename(file_name, new_path)

    def failed_to_preserve(self) -> None:
        """
        保险措施，如果策略重启失败，关闭文件，不移动json文件
        :return:
        """
        if self._json_file:
            self._json_file.flush()
            self._close_file()


if __name__ == '__main__':
    test_preserver = Preserver()
    test_preserver.open_file('test_symbol')
    test_preserver.preserve_strategy_info({'symbol': 'test'})

    test_preserver_dup = Preserver()
    test_preserver_dup.open_file('test_symbol')
    test_preserver_dup.preserve_strategy_info({'symbol': 'test_dup'})

    # time.sleep(10)
    # # test_preserver.close_file()
    test_preserver.stop_preserving()
