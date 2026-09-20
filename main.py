"""兼容 wrapper：`python main.py` 旧入口。

实现已全部迁入 src/luckywheel/（core/ 零 Qt 算法 + ui/ 界面 +
app.py 入口）；`python -m luckywheel` 等价于本文件。此文件保留是
为了老用户的使用习惯与桌面快捷方式。

以下两个 re-export 服务于既有测试与脚本的 `from main import ...`：
MainWindow 本体、SECTOR_COLORS 调色板。
"""

import sys

from luckywheel.ui.main_window import SAVE_DEBOUNCE_MS, MainWindow  # noqa: F401
from luckywheel.ui.wheel import SECTOR_COLORS, WheelWidget  # noqa: F401

if __name__ == "__main__":
    # PyQt6 默认启用高 DPI 缩放，无需手动设置
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
