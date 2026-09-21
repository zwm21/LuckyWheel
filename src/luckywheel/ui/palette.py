"""扇区调色板：转盘默认底色池与取色辅助。

单独成模块的理由：这个 tuple 是同一进程里所有窗口与 `from ... import
SECTOR_COLORS` 的导入方共享的默认池。用 tuple 而非 list，调用方只能
取副本（random.sample）而不能原地改动它。

转盘控件从本模块导入并再导出 SECTOR_COLORS，旧导入路径
`luckywheel.ui.wheel` 保持不变；文字对比色在 ui.theme。
"""

from PyQt6.QtGui import QColor

# 转盘扇区颜色池（默认值）。用 tuple 而非 list：窗口启动时只会取一份
# 副本去随机化（见 WheelWidget.setSectorColors），不会原地 shuffle 这个
# 模块级对象——后者会连带影响同一进程里的其他窗口与所有导入方。
SECTOR_COLORS = (
    QColor("#FF6B6B"),
    QColor("#4ECDC4"),
    QColor("#45B7D1"),
    QColor("#96CEB4"),
    QColor("#FFEAA7"),
    QColor("#DDA0DD"),
    QColor("#98D8C8"),
    QColor("#F7DC6F"),
    QColor("#BB8FCE"),
    QColor("#85C1E9"),
    QColor("#F8C471"),
    QColor("#82E0AA"),
    QColor("#F1948A"),
    QColor("#85929E"),
    QColor("#AED6F1"),
    QColor("#E8DAEF"),
    QColor("#A3E4D7"),
    QColor("#FAD7A0"),
    QColor("#D5F5E3"),
    QColor("#F9E79F"),
    QColor("#ABEBC6"),
    # 新增颜色
    QColor("#E74C3C"),
    QColor("#3498DB"),
    QColor("#2ECC71"),
    QColor("#F39C12"),
    QColor("#9B59B6"),
    QColor("#1ABC9C"),
    QColor("#E67E22"),
    QColor("#C0392B"),
    QColor("#16A085"),
    QColor("#8E44AD"),
    QColor("#D35400"),
)
