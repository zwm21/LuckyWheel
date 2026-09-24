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
# 入口保持 main.py：它是转发到 luckywheel.ui 的兼容 wrapper，作为 PyInstaller
# 入口最稳（无需处理 -m 形式的 spec）；GUI 冒烟亦以 --entry main 为基准
ENTRY = ROOT / "main.py"

# 运行时认的字体文件名从 core.paths 取而非在此重抄一份：抄一份就会各自漂移，
# 而漂移的表现是"打包报告已内嵌、运行时静默回退"，两边都不报错。
sys.path.insert(0, str(ROOT / "src"))
from luckywheel.core.paths import FONT_FILE_NAME  # noqa: E402


def find_font():
    """返回要内嵌的字体文件，以及它是否就是运行时认的那个名字。

    运行时（core.paths.FONT_FILE_NAME）只按固定文件名查找，不 glob 目录下的
    任意 ttf——字体解析是可被恶意构造文件利用的攻击面。所以这里必须优先取
    那个固定名；取到别名字体时仍然内嵌（--add-data 保留原名，至少 exe 里有
    这份资源），但要显式说明运行时找不到它，否则打包脚本报告"已内嵌"而程序
    静默回退到系统字体，两边都不报错。
    """
    if not FONT_DIR.is_dir():
        return None, False
    exact = FONT_DIR / FONT_FILE_NAME
    if exact.is_file():
        return exact, True
    for pattern in ("*.ttf", "*.otf"):
        fonts = sorted(FONT_DIR.glob(pattern))
        if fonts:
            return fonts[0], False
    return None, False


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

    font, runtime_match = find_font()
    if font:
        cmd += ["--add-data", f"{font}{';' if sys.platform == 'win32' else ':'}."]
        print(f"[*] 内嵌字体: {font.relative_to(ROOT)}")
        if not runtime_match:
            print(f"[!] 但运行时只按固定名 {FONT_FILE_NAME} 查找，这份字体不会被加载。")
            print(f"    如需生效，请把文件改名为 {FONT_FILE_NAME}。")
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
