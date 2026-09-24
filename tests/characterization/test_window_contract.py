"""MainWindow 公共契约快照：外部消费者依赖的属性与方法名。

批次 4 要把 initUI 里上千行的控件组装拆进各面板。拆分最容易犯的错
不是编译失败，而是静默丢契约：verify_gui.py、tests/gui/ 下的 6 个
文件、tests/characterization/ 以及 scripts/ 都按名字访问
MainWindow（window.wheel、window.list_widget、window.startBatchSpin()
……）。本文件把这份契约钉成断言——拆分后若漏转发某个名字，这里立刻
红，而不是等到用户点界面才发现。

另覆盖两条"按对象/按调色板"的隐式契约：

- applyUIFont 必须跳过转盘本体（转盘字号由 WheelWidget.setFontSize
  独立控制），且保留各控件原有的粗体/斜体/下划线属性；
- _applyTheme 之后两个列表及其 viewport 的调色板必须与 ui_theme 的
  明暗调色板一致——深层嵌套下调色板不会自动传播，故
  _initLowerAreaColors 要显式补设（否则列表底色停留在系统默认）。
"""

import pytest
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QWidget

from luckywheel.ui import theme as ui_theme
from luckywheel.ui import wheel as _wheel_module

# 默认配色池在模块导入期（任何窗口构造之前）的快照。
# test_constructing_window_does_not_mutate_default_pool 用它检测原地改动：
# 快照必须早于窗口构造，否则比的是改动后的自己，断言永远为真。
# tuple 本身拦不住对其中 QColor 逐个 setRgb，故按颜色名比对。
POOL_AT_IMPORT = tuple(c.name() for c in _wheel_module.SECTOR_COLORS)

# 外部消费者（verify_gui.py / tests/gui/* / tests/characterization/*）
# 直接按名字访问的契约面。属性与方法分开列，失败信息更好读。
CONTRACT_ATTRIBUTES = (
    "group_combo",
    "list_widget",
    "drawn_list_widget",
    "result_label",
    "batch_spinbox",
    "btn_stop_batch",
    "btn_stop_single",
    "batch_remaining",
    "theme_combo",
    "batch_frame",
    "single_frame",
    "wheel",
    "groups",
    "current_group_index",
    "data_file",
)

CONTRACT_METHODS = (
    "startBatchSpin",
    "stopBatchSpin",
    "stopSingleSpin",
    "flushSave",
    "saveData",
    "loadData",
    "applyUIFont",
    "applyWheelFont",
    "updateDrawnList",
    "updateWheelFromCurrentGroup",
)


def set_theme(window, name):
    window.theme = name
    window._applyTheme()


class TestContractSurface:
    """拆分面板后不得丢名字。"""

    @pytest.mark.parametrize("name", CONTRACT_ATTRIBUTES)
    def test_attribute_exists(self, window, name):
        assert hasattr(window, name), f"MainWindow 丢失契约属性 {name!r}"

    @pytest.mark.parametrize("name", CONTRACT_METHODS)
    def test_method_is_callable(self, window, name):
        assert callable(getattr(window, name, None)), f"MainWindow 丢失契约方法 {name!r}"

    def test_wheel_is_child_of_window(self, window):
        """applyUIFont 用 findChildren 递归同步字体，转盘必须是窗口后代
        才能被遍历到、再按 `widget is self.wheel` 跳过。"""
        assert window.wheel in window.findChildren(QWidget)

    def test_batch_remaining_starts_zero(self, window):
        assert window.batch_remaining == 0


class TestApplyUIFontContract:
    def test_all_widgets_except_wheel_get_font(self, window, monkeypatch):
        """全局字体同步覆盖每个子控件，唯独转盘本体被跳过。"""
        # 取一个必然存在的字体族（控件当前实际解析到的），避免依赖
        # QFontDatabase——headless/容器环境可能连字体数据库都是空的
        family = window.list_widget.font().family()
        size = 23
        window.ui_font_family = family
        window.ui_font_size = size

        # 转盘的字体由 setFontFamily/setFontSize 独立控制：applyUIFont
        # 不得对它调用 setFont（否则用户单独调小的转盘字号会被全局字号覆盖）
        wheel_font_calls = []
        monkeypatch.setattr(window.wheel, "setFont", wheel_font_calls.append)
        window.applyUIFont()
        assert wheel_font_calls == [], "applyUIFont 动了转盘的字体"

        covered = []
        for widget in window.findChildren(QWidget):
            if widget is window.wheel:
                continue
            covered.append(widget)
            assert widget.font().pointSize() == size, (
                f"{type(widget).__name__} 未同步字号 {widget.font().pointSize()}"
            )
            assert widget.font().family() == family, (
                f"{type(widget).__name__} 未同步字体族 {widget.font().family()!r}"
            )
        assert covered, "一个控件都没遍历到，断言形同虚设"

    def test_bold_and_italic_preserved(self, window):
        """统一字号只改字号，粗体/斜体/下划线逐个保留。"""
        window.ui_font_family = window.list_widget.font().family()
        window.ui_font_size = 19
        before = {
            w: (w.font().bold(), w.font().italic(), w.font().underline())
            for w in window.findChildren(QWidget)
        }
        window.applyUIFont()
        for w, flags in before.items():
            after = w.font()
            assert (after.bold(), after.italic(), after.underline()) == flags, (
                f"{type(w).__name__} 丢失字体属性 (bold/italic/underline)"
            )


class TestSectorPaletteContract:
    """扇区配色：默认池不可变，随机化只发生在窗口自己的副本上。

    旧实现 MainWindow.__init__ 里 `random.shuffle(SECTOR_COLORS)` 直接
    打乱模块级 list——那是同一进程里所有窗口、所有
    `from ... import SECTOR_COLORS` 的导入方共享的对象。第二个窗口
    （或测试里新构造的 WheelWidget）拿到的就是别人洗过的牌，且无法
    还原。现在默认池是 tuple，窗口把 random.sample 的副本经
    setSectorColors 注入转盘。
    """

    def test_default_pool_is_immutable(self):
        from luckywheel.ui.wheel import SECTOR_COLORS

        assert isinstance(SECTOR_COLORS, tuple)
        assert not hasattr(SECTOR_COLORS, "shuffle")
        assert not hasattr(SECTOR_COLORS, "append")

    def test_constructing_window_does_not_mutate_default_pool(self, window):
        from luckywheel.ui import wheel as wheel_module

        now = tuple(c.name() for c in wheel_module.SECTOR_COLORS)
        assert now == POOL_AT_IMPORT, "默认池被就地改动了"

    def test_wheel_gets_a_permutation_of_the_pool(self, window):
        from luckywheel.ui.wheel import SECTOR_COLORS

        by_name = lambda colors: sorted(c.name() for c in colors)  # noqa: E731
        assert by_name(window.wheel.sector_colors) == by_name(SECTOR_COLORS)
        # 随机化确实发生了（同一顺序的概率约 1/32!）
        assert [c.name() for c in window.wheel.sector_colors] != [c.name() for c in SECTOR_COLORS]

    def test_empty_injection_keeps_current_palette(self, qtbot):
        from luckywheel.ui.wheel import WheelWidget

        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        before = list(wheel.sector_colors)
        wheel.setSectorColors([])
        assert wheel.sector_colors == before

    def test_injection_replaces_and_copies(self, qtbot):
        from PyQt6.QtGui import QColor

        from luckywheel.ui.wheel import WheelWidget

        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        source = [QColor("#123456"), QColor("#654321")]
        wheel.setSectorColors(source)
        assert wheel.sector_colors == source
        source.append(QColor("#000000"))
        assert len(wheel.sector_colors) == 2, "注入后仍持有调用方 list 的引用"


class TestListPaletteContract:
    @pytest.mark.parametrize(
        ("theme_name", "expected"),
        [("light", ui_theme.light_palette()), ("dark", ui_theme.dark_palette())],
    )
    def test_lists_follow_theme_palette(self, window, theme_name, expected):
        """列表及 viewport 的 Base 色必须等于主题调色板（否则底色留系统默认）。"""
        set_theme(window, theme_name)
        base = QPalette.ColorRole.Base
        for w in (window.list_widget, window.drawn_list_widget):
            assert w.palette().color(base) == expected.color(base), f"{w} 调色板未随主题切换"
            vp = w.viewport()
            assert vp is not None
            assert vp.palette().color(base) == expected.color(base), f"{w}.viewport() 调色板未切换"
            assert vp.autoFillBackground(), f"{w}.viewport() 未开 autoFillBackground"

    def test_switch_back_and_forth(self, window):
        """来回切换后列表调色板跟着变，不停留在上一次的主题。"""
        base = QPalette.ColorRole.Base
        set_theme(window, "dark")
        assert window.list_widget.palette().color(base) == ui_theme.dark_palette().color(base)
        set_theme(window, "light")
        assert window.list_widget.palette().color(base) == ui_theme.light_palette().color(base)
