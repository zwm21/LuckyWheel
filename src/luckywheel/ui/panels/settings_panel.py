"""设置面板：界面字体、转盘字体、背景主题与文字阴影控件。

字体与主题的**应用**也归这里：它们都只服务"用户改设置"这一件事，
且都通过 window 落到全局（QApplication.setFont / ui_theme.apply_theme）。

控件在 initUI 里创建，而 loadData 先于 initUI 执行，因此这里的
初值直接读窗口状态即可，不需要额外回填。
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFontComboBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QWidget,
)

from luckywheel.ui import theme as ui_theme
from luckywheel.ui.panels.base import Panel

# 主题下拉框条目与 window.theme 的对应关系（顺序即索引）
THEME_NAMES = ["light", "dark", "system"]
THEME_LABELS = ["浅色", "深色", "跟随系统"]


class SettingsPanel(Panel):
    def __init__(self, window, parent=None):
        super().__init__(window, parent)

        # --- 界面字体 ---
        self.ui_font_layout = QHBoxLayout()
        self.ui_font_layout.addWidget(QLabel("界面字体:"))
        self.ui_font_combo = QFontComboBox()
        self.ui_font_combo.setCurrentFont(QFont(window.ui_font_family))
        self.ui_font_combo.currentFontChanged.connect(self.onUIFontChanged)
        self.ui_font_layout.addWidget(self.ui_font_combo, 1)
        self.ui_font_layout.addWidget(QLabel("大小:"))
        self.ui_font_size_spin = QSpinBox()
        self.ui_font_size_spin.setRange(1, 72)
        self.ui_font_size_spin.setValue(window.ui_font_size)
        self.ui_font_size_spin.setFixedWidth(42)
        self.ui_font_size_spin.valueChanged.connect(self.onUIFontSizeChanged)
        self.ui_font_layout.addWidget(self.ui_font_size_spin)

        # --- 转盘字体 ---
        self.wheel_font_layout = QHBoxLayout()
        self.wheel_font_layout.addWidget(QLabel("转盘字体:"))
        self.wheel_font_combo = QFontComboBox()
        self.wheel_font_combo.setCurrentFont(QFont(window.wheel_font_family))
        self.wheel_font_combo.currentFontChanged.connect(self.onWheelFontChanged)
        self.wheel_font_layout.addWidget(self.wheel_font_combo, 1)
        self.wheel_font_layout.addWidget(QLabel("大小:"))
        self.wheel_font_size_spin = QSpinBox()
        self.wheel_font_size_spin.setRange(0, 72)
        self.wheel_font_size_spin.setSpecialValueText("自动")  # 0 = 按扇区自适应
        self.wheel_font_size_spin.setValue(window.wheel_font_size)
        self.wheel_font_size_spin.setFixedWidth(42)
        self.wheel_font_size_spin.valueChanged.connect(self.onWheelFontSizeChanged)
        self.wheel_font_layout.addWidget(self.wheel_font_size_spin)

        # --- 背景主题 + 文字阴影 ---
        self.theme_layout = QHBoxLayout()
        self.theme_layout.addWidget(QLabel("背景主题:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEME_LABELS)
        self.theme_combo.setCurrentIndex(THEME_NAMES.index(window.theme))
        self.theme_combo.setFixedWidth(100)
        self.theme_combo.currentIndexChanged.connect(self.onThemeChanged)
        self.theme_layout.addWidget(self.theme_combo)
        self.theme_layout.addStretch(1)
        self.shadow_checkbox = QCheckBox("文字阴影")
        self.shadow_checkbox.setChecked(window.shadow_enabled)
        self.shadow_checkbox.stateChanged.connect(self.onShadowToggled)
        self.theme_layout.addWidget(self.shadow_checkbox)

    # ---- 字体：改状态 → 应用 → 落盘 ----
    def onUIFontChanged(self, font):
        self.window.ui_font_family = font.family()
        self.applyUIFont()
        self.save()

    def onUIFontSizeChanged(self, size):
        self.window.ui_font_size = size
        self.applyUIFont()
        self.save()

    def onWheelFontChanged(self, font):
        self.window.wheel_font_family = font.family()
        self.applyWheelFont()
        self.save()

    def onWheelFontSizeChanged(self, size):
        self.window.wheel_font_size = size
        self.applyWheelFont()
        self.save()

    def applyUIFont(self):
        """应用界面字体到全局，所有控件统一字号（保留粗体属性）"""
        base_font = QFont(self.window.ui_font_family, self.window.ui_font_size)
        QApplication.setFont(base_font)
        # QApplication.setFont 不会自动刷新已存在控件，这里遍历所有子控件手动同步
        for widget in self.window.findChildren(QWidget):
            # 转盘的字体由 setFontFamily/setFontSize 独立控制，跳过
            if widget is getattr(self.window, "wheel", None):
                continue
            old = widget.font()
            new_font = QFont(base_font)
            new_font.setBold(old.bold())
            new_font.setItalic(old.italic())
            new_font.setUnderline(old.underline())
            widget.setFont(new_font)

    def applyWheelFont(self):
        """应用转盘字体到 WheelWidget"""
        wheel = self.window.wheel
        wheel.setFontFamily(self.window.wheel_font_family)
        wheel.setFontSize(self.window.wheel_font_size)

    # ---- 主题与阴影 ----
    def onThemeChanged(self, index):
        if 0 <= index < len(THEME_NAMES):
            self.window.theme = THEME_NAMES[index]
            self.applyTheme()
            self.save()

    def onShadowToggled(self, state):
        enabled = self.shadow_checkbox.isChecked()
        self.window.shadow_enabled = enabled
        self.window.wheel.setShadowEnabled(enabled)
        self.save()

    def onSystemThemeChanged(self):
        if self.window.theme == "system":
            self.applyTheme()

    def applyTheme(self):
        """浅色=显式浅色调色板 / 深色=暗色调色板 / 跟随系统=检测。

        样式与调色板收敛在 ui.theme（颜色 token + 单份 QSS 模板）；
        本方法只负责解析主题名并把窗口交给它。注意列表类控件不设 QSS，
        见 ui/theme.py 模块 docstring 的滚动条约束。
        """
        window = self.window
        dark = window.theme == "dark" or (window.theme == "system" and self._isSystemDark())
        ui_theme.apply_theme(window, dark)
        self._initLowerAreaColors(is_dark=dark)

    def _isSystemDark(self):
        return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark

    def _initLowerAreaColors(self, is_dark):
        """为抽出项目列表及其视口显式设置调色板，解决深层嵌套时调色板不传播的问题。

        Args:
            is_dark: True=深色主题，False=浅色主题
        """
        try:
            palette = ui_theme.dark_palette() if is_dark else ui_theme.light_palette()
        except Exception:
            return  # 调色板构造失败，静默退出

        widgets = []
        try:
            if hasattr(self.window, "drawn_list_widget") and (
                self.window.drawn_list_widget is not None
            ):
                widgets.append(self.window.drawn_list_widget)
        except (RuntimeError, AttributeError):
            pass
        try:
            if hasattr(self.window, "list_widget") and self.window.list_widget is not None:
                widgets.append(self.window.list_widget)
        except (RuntimeError, AttributeError):
            pass

        for w in widgets:
            try:
                w.setPalette(palette)
                vp = w.viewport()
                if vp is not None:
                    vp.setPalette(palette)
                    vp.setAutoFillBackground(True)
            except (RuntimeError, AttributeError):
                continue
