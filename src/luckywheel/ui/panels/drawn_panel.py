"""抽出项目面板：抽出列表 + 返回 / 删除 / 编辑，以及抽签结果的抽出动作。

布局仍在 MainWindow.initUI：抽出列表是 list_splitter 的第三个窗格，
两个操作按钮固定在 splitter 下方，面板不自封装这部分布局
（见 panels/__init__.py 的拆分约定）。

「抽出」按钮本身属于右侧单次抽取卡片，由 MainWindow 编排；
本面板只提供它调用的 extractDrawnItem（把中奖项从抽签池移出）。
"""

from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from luckywheel.ui.panels.base import Panel


class DrawnPanel(Panel):
    def __init__(self, window, parent=None):
        super().__init__(window, parent)

        # 不给带滚动条的控件单独设 QSS：会切到 QStyleSheetStyle 渲染，
        # 导致滚动条不跟随 Fusion + palette，浅色主题下出现深色滚动条。
        self.drawn_list_widget = QListWidget()
        self.drawn_list_widget.itemSelectionChanged.connect(self.updateDrawnButtonsState)
        self.drawn_list_widget.itemDoubleClicked.connect(self.editDrawnItem)

        self.btn_return_drawn = QPushButton("返回项目")
        self.btn_return_drawn.setEnabled(False)
        self.btn_return_drawn.clicked.connect(self.returnDrawnItem)
        self.btn_delete_drawn = QPushButton("删除项目")
        self.btn_delete_drawn.setEnabled(False)
        self.btn_delete_drawn.clicked.connect(self.deleteDrawnItem)

        self.btn_widget = QWidget()
        self.btn_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        btn_layout = QHBoxLayout(self.btn_widget)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addWidget(self.btn_return_drawn)
        btn_layout.addWidget(self.btn_delete_drawn)

    def updateDrawnList(self):
        """刷新抽出项目列表"""
        if self.group is not None:
            drawn_items = self.group.get("drawn_items", [])
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

    def extractDrawnItem(self):
        """将抽签结果移出到抽出项目列表（按索引 pop，重复文本不会误删）"""
        if not self.groups:
            return
        index = self.window.last_result_index
        group = self.group
        if index is None or not 0 <= index < len(group["items"]):
            return
        item_text = group["items"].pop(index)
        group.setdefault("drawn_items", []).append(item_text)
        # 刷新会一并清理 last_result_index，抽出按钮随之禁用
        self.refresh_from_group()
        self.save()

    def returnDrawnItem(self):
        """将选中的抽出项目返回至抽签项目列表"""
        if not self.groups:
            return
        group = self.group
        if self.drawn_list_widget.currentItem() is None:
            return
        current_row = self.drawn_list_widget.currentRow()
        total_rows = self.drawn_list_widget.count()

        # 计算下一个要选中的行号
        next_row = -1
        if total_rows > 1:
            if current_row == total_rows - 1:
                next_row = current_row - 1  # 最后一项 → 上一项
            else:
                next_row = current_row  # 否则选正下方

        # 执行移除（按索引，重复文本不会误删）
        if 0 <= current_row < len(group["drawn_items"]):
            item_text = group["drawn_items"][current_row]
            del group["drawn_items"][current_row]
            group["items"].append(item_text)
            self.refresh_from_group()  # 内部会重建列表并刷新按钮状态

            # 按索引直接选中（refresh 后列表已缩短，需钳制）
            if next_row >= 0 and self.drawn_list_widget.count() > 0:
                if next_row >= self.drawn_list_widget.count():
                    next_row = self.drawn_list_widget.count() - 1
                self.drawn_list_widget.setCurrentRow(next_row)
            self.save()

    def deleteDrawnItem(self):
        """删除选中的抽出项目"""
        if not self.groups:
            return
        group = self.group
        if self.drawn_list_widget.currentItem() is None:
            return
        current_row = self.drawn_list_widget.currentRow()
        total_rows = self.drawn_list_widget.count()

        next_row = -1
        if total_rows > 1:
            if current_row == total_rows - 1:
                next_row = current_row - 1
            else:
                next_row = current_row

        if 0 <= current_row < len(group["drawn_items"]):
            del group["drawn_items"][current_row]
            self.updateDrawnList()  # 刷新

            if next_row >= 0 and self.drawn_list_widget.count() > 0:
                if next_row >= self.drawn_list_widget.count():
                    next_row = self.drawn_list_widget.count() - 1
                self.drawn_list_widget.setCurrentRow(next_row)
            self.save()

    def editDrawnItem(self, item=None):
        """双击编辑抽出项目"""
        if not self.groups:
            return
        row = self.drawn_list_widget.currentRow()
        group = self.group
        if row < 0 or row >= len(group.get("drawn_items", [])):
            return
        old_text = group["drawn_items"][row]

        dlg = QDialog(self.window)
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
                group["drawn_items"][row] = new_text
                self.updateDrawnList()
                self.save()
