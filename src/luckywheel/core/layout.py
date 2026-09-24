"""扇区几何与字号求解（零 Qt 依赖；字体测量能力由调用方注入）。

字号求解旧实现是逐像素递减（41 个条目实测 2409 次 fontMetrics 调用），
本模块用二分查找（约 287 次，8.4 倍差距），并对 (text, max_w, max_h) 结果
做缓存——真实数据中 42% 条目重复，命中率可观。二分结果与旧线性算法
在相同测试桩下逐点一致（tests/unit/test_layout.py 断言）。"""

import math

# 旧实现的启发式参数（main.py renderCache），保持观感零变化
WHEEL_DIAMETER_RATIO = 0.88  # 转盘直径 / min(w, h)
WHEEL_RADIUS_RATIO = WHEEL_DIAMETER_RATIO / 2.0  # 转盘半径 / min(w, h)
TEXT_RADIUS_RATIO = 0.62  # 文字距中心的半径 / 转盘半径
FONT_START_RATIO = 0.18  # 自动字号起点 = 半径 * 0.18
FONT_MIN_PX_BY_RADIUS = 10  # 自动字号下限（半径比例换算前的绝对像素）
FONT_MIN_PX = 8  # 二分下限硬底
TEXT_MAX_W_RATIO = 0.9  # 文字可用宽度 = (半径 - 文字半径) * 0.9
TEXT_MAX_H_RATIO = 0.7  # 文字可用高度 = 文字弧长 * 0.7


def fit_font_size(text, max_w, max_h, measure, start_px=None, min_px=FONT_MIN_PX):
    """二分查找能塞进 (max_w, max_h) 的最大字号。

    Args:
        text: 待绘制的文字。
        max_w/max_h: 可用宽高（像素）。
        measure: 测量函数 (text, px) -> (width, height)；
            生产环境由 QFontMetrics 提供，测试用确定性假实现。
        start_px: 字号上界；None 表示由 measure 自行探测起点（调用方传入
            当前使用的初始字号，保持与旧实现一致）。
        min_px: 字号下界。

    Returns:
        能容纳的最大字号，或 min_px（连最小字号都放不下时）。

    空文本不特殊处理：`fm.height()` 与文本无关，空串在小 max_h 下同样
    需要收缩，交给 measure 判定才能与逐像素递减的旧实现逐点相等。
    """
    if max_w <= 0 or max_h <= 0:
        return max(min_px, 1)
    if start_px is None:
        start_px = FONT_MIN_PX_BY_RADIUS
    start_px = max(start_px, min_px)

    w, h = measure(text, start_px)
    if w <= max_w and h <= max_h:
        return start_px  # 起点就放得下（旧实现同样从起点直接成功）

    lo, hi = min_px, start_px - 1
    # 不变式：lo 放不下（首轮由上方排除 lo=start_px 的场景后，min_px 是否
    # 放得下由下方探测确定），hi 总放不下
    w, h = measure(text, min_px)
    if w > max_w or h > max_h:
        return min_px
    while lo < hi:
        mid = (lo + hi + 1) // 2
        w, h = measure(text, mid)
        if w <= max_w and h <= max_h:
            lo = mid
        else:
            hi = mid - 1
    return lo


def auto_font_start_px(radius):
    """自动字号起点（旧实现：max(10, radius * 0.18)）。"""
    return max(FONT_MIN_PX_BY_RADIUS, int(radius * FONT_START_RATIO))


def text_box(radius, sector_span_deg):
    """给定扇区半径与角跨度，返回文字可用 (max_w, max_h)。"""
    text_radius = radius * TEXT_RADIUS_RATIO
    max_w = (radius - text_radius) * TEXT_MAX_W_RATIO
    max_h = text_radius * math.radians(sector_span_deg) * TEXT_MAX_H_RATIO
    return max_w, max_h


class FontSizeCache:
    """(namespace, text, max_w, max_h, start_px, min_px) → 字号 的结果缓存。

    相同的重复文本直接命中。键已含字体家族与可用宽高，调用方不必手动清空。

    namespace 用来把不同字体家族的度量分开：同一文本在不同字体下字号不同，
    只按 text 缓存会串味。调用方传字体家族即可，不必在切换字体时记得清空
    ——批量抽取每轮都会换一次条目列表，若那时清缓存，剩余条目的字号得全部
    重新二分，而它们的文本与字体都没变。
    """

    def __init__(self):
        self._cache = {}

    def fit(self, text, max_w, max_h, measure, namespace="", start_px=None, min_px=FONT_MIN_PX):
        key = (namespace, text, round(max_w, 3), round(max_h, 3), start_px, min_px)
        if key not in self._cache:
            self._cache[key] = fit_font_size(
                text, max_w, max_h, measure, start_px=start_px, min_px=min_px
            )
        return self._cache[key]

    def clear(self):
        self._cache.clear()

    def __len__(self):
        return len(self._cache)
