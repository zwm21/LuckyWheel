"""GUI 端到端：单次抽取的「停止」按钮。

要点有三条，都不是从代码形状能推出来的约定：

1. 位置——按钮夹在「抽出」与「开始旋转」之间，用行布局的下标钉住；
2. 停止后转盘停在原地。wheel.stopSpin() 不碰 self.rotation，所以「不归位」
   是复用既有方法的结果而非新写的逻辑，这里把它钉成断言防止日后有人
   在 stopSpin 里补一句归零；
3. 停止不产生中奖结果，所以 last_result_index 必须显式清空——否则上一轮
   的下标会残留，「抽出」按钮会指向与当前指针无关的项目。

与 test_wheel_spin.py::TestAnimationControl 的分工：那边钉转盘控件层
stopSpin 的信号契约，这边钉面板层的按钮状态机与窗口级转发。
"""

import pytest


@pytest.fixture
def window(build_main_window):
    return build_main_window(
        groups=[{"name": "g", "items": ["A", "B", "C"], "drawn_items": []}], refresh=True
    )


def row_containing(widget):
    """返回卡片内包含 widget 的那一行布局。"""
    frame_layout = widget.parentWidget().layout()
    for i in range(frame_layout.count()):
        row = frame_layout.itemAt(i).layout()
        if row is None:
            continue
        if any(row.itemAt(j).widget() is widget for j in range(row.count())):
            return row
    raise AssertionError(f"未找到包含 {widget} 的行布局")


class TestButtonPlacement:
    def test_sits_between_extract_and_spin(self, window):
        row = row_containing(window.btn_extract)
        order = [row.itemAt(i).widget() for i in range(row.count())]
        assert order == [window.btn_extract, window.btn_stop_single, window.btn_spin]

    def test_disabled_while_idle(self, window):
        assert not window.btn_stop_single.isEnabled()

    def test_matches_batch_stop_label(self, window):
        assert window.btn_stop_single.text() == window.btn_stop_batch.text() == "停止"


class TestSingleStop:
    def test_enabled_only_during_single_spin(self, window, qtbot):
        window.wheel.startSpin()
        assert window.btn_stop_single.isEnabled(), "单次旋转中停止按钮必须可用"
        assert not window.btn_spin.isEnabled()
        window.stopSingleSpin()
        assert not window.btn_stop_single.isEnabled()

    def test_stop_keeps_rotation_exactly_where_it_was(self, window, qtbot):
        """停止前后 rotation 逐位相同：转盘停在当前角度，不回弹、不归零。"""
        window.wheel.rotation = 0.0
        window.wheel.startSpin()
        qtbot.wait(120)  # 让动画真的推进一段
        frozen = window.wheel.rotation
        window.btn_stop_single.click()
        assert window.wheel.rotation == frozen
        qtbot.wait(150)  # 动画若未真停，会继续改角度
        assert window.wheel.rotation == frozen
        assert not window.wheel.spinning

    def test_stop_does_not_reset_to_origin(self, window):
        """用哨兵角度钉「不归位」：停止不得把 rotation 写回 0 或起始角。"""
        window.wheel.rotation = 0.0
        window.wheel.startSpin()
        window.wheel.rotation = 123.456
        window.stopSingleSpin()
        assert window.wheel.rotation == 123.456

    def test_stop_yields_no_winner(self, window, qtbot):
        captured = []
        window.wheel.spinFinished.connect(lambda i, t: captured.append(i))
        window.wheel.startSpin()
        qtbot.wait(80)
        window.stopSingleSpin()
        qtbot.wait(200)
        assert captured == [], "手动停止不应产生中奖结果"
        assert window.last_result_index is None
        assert not window.btn_extract.isEnabled(), "无中奖结果时抽出必须禁用"

    def test_stop_clears_stale_winner_index(self, window):
        """上一轮中奖后再旋转并停止：旧下标不得残留给抽出按钮。"""
        window.onSpinFinished(1, "B")
        assert window.btn_extract.isEnabled()

        window.wheel.startSpin()
        window.stopSingleSpin()
        assert window.last_result_index is None
        assert not window.btn_extract.isEnabled()

    def test_stop_restores_editing(self, window):
        window.wheel.startSpin()
        assert not window.left_panel.isEnabled()
        window.stopSingleSpin()
        assert window.left_panel.isEnabled()
        assert window.btn_spin.isEnabled()
        assert window.btn_batch_spin.isEnabled()

    def test_stop_does_not_touch_data(self, window):
        """停止只是中断动画：项目与抽出列表都不动（区别于批量的自动抽出）。"""
        window.wheel.startSpin()
        window.stopSingleSpin()
        group = window.groups[0]
        assert group["items"] == ["A", "B", "C"]
        assert group["drawn_items"] == []

    def test_can_spin_again_and_get_result(self, window, qtbot):
        """停止后重新旋转必须能正常跑完并出结果（停止不留残状态）。"""
        window.wheel.startSpin()
        window.stopSingleSpin()

        window.wheel.speed_scale = 60.0
        captured = []
        window.wheel.spinFinished.connect(lambda i, t: captured.append(i))
        window.wheel.startSpin()
        qtbot.waitUntil(lambda: not window.wheel.spinning, timeout=8000)
        assert len(captured) == 1
        assert window.last_result_index == captured[0]
        assert window.btn_extract.isEnabled()

    def test_idle_stop_is_harmless(self, window):
        """未旋转时调用（按钮虽禁用，窗口级入口仍可被脚本直接调）不得炸。"""
        window.stopSingleSpin()
        assert not window.wheel.spinning
        assert window.btn_spin.isEnabled()


class TestDoesNotDisturbBatch:
    """两个停止按钮各管一摊：批量期间单次停止按钮保持禁用且不接管。"""

    def test_batch_does_not_enable_single_stop(self, window):
        window.batch_spinbox.setValue(2)
        window.startBatchSpin()
        assert window.batch_remaining == 2
        assert window.btn_stop_batch.isEnabled()
        assert not window.btn_stop_single.isEnabled(), "批量期间单次停止按钮必须禁用"
        window.stopBatchSpin()

    def test_single_stop_is_noop_during_batch(self, window):
        """即使被直接调用，批量进行中的单次停止也必须原地返回。"""
        window.batch_spinbox.setValue(2)
        window.startBatchSpin()
        window.stopSingleSpin()
        assert window.wheel.spinning, "批量旋转不得被单次停止打断"
        assert window.batch_remaining == 2
        window.stopBatchSpin()

    def test_batch_stop_leaves_single_stop_disabled(self, window):
        window.batch_spinbox.setValue(2)
        window.startBatchSpin()
        window.stopBatchSpin()
        assert not window.btn_stop_single.isEnabled()
        assert not window.btn_stop_batch.isEnabled()
        assert window.btn_spin.isEnabled()
