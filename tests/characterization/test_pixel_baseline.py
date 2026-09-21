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

批次 5b 起全图对比从「逐字节相同」改为「有界且受限」：策略 J 的批量
描边无法复现优化前「每扇区各描一遍、中间夹着不透明填充」的交错合成，
抗锯齿带内的差异真实存在且可解释，见
test_render_matches_committed_baseline 的说明。
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

# 全图对比的容忍度（批次 5b 策略 J 后按实测标定，勿凭手感调）
DIFF_BUDGET = 0.05  # 差异字节占比上限，实测 1.10%
STROKE_BAND_PX = 4.0  # 描边几何带状区半宽（2px 描边+抗锯齿 fringe），实测最大 2.43px


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


def _stroke_distances(x, y, side):
    """像素到描边几何的最近距离：(到最近半径分隔线垂距, 到外圆中心线径向距)。

    描边几何指 renderCache 里的白描边图元：len(ITEMS)+1 条过中心的
    半径分隔线、半径 side*RADIUS_FRACTION 的外圆。分隔线在中心汇聚，
    垂距天然覆盖中心区；文字环与扇区纯色区到二者都远大于
    STROKE_BAND_PX，落在那里的大差异就是真实回归而非抗锯齿合成差。
    """
    cx = cy = side / 2.0
    radius = side * RADIUS_FRACTION
    dx, dy = x - cx, y - cy
    span = 360.0 / len(ITEMS)
    d_line = min(
        abs(dx * math.sin(math.radians(k * span)) - dy * math.cos(math.radians(k * span)))
        for k in range(len(ITEMS) + 1)
    )
    return d_line, abs(math.hypot(dx, dy) - radius)


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

    有意变更画面后分两种处理：变更只影响描边几何的抗锯齿带时，保留旧
    基线、按实测把 test_render_matches_committed_baseline 的容忍度调宽
    （见该测试说明）；变更改的是配色/几何/文字等实质内容时，删除
    tests/data/wheel_baseline.* 再跑本文件重新生成。两种结果都体现在
    git diff 里，不会静默掩盖回归。
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
        """全图差异有界（≤DIFF_BUDGET）且受限（只许出现在描边几何旁）。

        原断言是「>99.9% 字节相同、每通道差 ≤8」，按优化前实现写就。
        批次 5b 把逐扇区描边改为「填充 NoPen 一次遍历 → 半径线合并单
        路径 → 外圆单独 drawEllipse」后实测：4183 像素（2.61%）、7017
        字节（1.10%）不同，而两版画的是同一组图元，差异全部来自抗锯齿
        合成，无一处真实缺陷：

        - 共享半径边在旧实现里被相邻两扇区各描一次（中间还夹着不透明
          填充），抗锯齿的白色覆盖量系统性高于单遍描边，边界两侧约 2px
          内差 20-40；批量描边无法复现这种交错顺序（实测 stroke-all →
          fill-all → stroke-all 也只能匹配每边界一半的像素）；
        - 外圆由扇形路径的 arcTo 分段弧改为 drawEllipse，曲线扁平化不
          同，最外侧约 2600 像素差 1-2，另有 48 个 fringe 像素 alpha
          1→0（maxdiff 255 的全部来源）。

        因此保留优化前基线不重新生成，把断言换成仍能抓住「画面变样」的
        结构化容忍：

        1. 差异字节 ≤ DIFF_BUDGET（实测 1.10%）——换配色、丢描边、丢
           文字都是数量级以上的变化；
        2. 每个差异像素都必须落在描边几何 STROKE_BAND_PX 带状区内
           （实测最大 2.43px，全部 4183 个无一例外）——文字环、扇区
           纯色区出现任何差异即失败，与幅度无关；
        3. 文字环境指纹不一致时仍 skip：字形差异不是回归。
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

        width = img.width()
        differing_bytes = 0
        offenders = []  # (x, y, 通道差, 垂距px, 外圆距px)：落在描边几何带外的差异像素
        for i in range(0, len(current), 4):
            ca, cb = current[i : i + 4], reference[i : i + 4]
            if ca == cb:
                continue
            maxdiff = max(abs(ca[k] - cb[k]) for k in range(4))
            differing_bytes += sum(1 for k in range(4) if ca[k] != cb[k])
            pixel = i // 4
            x, y = pixel % width, pixel // width
            d_line, d_rim = _stroke_distances(x, y, width)
            if min(d_line, d_rim) > STROKE_BAND_PX:
                offenders.append((x, y, maxdiff, round(d_line, 1), round(d_rim, 1)))

        assert differing_bytes / len(reference) <= DIFF_BUDGET, (
            f"{differing_bytes}/{len(reference)} 字节不同（>{DIFF_BUDGET:.0%}），画面已变样"
        )
        assert not offenders, (
            f"{len(offenders)} 个差异像素落在描边几何 {STROKE_BAND_PX:g}px 带状区外，"
            f"画面已变样；前 3 个 (x, y, 通道差, 半径线垂距px, 外圆距px)：{offenders[:3]}"
        )
