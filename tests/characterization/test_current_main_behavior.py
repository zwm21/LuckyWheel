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
from pathlib import Path

import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor

import luckywheel
import main as legacy_main
from luckywheel.ui import theme as ui_theme
from main import SECTOR_COLORS, WheelWidget

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SRC_DIR = Path(luckywheel.__file__).resolve().parent


def _text_position(center, radius, theta_deg, text_radius_ratio=0.62):
    """复刻 WheelWidget.renderCache 中文字中心的定位公式（y 向下坐标系）。"""
    tr = radius * text_radius_ratio
    t = math.radians(theta_deg)
    return QPointF(center.x() + tr * math.cos(t), center.y() + tr * math.sin(t))


class TestLegacyDataShape:
    """旧格式数据文件的形状约束。

    形状断言对着版本控制内的 tests/data/legacy_v1.json，而不是工作区的
    wheel_data.json——后者是用户运行时数据，程序一存盘就会被改写（新版
    写入 version: 2），拿它当夹具会让用例在正常使用后无端翻红。真实文件
    这里只做与内容无关的可读性检查。
    """

    def test_legacy_fixture_keeps_duplicate_items(self):
        """重复项是旧数据的常态：按索引抽出与字号缓存都建立在这个事实上。"""
        data = json.loads((DATA_DIR / "legacy_v1.json").read_text(encoding="utf-8"))
        items = data["groups"][0]["items"]
        assert len(items) > len(set(items)), "夹具必须保留重复项"
        assert "version" not in data, "旧格式无 schema 版本号，是迁移测试的依据"

    def test_real_data_file_is_readable_json(self, real_wheel_data):
        if not real_wheel_data.exists():
            pytest.skip("工作区无 wheel_data.json（用户数据文件）")
        data = json.loads(real_wheel_data.read_text(encoding="utf-8"))
        assert isinstance(data.get("groups"), list), "数据文件必须含 groups 列表"

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
        # 采样点的底色是镜像扇区的颜色：arcTo 的正向扫掠与 (cosθ, sinθ)
        # 参数化方向相反，故文字位置 i 落在填充下标 n-1-i 的扇区上
        # （n=4/5/8 实测一致，wheel.py 的对比色取色即依赖此式）
        assert sampled.name().lower() == SECTOR_COLORS[4 - 1 - idx].name().lower()


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

        配色经 setSectorColors 注入（模块级 SECTOR_COLORS 已改为不可变 tuple，
        不再被原地 shuffle）。
        """
        palette = [
            QColor("#101820"),  # 深色：若取错底色，对应文字会是黑字深底
            QColor("#FAF3DD"),
            QColor("#123456"),
            QColor("#ABCDEF"),
        ]
        seen = []
        monkeypatch.setattr(
            ui_theme,
            "contrast_text_color",
            lambda background: seen.append(background.name()) or Qt.GlobalColor.black,
        )

        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setSectorColors(palette)
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


class TestEntryDelegation:
    """启动序列只有 app.py 一份，main.py 只做 re-export + 转调。

    缺陷记录（已修复）：app.py 的 create_window 曾写 `from main import
    MainWindow`，只有 cwd 恰好是仓库根时才 import 得到；`python -m
    luckywheel` 换目录或 pip 安装后运行直接 ModuleNotFoundError。
    """

    def test_main_delegates_to_app_main(self):
        import luckywheel.app as app_module

        assert legacy_main.main is app_module.main

    def test_main_has_no_startup_sequence_of_its_own(self):
        """QApplication/Fusion/show/exec 的组装不得在 main.py 重复一份。"""
        src = open(legacy_main.__file__, encoding="utf-8").read()
        for snippet in ("QApplication(", 'setStyle("Fusion")', "MainWindow()", "app.exec()"):
            assert src.count(snippet) == 0, f"main.py 仍自带启动片段 {snippet!r}"

    def test_app_does_not_import_root_main(self):
        import luckywheel.app as app_module

        src = open(app_module.__file__, encoding="utf-8").read()
        assert "from main import" not in src, "app.py 不得依赖根级 main.py"

    def test_app_create_window_uses_package_path(self):
        import luckywheel.app as app_module

        src = open(app_module.__file__, encoding="utf-8").read()
        assert "from luckywheel.ui.main_window import MainWindow" in src


class TestDeadCode:
    """阶段 3 清理掉的六个导入与调试 print 不得复现。

    扫描的是 src/ 整棵树，不是根级 main.py——后者已收缩成十几行的兼容
    wrapper，在它里面找 QPropertyAnimation 永远找不到，断言等于空转。

    与 ruff F401 的分工：F401 只抓「导入了但没用」，这里抓的是「重新导入
    并用起来」——例如有人再把 secrets 用回旋转初速度（语义上是过度工程，
    见 REFACTOR_PLAN_V2 的 M3），或把 QPropertyAnimation 用回动画实现。
    那类回退 ruff 看不见。
    """

    REMOVED_NAMES = (
        "QPropertyAnimation",
        "QEasingCurve",
        "QFontMetrics",
        "QAction",
        "QFileDialog",
        "secrets",
    )

    @staticmethod
    def _import_lines():
        for path in sorted(SRC_DIR.rglob("*.py")):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")):
                    yield path, lineno, stripped

    def test_removed_imports_do_not_return(self):
        """只看 import 行：core/layout.py 的 docstring 里提到 QFontMetrics
        是在说明测量函数的生产实现，属正常引用，不该被误判。"""
        offenders = [
            (path.name, lineno, line, name)
            for path, lineno, line in self._import_lines()
            for name in self.REMOVED_NAMES
            if name in line
        ]
        assert not offenders, f"已清理的导入又回来了: {offenders}"

    def test_no_debug_print_in_src(self):
        """启动/保存路径上的裸 print 会污染打包后的控制台，提示统一走
        ui.bootstrap.notify。"""
        offenders = [
            (path.name, lineno)
            for path in sorted(SRC_DIR.rglob("*.py"))
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if line.strip().startswith("print(")
        ]
        assert not offenders, f"src/ 下出现裸 print: {offenders}"

    def test_mainwindow_has_no_singular_font_family_field(self):
        """字体家族已拆成 ui_font_family / wheel_font_family 两份；
        单数的 self.font_family 是旧死字段（只被调试 print 读取）。"""
        src = (SRC_DIR / "ui" / "main_window.py").read_text(encoding="utf-8")
        assert "self.font_family" not in src
