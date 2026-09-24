"""GUI：保存去抖——高频变更合并为一次落盘，关窗时立即 flush。

旧实现每次变更同步写盘：字号微调 spinbox 每 ±1 一次、批量抽取每轮一次、
拖拽排序每步一次，机械盘上表现为可感知的卡顿。现在 saveData 只重置
500ms 单次定时器；closeEvent 改走 flushSave，避免关窗丢高度/几何。
"""

import json

import pytest

from luckywheel.core import storage


@pytest.fixture
def window(build_main_window):
    """MainWindow 实例，数据文件隔离到临时目录（不碰用户真实数据）。"""
    return build_main_window(groups=[{"name": "g", "items": ["A", "B"], "drawn_items": []}])


class TestDebouncedSave:
    def test_save_is_deferred(self, window, monkeypatch):
        """saveData 本身不落盘，只是调度。"""
        calls = []
        monkeypatch.setattr(storage, "save_state", lambda *a, **k: calls.append(1))
        window.saveData()
        assert calls == [], "saveData 不应同步写盘"

    def test_timer_eventually_writes(self, qtbot, window, monkeypatch):
        calls = []
        monkeypatch.setattr(storage, "save_state", lambda *a, **k: calls.append(1))
        window.saveData()
        qtbot.wait(800)  # 超过 500ms 去抖窗口
        assert len(calls) == 1

    def test_burst_collapses_to_single_write(self, qtbot, window, monkeypatch):
        """连续变更只落盘一次：每次 saveData 重置计时。"""
        calls = []
        monkeypatch.setattr(storage, "save_state", lambda *a, **k: calls.append(1))
        for _ in range(10):
            window.saveData()
            qtbot.wait(20)  # 远小于去抖窗口
        assert calls == []
        qtbot.wait(800)
        assert len(calls) == 1, "突发保存应合并为一次落盘"


class TestFlushSave:
    def test_flush_writes_immediately(self, window, monkeypatch):
        calls = []
        monkeypatch.setattr(storage, "save_state", lambda *a, **k: calls.append(1))
        window.saveData()
        window.flushSave()
        assert len(calls) == 1

    def test_flush_cancels_pending_timer(self, qtbot, window, monkeypatch):
        """flush 之后定时器不得补写一次（否则一次变更会落盘两次）。"""
        calls = []
        monkeypatch.setattr(storage, "save_state", lambda *a, **k: calls.append(1))
        window.saveData()
        window.flushSave()
        qtbot.wait(800)
        assert len(calls) == 1

    def test_close_event_flushes(self, qtbot, window):
        """关窗必须立即落盘：待发的去抖写入不得随窗口销毁而丢失。"""
        window.saveData()  # 有待发的保存
        window.close()
        with open(window.data_file, encoding="utf-8") as f:
            data = json.load(f)
        assert data["groups"][0]["items"] == ["A", "B"]

    def test_close_event_records_geometry(self, qtbot, window):
        """旧语义不丢：关窗时窗口几何与 splitter 尺寸进入落盘数据。"""
        window.close()
        with open(window.data_file, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["window_geometry"]) == 4
        assert isinstance(data["splitter_sizes"], list)
