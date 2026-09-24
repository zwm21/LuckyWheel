"""GUI：panels.base.sync_list_items 的增量 diff 语义。

clear() + addItems() 会重建全部条目，而刷新编排在批量抽取的每一轮都会跑
一遍：41 项的列表每轮重建 41 个 QListWidgetItem，并丢掉选中项与滚动位置，
视觉上是整表闪烁。这里钉住替代实现的四条性质：

1. 同步后内容与顺序与目标完全一致；
2. 内容相同则什么都不做（返回 False，不产生多余信号）；
3. 公共前后缀的条目对象原样保留——只增删中间差异段；
4. 纯追加时不做任何删除（批量抽取往抽出列表追加一项的场景）。

放在 gui/ 而非 unit/：本文件要构造 QListWidget，需要 QApplication。
"""

import pytest

from luckywheel.ui.panels.base import sync_list_items


@pytest.fixture
def list_widget(qtbot):
    from PyQt6.QtWidgets import QListWidget

    widget = QListWidget()
    qtbot.addWidget(widget)
    return widget


def texts(widget):
    return [widget.item(i).text() for i in range(widget.count())]


class TestSyncResult:
    @pytest.mark.parametrize(
        "before,target",
        [
            ([], ["a", "b", "c"]),
            (["a", "b", "c"], []),
            (["a", "b", "c"], ["a", "b", "c"]),
            (["a", "b", "c"], ["a", "b"]),  # 尾部少一项
            (["a", "b"], ["a", "b", "c"]),  # 尾部多一项
            (["a", "b", "c"], ["a", "x", "c"]),  # 中间替换
            (["a", "b", "c"], ["x", "y"]),  # 整体不同
            (["a", "b", "c", "d"], ["a", "d"]),  # 删中间段
            (["a", "d"], ["a", "b", "c", "d"]),  # 插中间段
            (["a", "b", "c"], ["c", "b", "a"]),  # 逆序：无公共前后缀
            (["1"] * 15 + ["2"], ["1"] * 15),  # 真实数据形状：重复项
        ],
    )
    def test_content_matches_target(self, list_widget, before, target):
        list_widget.addItems(before)
        sync_list_items(list_widget, target)
        assert texts(list_widget) == target

    def test_identical_content_is_noop(self, list_widget):
        list_widget.addItems(["a", "b"])
        assert sync_list_items(list_widget, ["a", "b"]) is False
        assert texts(list_widget) == ["a", "b"]

    def test_accepts_tuple(self, list_widget):
        assert sync_list_items(list_widget, ("x", "y")) is True
        assert texts(list_widget) == ["x", "y"]


class TestDiffIsIncremental:
    def test_common_prefix_and_suffix_preserved(self, list_widget, monkeypatch):
        """公共前后缀不得被删掉重建——这是"增量"二字的全部意义。"""
        list_widget.addItems(["a", "b", "c", "d", "e"])
        survivors = [list_widget.item(i) for i in range(list_widget.count())]

        removed, inserted = [], []
        original_take = list_widget.takeItem
        original_insert = list_widget.insertItem

        def spy_take(row):
            removed.append(row)
            return original_take(row)

        def spy_insert(*args):
            inserted.append(args[-1])
            return original_insert(*args)

        monkeypatch.setattr(list_widget, "takeItem", spy_take)
        monkeypatch.setattr(list_widget, "insertItem", spy_insert)

        sync_list_items(list_widget, ["a", "b", "x", "d", "e"])

        assert removed == [2], "只应删掉变化的那一行"
        assert inserted == ["x"], "只应插入变化的那一行"
        assert texts(list_widget) == ["a", "b", "x", "d", "e"]
        # 公共前缀的条目对象必须原样留着（未被重建）
        assert list_widget.item(0) is survivors[0]
        assert list_widget.item(1) is survivors[1]

    def test_appending_only_inserts(self, list_widget, monkeypatch):
        """往抽出列表追加一项时不得触发任何删除。"""
        list_widget.addItems(["a", "b"])
        removed = []
        monkeypatch.setattr(list_widget, "takeItem", lambda row: removed.append(row))

        sync_list_items(list_widget, ["a", "b", "c"])

        assert removed == []
        assert texts(list_widget) == ["a", "b", "c"]

    def test_deleting_from_middle_removes_back_to_front(self, list_widget, monkeypatch):
        """删除必须从后往前，否则行号在删除过程中漂移。"""
        list_widget.addItems(["a", "b", "c", "d", "e", "f"])
        removed = []
        monkeypatch.setattr(list_widget, "takeItem", lambda row: removed.append(row))

        sync_list_items(list_widget, ["a", "f"])

        assert removed == [4, 3, 2, 1], "应按行号递减顺序删除"
