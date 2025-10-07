# -*- coding: utf-8 -*-
# @Time : 2024/3/13 20:10
# @Author : 
# @File : sysout.py 
# @Software: PyCharm
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QMessageBox, QTextBrowser
from PyQt5 import QtGui


# 步骤1：创建一个自定义输出类
class CustomOutputStream(object):
    def __init__(self, text_widget, sys_file_name='system_out.txt'):
        self.text_widget = text_widget
        self.file_name = sys_file_name
        # 检查文件是否存在，不存在则创建
        self.file = open(sys_file_name, 'a', encoding='utf-8')

    def write(self, message):
        # 将文本追加到文本组件中
        self.text_widget.append(message)
        self.text_widget.moveCursor(QtGui.QTextCursor.End)
        # 将消息写入文件
        self.file.write(message)
        self.file.flush()

    def flush(self):
        # 这个方法可能是必需的，但可以保留空实现
        pass

    def __del__(self):
        # 关闭文件
        self.file.close()


# 步骤2：修改GUI窗口，添加一个用于显示输出的文本组件
class PrintWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('trading system info print')
        self.resize(1000, 618)
        self.text_browser = QTextBrowser()
        self.text_browser.setReadOnly(True)
        self.text_browser.document().setMaximumBlockCount(2000)
        layout = QVBoxLayout()
        layout.addWidget(self.text_browser)

        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)

        # 将自定义输出流与文本编辑组件关联
        sys.stdout = CustomOutputStream(self.text_browser)

    def closeEvent(self, event):
        # 弹出确认关闭的对话框
        reply = QMessageBox.question(self, '确认', '确认关闭输出窗口？\n这将会导致整个交易系统关闭！请谨慎确认！！！', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            event.accept()  # 接受关闭事件，关闭窗口
            sys.exit(-1)
        else:
            event.ignore()  # 忽略关闭事件，窗口不会关闭


if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_window = PrintWindow()
    main_window.show()

    # 现在，使用 print 会将文本输出到GUI窗口而不是控制台
    print("Hello, this is a test.")
    print("Your custom GUI console is working!")

    sys.exit(app.exec_())
