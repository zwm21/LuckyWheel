"""应用入口：`python -m luckywheel` 与安装后的 `luckywheel` 命令。

启动序列（app.setStyle 必须在任何控件创建前，Fusion 是明暗调色板
控色一致的前提）与旧 main.py 的 __main__ 段一致：

    python -m luckywheel        # 等价 python main.py
    luckywheel                  # pip install 后的命令

冒烟脚本 scripts/verify_gui.py 以 --entry module 走本模块的 run()，
它接受外部传入的 QApplication，便于复用同一个 app 实例。
"""

import sys

from PyQt6.QtWidgets import QApplication


def create_window():
    """构造主窗口（MainWindow 现居根级 main.py，拆分完成后将迁入 ui/）。"""
    from main import MainWindow

    return MainWindow()


def run(app=None):
    """显示窗口并返回它；app 为 None 时自建。不进入事件循环（由调用方决定）。"""
    if app is None:
        app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    window = create_window()
    window.show()
    return window


def main():
    app = QApplication(sys.argv)
    run(app)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
