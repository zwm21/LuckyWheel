"""LuckyWheel 测试包。

约定：
- 界面测试在 offscreen 平台运行，任何用例都不弹真实窗口；
- core/ 的测试不允许 import Qt，保证纯算法可以脱离 GUI 秒级验证；
- tests/data/ 下是手工维护的夹具，形状复刻真实数据但独立演化；
  tests/data/legacy_v1.json 特意不带 schema 版本号，用于迁移测试。
"""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 注意：QT_API 不能在此设置——pytest-qt 插件早于 conftest 完成初始化，
# 须通过 pyproject.toml 的 [tool.pytest.ini_options] qt_api 指定。

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "gui: 需要 QApplication 的界面测试")


@pytest.fixture(scope="session")
def real_wheel_data():
    """仓库根的运行时数据文件路径（可能不存在，属用户数据而非夹具）。"""
    root = Path(__file__).resolve().parent.parent
    return root / "wheel_data.json"


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch, request):
    """把延后弹出的模态框换成记录器，返回调用列表。

    提示经 ui/bootstrap.notify 用 QTimer.singleShot 延后到事件循环；测试里
    事件循环一旦被 qtbot 驱动就会真的弹出模态框并卡死用例。只有构造
    MainWindow 的目录（gui/ 与 characterization/）需要这道防线，
    core/ 的用例因此保持零 Qt 导入。

    替换点是 show_info 的归属模块（bootstrap），与调用方无关。
    """
    if request.node.path.parent.name not in ("gui", "characterization"):
        return None
    from luckywheel.ui import bootstrap

    calls = []
    monkeypatch.setattr(
        bootstrap,
        "show_info",
        lambda parent, title, text: calls.append((title, text)),
    )
    return calls
