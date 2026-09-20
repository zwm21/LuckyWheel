#!/usr/bin/env python
"""pre-commit 本地守卫：拒绝把 dist/ 产物与字体文件暂存进仓库。

背景：.git 曾因 8 次提交约 37MB 的 exe 膨胀到 289MB，字体文件
（HYWenHei-65W.ttf，3.3MB，版权归属作者）同样不应入库。

用法（由 .pre-commit-config.yaml 调用，传入暂存区文件名）：
    python scripts/precommit_no_binaries.py <file>...
退出码：发现问题为 1，并打印被拒绝的文件。
"""

import sys
from pathlib import PurePath

BLOCKED_DIRS = ("dist", "build")
BLOCKED_SUFFIXES = (".exe", ".ttf", ".otf")


def is_blocked(path: str) -> bool:
    p = PurePath(path)
    parts = p.parts
    if parts and parts[0] in BLOCKED_DIRS:
        return True
    if p.suffix.lower() in BLOCKED_SUFFIXES:
        return True
    return False


def main(argv):
    blocked = [f for f in argv[1:] if is_blocked(f)]
    if blocked:
        print("拒绝提交以下文件（仓库不收录构建产物与字体资产）：")
        for f in blocked:
            print(f"  - {f}")
        print("\n发布用 GitHub Release，字体放入 assets/fonts/ 且该目录被忽略。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
