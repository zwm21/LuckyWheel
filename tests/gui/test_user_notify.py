"""GUI：非致命问题必须让用户看见（原为 print，打包成 exe 后没有控制台）。

三处提示——数据文件迁移、数据读取告警、保存失败——原来都走 print。
源码运行时控制台能看到，PyInstaller 打包后 windowed 模式没有控制台，
用户对"数据没存上"一无所知。现在统一走 _notify 弹窗（延后到事件循环，
避免 __init__ 阶段同步弹模态框卡死启动）。

tests/conftest.py 的 no_modal_dialogs 已把 show_info 换成记录器，
本文件断言的就是那个记录器收到的内容。
"""

from luckywheel.core import storage


def drain_events(qtbot):
    """让 QTimer.singleShot(0, ...) 的弹窗回调跑完。"""
    qtbot.wait(50)


class TestSaveFailureNotifies:
    def test_failed_save_shows_dialog(self, qtbot, window, no_modal_dialogs, monkeypatch):
        """保存失败不得静默：至少弹一次，且标题点明是保存失败。"""

        def boom(*args, **kwargs):
            raise OSError("磁盘满了")

        monkeypatch.setattr(storage, "save_state", boom)
        window.flushSave()
        drain_events(qtbot)

        assert no_modal_dialogs, "保存失败时没有任何提示"
        titles = [t for t, _ in no_modal_dialogs]
        assert "保存失败" in titles
        assert any("磁盘满了" in text for _, text in no_modal_dialogs)

    def test_successful_save_is_silent(self, qtbot, window, no_modal_dialogs):
        window.flushSave()
        drain_events(qtbot)
        assert no_modal_dialogs == []


class TestMigrationNotifies:
    def test_relocation_shows_dialog(self, qtbot, monkeypatch, tmp_path, no_modal_dialogs):
        """便携位置不可写、数据要搬家时，必须告知用户（原为 print）。"""
        from luckywheel.ui.main_window import MainWindow

        old = tmp_path / "beside_exe.json"
        new = tmp_path / "user_dir" / "wheel_data.json"
        old.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("luckywheel.core.paths.resolve_data_path", lambda: (new, old))
        win = MainWindow()
        qtbot.addWidget(win)
        drain_events(qtbot)

        titles = [t for t, _ in no_modal_dialogs]
        assert "提示" in titles
        assert any("迁移" in text for _, text in no_modal_dialogs)


class TestNoPrintsLeft:
    def test_three_spots_no_longer_print(self):
        """源码里这三处不得再留下 print：提示语必须走 _notify。"""
        import inspect

        from luckywheel.ui import main_window as main_window_module

        src = inspect.getsource(main_window_module)
        assert 'print(f"提示' not in src
        assert 'print("数据提示:' not in src
        assert 'print("保存失败:' not in src
