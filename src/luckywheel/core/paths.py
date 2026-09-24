"""数据文件与资源定位（零 Qt 依赖）。

定位策略（按优先级）：
1. 可执行程序旁边（便携模式：源码运行=项目目录；PyInstaller exe=exe 目录）；
   该位置不可写时（如安装到 Program Files）回退到用户数据目录；
2. 用户数据目录：Windows=%%APPDATA%%/LuckyWheel，
   其他=~/.local/share/LuckyWheel（遵循 XDG）。

回退发生时调用方应把已有数据文件搬到新位置（见 relocate_data_file）。
"""

import os
import shutil
import sys
from pathlib import Path

APP_DIR_NAME = "LuckyWheel"
DATA_FILE_NAME = "wheel_data.json"
FONT_FILE_NAME = "HYWenHei-65W.ttf"


def is_frozen():
    """是否运行在打包后的可执行文件里。

    两个判据都要看：PyInstaller 同时设置 sys.frozen 与 sys._MEIPASS，但
    cx_Freeze / py2exe 只设 sys.frozen。早先 program_dir() 看 frozen、
    font_candidates() 看 _MEIPASS，于是在后两种打包器下"frozen 但无
    _MEIPASS"，仓库根候选会从毫无意义的 parents[3] 复活且仍排在
    program_dir() 之前——正是 6291c2d 要封掉的那个劫持面换了个打包器。
    """
    return bool(getattr(sys, "frozen", False)) or getattr(sys, "_MEIPASS", None) is not None


def program_dir():
    """程序所在目录：frozen 时是 exe 目录，源码运行时是本包上两级（仓库根）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # src/luckywheel/core/paths.py → 仓库根（parents: core, luckywheel, src, 根）
    return Path(__file__).resolve().parents[3]


def user_data_dir():
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME.lower()


def primary_data_path():
    return program_dir() / DATA_FILE_NAME


def fallback_data_path():
    return user_data_dir() / DATA_FILE_NAME


def _writable(directory):
    directory = Path(directory)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-test"
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False


def resolve_data_path():
    """决定本次运行的数据文件位置（不影响已有文件），返回 (path, relocated_from)。

    relocated_from 非空表示程序旁边的数据文件不可写在原地更新，
    调用方应把它搬到返回的路径（见 relocate_data_file）。
    """
    primary = primary_data_path()
    if not primary.exists():
        # 旁边没有历史文件：可写就用旁边（便携），否则用户目录
        if _writable(primary.parent):
            return primary, None
        return fallback_data_path(), None
    if _writable(primary.parent):
        return primary, None
    # 旁边有文件但不可写：搬到用户数据目录
    target = fallback_data_path()
    if target.resolve() == primary.resolve():
        return fallback_data_path().with_name(f"{DATA_FILE_NAME}.{os.getpid()}"), None
    return target, primary


def relocate_data_file(old_path, new_path):
    """把旧位置的数据文件搬到新位置（幂等：目标已存在则跳过）。"""
    old_path, new_path = Path(old_path), Path(new_path)
    if not old_path.exists() or new_path.exists():
        return False
    try:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_path), str(new_path))
        return True
    except OSError:
        return False


def font_candidates(font_filename=None):
    """内嵌字体的候选位置，按优先级返回（首个存在的被使用）。

    只收固定文件名，不 glob 目录下的任意 *.ttf/*.otf：字体解析是可被
    恶意构造文件利用的攻击面，程序目录下的字体应只来自 assets/fonts/ 与
    随包分发这两处（.gitignore 对两者都不放行，见 assets/fonts/README.md）。
    """
    name = font_filename or FONT_FILE_NAME
    frozen_base = getattr(sys, "_MEIPASS", None)
    bases = [
        # PyInstaller 解包目录（build_exe.py 用 --add-data 把字体放在这里）
        Path(frozen_base) if frozen_base else None,
        # 源码运行：仓库根的 assets/fonts。parents: core, luckywheel, src, 仓库根
        # （与 program_dir() 同一级，早先误写 parents[2] 指向 src/assets/fonts，
        # 该目录不存在，导致此候选永远落空）。仅非 frozen 加入：onefile 下
        # __file__ 位于 %TEMP%\_MEIxxxxxx 内，parents[3] 会指向 %TEMP%——那是
        # 任何用户态程序都可写的目录，而该候选又排在 program_dir() 之前，
        # 预置同名 ttf 即可劫持字体加载。判据用 is_frozen() 而非 _MEIPASS，
        # 否则 cx_Freeze 下同一个劫持面照旧敞开。
        (Path(__file__).resolve().parents[3] / "assets" / "fonts") if not is_frozen() else None,
        program_dir(),  # exe/脚本旁边
    ]
    candidates = [base / name for base in bases if base is not None]
    # 去重保序。键用 os.path.normcase：Windows 上折叠大小写与斜杠方向，
    # 而在大小写敏感的文件系统上是恒等映射——早先的 str().lower() 会把
    # Font.ttf 与 font.ttf 这类真正不同的路径当成同一个候选丢掉。
    seen, unique = set(), []
    for c in candidates:
        key = os.path.normcase(str(c))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def find_embedded_font(font_filename=None):
    """返回首个存在的字体路径，没有则 None。"""
    for candidate in font_candidates(font_filename):
        if candidate.is_file():
            return candidate
    return None
