"""plan_spin 落点均匀性统计检验（阶段 3 修正的量化验收）。

与同目录 test_fairness.py 的分工：那份钉住旧实现的偏差基线（相对偏差
10~12%），本文件检验新实现 core.spin.plan_spin——winner 由
rng.randrange(count) 等概率抽出，均匀性不再依赖浮点物理。

样本量与容差推导（v2 M5 约定：相对偏差）：

    任一扇区命中数 h ~ Binomial(n, 1/c)，rel = h·c/n − 1，σ = sqrt((c−1)/n)。

曾写的「20 万次 + count=41 + < 1.5%」实测必红：该情形 σ = 1.41%，1.5%
仅 1.06σ（seed 20260921 实测最大偏差 3.997%）。故每个 count 取独立样本量
n = 40000·(c−1)，σ 恒为 0.5%，1.5% 恰为 3σ；种子固定，CI 中完全确定、
无 flaky。本地预跑实测：c=4 为 0.62%，c=8 为 0.91%，c=10 为 1.46%，
c=41 为 1.13%，合计约 4s（plan_spin 实测 1.65µs/次）。
"""

import random

import pytest

from luckywheel.core.spin import plan_spin

# count -> (样本量, 种子)；样本量公式见模块 docstring
COUNTS = {
    4: (120_000, 20260925),
    8: (280_000, 20260929),
    10: (360_000, 20260931),
    41: (1_600_000, 20260962),
}

REL_TOLERANCE = 0.015  # 3σ，与旧实现 10~12% 的基线相差一个量级


class TestPlannedSpinUniformity:
    @pytest.mark.parametrize("count", sorted(COUNTS))
    def test_winner_uniform_within_tolerance(self, count):
        """最大相对偏差 < 1.5%。"""
        trials, seed = COUNTS[count]
        rng = random.Random(seed)
        hits = [0] * count
        for _ in range(trials):
            hits[plan_spin(count, rng.random() * 360.0, rng).winner_index] += 1
        rel = [h / trials * count - 1.0 for h in hits]
        assert max(abs(r) for r in rel) < REL_TOLERANCE, (
            f"count={count} n={trials} 相对偏差 {[f'{r:+.2%}' for r in rel]} "
            f"超过 {REL_TOLERANCE:.1%}"
        )

    @pytest.mark.parametrize("count", sorted(COUNTS))
    def test_sigma_is_half_percent_by_construction(self, count):
        """样本量公式自检：每个 count 的 σ 都必须是 0.5%。"""
        trials, _ = COUNTS[count]
        assert trials == 40_000 * (count - 1)
        assert ((count - 1) / trials) ** 0.5 == pytest.approx(0.005)
