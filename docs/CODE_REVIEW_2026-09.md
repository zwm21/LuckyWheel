# 代码审查报告与实施计划（2026-09-24）

本文档记录一次全仓审查（结构 / 卫生 / 安全 / 质量 / 算法性能）的结论与分批实施方案。
审查方式：三路并行专项（安全、算法性能、结构与质量）+ 逐条自主复核，
所有「高危」项均在本地实测复现，未复现的一律标注为「疑似」。

## 0. 基线状态（修改前）

- `pytest`：380 passed，offscreen 平台，无 skip 失败。
- `ruff check .` 与 `ruff format --check .`：干净。
- `scripts/verify_gui.py --entry main|module`：各 11 个 `[ok]`，exit 0。
- `.git` 松散对象 221.9 MiB，其中 6 个约 38 MB 的旧 exe blob 已不被任何 ref 可达
  （另见批次 7 的历史收尾计划，本文不涉及）。

## 1. 安全缺陷

### 高危（已实测复现）

| 编号 | 位置 | 问题 | 实测证据 |
|---|---|---|---|
| S1 | `core/storage.py:120-127` | `load_state` 只捕获 `json.JSONDecodeError`；深度嵌套 JSON 让 `json.loads` 抛 `RecursionError`，穿透 `loadData` → `MainWindow.__init__`，程序无法启动 | 3000 层 `{"a":` 嵌套文件实测抛 `RecursionError` 并逃出 `load_state` |
| S2 | `core/models.py:122`、`:130-133` | `clamp()` 只校验类型不校验数值范围，`ui_font_size` 仅验 `>=1`，`_is_int_list` 仅验 int。`ui_font_size: 1e12`、`window_geometry: [1e20,...]` 均通过校验，随后进 `QFont`/`QRect` 抛 `OverflowError` | 实测 `clamp()` 后 `ui_font_size == 1000000000000`、geometry 仍是合法 int 列表 |
| S3 | `core/storage.py:74-77` | `isinstance(True, int)` 为真，`current_group: true` 混过校验并原样写回 JSON，数据类型被静默改变 | 实测 `parse_state` 返回 `current_group is True`，`to_dict()` 序列化为 `true` |
| S4 | `core/storage.py:114` | 解析外部 JSON 无任何大小、条目数、字符串长度上限 | `read_text` 前无 `st_size`/上限判断（源码检索证实）；2 GB 文件实测加载 36 s、保存 17 s 并生成 2 GB `.bak` |

### 中低危

- **S5**（中）`ui/main_window.py:152-153` 对每条 warning 调一次 `notify`；2 万条非法项会产生 2 万条 warning，即 2 万个非模态 `QMessageBox` 同时排队弹出，界面被淹没。
- **S6**（中）`core/storage.py:166-171`：备份用 `os.replace` 把活动文件改名成 `.bak`，再 `replace(tmp, path)`，两步之间目标路径不存在。若此刻崩溃或第二步失败，只剩 `.bak`；而 `load_state` 与 `loadData` 从不读 `.bak`，缺文件时直接写默认数据——用户数据静默丢失。
- **S7**（低）`core/paths.py:104-107` `font_candidates` 会 glob 程序目录下任意 `*.ttf/*.otf` 交给 `QFontDatabase.addApplicationFont`（字体解析是已知攻击面）。该函数在生产中无调用方，当前不可利用，但与「字体只从 assets/fonts/ 固定文件名加载」的既定策略相悖。
- **S8**（低）`scripts/verify_gui.py:41-46` 把用户真实数据文件复制进 `build/verify/wheel_data.seed.json`，敏感内容落在构建产物目录。

### 已确认无害（记录在案，避免重复审查）

- 反序列化只用 `json.loads`，全仓无 `eval/exec/pickle/yaml.load/marshal/shelve`。
- `tests/data/hostile_types.json` 覆盖的类型混淆场景确已被 `parse_state` 防住（`tests/unit/test_storage.py:68` 逐条断言）。
- 原子写的核心步骤健全：`mkstemp`（O_EXCL）→ `fsync` → `os.replace`；`os.replace` 不跟随符号链接，无任意写。
- `core/spin.py` 用 `random`（Mersenne Twister），7 扇区 20 万次分布均匀（各扇区 28271~28708），`plan_spin` 的 winner 与 `sector_at(final_angle)` 在 7 种扇区数 × 2 万次下 0 次不一致。
- `scripts/build_exe.py` 用参数列表调 `subprocess.run`，无 `shell=True`，无外部输入进入参数。
- GUI 输入面干净：无 `QProcess`、无按路径加载 `QPixmap`、无动态代码执行；主题全为 `theme.py` 硬编码 token，用户数据无法进入 QSS。
- 无硬编码密码/令牌/内部绝对路径；无 logging 模块，无日志注入面。

## 2. 仓库结构与卫生

- **R1**（高）`.gitignore:33-34` 的 `# 文档` / `docs/` 是笔误。`git check-ignore -v` 证实 `docs/FIXUP_PLAN.md`、`docs/REVIEW_REFACTOR.md` 被忽略，`git status` 不显示、无法 `git add`；而 `docs/REFACTOR_PLAN.md`、`REFACTOR_PLAN_V2.md` 因先 add 后 ignore 仍在版本控制内。协作者完全看不到新计划文档。
- **R2**（高）`core/paths.py:96` 用 `parents[2]` 指向 `src/assets/fonts`（不存在；同文件 `program_dir():27` 用的就是 `parents[3]`）。生产实际调用的 `ui/bootstrap.py:22-25` 在非 frozen 时只看 `src/luckywheel/ui/`，而字体在 `assets/fonts/`（已 ignore）与仓库根。结果：源码运行模式下放进 `assets/fonts/` 的字体永远加载不到，回落 Microsoft YaHei；而打包版用 HYWenHei——`layout` 的字号求解「被测字体 ≠ 生产字体」。`tests/unit/test_paths.py:74` 只断言路径字符串含 "assets"/"fonts"，所以是绿的。README:66-67 承诺的加载顺序代码并未实现。
  - **R2a**（高，R2 的连带 bug，已实测）`core/storage.py:82-86` 在字体家族缺键时填默认字符串而非 None，使 `ui/main_window.py:158,160` 的 `state.x or self.x` 回退永远不触发——`:157` 注释声称「文件未记录字体家族时，保留 loadEmbeddedFont 已确定的选择」，实际被 `parse_state` 的默认值覆盖。实测：数据文件无字体字段时 `state.ui_font_family == "Microsoft YaHei"`，回退结果仍是 Microsoft YaHei，`loadEmbeddedFont` 的选择被丢弃。
  - **R2b**（中）字体查找有两套并存实现：`bootstrap.loadEmbeddedFont` 自己拼路径，`core/paths.py:92-123` 的 `font_candidates`/`find_embedded_font` 生产无调用方（死代码），且会 glob 程序目录下任意 `*.ttf/*.otf` 交给 `QFontDatabase.addApplicationFont`——字体解析是已知攻击面。
- **R3**（中）`.pre-commit-config.yaml:35` 的 `types: [text]` 会先过滤掉二进制文件，`git add -f dist/LuckyWheel.exe` 时脚本收不到文件名、直接放行——守卫恰在它要防的场景里空转。真正兜底只剩 CI 的 `git ls-files | grep`。
- **R4**（中）四份 docs 是链式修订而非逐字重复，但 v1/v2 的事实已过期（宣称「main.py 1515 行」「.git 289 MB」「测试 250 项」，实际分别为 19 行、221.9 MiB、380 项）。四份与 `CHANGELOG.md` 职责高度重叠。
- **R5**（中）README:71-91 项目结构过期：漏掉 `ui/panels/` 五个文件、`palette.py`、`save_scheduler.py`、`bootstrap.py`、`__main__.py`、precommit 脚本。
- **R6**（低）`ui/main_window.py:25` 的 `show_info` 导入带 `noqa: F401` 掩盖了真实的未使用导入（测试替换的是 `bootstrap.show_info`，与这里的导入无关）。
- **R7**（低）`ui/main_window.py:335` 注释写「初始左侧 300px」，代码是 250。
- **R8**（观察，不改）`pyproject.toml:10` `requires-python = ">=3.9"`，而 CI 只测 3.10/3.12/3.13。已检索全仓无 `match` 语句、无 `X | Y` 类型注解、无 `strict=True`/`removeprefix` 等 3.9 之后 API，故声明准确；CI 不测 3.9 属版本策略选择而非缺陷。
- **R9**（低）仓库根另有一份 3.3 MB `HYWenHei-65W.ttf`（已 ignore），无任何代码引用，是重构前布局残留。
- **R10**（低）`tests/statistical/test_fairness.py:3,17` 仍写「main.py:265-305」「main.py 的 timer_interval」，而 main.py 现仅 19 行。

## 3. 代码质量

- **Q1**（中）`ui/wheel.py` 五处完全相同的缓存失效三连（`setFontSize:74-76`、`setSectorColors:251-253`、`setShadowEnabled:258-260`、`setFontFamily:266-268`、`setItems:279-281`、`_onResizeSettled:307-309` 共六处），应抽成 `_invalidate_cache()`。
- **Q2**（中）几何魔数重复：`wheel.py:406` `radius = side * 0.44` 与 `:429` `wheel_radius = min(...) * 0.44` 是同一量算两遍（即 `layout.WHEEL_DIAMETER_RATIO / 2`），正是 CHANGELOG「移除」段声称删掉的重复计算；测试侧 `test_render_cache.py:69-77`、`test_pixel_baseline.py:39`、`test_current_main_behavior.py:29,102` 把 0.88/0.62/0.9/0.7/0.18/10 全硬编码，改 layout 常量时这些测试会静默测旧几何。
- **Q3**（中）`wheel.py:174-176` 重复计算 `num`/`sector_span`（与 `:133-134` 相同）。
- **Q4**（中）死代码：`models.py:83-105` 的 `AppState.from_dict` 与 `Group.from_dict` 生产从不调用（生产走 `storage.parse_state`），只有 `tests/unit/test_models.py` 在用——测试验证的不是生产路径，两套解析器有漂移风险。同类的还有 `models.py:57 current_group_object`、`spin.py:72 velocity_at`、`save_scheduler.py:38 pending()`、`wheel.py:313 startSpin(initial_velocity=None)`。
- **Q5**（中）跨对象私有访问：`main_window.py:394` 调 `spin_panel._updateBatchButtonState()`，`items_panel.py:149` 读 `window._updating_list`。
- **Q6**（中）`tests/` 有 7 份近乎逐字相同的 `window` fixture（gui 六个 + `test_window_contract.py:47`），应下沉 conftest。
- **Q7**（低）复杂度：`initUI` 137 行、`renderCache` 133 行、`paintEvent` 76 行、`spin_panel.__init__` 91 行；`storage.save_state` 嵌套 4 层。无超 4 层嵌套、无注释掉的代码块、无空 except。
- **Q8**（低）`src/` 全部 115 个参数/返回零类型注解（仅 `scripts/precommit_no_binaries.py:19` 有），无任何类型检查可能。
- **Q9**（低）`main_window.py:47-59` 九个属性在 `loadData` 中被无条件覆盖，`__init__` 的赋值在正常路径下是死写（但 `loadData` 之前 `initUI` 会读 `user_list_height`/`drawn_user_height`，作为兜底应保留并注释说明）。
- **Q10**（低）`settings_panel.py:156-189` 用 `hasattr` + `try/except` 三重防御同一次取控件操作，过度。

## 4. 算法与性能

### 明显可优化（有量化依据）

- **P1** `ui/wheel.py:180-234`：文本阶段占 rebuild 约 98%，是唯一真瓶颈。实测 side=700 时扇区填充（策略 J 之后）仅 0.19/0.19/0.37 ms，而文本阶段 8.18/14.35/25.03 ms（n=41/100/200），约 0.12 ms/条。每条目约 9 次 `measure`（每次新建 `QFont` + `painter.setFont` + `fontMetrics`）外加 2 次 `drawText`（阴影使绘制翻倍）。方向：`measure` 改用独立的 `QFontMetrics(QFont)`，不污染 pixmap 的 painter。
- **P2** `ui/wheel.py:405-442`：每帧重画静态装饰，实测 0.088 ms，是旋转 blit（0.03 ms）的 2.9 倍。每帧新建 `QFont`、解析 `QColor("#FF0000")`（实测 1.48 µs/次）、构造 `QPolygonF`。三者只依赖 `side`，应在 side 变化时缓存为第二张小 pixmap。
- **P3** `panels/spin_panel.py:258 → panels/base.py:24 → main_window.py:381-383`：批量每轮全量重建，总量 O(n²)。每轮 `clear()+addItems()` 为 O(n)，且 `setItems` 清空字号缓存并使 pixmap 失效；n=200 时每轮多付一次 25 ms rebuild。方向：批量期对列表做增量 diff。
- **P4** `ui/bootstrap.py:22-25`：源码运行永不加载内嵌字体（见 R2/R2a），导致字号求解的被测字体与生产字体不一致。批次 A 已修。

### 疑似问题（需实测后决定）

- **P5** `core/layout.py:15+17`：字号硬底 8px 与 `max_h ≈ 2.728r/n` 冲突。实测 HYWenHei 在 8px 的 `fm.height() == 9`，故 `n > 0.1335·side`（side=700 即 n≈93）时二分必然触底返回 8px，文字纵向溢出相邻扇区，「自适应」静默失效。方向：下界由 `max_h` 反推，或超密时截断/竖排。**此项改变视觉输出，仅在能证明不劣化的前提下实施。**
- **P6** `core/layout.py:87`：缓存 key 不含字体家族，正确性完全依赖 `setFontFamily`/`setItems` 手动 `clear()`；将来新增影响度量的 setter 若漏 clear，会静默用错字号。
- **P7** `core/storage.py:166-171`：备份两步之间数据真空（见 S6）。

### 已确认合理（改动时不得破坏）

- 几何链闭合，无 off-by-one：`arcTo` 正扫掠使 θ 递减，扇区 i 落在 θ∈[(num-1-i)·span, (num-i)·span]，与 `wheel.py:225` 取 `sector_colors[num-1-i]` 一致；`rotate(a)` 使局部 θ→θ+a，与 `spin.py:39` 反算 `270-rotation`、`spin.py:96` 落点 target 三者自洽。指针尖端仅 5px 径向内偏，无角度误差；`sector_at:41` 的 `min()` 兜住了 `%360` 舍入到 360.0 的边界。
- 抽取算法无偏：`spin.py:92` 用 `rng.randrange(count)` 定 winner，无 sort-by-random-key 之类 biased shuffle；`EDGE_MARGIN = 0.18·span` 使约 1e-13° 的浮点漂移不可能越界。
- render cache 确实命中，每帧无重复计算：guard 覆盖 pixmap/dpr/side 三项，80 ms 去抖与 dpr 变化均处理；`paintEvent` median 0.11 ms，占 60fps 预算 0.7%。
- 防抖不会丢最后一次修改：callback 落盘时重新读 live state 而非快照，`flush_now` 先 `stop()` 再执行，timeout 与手动 flush 同走该入口，不会双写。

## 5. 实施计划

总原则：**不改变软件功能**。所有改动按「可观测行为不变」验收，四个批次各自独立提交。
每批完成的验证链：`pytest`（计数不得低于 380 且无新增失败）、`ruff check` + `format --check`、
`verify_gui --entry main|module`（各 11 个 `[ok]`）、必要时加 `build/verify` 下的像素对比。

### 批次 A：仓库卫生与结构（零功能影响，最低风险）

1. 删 `.gitignore:33-34` 的 `# 文档` / `docs/`（R1）。
2. 修 `core/paths.py:96` 的 `parents[2]` → `parents[3]`（R2）。
3. 统一字体查找：`core/paths.py` 的 `font_candidates`/`find_embedded_font` 改为生产唯一实现
   （去掉 glob，只收固定文件名，见 S7），`bootstrap.loadEmbeddedFont` 委托它（R2b）。
4. 修 R2a：`parse_state` 字体家族缺键给 None，`clamp()` 放行 None，`to_dict()` 不写 None 键，
   使 `loadData` 的回退真正生效。**这是行为修复**：源码运行从「永远 Microsoft YaHei」
   变为「加载 assets/fonts/ 下的 HYWenHei」，与打包版一致、也正是 README 承诺的顺序。
   离线环境缺 CJK 字体，像素基线本地无法区分二者，故该变化只能由真实 Windows 目视确认。
5. 删 `main_window.py:25` 未使用的 `show_info` 导入（R6），修 `:335` 的 300px→250px 注释（R7）。
6. `.pre-commit-config.yaml` 去掉 `types: [text]`，让守卫真正收到二进制文件名（R3）。
7. `pyproject.toml` 不动（R8 核实为准确声明）。
8. README 项目结构补全（R5）与字体顺序描述修正。
9. 不删仓库根的 `HYWenHei-65W.ttf`（R9）：它已进入 `font_candidates` 的「程序旁边」候选，
   删与不删都不影响加载结果，而它是用户的字体资产，删除应由用户决定。

### 批次 B：健壮性与安全加固（每项配回归测试）

1. `storage.load_state` 把 `RecursionError` 与 `ValueError` 一并纳入损坏分支（S1）。
2. `models.clamp` 增加数值上限：`ui_font_size`、`wheel_font_size`、`list_height`、`drawn_list_height`、`batch_spin_count` 与 `window_geometry`/`splitter_sizes` 各分量设上界，越界回落默认值（S2）。
3. `storage.parse_state` 的 `current_group` 改用 `_is_int` 风格校验，排除 bool（S3）。
4. `load_state` 增加文件大小上限与条目数上限，超限按损坏处理并隔离（S4、S5）；
   warning 合并为一条汇总提示，避免 2 万个弹窗（S5）。
5. `save_state` 的备份从 `os.replace` 改为 `shutil.copy2`，消除两步之间的数据真空（S6）。
   顺序调整为先写 tmp → 复制出 .bak → replace(tmp, path)，任一步失败都保留原文件。
6. 每项在 `tests/unit/test_storage.py` / `test_models.py` 补断言；S1/S2 另加 GUI 级回归
   （构造真实 `MainWindow`， hostile 数据不得导致启动崩溃）。

### 批次 C：代码质量与死代码清理（不改变行为）

1. `wheel.py` 抽 `_invalidate_cache()`，六处失效点改为调用（Q1）。
2. `layout.py` 导出转盘半径常量，`wheel.py` 的 0.44 与测试里的硬编码几何改为引用（Q2、Q3）。
3. 删除死代码：`AppState.from_dict`、`current_group_object`、`velocity_at`、`save_scheduler.pending()`、
   `startSpin` 的 `initial_velocity` 形参（Q4）。删除前逐个确认无生产调用方；`test_models.py` 中针对
   `AppState.from_dict` 的断言改写成走 `parse_state`，保证安全网不减弱反而更贴生产路径。
   注意 `Group.from_dict` 一度也在删除清单里，实际是生产路径的一环（`main_window._write_state`
   把 UI 持有的 dict 形态 groups 转回 `Group`），已恢复并补注释说明这个桥接作用。
4. `_updateBatchButtonState` 改为公开方法；`_updating_list` 提供只读访问器（Q5）。
5. 7 份重复 `window` fixture 下沉 `tests/conftest.py`（Q6）。
6. 修正 `test_fairness.py` 的过期 main.py 行号引用（R10）。
7. `main_window.py:47-59` 的兜底默认值补注释说明为何保留（Q9）。

### 批次 D：渲染与交互性能优化（以像素基线与冒烟为不回归证据）

1. `_measure` 改用 `QFontMetrics(QFont)`，不再经由 `painter.setFont`（P1）。
   验收：`test_pixel_baseline.py` 逐像素不变；`renderCache` 耗时对比。
2. `paintEvent` 的中心装饰与指针按 `side` 缓存为第二张小 pixmap，只在 side 变化时重建（P2）。
   验收：像素基线不变 + 单帧 `paintEvent` 耗时对比。
3. 批量抽取期间列表改为增量 diff，`setItems` 增加「内容未变则短路」（P3）。
   验收：`tests/gui/test_save_debounce.py`、`test_stop_single_spin.py` 全绿 + 冒烟 11 个 `[ok]`。
4. `FontSizeCache` 的 key 纳入字体家族，去掉对调用方手动 `clear()` 的隐式依赖（P6）。
5. P4/P5 视批次 A 第 3 步的实测结果决定是否推进；P5 若会改变视觉输出则只记录不改。

### 不做的事（明确排除）

- 不动 `docs/REFACTOR_PLAN*.md` 与 `FIXUP_PLAN.md` 的内容（属历史记录，批次 7 收尾时统一归档）。
- 不做全仓类型注解补全（Q8）：收益低、diff 面极大，与「不影响功能」的目标冲突。
- 不重构 `initUI`/`renderCache` 的函数拆分（Q7）：纯结构改动，风险与收益不成比例。
- 不触碰 tag force push、`LuckyWheel` tag 删除、`git gc` 等历史收尾操作（批次 7，需单独确认）。

## 6. 风险与回退

每个批次独立提交，任一批次验证失败即 `git revert` 该提交，不影响其余批次。
批次 A 第 4 步（字体回退）是唯一有意改变可观测行为的改动——它修复的是「注释声明的意图
未实现」这一缺陷，方向是让源码运行与打包版一致；本地 offscreen 缺 CJK 字体，像素基线
无法区分 Microsoft YaHei 与 HYWenHei，故该变化在真实 Windows 上的观感需人工确认。
批次 B 全部是收紧密码，最坏情况是把原本「能启动但行为异常」的场景变成「按损坏处理并用
默认数据」，不会让原本正常的场景退化。批次 D 的每一项都有像素基线或冒烟作为客观不回归证据。

## 7. 实施记录

### 批次 A：仓库卫生与结构（已完成）

改动：`.gitignore` 删 `docs/` 笔误；`core/paths.py` 的 `parents[2]`→`parents[3]`、`font_candidates`
去 glob 并支持显式文件名、`find_embedded_font` 同步加参；`ui/bootstrap.py` 的 `loadEmbeddedFont`
委托 `paths.find_embedded_font`（删 `os`/`sys` 导入）；`core/storage.py` 字体家族缺键给 None；
`core/models.py` 的 `clamp` 放行 None、`to_dict` 不写 None 键；`ui/main_window.py` 删未使用的
`show_info` 导入、修 300px→250px 注释；`.pre-commit-config.yaml` 去 `types: [text]`；
README 补全项目结构与字体顺序；新增本文档；`tests/unit/test_storage.py` 补 3 个回归用例。

验证：`pytest` 383 passed（基线 380 + 新增 3）、`ruff check` 与 `format --check` 干净、
`verify_gui` 双入口各 12 个 `[ok]` 且 exit 0（冒烟脚本自身已含停止按钮检查，11→12 与本次改动无关）。
字体接线实测生效：`find_embedded_font` 返回 `assets/fonts/HYWenHei-65W.ttf`，
`loadEmbeddedFont` 返回族名 `HYWenHei`。

### 批次 B：健壮性与安全加固（已完成）

改动：`core/storage.py` 增加 `MAX_DATA_FILE_BYTES`/`MAX_ENTRIES_PER_GROUP`/`MAX_TEXT_LENGTH`
三道上限与 `_is_int`，`load_state` 读前查 `st_size`、捕获 `RecursionError`，`current_group` 排除
bool，`save_state` 备份改 `shutil.copy2`；`core/models.py` 增加字号/高度/批量次数/坐标的绝对
上界并在 `clamp` 中同时收上下界；`ui/main_window.py` 抽出 `_notifyWarnings` 把多条告警合并为
一次汇总提示；新增 `tests/gui/test_hostile_data.py`（GUI 级 hostile 回归）与两个 unit 测试类。

验证：`pytest` 397 passed、`ruff check` 与 `format --check` 干净、`verify_gui` 双入口各 12 个
`[ok]` 且 exit 0。`test_clamped_values_are_qt_safe` 直接断言收敛后每个整数都落在 C int 安全
范围；`test_backup_never_removes_original` 让 `os.replace` 抛错后确认原文件仍在原地。

### 批次 C：代码质量与死代码清理（已完成）

改动：`ui/wheel.py` 抽 `_invalidate_cache()` 并让六处缓存失效点改用它，`paintEvent` 改用
`layout.WHEEL_RADIUS_RATIO` 并复用已算出的 `radius`，`startSpin` 去掉 `initial_velocity` 死
参数；`core/layout.py` 导出 `WHEEL_RADIUS_RATIO`；删 `AppState.from_dict`、`current_group_object`、
`spin.SpinPlan.velocity_at`、`save_scheduler.pending()`（`Group.from_dict` 经核查是生产路径的
桥接，保留并补注释）；`spin_panel._updateBatchButtonState` 改名公开、`MainWindow.updating_list`
只读 property 取代面板对 `_updating_list` 的直接读取；7 份重复 `window` fixture 下沉
`tests/conftest.py` 的 `build_main_window`/`window`；`test_models.py` 全面改走
`storage.parse_state` 生产路径；`test_fairness.py` 去掉对已不存在的 main.py 行号的引用。

验证：`pytest` 397 passed（与批次 B 同数，纯清理无新增用例）、`ruff check` 与
`format --check` 干净、`verify_gui` 双入口各 12 个 `[ok]` 且 exit 0。`velocity_at` 删除后，
"收尾速度约为初速度的 TAIL_RATIO" 这条性质改在 `eased_fraction` 上以斜率比断言，安全网未减弱。
