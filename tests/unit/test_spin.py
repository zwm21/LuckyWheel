"""core.spin：扇区反算与旋转计划不变量（零 Qt 依赖）。"""

import random

import pytest

from luckywheel.core.spin import (
    POINTER_ANGLE,
    SpinPlan,
    eased_fraction,
    plan_spin,
    sector_at,
)


class TestSectorAt:
    @pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 8, 10, 17, 41, 60, 97])
    @pytest.mark.parametrize("angle", [0.0, 30.0, 100.0, 217.3, 359.0, 720.5, -45.0])
    def test_matches_legacy_formula(self, angle, count):
        """与旧实现 determineResult 逐点一致（含负数与超 360 输入）。"""
        pointer_angle = (POINTER_ANGLE - angle) % 360.0
        expected = int(pointer_angle / (360.0 / count))
        expected = min(expected, count - 1)
        assert sector_at(angle, count) == expected

    def test_count_zero_is_safe(self):
        assert sector_at(123.0, 0) == 0

    def test_boundary_goes_to_higher_sector(self):
        """恰落在边界 270°、count=4 时为平局，旧实现取高索引，保持一致。"""
        assert sector_at(0.0, 4) == 3


class TestEasedFraction:
    def test_endpoints(self):
        assert eased_fraction(0.0) == pytest.approx(0.0)
        assert eased_fraction(1.0) == pytest.approx(1.0)

    def test_monotonic(self):
        xs = [i / 100 for i in range(101)]
        ys = [eased_fraction(x) for x in xs]
        assert all(b >= a for a, b in zip(ys, ys[1:]))

    def test_clamped_outside(self):
        assert eased_fraction(-1.0) == pytest.approx(0.0)
        assert eased_fraction(2.0) == pytest.approx(1.0)


class TestPlanSpin:
    @pytest.mark.parametrize("count", range(1, 61))
    def test_invariant_final_angle_hits_winner(self, count):
        """核心不变式：sector_at(start + total) == winner（count 1..60 逐值）。

        旧的抽样清单 [1, 2, 3, 4, 8, 10, 41] 漏掉了 count=7、12 等
        span 非整数度的组合；逐值覆盖 60 个 count 实测仅约 0.03s，
        没有理由再抽样。
        """
        rng = random.Random(1000 + count)
        for _ in range(300):
            start = rng.random() * 360.0
            plan = plan_spin(count, start, rng)
            final = (plan.start_angle + plan.total_rotation) % 360.0
            assert sector_at(final, count) == plan.winner_index, (
                f"count={count} start={start:.1f} final={final:.1f} "
                f"winner={plan.winner_index} got={sector_at(final, count)}"
            )

    @pytest.mark.parametrize("count", [3, 4, 7, 12])
    def test_winner_is_uniform(self, count):
        """均匀性：10 万次直接采样，任一扇区相对偏差 < 3%。

        3% 约 3.8σ（100k/7 桶的标准误约 0.78%），全部不超的概率 >99.99%；
        旧实现的偏差是 10~12%（约 12σ），两者相差一个数量级。
        """
        rng = random.Random(count)
        trials = 100_000
        hits = [0] * count
        for _ in range(trials):
            hits[plan_spin(count, rng.random() * 360, rng).winner_index] += 1
        rel = [h / trials * count - 1.0 for h in hits]
        assert max(abs(r) for r in rel) < 0.03, f"相对偏差 {[f'{r:+.2%}' for r in rel]} 超过 3%"

    def test_landing_keeps_edge_margin(self):
        """落点不贴扇区边界（安全裕量内），避免浮点边界歧义。"""
        rng = random.Random(42)
        for count in (4, 9, 17):
            for _ in range(500):
                plan = plan_spin(count, rng.random() * 360, rng)
                span = 360.0 / count
                final = (plan.start_angle + plan.total_rotation) % 360.0
                pointer = (POINTER_ANGLE - final) % 360.0
                offset = pointer % span  # 距扇区下边界的偏移
                assert span * 0.18 < offset < span * 0.82, (
                    f"count={count} 落点 offset={offset:.2f} span={span:.2f} 过于贴边"
                )

    def test_minimum_turns(self):
        rng = random.Random(1)
        for _ in range(50):
            plan = plan_spin(5, 0.0, rng)
            assert plan.total_rotation >= 4 * 360.0

    def test_zero_count_is_noop(self):
        plan = plan_spin(0, 123.0, random.Random(0))
        assert plan.total_rotation == 0.0
        assert plan.winner_index == 0


class TestSpinPlanTimeline:
    def test_rotation_at_endpoint_exact(self):
        plan = SpinPlan(winner_index=0, start_angle=30.0, total_rotation=1437.5, duration=7.0)
        assert plan.rotation_at(7.0) == pytest.approx(30.0 + 1437.5)
        assert plan.rotation_at(99.0) == pytest.approx(30.0 + 1437.5)

    def test_rotation_at_is_frame_rate_independent(self):
        """同一起止，无论以什么 dt 序列推进，终点一致。"""
        plan = SpinPlan(winner_index=2, start_angle=10.0, total_rotation=1900.0, duration=6.0)
        for dts in (
            [0.03] * 200,
            [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
            [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        ):
            t = 0.0
            while t < plan.duration:
                t += dts[0]
            assert plan.rotation_at(t) == pytest.approx(plan.start_angle + plan.total_rotation)

    def test_velocity_decreases(self):
        plan = SpinPlan(winner_index=0, start_angle=0.0, total_rotation=1800.0, duration=7.0)
        assert plan.velocity_at(0.0) > plan.velocity_at(plan.duration / 2)
        assert plan.velocity_at(plan.duration / 2) > plan.velocity_at(plan.duration)
        assert plan.velocity_at(plan.duration) < 15.0  # 收尾很慢

    def test_duration_in_legacy_range(self):
        """时长与旧实现同一量级（旧版 5.1~7.1 秒）。"""
        rng = random.Random(7)
        for _ in range(30):
            plan = plan_spin(8, 0.0, rng)
            assert 5.0 < plan.duration < 7.5
