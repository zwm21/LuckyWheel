"""GUI：外部数据文件不可信时，MainWindow 必须仍然起得来。

这两个场景在修复前都会让程序无法启动，且都不需要任何合法 schema 就能
构造出来（tests/unit 已覆盖解析层，这里验证异常不会穿透到窗口构造）：
- 深度嵌套 JSON 让 json.loads 抛 RecursionError，load_state 漏捕即穿透；
- 超大整数通过 clamp 的类型校验后进 QFont/QRect，抛 OverflowError。

另覆盖载入告警的合并：坏数据下逐条弹窗会把界面淹没。
"""

import json

import pytest

HOSTILE = {
    "deep_nesting": '{"a":' * 3000 + "1" + "}" * 3000,
    "huge_ints": json.dumps(
        {
            "version": 2,
            "groups": [{"name": "g", "items": ["a", "b"]}],
            "ui_font_size": 10**12,
            "window_geometry": [10**20, 0, 800, 600],
            "splitter_sizes": [10**20, 600],
        }
    ),
    "many_warnings": json.dumps(
        {
            "version": 2,
            "groups": [
                {
                    "name": "g",
                    "items": [None, ["x"], {"y": 1}, True, 42, "正常"],
                }
            ],
        }
    ),
}


@pytest.fixture
def make_window(build_main_window, tmp_path):
    """按给定文件内容构造 MainWindow；返回 (window, data_path)。

    复用 conftest 的 build_main_window：它把数据路径指向同一个临时文件，
    因此先写内容再构造即可，窗口同样交给 qtbot 管理（否则 500ms 去抖
    定时器会跨测试存活，撞上别处对 storage.save_state 的 monkeypatch）。
    """

    def build(content):
        path = tmp_path / "wheel_data.json"
        path.write_text(content, encoding="utf-8")
        return build_main_window(), path

    return build


class TestHostileDataStillStarts:
    @pytest.mark.parametrize("case", ["deep_nesting", "huge_ints"])
    def test_window_constructs(self, qtbot, make_window, no_modal_dialogs, case):
        """异常数据不得让构造失败；用户应看到一条提示且程序可用。"""
        win, _ = make_window(HOSTILE[case])
        assert win.windowTitle()
        assert win.wheel.items, "应回落到默认数据而非空转盘"

    def test_corrupt_file_quarantined(self, qtbot, make_window, tmp_path):
        """损坏/超限文件被隔离，不在原位留着反复触发同一故障。"""
        _, path = make_window(HOSTILE["deep_nesting"])
        assert not path.exists()
        assert len(list(tmp_path.glob("*.corrupt-*.json"))) == 1


class TestWarningsAreBatched:
    def test_many_warnings_collapse_to_one_dialog(self, qtbot, make_window, no_modal_dialogs):
        """逐条弹窗会淹没界面：多条告警必须合并为一次提示。"""
        win, _ = make_window(HOSTILE["many_warnings"])
        qtbot.wait(50)  # 让 singleShot(0) 的弹窗回调跑完

        assert len(no_modal_dialogs) == 1, f"应只弹一次，实际 {len(no_modal_dialogs)} 次"
        title, text = no_modal_dialogs[0]
        assert "数据提示" in title
        # 总量写在标题里，正文只预览前几条
        assert "共" in title and "条" in title
        assert "\n" in text or "另有" in text
