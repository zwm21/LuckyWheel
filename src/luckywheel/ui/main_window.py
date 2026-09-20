"""主窗口 MainWindow（拆分自根级 main.py）。

职责：分组与项目的增删改查、抽出/放回、单次与不放回批量抽取的编排、
字体与主题的应用、数据读写（core.storage）与窗口几何恢复。

纯绘制在 ui/wheel.py，主题在 ui/theme.py，算法在 core/。
"""


import os
import random
import sys

from PyQt6.QtCore import QEvent, QRect, Qt, QTimer
from PyQt6.QtGui import (
    QFont,
    QFontDatabase,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFontComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from luckywheel.core import paths as core_paths
from luckywheel.core import storage
from luckywheel.core.models import AppState, Group
from luckywheel.ui import theme as ui_theme
from luckywheel.ui.wheel import SECTOR_COLORS, WheelWidget  # noqa: F401  (兼容旧导入路径)

# 保存去抖窗口：字号微调、批量抽取每轮、拖拽排序等高频变更在此毫秒数内
# 合并为一次落盘；关闭窗口等不能丢数据的时机走 flushSave 立即写入
SAVE_DEBOUNCE_MS = 500


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
            palette = ui_theme.dark_palette() if is_dark else ui_theme.light_palette()
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
    def _isSystemDark(self):
        return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark

    def _applyTheme(self):
        """浅色=显式浅色调色板 / 深色=暗色调色板 / 跟随系统=检测。

        样式与调色板收敛在 ui.theme（颜色 token + 单份 QSS 模板）；
        本方法只负责解析主题名并把窗口交给它。注意列表类控件不设 QSS，
        见 ui/theme.py 模块 docstring 的滚动条约束。
        """
        dark = self.theme == "dark" or (self.theme == "system" and self._isSystemDark())
        ui_theme.apply_theme(self, dark)
        self._initLowerAreaColors(is_dark=dark)

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
                list_height=(
                    self.list_widget.height()
                    if hasattr(self, 'list_widget') else self.user_list_height
                ),
                drawn_list_height=(
                    self.drawn_list_widget.height()
                    if hasattr(self, 'drawn_list_widget') else self.drawn_user_height
                ),
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

        # 可拖拽排序的项目列表（高度由下方 QSplitter 管理）
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.model().layoutChanged.connect(self.onItemsReordered)
        self.list_widget.itemDoubleClicked.connect(self.editItem)
        self.list_widget.viewport().installEventFilter(self)
        # 列表本体由下方 QSplitter 组装（含抽出列表共三个窗格）

        # ===== 下方固定区域（按钮 + 抽出项目 + 抽出操作） =====
        self.bottom_widget = QWidget()
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
        # 不给带滚动条的控件单独设 QSS：会切到 QStyleSheetStyle 渲染，
        # 导致滚动条不跟随 Fusion + palette，浅色主题下出现深色滚动条。
        self.drawn_list_widget.itemSelectionChanged.connect(self.updateDrawnButtonsState)
        self.drawn_list_widget.itemDoubleClicked.connect(self.editDrawnItem)

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

        # 垂直 QSplitter 取代手写 SplitterHandle：两个列表的高度拖动、
        # 越界钳制全部交给 QSplitter；保存的高度在关闭窗口时由
        # list_widget.height() / drawn_list_widget.height() 落盘
        self.list_splitter = QSplitter(Qt.Orientation.Vertical)
        self.list_splitter.setChildrenCollapsible(False)
        self.list_splitter.addWidget(self.list_widget)
        self.list_splitter.addWidget(self.bottom_widget)
        self.list_splitter.addWidget(self.drawn_list_widget)
        self.list_splitter.setSizes([self.user_list_height, 220, self.drawn_user_height])
        left_layout.addWidget(self.list_splitter, 1)
        left_layout.addWidget(drawn_btn_widget)

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
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_label.setFont(QFont(self.ui_font_family, self.ui_font_size, QFont.Weight.Bold))
        # 卡片样式不一在此处硬编码：_applyTheme 在 showEvent 统一应用
        # （ui/theme.py 的颜色 token + 单份模板）
        right_layout.addWidget(self.result_label)

        # ----- 单次抽取卡片 -----
        self.single_frame = QFrame()
        single_layout = QVBoxLayout(self.single_frame)
        single_layout.setContentsMargins(8, 4, 8, 4)
        single_layout.setSpacing(4)

        self.single_title = QLabel("单次抽取")
        self.single_title.setFont(QFont(self.ui_font_family, self.ui_font_size, QFont.Weight.Bold))
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
        self.btn_spin.setStyleSheet(
            "background-color: #FF6B6B; color: white; font-weight: bold;")
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
        batch_layout = QVBoxLayout(self.batch_frame)
        batch_layout.setContentsMargins(8, 4, 8, 4)
        batch_layout.setSpacing(4)

        self.batch_title = QLabel("不放回批量抽取")
        self.batch_title.setFont(QFont(self.ui_font_family, self.ui_font_size, QFont.Weight.Bold))
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
        self.btn_batch_spin.setStyleSheet(
            "background-color: #FF6B6B; color: white; font-weight: bold;")
        self.btn_batch_spin.clicked.connect(self.startBatchSpin)
        batch_ctrl_layout.addWidget(self.btn_batch_spin, 1)
        self.btn_stop_batch = QPushButton("停止")
        self.btn_stop_batch.setEnabled(False)
        self.btn_stop_batch.clicked.connect(self.stopBatchSpin)
        batch_ctrl_layout.addWidget(self.btn_stop_batch)
        batch_layout.addLayout(batch_ctrl_layout)

        self.batch_log_label = QLabel("")
        self.batch_log_label.setFont(QFont(self.ui_font_family, self.ui_font_size))
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
        reply = QMessageBox.question(
            self, "清空", "确定清空当前分组的所有项目吗？\n（抽出项目也将一并清空）",
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

