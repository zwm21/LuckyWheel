"""GUI 端到端：旋转动画结束后 emit 的 winner 必须与指针实际指向一致（P2）。

core.spin 的单元测试保证 plan_spin 的不变量；这里把整条链路接起来：
真动画 → 终角 → sector_at 反算 → emit 的 (index, text)。
"""

import random

import pytest
from PyQt6.QtCore import QVariantAnimation

from luckywheel.core.spin import sector_at


@pytest.fixture
def fast_wheel(qtbot):
    """加速版转盘：动画时长除以 60，冒烟与统计都能在秒级跑完。"""
    from main import WheelWidget

    wheel = WheelWidget()
    qtbot.addWidget(wheel)
    wheel.resize(600, 600)
    wheel.speed_scale = 60.0
    return wheel


def run_to_completion(qtbot, wheel, timeout=8000):
    qtbot.waitUntil(lambda: not wheel.spinning, timeout=timeout)


class TestSpinFinishedContract:
    def test_emit_matches_pointer_direction(self, qtbot, fast_wheel):
        """emit 的 index 必须等于对最终角度做 sector_at 反算的结果。"""
        fast_wheel.setItems(["A", "B", "C", "D", "E"])
        captured = []
        fast_wheel.spinFinished.connect(lambda i, t: captured.append((i, t, fast_wheel.rotation)))
        fast_wheel.startSpin()
        run_to_completion(qtbot, fast_wheel)

        assert len(captured) == 1
        index, text, final_rotation = captured[0]
        assert sector_at(final_rotation, 5) == index, "emit 的扇区与盘面角度不一致"
        assert text == fast_wheel.items[index]

    def test_emit_matches_pointer_many_runs(self, qtbot, fast_wheel):
        """重复多轮：信号契约与 plan 不变量在整条链路上都成立。"""
        for _ in range(30):
            fast_wheel.setItems(["A", "A", "B", "C"])  # 含重复项
            captured = []
            fast_wheel.spinFinished.connect(
                lambda i, t, c=captured, w=fast_wheel: c.append((i, t, w.rotation))
            )
            fast_wheel.startSpin()
            run_to_completion(qtbot, fast_wheel)
            index, text, final_rotation = captured[0]
            assert sector_at(final_rotation, 4) == index
            assert text == fast_wheel.items[index]
            fast_wheel.spinFinished.disconnect()

    def test_winner_distribution_roughly_uniform(self, qtbot, fast_wheel):
        """端到端 60 轮的胜者分布：每桶至少命中一次（均匀期望的 0.5 倍）。"""
        items = ["A", "B", "C", "D", "E", "F"]
        hits = [0] * len(items)
        for _ in range(60):
            fast_wheel.setItems(items)
            captured = []
            fast_wheel.spinFinished.connect(lambda i, t, c=captured: c.append(i))
            fast_wheel.startSpin()
            run_to_completion(qtbot, fast_wheel)
            hits[captured[0]] += 1
            fast_wheel.spinFinished.disconnect()
        assert min(hits) >= 1, f"分布严重倾斜: {hits}"


class TestAnimationControl:
    def test_stop_spin_emits_no_result(self, qtbot, fast_wheel):
        fast_wheel.setItems(["A", "B", "C"])
        captured = []
        fast_wheel.spinFinished.connect(lambda i, t: captured.append(i))
        fast_wheel.startSpin()
        assert fast_wheel.spinning
        qtbot.wait(50)
        fast_wheel.stopSpin()
        qtbot.wait(200)
        assert not fast_wheel.spinning
        assert captured == [], "手动停止不应产生中奖结果"

    def test_double_start_is_guarded(self, qtbot, fast_wheel):
        fast_wheel.setItems(["A", "B", "C"])
        fast_wheel.startSpin()
        first = fast_wheel.animation
        fast_wheel.startSpin()
        assert fast_wheel.animation is first, "旋转中重复 startSpin 应被忽略"
        run_to_completion(qtbot, fast_wheel)

    def test_animation_is_qvariantanimation(self, fast_wheel):
        fast_wheel.setItems(["A", "B", "C"])
        fast_wheel.startSpin()
        assert isinstance(fast_wheel.animation, QVariantAnimation)

    def test_rotation_stays_normalized_after_spin(self, qtbot, fast_wheel):
        fast_wheel.setItems(["A", "B", "C", "D"])
        fast_wheel.startSpin()
        run_to_completion(qtbot, fast_wheel)
        assert 0.0 <= fast_wheel.rotation < 360.0


class TestSetItemsCancelsSpin:
    def test_set_items_stops_animation(self, qtbot, fast_wheel):
        fast_wheel.setItems(["A", "B", "C"])
        fast_wheel.startSpin()
        fast_wheel.setItems(["X", "Y", "Z"])
        assert not fast_wheel.spinning
        assert fast_wheel.animation is None
        qtbot.wait(200)  # 旧动画若未停会继续改角度

    def test_empty_items_no_spin(self, fast_wheel):
        fast_wheel.setItems([])
        fast_wheel.startSpin()
        assert not fast_wheel.spinning
        assert fast_wheel.animation is None


class TestSeededPlan:
    def test_fixed_seed_gives_expected_winner(self, qtbot, fast_wheel, monkeypatch):
        """以固定 seed 驱动 plan_spin：整条动画链路的结果可复现。"""
        rng = random.Random(20260920)
        monkeypatch.setattr("luckywheel.ui.wheel.random", rng)
        fast_wheel.setItems(["A", "B", "C", "D", "E", "F", "G"])
        captured = []
        fast_wheel.spinFinished.connect(lambda i, t: captured.append(i))
        fast_wheel.startSpin()
        run_to_completion(qtbot, fast_wheel)

        from luckywheel.core.spin import plan_spin

        expected = plan_spin(7, 0.0, random.Random(20260920)).winner_index
        assert captured[0] == expected
