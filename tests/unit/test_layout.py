"""core.layout：字号二分与测量注入（零 Qt 依赖）。"""

import random

from luckywheel.core.layout import (
    FONT_MIN_PX,
    FontSizeCache,
    auto_font_start_px,
    fit_font_size,
    text_box,
)


class Measurement:
    """确定性测量桩：宽度 = 0.6em * 字数，高度 = 1.2em。"""

    def __init__(self):
        self.calls = 0

    def __call__(self, text, px):
        self.calls += 1
        return len(text) * 0.6 * px, 1.2 * px


def linear_fit(text, max_w, max_h, measure, start_px):
    """旧实现：逐像素递减。用于与二分结果比对。"""
    px = start_px
    while px > FONT_MIN_PX:
        w, h = measure(text, px)
        if w <= max_w and h <= max_h:
            return px
        px -= 1
    return px


class TestFitFontSize:
    def test_binary_matches_linear(self):
        """观感零变化：二分结果与旧逐像素递减逐一相等。"""
        measure = Measurement()
        rng = random.Random(3)
        for _ in range(300):
            text = "项" * rng.randrange(1, 12)
            max_w = rng.uniform(20, 300)
            max_h = rng.uniform(10, 80)
            start_px = rng.randrange(10, 60)
            binary = fit_font_size(text, max_w, max_h, measure, start_px=start_px)
            linear = linear_fit(text, max_w, max_h, Measurement(), start_px)
            assert binary == linear, (text, max_w, max_h, start_px, binary, linear)

    def test_fewer_measure_calls_than_linear(self):
        """二分的核心动机：测量调用显著少于线性。"""
        measure = Measurement()
        text = "长文本条目示例长文本"
        fit_font_size(text, 60, 30, measure, start_px=60)
        binary_calls = measure.calls
        linear_calls = 0
        px = 60
        while px > FONT_MIN_PX:
            linear_calls += 1
            px -= 1
        assert binary_calls < linear_calls / 3

    def test_start_px_fits_returns_start(self):
        measure = Measurement()
        assert fit_font_size("A", 1000, 1000, measure, start_px=42) == 42

    def test_below_floor_returns_min(self):
        measure = Measurement()
        assert fit_font_size("很长" * 30, 5, 5, measure, start_px=50) == FONT_MIN_PX

    def test_empty_text_is_safe(self):
        measure = Measurement()
        assert fit_font_size("", 10, 10, measure, start_px=20) >= 1


class TestTextboxHelpers:
    def test_auto_font_start_px(self):
        assert auto_font_start_px(50) == 10  # max(10, 9)
        assert auto_font_start_px(300) == 54

    def test_text_box_shapes(self):
        max_w, max_h = text_box(radius=100, sector_span_deg=30)
        assert 0 < max_w < 100
        assert 0 < max_h < 100


class TestFontSizeCache:
    def test_hits_for_repeated_text(self):
        measure = Measurement()
        cache = FontSizeCache()
        args = ("相同文本", 100, 40)
        first = cache.fit(*args, measure, start_px=30)
        calls_after_first = measure.calls
        second = cache.fit(*args, measure, start_px=30)
        assert first == second
        assert measure.calls == calls_after_first, "第二次应直接命中缓存"

    def test_typical_data_hit_rate(self):
        """复刻真实数据形状：41 项中 17 个唯一值，命中率约 58%。"""
        measure = Measurement()
        cache = FontSizeCache()
        items = (
            ["选项3", "选项1", "选项2"]
            + ["1"] * 15
            + [
                "214",
                "21",
                "454",
                "12",
                "145",
                "5412",
                "451",
                "54",
                "54",
                "41",
                "4",
                "542",
                "45",
                "5412",
                "54",
                "5412",
                "41",
                "54",
                "52",
                "41",
                "52",
                "45",
                "41",
            ]
        )
        assert len(items) == 41 and len(set(items)) == 17
        solve_calls = 0
        for item in items:
            before = measure.calls
            cache.fit(item, 60, 30, measure, start_px=40)
            if measure.calls > before:
                solve_calls += 1
        assert solve_calls == 17, "唯一文本才应触发求解"

    def test_clear(self):
        cache = FontSizeCache()
        measure = Measurement()
        cache.fit("A", 10, 10, measure, start_px=20)
        assert len(cache) == 1
        cache.clear()
        assert len(cache) == 0

    def test_namespace_separates_font_families(self):
        """同一文本在不同字体下字号不同，键必须带 namespace。

        调用方（WheelWidget）传字体家族；若只按 text 缓存，换字体后会沿用
        旧字体的求解结果。
        """
        narrow = lambda text, px: (len(text) * 0.3 * px, 1.2 * px)  # noqa: E731
        wide = lambda text, px: (len(text) * 0.9 * px, 1.2 * px)  # noqa: E731
        cache = FontSizeCache()
        # max_h 给足，让宽度成为唯一约束：窄体在起点 40 就放得下，宽体要收缩
        a = cache.fit("条目", 60, 1000, narrow, namespace="窄体", start_px=40)
        b = cache.fit("条目", 60, 1000, wide, namespace="宽体", start_px=40)
        assert a == 40, "窄体应放得下起点字号"
        assert b == 33, "宽体应收缩到 60 / (2 * 0.9) = 33"
        assert len(cache) == 2, "不同 namespace 不得共享条目"

    def test_same_namespace_hits(self):
        cache = FontSizeCache()
        measure = Measurement()
        first = cache.fit("A", 60, 30, measure, namespace="F", start_px=20)
        calls = measure.calls
        assert cache.fit("A", 60, 30, measure, namespace="F", start_px=20) == first
        assert measure.calls == calls, "同 namespace 同参数应命中"

    def test_capacity_is_bounded(self, monkeypatch):
        """容量封顶：键含可用宽高，批量抽取每轮条目数变化都产生新键，不淘汰
        则整个批次（spinbox 上限近千次）单调增长。超限整体清空即可——求解
        是纯函数，重建成本有界。
        """
        cache = FontSizeCache()
        measure = Measurement()
        monkeypatch.setattr(FontSizeCache, "MAX_ENTRIES", 4)
        for i in range(10):
            cache.fit(f"t{i}", 60, 30, measure, namespace="F", start_px=20)
        assert len(cache) <= 4, "缓存条目数必须有上界"
