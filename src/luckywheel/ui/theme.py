"""主题：明暗调色板 + 颜色 token + 单份 QSS 模板。

旧实现在 _applyTheme 里有两个近乎重复的分支，各自拼一整套 QSS 字符串，
改一处颜色要同时改两处，极易漂移。现在收敛为「每种主题一份颜色 token 字典
+ 一份模板」，新主题只需加字典条目。

有一条必须保留的约束（commit b34d41d 的教训，tests/gui/test_theme.py 有回归）：

    **不要给带滚动条的控件（QListWidget 等）单独设 QSS。**

一旦设了，该控件会切到 QStyleSheetStyle 渲染，滚动条脱离 Fusion + palette，
浅色主题下会出现深色滚动条。因此本模块的样式只作用于 QFrame 卡片与
QLabel；列表类控件一律交给调色板，样式模板只为这几类角色服务。
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


def relative_luminance(color):
    """WCAG 相对亮度：sRGB 线性化后按 Rec.709 权重加权，范围 [0, 1]。"""
    def channel(value):
        c = value / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def contrast_text_color(background):
    """按背景相对亮度选择黑/白文字，保证可读性。"""
    return Qt.GlobalColor.white if relative_luminance(background) < 0.5 else Qt.GlobalColor.black


def dark_palette():
    """深色调色板（不对通用控件设 QSS，保证深浅主题控件形态一致）。"""
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window,          QColor(53, 53, 53))
    p.setColor(QPalette.ColorRole.WindowText,      QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.Base,            QColor(35, 35, 35))
    p.setColor(QPalette.ColorRole.AlternateBase,   QColor(53, 53, 53))
    p.setColor(QPalette.ColorRole.ToolTipBase,     QColor(25, 25, 25))
    p.setColor(QPalette.ColorRole.ToolTipText,     QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.Text,            QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.Button,          QColor(53, 53, 53))
    p.setColor(QPalette.ColorRole.ButtonText,      QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.BrightText,      QColor(255, 0, 0))
    p.setColor(QPalette.ColorRole.Link,            QColor(42, 130, 218))
    p.setColor(QPalette.ColorRole.Highlight,       QColor(42, 130, 218))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(127, 127, 127))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,       QColor(127, 127, 127))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(127, 127, 127))
    return p


def light_palette():
    """显式浅色调色板，不依赖系统当前主题。"""
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window,          QColor(240, 240, 240))
    p.setColor(QPalette.ColorRole.WindowText,      QColor(0, 0, 0))
    p.setColor(QPalette.ColorRole.Base,            QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.AlternateBase,   QColor(245, 245, 245))
    p.setColor(QPalette.ColorRole.ToolTipBase,     QColor(255, 255, 220))
    p.setColor(QPalette.ColorRole.ToolTipText,     QColor(0, 0, 0))
    p.setColor(QPalette.ColorRole.Text,            QColor(0, 0, 0))
    p.setColor(QPalette.ColorRole.Button,          QColor(240, 240, 240))
    p.setColor(QPalette.ColorRole.ButtonText,      QColor(0, 0, 0))
    p.setColor(QPalette.ColorRole.BrightText,      QColor(255, 0, 0))
    p.setColor(QPalette.ColorRole.Link,            QColor(42, 130, 218))
    p.setColor(QPalette.ColorRole.Highlight,       QColor(42, 130, 218))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    return p


# 每种主题一份颜色 token；模板在 card_style 中只写一次
_TOKENS = {
    "light": {
        "card_bg": "#f8f7f5",
        "title": "#555",
        "muted": "#666",
        "result": "#333",
        "handle_bg": "#eee",
        "handle_border": "#ccc",
    },
    "dark": {
        "card_bg": "#3D3D3D",
        "title": "#AAA",
        "muted": "#AAA",
        "result": "#E0E0E0",
        "handle_bg": "#4A4A4A",
        "handle_border": "#555",
    },
}

# 单份 QSS 模板：卡片（批量抽取区带 padding，单次抽取区不带，与原观感一致）
_CARD = "QFrame {{ background: {card_bg}; border: none; border-radius: 4px;{padding} }}"
_PADDED = " padding: 4px;"
_LABEL = "color: {color}; background: transparent; border: none;"
_RESULT = "font-weight: bold; color: {result};"
_HANDLE = "QFrame {{ background: {handle_bg}; border: 1px solid {handle_border}; }}"


def card_styles(theme_name):
    """返回 {控件属性名: QSS}；只覆盖卡片与标签，不含滚动条控件。"""
    t = _TOKENS[theme_name]
    return {
        "single_frame": _CARD.format(padding="", **t),
        "batch_frame": _CARD.format(padding=_PADDED, **t),
        "single_title": _LABEL.format(color=t["title"]),
        "batch_title": _LABEL.format(color=t["title"]),
        "batch_log_label": _LABEL.format(color=t["muted"]),
        "result_label": _RESULT.format(**t),
        "handle": _HANDLE.format(**t),
    }


def apply_theme(window, dark):
    """把主题应用到窗口：调色板 + 卡片/标签样式。

    dark: True=深色。widget 尚未创建（initUI 中途调用）时跳过缺失项；
    列表类控件不在此列（见模块 docstring 的滚动条约束）。
    """
    app = QApplication.instance()
    app.setPalette(dark_palette() if dark else light_palette())
    # 不对通用控件设 QSS，交由 Fusion 样式+调色板自动着色，
    # 保证深/浅两种主题下控件形态（边框、圆角、indicator 尺寸）完全一致
    window.setStyleSheet("")
    styles = card_styles("dark" if dark else "light")
    for name in ("single_frame", "single_title", "batch_frame", "batch_title",
                 "batch_log_label", "result_label"):
        widget = getattr(window, name, None)
        if widget is not None:
            widget.setStyleSheet(styles[name])
    for name in ("splitter_handle", "drawn_splitter_handle"):
        widget = getattr(window, name, None)
        if widget is not None:
            widget.setStyleSheet(styles["handle"])
