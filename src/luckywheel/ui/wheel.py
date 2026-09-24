"""转盘控件：离屏缓存绘制、旋转动画与结果分派。

原为 main.py 内的 WheelWidget，随 UI 分层迁入本模块。默认扇区配色池
SECTOR_COLORS 定义在 ui.palette（它是所有实例与导入方共享的默认池），
本模块再导出以兼容 `from luckywheel.ui.wheel import SECTOR_COLORS`；
控件自己持有一份副本 self.sector_colors（启动时由窗口随机化后经
setSectorColors 注入）。

公平性说明：旋转由 core.spin.plan_spin 先等概率选定 winner，动画只负责
把角度演到终点（见 startSpin）；结果经 determineResult 由最终角度反算，
与指针下扇区一致。
"""

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QSizePolicy, QWidget

from luckywheel.core import layout, spin
from luckywheel.core.spin import sector_at
from luckywheel.ui import theme as ui_theme

# 再导出默认配色池，旧导入路径（luckywheel.ui.wheel / main.py）不变
from luckywheel.ui.palette import SECTOR_COLORS  # noqa: F401

# resize 去抖窗口：拖动窗口边缘时 resizeEvent 密集到达，每次同步重建缓存
# 在项目多时要几十毫秒；窗口内先用旧缓存按新旧边长比拉伸兜底（画面短暂
# 模糊，CHANGELOG「未发布」段记录该折衷）
RESIZE_DEBOUNCE_MS = 80


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
        self._font_size_cache = layout.FontSizeCache()
        # 本实例的扇区配色：默认池的一份副本，可被 setSectorColors 整体替换
        self.sector_colors = list(SECTOR_COLORS)
        self.plan = None  # 当前旋转计划（core.spin.SpinPlan）
        self.animation = None  # 驱动计划时间轴的 QVariantAnimation
        self.speed_scale = 1.0  # 动画时长除数：>1 加速（冒烟/测试用）
        # resize 去抖：待生效的新边长（min(w, h)）与到点才真正失效缓存的
        # 单次定时器。窗口内 paintEvent 拉伸旧缓存兜底，见 resizeEvent。
        self._pending_side = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(RESIZE_DEBOUNCE_MS)
        self._resize_timer.timeout.connect(self._onResizeSettled)

        # 允许被窗口压缩到较小尺寸；实际绘制半径由 min(width, height) 决定，
        # 因此始终保持圆形比例不变形
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _invalidate_cache(self):
        """让离屏缓存失效，由下一次 paintEvent 按当前状态重建。

        六个 setter 与 resize 去抖到点都走这里。三项必须一起清：paintEvent
        的 guard 同时比对 pixmap、逻辑边长与 dpr，只清其中一两项会让旧图
        被判为"仍然匹配"而继续使用。
        """
        self.cached_pixmap = None
        self.cached_size = None
        self.cached_dpr = None

    def setFontSize(self, size):
        """设置转盘文字固定大小，0 为自动"""
        self.font_size = size
        self._invalidate_cache()
        self._font_size_cache.clear()
        self.update()

    def _measure(self, painter):
        """返回 (text, px) -> (宽, 高) 的测量闭包，绑定当前字体家族。

        调用方保证 painter 存活；闭包会改动 painter 的字体，renderCache
        在取到字号后会显式重设，故副作用不外泄。
        """

        def measure(text, px):
            font = QFont(self.font_family)
            font.setBold(True)
            font.setPixelSize(px)
            painter.setFont(font)
            fm = painter.fontMetrics()
            return fm.horizontalAdvance(text), fm.height()

        return measure

    def _fit_min_px(self, init_size):
        """字号下界。

        取 min(8, init_size) 而非固定 8：转盘字号 spinbox 下限为 0（自动），
        1~7 是用户可选的固定值，夹到 8 会让「设成 6」失效。
        """
        return min(layout.FONT_MIN_PX, init_size)

    def renderCache(self):
        """将当前所有项目绘制到一个固定 pixmap 上（不包含旋转）"""
        if not self.items:
            self.cached_pixmap = None
            self.cached_size = None
            return

        side = min(self.width(), self.height())
        wheel_diameter = side * layout.WHEEL_DIAMETER_RATIO
        radius = wheel_diameter / 2.0
        center = QPointF(side / 2.0, side / 2.0)

        # 按 devicePixelRatio 放大画布，高 DPI 屏幕下不做插值放大。
        # 注意：QPixmap 设置了 devicePixelRatio 后，其 QPainter 的坐标系
        # 会自动按 dpr 缩放（图元与文字均以设备分辨率渲染），因此此处
        # 绝不能再手动 painter.scale(dpr, dpr)——那会叠加成 dpr² 缩放，
        # 整个转盘被放大并移出画布（dpr=1 时 1²=1 无差别，故难以察觉）。
        dpr = self.devicePixelRatio()
        if dpr <= 0:
            dpr = 1.0
        pixmap = QPixmap(int(round(side * dpr)), int(round(side * dpr)))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ---------- 绘制扇形（无旋转） ----------
        num = len(self.items)
        sector_span = 360.0 / num
        sector_colors = []  # 每个扇区实际使用的底色，供下方文字对比色查询

        painter.save()
        painter.translate(center)
        # 策略 J（R5 微基准结论）：逐个扇区描边占总耗时约 73%，改为三步——
        # 1) 填充全程 NoPen 一次遍历；
        # 2) N+1 条半径分隔线合并为单一路径，只描一次；
        # 3) 外圆单独 drawEllipse 描边。
        # 图元集合不变（同一批填充 + 白 2px 描边），但共享半径边由「描两遍」
        # 变「描一遍」、外圆由 arcTo 分段弧变 drawEllipse，抗锯齿合成结果与
        # 旧实现有可测差异：实测 4183 像素（1.10% 字节）不同，全部落在描边
        # 几何 2.5px 带状区内、无真实缺陷（定量说明见
        # tests/characterization/test_pixel_baseline.py）。
        # 约束：外圆不得 addEllipse 进半径线的同一路径——实测会从 22ms 恶化到
        # 345ms（疑似多子路径合判时栅格化走慢路径），现象稳定复现。
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        for i in range(num):
            start_angle = i * sector_span
            color = self.sector_colors[i % len(self.sector_colors)]
            sector_colors.append(color)
            painter.setBrush(QBrush(color))
            path = QPainterPath()
            path.moveTo(0, 0)
            path.arcTo(QRectF(-radius, -radius, radius * 2, radius * 2), start_angle, sector_span)
            path.lineTo(0, 0)
            painter.drawPath(path)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        separators = QPainterPath()
        for k in range(num + 1):
            angle = math.radians(k * sector_span)
            separators.moveTo(0, 0)
            separators.lineTo(radius * math.cos(angle), radius * math.sin(angle))
        painter.drawPath(separators)
        painter.drawEllipse(QRectF(-radius, -radius, radius * 2, radius * 2))
        painter.restore()

        # ---------- 绘制文字（完全沿用原版逻辑，仅将全局坐标改为未旋转下的固定位置） ----------
        text_radius = radius * layout.TEXT_RADIUS_RATIO
        # 宽高约束与文本无关，整批文字共用（num/sector_span 已在上方算过）
        max_w, max_h = layout.text_box(radius, sector_span)

        measure = self._measure(painter)

        for i, item in enumerate(self.items):
            # 扇区中线角度（未旋转）
            mid_angle_deg = i * sector_span + sector_span / 2.0
            mid_angle_rad = math.radians(mid_angle_deg)

            lx = text_radius * math.cos(mid_angle_rad)
            ly = text_radius * math.sin(mid_angle_rad)

            # 动态字体大小
            font = QFont(self.font_family)
            font.setBold(True)
            if self.font_size > 0:
                init_size = self.font_size
            else:
                init_size = layout.auto_font_start_px(radius)
            # 重复文本复用同一字号：真实数据重复率约四成，二分查找只需为
            # 每个唯一文本做一次。缓存键不含字体家族，由 setFontFamily
            # 清空来保证正确性。
            size = self._font_size_cache.fit(
                item,
                max_w,
                max_h,
                measure,
                start_px=init_size,
                min_px=self._fit_min_px(init_size),
            )
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

    def setSectorColors(self, colors):
        """注入扇区配色（通常是默认池的一份随机化副本）。

        随机化在调用方做、这里只接收结果：模块级 SECTOR_COLORS 是
        所有窗口与导入方共享的默认池，原地 shuffle 会把别人的配色
        一起改掉。空列表视为放弃注入，保留当前配色。

        字号缓存不必清空：字号只由文本/字体/可用宽高决定，与底色无关。
        """
        if not colors:
            return
        self.sector_colors = list(colors)
        self._invalidate_cache()
        self.update()

    def setShadowEnabled(self, enabled):
        self.shadow_enabled = enabled
        self._invalidate_cache()
        self.update()

    def setFontFamily(self, family):
        """设置转盘文字的字体家族"""
        self.font_family = family
        self._invalidate_cache()
        self._font_size_cache.clear()  # 不同字体的度量不同，缓存不得沿用
        self.update()

    def setItems(self, items):
        """设置转盘项目"""
        self.stopSpin()
        self.items = items
        # 注意：此处不再把 rotation 归零。旋转角是绘制相位，与项目列表
        # 无关；换列表时保留当前角度可避免视觉上的跳变，也让 setItems
        # 不会被误用作"重置转盘"的入口。
        self._invalidate_cache()
        self._font_size_cache.clear()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 绘制几何只取决于 min(w, h)：未变化时缓存仍然有效，单维拉伸
        # 不再触发重绘（拖动窗口边缘时尤为明显）
        side = min(self.width(), self.height())
        if self.cached_size is None:
            # 还没有缓存可失效：由 paintEvent 直接按当前边长建第一个
            return
        if side == self.cached_size:
            # 拖回原尺寸：缓存依然有效，取消可能挂起的去抖
            self._pending_side = None
            self._resize_timer.stop()
            return
        # 去抖：进入待生效态并（重）起单次定时器，到点才真正失效缓存；
        # 窗口内的 paintEvent 用旧缓存按新旧边长比拉伸兜底
        self._pending_side = side
        self._resize_timer.start(RESIZE_DEBOUNCE_MS)
        self.update()

    def _onResizeSettled(self):
        """去抖到点：失效缓存，由下一次 paintEvent 按新边长重建。"""
        if self.cached_pixmap is not None:
            self._invalidate_cache()
            self.update()
        self._pending_side = None

    def startSpin(self):
        """开始旋转：先由 core.plan_spin 定好结果，再把动画演到终点。

        公平性由 plan_spin 的 winner 抽取保证，与浮点物理脱钩。
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

        # 需要重建缓存的情况：缓存缺失、窗口被移到不同 devicePixelRatio 的
        # 屏幕上，或边长已变化且不在 resize 去抖窗口内（窗口内先拉伸旧图）
        if (
            self.cached_pixmap is None
            or self.cached_dpr != self.devicePixelRatio()
            or (self.cached_size != side and self._pending_side is None)
        ):
            self.renderCache()

        if self.cached_pixmap is None:
            return

        # 在 widget 中心贴上旋转后的缓存图
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        # 将缓存图中心对齐到 widget 中心。去抖窗口内缓存边长与当前不一致，
        # 按新旧边长比拉伸（圆心仍对齐；短暂模糊见 resizeEvent 的说明）
        cache_side = side if self.cached_size is None else self.cached_size

        painter.save()
        painter.translate(center)
        painter.rotate(self.rotation)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if cache_side != side:
            painter.scale(side / cache_side, side / cache_side)
        painter.drawPixmap(QPointF(-cache_side / 2.0, -cache_side / 2.0), self.cached_pixmap)
        painter.restore()

        # ---------- 绘制固定的中心装饰和指针 ----------
        # 半径与 renderCache 用同一个量：改 layout.WHEEL_DIAMETER_RATIO 时
        # 两者一起动，不会出现缓存图与指针脱钩
        radius = side * layout.WHEEL_RADIUS_RATIO
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
        pointer_tip = QPointF(center.x(), center.y() - radius + 5)
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
        radius = side * layout.WHEEL_DIAMETER_RATIO / 2.0
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        click_pos = event.position()
        dist = math.hypot(click_pos.x() - center.x(), click_pos.y() - center.y())
        if dist <= radius * 0.15:
            self.startSpin()
        else:
            super().mousePressEvent(event)
