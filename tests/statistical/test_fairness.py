"""转盘落点公平性统计检验。

这是整个重构中收益最大的一项修正的量化依据。当前实现（main.py:265-305）
取初速度 v0 ∈ [600, 2100)，按每帧 0.98 衰减，总转角跨度 2250° ＝ 6.25 圈。
非整数圈使落点密度在一个 90° 窗口内超均值 7/6.25 倍、其余区域 6/6.25 倍，
而不超过 90° 的扇区整体落入该窗口即继承约 12% 的相对超额概率。
且 setItems() 每次把 rotation 归零，该偏差在日常路径上持续生效。

本文件在阶段 0 记录**旧实现的基线**；阶段 3 改为 core.spin.plan_spin
的均匀性检验（目标相对偏差 < 1.5%），并以本文件的基线数字作为对照。
"""

import math
import random

import pytest

TIMER_INTERVAL = 0.03  # 秒，main.py 的 timer_interval / 1000
FRICTION = 0.98
VELOCITY_MIN = 600.0
VELOCITY_SPAN = 1500.0
STOP_THRESHOLD = 5.0
POINTER_ANGLE = 270.0  # 指针固定在 12 点


def legacy_total_rotation(v0):
    """闭式复刻旧物理：总转角（与逐帧模拟逐点一致，误差 0）。"""
    m = 1
    while v0 * FRICTION ** m >= STOP_THRESHOLD:
        m += 1
    return TIMER_INTERVAL * v0 * (1 - FRICTION ** m) / (1 - FRICTION)


def legacy_draw_rotation(rng):
    v0 = VELOCITY_MIN + rng.randrange(int(VELOCITY_SPAN * 1000)) / 1000.0
    return legacy_total_rotation(v0) % 360.0


def sector_at(angle, count):
    """旧实现 determineResult 的角度反算公式（重构后不得改变）。"""
    return int(((POINTER_ANGLE - angle) % 360.0) / (360.0 / count))


class TestLegacyFairnessBaseline:
    """旧实现的偏差基线：这些数字证明问题真实存在，是阶段 3 的动机。
    阶段 3 重写 spin 后本类由 test_planned_spin 取代。"""

    @pytest.mark.parametrize("count", [4, 8, 10])
    def test_legacy_bias_above_five_percent_relative(self, count):
        rng = random.Random(20260920)
        trials = 400_000
        hits = [0] * count
        for _ in range(trials):
            hits[sector_at(legacy_draw_rotation(rng), count)] += 1
        rel = [h / trials * count - 1.0 for h in hits]  # 相对偏差
        # 基线实测：n=4 约 +10.6%，n=8 约 +11~13%，n=10 约 +12.7%
        assert max(rel) > 0.05, (
            f"n={count} 相对偏差 {[f'{x:+.1%}' for x in rel]} 应显著大于 5%"
        )
        assert max(rel) < 0.20, "偏差不应超过理论上界 16.7%"

    def test_rotation_span_is_6_25_turns(self):
        lo = legacy_total_rotation(VELOCITY_MIN)
        hi = legacy_total_rotation(VELOCITY_MIN + VELOCITY_SPAN)
        assert lo == pytest.approx(892.5, abs=0.1)
        assert hi == pytest.approx(3142.5, abs=0.1)
        assert (hi - lo) / 360.0 == pytest.approx(6.25)

    def test_density_excess_window(self):
        """解析验证：落点密度在 (270-262.5, 270-172.5) ＝ (7.5°, 97.5°) 这 90°
        窗口内为 7/6.25 倍，其余为 6/6.25 倍 —— 这就是扇区级偏差的来源。"""
        rng = random.Random(7)
        bins = [0] * 72
        for _ in range(600_000):
            angle = (POINTER_ANGLE - legacy_draw_rotation(rng)) % 360.0
            bins[int(angle / 5.0)] += 1
        expected = trials_per_bin = 600_000 / 72
        inside = [bins[b] for b in range(72) if 1.5 < b * 5 + 2.5 < 97.5]
        outside = [bins[b] for b in range(72) if not (1.5 < b * 5 + 2.5 < 97.5)]
        mean_inside = sum(inside) / len(inside) / expected
        mean_outside = sum(outside) / len(outside) / expected
        assert mean_inside > 1.05
        assert mean_outside < 0.99
