"""core.paths：数据文件定位与字体查找（零 Qt 依赖）。"""

import os
import sys
from pathlib import Path

import pytest

from luckywheel.core import paths
from luckywheel.core.paths import (
    DATA_FILE_NAME,
    fallback_data_path,
    find_embedded_font,
    font_candidates,
    primary_data_path,
    program_dir,
    relocate_data_file,
    user_data_dir,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


class TestProgramDir:
    def test_source_run_points_to_repo_root(self):
        """源码运行：program_dir 即仓库根（含 pyproject.toml）。"""
        assert (program_dir() / "pyproject.toml").is_file()

    def test_frozen_uses_executable_parent(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", r"C:\Apps\LuckyWheel\LuckyWheel.exe")
        assert program_dir() == Path(r"C:\Apps\LuckyWheel")

    def test_primary_and_fallback_differ_by_design(self):
        assert primary_data_path().name == DATA_FILE_NAME
        assert fallback_data_path().parent == user_data_dir()


class TestResolveDataPath:
    def test_primary_when_writable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "program_dir", lambda: tmp_path)
        path, relocated = paths.resolve_data_path()
        assert path == tmp_path / DATA_FILE_NAME
        assert relocated is None

    def test_falls_back_when_readonly(self, tmp_path, monkeypatch):
        """程序目录不可写：回退用户数据目录，并提示搬移已有文件。"""
        ro_dir = tmp_path / "ro"
        ro_dir.mkdir()
        (ro_dir / DATA_FILE_NAME).write_text("{}", encoding="utf-8")
        monkeypatch.setattr(paths, "program_dir", lambda: ro_dir)
        monkeypatch.setattr(paths, "_writable", lambda d: False)
        monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path / "appdata")

        path, relocated = paths.resolve_data_path()
        assert path == tmp_path / "appdata" / DATA_FILE_NAME
        assert relocated == ro_dir / DATA_FILE_NAME

    def test_relocate_moves_file(self, tmp_path):
        old = tmp_path / "a" / DATA_FILE_NAME
        new = tmp_path / "b" / DATA_FILE_NAME
        old.parent.mkdir()
        old.write_text('{"version": 2}', encoding="utf-8")
        assert relocate_data_file(old, new)
        assert new.exists() and not old.exists()
        assert relocate_data_file(old, new) is False  # 幂等

    def test_relocate_missing_source(self, tmp_path):
        assert relocate_data_file(tmp_path / "nope", tmp_path / "dest") is False


class TestFontCandidates:
    def test_candidates_include_assets_and_program_dir(self):
        cands = font_candidates()
        assert any("assets" in str(c) or "fonts" in str(c) for c in cands)
        assert any(c.name.lower().endswith((".ttf", ".otf")) for c in cands)

    def test_candidates_dedup(self):
        cands = font_candidates()
        seen = {str(c) for c in cands}
        assert len(seen) == len(cands)

    def test_frozen_skips_repo_assets_candidate(self, monkeypatch, tmp_path):
        """onefile 下 __file__ 位于 %TEMP%\\_MEIxxxxxx 内，parents[3] 会指向
        %TEMP%：该候选排在 program_dir() 之前，而 %TEMP% 是任何用户态程序
        都可写的目录，预置同名 ttf 即可劫持字体加载。frozen 时只应看解包
        目录与 exe/脚本旁边。
        """
        fake_meipass = tmp_path / "_MEI12345"
        fake_meipass.mkdir()
        monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
        cands = font_candidates()
        assert cands[0] == fake_meipass / paths.FONT_FILE_NAME
        # 按路径分量匹配而非子串：tmp_path 的目录名由测试名生成，可能含 assets
        assert not any(Path("assets") in c.parts for c in cands)
        assert cands[-1] == program_dir() / paths.FONT_FILE_NAME

    def test_frozen_without_meipass_also_skips_repo_assets(self, monkeypatch, tmp_path):
        """cx_Freeze / py2exe 只设 sys.frozen，不设 sys._MEIPASS。

        判据若只看 _MEIPASS，这两种打包器下"frozen 但无 _MEIPASS"，仓库根
        候选会从毫无意义的 parents[3] 复活、且仍排在 program_dir() 之前，
        劫持面换个打包器就重新敞开。
        """
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "LuckyWheel.exe"))
        cands = font_candidates()
        assert cands == [tmp_path / paths.FONT_FILE_NAME]

    def test_dedup_follows_filesystem_case_rules(self, monkeypatch, tmp_path):
        """去重键用 os.path.normcase：大小写敏感的文件系统上不折叠大小写。

        早先的 str().lower() 在 Linux/macOS（区分大小写）上会把 Fonts/ 与
        fonts/ 这类真正不同的目录当成同一个候选丢掉。
        """
        monkeypatch.setattr(paths, "program_dir", lambda: tmp_path / "Bin")
        lower = tmp_path / "bin"
        monkeypatch.setattr(sys, "_MEIPASS", str(lower), raising=False)

        cands = font_candidates()
        folded = os.path.normcase(str(lower)) == os.path.normcase(str(tmp_path / "Bin"))
        assert len(cands) == (1 if folded else 2)

    def test_find_embedded_font_none_or_file(self):
        found = find_embedded_font()
        assert found is None or found.is_file()
