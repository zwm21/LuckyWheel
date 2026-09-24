"""兼容 wrapper：`python main.py` 旧入口。

实现已全部迁入 src/luckywheel/（core/ 零 Qt 算法 + ui/ 界面 +
app.py 入口）；`python -m luckywheel` 等价于本文件。此文件保留是
为了老用户的使用习惯与桌面快捷方式。

只 re-export 一个 MainWindow，供 scripts/verify_gui.py --entry main
走旧入口冒烟。测试与其他脚本一律直接从 luckywheel.* 导入：re-export
清单越长，这个 wrapper 就越像事实上的 API 门面，改动 ui/ 的模块划分
时反而要先绕过它。
"""

import sys

from luckywheel.app import main
from luckywheel.ui.main_window import MainWindow  # noqa: F401

if __name__ == "__main__":
    sys.exit(main())
