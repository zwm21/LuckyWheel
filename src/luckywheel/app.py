"""应用入口：`python -m luckywheel` 与安装后的 `luckywheel` 命令。

启动序列（app.setStyle 必须在任何控件创建前，Fusion 是明暗调色板
控色一致的前提；PyQt6 默认启用高 DPI 缩放，无需手动设置）只此一份，
根级 main.py 的 __main__ 段转调本模块的 main()，两份入口不再各写一遍：

    python -m luckywheel        # 等价 python main.py
    luckywheel                  # pip install 后的命令

冒烟脚本 scripts/verify_gui.py 以 --entry module 走本模块的 run()，
它接受外部传入的 QApplication，便于复用同一个 app 实例。
"""

import sys

from PyQt6.QtWidgets import QApplication

from luckywheel.ui.main_window import MainWindow


def create_window():
    """构造主窗口。

    这里必须走包内路径：早先本函数依赖根级 main.py 的 re-export，只有
    cwd 恰好是仓库根时才 import 得到；`python -m luckywheel` 换个目录
    或 pip 安装后运行直接 ModuleNotFoundError。
    """
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
