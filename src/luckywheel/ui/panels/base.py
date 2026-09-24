"""面板基类：持有窗口引用，收敛跨切面调用的写法。"""

from PyQt6.QtWidgets import QWidget


def sync_list_items(widget, items):
    """把 QListWidget 的内容同步为 items，只改动变化的那一段。

    返回是否发生了实际改动。

    为什么不用 clear() + addItems()：刷新编排（updateWheelFromCurrentGroup）
    在批量抽取的每一轮都会跑一遍，41 项的列表每轮重建 41 个
    QListWidgetItem，并丢掉选中项与滚动位置，视觉上是整表闪烁。改为先找
    公共前后缀、只替换中间差异段，抽掉一项时只删一行。

    删除必须从后往前：takeItem 会立即重排行号，正序删会让后续行号错位。
    insertItem/takeItem 只发 rowsInserted/rowsRemoved，不发 layoutChanged，
    因此不会误触发拖拽排序的 onItemsReordered。
    """
    current = [widget.item(i).text() for i in range(widget.count())]
    target = list(items)
    if current == target:
        return False

    n_cur, n_new = len(current), len(target)
    limit = min(n_cur, n_new)
    head = 0
    while head < limit and current[head] == target[head]:
        head += 1
    tail = 0
    while tail < limit - head and current[n_cur - 1 - tail] == target[n_new - 1 - tail]:
        tail += 1

    for row in range(n_cur - tail - 1, head - 1, -1):
        widget.takeItem(row)
    for offset, text in enumerate(target[head : n_new - tail]):
        widget.insertItem(head + offset, text)
    return True


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
