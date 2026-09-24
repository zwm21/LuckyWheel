"""GUI 端到端：拖拽排序后上一轮的中奖结果必须失效。

last_result_index 是扇区下标。拖拽排序改变的正是下标与项目的对应关系，
而 onItemsReordered 不走 updateWheelFromCurrentGroup（那条路径本来就清
标签与下标），于是排序后：结果标签仍显示旧中奖项，「抽出」按旧下标 pop
的是另一个项目——宣布 A05 中奖、把第 0 行拖到第 5 行，抽出拿走的是 A00。
"""

import pytest


@pytest.fixture
def window(build_main_window):
    return build_main_window(
        groups=[{"name": "g", "items": [f"A{i:02d}" for i in range(6)], "drawn_items": []}],
        refresh=True,
    )


def move_row(window, src, dst):
    """把第 src 行搬到第 dst 行，并触发面板的排序同步。"""
    item = window.list_widget.takeItem(src)
    window.list_widget.insertItem(dst, item)
    window.items_panel.onItemsReordered()


class TestReorderInvalidatesResult:
    def test_reorder_clears_winner_index_and_label(self, window):
        window.onSpinFinished(5, "A05")
        assert window.last_result_index == 5
        assert "A05" in window.result_label.text()

        move_row(window, 0, 5)

        assert window.last_result_index is None, "顺序一变，旧扇区下标即失效"
        assert window.result_label.text() == ""
        assert not window.btn_extract.isEnabled(), "无有效结果时抽出必须禁用"

    def test_reorder_prevents_extracting_the_wrong_item(self, window):
        """回归的实质：修复前这里抽走的是 A00。"""
        window.onSpinFinished(5, "A05")
        move_row(window, 0, 5)
        window.extractDrawnItem()

        group = window.groups[0]
        assert group["drawn_items"] == [], "旧下标已清，抽出应是空操作"
        assert len(group["items"]) == 6

    def test_noop_reorder_leaves_result_alone(self, window):
        """顺序未真的改变时不得误清结果（面板按值比较后短路）。"""
        window.onSpinFinished(5, "A05")
        window.items_panel.onItemsReordered()
        assert window.last_result_index == 5
        assert "A05" in window.result_label.text()

    def test_wheel_follows_the_new_order(self, window):
        move_row(window, 0, 5)
        expected = ["A01", "A02", "A03", "A04", "A05", "A00"]
        assert window.groups[0]["items"] == expected
        assert window.wheel.items == expected
