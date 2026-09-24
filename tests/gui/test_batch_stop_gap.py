"""GUI 端到端：批量抽取的轮间停顿里按「停止」不得再转一轮。

批量的每一轮之间有 400ms 停顿，早先用
`QTimer.singleShot(400, wheel.startSpin)` 排下一轮。QTimer.singleShot 起的
是不可取消的一次性定时器，而 startSpin 又不看批量状态：这 400ms 里按
「停止」只把 batch_remaining 归零、界面已显示"批量抽取完成"，到点的
startSpin 照样转一轮、照样宣布中奖并写上 last_result_index，于是"停止"
之后还会自动抽走一个项目。

现在续转经 SpinPanel._continueBatch，它先查 batch_remaining。
"""

import pytest

GAP_MS = 400


@pytest.fixture
def window(build_main_window):
    return build_main_window(
        groups=[{"name": "g", "items": ["A", "B", "C", "D"], "drawn_items": []}], refresh=True
    )


def finish_one_round(window, index=0):
    """掐掉动画并手动喂一个结果，等价于跑完批量的一轮。"""
    window.wheel.stopSpin()
    window.onSpinFinished(index, window.wheel.items[index])


class TestStopDuringRoundGap:
    def test_stop_in_the_gap_does_not_start_another_round(self, window, qtbot):
        window.batch_spinbox.setValue(3)
        window.startBatchSpin()
        finish_one_round(window)
        assert window.batch_remaining == 2, "前置条件：还剩两轮，停顿定时器已排下"

        window.stopBatchSpin()
        announced = []
        window.wheel.spinFinished.connect(lambda i, t: announced.append((i, t)))
        label = window.result_label.text()
        drawn = list(window.groups[0]["drawn_items"])

        qtbot.wait(GAP_MS + 200)

        assert not window.wheel.spinning, "停顿到点不得重新起转"
        assert announced == [], "停止之后不该再宣布中奖"
        assert window.result_label.text() == label
        assert window.groups[0]["drawn_items"] == drawn, "停止后不该再自动抽走项目"
        assert len(window.spin_panel.batch_results) == 1

    def test_gap_still_continues_when_not_stopped(self, window, qtbot):
        """未被停止时停顿到点照旧续转（上一条不能是靠"永不续转"通过的）。"""
        window.batch_spinbox.setValue(3)
        window.startBatchSpin()
        finish_one_round(window)
        assert not window.wheel.spinning

        qtbot.waitUntil(lambda: window.wheel.spinning, timeout=GAP_MS + 500)
        assert window.batch_remaining == 2
        window.stopBatchSpin()

    def test_idle_continue_is_harmless(self, window):
        """批量已结束时直接调用续转入口不得起转。"""
        window.spin_panel._continueBatch()
        assert not window.wheel.spinning
