import sys
import json
import random
import math
import os

from PyQt5.QtCore import (Qt, QTimer, QRectF, QPointF, pyqtSignal,
                          QPropertyAnimation, QEasingCurve)
from PyQt5.QtGui import QPainter, QColor, QFont, QPen, QBrush, QPolygonF, QPainterPath
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QComboBox, QFileDialog,
                             QMessageBox, QSplitter, QInputDialog, QSizePolicy,
                             QAbstractItemView)

# 转盘扇区颜色池
SECTOR_COLORS = [
    QColor("#FF6B6B"), QColor("#4ECDC4"), QColor("#45B7D1"),
    QColor("#96CEB4"), QColor("#FFEAA7"), QColor("#DDA0DD"),
    QColor("#98D8C8"), QColor("#F7DC6F"), QColor("#BB8FCE"),
    QColor("#85C1E9"), QColor("#F8C471"), QColor("#82E0AA"),
    QColor("#F1948A"), QColor("#85929E"), QColor("#AED6F1"),
    QColor("#E8DAEF"), QColor("#A3E4D7"), QColor("#FAD7A0"),
    QColor("#D5F5E3"), QColor("#F9E79F"), QColor("#ABEBC6")
]


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

        self.setMinimumSize(350, 350)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def setItems(self, items):
        """设置转盘项目"""
        self.items = items
        self.rotation = 0.0
        self.angular_velocity = 0.0
        self.spinning = False
        self.update()

    def startSpin(self, initial_velocity=None):
        """开始旋转，initial_velocity 可选，非正值则自动随机"""
        if self.spinning or len(self.items) == 0:
            return
        # 确保初速度是一个正数，否则随机
        if not isinstance(initial_velocity, (int, float)) or initial_velocity <= 0:
            initial_velocity = random.uniform(600, 1500)  # 稍大一些更带劲
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
        """绘制转盘——完美版：独立计算文字全局坐标，避免嵌套变换导致的裁剪"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
    
        side = min(self.width(), self.height())
        wheel_diameter = side * 0.88
        radius = wheel_diameter / 2.0
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
    
        if len(self.items) == 0:
            painter.setPen(QPen(Qt.black, 1))
            painter.drawText(QRectF(center.x() - 60, center.y() - 10, 120, 20),
                             Qt.AlignCenter, "请添加项目")
            return
    
        num = len(self.items)
        sector_span = 360.0 / num
        rot_rad = math.radians(self.rotation)  # 当前转盘旋转角度（弧度）
    
        # ---------- 第 1 步：绘制扇形和装饰（使用内部变换） ----------
        painter.save()
        painter.translate(center)
        painter.rotate(self.rotation)
    
        for i in range(num):
            start_angle = i * sector_span
            span_angle = sector_span
    
            # 扇形
            color = SECTOR_COLORS[i % len(SECTOR_COLORS)]
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(Qt.white, 2))
            path = QPainterPath()
            path.moveTo(0, 0)
            path.arcTo(QRectF(-radius, -radius, radius * 2, radius * 2),
                       start_angle, span_angle)
            path.lineTo(0, 0)
            painter.drawPath(path)
    
        # 中心装饰（在旋转坐标系内画，但装饰不旋转也没关系，我们这里也画上）
        # 注意：中心装饰最好不要旋转，所以我们回到 widget 坐标系再画
        painter.restore()  # 退出扇形绘制变换
    
        # ---------- 第 2 步：绘制文字（在 widget 原生坐标系，避免裁剪） ----------
        # 预先计算每个文字的位置、角度和尺寸
        text_radius = radius * 0.62          # 文字离圆心距离
    
        for i, item in enumerate(self.items):
            # 扇区中线在未旋转转盘中的角度
            mid_angle_deg = i * sector_span + sector_span / 2.0
            mid_angle_rad = math.radians(mid_angle_deg)
    
            # 在未旋转转盘坐标系中的文字位置
            lx = text_radius * math.cos(mid_angle_rad)
            ly = text_radius * math.sin(mid_angle_rad)
    
            # 应用转盘旋转 rot_rad，得到在 widget 坐标系下的位置（相对于中心）
            cos_r = math.cos(rot_rad)
            sin_r = math.sin(rot_rad)
            global_x = center.x() + (lx * cos_r - ly * sin_r)
            global_y = center.y() + (lx * sin_r + ly * cos_r)
    
            # 文字绘制的旋转角度 = 扇区中线角度 + 转盘旋转角度
            final_angle_deg = mid_angle_deg + self.rotation
    
            # 动态字体大小（确保不溢出 widget）
            font = QFont()
            font.setBold(True)
            init_size = max(10, int(radius * 0.18))
            font.setPixelSize(init_size)
            painter.setFont(font)
            fm = painter.fontMetrics()
            # 允许的最大宽度和高度（基于到转盘边缘的距离和 widget 边界）
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
    
            # 绘制文字（带背景块增强可读性）
            painter.save()
            # 移动到全局位置，并旋转到径向朝外
            painter.translate(global_x, global_y)
            painter.rotate(final_angle_deg)
    
            # 文字矩形（x轴正向为径向朝外）
            rect = QRectF(-text_w / 2, -text_h / 2, text_w, text_h)
    
            # 半透明白色背景
            #bg = QColor(255, 255, 255, 180)
            #painter.fillRect(rect, bg)
    
            # 文字颜色（与扇区颜色对比）
            color = SECTOR_COLORS[i % len(SECTOR_COLORS)]
            text_color = Qt.black if color.lightness() > 150 else Qt.white
            painter.setPen(text_color)
            # 阴影绘制（向右下偏移 1 像素）
            painter.setPen(QColor(0, 0, 0, 120))  # 半透明黑色阴影
            painter.drawText(rect.translated(1, 1), Qt.AlignCenter, item)

            painter.drawText(rect, Qt.AlignCenter, item)
    
            painter.restore()
    
        # ---------- 第 3 步：绘制固定元素（中心圆、指针） ----------
        # 中心圆（不旋转）
        painter.save()
        painter.translate(center)
        painter.setBrush(QBrush(QColor("#333333")))
        painter.setPen(QPen(Qt.white, 2))
        painter.drawEllipse(QPointF(0, 0), radius * 0.15, radius * 0.15)
        painter.setBrush(QBrush(QColor("#555555")))
        painter.drawEllipse(QPointF(0, 0), radius * 0.1, radius * 0.1)
        painter.setPen(QPen(Qt.white, 1))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(int(radius * 0.08))
        painter.setFont(font)
        painter.drawText(QRectF(-radius * 0.1, -radius * 0.1, radius * 0.2, radius * 0.2),
                         Qt.AlignCenter, "GO")
        painter.restore()
    
        # 指针（固定在顶部）
        painter.save()
        pointer_tip = QPointF(center.x(), center.y() - radius + 5)
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
        self.groups = []               # 分组列表 [{'name':..., 'items':[...]}, ...]
        self.current_group_index = 0
        self._updating_list = False    # 防止界面更新时重复触发事件

        # 数据文件路径（兼容打包后的 exe）
        if getattr(sys, 'frozen', False):
            app_dir = os.path.dirname(sys.executable)
        else:
            app_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_file = os.path.join(app_dir, "wheel_data.json")

        self.loadData()
        self.initUI()
        self.updateWheelFromCurrentGroup()

    # ================= 数据持久化 =================
    def loadData(self):
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.groups = data.get('groups', [])
                self.current_group_index = data.get('current_group', 0)
                if not self.groups:
                    self.groups.append({'name': '默认分组', 'items': ['选项1', '选项2', '选项3']})
                    self.current_group_index = 0
        except (FileNotFoundError, json.JSONDecodeError):
            self.groups = [{'name': '默认分组', 'items': ['选项1', '选项2', '选项3']}]
            self.current_group_index = 0
            self.saveData()

    def saveData(self):
        try:
            data = {
                'groups': self.groups,
                'current_group': self.current_group_index
            }
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
        self.left_panel.setFixedWidth(300)

        # 分组管理
        group_layout = QHBoxLayout()
        group_layout.addWidget(QLabel("分组:"))
        self.group_combo = QComboBox()
        self.group_combo.currentIndexChanged.connect(self.onGroupChanged)
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

        # 使用 QSplitter 可拖拽调整左右比例
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter)

        self.setMinimumSize(850, 600)

    # ================= 分组管理 =================
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