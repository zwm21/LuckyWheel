"""转盘离屏渲染的像素级基线回归（批次 5a）。

基线 PNG 由**现状实现**渲染固定用例生成并入库 tests/data/；批次 5b 的
策略 J 与 5c 的 resize 去抖都对照它保证「画面没有变样」。

断言按环境相关性分两级：

- 几何与配色（扇区底色、半径分隔线、外圆描边）只取决于注入的 palette
  与绘制路径，与字体无关，任何环境都执行；
- 全图像素对比还取决于文字字形，而字形随可用字体与 Qt 版本变化。用
  探针指纹（同一字体设置渲染固定文本的像素摘要）判定环境是否一致，
  不一致时 skip 全图对比而不是失败——那不是回归，只是基线不可复现。

offscreen 下 QFontInfo 解析不到族名（返回空串），所以指纹直接取渲染
结果，比族名更贴近真实依赖。
"""

import hashlib
import json
import math
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter

from luckywheel.ui.wheel import WheelWidget

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BASELINE_PNG = DATA_DIR / "wheel_baseline.png"
BASELINE_META = DATA_DIR / "wheel_baseline.json"

SIDE = 400
RADIUS_FRACTION = 0.44  # renderCache: wheel_diameter = side * 0.88
# 高区分度配色：相邻项色相/明度差足够大，取样点落错扇区立刻可见
COLOR_HEXES = [
    "#FF0000",
    "#00FF00",
    "#0000FF",
    "#FFFF00",
    "#FF00FF",
    "#00FFFF",
    "#123456",
    "#654321",
]
# 混合长度文本：覆盖 _fit_font_size 二分命中的长文本与 CJK/ASCII 混排
ITEMS = [
    "一等奖",
    "二等奖",
    "三等奖",
    "幸运奖",
    "谢谢参与",
    "再来一次",
    "安慰奖",
    "神秘大奖",
]


def _polar_point(radius_fraction, angle_deg):
    """极角（度）与半径比例 → 缓存图的设备像素坐标。"""
    theta = math.radians(angle_deg)
    radius = SIDE * RADIUS_FRACTION * radius_fraction
    return (
        SIDE / 2.0 + radius * math.cos(theta),
        SIDE / 2.0 + radius * math.sin(theta),
    )


def _color_at(img, x, y):
    return QColor.fromRgba(img.pixel(int(x), int(y)))


def _is_white(color):
    """白色描边判定：抗锯齿边缘到不了 255，阈值取 230。"""
    return color.red() > 230 and color.green() > 230 and color.blue() > 230 and color.alpha() > 200


def _has_white_near(img, point, span=3):
    """理想坐标附近的小邻域内是否存在白色描边像素。

    描边宽 2px，而取样用的是理想角度/半径，抗锯齿会让线心偏离整像素，
    只查一个点会偶发落空。
    """
    x0, y0 = int(round(point[0])), int(round(point[1]))
    for dy in range(-span, span + 1):
        for dx in range(-span, span + 1):
            x, y = x0 + dx, y0 + dy
            if 0 <= x < img.width() and 0 <= y < img.height():
                if _is_white(_color_at(img, x, y)):
                    return True
    return False


def _text_env_fingerprint(wheel):
    """同一字体设置渲染固定文本的像素摘要，判定基线能否复现。"""
    probe = QImage(96, 32, QImage.Format.Format_ARGB32)
    probe.fill(Qt.GlobalColor.transparent)
    painter = QPainter(probe)
    font = QFont(wheel.font_family)
    font.setBold(True)
    font.setPixelSize(20)
    painter.setFont(font)
    painter.drawText(probe.rect(), Qt.AlignmentFlag.AlignCenter, "幸运奖 Ag0")
    painter.end()
    return hashlib.sha256(probe.bits().asstring(probe.sizeInBytes())).hexdigest()


def _write_baseline(wheel, img):
    """把当前渲染写为基线（仅在 tests/data/ 缺文件时由测试调用）。

    有意变更画面后要重新生成：删除 tests/data/wheel_baseline.* 再跑本
    文件。生成结果会体现在 git diff 里，不会静默掩盖回归。
    """
    if not img.save(str(BASELINE_PNG), "PNG"):
        pytest.fail(f"基线写入失败：{BASELINE_PNG}")
    meta = {
        "items": ITEMS,
        "colors": COLOR_HEXES,
        "side": SIDE,
        "font_family": wheel.font_family,
        "font_size": wheel.font_size,
        "shadow_enabled": wheel.shadow_enabled,
        "text_env_fingerprint": _text_env_fingerprint(wheel),
        "regenerate": "删除 tests/data/wheel_baseline.* 后运行本测试文件",
    }
    BASELINE_META.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


@pytest.fixture
def wheel(qtbot):
    widget = WheelWidget()
    qtbot.addWidget(widget)
    widget.setItems(ITEMS)
    widget.setSectorColors([QColor(h) for h in COLOR_HEXES])
    widget.resize(SIDE, SIDE)
    widget.renderCache()
    return widget


@pytest.fixture
def img(wheel):
    """缓存的非预乘 ARGB32 视图：取值与 PNG 往返结果逐字节一致。"""
    return wheel.cached_pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)


class TestSectorPalette:
    def test_interior_color_matches_injected_palette(self, img):
        """扇区内部底色 = 注入 palette 的对应色（含反向映射）。

        arcTo 的正向扫掠与 (cosθ, sinθ) 参数化方向相反：极角
        k·span+span/2 处的底色是 COLOR_HEXES[num-1-k]，与 renderCache 给
        文字取对比色同一公式（sector_colors[num - 1 - i]）。取样半径取
        0.2r：文字带在 0.5r 以外，这里必为纯净色。
        """
        num = len(ITEMS)
        span = 360.0 / num
        for k in range(num):
            expected = QColor(COLOR_HEXES[num - 1 - k])
            actual = _color_at(img, *_polar_point(0.2, k * span + span / 2.0))
            assert actual.name().upper() == expected.name().upper(), (
                f"扇区 {k} 中线底色 {actual.name()} != 注入色 {expected.name()}"
            )


class TestStrokeGeometry:
    def test_radial_separators_are_white(self, img):
        """每个扇区边界半径上都有 2px 白描边（策略 J 不得改丢）。"""
        num = len(ITEMS)
        span = 360.0 / num
        for k in range(num):
            assert _has_white_near(img, _polar_point(0.5, k * span)), (
                f"扇区 {k} 与 {(k + 1) % num} 之间的半径分隔线缺失白描边"
            )

    def test_outer_rim_is_white(self, img):
        """外圆有白描边（策略 J 把它从扇形路径拆出，不得改丢）。"""
        num = len(ITEMS)
        span = 360.0 / num
        for k in range(num):
            assert _has_white_near(img, _polar_point(1.0, k * span + span / 2.0)), (
                f"扇区 {k} 中线的外圆描边缺失"
            )


class TestBaselinePixels:
    def test_metadata_matches_fixture(self):
        """元数据与测试常量不一致 = 改了用例却没重新生成基线。"""
        if not BASELINE_META.exists():
            pytest.skip(f"基线尚未生成：{BASELINE_META}")
        meta = json.loads(BASELINE_META.read_text(encoding="utf-8"))
        assert meta["items"] == ITEMS, "items 与基线不一致，需重新生成基线"
        assert meta["colors"] == COLOR_HEXES, "配色与基线不一致，需重新生成基线"
        assert meta["side"] == SIDE, "尺寸与基线不一致，需重新生成基线"

    def test_render_matches_committed_baseline(self, wheel, img):
        """全图与基线 >99.9% 字节相同，且差异处每通道差 ≤8。

        ARGB32 里一个字节就是一个颜色通道，因此字节差即通道差；抗锯齿
        与字体版本差异只会带来 ±1 量级的舍入，阈值 8 足够宽松又能抓住
        真正的画面变样。
        """
        if not BASELINE_PNG.exists():
            _write_baseline(wheel, img)
            pytest.skip(f"基线已生成：{BASELINE_PNG}")
        meta = json.loads(BASELINE_META.read_text(encoding="utf-8"))
        if meta.get("text_env_fingerprint") != _text_env_fingerprint(wheel):
            pytest.skip("文字渲染环境与基线不一致（字体/字形差异），跳过全图对比")
        baseline = QImage(str(BASELINE_PNG)).convertToFormat(QImage.Format.Format_ARGB32)
        assert baseline.size() == img.size(), (
            f"基线尺寸 {baseline.width()}x{baseline.height()} != 当前 {img.width()}x{img.height()}"
        )
        current = img.bits().asstring(img.sizeInBytes())
        reference = baseline.bits().asstring(baseline.sizeInBytes())
        if current != reference:
            diff = [abs(a - b) for a, b in zip(current, reference) if a != b]
            assert len(diff) / len(reference) <= 0.001, (
                f"{len(diff)}/{len(reference)} 字节不同（>0.1%），画面已变样"
            )
            assert max(diff) <= 8, f"最大通道差 {max(diff)} > 8，画面已变样"
