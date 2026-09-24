# LuckyWheel 重构符合性审查报告（第二轮）

审查日期：2026-09-21 ｜ 审查范围：`beec6fc`..HEAD（21 个提交）＋ 当前工作区
对照基准：`docs/REFACTOR_PLAN.md`（v1）、`docs/REFACTOR_PLAN_V2.md`（v2，冲突处以 v2 为准）
本地环境：Windows + python3.10 + offscreen；测试 250 项全绿，`ruff check` / `ruff format --check` 全绿

> 本版取代同日第一轮报告。第一轮之后工作区发生了两件事：高 DPI 修复提交
> （`be83552`），以及一次 `git filter-branch` 历史重写（reflog 有记录）。阶段 1
> 的结论因此从「未执行」变为「已执行、收尾未做」，详见 D1。

## 总体结论

阶段 0、2、5 基本达成且质量较高；阶段 3 核心算法全部落地，但统计层验收与
性能线有缺口；阶段 4 未完成核心目标；阶段 1 的重写已执行，然而瘦身、推送、
tag 清理三项收尾都未做，本地 `.git` 仍 217MB。

## 一、符合规划的部分（本轮逐项复核过的要点）

- **core 层零 Qt 依赖**：`core/{models,spin,layout,paths,storage}.py` 无任何
  PyQt6 import（`core/__init__.py` 仅 docstring 提及）。
- **spin.py**：`POINTER_ANGLE=270`、`sector_at` 与旧公式逐点一致、
  `plan_spin` 由 `rng.randrange(count)` 保证均匀、`EDGE_MARGIN=0.18` 边界
  裕量、`rotation_at` 帧率无关（v2 M2）、`random` 取代 `secrets`（v2 M3）。
- **layout.py**：二分查找 + `FontSizeCache` 对 `(text, max_w, max_h)` 缓存，
  测量函数注入，docstring 记录与旧线性算法逐点相等。
- **P2 端到端**：`tests/gui/test_wheel_spin.py` 把「动画终角 → `sector_at`
  反算 → emit 的 (index, text)」整条链路接起来。
- **P5 QSS 白名单**：`tests/gui/test_theme.py` 钉住滚动条控件不单独设 QSS
  与 token 合并后样式逐项相等。
- **M6 fixture 独立**：`tests/data/` 四个 fixture 均在版本控制内，未引用真实
  `wheel_data.json`。
- **M7 入口兼容**：`main.py` 保留为 wrapper；`python -m luckywheel`、
  `app.py`、`__main__.py`、`pyproject.toml` 的 `[project.scripts]` 齐备。
- **卫生三件套**：`.gitignore`（含 `dist/`、`*.ttf`、`wheel_data.json`，不再
  忽略自身）、`.gitattributes`（LF + 二进制标记）、`.pre-commit-config.yaml`
  （ruff 双钩 + check-json/yaml/toml + end-of-file-fixer + large-files +
  本地 dist/字体拦截 hook）。
- **构建链**：`scripts/build_exe.py` 字体可选、spec 写临时目录、产物全被
  ignore；`release.yml` tag 触发上传 exe。本地 hook 与 CI 双拦的设计意图
  符合 v2 P7。
- **README 公平性措辞克制**：「先等概率选中目标，再把动画演到对应位置」，
  未出现「内定」类表述。

## 二、偏差清单（按严重度排序）

### D1. 阶段 1 历史重写：执行了，收尾三项全缺 —— 严重

- filter-branch 已跑（reflog 三次 rewrite），`git log -- dist/` 为空，
  `git ls-files` 无 exe，`refs/original` 已清。**重写本身完成**。
- 但 `git count-objects -vH`：loose objects 129 个占 **216.47 MiB**，pack 仅
  165 KiB。旧对象未被 gc 回收，本地 `.git` 仍 217MB，距规划「降到 2MB 量级」
  的验收线差两个数量级。缺 `git reflog expire --expire=now --all` 与
  `git gc --prune=now`。
- **未 push**：`origin/main` 仍是重写前历史，本地已分叉。规划的
  `push --force --all && --tags` 未执行，GitHub 端分毫未动。
- 误建的 `LuckyWheel` tag 仍在（指向 `da2134d`）；且 `v1.0.1` 与 `v1.0.4`
  两个 tag 同指 `1201750` 一个提交。重写后 4 个旧 Release 与新 tag 的关联
  是否失效，本机无 `gh`，未能核实——这是 force push 前必须确认的一项。

### D2. 阶段 4 UI 分层未完成 —— 严重

- `main_window.py` **1071 行**（第一轮报告记为 936 行，本轮实测 1071），
  验收线 400 行，超标 168%。
- `ui/panels/{group,items,settings}_panel.py` 不存在；`ui/save_scheduler.py`
  不存在，500ms 去抖以 `_save_timer` 内联在 MainWindow（main_window.py:92-96、
  447-453），功能在、结构不符。
- `wheel.py` 409 行，同样越过 400 行线。

### D3. 公平性统计层断言缺失 —— 中

- `tests/statistical/test_fairness.py` 仍只有旧实现基线，文件自述「阶段 3 由
  test_planned_spin 取代」，但 **`test_planned_spin` 不存在**。新实现的均匀性
  只有单测不变式，没有 v2 M5 要求的 20 万次相对偏差 < 1.5% 断言与基线对照。
- `test_spin.py:51` 的 count 覆盖为 `[1,2,3,4,8,10,41]`（不变式）与
  `[1,2,3,4,5,8,10,17,41,60,97]`（公式一致性），有边界值但非规划要求的
  1..60 逐值。

### D4. 死代码清理遗漏 —— 中

- `SECTOR_COLORS` 仍是可变 list（wheel.py:25），main_window.py:116 仍
  `random.shuffle(SECTOR_COLORS)` 原地打乱模块级常量（v1 阶段 3 / v2 M3
  明确要求改元组 + 打乱副本）。
- 裸 `print` 三处：main_window.py:101、424、481。
- main_window.py:766 一行注释掉的死代码 `# self.applyGlobalFont(...)`。
- 另：wheel.py 的 `self.font_family` 经 `setFontFamily` 设置并被 4 处使用，
  已非死属性，此项较第一轮报告已消解。

### D5. app.py 绕道根级 main.py，打包/安装路径有缺口 —— 中（本轮新发现）

`app.py:20` 的 `create_window()` 用 `from main import MainWindow`，而
MainWindow 实际住在 `luckywheel.ui.main_window`。仓库根目录运行时碰巧可行
（main.py 在），但 `pip install` 后在任意目录执行 `luckywheel` 命令或
`python -m luckywheel`，根级 `main.py` 不存在，直接 ImportError。同时
app.py:19 的注释「MainWindow 现居根级 main.py，拆分完成后将迁入 ui/」与
事实相反，已经过期。第一轮报告未触及此项。

### D6. renderCache 性能未达验收线 —— 轻~中（本轮新发现）

实测（offscreen，预热后 5 次均值）：n=8 为 2.9ms，n=41 为 16.4ms，
n=200 为 **73.2ms**。阶段 3 验收要求 n=200 降到 30ms 以内（旧值 112ms），
实际只降了 35%。规划中的 ~80ms resize 去抖 + 旧 pixmap 拉伸兜底也未实现，
paintEvent 仅在 `min(w,h)` 或 dpr 变化时同步重建（wheel.py:336-341）。

### D7. CI 门禁低于规划 —— 轻

- ci.yml:34 为 `--cov=src/luckywheel/core --cov-fail-under=70`：低于规划的
  core ≥ 90%，且无整体 ≥ 60% 门禁。
- v2 P7 的 CI 二进制守卫（`git ls-files | grep -E '\.(exe|ttf)$'` 必须为空）
  缺失。本地 pre-commit hook 存在，但其 `types: [text]` 使二进制恰不触发
  该 hook，实际兜底靠 `check-added-large-files`（>2MB 拒绝）——有效，但
  与 hook 自身声明的拦截目标错位。

### D8. 其余记录项

- main.py 为 24 行且自行构造 QApplication/Fusion，与 app.py:34-38 重复
  （v2 M7 建议的三行转调 shim 未做）。
- `packaging/` 目录不存在，实为 `scripts/build_exe.py`（v1 正文即写
  scripts/，是目标结构图过期，非实现偏差）。
- `tests/gui/` 命名与规划图不同：`test_wheel_spin.py` 对应图中的
  `test_wheel_widget.py`，无 `test_main_window.py`（其覆盖分散在
  test_extract_by_index / test_save_debounce / test_splitter_layout /
  test_window_geometry 四个文件）。
- `scripts/verify_gui.py` 为计划外产物（CI GUI 冒烟用），方向合理。
- 工作区 `build_exe.bat` 有未提交修改：39 行的环境检查逻辑删到只剩
  `python scripts/build_exe.py` + pause。改动方向合理（检查已移入
  build_exe.py），但未提交，需用户确认取舍。
- v2 P3 的条目稳定 id（`Entry(id, text)`）未实现，models.py 仍纯字符串
  list，重复项「抽的是哪个 1」仍无解。

## 三、建议的后续动作（按优先级）

1. **阶段 1 收尾**（改动前先备份）：`git reflog expire --expire=now --all &&
   git gc --prune=now --aggressive` 验证 `.git` 降到 2MB 量级；删
   `LuckyWheel` tag；在沙箱 fork 预演 Release/tag 关联后再
   `push --force --all && --tags`。
2. **补 test_planned_spin**：对 `plan_spin` 做 20 万次卡方，断言相对偏差
   < 1.5%，与 test_fairness.py 的旧基线同目录对照。
3. **修 app.py 导入**：`create_window` 直接 `from luckywheel.ui.main_window
   import MainWindow`，同步删过期注释；main.py 收缩为转调 `luckywheel.app`。
4. 拆 `panels/`、抽 `save_scheduler.py`，把 main_window.py 压进 400 行。
5. `SECTOR_COLORS` 改元组、shuffle 改副本、删三处 print 与注释死代码。
6. CI 补二进制守卫；门禁上调到 core ≥ 90% 并加整体 ≥ 60%。
7. renderCache 性能：定位 73ms 去向（大概率是逐扇区 QFontMetrics 与路径
  构建），补 80ms 去抖 + 拉伸兜底，目标 n=200 < 30ms。
