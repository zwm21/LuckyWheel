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


def program_dir():
    """程序所在目录：frozen 时是 exe 目录，源码运行时是本包上两级（仓库根）。"""
    if getattr(sys, "frozen", False):
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
        # 该目录不存在，导致此候选永远落空）
        Path(__file__).resolve().parents[3] / "assets" / "fonts",
        program_dir(),  # exe/脚本旁边
    ]
    candidates = [base / name for base in bases if base is not None]
    # 去重保序
    seen, unique = set(), []
    for c in candidates:
        key = str(c).lower()
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
