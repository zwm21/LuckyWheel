"""特征测试：renderCache 的字号自适应、缓存失效规则与 HiDPI 画布。

钉住的是 CHANGELOG「未发布」段两条改动的可观察行为：
- 字号自适应：等宽/不等宽文本下二分结果与原逐像素递减逐点一致；
  重复文本只测量一次，换字体后不得沿用缓存；
- 转盘缓存：仅 min(w, h) 变化时失效；画布按 devicePixelRatio 放大，
  cached_size 仍记逻辑边长；dpr 变化必须重渲染；绘制内容的有效缩放
  恰为 dpr，不得与 QPixmap 自身的 dpr 缩放叠加成 dpr^2。

本文件与 test_current_main_behavior.py 的分工：那份钉住单文件阶段的
旧实现与已知缺陷，这份钉住重构改动的语义等价面。
"""

import math

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QFont, QPainter, QPaintEvent, QPixmap

from main import WheelWidget


class _Measurer:
    """在与 renderCache 相同的绘制环境（同尺寸 pixmap）下测量文字。"""

    def __init__(self, wheel):
        self.probe = QPixmap(wheel.width(), wheel.height())
        self.painter = QPainter(self.probe)
        self.family = wheel.font_family

    def advance_and_height(self, text, size):
        font = QFont(self.family)
        font.setBold(True)
        font.setPixelSize(size)
        self.painter.setFont(font)
        fm = self.painter.fontMetrics()
        return fm.horizontalAdvance(text), fm.height()

    def fits(self, text, size, max_w, max_h):
        w, h = self.advance_and_height(text, size)
        return w <= max_w and h <= max_h

    def close(self):
        self.painter.end()


def _constraints(wheel):
    """复刻 renderCache 中与文本无关的几何约束与初始字号。"""
    side = min(wheel.width(), wheel.height())
    radius = side * 0.88 / 2.0
    text_radius = radius * 0.62
    num = len(wheel.items)
    max_w = (radius - text_radius) * 0.9
    max_h = text_radius * math.radians(360.0 / num) * 0.7
    if wheel.font_size > 0:
        init_size = wheel.font_size
    else:
        init_size = max(10, int(radius * 0.18))
    return init_size, max_w, max_h


@pytest.fixture
def wheel(qtbot):
    wheel = WheelWidget()
    qtbot.addWidget(wheel)
    wheel.setItems(["壹", "贰", "叁", "肆", "伍"])
    wheel.resize(800, 800)
    return wheel


@pytest.fixture
def measurer(wheel):
    measurer = _Measurer(wheel)
    yield measurer
    measurer.close()


class TestFontSizeBinarySearch:
    """二分查找必须与原逐像素递减语义一致。"""

    @pytest.mark.parametrize(
        "text", ["A", "一二三四五", "很长很长的中文字符串超出扇区宽度限制", ""]
    )
    @pytest.mark.parametrize("init_size", [10, 20, 48])
    def test_binary_matches_linear_reference(self, wheel, measurer, text, init_size):
        _, max_w, max_h = _constraints(wheel)

        expected = init_size
        while not measurer.fits(text, expected, max_w, max_h):
            if expected <= 8:
                break
            expected -= 1

        actual = wheel._fit_font_size(measurer.painter, text, init_size, max_w, max_h)
        assert actual == expected

    @pytest.mark.parametrize("init_size", [10, 16, 33, 64])
    def test_result_is_largest_fitting_size(self, wheel, measurer, init_size):
        """未达下界必须放得下；结果小于初值时，结果+1 必须放不下。"""
        text = "一二三四五六七八九十"
        _, max_w, max_h = _constraints(wheel)
        size = wheel._fit_font_size(measurer.painter, text, init_size, max_w, max_h)

        assert min(8, init_size) <= size <= init_size
        if size > min(8, init_size):
            assert measurer.fits(text, size, max_w, max_h), "未达下界必须放得下"
        if size < init_size:
            assert not measurer.fits(text, size + 1, max_w, max_h), "应为最大可用字号"

    def test_tiny_init_size_is_left_alone(self, wheel, measurer):
        """固定字号 <= 8 时不再收缩（原循环在 pixelSize <= 8 时 break）。"""
        _, max_w, max_h = _constraints(wheel)
        text = "一二三四五六七八九十壹贰叁肆伍"
        assert wheel._fit_font_size(measurer.painter, text, 6, max_w, max_h) == 6

    def test_unsatisfiable_falls_back_to_lower_bound(self, wheel, measurer):
        """约束苛刻到连下界都放不下时，回退到下界而非死循环。"""
        text = "一二三四五六七八九十壹贰叁肆伍"
        size = wheel._fit_font_size(measurer.painter, text, 40, 1.0, 1.0)
        assert size == 8


class TestFontSizeCache:
    """重复文本的字号缓存。"""

    @staticmethod
    def _spy_fit(monkeypatch, seen):
        original = WheelWidget._fit_font_size

        def spy(self, painter, text, init_size, max_w, max_h):
            seen.append(text)
            return original(self, painter, text, init_size, max_w, max_h)

        monkeypatch.setattr(WheelWidget, "_fit_font_size", spy)

    def test_repeated_text_measured_once(self, qtbot, monkeypatch):
        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems(["A", "A", "A", "B"])
        wheel.resize(800, 800)

        measured = []
        self._spy_fit(monkeypatch, measured)
        wheel.renderCache()
        assert measured == ["A", "B"], "重复文本只应为每个唯一值测量一次"

    def test_font_family_change_clears_cache(self, qtbot, monkeypatch):
        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems(["测试文本"])
        wheel.resize(600, 600)
        wheel.renderCache()
        assert wheel._font_size_cache, "渲染后应留下字号缓存"

        measured = []
        self._spy_fit(monkeypatch, measured)
        wheel.setFontFamily("SimSun")
        assert wheel._font_size_cache == {}
        wheel.renderCache()
        assert measured == ["测试文本"], "换字体后必须重新测量"

    def test_font_size_change_clears_cache(self, qtbot, monkeypatch):
        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems(["测试文本"])
        wheel.resize(600, 600)
        wheel.renderCache()

        measured = []
        self._spy_fit(monkeypatch, measured)
        wheel.setFontSize(64)
        assert wheel._font_size_cache == {}
        wheel.renderCache()
        assert measured == ["测试文本"], "固定字号变更后必须重新测量"


class TestCacheGuardOnResize:
    """resize 只在 min(w, h) 变化时失效缓存。"""

    def test_same_min_side_keeps_cache(self, qtbot):
        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems(["A", "B", "C"])
        wheel.resize(700, 500)
        wheel.renderCache()
        pixmap = wheel.cached_pixmap

        wheel.show()
        wheel.resize(900, 500)  # min(w, h) 仍是 500
        assert wheel.cached_pixmap is pixmap, "min 未变时缓存应保留"
        assert wheel.cached_size == 500

    def test_changed_min_side_invalidates_cache(self, qtbot):
        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems(["A", "B", "C"])
        wheel.resize(700, 500)
        wheel.renderCache()

        wheel.show()
        wheel.resize(600, 400)
        assert wheel.cached_pixmap is None
        assert wheel.cached_size is None

    def test_paint_event_rerenders_after_invalidate(self, qtbot):
        """resize 失效后由 paintEvent 懒重建，几何未变则不重建。"""
        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems(["A", "B", "C"])
        wheel.resize(400, 300)
        wheel.renderCache()
        first = wheel.cached_pixmap

        wheel.show()
        wheel.resize(300, 200)  # resizeEvent 已失效缓存
        wheel.paintEvent(QPaintEvent(QRect(0, 0, 300, 200)))
        assert wheel.cached_pixmap is not first
        assert wheel.cached_size == 200

        current = wheel.cached_pixmap
        wheel.paintEvent(QPaintEvent(QRect(0, 0, 300, 200)))
        assert wheel.cached_pixmap is current, "几何未变时 paintEvent 不得重建缓存"


def _opaque_bbox(img):
    """不透明像素的设备像素 bbox，None 表示整图透明。"""
    x0, y0, x1, y1 = img.width(), img.height(), -1, -1
    for y in range(img.height()):
        for x in range(img.width()):
            if (img.pixel(x, y) >> 24) & 0xFF > 200:
                x0, x1 = min(x0, x), max(x1, x)
                y0, y1 = min(y0, y), max(y1, y)
    return None if x1 < 0 else (x0, y0, x1, y1)


class TestHighDpiCanvas:
    """画布按 devicePixelRatio 放大，逻辑坐标不变。"""

    @pytest.mark.parametrize("dpr,expected", [(1.0, 400), (1.25, 500), (2.0, 800)])
    def test_canvas_scaled_by_dpr(self, qtbot, monkeypatch, dpr, expected):
        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems(["A", "B", "C", "D"])
        wheel.resize(400, 400)
        monkeypatch.setattr(wheel, "devicePixelRatio", lambda: dpr)

        wheel.renderCache()
        assert wheel.cached_pixmap.width() == expected
        assert wheel.cached_pixmap.devicePixelRatio() == dpr
        assert wheel.cached_size == 400, "cached_size 保持逻辑边长，守卫语义不变"

    @pytest.mark.parametrize("dpr", [1.0, 1.5, 2.0])
    def test_drawn_wheel_is_centered_and_unclipped(self, qtbot, monkeypatch, dpr):
        """绘制内容的有效缩放必须恰为 dpr，不得叠加成 dpr^2。

        QPixmap 设了 devicePixelRatio 后其 QPainter 坐标已自动按 dpr 缩放，
        若再手动 painter.scale(dpr, dpr) 便叠加成 dpr^2：转盘被放大并移出
        画布，dpr=1 时 1^2=1 无差别，故离屏测试与仅断言画布尺寸的特征测试
        都无法暴露。此处用不透明像素 bbox 同时钉住"居中"与"不触边"——
        dpr^2 下跨度可能仍接近期望值，但圆心必然偏移且被画布裁切。
        """
        side = 400
        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems([f"ITEM{i:02d}" for i in range(12)])
        wheel.resize(side, side)
        monkeypatch.setattr(wheel, "devicePixelRatio", lambda: dpr)

        wheel.renderCache()
        img = wheel.cached_pixmap.toImage()
        bbox = _opaque_bbox(img)
        assert bbox is not None

        canvas = side * dpr
        center = canvas / 2.0
        radius = side * 0.88 / 2.0
        expected_span = 2.0 * radius * dpr

        x0, y0, x1, y1 = bbox
        actual_center = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        for axis, value in zip("xy", actual_center):
            assert abs(value - center) <= 3.0 * dpr, (
                f"{axis} 方向圆心偏移：{value:.1f} != {center:.1f}"
            )

        actual_span = (x1 - x0, y1 - y0)
        for axis, value in zip("xy", actual_span):
            # 容差覆盖 2px 白色描边向外扩出的约 1 逻辑像素与抗锯齿
            assert abs(value - expected_span) <= 6.0 * dpr, (
                f"{axis} 方向跨度 {value:.0f} != {expected_span:.0f}"
            )

        for axis, (lo, hi) in zip("xy", ((x0, x1), (y0, y1))):
            assert 0 < lo and hi < canvas - 1, f"{axis} 方向触达画布边缘（内容被裁切）：{(lo, hi)}"

    def test_dpr_change_forces_rerender(self, qtbot, monkeypatch):
        """窗口移到另一 DPI 的屏幕上（边长不变）也必须重渲染。"""
        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems(["A", "B", "C"])
        wheel.resize(400, 400)
        monkeypatch.setattr(wheel, "devicePixelRatio", lambda: 1.0)
        wheel.renderCache()
        first = wheel.cached_pixmap
        assert wheel.cached_dpr == 1.0

        monkeypatch.setattr(wheel, "devicePixelRatio", lambda: 2.0)
        wheel.paintEvent(QPaintEvent(QRect(0, 0, 400, 400)))
        assert wheel.cached_pixmap is not first, "dpr 变化后 paintEvent 必须重渲染"
        assert wheel.cached_dpr == 2.0
