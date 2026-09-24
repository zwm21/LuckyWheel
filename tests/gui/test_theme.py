"""GUI：主题合并回归。

钉住两条约束：
1. commit b34d41d 的教训——带滚动条的列表控件不得单独设 QSS，
   否则切到 QStyleSheetStyle 渲染，浅色主题下出现深色滚动条；
2. 明暗两个分支收敛为「颜色 token + 单份模板」后，卡片/标签的
   实际样式必须与旧实现的硬编码值逐一相等（观感零变化）。
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from luckywheel.ui import theme as ui_theme


def set_theme(window, name):
    window.theme = name
    window._applyTheme()


class TestNoStylesheetOnScrollableWidgets:
    """回归 b34d41d：滚动条控件不得有 QSS。"""

    def test_lists_have_empty_stylesheet_in_both_themes(self, window):
        for name in ("light", "dark", "system"):
            set_theme(window, name)
            assert window.list_widget.styleSheet() == "", f"{name}: 列表一带了 QSS"
            assert window.drawn_list_widget.styleSheet() == "", f"{name}: 抽出列表带了 QSS"

    def test_styles_do_not_mention_list_widget(self):
        """模板只为卡片与标签服务：任何角色的样式都不该出现在列表属性上。"""
        for name in ("light", "dark"):
            styles = ui_theme.card_styles(name)
            assert set(styles) == {
                "single_frame",
                "batch_frame",
                "single_title",
                "batch_title",
                "batch_log_label",
                "result_label",
            }


class TestCardStyleValues:
    """token 化后的样式与旧硬编码值一致。"""

    def test_light_cards_match_legacy_values(self):
        styles = ui_theme.card_styles("light")
        assert styles["single_frame"] == (
            "QFrame { background: #f8f7f5; border: none; border-radius: 4px; }"
        )
        assert styles["batch_frame"] == (
            "QFrame { background: #f8f7f5; border: none; border-radius: 4px; padding: 4px; }"
        )
        assert styles["single_title"] == "color: #555; background: transparent; border: none;"
        assert styles["batch_log_label"] == "color: #666; background: transparent; border: none;"
        assert styles["result_label"] == "font-weight: bold; color: #333;"

    def test_dark_cards_match_legacy_values(self):
        styles = ui_theme.card_styles("dark")
        assert styles["single_frame"] == (
            "QFrame { background: #3D3D3D; border: none; border-radius: 4px; }"
        )
        assert styles["batch_frame"] == (
            "QFrame { background: #3D3D3D; border: none; border-radius: 4px; padding: 4px; }"
        )
        assert styles["single_title"] == "color: #AAA; background: transparent; border: none;"
        assert styles["batch_log_label"] == "color: #AAA; background: transparent; border: none;"
        assert styles["result_label"] == "font-weight: bold; color: #E0E0E0;"

    def test_themes_differ_only_in_colors(self):
        """模板单份的证据：两套样式的结构骨架相同，只有色值不同。"""
        light = ui_theme.card_styles("light")
        dark = ui_theme.card_styles("dark")
        assert light["single_frame"] != dark["single_frame"]
        assert light["result_label"] != dark["result_label"]

        # 结构一致：去掉色值后逐字符相等
        def strip(s):
            return s.replace("#f8f7f5", "").replace("#3D3D3D", "")

        assert strip(light["single_frame"]) == strip(dark["single_frame"])


class TestAppliedToWindow:
    def test_switch_updates_card_styles(self, window):
        set_theme(window, "light")
        assert "f8f7f5" in window.batch_frame.styleSheet()
        set_theme(window, "dark")
        assert "3D3D3D" in window.batch_frame.styleSheet()
        assert "E0E0E0" in window.result_label.styleSheet()

    def test_apply_theme_tolerates_missing_widgets(self, qtbot):
        """initUI 中途或面板未装配时不得因属性缺失崩溃。"""
        from PyQt6.QtWidgets import QWidget

        bare = QWidget()
        qtbot.addWidget(bare)
        ui_theme.apply_theme(bare, dark=True)
        ui_theme.apply_theme(bare, dark=False)

    def test_theme_combo_switch_end_to_end(self, window):
        window.show()
        for idx, expected in ((0, "light"), (1, "dark")):
            window.theme_combo.setCurrentIndex(idx)
            assert window.theme == expected
        # 深色下卡片为深色，浅色下为浅色
        assert "3D3D3D" in window.batch_frame.styleSheet()
        window.theme_combo.setCurrentIndex(0)
        assert "f8f7f5" in window.batch_frame.styleSheet()


class TestContrastColor:
    """文字对比色：按相对亮度选黑/白（阈值从 lightness>50 改来）。"""

    def test_light_background_gets_dark_text(self):
        assert ui_theme.contrast_text_color(QColor("#FFEAA7")) == Qt.GlobalColor.black

    def test_dark_background_gets_light_text(self):
        assert ui_theme.contrast_text_color(QColor("#333333")) == Qt.GlobalColor.white

    def test_mid_tone_boundary(self):
        # 相对亮度 0.5 对应约 #BCBCBC：暗侧取白字，亮侧取黑字
        assert ui_theme.contrast_text_color(QColor("#BBBBBB")) == Qt.GlobalColor.white
        assert ui_theme.contrast_text_color(QColor("#BDBDBD")) == Qt.GlobalColor.black
