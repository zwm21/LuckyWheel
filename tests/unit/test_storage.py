"""core.storage：原子写、损坏保留、迁移与类型校验（零 Qt 依赖）。"""

import json
import os
import shutil
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

    def test_fresh_install_leaves_font_to_embedded(self, tmp_path):
        """首启（文件不存在）走 default_state：字体家族必须是 None，
        MainWindow.loadData 的 `state.x or self.x` 才会保留启动期
        loadEmbeddedFont 选中的内嵌字体。若此处给默认字符串，内嵌字体被
        丢弃，还会在 loadData 末尾的 saveData 里写盘固化，此后每次启动
        都从文件读回同一个默认值（打包版与源码运行因此不一致）。
        """
        state, warnings = storage.load_state(tmp_path / "nothing.json")
        assert state.ui_font_family is None
        assert state.wheel_font_family is None
        assert (state.ui_font_family or "HYWenHei") == "HYWenHei"
        dumped = state.to_dict()
        assert "ui_font_family" not in dumped and "wheel_font_family" not in dumped

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


class TestHostileInput:
    """外部数据文件是不可信输入：异常不得穿透到 MainWindow.__init__。"""

    def test_deep_nesting_does_not_escape(self, tmp_path):
        """深度嵌套 JSON 抛 RecursionError 而非 JSONDecodeError，必须被接住。

        实测 3000 层 {"a": 即触发；漏捕时它一路穿透 loadState → loadData →
        MainWindow.__init__，程序根本无法启动，而构造这种文件不需要任何
        合法 schema。
        """
        path = tmp_path / "deep.json"
        path.write_text('{"a":' * 3000 + "1" + "}" * 3000, encoding="utf-8")
        state, warnings = storage.load_state(path)
        assert state.groups[0].items == ["选项1", "选项2", "选项3"]
        assert any("嵌套" in w for w in warnings)
        # 原件被隔离，不静默覆盖
        assert not path.exists()
        assert len(list(tmp_path.glob("*.corrupt-*.json"))) == 1

    def test_oversized_file_is_quarantined(self, tmp_path, monkeypatch):
        """超过体积上限按损坏处理，且不把整个文件读进内存。"""
        path = tmp_path / "big.json"
        path.write_text("[" + ",".join(["1"] * 10) + "]", encoding="utf-8")
        # 把上限压到 10 字节来触发分支，避免真的写出 8 MiB
        monkeypatch.setattr(storage, "MAX_DATA_FILE_BYTES", 10)
        state, warnings = storage.load_state(path)
        assert state.groups[0].items == ["选项1", "选项2", "选项3"]
        assert any("MiB" in w for w in warnings)
        assert not path.exists(), "超限文件应被隔离"

    def test_gbk_encoded_file_does_not_escape(self, tmp_path):
        """中文 Windows 记事本默认另存的 GBK 文件：UnicodeDecodeError 是
        ValueError 子类而非 OSError，漏捕就穿透 loadData 直达
        MainWindow.__init__，程序起不来。按损坏同等隔离，用户改个编码
        不丢数据也不至于开不了机。
        """
        path = tmp_path / "wheel_data.json"
        path.write_bytes(
            json.dumps(
                {"version": SCHEMA_VERSION, "groups": [{"name": "一组", "items": ["中文条目"]}]},
                ensure_ascii=False,
            ).encode("gbk")
        )
        state, warnings = storage.load_state(path)
        assert state.groups[0].items == ["选项1", "选项2", "选项3"]
        assert any("UTF-8" in w for w in warnings)
        assert not path.exists(), "原件应被隔离保留而非静默覆盖"
        assert len(list(tmp_path.glob("*.corrupt-*.json"))) == 1

    def test_utf8_bom_file_is_accepted(self, tmp_path):
        """记事本"UTF-8"选项另存的是带 BOM 的 UTF-8：json 不跳过前导
        \\ufeff，用 utf-8 读取会把这种合法文件判成损坏并整份隔离搬家，
        且没有恢复入口。utf-8-sig 对带/不带 BOM 的 UTF-8 都正确。
        """
        path = tmp_path / "wheel_data.json"
        payload = json.dumps({"version": SCHEMA_VERSION, "groups": [{"name": "g", "items": ["a"]}]})
        path.write_bytes(b"\xef\xbb\xbf" + payload.encode("utf-8"))
        state, warnings = storage.load_state(path)
        assert state.groups[0].items == ["a"]
        assert not any("损坏" in w for w in warnings), "合法数据不得被判损坏"
        assert path.exists(), "合法数据不得被隔离"

    def test_entry_cap_truncates_with_warning(self):
        """条目数超限截断而非全部拒绝，且只产生一条汇总 warning。"""
        raw = {"items": [str(i) for i in range(storage.MAX_ENTRIES_PER_GROUP + 50)]}
        warnings = []
        cleaned = storage._sanitize_entries(raw["items"], "items", 0, warnings)
        assert len(cleaned) == storage.MAX_ENTRIES_PER_GROUP
        assert len(warnings) == 1, "超限只应有一条汇总提示"
        assert str(storage.MAX_ENTRIES_PER_GROUP) in warnings[0]

    def test_entry_cap_counts_read_positions_not_kept_items(self, monkeypatch):
        """上限按已读位置计，不按已保留条数。

        用 len(cleaned) 计数时，一组全是 null 的条目永远触不到上限
        （cleaned 恒为 0），恰是构造成本最低的输入（每条 5 字节）拿到了
        唯一不受限的遍历；8 MiB 内可塞约 140 万条。
        """
        monkeypatch.setattr(storage, "MAX_ENTRIES_PER_GROUP", 5)
        warnings = []
        cleaned = storage._sanitize_entries([None] * 20, "items", 0, warnings)
        assert cleaned == []
        assert any("超过 5 条" in w for w in warnings), "全部非法的条目列表也必须在上限处停下"
        # 上限之后的位置不再产生逐项告警
        assert sum("类型非法" in w for w in warnings) == 5

    def test_overlong_text_truncated(self):
        warnings = []
        raw = ["x" * (storage.MAX_TEXT_LENGTH + 10)]
        cleaned = storage._sanitize_entries(raw, "items", 0, warnings)
        assert len(cleaned[0]) == storage.MAX_TEXT_LENGTH
        assert any("过长" in w for w in warnings)

    def test_current_group_bool_is_rejected(self):
        """bool 是 int 子类：不排除的话 True 会混过校验并被序列化回 true。"""
        data = {
            "groups": [{"name": "g", "items": ["a"]}, {"name": "h", "items": ["b"]}],
            "current_group": True,
        }
        state, _ = storage.parse_state(data)
        assert state.current_group == 0
        assert state.to_dict()["current_group"] == 0

    def test_group_cap_truncates_with_warning(self):
        """分组数超限截断：<8 MiB 可塞约 18 万个空分组，逐个进下拉框会拖死界面。"""
        raw = {"groups": [{"name": f"g{i}", "items": []} for i in range(storage.MAX_GROUPS + 30)]}
        state, warnings = storage.parse_state(raw)
        assert len(state.groups) == storage.MAX_GROUPS
        assert any(str(storage.MAX_GROUPS) in w for w in warnings)

    def test_warnings_are_capped(self):
        """告警总量封顶：8 MiB 内可塞约 140 万条 null，逐条累积的字符串
        会常驻上百 MB，而展示侧本来就只预览前几条并说明总量。"""
        raw = {"groups": [{"name": "g", "items": [None] * 3000}]}
        _, warnings = storage.parse_state(raw)
        assert len(warnings) <= storage.MAX_WARNINGS + 1
        assert "省略" in warnings[-1]

    def test_quarantine_warning_names_actual_file(self, tmp_path):
        """隔离告警必须给出确切文件名：glob 形式（.corrupt-*.json）让用户
        按名字找不到被搬走的文件。"""
        path = tmp_path / "wheel_data.json"
        path.write_text("not json", encoding="utf-8")
        _, warnings = storage.load_state(path)
        kept = list(tmp_path.glob("*.corrupt-*.json"))[0].name
        assert any(kept in w for w in warnings)

    def test_lone_surrogate_does_not_break_saving(self, tmp_path):
        """孤立代理字符必须在载入边界被换掉，否则保存永久失败。

        JSON 里的 "\\ud800" 字面量是纯 ASCII 字节，json.loads 给出合法
        str，一路通过类型校验进入 AppState；写盘时 encode("utf-8") 抛
        UnicodeEncodeError（ValueError 子类，不被 except OSError 接住），
        于是每次保存都失败、关窗的 flushSave 也失败，整场会话的改动
        无声丢失（_write_state 的宽 except 只保证不崩，不保证存下来）。
        """
        path = tmp_path / "wheel_data.json"
        path.write_text(
            '{"version": 2, "groups": [{"name": "\\ud800组", "items": ["\\ud800ok", "正常"]}]}',
            encoding="utf-8",
        )
        state, warnings = storage.load_state(path)

        assert any("无法保存的字符" in w for w in warnings)
        assert state.groups[0].items[1] == "正常", "同组的正常条目不受影响"
        # 关键断言：存得下去，且往返闭合
        out = tmp_path / "out.json"
        storage.save_state(out, state)
        reloaded, _ = storage.load_state(out)
        assert reloaded.groups[0].items == state.groups[0].items
        assert reloaded.groups[0].name == state.groups[0].name

    def test_unencodable_state_raises_storage_error(self, tmp_path):
        """内存里的状态若仍含无法编码的字符，必须归入 StorageError 契约。

        save_state 的文档承诺失败以 StorageError 呈现；UnicodeEncodeError
        直接穿透会让调用方的 except StorageError 落空，且不得在数据目录
        留下临时文件。
        """
        state = default_state()
        state.groups[0].items = ["\ud800"]
        with pytest.raises(storage.StorageError):
            storage.save_state(tmp_path / "d.json", state)
        assert list(tmp_path.iterdir()) == [], "失败不得留下临时文件或半截数据"

    def test_saved_file_size_matches_payload(self, tmp_path):
        """落盘字节数必须等于 payload 字节数（不得有换行翻译带来的膨胀）。

        文本模式在 Windows 下把每个 LF 写成 CRLF，而 indent=2 是一个条目
        一行：于是"体积检查刚好通过"的数据存回去就越过
        MAX_DATA_FILE_BYTES，下次启动被整份隔离，真实数据只剩在
        load_state 从不读的 .bak 里。
        """
        state = default_state()
        state.groups[0].items = [f"条目{n}" for n in range(500)]
        payload = json.dumps(state.to_dict(), ensure_ascii=False, indent=2)
        path = tmp_path / "d.json"
        storage.save_state(path, state)

        assert payload.count("\n") > 500, "indent=2 应产生大量换行，否则本测试失去意义"
        assert path.stat().st_size == len(payload.encode("utf-8"))
        assert b"\r\n" not in path.read_bytes()

    def test_backup_never_removes_original(self, tmp_path, monkeypatch):
        """备份用复制而非改名：最后一步失败时原文件必须还在原地。

        旧实现先 os.replace(path, .bak) 再 replace(tmp, path)，两步之间
        目标路径不存在，此刻失败就等于数据丢失，而 load_state 从不读 .bak。
        现实现备份也走 tmp + replace：这里只让主替换失败，备份照常完成。
        """
        path = tmp_path / "d.json"
        storage.save_state(path, default_state())
        original = path.read_text(encoding="utf-8")
        real_replace = os.replace

        def main_replace_only_fails(src, dst):
            if Path(dst) == path:
                raise OSError("磁盘满了")
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", main_replace_only_fails)
        with pytest.raises(storage.StorageError):
            storage.save_state(path, default_state())

        assert path.read_text(encoding="utf-8") == original, "原文件被备份步骤挪走了"
        assert (tmp_path / "d.json.bak").exists()
        assert not list(tmp_path.glob(".d.json.*.tmp")), "失败不得留下临时文件"

    def test_failed_backup_keeps_previous_backup(self, tmp_path, monkeypatch):
        """备份写 tmp 中途失败：上一份好 .bak 必须原样保留。

        shutil.copy2 以 "wb" 直开目标的旧行为会留下半截 .bak，把上一份好
        备份覆盖丢失；现实现先写临时文件再 replace，失败时旧 .bak 不动。
        """
        path = tmp_path / "d.json"
        path.write_text("seed", encoding="utf-8")  # 已有数据文件，本次保存才会备份
        storage.save_state(path, default_state())
        good = (tmp_path / "d.json.bak").read_text(encoding="utf-8")
        assert good == "seed"

        def boom(*args):
            raise OSError("磁盘满了")

        monkeypatch.setattr(shutil, "copyfileobj", boom)
        storage.save_state(path, default_state())  # 备份失败不阻塞主写入
        assert path.exists(), "主写入不应被备份失败阻塞"
        assert (tmp_path / "d.json.bak").read_text(encoding="utf-8") == good
        assert not list(tmp_path.glob(".d.json.bak.*.tmp")), "失败不得留下临时文件"


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
