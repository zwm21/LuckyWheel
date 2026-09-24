"""特征测试：renderCache 的字号自适应、缓存失效规则与 HiDPI 画布。

钉住的是 CHANGELOG「未发布」段两条改动的可观察行为：
- 字号自适应：等宽/不等宽文本下二分结果与原逐像素递减逐点一致；
  重复文本只测量一次，换字体后不得沿用缓存；
- 转盘缓存：仅 min(w, h) 变化时失效，且变化后经 80ms 去抖才真正失效
  （窗口内 paintEvent 拉伸旧缓存兜底，画面短暂模糊）；画布按
  devicePixelRatio 放大，cached_size 仍记逻辑边长；dpr 变化必须重渲染；
  绘制内容的有效缩放恰为 dpr，不得与 QPixmap 自身的 dpr 缩放叠加成 dpr^2。

本文件与 test_current_main_behavior.py 的分工：那份钉住单文件阶段的
旧实现与已知缺陷，这份钉住重构改动的语义等价面。
"""

import math

import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QFont, QImage, QPainter, QPaintEvent, QPixmap, QRegion
from PyQt6.QtWidgets import QWidget

from luckywheel.core import layout
from main import RESIZE_DEBOUNCE_MS, WheelWidget


def fit_size(wheel, painter, text, init_size, max_w, max_h):
    """复刻 renderCache 的字号求解调用。

    算法住在 core.layout；下界经 wheel._fit_min_px（min(8, init_size)），
    测量由 wheel._measure 绑定当前字体家族。
    """
    return layout.fit_font_size(
        text,
        max_w,
        max_h,
        wheel._measure(painter),
        start_px=init_size,
        min_px=wheel._fit_min_px(init_size),
    )


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

        actual = fit_size(wheel, measurer.painter, text, init_size, max_w, max_h)
        assert actual == expected

    @pytest.mark.parametrize("init_size", [10, 16, 33, 64])
    def test_result_is_largest_fitting_size(self, wheel, measurer, init_size):
        """未达下界必须放得下；结果小于初值时，结果+1 必须放不下。"""
        text = "一二三四五六七八九十"
        _, max_w, max_h = _constraints(wheel)
        size = fit_size(wheel, measurer.painter, text, init_size, max_w, max_h)

        assert min(8, init_size) <= size <= init_size
        if size > min(8, init_size):
            assert measurer.fits(text, size, max_w, max_h), "未达下界必须放得下"
        if size < init_size:
            assert not measurer.fits(text, size + 1, max_w, max_h), "应为最大可用字号"

    def test_tiny_init_size_is_left_alone(self, wheel, measurer):
        """固定字号 <= 8 时不再收缩（原循环在 pixelSize <= 8 时 break）。"""
        _, max_w, max_h = _constraints(wheel)
        text = "一二三四五六七八九十壹贰叁肆伍"
        assert fit_size(wheel, measurer.painter, text, 6, max_w, max_h) == 6

    def test_unsatisfiable_falls_back_to_lower_bound(self, wheel, measurer):
        """约束苛刻到连下界都放不下时，回退到下界而非死循环。"""
        text = "一二三四五六七八九十壹贰叁肆伍"
        size = fit_size(wheel, measurer.painter, text, 40, 1.0, 1.0)
        assert size == 8


class TestFontSizeCache:
    """重复文本的字号缓存。"""

    @staticmethod
    def _spy_fit(monkeypatch, seen):
        """拦在 core.layout.fit_font_size 上：FontSizeCache 命中时不该到达这里。"""
        original = layout.fit_font_size

        def spy(text, *args, **kwargs):
            seen.append(text)
            return original(text, *args, **kwargs)

        monkeypatch.setattr(layout, "fit_font_size", spy)

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
        assert len(wheel._font_size_cache) > 0, "渲染后应留下字号缓存"

        measured = []
        self._spy_fit(monkeypatch, measured)
        wheel.setFontFamily("SimSun")
        assert len(wheel._font_size_cache) == 0
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
        assert len(wheel._font_size_cache) == 0
        wheel.renderCache()
        assert measured == ["测试文本"], "固定字号变更后必须重新测量"


class TestCacheGuardOnResize:
    """resize 去抖：窗口内只标记 pending，停止 80ms 后才失效重建。

    拖动窗口边缘时 resizeEvent 密集到达，每次同步重建缓存在 n=200 时要
    几十毫秒（CHANGELOG「未发布」段记录）。去抖后：resize 标记 pending
    并（重）起单次定时器，窗口内 paintEvent 用旧缓存按新旧边长比拉伸
    兜底——短暂模糊是该方案的有意折衷。
    """

    @staticmethod
    def _spy_render(monkeypatch, seen):
        """记录每次 renderCache 实际使用的边长。"""
        original = WheelWidget.renderCache

        def spy(self):
            seen.append(min(self.width(), self.height()))
            return original(self)

        monkeypatch.setattr(WheelWidget, "renderCache", spy)

    @staticmethod
    def _shown_wheel(qtbot, side=500, count=12):
        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems([f"ITEM{i:02d}" for i in range(count)])
        wheel.resize(side, side)
        wheel.renderCache()
        wheel.show()
        return wheel

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
        assert wheel._pending_side is None, "min 未变不应进入去抖"

    def test_changed_min_side_defers_invalidation(self, qtbot):
        """min(w, h) 变化不再立即失效：标记 pending 并起单次定时器。"""
        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems(["A", "B", "C"])
        wheel.resize(700, 500)
        wheel.renderCache()
        pixmap = wheel.cached_pixmap

        wheel.show()
        wheel.resize(600, 400)
        assert wheel.cached_pixmap is pixmap, "去抖窗口内缓存不得失效"
        assert wheel.cached_size == 500
        assert wheel._pending_side == 400, "应记下待生效的新边长"
        assert wheel._resize_timer.isSingleShot()
        assert wheel._resize_timer.isActive(), "pending 期间定时器必须在跑"

    def test_repeated_resizes_do_not_rebuild(self, qtbot, monkeypatch):
        """窗口内连续 resize 不触发 renderCache，定时器被不断重启。"""
        wheel = self._shown_wheel(qtbot)
        rendered = []
        self._spy_render(monkeypatch, rendered)

        for side in (480, 460, 440, 420, 400):
            wheel.resize(side, side)
            assert rendered == [], f"resize 到 {side} 不应重建缓存"
            assert wheel._resize_timer.isActive(), "每次 resize 都应重启定时器"
        assert wheel._pending_side == 400, "pending 应跟踪最后一次 resize"

    def test_rebuilds_once_after_debounce_elapses(self, qtbot, monkeypatch):
        """停止 80ms 后恰好重建一次，且按最新边长重建。"""
        wheel = self._shown_wheel(qtbot)
        rendered = []
        self._spy_render(monkeypatch, rendered)

        for side in (480, 460, 440, 420, 400):
            wheel.resize(side, side)
        qtbot.wait(RESIZE_DEBOUNCE_MS + 60)

        assert rendered == [400], "去抖到点应恰好重建一次，且使用最新边长"
        assert wheel.cached_size == 400
        assert wheel._pending_side is None, "生效后应清除 pending"
        assert not wheel._resize_timer.isActive()

    def test_paint_stretches_old_cache_during_debounce(self, qtbot, monkeypatch):
        """去抖窗口内 paintEvent 拉伸旧缓存兜底，不触发重建。

        旧 500 边长缓存按 400/500 拉伸后半径恰为 400*0.44，与新边长直接
        渲染同几何，故同时钉住「画满新尺寸」与「未触边」：若窗口内按原
        尺寸绘制旧图，半径 500*0.44=220 会超出 400 画布的一半而被裁切。

        wheel.grab() 会用 widget 背景色填满整幅画布，角点全不透明，无法
        用 alpha 分辨轮盘边界；改用 wheel.render() 画到自建透明 QImage 上
        测量。指针固定在圆心正上方，量竖向跨度时取偏离圆心的一列，按弦长
        公式换算期望值，避免把指针尖端当成轮盘边缘。
        """
        wheel = self._shown_wheel(qtbot, side=500)
        rendered = []
        self._spy_render(monkeypatch, rendered)

        wheel.resize(400, 400)
        img = _render_to_transparent(wheel)
        assert rendered == [], "去抖窗口内不得重建缓存"

        side = 400
        radius = side * 0.88 / 2.0
        center = side / 2.0
        row = _opaque_extent(img, y=int(center))
        offset = int(radius / 3)
        col = _opaque_extent(img, x=int(center) + offset)
        assert row is not None and col is not None, "拉伸后转盘应仍在绘制"

        # 偏离圆心 offset 处，轮盘在该列的竖向半弦长
        half_chord = math.sqrt(radius**2 - offset**2)
        for label, (lo, hi), expected in (
            ("横向（过圆心行）", row, 2.0 * radius),
            (f"竖向（圆心右 {offset} 列）", col, 2.0 * half_chord),
        ):
            assert abs((lo + hi) / 2.0 - center) <= 3.0, f"{label} 圆心偏移：{(lo, hi)}"
            # 容差覆盖 2px 白色描边向外扩出的约 1 逻辑像素与抗锯齿
            assert abs((hi - lo) - expected) <= 6.0, (
                f"{label} 跨度 {hi - lo} != {expected:.0f}（旧图未拉伸到新尺寸）"
            )
            assert 0 < lo and hi < side - 1, f"{label} 触达画布边缘（内容被裁切）：{(lo, hi)}"


def _render_to_transparent(widget, side=None):
    """把 widget 画到透明 QImage 上并返回（grab() 会填背景色，角点全不透明）。"""
    if side is None:
        side = min(widget.width(), widget.height())
    img = QImage(side, side, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    widget.render(painter, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
    painter.end()
    return img


def _opaque_extent(img, x=None, y=None):
    """沿 y 行或 x 列量不透明像素的起止坐标；该行/列全透明时返回 None。"""
    count = img.height() if y is None else img.width()
    hits = []
    for i in range(count):
        px, py = (i, y) if y is not None else (x, i)
        if (img.pixel(px, py) >> 24) & 0xFF > 200:
            hits.append(i)
    return (hits[0], hits[-1]) if hits else None


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
