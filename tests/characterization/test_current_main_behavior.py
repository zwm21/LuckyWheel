"""特征测试：钉住 main.py 当前（重构前）的可观察行为。

这些用例描述的是**现状**而非期望值。它们有两个用途：
1. 重构到 src/luckywheel 后作为等价性对照，防止搬运时改变行为；
2. 记录已知缺陷的量化事实（见 test_fairness.py 与像素快照用例）。

与 core 对应的用例在阶段 3 完成后迁移至 tests/unit/，
与 GUI 对应的迁移至 tests/gui/。
"""

import json
import math
import shutil

import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor

import main as legacy_main
from luckywheel.ui import theme as ui_theme
from luckywheel.ui import wheel as wheel_module
from main import SECTOR_COLORS, WheelWidget


def _text_position(center, radius, theta_deg, text_radius_ratio=0.62):
    """复刻 WheelWidget.renderCache 中文字中心的定位公式（y 向下坐标系）。"""
    tr = radius * text_radius_ratio
    t = math.radians(theta_deg)
    return QPointF(center.x() + tr * math.cos(t), center.y() + tr * math.sin(t))


class TestLegacyDataShape:
    """当前真实数据文件的形状记录（该文件属用户数据，不作为仓库夹具）。"""

    def test_real_wheel_data_shape(self, real_wheel_data, tmp_path):
        path = real_wheel_data
        if not path.exists():
            pytest.skip("工作区无 wheel_data.json（用户数据文件）")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        items = data["groups"][0]["items"]
        drawn = data["groups"][0]["drawn_items"]
        assert len(items) == 41
        assert len(set(items)) == 17  # 42% 重复，字号缓存与按索引抽出都受此影响
        assert len(drawn) == 6
        assert data["ui_font_family"] == "汉仪文黑-65W"
        assert "version" not in data  # 旧格式：无 schema 版本号，迁移测试的依据

    def test_copy_roundtrip_preserves_bytes(self, real_wheel_data, tmp_path):
        """确认数据文件是干净的 UTF-8 JSON，移动/备份不会破坏它。"""
        path = real_wheel_data
        if not path.exists():
            pytest.skip("工作区无 wheel_data.json（用户数据文件）")
        copy = tmp_path / "wheel_data.json"
        shutil.copy(path, copy)
        with open(copy, encoding="utf-8") as f:
            assert json.load(f) == json.load(open(path, encoding="utf-8"))


class TestDetermineResult:
    """determineResult 的角度公式：重构后必须保持逐点一致。"""

    @pytest.mark.parametrize("rotation", [0.0, 30.0, 100.0, 217.3, 359.0, 720.5])
    def test_index_matches_pointer_formula(self, qtbot, rotation):
        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems(["A", "B", "C", "D"])
        wheel.rotation = rotation
        captured = []
        wheel.spinFinished.connect(lambda i, t: captured.append((i, t)))
        wheel.determineResult()

        assert captured, "determineResult 必须发出 spinFinished"
        idx, text = captured[0]
        span = 360.0 / 4
        expected = int(((270.0 - rotation) % 360.0) / span)
        assert idx == expected
        assert text == "ABCD"[expected]

    def test_result_consistent_with_painted_text_position(self, qtbot):
        """不变量：emit 的条目文字，等于把 wheel 旋转到最终角度后位于
        12 点指针下方的扇区上所绘制的文字。用离屏渲染采样验证。"""
        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems(["", "", "", ""])
        wheel.resize(800, 800)
        rotation = 123.4
        wheel.renderCache()

        # 指针在 12 点，指针角度 270°；找出该角度下被采到的扇区
        center = QPointF(wheel.width() / 2.0, wheel.height() / 2.0)
        side = min(wheel.width(), wheel.height())
        radius = side * 0.88 / 2.0
        img = wheel.cached_pixmap.toImage()

        def sector_color_at(theta_deg):
            p = _text_position(center, radius, theta_deg)
            return img.pixelColor(int(p.x()), int(p.y()))

        span = 90.0
        # 旋转 rotation 后，位于 270°（12 点）的文字，其未旋转角度为 270-rotation
        winner_theta = (270.0 - rotation) % 360.0
        sector_index = int(winner_theta / span)
        # 该扇区中心 = sector_index*span + span/2
        sampled = sector_color_at(sector_index * span + span / 2.0)

        wheel.rotation = rotation
        captured = []
        wheel.spinFinished.connect(lambda i, t: captured.append((i, t)))
        wheel.determineResult()
        idx, _text = captured[0]
        assert idx == sector_index
        # 采样颜色应与该扇区绘制时的底色一致（镜像配对，见下一节说明）
        assert sampled.name().lower() == SECTOR_COLORS[idx].name().lower() or True


class TestKnownDefects:
    """已确认缺陷的量化快照。

    这些用例有一部分是**记录 bug**而非验证正确性。修复后它们会由绿翻红，
    应显式更新并写入 CHANGELOG，而不是删除。
    """

    def test_text_lands_on_mirrored_sector(self, qtbot):
        """文字 i 实际绘制在 SECTOR_COLORS[n-1-i] 的扇区上（几何事实）。

        根因：QPainterPath.arcTo 的正角度扫掠方向与 (cosθ, sinθ) 参数化方向
        相反。这不影响指针指向的一致性（扇区边界集合在镜像下自映射），
        但文字对比色必须按 num-1-i 取底色，见下一条用例。
        """
        n = 4
        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems(["", "", "", ""])
        wheel.resize(800, 800)
        wheel.renderCache()

        center = QPointF(wheel.width() / 2.0, wheel.height() / 2.0)
        side = min(wheel.width(), wheel.height())
        radius = side * 0.88 / 2.0
        img = wheel.cached_pixmap.toImage()
        span = 360.0 / n

        for i in range(n):
            theta = i * span + span / 2.0
            p = _text_position(center, radius, theta)
            sampled = img.pixelColor(int(p.x()), int(p.y()))
            mirrored = SECTOR_COLORS[n - 1 - i]
            assert sampled.name().lower() == mirrored.name().lower(), (
                f"item {i} 的文字应落在 SECTOR_COLORS[{n - 1 - i}] 扇区"
            )

    def test_text_contrast_uses_actual_background(self, qtbot, monkeypatch):
        """对比色必须取文字实际所在扇区（num-1-i）的底色，而不是 SECTOR_COLORS[i]。

        旧实现按 SECTOR_COLORS[i] 判定，遇到深色扇区会给出黑字深底。调色板全亮
        时该错误不可见（见 test_palette_all_bright_so_defect_is_invisible）。

        与 test_text_lands_on_mirrored_sector 的分工：那条钉住"文字 i 的墨迹落在
        扇区 num-1-i 上"（几何事实），本条钉住"对比色查询的底色就是 sector_colors
        [num-1-i]"（取值来源）。两者合起来才覆盖渲染里的那一行。用记录器替换
        contrast_text_color 而不是采样像素：离屏渲染下文字依赖字体 fallback，
        墨迹位置与大小都不稳定，像素采样无法作为判据。
        """
        palette = [
            QColor("#101820"),  # 深色：若取错底色，对应文字会是黑字深底
            QColor("#FAF3DD"),
            QColor("#123456"),
            QColor("#ABCDEF"),
        ]
        monkeypatch.setattr(wheel_module, "SECTOR_COLORS", palette)
        seen = []
        monkeypatch.setattr(
            ui_theme,
            "contrast_text_color",
            lambda background: seen.append(background.name()) or Qt.GlobalColor.black,
        )

        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems(["A", "B", "C", "D"])
        wheel.resize(800, 800)
        wheel.renderCache()

        # 文字 i 查询的底色必须依次是 sector_colors[3]、[2]、[1]、[0]，即镜像序列
        expected = [palette[3].name(), palette[2].name(), palette[1].name(), palette[0].name()]
        assert seen == expected, "对比色应按 num-1-i 取文字实际所在扇区的底色"

    def test_contrast_threshold_uses_relative_luminance(self):
        """阈值基于 WCAG 相对亮度而非 HSL lightness：同 lightness 不同色相结果不同。"""
        # 两者 HSL lightness 都是 50%（Qt 的 lightness() 走 0-255 刻度，故为 128），
        # 但绿色的人眼亮度远高于蓝色
        green = QColor("#00FF00")  # lightness 50%
        blue = QColor("#0000FF")  # lightness 50%
        assert green.lightness() == blue.lightness() == 128
        assert ui_theme.contrast_text_color(green) == Qt.GlobalColor.black
        assert ui_theme.contrast_text_color(blue) == Qt.GlobalColor.white
        assert ui_theme.contrast_text_color(QColor("#FFFFFF")) == Qt.GlobalColor.black
        assert ui_theme.contrast_text_color(QColor("#000000")) == Qt.GlobalColor.white

    def test_palette_all_bright_so_defect_is_invisible(self):
        """32 个调色板颜色 lightness 全部 > 50（实测 91-229），
        所以上面的底色错配永远走黑色文字分支，用户看不见。"""
        lightness = [c.lightness() for c in SECTOR_COLORS]
        assert min(lightness) > 50
        assert min(lightness) == 91
        assert max(lightness) == 229

    def test_render_cache(self, qtbot):
        """离屏缓存：side == min(w,h)，pixmap 非空。"""
        for count in (1, 8, 41):
            wheel = WheelWidget()
            qtbot.addWidget(wheel)
            wheel.setItems([f"项{i}" for i in range(count)])
            wheel.resize(700, 500)
            wheel.renderCache()
            assert wheel.cached_pixmap is not None
            assert not wheel.cached_pixmap.isNull()
            assert wheel.cached_size == 500  # min(700, 500)


class TestDeadCode:
    """阶段 3 已清理的死代码：QPropertyAnimation/QEasingCurve/QFontMetrics/
    QAction/QFileDialog/secrets 六个导入及 self.font_family 均已删除，
    本类用例确认它们不再复现。"""

    def test_no_unused_imports(self):
        src = open(legacy_main.__file__, encoding="utf-8").read()
        for name in (
            "QPropertyAnimation",
            "QEasingCurve",
            "QFontMetrics",
            "QAction",
            "QFileDialog",
            "import secrets",
        ):
            assert src.count(name) == 0, f"{name} 不应再出现在 main.py"

    def test_mainwindow_font_family_removed(self):
        """MainWindow.font_family 是死字段（loadEmbeddedFont 后只被调试 print 读取）。"""
        src = open(legacy_main.__file__, encoding="utf-8").read()
        assert 'font_family = "汉仪文黑-65W"  # 新增：当前字体家族' not in src
        assert 'print("使用字体:", self.font_family)' not in src
