import sys
import json
import random
import math
import os

from PyQt5.QtCore import (Qt, QTimer, QRectF, QPointF, pyqtSignal,
                          QPropertyAnimation, QEasingCurve, QEvent)
from PyQt5.QtGui import QFontMetrics, QPainter, QColor, QFont, QPen, QBrush, QPixmap, QPolygonF, QPainterPath, QFontDatabase
from PyQt5.QtWidgets import (QApplication, QCheckBox, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QComboBox, QFileDialog,
                             QMessageBox, QSplitter, QInputDialog, QSizePolicy,
                             QAbstractItemView, QFontComboBox)

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

class WheelWidget(QWidget):
    """转盘绘制与旋转逻辑"""
    spinStarted = pyqtSignal()
    spinFinished = pyqtSignal(int, str)  # 扇区索引, 项目文字

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.rotation = 0.0          # 当前旋转角度（度）
        self.angular_velocity = 0.0  # 角速度（度/秒）
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.updateRotation)
        self.spinning = False
        self.friction = 0.98         # 每帧速度衰减系数
        self.timer_interval = 30     # 毫秒
        self.result_text = ""
        self.font_family = "汉仪文黑-65W"   # 默认字体家族
        self.shadow_enabled = True   # 默认转盘字体开启阴影
        self.cached_pixmap = None   # 离屏转盘图像（不含旋转）
        self.cached_size = None     # 上次生成缓存时的 widget 尺寸

        self.setMinimumSize(350, 350)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

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
    
        # 创建正方形画布，避免圆形被拉伸
        pixmap = QPixmap(side, side)
        pixmap.fill(Qt.transparent)
    
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
    
        # ---------- 绘制扇形（无旋转） ----------
        num = len(self.items)
        sector_span = 360.0 / num
    
        painter.translate(center)
        for i in range(num):
            start_angle = i * sector_span
            span_angle = sector_span
            color = SECTOR_COLORS[i % len(SECTOR_COLORS)]
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(Qt.white, 2))
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

        for i, item in enumerate(self.items):
            # 扇区中线角度（未旋转）
            mid_angle_deg = i * sector_span + sector_span / 2.0
            mid_angle_rad = math.radians(mid_angle_deg)

            lx = text_radius * math.cos(mid_angle_rad)
            ly = text_radius * math.sin(mid_angle_rad)

            # 动态字体大小（与原版完全相同）
            font = QFont(self.font_family)
            font.setBold(True)
            init_size = max(10, int(radius * 0.18))
            font.setPixelSize(init_size)
            painter.setFont(font)
            fm = painter.fontMetrics()
            max_w = (radius - text_radius) * 0.9
            max_h = text_radius * math.radians(sector_span) * 0.7
            while fm.horizontalAdvance(item) > max_w or fm.height() > max_h:
                if font.pixelSize() <= 8:
                    break
                font.setPixelSize(font.pixelSize() - 1)
                painter.setFont(font)
                fm = painter.fontMetrics()

            text_w = fm.horizontalAdvance(item)
            text_h = fm.height()

            # 文字在 pixmap 中的位置（center 是 pixmap 中心，与 widget 中心相同计算方式）
            painter.save()
            painter.translate(center.x() + lx, center.y() + ly)
            painter.rotate(mid_angle_deg)   # 注意此处直接使用 mid_angle_deg，不再加 rotation

            rect = QRectF(-text_w / 2, -text_h / 2, text_w, text_h)

            # 阴影与主体文字（阈值与原版相同的 > 50）
            color = SECTOR_COLORS[i % len(SECTOR_COLORS)]
            text_color = Qt.black if color.lightness() > 50 else Qt.white
            if self.shadow_enabled:
                painter.setPen(QColor(0, 0, 0, 120))
                painter.drawText(rect.translated(1, 1), Qt.AlignCenter, item)
            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignCenter, item)

            painter.restore()
    
        painter.end()
        self.cached_pixmap = pixmap
        self.cached_size = side

    def setShadowEnabled(self, enabled):
        self.shadow_enabled = enabled
        self.cached_pixmap = None
        self.cached_size = None
        self.update()

    def setFontFamily(self, family):
        """设置转盘文字的字体家族"""
        self.font_family = family
        self.cached_pixmap = None
        self.cached_size = None
        self.update()

    def setItems(self, items):
        """设置转盘项目"""
        self.items = items
        self.rotation = 0.0
        self.angular_velocity = 0.0
        self.spinning = False
        self.cached_pixmap = None
        self.cached_size = None
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.cached_pixmap = None
        self.cached_size = None
        self.update()

    def startSpin(self, initial_velocity=None):
        """开始旋转，initial_velocity 可选，非正值则自动随机"""
        if self.spinning or len(self.items) == 0:
            return
        # 确保初速度是一个正数，否则随机
        if not isinstance(initial_velocity, (int, float)) or initial_velocity <= 0:
            initial_velocity = random.uniform(600, 1500)
        self.angular_velocity = initial_velocity
        self.spinning = True
        self.timer.start(self.timer_interval)
        self.spinStarted.emit()

    def updateRotation(self):
        """定时器回调：更新角度和速度"""
        if not self.spinning:
            return
        delta = self.angular_velocity * (self.timer_interval / 1000.0)
        self.rotation = (self.rotation + delta) % 360.0
        self.angular_velocity *= self.friction

        # 速度低于阈值则停止
        if abs(self.angular_velocity) < 5.0:
            self.angular_velocity = 0.0
            self.spinning = False
            self.timer.stop()
            self.determineResult()
        self.update()

    def determineResult(self):
        """根据最终角度计算指针所指扇区"""
        if len(self.items) == 0:
            return
        # 指针固定在顶部（12点方向），对应圆盘坐标系角度 270°
        pointer_angle = (270.0 - self.rotation) % 360.0
        num = len(self.items)
        sector_span = 360.0 / num
        sector_index = int(pointer_angle / sector_span)
        if sector_index >= num:
            sector_index = num - 1
        self.result_text = self.items[sector_index]
        self.spinFinished.emit(sector_index, self.result_text)

    def paintEvent(self, event):
        """使用离屏缓存绘制，大幅提升大量项目时的旋转性能"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
    
        if not self.items:
            painter.setPen(QPen(Qt.black, 1))
            painter.drawText(self.rect(), Qt.AlignCenter, "请添加项目")
            return
    
        # 需要重建缓存的情况
        if self.cached_pixmap is None or self.cached_size != side:
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
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(-pixmap_center, self.cached_pixmap)
        painter.restore()
    
        # ---------- 绘制固定的中心装饰和指针 ----------
        radius = side * 0.44  # 简便计算，也可用 wheel_diameter/2
        # 中心圆
        painter.save()
        painter.translate(center)
        painter.setBrush(QBrush(QColor("#333333")))
        painter.setPen(QPen(Qt.white, 2))
        painter.drawEllipse(QPointF(0, 0), radius * 0.15, radius * 0.15)
        painter.setBrush(QBrush(QColor("#555555")))
        painter.drawEllipse(QPointF(0, 0), radius * 0.1, radius * 0.1)
        painter.setPen(QPen(Qt.white, 1))
        font = QFont(self.font_family)
        font.setBold(True)
        font.setPixelSize(int(radius * 0.08))
        painter.setFont(font)
        painter.drawText(QRectF(-radius * 0.1, -radius * 0.1, radius * 0.2, radius * 0.2),
                         Qt.AlignCenter, "GO")
        painter.restore()
    
        # 指针
        painter.save()
        pointer_tip = QPointF(center.x(), center.y() - radius * 0.88 + 5)  # radius 是转盘半径
        # 注意 radius 应该用 wheel_diameter/2 更准，需重新计算
        wheel_radius = min(self.width(), self.height()) * 0.44
        pointer_tip = QPointF(center.x(), center.y() - wheel_radius + 5)
        pointer_size = 20
        pointer = QPolygonF([
            pointer_tip,
            QPointF(pointer_tip.x() - pointer_size / 2, pointer_tip.y() - pointer_size),
            QPointF(pointer_tip.x() + pointer_size / 2, pointer_tip.y() - pointer_size)
        ])
        painter.setBrush(QBrush(QColor("#FF0000")))
        painter.setPen(QPen(Qt.white, 2))
        painter.drawPolygon(pointer)
        painter.restore()

    def mousePressEvent(self, event):
        """点击中心圆触发旋转"""
        if self.spinning:
            return
        side = min(self.width(), self.height())
        radius = side * 0.88 / 2.0
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        click_pos = event.pos()
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
        self.font_family = "汉仪文黑-65W"  # 新增：当前字体家族
        self.shadow_enabled = True   # 给一个默认值，loadData 会覆盖
        self.window_geometry = None
        self.splitter_sizes = None

        # 数据文件路径（兼容打包后的 exe）
        if getattr(sys, 'frozen', False):
            app_dir = os.path.dirname(sys.executable)
        else:
            app_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_file = os.path.join(app_dir, "wheel_data.json")

        # 优先使用内嵌字体，失败则使用默认后备
        embedded_font = loadEmbeddedFont("HYWenHei-65W.ttf")  # 替换为你的字体文件名
        if embedded_font:
            self.font_family = embedded_font
        else:
            self.font_family = "Microsoft YaHei"  # 后备字体
        print("使用字体:", self.font_family)  # 调试用，可删除

        self.loadData()

        random.shuffle(SECTOR_COLORS)

        self.initUI()
        self.updateWheelFromCurrentGroup()

    def onShadowToggled(self, state):
        enabled = (state == Qt.Checked)
        self.shadow_enabled = enabled         # 关键：更新成员变量
        self.wheel.setShadowEnabled(enabled)
        self.saveData()
        
    def eventFilter(self, obj, event):
        # 监听列表视口的拖放事件
        if obj is self.list_widget.viewport() and event.type() == QEvent.Drop:
            # 拖放完成后，使用 QTimer 确保列表数据已更新
            QTimer.singleShot(0, self.onItemsReordered)
            return False
        return super().eventFilter(obj, event)

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

    # ================= 数据持久化 =================
    def loadData(self):
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.groups = data.get('groups', [])
                self.current_group_index = data.get('current_group', 0)
                self.font_family = data.get('font_family', '汉仪文黑-65W')   # 新读取
                self.shadow_enabled = data.get('shadow_enabled', True)
                self.window_geometry = data.get('window_geometry', None)
                if self.window_geometry and len(self.window_geometry) != 4:
                    self.window_geometry = None
                
                self.splitter_sizes = data.get('splitter_sizes', None)
                if not (isinstance(self.splitter_sizes, list) and len(self.splitter_sizes) == 2):
                    self.splitter_sizes = None
                
                if not self.groups:
                    self.groups.append({'name': '默认分组', 'items': ['选项1', '选项2', '选项3']})
                    self.current_group_index = 0
        except (FileNotFoundError, json.JSONDecodeError):
            self.groups = [{'name': '默认分组', 'items': ['选项1', '选项2', '选项3']}]
            self.current_group_index = 0
            self.font_family = "汉仪文黑-65W"
            self.shadow_enabled = True
            self.saveData()
            self.window_geometry = None

    def saveData(self):
        try:
            data = {
                'groups': self.groups,
                'current_group': self.current_group_index,
                'font_family': self.font_family,   # 新保存
                'shadow_enabled': self.shadow_enabled
            }
            if self.window_geometry and len(self.window_geometry) == 4:
                data['window_geometry'] = self.window_geometry
            if self.splitter_sizes is not None:
                data['splitter_sizes'] = self.splitter_sizes
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("保存失败:", e)

    # ================= UI 构建 =================
    def initUI(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # ----- 左侧编辑面板 -----
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        self.left_panel.setMinimumWidth(250)   # 可自由调大，但不能小于 250px
        self.left_panel.setMaximumWidth(600)   # 最大宽度，按需调整

        # 分组管理（保持不变）
        group_layout = QHBoxLayout()
        group_layout.addWidget(QLabel("分组:"))
        self.group_combo = QComboBox()
        self.group_combo.currentIndexChanged.connect(self.onGroupChanged)
        self.group_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
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
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.InternalMove)
        self.list_widget.model().layoutChanged.connect(self.onItemsReordered)
        self.list_widget.itemDoubleClicked.connect(self.editItem)
        self.list_widget.viewport().installEventFilter(self)
        left_layout.addWidget(self.list_widget)

        # 项目编辑按钮
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
        left_layout.addLayout(item_btn_layout)

        btn_batch = QPushButton("批量导入")
        btn_batch.clicked.connect(self.batchAddItems)
        left_layout.addWidget(btn_batch)

        btn_shuffle = QPushButton("随机打乱顺序")
        btn_shuffle.clicked.connect(self.shuffleItems)
        left_layout.addWidget(btn_shuffle)

        btn_edit_all = QPushButton("编辑所有项目")
        btn_edit_all.clicked.connect(self.editAllItems)
        left_layout.addWidget(btn_edit_all)

        btn_clear = QPushButton("清空项目")
        btn_clear.clicked.connect(self.clearItems)
        left_layout.addWidget(btn_clear)

        left_layout.addStretch()

        # ----- 右侧转盘区域 -----
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.wheel = WheelWidget()
        self.wheel.spinStarted.connect(self.onSpinStarted)
        self.wheel.spinFinished.connect(self.onSpinFinished)
        right_layout.addWidget(self.wheel)

        self.btn_spin = QPushButton("开始旋转 (或点击转盘中心)")
        self.btn_spin.setMinimumHeight(40)
        self.btn_spin.clicked.connect(lambda: self.wheel.startSpin())
        right_layout.addWidget(self.btn_spin)

        self.result_label = QLabel("")
        self.result_label.setAlignment(Qt.AlignCenter)
        self.result_label.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #333;"
        )
        right_layout.addWidget(self.result_label)

        # ----- 字体选择（右下角） -----
        font_layout = QHBoxLayout()
        font_layout.addStretch()  # 推到右侧
        font_label = QLabel("字体:")
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont(self.font_family))
        self.font_combo.currentFontChanged.connect(self.onFontChanged)
        font_layout.addWidget(font_label)
        font_layout.addWidget(self.font_combo)
        right_layout.addLayout(font_layout)

        # 阴影开关（放在字体下方）
        shadow_layout = QHBoxLayout()
        shadow_layout.addStretch()   # 推到右边，保持对齐
        self.shadow_checkbox = QCheckBox("文字阴影")
        self.shadow_checkbox.setChecked(True)   # 默认开启，可从配置读取
        self.shadow_checkbox.stateChanged.connect(self.onShadowToggled)
        shadow_layout.addWidget(self.shadow_checkbox)
        right_layout.addLayout(shadow_layout)

        # 使用 QSplitter 可拖拽调整左右比例
        self.splitter = QSplitter(Qt.Horizontal)
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

        if self.window_geometry:
            self.setGeometry(*self.window_geometry)
        else:
            default_w, default_h = 1024, 700
            self.resize(default_w, default_h)
            # 居中显示
            screen_geo = QApplication.primaryScreen().availableGeometry()
            x = (screen_geo.width() - default_w) // 2
            y = (screen_geo.height() - default_h) // 2
            self.move(x, y)
        # 初始化转盘字体
        self.wheel.setFontFamily(self.font_family)
        self.shadow_checkbox.setChecked(self.shadow_enabled)
        self.wheel.setShadowEnabled(self.shadow_enabled)

    # ================= 字体切换 =================
    def onFontChanged(self, font):
        """当字体选择框改变时，更新所有相关字体"""
        self.font_family = font.family()
        self.wheel.setFontFamily(self.font_family)
        # 同时更新结果标签的字体（保持大小 18px）
        self.result_label.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #333;"
        )
        self.setFont(font)
        self.result_label.setFont(font)
        self.saveData()

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
            self.updateGroupCombo()
        else:
            self.list_widget.clear()
            self.wheel.setItems([])
        self._updating_list = False

    def onGroupChanged(self, index):
        if index >= 0:
            self.current_group_index = index
            self.updateWheelFromCurrentGroup()
            self.saveData()

    def addGroup(self):
        name, ok = QInputDialog.getText(self, "添加分组", "分组名称:")
        if ok and name.strip():
            self.groups.append({'name': name.strip(), 'items': []})
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
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
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
        row = self.list_widget.currentRow()
        if row >= 0:
            del self.groups[self.current_group_index]['items'][row]
            self.updateWheelFromCurrentGroup()
            self.saveData()

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

    def shuffleItems(self):
        if self.groups and self.groups[self.current_group_index]['items']:
            random.shuffle(self.groups[self.current_group_index]['items'])
            self.updateWheelFromCurrentGroup()
            self.saveData()

    def clearItems(self):
        reply = QMessageBox.question(self, "清空", "确定清空所有项目吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.groups[self.current_group_index]['items'] = []
            self.updateWheelFromCurrentGroup()
            self.saveData()

    # ================= 旋转控制 =================
    def onSpinStarted(self):
        """旋转开始时禁用编辑"""
        self.left_panel.setEnabled(False)
        self.btn_spin.setEnabled(False)

    def onSpinFinished(self, index, text):
        """旋转结束时显示结果并恢复编辑"""
        self.result_label.setText(f"🎉 恭喜中奖: {text}")
        self.left_panel.setEnabled(True)
        self.btn_spin.setEnabled(True)

    def closeEvent(self, event):
        geo = self.geometry()
        self.window_geometry = [geo.x(), geo.y(), geo.width(), geo.height()]
        self.splitter_sizes = self.splitter.sizes()
        self.saveData()
        super().closeEvent(event)


if __name__ == "__main__":
    # 高 DPI 适配
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())