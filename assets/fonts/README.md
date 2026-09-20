# assets/fonts

此目录用于放置可选的内嵌字体文件（如 `HYWenHei-65W.ttf`）。

**仓库不包含任何字体文件**（字体版权归属原作者；`.gitignore` 全局排除
`*.ttf` / `*.otf`）。如需内嵌字体：

1. 自行获取字体文件，放入本目录；
2. `python scripts/build_exe.py` 会自动检测并 `--add-data` 内嵌；
3. 源码运行时，程序按以下顺序查找：本目录 → 程序所在目录 → exe 解包目录，
   均失败时回退为 Microsoft YaHei。

未放置字体不影响任何功能，仅界面与转盘文字使用回退字体渲染。
