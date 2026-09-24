"""core.storage：原子写、损坏保留、迁移与类型校验（零 Qt 依赖）。"""

import json
import os
from pathlib import Path

import pytest

from luckywheel.core import storage
from luckywheel.core.models import SCHEMA_VERSION, default_state

DATA = Path(__file__).parent.parent / "data"


def load_fixture(name):
    with open(DATA / name, encoding="utf-8") as f:
        return json.load(f)


class TestLoad:
    def test_valid_v2_roundtrip(self, tmp_path):
        path = tmp_path / "d.json"
        path.write_text((DATA / "valid_v2.json").read_text(encoding="utf-8"), encoding="utf-8")
        state, warnings = storage.load_state(path)
        assert warnings == []
        assert len(state.groups) == 1
        assert state.groups[0].items == ["A", "A", "B", "长文本条目示例"]
        assert state.groups[0].drawn == ["X", "Y"]
        assert state.theme == "dark"
        assert state.ui_font_size == 11
        assert state.version == SCHEMA_VERSION

    def test_missing_file_gives_default(self, tmp_path):
        state, warnings = storage.load_state(tmp_path / "nothing.json")
        assert state.groups[0].items == ["选项1", "选项2", "选项3"]
        assert warnings == []

    def test_unrecorded_font_family_stays_none(self, tmp_path):
        """数据文件未记录字体家族时必须给 None，不能给默认字符串。

        MainWindow.loadData 用 `state.x or self.x` 保留启动期 loadEmbeddedFont
        的选择；此处若填默认值，那个回退永不触发，源码运行就用不到
        assets/fonts/ 下的字体、与打包版不一致。
        """
        path = tmp_path / "d.json"
        path.write_text(
            json.dumps({"version": SCHEMA_VERSION, "groups": [{"name": "g", "items": ["a"]}]}),
            encoding="utf-8",
        )
        state, _ = storage.load_state(path)
        assert state.ui_font_family is None
        assert state.wheel_font_family is None
        # 回退链：None 让调用方的选择生效，默认字符串则不会
        assert (state.ui_font_family or "启动期字体") == "启动期字体"
        # to_dict 不写键，避免把默认值固化成用户选择
        assert "ui_font_family" not in state.to_dict()
        assert "wheel_font_family" not in state.to_dict()

    def test_legacy_font_family_still_splits(self):
        """旧 font_family 仍同时供 ui 与 wheel 两份使用。"""
        state, _ = storage.parse_state(
            {"groups": [{"name": "g", "items": ["a"]}], "font_family": "旧字体"}
        )
        assert state.ui_font_family == "旧字体"
        assert state.wheel_font_family == "旧字体"

    def test_non_string_font_family_falls_back(self):
        """显式记录但类型非法的字体家族回落默认值（None 不受此限）。"""
        data = {"groups": [{"name": "g", "items": ["a"]}], "ui_font_family": 42}
        state, _ = storage.parse_state(data)
        assert state.ui_font_family == "Microsoft YaHei"

    def test_corrupt_file_is_quarantined_not_overwritten(self, tmp_path):
        """损坏文件改名保留为 .corrupt-<时间戳>，原位启用默认数据。"""
        path = tmp_path / "wheel_data.json"
        original = (DATA / "corrupt.json").read_text(encoding="utf-8")
        path.write_text(original, encoding="utf-8")

        state, warnings = storage.load_state(path)

        assert state.groups[0].items == ["选项1", "选项2", "选项3"]
        assert not path.exists(), "损坏文件不应留在原位"
        quarantined = list(tmp_path.glob("*.corrupt-*.json"))
        assert len(quarantined) == 1
        assert quarantined[0].read_text(encoding="utf-8") == original
        assert any("损坏" in w for w in warnings)

    def test_legacy_v1_migrates(self, tmp_path):
        path = tmp_path / "d.json"
        path.write_text((DATA / "legacy_v1.json").read_text(encoding="utf-8"), encoding="utf-8")
        state, warnings = storage.load_state(path)
        assert len(state.groups) == 2
        assert state.current_group == 1
        assert state.groups[1].items == ["甲", "乙"]
        # 旧 font_family 拆分；ui_font_size 旧文件未存过，默认 9
        assert state.ui_font_family == "汉仪文黑-65W"
        assert state.wheel_font_family == "汉仪文黑-65W"
        assert state.ui_font_size == 9
        assert state.batch_spin_count == 5
        assert state.version == SCHEMA_VERSION
        assert any("迁移" in w for w in warnings)

    def test_hostile_types_do_not_crash(self, tmp_path):
        """恶意/手搓文件：非法项被规整或跳过，绝不 KeyError。"""
        path = tmp_path / "d.json"
        path.write_text((DATA / "hostile_types.json").read_text(encoding="utf-8"), encoding="utf-8")
        state, warnings = storage.load_state(path)
        assert len(state.groups) == 5
        assert state.current_group == 0  # 99 越界已收敛
        assert state.ui_font_size == 9  # "九号" 非法
        assert state.wheel_font_size == 0  # -3 非法
        assert state.theme == "light"  # "彩虹色" 非法
        # 分组 3：数字/None/布尔/列表/字典被剔除，字符串转写
        assert state.groups[2].items == ["42", "正常项"]
        assert state.groups[2].name == "分组3"
        # 分组 4：drawn 为 null → []
        assert state.groups[3].drawn == []
        # 分组 5：items 是字符串 → []
        assert state.groups[4].items == []
        assert warnings, "异常输入应产生警告"

    def test_non_object_top_level(self, tmp_path):
        path = tmp_path / "d.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        state, warnings = storage.load_state(path)
        assert state.groups[0].items == ["选项1", "选项2", "选项3"]
        assert warnings


class TestSave:
    def test_roundtrip_preserves_state(self, tmp_path):
        state = default_state()
        state.groups[0].items = ["甲", "乙", "丙"]
        state.theme = "dark"
        path = tmp_path / "d.json"
        storage.save_state(path, state)
        loaded, _ = storage.load_state(path)
        assert loaded == state

    def test_atomic_replace_keeps_backup(self, tmp_path):
        path = tmp_path / "d.json"
        first = default_state()
        storage.save_state(path, first)
        first_text = path.read_text(encoding="utf-8")

        first.groups[0].items = ["改"]
        storage.save_state(path, first)

        assert path.read_text(encoding="utf-8") != first_text
        backup = tmp_path / "d.json.bak"
        assert backup.exists()
        assert json.loads(backup.read_text(encoding="utf-8"))["groups"][0]["items"] == [
            "选项1",
            "选项2",
            "选项3",
        ]

    def test_failed_replace_leaves_original_intact(self, tmp_path, monkeypatch):
        """os.replace 抛异常时原文件完好、临时文件被清理。"""
        path = tmp_path / "d.json"
        storage.save_state(path, default_state())
        original = path.read_text(encoding="utf-8")

        def boom(*args, **kwargs):
            raise OSError("磁盘满了")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(storage.StorageError):
            storage.save_state(path, default_state())

        assert path.read_text(encoding="utf-8") == original
        leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == [], f"临时文件未清理: {leftovers}"

    def test_writes_utf8_without_escaping(self, tmp_path):
        state = default_state()
        state.groups[0].items = ["中文项目", "émoji 🎉"]
        path = tmp_path / "d.json"
        storage.save_state(path, state)
        text = path.read_text(encoding="utf-8")
        assert "中文项目" in text and "🎉" in text

    def test_creates_missing_directory(self, tmp_path):
        path = tmp_path / "nested" / "deeper" / "d.json"
        storage.save_state(path, default_state())
        assert path.exists()
