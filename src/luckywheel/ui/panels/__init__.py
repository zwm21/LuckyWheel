"""UI 面板：把 MainWindow 的关注点拆成可独立阅读的类。

拆分约定（方案 b）：**行为入面板，布局与组装留在 MainWindow**。
三个列表窗格（项目列表 / 项目编辑按钮组 / 抽出列表）同处一个
QSplitter，却分属「项目编辑」与「抽出项目」两个关注点；若要求每个
面板自封装布局，splitter 必被拆散。因此面板只负责「创建自己的控件 +
连接自己的信号 + 实现自己的数据操作」，控件以公有属性暴露，由
MainWindow.initUI 拼装。

跨切面动作（saveData、updateWheelFromCurrentGroup 等）一律经
self.window 调用，面板之间不互相持有引用。
"""

from luckywheel.ui.panels.base import Panel
from luckywheel.ui.panels.drawn_panel import DrawnPanel
from luckywheel.ui.panels.group_panel import GroupPanel
from luckywheel.ui.panels.items_panel import ItemsPanel
from luckywheel.ui.panels.settings_panel import SettingsPanel
from luckywheel.ui.panels.spin_panel import SpinPanel

__all__ = [
    "DrawnPanel",
    "GroupPanel",
    "ItemsPanel",
    "Panel",
    "SettingsPanel",
    "SpinPanel",
]
