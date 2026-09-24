"""GUI 端到端：按索引抽出——重复文本场景下必须移除中奖索引对应的那一项。

旧实现从 result_label 反解文本再 `items.remove(text)`，遇到重复项时
永远删掉第一个匹配；真实数据 41 项只有 17 个唯一值，误删概率很高。
现在 spinFinished 携带索引，抽出按钮与批量抽取都按索引 pop。
"""

import pytest

from luckywheel.core.spin import sector_at


def rotation_pointing_at(index, count):
    """求一个 rotation，使 sector_at(rotation, count) 恰为 index（扇区中心）。"""
    span = 360.0 / count
    target = index * span + span / 2.0
    return (270.0 - target) % 360.0


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    """装配好 ["A", "A", "B"] 的 MainWindow，数据文件隔离到临时目录。"""
    from luckywheel.ui.main_window import MainWindow

    monkeypatch.setattr(
        "luckywheel.core.paths.resolve_data_path", lambda: (tmp_path / "wheel_data.json", None)
    )
    win = MainWindow()
    qtbot.addWidget(win)
    win.groups = [{"name": "g", "items": ["A", "A", "B"], "drawn_items": []}]
    win.current_group_index = 0
    win.updateWheelFromCurrentGroup()
    return win


def finish_on(window, index):
    """把转盘停到指向 index 的角度并触发一次完整的结果分发。"""
    window.wheel.rotation = rotation_pointing_at(index, len(window.wheel.items))
    captured = []
    window.wheel.spinFinished.connect(lambda i, t: captured.append((i, t)))
    window.wheel.determineResult()
    window.wheel.spinFinished.disconnect()
    return captured[0]


class TestExtractByIndex:
    def test_pointer_angle_maps_to_expected_index(self, qtbot):
        """sector_at 反算与构造的角度自洽（用例前提）。"""
        rotation = rotation_pointing_at(1, 3)
        assert sector_at(rotation, 3) == 1

    @pytest.mark.parametrize("target", [0, 1, 2])
    def test_extract_removes_exact_index(self, window, target):
        index, _text = finish_on(window, target)
        assert index == target, "前置条件：winner 索引应等于构造的目标"
        window.onSpinFinished(index, _text)
        window.extractDrawnItem()

        group = window.groups[0]
        expected = [x for i, x in enumerate(["A", "A", "B"]) if i != target]
        assert group["items"] == expected
        assert len(group["drawn_items"]) == 1
        assert window.last_result_index is None, "抽出后索引应失效"
        assert not window.btn_extract.isEnabled(), "无可抽结果时按钮应禁用"

    def test_repeat_extract_is_noop(self, window):
        index, text = finish_on(window, 0)
        window.onSpinFinished(index, text)
        window.extractDrawnItem()
        after_first = list(window.groups[0]["items"])
        window.extractDrawnItem()  # index 已清空，不应再删
        assert window.groups[0]["items"] == after_first
        assert len(window.groups[0]["drawn_items"]) == 1

    def test_stale_index_after_data_change_is_guarded(self, window):
        """分组切换/编辑使旧索引越界时，抽出必须是安全的空操作。"""
        window.onSpinFinished(2, "B")
        window.groups[0]["items"] = ["A"]  # 只剩一项，索引 2 越界
        window.updateWheelFromCurrentGroup()
        window.last_result_index = 2  # 模拟未清理的僵尸索引
        window.extractDrawnItem()
        assert window.groups[0]["items"] == ["A"], "越界索引不得误删"


class TestAutoExtractByIndex:
    def test_batch_removes_exact_index(self, window):
        """批量抽取同样按索引 pop：两轮后剩下的正是未被抽中的那一项。"""
        removed = []
        for target in (1, 1):  # 第一轮中奖索引 1（删第二个 A），第二轮删索引 1（删 B）
            index, text = finish_on(window, target)
            assert index == target
            removed.append(text)
            window.batch_remaining = 1
            window.onSpinFinished(index, text)

        group = window.groups[0]
        assert removed == ["A", "B"]
        assert group["items"] == ["A"]
        assert group["drawn_items"] == ["A", "B"]
        assert window.batch_remaining == 0

    def test_batch_leaves_no_stale_index(self, window):
        index, text = finish_on(window, 0)
        window.batch_remaining = 1
        window.onSpinFinished(index, text)
        assert window.last_result_index is None, "批量路径不保留索引供抽取按钮使用"
