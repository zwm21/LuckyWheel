"""转盘控件：离屏缓存绘制、旋转动画与结果分派。

原为 main.py 内的 WheelWidget，随 UI 分层迁入本模块。SECTOR_COLORS
（扇区调色板）与控件同文件定义：只有 renderCache 用它，搬走后
main.py 仍经 `from luckywheel.ui.wheel import SECTOR_COLORS` 再导出，
旧导入路径不变。

公平性说明：旋转由 core.spin.plan_spin 先等概率选定 winner，动画只负责
把角度演到终点（见 startSpin）；结果经 determineResult 由最终角度反算，
与指针下扇区一致。
"""

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QSizePolicy, QWidget

from luckywheel.core import spin
from luckywheel.core.spin import sector_at
from luckywheel.ui import theme as ui_theme

# 转盘扇区颜色池
SECTOR_COLORS = [
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
]


class WheelWidget(QWidget):
    """转盘绘制与旋转逻辑"""

    spinStarted = pyqtSignal()
    spinFinished = pyqtSignal(int, str)  # 扇区索引, 项目文字

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.rotation = 0.0  # 当前旋转角度（度，规范化到 [0, 360)）
        self.spinning = False
        self.result_text = ""
        self.font_family = "汉仪文黑-65W"
        self.shadow_enabled = True
        self.cached_pixmap = None  # 离屏转盘图像（不含旋转）
        self.cached_size = None  # 上次生成缓存时的逻辑边长 min(w, h)
        self.cached_dpr = None  # 上次生成缓存时的 devicePixelRatio
        self.font_size = 0  # 0=自动，>0=固定像素大小
        self._font_size_cache = {}  # (文本, 字体, 初始字号, 宽限, 高限) -> 实际字号
        self.plan = None  # 当前旋转计划（core.spin.SpinPlan）
        self.animation = None  # 驱动计划时间轴的 QVariantAnimation
        self.speed_scale = 1.0  # 动画时长除数：>1 加速（冒烟/测试用）

        # 允许被窗口压缩到较小尺寸；实际绘制半径由 min(width, height) 决定，
        # 因此始终保持圆形比例不变形
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def setFontSize(self, size):
        """设置转盘文字固定大小，0 为自动"""
        self.font_size = size
        self.cached_pixmap = None
        self.cached_size = None
        self.cached_dpr = None
        self._font_size_cache.clear()
        self.update()

    def _fit_font_size(self, painter, text, init_size, max_w, max_h):
        """二分查找 [min(8, init_size), init_size] 中满足宽高约束的最大字号。

        替代原逐像素递减循环。字号越小文字越小、越放得下，因此满足性是
        单调的，可用二分。找不到满足约束的字号时返回下界，与原循环
        在 pixelSize <= 8 时 break 的语义一致。
        """
        lo, hi = min(8, init_size), init_size
        while lo < hi:
            mid = (lo + hi + 1) // 2
            font = QFont(self.font_family)
            font.setBold(True)
            font.setPixelSize(mid)
            painter.setFont(font)
            fm = painter.fontMetrics()
            if fm.horizontalAdvance(text) <= max_w and fm.height() <= max_h:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def renderCache(self):
        """将当前所有项目绘制到一个固定 pixmap 上（不包含旋转）"""
        if not self.items:
            self.cached_pixmap = None
            self.cached_size = None
            return

        side = min(self.width(), self.height())
        wheel_diameter = side * 0.88
        radius = wheel_diameter / 2.0
        center = QPointF(side / 2.0, side / 2.0)

        # 按 devicePixelRatio 放大画布，高 DPI 屏幕下不做插值放大；
        # 之后所有绘制仍用逻辑像素坐标（painter.scale 负责换算）
        dpr = self.devicePixelRatio()
        if dpr <= 0:
            dpr = 1.0
        pixmap = QPixmap(int(round(side * dpr)), int(round(side * dpr)))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(dpr, dpr)

        # ---------- 绘制扇形（无旋转） ----------
        num = len(self.items)
        sector_span = 360.0 / num
        sector_colors = []  # 每个扇区实际使用的底色，供下方文字对比色查询

        painter.translate(center)
        for i in range(num):
            start_angle = i * sector_span
            span_angle = sector_span
            color = SECTOR_COLORS[i % len(SECTOR_COLORS)]
            sector_colors.append(color)
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(Qt.GlobalColor.white, 2))
            path = QPainterPath()
            path.moveTo(0, 0)
            path.arcTo(QRectF(-radius, -radius, radius * 2, radius * 2), start_angle, span_angle)
            path.lineTo(0, 0)
            painter.drawPath(path)
        painter.resetTransform()

        # ---------- 绘制文字（完全沿用原版逻辑，仅将全局坐标改为未旋转下的固定位置） ----------
        text_radius = radius * 0.62
        num = len(self.items)
        sector_span = 360.0 / num
        # 宽高约束与文本无关，整批文字共用
        max_w = (radius - text_radius) * 0.9
        max_h = text_radius * math.radians(sector_span) * 0.7

        for i, item in enumerate(self.items):
            # 扇区中线角度（未旋转）
            mid_angle_deg = i * sector_span + sector_span / 2.0
            mid_angle_rad = math.radians(mid_angle_deg)

            lx = text_radius * math.cos(mid_angle_rad)
            ly = text_radius * math.sin(mid_angle_rad)

            # 动态字体大小（与原版语义相同，见 _fit_font_size）
            font = QFont(self.font_family)
            font.setBold(True)
            if self.font_size > 0:
                init_size = self.font_size
            else:
                init_size = max(10, int(radius * 0.18))
            # 重复文本复用同一字号：真实数据重复率约四成，二分查找只需为
            # 每个唯一文本做一次
            cache_key = (item, self.font_family, init_size, max_w, max_h)
            size = self._font_size_cache.get(cache_key)
            if size is None:
                size = self._fit_font_size(painter, item, init_size, max_w, max_h)
                self._font_size_cache[cache_key] = size
            font.setPixelSize(size)
            painter.setFont(font)
            fm = painter.fontMetrics()

            text_w = fm.horizontalAdvance(item)
            text_h = fm.height()

            # 文字在 pixmap 中的位置（center 是 pixmap 中心，与 widget 中心相同计算方式）
            painter.save()
            painter.translate(center.x() + lx, center.y() + ly)
            painter.rotate(mid_angle_deg)  # 注意此处直接使用 mid_angle_deg，不再加 rotation

            rect = QRectF(-text_w / 2, -text_h / 2, text_w, text_h)

            # 对比色取文字实际所在扇区的底色：arcTo 的正向扫掠与
            # (cosθ, sinθ) 参数化方向相反，文字 i 落在扇区 num-1-i 上，
            # 而非 SECTOR_COLORS[i]。调色板全为亮色时取错也不可见。
            text_color = ui_theme.contrast_text_color(sector_colors[num - 1 - i])
            if self.shadow_enabled:
                painter.setPen(QColor(0, 0, 0, 120))
                painter.drawText(rect.translated(1, 1), Qt.AlignmentFlag.AlignCenter, item)
            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, item)

            painter.restore()

        painter.end()
        self.cached_pixmap = pixmap
        self.cached_size = side
        self.cached_dpr = dpr

    def setShadowEnabled(self, enabled):
        self.shadow_enabled = enabled
        self.cached_pixmap = None
        self.cached_size = None
        self.cached_dpr = None
        self.update()

    def setFontFamily(self, family):
        """设置转盘文字的字体家族"""
        self.font_family = family
        self.cached_pixmap = None
        self.cached_size = None
        self.cached_dpr = None
        self._font_size_cache.clear()  # 不同字体的度量不同，缓存不得沿用
        self.update()

    def setItems(self, items):
        """设置转盘项目"""
        self.stopSpin()
        self.items = items
        # 注意：此处不再把 rotation 归零。旋转角是绘制相位，与项目列表
        # 无关；换列表时保留当前角度可避免视觉上的跳变，也让 setItems
        # 不会被误用作"重置转盘"的入口。
        self.cached_pixmap = None
        self.cached_size = None
        self.cached_dpr = None
        self._font_size_cache.clear()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 绘制几何只取决于 min(w, h)：未变化时缓存仍然有效，单维拉伸
        # 不再触发重绘（拖动窗口边缘时尤为明显）
        side = min(self.width(), self.height())
        if self.cached_size is not None and side != self.cached_size:
            self.cached_pixmap = None
            self.cached_size = None
            self.cached_dpr = None
            self.update()

    def startSpin(self, initial_velocity=None):
        """开始旋转：先由 core.plan_spin 定好结果，再把动画演到终点。

        公平性由 plan_spin 的 winner 抽取保证，与浮点物理脱钩；
        initial_velocity 仅为兼容旧签名保留，不再影响结果。
        """
        if self.spinning or len(self.items) == 0:
            return
        self.plan = spin.plan_spin(len(self.items), self.rotation, random)
        animation = QVariantAnimation(self)
        animation.setDuration(int(self.plan.duration * 1000.0 / max(self.speed_scale, 0.01)))
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.valueChanged.connect(self._onAnimationValue)
        animation.finished.connect(self._onAnimationFinished)
        self.animation = animation
        self.spinning = True
        animation.start()
        self.spinStarted.emit()

    def _onAnimationValue(self, progress):
        """动画推进：角度取自 SpinPlan 的缓动曲线，帧率无关。"""
        if self.plan is None:
            return
        self.rotation = self.plan.rotation_at(progress * self.plan.duration)
        self.update()

    def _onAnimationFinished(self):
        if self.plan is None:
            self.spinning = False
            return
        self.rotation = (self.plan.start_angle + self.plan.total_rotation) % 360.0
        self.spinning = False
        self.animation = None
        self.update()
        self.determineResult()

    def stopSpin(self):
        """立即停止当前旋转（不产生结果）。"""
        if self.animation is not None:
            self.animation.stop()
            self.animation = None
        self.plan = None
        self.spinning = False
        self.update()

    def determineResult(self):
        """根据最终角度反算指针所指扇区（旧公式，逐点保持一致）。"""
        if len(self.items) == 0:
            return
        sector_index = sector_at(self.rotation, len(self.items))
        self.result_text = self.items[sector_index]
        self.spinFinished.emit(sector_index, self.result_text)

    def paintEvent(self, event):
        """使用离屏缓存绘制，大幅提升大量项目时的旋转性能"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())

        if not self.items:
            painter.setPen(QPen(Qt.GlobalColor.black, 1))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "请添加项目")
            return

        # 需要重建缓存的情况：缓存缺失、边长变化，或窗口被移到不同
        # devicePixelRatio 的屏幕上
        if (
            self.cached_pixmap is None
            or self.cached_size != side
            or self.cached_dpr != self.devicePixelRatio()
        ):
            self.renderCache()

        if self.cached_pixmap is None:
            return

        # 在 widget 中心贴上旋转后的缓存图
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        # 将缓存图中心对齐到 widget 中心
        pixmap_center = QPointF(side / 2.0, side / 2.0)

        painter.save()
        painter.translate(center)
        painter.rotate(self.rotation)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(-pixmap_center, self.cached_pixmap)
        painter.restore()

        # ---------- 绘制固定的中心装饰和指针 ----------
        radius = side * 0.44  # 简便计算，也可用 wheel_diameter/2
        # 中心圆
        painter.save()
        painter.translate(center)
        painter.setBrush(QBrush(QColor("#333333")))
        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        painter.drawEllipse(QPointF(0, 0), radius * 0.15, radius * 0.15)
        painter.setBrush(QBrush(QColor("#555555")))
        painter.drawEllipse(QPointF(0, 0), radius * 0.1, radius * 0.1)
        painter.setPen(QPen(Qt.GlobalColor.white, 1))
        font = QFont(self.font_family)
        font.setBold(True)
        font.setPixelSize(int(radius * 0.08))
        painter.setFont(font)
        painter.drawText(
            QRectF(-radius * 0.1, -radius * 0.1, radius * 0.2, radius * 0.2),
            Qt.AlignmentFlag.AlignCenter,
            "GO",
        )
        painter.restore()

        # 指针
        painter.save()
        wheel_radius = min(self.width(), self.height()) * 0.44
        pointer_tip = QPointF(center.x(), center.y() - wheel_radius + 5)
        pointer_size = 20
        pointer = QPolygonF(
            [
                pointer_tip,
                QPointF(pointer_tip.x() - pointer_size / 2, pointer_tip.y() - pointer_size),
                QPointF(pointer_tip.x() + pointer_size / 2, pointer_tip.y() - pointer_size),
            ]
        )
        painter.setBrush(QBrush(QColor("#FF0000")))
        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        painter.drawPolygon(pointer)
        painter.restore()

    def mousePressEvent(self, event):
        """点击中心圆触发旋转"""
        if self.spinning:
            return
        side = min(self.width(), self.height())
        radius = side * 0.88 / 2.0
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        click_pos = event.position()
        dist = math.hypot(click_pos.x() - center.x(), click_pos.y() - center.y())
        if dist <= radius * 0.15:
            self.startSpin()
        else:
            super().mousePressEvent(event)
