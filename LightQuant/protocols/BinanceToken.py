# -*- coding: utf-8 -*-
# @Time : 2022/11/6 10:00
# @Author : 
# @File : BinanceToken.py 
# @Software: PyCharm


class BinanceToken:
    """
    币安 token 类，定义 币安执行者和分析者之间通信使用的token

    """
    # 规范化通讯信息
    ORDER_INFO = {
        'symbol': 'symbol_name',
        'id': 'symbol-side-index',
        'price': 0.00,
        'side': 'BUY',
        'quantity': 0.00,
        'status': 'self_defined_status'
    }

    # todo: 修改名称
    BATCH_ORDER_INFO = {
        'orders': [
            ORDER_INFO
        ],
        'status': 'to_post_batch'
    }
    # todo: 修改batch status

    TICKER_INFO = {
        'symbol': 'symbol_name',
        'price': 0.00,
    }

    PUBLIC_TRADE_INFO = {
        'event_time': 1701243305547,
        'symbol': 'symbol_name',
        'price': 0.00
    }

    BOOK_TICKER_INFO = {
        'ask': 0.0,
        'bid': 0.0
    }

    # 定义与 Analyzer 通信时的订单状态
    # 发送命令
    TO_POST_LIMIT = 'to_post_limit'
    TO_POST_POC = 'to_post_poc'
    TO_POST_MARKET = 'to_post_market'
    TO_CANCEL = 'to_cancel'
    TO_POST_BATCH = 'to_post_batch'
    TO_POST_BATCH_POC = 'to_post_batch_poc'
    CLOSE_POSITION = 'close_position'
    CANCEL_ALL = 'cancel_all'
    AMEND_POC_PRICE = 'amend_poc_price'
    AMEND_POC_QTY = 'amend_poc_qty'

    # 接受命令
    ORDER_FILLED = 'order_filled'
    PARTIALLY_FILLED = 'partially_filled'
    ORDER_UPDATE = 'order_update'               # 订单更新，该token范围比较大

    POST_SUCCESS = 'post_success'               # 单个限价单挂单成功
    POC_SUCCESS = 'poc_success'                 # 单个poc挂单成功
    CANCEL_SUCCESS = 'cancel_success'           # 撤销单个gtc挂单
    CANCEL_POC_SUCCESS = 'cancel_poc_success'   # 撤销单个poc挂单

    UNIDENTIFIED = 'unidentified'

    FAILED = 'failed'
    POST_FAILED = 'post_failed'                 # 单个限价单挂单失败
    POC_FAILED = 'poc_failed'                   # 单个poc挂单失败
    POC_REJECTED = 'poc_rejected'               # 这是一个特殊的返回，表示poc挂单因为价格不对导致无法成为maker
    CANCEL_FAILED = 'cancel_failed'             # 撤销单个挂单失败
    AMEND_POC_FAILED = 'amend_poc_failed'       # 修改单个poc挂单失败

    AMEND_NONEXISTENT_POC = 'amend_nonexistent_poc'         # 修改不存在的poc挂单       # todo: 这个错误专门为修改maker市价单创建

    # 临时测试用
    TEMP_TOKEN = 'temp_token'

    # todo: 或许可以直接改为数字
