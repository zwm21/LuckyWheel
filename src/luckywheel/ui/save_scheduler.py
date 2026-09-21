"""保存去抖调度：把高频变更合并为一次落盘。

为什么需要：字号微调 spinbox 每 ±1 触发一次、批量抽取每轮一次、拖拽排序
每步一次。旧实现每次变更同步写盘，机械盘上表现为可感知的卡顿。

用法：MainWindow 持一个实例，`saveData()` 只登记（重置计时器），
`flushSave()` 取消待发定时器并立即落盘（关窗等不能丢数据的时机）。
"""

from PyQt6.QtCore import QTimer


class SaveScheduler:
    """单次定时器去抖：窗口期内多次 schedule() 只触发一次 callback。"""

    def __init__(self, parent, callback, interval_ms=500):
        """
        Args:
            parent: 定时器的属主 QObject（通常是窗口）
            callback: 真正执行保存的可调用对象，无参数
            interval_ms: 去抖窗口
        """
        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.flush_now)
        self._callback = callback

    def schedule(self):
        """登记一次待保存变更（重置计时器）。"""
        self._timer.start()

    def flush_now(self):
        """取消待发定时器并立即执行保存。"""
        self._timer.stop()
        self._callback()

    def pending(self):
        """是否有尚未落盘的变更。"""
        return self._timer.isActive()
