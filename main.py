import sys
import random
import math
import os

from PyQt6.QtCore import (Qt, QTimer, QRect, QRectF, QPointF, pyqtSignal,
                          QVariantAnimation, QEvent)
from PyQt6.QtGui import (QPainter, QColor, QFont, QPen,
                         QBrush, QPixmap, QPolygonF, QPainterPath,
                         QFontDatabase, QCursor, QPalette)
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QFrame,
                             QMainWindow, QSpinBox, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QComboBox,
                             QMessageBox, QSplitter,
                             QInputDialog, QSizePolicy,
                             QAbstractItemView, QFontComboBox)

from luckywheel.core import paths as core_paths, spin, storage
from luckywheel.core.models import AppState, Group
from luckywheel.core.spin import sector_at

# 转盘扇区颜色池
SECTOR_COLORS = [
    QColor("#FF6B6B"), QColor("#4ECDC4"), QColor("#45B7D1"),
    QColor("#96CEB4"), QColor("#FFEAA7"), QColor("#DDA0DD"),
    QColor("#98D8C8"), QColor("#F7DC6F"), QColor("#BB8FCE"),
    QColor("#85C1E9"), QColor("#F8C471"), QColor("#82E0AA"),
    QColor("#F1948A"), QColor("#85929E"), QColor("#AED6F1"),
    QColor("#E8DAEF"), QColor("#A3E4D7"), QColor("#FAD7A0"),
    QColor("#D5F5E3"), QColor("#F9E79F"), QColor("#ABEBC6"),
    # 新增颜色
    QColor("#E74C3C"), QColor("#3498DB"), QColor("#2ECC71"),
    QColor("#F39C12"), QColor("#9B59B6"), QColor("#1ABC9C"),
    QColor("#E67E22"), QColor("#C0392B"),
    QColor("#16A085"), QColor("#8E44AD"), QColor("#D35400"),
]


# 保存去抖窗口：字号微调、批量抽取每轮、拖拽排序等高频变更在此毫秒数内
# 合并为一次落盘；关闭窗口等不能丢数据的时机走 flushSave 立即写入
SAVE_DEBOUNCE_MS = 500


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


def loadEmbeddedFont(font_filename):
    """加载内嵌字体并返回族名，失败返回 None"""
    # PyInstaller 打包后解压路径
    if getattr(sys, 'frozen', False):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    font_path = os.path.join(base_dir, font_filename)
    if os.path.exists(font_path):
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                return families[0]  # 返回族名
    return None

class SplitterHandle(QFrame):
    def __init__(self, list_widget, save_callback, set_height_callback,
                 left_panel, max_height_func=None, parent=None):
        super().__init__(parent)
        self.list_widget = list_widget
        self.save_callback = save_callback
        self.set_height_callback = set_height_callback
        self.left_panel = left_panel
        self.max_height_func = max_height_func or (lambda: self.left_panel.height() - 200)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFrameShadow(QFrame.Shadow.Plain)
        self.setStyleSheet("QFrame { border: 1px solid #ccc; background: #eee; }")
        self.setCursor(Qt.CursorShape.SplitVCursor)
        self.setFixedHeight(6)
        self._dragging = False
        self._start_y = 0
        self._start_height = 0

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._start_y = QCursor.pos().y()
            self._start_height = self.list_widget.height()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = QCursor.pos().y() - self._start_y
            new_height = int(self._start_height + delta)
            min_h = 60
            max_h = self.max_height_func()
            new_height = max(min_h, min(new_height, max_h))
            self.list_widget.setFixedHeight(new_height)
            # 实时同步高度到 MainWindow，防止 resizeEvent 回路覆盖拖拽值
            if self.set_height_callback:
                self.set_height_callback(new_height)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            # 把当前高度保存到 MainWindow 的 user_list_height
            if self.set_height_callback:
                self.set_height_callback(self.list_widget.height())
            if self.save_callback:
                self.save_callback()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
            
class WheelWidget(QWidget):
    """转盘绘制与旋转逻辑"""
    spinStarted = pyqtSignal()
    spinFinished = pyqtSignal(int, str)  # 扇区索引, 项目文字

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.rotation = 0.0          # 当前旋转角度（度，规范化到 [0, 360)）
        self.spinning = False
        self.result_text = ""
        self.font_family = "汉仪文黑-65W"
        self.shadow_enabled = True
        self.cached_pixmap = None    # 离屏转盘图像（不含旋转）
        self.cached_size = None      # 上次生成缓存时的逻辑边长 min(w, h)
        self.cached_dpr = None       # 上次生成缓存时的 devicePixelRatio
        self.font_size = 0           # 0=自动，>0=固定像素大小
        self._font_size_cache = {}   # (文本, 字体, 初始字号, 宽限, 高限) -> 实际字号
        self.plan = None             # 当前旋转计划（core.spin.SpinPlan）
        self.animation = None        # 驱动计划时间轴的 QVariantAnimation
        self.speed_scale = 1.0       # 动画时长除数：>1 加速（冒烟/测试用）

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
        sector_colors = []   # 每个扇区实际使用的底色，供下方文字对比色查询

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
            path.arcTo(QRectF(-radius, -radius, radius * 2, radius * 2),
                       start_angle, span_angle)
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
            painter.rotate(mid_angle_deg)   # 注意此处直接使用 mid_angle_deg，不再加 rotation

            rect = QRectF(-text_w / 2, -text_h / 2, text_w, text_h)

            # 对比色取文字实际所在扇区的底色：arcTo 的正向扫掠与
            # (cosθ, sinθ) 参数化方向相反，文字 i 落在扇区 num-1-i 上，
            # 而非 SECTOR_COLORS[i]。调色板全为亮色时取错也不可见。
            text_color = contrast_text_color(sector_colors[num - 1 - i])
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
        self._font_size_cache.clear()   # 不同字体的度量不同，缓存不得沿用
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
        if (self.cached_pixmap is None or self.cached_size != side
                or self.cached_dpr != self.devicePixelRatio()):
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
        painter.drawText(QRectF(-radius * 0.1, -radius * 0.1, radius * 0.2, radius * 0.2),
                         Qt.AlignmentFlag.AlignCenter, "GO")
        painter.restore()
    
        # 指针
        painter.save()
        wheel_radius = min(self.width(), self.height()) * 0.44
        pointer_tip = QPointF(center.x(), center.y() - wheel_radius + 5)
        pointer_size = 20
        pointer = QPolygonF([
            pointer_tip,
            QPointF(pointer_tip.x() - pointer_size / 2, pointer_tip.y() - pointer_size),
            QPointF(pointer_tip.x() + pointer_size / 2, pointer_tip.y() - pointer_size)
        ])
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


class MainWindow(QMainWindow):
    """主窗口：编辑面板 + 转盘"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("幸运大转盘")
        self.groups = []
        self.current_group_index = 0
        self._updating_list = False
        self.shadow_enabled = True   # 给一个默认值，loadData 会覆盖
        self.window_geometry = None
        self.splitter_sizes = None
        self.user_list_height = 200
        self.drawn_user_height = 120   # 抽出列表默认高度

        # 批量抽取相关
        self.batch_remaining = 0        # 批量抽取剩余次数
        self.batch_results = []         # 批量抽取结果日志
        self.batch_spin_count = 3       # 批量抽取默认次数
        self.theme = "light"           # 背景主题: light / dark / system
        self.last_result_index = None   # 最近一次中奖扇区的索引（按索引抽出的依据）

        # 保存去抖：saveData 只重置这个单次定时器，到点或 flushSave 才真正落盘
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self.flushSave)

        # 数据文件路径：优先程序旁边（便携模式），不可写时回退用户数据目录
        data_path, relocated = core_paths.resolve_data_path()
        if relocated is not None:
            print(f"提示: 数据文件将从 {relocated} 迁移到 {data_path}")
            core_paths.relocate_data_file(relocated, data_path)
        self.data_file = str(data_path)

        # 优先使用内嵌字体，失败则使用默认后备
        embedded_font = loadEmbeddedFont("HYWenHei-65W.ttf")
        if embedded_font:
            self.ui_font_family = embedded_font
            self.wheel_font_family = embedded_font
        else:
            self.ui_font_family = "Microsoft YaHei"
            self.wheel_font_family = "Microsoft YaHei"

        self.loadData()

        random.shuffle(SECTOR_COLORS)

        self.initUI()
        self.updateWheelFromCurrentGroup()
        QApplication.styleHints().colorSchemeChanged.connect(self._onSystemThemeChanged)
        self._theme_applied = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._theme_applied:
            self._theme_applied = True
            QTimer.singleShot(0, self._applyTheme)

    # ================= 下方控件颜色初始化 =================
    def _initLowerAreaColors(self, is_dark):
        """为抽出项目列表及其视口显式设置调色板，解决深层嵌套时调色板不传播的问题。
        
        Args:
            is_dark: True=深色主题，False=浅色主题
        """
        try:
            palette = self._darkPalette() if is_dark else self._lightPalette()
        except Exception:
            return  # 调色板构造失败，静默退出

        widgets = []
        try:
            if hasattr(self, 'drawn_list_widget') and self.drawn_list_widget is not None:
                widgets.append(self.drawn_list_widget)
        except (RuntimeError, AttributeError):
            pass
        try:
            if hasattr(self, 'list_widget') and self.list_widget is not None:
                widgets.append(self.list_widget)
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

    def onShadowToggled(self, state):
        enabled = self.shadow_checkbox.isChecked()
        self.shadow_enabled = enabled
        self.wheel.setShadowEnabled(enabled)
        self.saveData()
        
    def eventFilter(self, obj, event):
        # 监听列表视口的拖放事件
        if obj is self.list_widget.viewport() and event.type() == QEvent.Type.Drop:
            # 拖放完成后，使用 QTimer 确保列表数据已更新
            QTimer.singleShot(0, self.onItemsReordered)
            return False
        return super().eventFilter(obj, event)

    # ================= 主题切换 =================
    @staticmethod
    def _darkPalette():
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

    @staticmethod
    def _lightPalette():
        """显式浅色调色板，不依赖系统当前主题"""
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

    def _isSystemDark(self):
        return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark

    def _applyTheme(self):
        """浅色=显式浅色调板 / 深色=暗色调板+QSS / 跟随系统=检测"""
        if self.theme == "dark" or (self.theme == "system" and self._isSystemDark()):
            QApplication.instance().setPalette(self._darkPalette())
            # 不对通用控件设置 QSS，交由 Fusion 样式+调色板自动着色，
            # 保证深/浅两种主题下控件形态（边框、圆角、indicator 尺寸）完全一致
            self.setStyleSheet("")
            if hasattr(self, 'single_frame'):
                self.single_frame.setStyleSheet(
                    "QFrame { background: #3D3D3D; border: none; border-radius: 4px; }")
                self.single_title.setStyleSheet(
                    "color: #AAA; background: transparent; border: none;")
                self.batch_frame.setStyleSheet(
                    "QFrame { background: #3D3D3D; border: none; border-radius: 4px; padding: 4px; }")
                self.batch_title.setStyleSheet(
                    "color: #AAA; background: transparent; border: none;")
                self.batch_log_label.setStyleSheet(
                    "color: #AAA; background: transparent; border: none;")
                self.result_label.setStyleSheet(
                    "font-weight: bold; color: #E0E0E0;")
                self.splitter_handle.setStyleSheet(
                    "QFrame { background: #4A4A4A; border: 1px solid #555; }")
                self.drawn_splitter_handle.setStyleSheet(
                    "QFrame { background: #4A4A4A; border: 1px solid #555; }")
            self._initLowerAreaColors(is_dark=True)
        else:
            QApplication.instance().setPalette(self._lightPalette())
            self.setStyleSheet("")
            if hasattr(self, 'single_frame'):
                self.single_frame.setStyleSheet(
                    "QFrame { background: #f8f7f5; border: none; border-radius: 4px; }")
                self.single_title.setStyleSheet(
                    "color: #555; background: transparent; border: none;")
                self.batch_frame.setStyleSheet(
                    "QFrame { background: #f8f7f5; border: none; border-radius: 4px; padding: 4px; }")
                self.batch_title.setStyleSheet(
                    "color: #555; background: transparent; border: none;")
                self.batch_log_label.setStyleSheet(
                    "color: #666; background: transparent; border: none;")
                self.result_label.setStyleSheet(
                    "font-weight: bold; color: #333;")
                self.splitter_handle.setStyleSheet(
                    "QFrame { border: 1px solid #ccc; background: #eee; }")
                self.drawn_splitter_handle.setStyleSheet(
                    "QFrame { border: 1px solid #ccc; background: #eee; }")
            self._initLowerAreaColors(is_dark=False)

    def _onSystemThemeChanged(self):
        if self.theme == "system":
            self._applyTheme()

    def onThemeChanged(self, index):
        themes = ["light", "dark", "system"]
        if 0 <= index < len(themes):
            self.theme = themes[index]
            self._applyTheme()
            self.saveData()

    def editAllItems(self):
        """编辑当前分组的所有项目（每行一个）"""
        if not self.groups:
            return
        # 将当前项目列表拼成多行文本
        current_text = "\n".join(self.groups[self.current_group_index]['items'])
        text, ok = QInputDialog.getMultiLineText(
            self, "编辑所有项目",
            "每行一个项目（可添加、删除、修改）:",
            text=current_text
        )
        if ok:
            # 按行分割，过滤空行
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            self.groups[self.current_group_index]['items'] = lines
            self.updateWheelFromCurrentGroup()
            self.saveData()

    def updateDrawnList(self):
        """刷新抽出项目列表"""
        if 0 <= self.current_group_index < len(self.groups):
            drawn_items = self.groups[self.current_group_index].get('drawn_items', [])
        else:
            drawn_items = []
        self.drawn_list_widget.clear()
        self.drawn_list_widget.addItems(drawn_items)
        self.updateDrawnButtonsState()

    def updateDrawnButtonsState(self):
        """根据是否有选中项启用/禁用操作按钮"""
        has_selection = self.drawn_list_widget.currentItem() is not None
        self.btn_return_drawn.setEnabled(has_selection)
        self.btn_delete_drawn.setEnabled(has_selection)

    def updateExtractButtonState(self):
        """控制抽出按钮的可用状态"""
        if not self.groups or self.current_group_index < 0:
            self.btn_extract.setEnabled(False)
            return
        items = self.groups[self.current_group_index]['items']
        has_result = self.last_result_index is not None
        self.btn_extract.setEnabled(bool(has_result and items))

    def _updateBatchButtonState(self):
        """控制批量抽取按钮的可用状态"""
        if not self.groups or self.current_group_index < 0:
            self.btn_batch_spin.setEnabled(False)
            return
        items = self.groups[self.current_group_index]['items']
        has_items = len(items) > 0
        self.btn_batch_spin.setEnabled(has_items and not self.wheel.spinning)

    def _onBatchCountChanged(self, value):
        """批量次数变更时持久化"""
        self.batch_spin_count = value
        self.saveData()

    def extractDrawnItem(self):
        """将抽签结果移出到抽出项目列表（按索引 pop，重复文本不会误删）"""
        if not self.groups or self.current_group_index < 0:
            return
        index = self.last_result_index
        group = self.groups[self.current_group_index]
        if index is None or not 0 <= index < len(group['items']):
            return
        item_text = group['items'].pop(index)
        group.setdefault('drawn_items', []).append(item_text)
        self.updateWheelFromCurrentGroup()  # 内部会清理 last_result_index
        self.saveData()

    def returnDrawnItem(self):
        """将选中的抽出项目返回至抽签项目列表"""
        if not self.groups:
            return
        group = self.groups[self.current_group_index]
        selected = self.drawn_list_widget.currentItem()
        if selected is None:
            return
        item_text = selected.text()
        current_row = self.drawn_list_widget.currentRow()
        total_rows = self.drawn_list_widget.count()
    
        # 计算下一个要选中的行号
        next_row = -1
        if total_rows > 1:
            if current_row == total_rows - 1:
                next_row = current_row - 1    # 最后一项 → 上一项
            else:
                next_row = current_row #+ 1    # 否则 → 下一项
    
        # 执行移除
        if 0 <= current_row < len(group['drawn_items']):
            item_text = group['drawn_items'][current_row]   # 根据索引获取准确项目
            del group['drawn_items'][current_row]           # 根据索引删除
            group['items'].append(item_text)
            self.updateWheelFromCurrentGroup()   # 刷新列表
    
            # 按索引直接选中
            if next_row >= 0 and self.drawn_list_widget.count() > 0:
                # 防止索引越界（移除后列表缩短）
                if next_row >= self.drawn_list_widget.count():
                    next_row = self.drawn_list_widget.count() - 1
                self.drawn_list_widget.setCurrentRow(next_row)
            self.saveData()

    def deleteDrawnItem(self):
        """删除选中的抽出项目"""
        if not self.groups:
            return
        group = self.groups[self.current_group_index]
        selected = self.drawn_list_widget.currentItem()
        if selected is None:
            return
        item_text = selected.text()
        current_row = self.drawn_list_widget.currentRow()
        total_rows = self.drawn_list_widget.count()
    
        next_row = -1
        if total_rows > 1:
            if current_row == total_rows - 1:
                next_row = current_row - 1
            else:
                next_row = current_row #+ 1
    
        if 0 <= current_row < len(group['drawn_items']):
            del group['drawn_items'][current_row]
            self.updateDrawnList()              # 刷新
    
            if next_row >= 0 and self.drawn_list_widget.count() > 0:
                if next_row >= self.drawn_list_widget.count():
                    next_row = self.drawn_list_widget.count() - 1
                self.drawn_list_widget.setCurrentRow(next_row)
            self.saveData()

    def editDrawnItem(self, item=None):
        """双击编辑抽出项目"""
        if not self.groups:
            return
        row = self.drawn_list_widget.currentRow()
        group = self.groups[self.current_group_index]
        if row < 0 or row >= len(group.get('drawn_items', [])):
            return
        old_text = group['drawn_items'][row]

        dlg = QDialog(self)
        dlg.setWindowTitle("编辑抽出项目")
        dlg.setMinimumWidth(350)
        layout = QVBoxLayout(dlg)

        edit = QLineEdit(old_text)
        edit.selectAll()
        layout.addWidget(edit)

        btn_layout = QHBoxLayout()

        def copy_text():
            QApplication.clipboard().setText(edit.text())

        btn_copy = QPushButton("复制")
        btn_copy.clicked.connect(copy_text)
        btn_layout.addWidget(btn_copy)

        btn_layout.addStretch()

        btn_ok = QPushButton("确定")
        btn_cancel = QPushButton("取消")
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_text = edit.text().strip()
            if new_text and new_text != old_text:
                group['drawn_items'][row] = new_text
                self.updateDrawnList()
                self.saveData()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, 'list_widget') or not hasattr(self, 'left_panel'):
            return
    
        panel_h = self.left_panel.height()
    
        # 抽签项目列表：最大高度 = 面板高 - 下方全部控件最小高度(约 200)
        max_list = max(800, panel_h - 0)
        target_list = min(self.user_list_height, max_list)
        self.list_widget.setFixedHeight(target_list)
    
        # 抽出项目列表：最大高度 = 面板高 - 上方已占 - 下方按钮区
        # 上方已占：项目列表高度 + 分隔条高度 + 编辑按钮区域等（大约 180 像素）
        used_top = self.list_widget.height() + 6 - 180   # 6 是分隔条高度，180 是编辑按钮、标签等
        max_drawn = max(600, panel_h - used_top - 40)     # 40 是抽出按钮区
        target_drawn = min(self.drawn_user_height, max_drawn)
        self.drawn_list_widget.setFixedHeight(target_drawn)

    def onUserHeightChanged(self, new_height):
        """拖拽结束时保存用户设定的高度"""
        self.user_list_height = new_height

    def onDrawnHeightChanged(self, new_height):
        """拖拽抽出列表分隔条时保存高度"""
        self.drawn_user_height = new_height

    def applyUIFont(self):
        """应用界面字体到全局，所有控件统一字号（保留粗体属性）"""
        base_font = QFont(self.ui_font_family, self.ui_font_size)
        QApplication.setFont(base_font)
        # QApplication.setFont 不会自动刷新已存在控件，这里遍历所有子控件手动同步
        for widget in self.findChildren(QWidget):
            # 转盘的字体由 setFontFamily/setFontSize 独立控制，跳过
            if widget is getattr(self, 'wheel', None):
                continue
            old = widget.font()
            new_font = QFont(base_font)
            new_font.setBold(old.bold())
            new_font.setItalic(old.italic())
            new_font.setUnderline(old.underline())
            widget.setFont(new_font)

    def applyWheelFont(self):
        """应用转盘字体到 WheelWidget"""
        self.wheel.setFontFamily(self.wheel_font_family)
        self.wheel.setFontSize(self.wheel_font_size)

    def onUIFontChanged(self, font):
        self.ui_font_family = font.family()
        self.applyUIFont()
        self.saveData()

    def onUIFontSizeChanged(self, size):
        self.ui_font_size = size
        self.applyUIFont()
        self.saveData()

    def onWheelFontChanged(self, font):
        self.wheel_font_family = font.family()
        self.applyWheelFont()
        self.saveData()

    def onWheelFontSizeChanged(self, size):
        self.wheel_font_size = size
        self.applyWheelFont()
        self.saveData()
    # ================= 数据持久化 =================
    def loadData(self):
        state, warnings = storage.load_state(self.data_file)
        for w in warnings:
            print("数据提示:", w)
        self.groups = [g.to_dict() for g in state.groups]
        self.current_group_index = state.current_group
        # 读取新字段，兼容旧 font_family；文件未记录字体家族时，
        # 保留 loadEmbeddedFont 已确定的选择（老数据没有这些字段）
        self.ui_font_family = state.ui_font_family or self.ui_font_family
        self.ui_font_size = state.ui_font_size
        self.wheel_font_family = state.wheel_font_family or self.wheel_font_family
        self.wheel_font_size = state.wheel_font_size
        self.shadow_enabled = state.shadow_enabled
        self.window_geometry = state.window_geometry
        self.splitter_sizes = state.splitter_sizes
        self.user_list_height = state.list_height
        self.drawn_user_height = state.drawn_list_height
        self.batch_spin_count = state.batch_spin_count
        self.theme = state.theme
        if not os.path.exists(self.data_file):
            # 首次启动或文件损坏被隔离：把默认数据落盘（与旧行为一致）
            self.saveData()

    def saveData(self):
        """调度一次延迟保存：连续的高频变更在 500ms 内合并为一次落盘。

        需要立即落盘的时机（关闭窗口）必须改用 flushSave。
        """
        self._save_timer.start()

    def flushSave(self):
        """取消待发的定时器并立即落盘。"""
        self._save_timer.stop()
        try:
            state = AppState(
                groups=[Group.from_dict(g) for g in self.groups],
                current_group=self.current_group_index,
                ui_font_family=self.ui_font_family,
                ui_font_size=self.ui_font_size,
                wheel_font_family=self.wheel_font_family,
                wheel_font_size=self.wheel_font_size,
                shadow_enabled=self.shadow_enabled,
                window_geometry=self.window_geometry,
                splitter_sizes=self.splitter_sizes,
                # 保存实际显示的高度（所见即所得）
                list_height=self.list_widget.height() if hasattr(self, 'list_widget') else self.user_list_height,
                drawn_list_height=self.drawn_list_widget.height() if hasattr(self, 'drawn_list_widget') else self.drawn_user_height,
                batch_spin_count=self.batch_spin_count,
                theme=self.theme,
            )
            storage.save_state(self.data_file, state)
        except Exception as e:
            print("保存失败:", e)

    # ================= UI 构建 =================
    def initUI(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # ===== 左侧面板 =====
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        self.left_panel.setMinimumWidth(250)
        self.left_panel.setMaximumWidth(600)

        # 分组管理
        group_layout = QHBoxLayout()
        group_layout.addWidget(QLabel("分组:"))
        self.group_combo = QComboBox()
        self.group_combo.currentIndexChanged.connect(self.onGroupChanged)
        self.group_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        group_layout.addWidget(self.group_combo)
        btn_add_group = QPushButton("+")
        btn_add_group.setMaximumWidth(30)
        btn_add_group.clicked.connect(self.addGroup)
        group_layout.addWidget(btn_add_group)
        btn_del_group = QPushButton("-")
        btn_del_group.setMaximumWidth(30)
        btn_del_group.clicked.connect(self.deleteGroup)
        group_layout.addWidget(btn_del_group)
        left_layout.addLayout(group_layout)

        btn_rename_group = QPushButton("重命名分组")
        btn_rename_group.clicked.connect(self.renameGroup)
        left_layout.addWidget(btn_rename_group)

        left_layout.addWidget(QLabel("抽签项目 (可拖拽排序):"))

        # 可拖拽高度的项目列表
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.model().layoutChanged.connect(self.onItemsReordered)
        self.list_widget.itemDoubleClicked.connect(self.editItem)
        self.list_widget.viewport().installEventFilter(self)
        self.list_widget.setFixedHeight(self.user_list_height)   # 使用保存的用户高度
        left_layout.addWidget(self.list_widget)

        # 第一个分隔条
        self.splitter_handle = SplitterHandle(
            list_widget=self.list_widget,
            save_callback=self.saveData,
            set_height_callback=self.onUserHeightChanged,
            left_panel=self.left_panel,
            max_height_func=lambda: max(80, self.left_panel.height() - 0),
            parent=self.left_panel
        )

        left_layout.addWidget(self.splitter_handle)

        # ===== 下方固定区域（按钮 + 抽出项目 + 抽出操作） =====
        self.bottom_widget = QWidget()
        self.bottom_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        bottom_layout = QVBoxLayout(self.bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(4)

        # --- 项目编辑按钮 ---
        item_btn_layout = QHBoxLayout()
        btn_add_item = QPushButton("添加")
        btn_add_item.clicked.connect(self.addItem)
        item_btn_layout.addWidget(btn_add_item)
        btn_del_item = QPushButton("删除")
        btn_del_item.clicked.connect(self.deleteItem)
        item_btn_layout.addWidget(btn_del_item)
        btn_edit_item = QPushButton("编辑")
        btn_edit_item.clicked.connect(self.editItem)
        item_btn_layout.addWidget(btn_edit_item)
        bottom_layout.addLayout(item_btn_layout)

        btn_batch = QPushButton("批量导入")
        btn_batch.clicked.connect(self.batchAddItems)
        bottom_layout.addWidget(btn_batch)

        btn_shuffle = QPushButton("随机打乱顺序")
        btn_shuffle.clicked.connect(self.shuffleItems)
        bottom_layout.addWidget(btn_shuffle)

        btn_edit_all = QPushButton("编辑所有项目")
        btn_edit_all.clicked.connect(self.editAllItems)
        bottom_layout.addWidget(btn_edit_all)

        btn_clear = QPushButton("清空项目")
        btn_clear.clicked.connect(self.clearItems)
        bottom_layout.addWidget(btn_clear)

        # --- 抽出项目区域（可拖拽高度） ---
        bottom_layout.addWidget(QLabel("抽出项目:"))
        self.drawn_list_widget = QListWidget()
        self.drawn_list_widget.setFixedHeight(self.drawn_user_height)  # 初始高度
        self.drawn_list_widget.setMaximumHeight(900)                   # 硬上限，可删除，由拖动动态限制
        self.drawn_list_widget.itemSelectionChanged.connect(self.updateDrawnButtonsState)
        self.drawn_list_widget.itemDoubleClicked.connect(self.editDrawnItem)
        # 不要给带滚动条的控件单独设 QSS，否则会切换到 QStyleSheetStyle 渲染，
        # 导致滚动条不跟随 Fusion + palette，在浅色主题下出现深色滚动条。
        bottom_layout.addWidget(self.drawn_list_widget)

        # 分隔条2
        self.drawn_splitter_handle = SplitterHandle(
            list_widget=self.drawn_list_widget,
            save_callback=self.saveData,
            set_height_callback=self.onDrawnHeightChanged,
            left_panel=self.left_panel,
            parent=self.left_panel
        )
        bottom_layout.addWidget(self.drawn_splitter_handle)

        # 抽出操作按钮（固定高度）
        drawn_btn_widget = QWidget()
        drawn_btn_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        drawn_btn_layout = QHBoxLayout(drawn_btn_widget)
        drawn_btn_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_return_drawn = QPushButton("返回项目")
        self.btn_return_drawn.setEnabled(False)
        self.btn_return_drawn.clicked.connect(self.returnDrawnItem)
        drawn_btn_layout.addWidget(self.btn_return_drawn)
        self.btn_delete_drawn = QPushButton("删除项目")
        self.btn_delete_drawn.setEnabled(False)
        self.btn_delete_drawn.clicked.connect(self.deleteDrawnItem)
        drawn_btn_layout.addWidget(self.btn_delete_drawn)
        bottom_layout.addWidget(drawn_btn_widget)

        left_layout.addWidget(self.bottom_widget)
        left_layout.addStretch(1)   # 吸收剩余高度
        # 不再需要 addStretch()，因为列表高度已由用户控制，空白区域可被列表占用
        
        # 弹性空间放在最下方，保证以上控件始终靠上
        #left_layout.addStretch()

        # ----- 右侧转盘区域 -----
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(6)
        self.wheel = WheelWidget()
        self.wheel.spinStarted.connect(self.onSpinStarted)
        self.wheel.spinFinished.connect(self.onSpinFinished)
        # 转盘吸收所有剩余高度并保持内部圆形比例（min side 决定绘制半径）
        right_layout.addWidget(self.wheel, 1)

        # ----- 结算文字（位于单次抽取卡片上方） -----
        self.result_label = QLabel("")
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_label.setFont(QFont(self.ui_font_family, self.ui_font_size, QFont.Weight.Bold))
        self.result_label.setStyleSheet("color: #333;")
        right_layout.addWidget(self.result_label)

        # ----- 单次抽取卡片 -----
        self.single_frame = QFrame()
        self.single_frame.setStyleSheet("QFrame { background: #f8f7f5; border: none; border-radius: 4px; }")
        single_layout = QVBoxLayout(self.single_frame)
        single_layout.setContentsMargins(8, 4, 8, 4)
        single_layout.setSpacing(4)

        self.single_title = QLabel("单次抽取")
        self.single_title.setFont(QFont(self.ui_font_family, self.ui_font_size, QFont.Weight.Bold))
        self.single_title.setStyleSheet("color: #555; background: transparent; border: none;")
        single_layout.addWidget(self.single_title)

        spin_layout = QHBoxLayout()
        spin_layout.setSpacing(8)

        self.btn_extract = QPushButton("抽出")
        self.btn_extract.setFixedHeight(38)
        self.btn_extract.setMaximumWidth(72)
        self.btn_extract.clicked.connect(self.extractDrawnItem)
        spin_layout.addWidget(self.btn_extract)

        self.btn_spin = QPushButton("开始旋转")
        self.btn_spin.setMinimumHeight(38)
        self.btn_spin.setStyleSheet("background-color: #FF6B6B; color: white; font-weight: bold;")
        self.btn_spin.setToolTip("或点击转盘中心的 GO 按钮")
        self.btn_spin.clicked.connect(lambda: self.wheel.startSpin())
        spin_layout.addWidget(self.btn_spin, 1)

        single_layout.addLayout(spin_layout)
        right_layout.addWidget(self.single_frame)

        # ----- 底部两栏：左=批量抽取卡片，右=界面/转盘/主题控件 -----
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)

        # 左：批量抽取卡片
        self.batch_frame = QFrame()
        self.batch_frame.setStyleSheet("QFrame { background: #f8f7f5; border: none; border-radius: 4px; padding: 4px; }")
        batch_layout = QVBoxLayout(self.batch_frame)
        batch_layout.setContentsMargins(8, 4, 8, 4)
        batch_layout.setSpacing(4)

        self.batch_title = QLabel("不放回批量抽取")
        self.batch_title.setFont(QFont(self.ui_font_family, self.ui_font_size, QFont.Weight.Bold))
        self.batch_title.setStyleSheet("color: #555; background: transparent; border: none;")
        batch_layout.addWidget(self.batch_title)

        batch_ctrl_layout = QHBoxLayout()
        self.batch_count_label = QLabel("抽取次数:")
        batch_ctrl_layout.addWidget(self.batch_count_label)
        self.batch_spinbox = QSpinBox()
        self.batch_spinbox.setRange(1, 999)
        self.batch_spinbox.setValue(self.batch_spin_count)
        self.batch_spinbox.setFixedWidth(60)
        self.batch_spinbox.valueChanged.connect(self._onBatchCountChanged)
        batch_ctrl_layout.addWidget(self.batch_spinbox)
        self.btn_batch_spin = QPushButton("开始批量抽取")
        self.btn_batch_spin.setMinimumHeight(32)
        self.btn_batch_spin.setStyleSheet("background-color: #FF6B6B; color: white; font-weight: bold;")
        self.btn_batch_spin.clicked.connect(self.startBatchSpin)
        batch_ctrl_layout.addWidget(self.btn_batch_spin, 1)
        self.btn_stop_batch = QPushButton("停止")
        self.btn_stop_batch.setEnabled(False)
        self.btn_stop_batch.clicked.connect(self.stopBatchSpin)
        batch_ctrl_layout.addWidget(self.btn_stop_batch)
        batch_layout.addLayout(batch_ctrl_layout)

        self.batch_log_label = QLabel("")
        self.batch_log_label.setFont(QFont(self.ui_font_family, self.ui_font_size))
        self.batch_log_label.setStyleSheet("color: #666; background: transparent; border: none;")
        self.batch_log_label.setWordWrap(True)
        batch_layout.addWidget(self.batch_log_label)

        bottom_row.addWidget(self.batch_frame, 1)

        # 右：设置控件列（界面字体 / 转盘字体 / 背景主题+文字阴影）
        settings_column = QVBoxLayout()
        settings_column.setSpacing(4)

        ui_font_layout = QHBoxLayout()
        ui_font_layout.addWidget(QLabel("界面字体:"))
        self.ui_font_combo = QFontComboBox()
        self.ui_font_combo.setCurrentFont(QFont(self.ui_font_family))
        self.ui_font_combo.currentFontChanged.connect(self.onUIFontChanged)
        ui_font_layout.addWidget(self.ui_font_combo, 1)
        ui_font_layout.addWidget(QLabel("大小:"))
        self.ui_font_size_spin = QSpinBox()
        self.ui_font_size_spin.setRange(1, 72)
        self.ui_font_size_spin.setValue(self.ui_font_size)
        self.ui_font_size_spin.setFixedWidth(42)
        self.ui_font_size_spin.valueChanged.connect(self.onUIFontSizeChanged)
        ui_font_layout.addWidget(self.ui_font_size_spin)
        settings_column.addLayout(ui_font_layout)

        wheel_font_layout = QHBoxLayout()
        wheel_font_layout.addWidget(QLabel("转盘字体:"))
        self.wheel_font_combo = QFontComboBox()
        self.wheel_font_combo.setCurrentFont(QFont(self.wheel_font_family))
        self.wheel_font_combo.currentFontChanged.connect(self.onWheelFontChanged)
        wheel_font_layout.addWidget(self.wheel_font_combo, 1)
        wheel_font_layout.addWidget(QLabel("大小:"))
        self.wheel_font_size_spin = QSpinBox()
        self.wheel_font_size_spin.setRange(0, 72)
        self.wheel_font_size_spin.setSpecialValueText("自动")
        self.wheel_font_size_spin.setValue(self.wheel_font_size)
        self.wheel_font_size_spin.setFixedWidth(42)
        self.wheel_font_size_spin.valueChanged.connect(self.onWheelFontSizeChanged)
        wheel_font_layout.addWidget(self.wheel_font_size_spin)
        settings_column.addLayout(wheel_font_layout)

        shadow_layout = QHBoxLayout()
        shadow_layout.addWidget(QLabel("背景主题:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["浅色", "深色", "跟随系统"])
        theme_map = {"light": 0, "dark": 1, "system": 2}
        self.theme_combo.setCurrentIndex(theme_map.get(self.theme, 0))
        self.theme_combo.setFixedWidth(100)
        self.theme_combo.currentIndexChanged.connect(self.onThemeChanged)
        shadow_layout.addWidget(self.theme_combo)
        shadow_layout.addStretch(1)
        self.shadow_checkbox = QCheckBox("文字阴影")
        self.shadow_checkbox.setChecked(self.shadow_enabled)
        self.shadow_checkbox.stateChanged.connect(self.onShadowToggled)
        shadow_layout.addWidget(self.shadow_checkbox)
        settings_column.addLayout(shadow_layout)

        bottom_row.addLayout(settings_column, 1)

        right_layout.addLayout(bottom_row)

        # 使用 QSplitter 可拖拽调整左右比例
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.left_panel)
        self.splitter.addWidget(right_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        if self.splitter_sizes:
            self.splitter.setSizes(self.splitter_sizes)
        else:
            self.splitter.setSizes([250, 600])   # 初始左侧 300px，右侧占剩余

        main_layout.addWidget(self.splitter)

        self.setMinimumSize(850, 600)

        self._applyWindowGeometry()
        # 初始化转盘字体
        self.shadow_checkbox.setChecked(self.shadow_enabled)
        self.wheel.setShadowEnabled(self.shadow_enabled)

        self.btn_extract.setEnabled(False)   # 初始无结果，禁用
        #self.applyGlobalFont(self.font_family) # 应用全局字体
        # 应用保存的字体设置
        self.applyUIFont()
        self.applyWheelFont()

    def _applyWindowGeometry(self):
        """恢复保存的窗口几何；与所有屏幕都不相交时回退为默认居中。

        副屏未连接时，按保存坐标摆放会把窗口放到屏幕外，用户看不到也
        拖不回来。此处用全部屏幕 availableGeometry 的相交判定（虚拟
        桌面坐标），副屏在线时正常恢复。
        """
        geometry = self.window_geometry
        if geometry and len(geometry) == 4:
            x, y, w, h = (int(v) for v in geometry)
            rect = QRect(x, y, w, h)
            screens = QApplication.screens() or []
            if any(rect.intersects(s.availableGeometry()) for s in screens):
                self.setGeometry(rect)
                return
        self._centerWindow(1024, 700)

    def _centerWindow(self, width, height):
        """按默认尺寸打开并居中到主屏可用区域。"""
        self.resize(width, height)
        screen_geo = QApplication.primaryScreen().availableGeometry()
        x = (screen_geo.width() - width) // 2
        y = (screen_geo.height() - height) // 2
        self.move(x, y)

    # ================= 分组管理 =================
    # （以下方法保持不变，仅列出，未改动）
    def updateGroupCombo(self):
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        for group in self.groups:
            self.group_combo.addItem(group['name'])
        self.group_combo.setCurrentIndex(self.current_group_index)
        self.group_combo.blockSignals(False)

    def updateWheelFromCurrentGroup(self):
        """用当前分组数据刷新界面"""
        self._updating_list = True
        if 0 <= self.current_group_index < len(self.groups):
            items = self.groups[self.current_group_index]['items']
            self.list_widget.clear()
            self.list_widget.addItems(items)
            self.wheel.setItems(items)
            self.result_label.setText("")
            self.last_result_index = None  # 数据已刷新，旧索引失效
            self.updateGroupCombo()
        else:
            self.list_widget.clear()
            self.wheel.setItems([])
        self._updating_list = False

        self.updateDrawnList()
        self.updateExtractButtonState()
        self._updateBatchButtonState()

    def onGroupChanged(self, index):
        if index >= 0:
            self.current_group_index = index
            self.updateWheelFromCurrentGroup()
            self.updateExtractButtonState()
            self.saveData()

    def addGroup(self):
        name, ok = QInputDialog.getText(self, "添加分组", "分组名称:")
        if ok and name.strip():
            self.groups.append({'name': name.strip(), 'items': [], 'drawn_items': []})
            self.current_group_index = len(self.groups) - 1
            self.updateWheelFromCurrentGroup()
            self.saveData()

    def deleteGroup(self):
        if len(self.groups) <= 1:
            QMessageBox.warning(self, "提示", "至少保留一个分组")
            return
        reply = QMessageBox.question(
            self, "删除分组",
            f"确定删除分组 '{self.groups[self.current_group_index]['name']}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self.groups[self.current_group_index]
            if self.current_group_index >= len(self.groups):
                self.current_group_index = len(self.groups) - 1
            self.updateWheelFromCurrentGroup()
            self.saveData()

    def renameGroup(self):
        if self.groups:
            name, ok = QInputDialog.getText(
                self, "重命名分组", "新名称:",
                text=self.groups[self.current_group_index]['name']
            )
            if ok and name.strip():
                self.groups[self.current_group_index]['name'] = name.strip()
                self.updateGroupCombo()
                self.saveData()

    # ================= 项目编辑 =================
    def addItem(self):
        if not self.groups:
            return
        text, ok = QInputDialog.getText(self, "添加项目", "项目文字:")
        if ok and text.strip():
            self.groups[self.current_group_index]['items'].append(text.strip())
            self.updateWheelFromCurrentGroup()
            self.saveData()

    def batchAddItems(self):
        if not self.groups:
            return
        text, ok = QInputDialog.getMultiLineText(self, "批量导入", "每行一个项目:")
        if ok and text.strip():
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines:
                self.groups[self.current_group_index]['items'].extend(lines)
                self.updateWheelFromCurrentGroup()
                self.saveData()

    def deleteItem(self):
        if not self.groups:
            return
        group = self.groups[self.current_group_index]
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(group['items']):
            return
        current_row = row
        total_items = len(group['items'])
        # 计算下一个要选中的行号
        next_row = -1
        if total_items > 1:
            if current_row == total_items - 1:    # 最后一项 → 选上一项
                next_row = current_row - 1
            else:                                 # 否则选正下方（删除后原下一项会占据当前行）
                next_row = current_row
        # 执行删除
        del group['items'][row]
        self.updateWheelFromCurrentGroup()        # 刷新列表
        self.saveData()
        # 自动选中下一个项目
        if next_row >= 0 and self.list_widget.count() > 0:
            if next_row >= self.list_widget.count():
                next_row = self.list_widget.count() - 1
            self.list_widget.setCurrentRow(next_row)

    def editItem(self, item=None):
        if isinstance(item, QListWidgetItem):
            row = self.list_widget.row(item)
        else:
            row = self.list_widget.currentRow()
        if row >= 0 and row < len(self.groups[self.current_group_index]['items']):
            old_text = self.groups[self.current_group_index]['items'][row]
            text, ok = QInputDialog.getText(self, "编辑项目", "修改文字:", text=old_text)
            if ok and text.strip():
                self.groups[self.current_group_index]['items'][row] = text.strip()
                self.updateWheelFromCurrentGroup()
                self.saveData()

    def onItemsReordered(self):
        """拖拽排序后同步数据"""
        if self._updating_list:
            return
        items = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        if items != self.groups[self.current_group_index]['items']:
            self.groups[self.current_group_index]['items'] = items
            self.wheel.setItems(items)
            self.saveData()
            self.updateExtractButtonState()

    def shuffleItems(self):
        if self.groups and self.groups[self.current_group_index]['items']:
            random.shuffle(self.groups[self.current_group_index]['items'])
            self.updateWheelFromCurrentGroup()
            self.saveData()

    def clearItems(self):
        reply = QMessageBox.question(self, "清空", "确定清空当前分组的所有项目吗？\n（抽出项目也将一并清空）",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.groups[self.current_group_index]['items'] = []
            self.groups[self.current_group_index]['drawn_items'] = []
            self.updateWheelFromCurrentGroup()
            self.saveData()

    # ================= 旋转控制 =================
    def onSpinStarted(self):
        """旋转开始时禁用编辑"""
        self.left_panel.setEnabled(False)
        self.btn_spin.setEnabled(False)
        self.btn_extract.setEnabled(False)
        if self.batch_remaining <= 0:
            self.btn_batch_spin.setEnabled(False)

    def onSpinFinished(self, index, text):
        """旋转结束时显示结果并恢复编辑"""
        self.result_label.setText(f"🎉 恭喜中奖: {text}")
        self.last_result_index = index

        # 批量抽取模式
        if self.batch_remaining > 0:
            # 自动抽出当前结果
            self._autoExtract(index)
            self.batch_results.append(text)
            self.batch_remaining -= 1
            self.batch_log_label.setText(
                f"已抽取 {len(self.batch_results)} 次，剩余 {self.batch_remaining} 次\n"
                + "  →  ".join(self.batch_results[-8:])
                + ("..." if len(self.batch_results) > 8 else "")
            )
            self.saveData()

            # 检查是否还有项目可供抽取
            group = self.groups[self.current_group_index]
            if not group['items'] or self.batch_remaining <= 0:
                self._finishBatch()
                return

            # 继续下一轮旋转
            QTimer.singleShot(400, self.wheel.startSpin)
            return

        # 单次抽取模式：恢复正常状态
        self.left_panel.setEnabled(True)
        self.btn_spin.setEnabled(True)
        self.btn_batch_spin.setEnabled(True)
        self.updateExtractButtonState()

    # ================= 批量抽取（不放回）=================
    def startBatchSpin(self):
        """开始批量不放回抽取"""
        if self.wheel.spinning:
            return
        if not self.groups or self.current_group_index < 0:
            return
        items = self.groups[self.current_group_index]['items']
        if not items:
            QMessageBox.warning(self, "提示", "当前分组没有可抽取的项目！")
            return

        n = self.batch_spinbox.value()
        if n > len(items):
            reply = QMessageBox.question(
                self, "确认",
                f"当前只有 {len(items)} 个项目，但请求抽取 {n} 次。\n"
                f"抽取 {len(items)} 次后会自动停止。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            n = len(items)

        self.batch_remaining = n
        self.batch_results = []
        self.batch_log_label.setText(f"开始不放回批量抽取 {n} 次...")
        self.btn_batch_spin.setEnabled(False)
        self.btn_stop_batch.setEnabled(True)
        self.left_panel.setEnabled(False)
        self.wheel.setItems(items)
        self.wheel.startSpin()

    def stopBatchSpin(self):
        """手动停止批量抽取"""
        self.batch_remaining = 0
        self._finishBatch()

    def _autoExtract(self, index):
        """自动将结果移入抽出列表（按索引移除，避免重复文本误删）"""
        group = self.groups[self.current_group_index]
        if 0 <= index < len(group['items']):
            item_text = group['items'].pop(index)
            if 'drawn_items' not in group:
                group['drawn_items'] = []
            group['drawn_items'].append(item_text)
            self.updateWheelFromCurrentGroup()

    def _finishBatch(self):
        """批量抽取结束，恢复界面"""
        self.batch_remaining = 0
        self.wheel.stopSpin()
        self.result_label.setText(f"✅ 批量抽取完成！共抽取 {len(self.batch_results)} 次")
        summary = "  →  ".join(self.batch_results[-20:])
        if len(self.batch_results) > 20:
            summary += f"\n（共 {len(self.batch_results)} 项，仅显示最后20项）"
        self.batch_log_label.setText(summary)
        self.left_panel.setEnabled(True)
        self.btn_spin.setEnabled(True)
        self.btn_batch_spin.setEnabled(True)
        self.btn_stop_batch.setEnabled(False)
        self.updateExtractButtonState()
        self.updateDrawnList()

    def closeEvent(self, event):
        geo = self.geometry()
        self.window_geometry = [geo.x(), geo.y(), geo.width(), geo.height()]
        self.splitter_sizes = self.splitter.sizes()
        self.flushSave()   # 关窗不能丢数据：绕过去抖立即落盘
        super().closeEvent(event)


if __name__ == "__main__":
    # PyQt6 默认启用高 DPI 缩放，无需手动设置
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())