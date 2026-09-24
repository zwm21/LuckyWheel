"""抽奖算法：扇区角度反算、先定结果再播动画、帧率无关的旋转物理。

三个不变量（tests/unit/test_spin.py 逐条断言）：

1. `sector_at` 与旧实现 `determineResult` 逐点一致——指针固定在 12 点
   （270°），反算 `(270 - rotation) mod 360` 落在哪个扇区；
2. `plan_spin` 保证 `sector_at(start + total_rotation) == winner_index`，
   均匀性由 `rng.randbelow(count)` 直接保证，不依赖浮点物理的副产品；
3. `rotation_at(t)` 帧率无关——无论调用方以什么节奏推进时间，终点
   精确落在 `start + total_rotation`，且曲线形状复刻旧摩擦衰减外观。

旧实现（摩擦力按帧衰减、总转角跨度 2250°＝6.25 圈）在固定起点路径下
有约 +10~12% 的扇区级相对偏差，详见 docs/REFACTOR_PLAN_V2.md 核实记录。
"""

import math
from dataclasses import dataclass

POINTER_ANGLE = 270.0  # 指针固定在 12 点方向（屏幕坐标，y 向下）

# 手感参数：与旧物理同一数量级
# 旧版摩擦 0.98/30ms ⇒ k = -ln(0.98)/0.03 ≈ 0.6735 /秒
FRICTION_K = 0.6735
# 收尾速度占初速度的比例。旧版从 v0 衰减到 <5°/s 即停，v0∈[600,2100]
# ⇒ 比例约 0.0024~0.0083，取 0.0085，停时视觉速度足够低
TAIL_RATIO = 0.0085

# 圈数：完整圈 + 随机附加圈，保证"转了好几圈再停"的观感
MIN_TURNS = 4
EXTRA_TURNS_MAX = 3
# 落点距扇区边界的最小安全裕量（占扇区跨度比例），避免浮点边界歧义
EDGE_MARGIN = 0.18


def sector_at(angle_deg, count):
    """屏幕角度（度）落在哪个扇区。旧 determineResult 的公式，逐点保持。"""
    if count <= 0:
        return 0
    pointer_angle = (POINTER_ANGLE - angle_deg) % 360.0
    idx = int(pointer_angle / (360.0 / count))
    return min(idx, count - 1)


def eased_fraction(t_over_T):
    """归一化进度 → 归一化转角。形状为指数收敛（复刻摩擦衰减外观）。

    f(x) = (1 - exp(-K x)) / (1 - TAIL_RATIO)，f(0)=0，f(1)=1，
    f'(0) = K/(1-r) 为初速度对应的斜率比例。
    """
    K = -math.log(TAIL_RATIO)
    x = min(max(t_over_T, 0.0), 1.0)
    return (1.0 - math.exp(-K * x)) / (1.0 - TAIL_RATIO)


@dataclass(frozen=True)
class SpinPlan:
    """一次旋转的完整计划。UI 只负责按时间把动画演到终点。"""

    winner_index: int
    start_angle: float  # 起始角度（度，由 UI 的当前旋转角提供）
    total_rotation: float  # 总转角（度，含完整圈与落点微调）
    duration: float  # 动画时长（秒）

    def rotation_at(self, t_seconds):
        """t 秒时的转盘角度（度）。"""
        if self.total_rotation == 0:
            return self.start_angle % 360.0
        progress = t_seconds / self.duration if self.duration > 0 else 1.0
        angle = self.start_angle + self.total_rotation * eased_fraction(progress)
        return angle


def plan_spin(count, start_angle, rng, min_turns=MIN_TURNS, extra_turns=EXTRA_TURNS_MAX):
    """为 count 个扇区的转盘生成一次旋转计划。

    均匀性来自 winner = rng.randbelow(count)；
    落点为该扇区中心附近的一个安全位置（EDGE_MARGIN 之外），
    观感上仍像随机停止，但不落在边界上。
    """
    if count <= 0:
        return SpinPlan(
            winner_index=0, start_angle=start_angle % 360.0, total_rotation=0.0, duration=0.0
        )
    winner = rng.randrange(count)
    span = 360.0 / count

    # 让 winner 扇区中心停在指针下：rotation ≡ 270 - (winner+0.5)*span
    target = (POINTER_ANGLE - (winner + 0.5) * span) % 360.0
    # 扇区内抖动，保留边界两侧至少 EDGE_MARGIN*span 的裕量
    max_jitter = (0.5 - EDGE_MARGIN) * span
    jitter = (rng.random() * 2.0 - 1.0) * max_jitter
    target = (target + jitter) % 360.0

    delta = (target - start_angle % 360.0) % 360.0
    turns = min_turns + (rng.randrange(extra_turns + 1) if extra_turns > 0 else 0)
    total = turns * 360.0 + delta

    # duration 由 K 与收尾比例决定（与旧版 3.5~5.1 秒同一量级）
    duration = -math.log(TAIL_RATIO) / FRICTION_K
    return SpinPlan(
        winner_index=winner,
        start_angle=start_angle % 360.0,
        total_rotation=total,
        duration=duration,
    )
