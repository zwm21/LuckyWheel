"""面板基类：持有窗口引用，收敛跨切面调用的写法。"""

from PyQt6.QtWidgets import QWidget


class Panel(QWidget):
    """所有面板的基类。

    以窗口为 parent：控件随后会被 addWidget  reparent 进窗口的布局，
    因此 `window.findChildren(QWidget)` 仍能覆盖到它们（applyUIFont
    的全局字体同步依赖这一点）。
    """

    def __init__(self, window, parent=None):
        super().__init__(parent if parent is not None else window)
        self.window = window

    # ---- 跨切面动作：统一经 window，避免面板互相持有引用 ----
    def save(self):
        self.window.saveData()

    def refresh_from_group(self):
        """数据已变：刷新列表、转盘、抽出列表与按钮状态。"""
        self.window.updateWheelFromCurrentGroup()

    def refresh_extract_state(self):
        self.window.updateExtractButtonState()

    @property
    def groups(self):
        return self.window.groups

    @property
    def group(self):
        """当前分组 dict（无分组时为 None）。"""
        index = self.window.current_group_index
        if 0 <= index < len(self.window.groups):
            return self.window.groups[index]
        return None
