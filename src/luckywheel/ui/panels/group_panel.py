"""分组管理面板：下拉框 + 增 / 删 / 重命名。

布局仍在 MainWindow.initUI：分组行（标签 + 下拉 + 两个小按钮）与
重命名按钮分处两行，面板只把控件暴露出来，不自己拼布局。
"""

from PyQt6.QtWidgets import QComboBox, QInputDialog, QMessageBox, QPushButton, QSizePolicy

from luckywheel.ui.panels.base import Panel


class GroupPanel(Panel):
    def __init__(self, window, parent=None):
        super().__init__(window, parent)
        self.group_combo = QComboBox()
        self.group_combo.currentIndexChanged.connect(self.onGroupChanged)
        self.group_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.btn_add = QPushButton("+")
        self.btn_add.setMaximumWidth(30)
        self.btn_add.clicked.connect(self.addGroup)

        self.btn_del = QPushButton("-")
        self.btn_del.setMaximumWidth(30)
        self.btn_del.clicked.connect(self.deleteGroup)

        self.btn_rename = QPushButton("重命名分组")
        self.btn_rename.clicked.connect(self.renameGroup)

    def updateGroupCombo(self):
        """重建下拉框条目并选中当前分组（blockSignals 防止联动刷新）。"""
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        for group in self.groups:
            self.group_combo.addItem(group["name"])
        self.group_combo.setCurrentIndex(self.window.current_group_index)
        self.group_combo.blockSignals(False)

    def onGroupChanged(self, index):
        if index >= 0:
            self.window.current_group_index = index
            self.refresh_from_group()
            self.refresh_extract_state()
            self.save()

    def addGroup(self):
        name, ok = QInputDialog.getText(self.window, "添加分组", "分组名称:")
        if ok and name.strip():
            self.groups.append({"name": name.strip(), "items": [], "drawn_items": []})
            self.window.current_group_index = len(self.groups) - 1
            self.refresh_from_group()
            self.save()

    def deleteGroup(self):
        if len(self.groups) <= 1:
            QMessageBox.warning(self.window, "提示", "至少保留一个分组")
            return
        reply = QMessageBox.question(
            self.window,
            "删除分组",
            f"确定删除分组 '{self.groups[self.window.current_group_index]['name']}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self.groups[self.window.current_group_index]
            if self.window.current_group_index >= len(self.groups):
                self.window.current_group_index = len(self.groups) - 1
            self.refresh_from_group()
            self.save()

    def renameGroup(self):
        if not self.groups:
            return
        name, ok = QInputDialog.getText(
            self.window,
            "重命名分组",
            "新名称:",
            text=self.groups[self.window.current_group_index]["name"],
        )
        if ok and name.strip():
            self.groups[self.window.current_group_index]["name"] = name.strip()
            self.updateGroupCombo()
            self.save()
