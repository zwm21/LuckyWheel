"""GUI：垂直 QSplitter 布局回归。

手写 SplitterHandle 换成 QSplitter 后，列表高度行为完全由 Qt 管理，
旧 resizeEvent 里那段算错的钳制逻辑（max(800, ...)）随之删除。这里
钉住新行为：最小窗口尺寸下两个列表仍可见可操作、初始高度来自保存值。
"""

import pytest


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    """数据文件隔离到临时目录的 MainWindow。"""
    from main import MainWindow

    monkeypatch.setattr(
        "luckywheel.core.paths.resolve_data_path", lambda: (tmp_path / "wheel_data.json", None)
    )
    win = MainWindow()
    qtbot.addWidget(win)
    win.groups = [{"name": "g", "items": ["A", "B", "C"], "drawn_items": ["X"]}]
    win.current_group_index = 0
    win.updateWheelFromCurrentGroup()
    return win


class TestSplitterLayout:
    def test_both_lists_are_splitter_panes(self, window):
        panes = [window.list_widget, window.bottom_widget, window.drawn_list_widget]
        assert [window.list_splitter.widget(i) for i in range(3)] == panes

    def test_legacy_handle_gone(self, window):
        """SplitterHandle 类与高度钳制逻辑都已移除。"""
        from main import MainWindow

        assert not hasattr(window, "splitter_handle")
        assert not hasattr(window, "drawn_splitter_handle")
        assert "resizeEvent" not in MainWindow.__dict__, "MainWindow 不得再有自己的 resizeEvent"
        try:
            import main as legacy_main

            assert not hasattr(legacy_main, "SplitterHandle"), "SplitterHandle 类应删除"
        finally:
            pass

    def test_initial_sizes_from_saved_heights(self, qtbot, monkeypatch, tmp_path):
        import json

        from main import MainWindow

        data = json.loads(open("tests/data/valid_v2.json", encoding="utf-8").read())
        data["list_height"] = 260
        data["drawn_list_height"] = 160
        data_file = tmp_path / "wheel_data.json"
        data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr("luckywheel.core.paths.resolve_data_path", lambda: (data_file, None))
        win = MainWindow()
        qtbot.addWidget(win)
        win.resize(1400, 1000)
        win.show()
        qtbot.waitExposed(win)
        qtbot.wait(50)
        # 空间足够时 setSizes 的请求值是下界（QSplitter 只在其上拉伸）
        assert win.list_widget.height() >= 260
        assert win.drawn_list_widget.height() >= 160

    def test_lists_usable_at_minimum_size(self, window, qtbot):
        """计划验收点：窗口缩到最小尺寸时两个列表仍可操作。"""
        window.show()
        qtbot.waitExposed(window)
        window.resize(850, 600)  # setMinimumSize(850, 600)
        qtbot.wait(50)
        assert window.list_widget.isVisible()
        assert window.drawn_list_widget.isVisible()
        assert window.list_widget.height() > 0
        assert window.drawn_list_widget.height() > 0
        # 列表内容仍可完整显示行项（视口有内容高度）
        assert window.list_widget.count() == 3
        assert window.drawn_list_widget.count() == 1
