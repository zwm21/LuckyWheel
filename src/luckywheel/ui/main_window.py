"""主窗口 MainWindow（拆分自根级 main.py）。

职责：窗口装配（左栏编辑区 + 右栏转盘与抽取卡片）、数据读写、窗口几何
恢复，以及把各面板组织起来的编排逻辑。面板在 ui/panels/，纯绘制在
ui/wheel.py，主题在 ui/theme.py，启动期辅助在 ui/bootstrap.py。
"""

import os
import random

from PyQt6.QtCore import QEvent, QRect, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from luckywheel.core import paths as core_paths
from luckywheel.core import storage
from luckywheel.core.models import AppState, Group
from luckywheel.ui.bootstrap import loadEmbeddedFont, notify
from luckywheel.ui.panels import (
    DrawnPanel,
    GroupPanel,
    ItemsPanel,
    SettingsPanel,
    SpinPanel,
)
from luckywheel.ui.save_scheduler import SaveScheduler
from luckywheel.ui.wheel import SECTOR_COLORS, WheelWidget  # noqa: F401  (兼容旧导入路径)

# 保存去抖窗口：字号微调、批量抽取每轮等高频变更在此毫秒数内合并为一次
# 落盘；关闭窗口等不能丢数据的时机走 flushSave 立即写入
SAVE_DEBOUNCE_MS = 500


class MainWindow(QMainWindow):
    """主窗口：编辑面板 + 转盘"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("幸运大转盘")
        self.groups = []
        self.current_group_index = 0
        self._updating_list = False
        self.shadow_enabled = True  # 给一个默认值，loadData 会覆盖
        self.window_geometry = None
        self.splitter_sizes = None
        self.user_list_height = 200
        self.drawn_user_height = 120  # 抽出列表默认高度

        # 批量抽取相关：batch_remaining / batch_results 是 SpinPanel 的运行时
        # 状态（窗口以同名 property 转发，见下方 batch_remaining）
        self.batch_spin_count = 3  # 批量抽取默认次数
        self.theme = "light"  # 背景主题: light / dark / system
        self.last_result_index = None  # 最近一次中奖扇区的索引（按索引抽出的依据）

        # 保存去抖：saveData 只登记一次待保存变更，到点或 flushSave 才落盘
        self._scheduler = SaveScheduler(self, self._write_state, SAVE_DEBOUNCE_MS)

        # 数据文件路径：优先程序旁边（便携模式），不可写时回退用户数据目录
        data_path, relocated = core_paths.resolve_data_path()
        if relocated is not None:
            notify(self, f"数据文件将从 {relocated} 迁移到 {data_path}")
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

        # 扇区配色启动时随机化：只取默认池（ui.palette）的副本，不动共享的 tuple
        self._sector_colors = random.sample(SECTOR_COLORS, len(SECTOR_COLORS))

        self.initUI()
        self.updateWheelFromCurrentGroup()
        QApplication.styleHints().colorSchemeChanged.connect(
            self.settings_panel.onSystemThemeChanged
        )
        self._theme_applied = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._theme_applied:
            self._theme_applied = True
            QTimer.singleShot(0, self._applyTheme)

    def _applyTheme(self):
        """转调 SettingsPanel（showEvent 与测试都走这个窗口级入口）。"""
        self.settings_panel.applyTheme()

    def eventFilter(self, obj, event):
        # 监听列表视口的拖放事件
        if obj is self.list_widget.viewport() and event.type() == QEvent.Type.Drop:
            # 拖放完成后，使用 QTimer 确保列表数据已更新
            QTimer.singleShot(0, self.items_panel.onItemsReordered)
            return False
        return super().eventFilter(obj, event)

    # ---- 抽出项目：转调 DrawnPanel（保留窗口级入口：外部调用方与编排代码都用它）----
    def updateDrawnList(self):
        self.drawn_panel.updateDrawnList()

    def extractDrawnItem(self):
        self.drawn_panel.extractDrawnItem()

    def updateExtractButtonState(self):
        self.spin_panel.updateExtractButtonState()

    def startBatchSpin(self):
        """转调 SpinPanel（verify_gui 直接调用这个窗口级入口）。"""
        self.spin_panel.startBatchSpin()

    def stopBatchSpin(self):
        self.spin_panel.stopBatchSpin()

    def stopSingleSpin(self):
        self.spin_panel.stopSingleSpin()

    def onSpinFinished(self, index, text):
        self.spin_panel.onSpinFinished(index, text)

    @property
    def batch_remaining(self):
        return self.spin_panel.batch_remaining

    @batch_remaining.setter
    def batch_remaining(self, value):
        self.spin_panel.batch_remaining = value

    def applyUIFont(self):
        """转调 SettingsPanel（契约方法：测试与窗口初始化都走这个入口）。"""
        self.settings_panel.applyUIFont()

    def applyWheelFont(self):
        self.settings_panel.applyWheelFont()

    # ================= 数据持久化 =================
    def loadData(self):
        state, warnings = storage.load_state(self.data_file)
        for w in warnings:
            notify(self, w, title="数据提示")
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
        self._scheduler.schedule()

    def flushSave(self):
        """取消待发的定时器并立即落盘。"""
        self._scheduler.flush_now()

    def _current_height(self, widget_name, fallback):
        """列表控件已建成时存实际显示高度（所见即所得），否则存上次的配置值。"""
        widget = getattr(self, widget_name, None)
        return fallback if widget is None else widget.height()

    def _write_state(self):
        """把当前状态序列化落盘（去抖到点或 flushSave 时调用）。"""
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
                list_height=self._current_height("list_widget", self.user_list_height),
                drawn_list_height=self._current_height("drawn_list_widget", self.drawn_user_height),
                batch_spin_count=self.batch_spin_count,
                theme=self.theme,
            )
            storage.save_state(self.data_file, state)
        except Exception as e:
            notify(self, f"保存失败: {e}", title="保存失败")

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

        # 分组管理：控件与行为在 GroupPanel，布局归本方法；group_combo 转发保契约可达
        self.group_panel = GroupPanel(self)
        self.group_combo = self.group_panel.group_combo
        group_layout = QHBoxLayout()
        group_layout.addWidget(QLabel("分组:"))
        group_layout.addWidget(self.group_panel.group_combo)
        group_layout.addWidget(self.group_panel.btn_add)
        group_layout.addWidget(self.group_panel.btn_del)
        left_layout.addLayout(group_layout)
        left_layout.addWidget(self.group_panel.btn_rename)

        left_layout.addWidget(QLabel("抽签项目 (可拖拽排序):"))

        # 项目编辑：控件与行为在 ItemsPanel；list_widget 转发保契约可达
        self.items_panel = ItemsPanel(self)
        self.list_widget = self.items_panel.list_widget
        self.list_widget.viewport().installEventFilter(self)
        # 列表本体由下方 QSplitter 组装（含抽出列表共三个窗格）

        # ===== 下方固定区域（按钮 + 抽出项目 + 抽出操作） =====
        self.bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(self.bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(4)

        # --- 项目编辑按钮 ---
        item_btn_layout = QHBoxLayout()
        item_btn_layout.addWidget(self.items_panel.btn_add)
        item_btn_layout.addWidget(self.items_panel.btn_del)
        item_btn_layout.addWidget(self.items_panel.btn_edit)
        bottom_layout.addLayout(item_btn_layout)

        bottom_layout.addWidget(self.items_panel.btn_batch_import)
        bottom_layout.addWidget(self.items_panel.btn_shuffle)
        bottom_layout.addWidget(self.items_panel.btn_edit_all)
        bottom_layout.addWidget(self.items_panel.btn_clear)

        # --- 抽出项目区域：控件与行为在 DrawnPanel；drawn_list_widget 转发保契约可达 ---
        bottom_layout.addWidget(QLabel("抽出项目:"))
        self.drawn_panel = DrawnPanel(self)
        self.drawn_list_widget = self.drawn_panel.drawn_list_widget

        # 垂直 QSplitter 取代手写 SplitterHandle：两个列表的高度拖动与越界
        # 钳制全部交给 QSplitter；保存的高度在关窗时由 list_widget.height() 落盘
        self.list_splitter = QSplitter(Qt.Orientation.Vertical)
        self.list_splitter.setChildrenCollapsible(False)
        self.list_splitter.addWidget(self.list_widget)
        self.list_splitter.addWidget(self.bottom_widget)
        self.list_splitter.addWidget(self.drawn_list_widget)
        self.list_splitter.setSizes([self.user_list_height, 220, self.drawn_user_height])
        left_layout.addWidget(self.list_splitter, 1)
        left_layout.addWidget(self.drawn_panel.btn_widget)

        # ----- 右侧转盘区域 -----
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(6)
        self.wheel = WheelWidget()
        self.wheel.setSectorColors(self._sector_colors)
        # 旋转与抽取卡片：控件与行为在 SpinPanel；下方同名属性转发供
        # ui/theme.py、verify_gui 与测试按 window.xxx 访问（同一对象）
        self.spin_panel = SpinPanel(self)
        self.result_label = self.spin_panel.result_label
        self.single_frame = self.spin_panel.single_frame
        self.single_title = self.spin_panel.single_title
        self.batch_frame = self.spin_panel.batch_frame
        self.batch_title = self.spin_panel.batch_title
        self.batch_log_label = self.spin_panel.batch_log_label
        self.batch_spinbox = self.spin_panel.batch_spinbox
        self.btn_spin = self.spin_panel.btn_spin
        self.btn_extract = self.spin_panel.btn_extract
        self.btn_stop_single = self.spin_panel.btn_stop_single
        self.btn_batch_spin = self.spin_panel.btn_batch_spin
        self.btn_stop_batch = self.spin_panel.btn_stop_batch
        self.wheel.spinStarted.connect(self.spin_panel.onSpinStarted)
        self.wheel.spinFinished.connect(self.spin_panel.onSpinFinished)
        # 转盘吸收所有剩余高度并保持内部圆形比例（min side 决定绘制半径）
        right_layout.addWidget(self.wheel, 1)
        right_layout.addWidget(self.spin_panel.result_label)
        right_layout.addWidget(self.spin_panel.single_frame)

        # ----- 底部两栏：左=批量抽取卡片，右=设置控件列 -----
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.addWidget(self.spin_panel.batch_frame, 1)

        # 右：设置控件列（控件在 SettingsPanel）；theme_combo 等转发保契约可达
        self.settings_panel = SettingsPanel(self)
        self.theme_combo = self.settings_panel.theme_combo
        self.shadow_checkbox = self.settings_panel.shadow_checkbox
        settings_column = QVBoxLayout()
        settings_column.setSpacing(4)
        settings_column.addLayout(self.settings_panel.ui_font_layout)
        settings_column.addLayout(self.settings_panel.wheel_font_layout)
        settings_column.addLayout(self.settings_panel.theme_layout)

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
            self.splitter.setSizes([250, 600])  # 初始左侧 250px，右侧占剩余

        main_layout.addWidget(self.splitter)

        self.setMinimumSize(850, 600)

        self._applyWindowGeometry()
        self.shadow_checkbox.setChecked(self.shadow_enabled)
        self.wheel.setShadowEnabled(self.shadow_enabled)

        self.spin_panel.btn_extract.setEnabled(False)  # 初始无结果，禁用
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
    def updateWheelFromCurrentGroup(self):
        """用当前分组数据刷新界面"""
        self._updating_list = True
        if 0 <= self.current_group_index < len(self.groups):
            items = self.groups[self.current_group_index]["items"]
            self.list_widget.clear()
            self.list_widget.addItems(items)
            self.wheel.setItems(items)
            self.result_label.setText("")
            self.last_result_index = None  # 数据已刷新，旧索引失效
            self.group_panel.updateGroupCombo()
        else:
            self.list_widget.clear()
            self.wheel.setItems([])
        self._updating_list = False

        self.updateDrawnList()
        self.updateExtractButtonState()
        self.spin_panel._updateBatchButtonState()

    def closeEvent(self, event):
        geo = self.geometry()
        self.window_geometry = [geo.x(), geo.y(), geo.width(), geo.height()]
        self.splitter_sizes = self.splitter.sizes()
        self.flushSave()  # 关窗不能丢数据：绕过去抖立即落盘
        super().closeEvent(event)
