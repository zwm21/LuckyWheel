"""旋转与抽取面板：单次抽取卡片、不放回批量抽取卡片与结果标签。

这一块耦合最深：它要按索引弹出中奖项（经 window.groups）、刷新转盘
（window.updateWheelFromCurrentGroup）、整块禁用左栏（window.left_panel），
并驱动转盘启停。因此控件归面板，状态与跨切面动作仍走 window
（batch_remaining / last_result_index / groups 都是窗口级运行时状态）。

「抽出」按钮在物理上属于单次抽取卡片，语义上属于抽出项目，点击后
执行 DrawnPanel.extractDrawnItem；窗口只在两边之间转发。
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from luckywheel.ui.panels.base import Panel


class SpinPanel(Panel):
    def __init__(self, window, parent=None):
        super().__init__(window, parent)

        # 批量抽取的运行时状态（窗口以同名属性转发，verify_gui 与测试要读）
        self.batch_remaining = 0  # 剩余次数
        self.batch_results = []  # 已抽结果日志

        # --- 结果标签（位于单次抽取卡片上方） ---
        self.result_label = QLabel("")
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_label.setFont(
            QFont(window.ui_font_family, window.ui_font_size, QFont.Weight.Bold)
        )
        # 卡片样式不在此处硬编码：_applyTheme 在 showEvent 统一应用
        # （ui/theme.py 的颜色 token + 单份模板）

        # --- 单次抽取卡片 ---
        self.single_frame = QFrame()
        single_layout = QVBoxLayout(self.single_frame)
        single_layout.setContentsMargins(8, 4, 8, 4)
        single_layout.setSpacing(4)

        self.single_title = QLabel("单次抽取")
        self.single_title.setFont(
            QFont(window.ui_font_family, window.ui_font_size, QFont.Weight.Bold)
        )
        single_layout.addWidget(self.single_title)

        spin_layout = QHBoxLayout()
        spin_layout.setSpacing(8)

        self.btn_extract = QPushButton("抽出")
        self.btn_extract.setFixedHeight(38)
        self.btn_extract.setMaximumWidth(72)
        self.btn_extract.clicked.connect(window.drawn_panel.extractDrawnItem)
        spin_layout.addWidget(self.btn_extract)

        self.btn_spin = QPushButton("开始旋转")
        self.btn_spin.setMinimumHeight(38)
        self.btn_spin.setStyleSheet("background-color: #FF6B6B; color: white; font-weight: bold;")
        self.btn_spin.setToolTip("或点击转盘中心的 GO 按钮")
        self.btn_spin.clicked.connect(lambda: window.wheel.startSpin())
        spin_layout.addWidget(self.btn_spin, 1)

        single_layout.addLayout(spin_layout)

        # --- 不放回批量抽取卡片 ---
        self.batch_frame = QFrame()
        batch_layout = QVBoxLayout(self.batch_frame)
        batch_layout.setContentsMargins(8, 4, 8, 4)
        batch_layout.setSpacing(4)

        self.batch_title = QLabel("不放回批量抽取")
        self.batch_title.setFont(
            QFont(window.ui_font_family, window.ui_font_size, QFont.Weight.Bold)
        )
        batch_layout.addWidget(self.batch_title)

        batch_ctrl_layout = QHBoxLayout()
        self.batch_count_label = QLabel("抽取次数:")
        batch_ctrl_layout.addWidget(self.batch_count_label)
        self.batch_spinbox = QSpinBox()
        self.batch_spinbox.setRange(1, 999)
        self.batch_spinbox.setValue(window.batch_spin_count)
        self.batch_spinbox.setFixedWidth(60)
        self.batch_spinbox.valueChanged.connect(self._onBatchCountChanged)
        batch_ctrl_layout.addWidget(self.batch_spinbox)
        self.btn_batch_spin = QPushButton("开始批量抽取")
        self.btn_batch_spin.setMinimumHeight(32)
        self.btn_batch_spin.setStyleSheet(
            "background-color: #FF6B6B; color: white; font-weight: bold;"
        )
        self.btn_batch_spin.clicked.connect(self.startBatchSpin)
        batch_ctrl_layout.addWidget(self.btn_batch_spin, 1)
        self.btn_stop_batch = QPushButton("停止")
        self.btn_stop_batch.setEnabled(False)
        self.btn_stop_batch.clicked.connect(self.stopBatchSpin)
        batch_ctrl_layout.addWidget(self.btn_stop_batch)
        batch_layout.addLayout(batch_ctrl_layout)

        self.batch_log_label = QLabel("")
        self.batch_log_label.setFont(QFont(window.ui_font_family, window.ui_font_size))
        self.batch_log_label.setWordWrap(True)
        batch_layout.addWidget(self.batch_log_label)

    # ---- 按钮可用状态 ----
    def updateExtractButtonState(self):
        """控制抽出按钮的可用状态"""
        if not self.groups or self.window.current_group_index < 0:
            self.btn_extract.setEnabled(False)
            return
        items = self.window.groups[self.window.current_group_index]["items"]
        has_result = self.window.last_result_index is not None
        self.btn_extract.setEnabled(bool(has_result and items))

    def _updateBatchButtonState(self):
        """控制批量抽取按钮的可用状态"""
        if not self.groups or self.window.current_group_index < 0:
            self.btn_batch_spin.setEnabled(False)
            return
        items = self.window.groups[self.window.current_group_index]["items"]
        has_items = len(items) > 0
        self.btn_batch_spin.setEnabled(has_items and not self.window.wheel.spinning)

    def _onBatchCountChanged(self, value):
        """批量次数变更时持久化"""
        self.window.batch_spin_count = value
        self.save()

    # ---- 旋转启停 ----
    def onSpinStarted(self):
        """旋转开始时禁用编辑"""
        self.window.left_panel.setEnabled(False)
        self.btn_spin.setEnabled(False)
        self.btn_extract.setEnabled(False)
        if self.batch_remaining <= 0:
            self.btn_batch_spin.setEnabled(False)

    def onSpinFinished(self, index, text):
        """旋转结束时显示结果并恢复编辑"""
        self.result_label.setText(f"🎉 恭喜中奖: {text}")
        self.window.last_result_index = index

        # 批量抽取模式
        if self.batch_remaining > 0:
            # 自动抽出当前结果
            self._autoExtract(index)
            self.batch_results.append(text)
            self.batch_remaining -= 1
            self.batch_log_label.setText(
                f"已抽取 {len(self.batch_results)} 次，"
                f"剩余 {self.batch_remaining} 次\n"
                + "  →  ".join(self.batch_results[-8:])
                + ("..." if len(self.batch_results) > 8 else "")
            )
            self.save()

            # 检查是否还有项目可供抽取
            group = self.window.groups[self.window.current_group_index]
            if not group["items"] or self.batch_remaining <= 0:
                self._finishBatch()
                return

            # 继续下一轮旋转
            QTimer.singleShot(400, self.window.wheel.startSpin)
            return

        # 单次抽取模式：恢复正常状态
        self.window.left_panel.setEnabled(True)
        self.btn_spin.setEnabled(True)
        self.btn_batch_spin.setEnabled(True)
        self.updateExtractButtonState()

    # ---- 批量抽取（不放回）----
    def startBatchSpin(self):
        """开始批量不放回抽取"""
        window = self.window
        if window.wheel.spinning:
            return
        if not self.groups or window.current_group_index < 0:
            return
        items = window.groups[window.current_group_index]["items"]
        if not items:
            QMessageBox.warning(window, "提示", "当前分组没有可抽取的项目！")
            return

        n = self.batch_spinbox.value()
        if n > len(items):
            reply = QMessageBox.question(
                window,
                "确认",
                f"当前只有 {len(items)} 个项目，但请求抽取 {n} 次。\n"
                f"抽取 {len(items)} 次后会自动停止。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            n = len(items)

        self.batch_remaining = n
        self.batch_results = []
        self.batch_log_label.setText(f"开始不放回批量抽取 {n} 次...")
        self.btn_batch_spin.setEnabled(False)
        self.btn_stop_batch.setEnabled(True)
        window.left_panel.setEnabled(False)
        window.wheel.setItems(items)
        window.wheel.startSpin()

    def stopBatchSpin(self):
        """手动停止批量抽取"""
        self.batch_remaining = 0
        self._finishBatch()

    def _autoExtract(self, index):
        """自动将结果移入抽出列表（按索引移除，避免重复文本误删）"""
        group = self.window.groups[self.window.current_group_index]
        if 0 <= index < len(group["items"]):
            item_text = group["items"].pop(index)
            if "drawn_items" not in group:
                group["drawn_items"] = []
            group["drawn_items"].append(item_text)
            self.refresh_from_group()

    def _finishBatch(self):
        """批量抽取结束，恢复界面"""
        window = self.window
        self.batch_remaining = 0
        window.wheel.stopSpin()
        self.result_label.setText(f"✅ 批量抽取完成！共抽取 {len(self.batch_results)} 次")
        summary = "  →  ".join(self.batch_results[-20:])
        if len(self.batch_results) > 20:
            summary += f"\n（共 {len(self.batch_results)} 项，仅显示最后20项）"
        self.batch_log_label.setText(summary)
        window.left_panel.setEnabled(True)
        self.btn_spin.setEnabled(True)
        self.btn_batch_spin.setEnabled(True)
        self.btn_stop_batch.setEnabled(False)
        self.updateExtractButtonState()
        window.updateDrawnList()
