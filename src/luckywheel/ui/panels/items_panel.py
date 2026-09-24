"""项目编辑面板：项目列表 + 增删改、批量导入、打乱、清空。

布局仍在 MainWindow.initUI：列表与这排按钮同处 list_splitter 的
bottom_widget 窗格，但 bottom_widget 还装着抽出列表上方的按钮组，
面板不自封装布局（见 panels/__init__.py 的拆分约定）。
"""

import random

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
)

from luckywheel.ui.panels.base import Panel


class ItemsPanel(Panel):
    def __init__(self, window, parent=None):
        super().__init__(window, parent)

        # 可拖拽排序的项目列表（高度由 list_splitter 管理）
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.model().layoutChanged.connect(self.onItemsReordered)
        self.list_widget.itemDoubleClicked.connect(self.editItem)
        # 拖放结束的监听由 MainWindow.eventFilter 安装（跨切面的窗口级过滤器）

        self.btn_add = QPushButton("添加")
        self.btn_add.clicked.connect(self.addItem)
        self.btn_del = QPushButton("删除")
        self.btn_del.clicked.connect(self.deleteItem)
        self.btn_edit = QPushButton("编辑")
        self.btn_edit.clicked.connect(self.editItem)
        self.btn_batch_import = QPushButton("批量导入")
        self.btn_batch_import.clicked.connect(self.batchAddItems)
        self.btn_shuffle = QPushButton("随机打乱顺序")
        self.btn_shuffle.clicked.connect(self.shuffleItems)
        self.btn_edit_all = QPushButton("编辑所有项目")
        self.btn_edit_all.clicked.connect(self.editAllItems)
        self.btn_clear = QPushButton("清空项目")
        self.btn_clear.clicked.connect(self.clearItems)

    def addItem(self):
        if not self.groups:
            return
        text, ok = QInputDialog.getText(self.window, "添加项目", "项目文字:")
        if ok and text.strip():
            self.group["items"].append(text.strip())
            self.refresh_from_group()
            self.save()

    def batchAddItems(self):
        if not self.groups:
            return
        text, ok = QInputDialog.getMultiLineText(self.window, "批量导入", "每行一个项目:")
        if ok and text.strip():
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines:
                self.group["items"].extend(lines)
                self.refresh_from_group()
                self.save()

    def deleteItem(self):
        if not self.groups:
            return
        group = self.group
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(group["items"]):
            return
        current_row = row
        total_items = len(group["items"])
        # 计算下一个要选中的行号
        next_row = -1
        if total_items > 1:
            if current_row == total_items - 1:  # 最后一项 → 选上一项
                next_row = current_row - 1
            else:  # 否则选正下方（删除后原下一项会占据当前行）
                next_row = current_row
        # 执行删除
        del group["items"][row]
        self.refresh_from_group()  # 刷新列表
        self.save()
        # 自动选中下一个项目
        if next_row >= 0 and self.list_widget.count() > 0:
            if next_row >= self.list_widget.count():
                next_row = self.list_widget.count() - 1
            self.list_widget.setCurrentRow(next_row)

    def editItem(self, item=None):
        if not self.groups:
            return
        if isinstance(item, QListWidgetItem):
            row = self.list_widget.row(item)
        else:
            row = self.list_widget.currentRow()
        items = self.group["items"]
        if row >= 0 and row < len(items):
            old_text = items[row]
            text, ok = QInputDialog.getText(self.window, "编辑项目", "修改文字:", text=old_text)
            if ok and text.strip():
                items[row] = text.strip()
                self.refresh_from_group()
                self.save()

    def editAllItems(self):
        """编辑当前分组的所有项目（每行一个）"""
        if not self.groups:
            return
        # 将当前项目列表拼成多行文本
        current_text = "\n".join(self.group["items"])
        text, ok = QInputDialog.getMultiLineText(
            self.window, "编辑所有项目", "每行一个项目（可添加、删除、修改）:", text=current_text
        )
        if ok:
            # 按行分割，过滤空行
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            self.group["items"] = lines
            self.refresh_from_group()
            self.save()

    def shuffleItems(self):
        if self.group and self.group["items"]:
            random.shuffle(self.group["items"])
            self.refresh_from_group()
            self.save()

    def clearItems(self):
        if not self.groups:
            return
        reply = QMessageBox.question(
            self.window,
            "清空",
            "确定清空当前分组的所有项目吗？\n（抽出项目也将一并清空）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.group["items"] = []
            self.group["drawn_items"] = []
            self.refresh_from_group()
            self.save()

    def onItemsReordered(self):
        """拖拽排序后同步数据。

        顺序一变，上一轮的中奖结果就失效了：last_result_index 是扇区下标，
        排序后同一扇区下已经换成别的项目——留着它，结果标签仍显示旧中奖项，
        而「抽出」会按旧下标 pop 掉另一个项目。与
        MainWindow.updateWheelFromCurrentGroup 的处理保持一致（那条路径本来
        就清，只是拖拽排序不走它）。
        """
        if self.window.updating_list:
            return
        items = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        if items != self.group["items"]:
            self.group["items"] = items
            self.window.wheel.setItems(items)
            self.window.last_result_index = None
            self.window.result_label.setText("")
            self.save()
            self.refresh_extract_state()
