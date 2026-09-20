"""LuckyWheel 包根。

纯算法在 core/（零 Qt 依赖），界面在 ui/；应用入口见 app.py。
本文件刻意不放任何 import，避免 `import luckywheel.core.storage` 之类
的算法测试被 Qt 依赖拖累。
"""
