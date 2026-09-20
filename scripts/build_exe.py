#!/usr/bin/env python
"""LuckyWheel 打包脚本：字体可选，缺失也能打出可用的 exe。

与旧版 build_exe.bat 的区别：
- 不要求在仓库根目录放置字体；字体放 assets/fonts/ 且该目录被 .gitignore
  排除（版权归属作者），打包时检测到才 --add-data，缺失仅提示不失败；
- 临时 spec 文件写入系统临时目录，仓库不留 *.spec 残留；
- dist/ 与 build/pyinstaller/ 产物均被 .gitignore 排除。

用法：python scripts/build_exe.py [--onedir]
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "assets" / "fonts"
APP_NAME = "LuckyWheel"
# 阶段 2 后入口迁移至 src/luckywheel/app.py，此处再调整
ENTRY = ROOT / "main.py"


def find_font():
    if not FONT_DIR.is_dir():
        return None
    for pattern in ("*.ttf", "*.otf"):
        fonts = sorted(FONT_DIR.glob(pattern))
        if fonts:
            return fonts[0]
    return None


def build(onefile=True):
    if not ENTRY.exists():
        print(f"[X] 入口文件不存在: {ENTRY}")
        return 1

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        f"--name={APP_NAME}",
        f"--distpath={ROOT / 'dist'}",
        f"--workpath={ROOT / 'build' / 'pyinstaller'}",
        f"--specpath={Path(tempfile.mkdtemp(prefix='luckywheel-spec-'))}",
        "--noconfirm",
        "--clean",
    ]
    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")
    cmd.append("--windowed")

    font = find_font()
    if font:
        cmd += ["--add-data", f"{font}{';' if sys.platform == 'win32' else ':'}."]
        print(f"[*] 内嵌字体: {font.relative_to(ROOT)}")
    else:
        print("[!] 未找到 assets/fonts/ 下的字体文件，本次打包不内嵌字体。")
        print("    运行时将回退为系统默认字体（Microsoft YaHei）。")
        print("    如需内嵌，请自备字体放入 assets/fonts/（注意版权）。")

    cmd.append(str(ENTRY))
    print("[*] 开始打包，请稍候...")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode == 0:
        suffix = "LuckyWheel.exe" if sys.platform == "win32" else "LuckyWheel"
        print(f"[√] 打包成功: {(ROOT / 'dist' / suffix)}")
    else:
        print("[X] 打包失败。")
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onefile", action="store_true", default=True, help="单文件打包（默认）")
    parser.add_argument(
        "--onedir", dest="onefile", action="store_false", help="目录打包，便于排查资源加载问题"
    )
    args = parser.parse_args()
    return build(onefile=args.onefile)


if __name__ == "__main__":
    sys.exit(main())
