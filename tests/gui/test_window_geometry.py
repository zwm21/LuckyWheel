"""GUI：窗口几何恢复的屏幕边界校验，以及 setItems 不再归零旋转角。

旧行为两处可观察的缺陷：
- 恢复几何时无脑 setGeometry，副屏未连接时窗口被摆到屏幕外；
- setItems 把 rotation 清零，换分组/刷新列表时转盘视觉跳变。
本文件把两者的新语义钉住。
"""

import json

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication

VALID_FIXTURE = "tests/data/valid_v2.json"


class FakeScreen:
    """只暴露 availableGeometry 的假屏幕，供 QApplication.screens() 打桩。"""

    def __init__(self, geo):
        self._geo = QRect(*geo)

    def availableGeometry(self):
        return self._geo


def build_window(qtbot, monkeypatch, tmp_path, geometry):
    """以 valid_v2.json 为底、覆盖 window_geometry 后构造 MainWindow。

    屏幕列表同时打桩：offscreen 平台的真实屏幕位形各机器不同，
    不固定就无法对坐标做断言。注意 setMinimumSize(850, 600) 会把更窄
    的恢复宽度撑开，夹具几何一律用不低于最小值的尺寸。
    """
    from main import MainWindow

    data = json.loads(open(VALID_FIXTURE, encoding="utf-8").read())
    data["window_geometry"] = geometry
    data_file = tmp_path / "wheel_data.json"
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("luckywheel.core.paths.resolve_data_path", lambda: (data_file, None))
    win = MainWindow()
    qtbot.addWidget(win)
    return win


@pytest.fixture
def patch_screens(monkeypatch):
    """打桩 QApplication.screens() 与 primaryScreen()。"""

    def apply(primary_geo, extra_screens=()):
        primary = FakeScreen(primary_geo)
        screens = [primary, *(FakeScreen(g) for g in extra_screens)]
        monkeypatch.setattr(QApplication, "screens", staticmethod(lambda: screens))
        monkeypatch.setattr(QApplication, "primaryScreen", staticmethod(lambda: primary))
        return screens

    return apply


class TestGeometryScreenValidation:
    def test_geometry_on_primary_is_restored(self, qtbot, monkeypatch, tmp_path, patch_screens):
        patch_screens((0, 0, 1920, 1080))
        win = build_window(qtbot, monkeypatch, tmp_path, [10, 20, 900, 620])
        assert win.geometry() == QRect(10, 20, 900, 620)

    def test_geometry_of_connected_secondary_is_restored(
        self, qtbot, monkeypatch, tmp_path, patch_screens
    ):
        """副屏在线时，副屏上的几何必须恢复（校验不得误伤多屏用户）。"""
        patch_screens((0, 0, 1920, 1080), extra_screens=[(1920, 0, 1920, 1080)])
        win = build_window(qtbot, monkeypatch, tmp_path, [2000, 100, 950, 660])
        assert win.geometry() == QRect(2000, 100, 950, 660)

    @pytest.mark.parametrize(
        "geometry",
        [
            [3000, 100, 950, 660],  # 副屏已拔：x 起于主屏右侧之外
            [-5000, 50, 950, 660],  # 负坐标远在虚拟桌面左侧之外
            [100, 4000, 950, 660],  # y 起于主屏下方之外
        ],
    )
    def test_unreachable_geometry_falls_back_to_center(
        self, qtbot, monkeypatch, tmp_path, patch_screens, geometry
    ):
        patch_screens((0, 0, 1920, 1080))
        win = build_window(qtbot, monkeypatch, tmp_path, geometry)
        assert win.width() == 1024
        assert win.height() == 700
        geo = win.geometry()
        assert geo.x() >= 0 and geo.y() >= 0, "回退窗口必须落在主屏可用区域内"

    def test_bad_geometry_falls_back_to_center(self, qtbot, monkeypatch, tmp_path, patch_screens):
        """长度非 4 的几何在 core 层已被收敛为 None，此处验证端到端回退。"""
        patch_screens((0, 0, 1920, 1080))
        win = build_window(qtbot, monkeypatch, tmp_path, [10, 20])
        assert win.width() == 1024
        assert win.height() == 700

    def test_no_screens_falls_back_to_center(self, qtbot, monkeypatch, tmp_path):
        """screens() 为空（极端环境）时不得抛异常，回退默认尺寸。"""
        monkeypatch.setattr(QApplication, "screens", staticmethod(lambda: []))

        class _Primary:
            def availableGeometry(self):
                return QRect(0, 0, 1920, 1080)

        monkeypatch.setattr(QApplication, "primaryScreen", staticmethod(lambda: _Primary()))
        win = build_window(qtbot, monkeypatch, tmp_path, [10, 20, 900, 620])
        assert win.width() == 1024
        assert win.height() == 700


class TestSetItemsKeepsRotation:
    def test_rotation_survives_set_items(self, qtbot):
        from main import WheelWidget

        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems(["A", "B", "C"])
        wheel.rotation = 123.4
        wheel.setItems(["甲", "乙"])
        assert wheel.rotation == 123.4

    def test_set_items_still_stops_spin(self, qtbot):
        """删归零不得顺手删掉 stopSpin：旋转中换列表必须停下。"""
        from main import WheelWidget

        wheel = WheelWidget()
        qtbot.addWidget(wheel)
        wheel.setItems(["A", "B", "C"])
        wheel.rotation = 200.0
        stopped = []
        original = wheel.stopSpin
        wheel.stopSpin = lambda: (stopped.append(1), original())[1]
        wheel.setItems(["X", "Y"])
        assert stopped, "setItems 必须调用 stopSpin"
