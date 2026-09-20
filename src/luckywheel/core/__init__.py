"""luckywheel.core：零 Qt 依赖的纯逻辑层。

本包的任何模块都不得 import PyQt6，保证算法、数据模型与持久化逻辑
可以用普通 pytest 秒级验证（见 tests/unit/）。界面层只做消费。
"""
