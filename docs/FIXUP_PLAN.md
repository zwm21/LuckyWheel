# LuckyWheel 收尾工作计划：Research + Plan（第二版）

日期：2026-09-21 ｜ 输入：`docs/REVIEW_REFACTOR.md`（第二轮审查，偏差项 D1–D8）
定位：本文只规划**不动代码**，等指示后按「第二部分」分批开工。每批独立提交、
独立验证、可单独回滚；任何一批验证链失败即停在当批，不叠加下一批。

与第一版的差异（全部来自本轮结合代码的实测，非推测）：R1 复现了入口 ImportError
并给出可执行的验证命令；R2/R3 补齐了 wheel.py 与 main_window.py 的精确行号与注入
点；R4 拿到了 initUI 全部控件清点与 `list_splitter` 横跨三窗格这一硬约束，拆分
方案因此从「三面板各自封装」改为「行为入面板、布局组装留 MainWindow」；R5 用
cProfile + 微基准定位了 73ms 的真实去向，并实测出一个 3.1 倍加速且视觉等价的
绘制策略，同时发现一个会让渲染慢 5.倍的陷阱；批次 1 的统计断言参数按 σ 数学
重算——第一版写的「20 万次、count=41、< 1.5%」实测必红（下文附证据）。
`build_exe.bat` 的未提交修改已由 `d5a7b5f` 提交，从待定事项移除。

## 总原则：如何保证不影响软件功能

1. **测试先于重构**。批次 1 先把网补密（统计断言 + 行为快照），后续所有批次
   都跑在这张网上。
2. **搬家式重构优先**。拆分只做「原样搬运 + 连接」，不在同一批里夹带逻辑修改；
   逻辑修改单独成批，便于二分定位。
3. **统一验证链**。每批完成后必跑，四项全绿才算完成：
   - `python -m pytest -q -p no:cacheprovider`（当前基线 250 项）
   - `ruff check . && ruff format --check .`
   - `python scripts/verify_gui.py --entry main`
   - `python scripts/verify_gui.py --entry module`
4. **行为可观测的变化留证**。benchmark 数字、测试计数变化写入提交信息；
   确需改变用户可见行为的（若有），先写进 CHANGELOG 再改。
5. **渲染与统计的结论必须来自实测**。本版所有性能数字、统计参数都先在本地
   offscreen 环境跑过再写进方案；实施时如实测与本文记录不符，以复现实测为准
   并回头修订本文，不按记忆中的数字调门禁。
6. **git 历史类操作全部置于代码落定之后**，且每一步前有备份确认、每一步后
   有验证点（见批次 7）。

环境备注（影响验证解读）：本地为 editable install（site-packages 内
`__editable__.luckywheel-2.0.0.pth` 指向 `src/`），故「仓库根目录碰巧可行」
有一部分是该安装方式掩盖的；offscreen 下 dpr 恒为 1，渲染对错靠 bbox 与
像素采样等客观测量，不靠目视。

---

## 第一部分：Research——逐项风险与保功能手段

### R1. main.py 与 app.py 的入口纠缠（D5）

事实与复现：`app.py:20` 的 `create_window()` 用 `from main import MainWindow`
拿窗口，而 MainWindow 住在 `luckywheel.ui.main_window`。本轮在临时目录实测
复现了缺陷（`cd /tmp` + `PYTHONPATH=src` 调 `create_window`）：

    ModuleNotFoundError: No module named 'main'

这正是 `pip install` 后在任意目录执行 `luckywheel` 命令的场景。约束（已核实）：
`from main import ...` 的消费方有 8 个测试文件（characterization×2、gui×6）、
`scripts/verify_gui.py:82-84`（`import main as legacy; legacy.MainWindow()`）
和 app.py 本身。main.py 收缩后**必须保留** `MainWindow`、`WheelWidget`、
`SECTOR_COLORS`、`SAVE_DEBOUNCE_MS` 四个 re-export（main.py:13-14），否则测试
网自己先红。

保功能手段：app.py 改为直连 `luckywheel.ui.main_window`；main.py 的 `__main__`
段转调 `luckywheel.app:main`（app.py:35-38 的 QApplication → Fusion → show 序列
与 main.py:16-24 逐行等价，合并后以 app.py 为单一事实来源）。验证增加一条**非
根目录复现**（即上面那条命令，修复后应打印 `create_window OK: MainWindow`）。

### R2. SECTOR_COLORS 的原地 shuffle（D4 之一）

事实：`wheel.py:25-59` 的 `SECTOR_COLORS` 是 32 色可变 list；
`main_window.py:116` 每次构造 MainWindow 时 `random.shuffle(SECTOR_COLORS)`
原地打乱模块级 list；`wheel.py:157` 读取**同一个模块级对象**取色。也就是说
「打乱生效」依赖共享可变状态这一隐式通道。另注意 `wheel.py:215` 的对比色取
`sector_colors[num - 1 - i]`，与取色同源，注入 palette 后两者自动保持一致。

因此直接 `list → tuple` 会让 shuffle 静默失效（改 tuple 后原地修改会抛
AttributeError，反而暴露；但若只改类型不改注入方式，行为已变）。正确迁移：

- `wheel.py`：`SECTOR_COLORS` 改 tuple；新增 `setPalette(colors)`，同时失效
  `cached_pixmap/cached_size/cached_dpr`（**不清** `_font_size_cache`——字号
  与颜色无关）；renderCache 取色改 `self._palette`，默认值即模块级
  `SECTOR_COLORS`。
- `main_window.py`：116 行改为生成副本 `palette = list(SECTOR_COLORS)` 后
  shuffle 并暂存；在 601 行 `self.wheel = WheelWidget()` 之后注入
  `self.wheel.setPalette(palette)`。

净效果：仍是每次启动随机取色顺序、32 色调色板内容不变——行为等价，且未来任何
`SECTOR_COLORS.append` 都会立刻炸响而不是污染全局。

保功能手段：新增测试断言「注入的 palette 与模块级调色板元素多重集相等」与
「renderCache 使用的底色序列 = 注入序列」（后者可 monkeypatch `setPalette`
记录传入值，再用 spy 包 `_fit_font_size` 同款手法核对 renderCache 实际使用
的序列），shuffle 随机性本身用 `random.Random(seed)` 打桩后逐位对照。

### R3. 调试 print 三处（D4 之二）

三处的位置与语义（本轮已读全上下文）：`main_window.py:101` 数据文件迁移提示、
`:424` 加载时的 storage 警告（文件损坏被隔离等）、`:481` 保存失败提示。GUI 程序的
stdout 用户通常看不到，但三处承载的都是**用户应当知晓的信息**，直接删除是功能
回退。方案：统一走一个 `_notify(title, text, level)` 助手，内部用
`QTimer.singleShot(0, ...)` 延迟到事件循环再弹 `QMessageBox`（迁移/损坏用
warning，保存失败用 warning）。延迟的理由：101 行在 `__init__` 里，窗口尚未
show，同步 `exec()` 会在构造期间开嵌套事件循环。

已知风险与对策：offscreen 冒烟与 pytest 都没有人点对话框，通知一旦被误触发就会
挂死。当前两条路径都不产生通知（测试全部 monkeypatch 了 `resolve_data_path`，
relocated 为 None；冒烟的沙箱 seed 数据合法）。为防未来回归，批次 3 同步在
`tests/gui/conftest.py`（新文件）加 autouse fixture，把 QMessageBox 的三个静态
方法替换为记录器——测试套件从此对通知免疫。验收标准里写明：四项验证链中冒烟
两项若挂起超过 60 秒，即视为通知路径被误触发，批次失败。

另：`main_window.py:766` 的注释死代码 `# self.applyGlobalFont(...)` 与 610-612
行重复的 `setAlignment`/`setFont`（同一对语句连写两遍）一并删除，属零风险清理，
放入批次 3。

### R4. main_window 拆分（D2）

事实：1071 行，`initUI`（484-769）单方法约 285 行；`ui/panels/` 与
`ui/save_scheduler.py` 均不存在，500ms 去抖内联于 main_window.py:92-96、
444-453。

本轮读完 initUI 全部控件，两个已核实的风险边界：

- **`applyUIFont` 的遍历**（379-393）用 `self.findChildren(QWidget)` 递归设置
  字体并按 `widget is self.wheel` 跳过转盘。`findChildren` 递归覆盖面板后代
  控件，拆 panels **不破坏**字体应用；但 `wheel` 必须仍是 MainWindow 的直属
  属性，不能随拆分移入面板。
- **verify_gui 的属性契约**：脚本直接访问 `window.group_combo`、
  `window.list_widget`、`window.result_label`、`window.batch_spinbox`、
  `window.btn_stop_batch`、`window.batch_remaining`、`window.groups`、
  `window.current_group_index`、`window.startBatchSpin`、`window.flushSave`、
  `window.data_file`、`window.loadData`、`window.wheel`、`window.theme_combo`。
  拆分后这些名字必须仍从 window 可达（属性转发或保留直属），否则冒烟先红。
  批次 1 会把这个契约写成快照测试固定住。

**新发现的硬约束**：`list_splitter`（588-594）的三个窗格是 `list_widget`、
`bottom_widget`（项目编辑按钮组 + drawn 列表上方的按钮）、`drawn_list_widget`——
它们分属「项目编辑」与「抽出项目」两个关注点。若按关注点切面板并要求每个面板
自封装布局，splitter 就必被拆散。因此采用**方案 b：行为搬进面板，布局与组装
留在 MainWindow**。具体规则：

1. 三个面板类各负责「创建自己的控件 + 连接自己的信号 + 实现自己的数据操作」，
   通过构造参数拿到窗口引用以调用跨切面动作（`saveData()`、
   `updateWheelFromCurrentGroup()` 等，签名在批次 4 实施时定）。
2. MainWindow 保留全部布局代码（left_panel、list_splitter、right 区、
   bottom_row、self.splitter）与几何/持久化/编排逻辑；面板把自己创建的控件
   暴露为公有属性，由 MainWindow 组装。
3. `self.left_panel` 容器属性必须保留——`onSpinStarted`（961）与
   `_finishBatch`（1059-1062）靠整块启用/禁用它实现「旋转时锁定编辑」。
4. verify_gui 契约属性在 MainWindow 里以赋值转发保持可达
   （`self.group_combo = group_panel.group_combo`，同一对象，零行为变化）。
5. `wheel` 与 `list_splitter`、`splitter` 保持直属。

控件与方法归属（按 initUI 实际构建顺序清点）：

| 面板 | 控件 | 方法 |
| --- | --- | --- |
| GroupPanel | group_combo、+/- 两个按钮、重命名分组按钮 | updateGroupCombo、onGroupChanged、addGroup、deleteGroup、renameGroup |
| ItemsPanel | list_widget、添加/删除/编辑、批量导入、随机打乱、编辑所有、清空 | addItem、batchAddItems、deleteItem、editItem、editAllItems、shuffleItems、clearItems、onItemsReordered（含 eventFilter 的 Drop 监听安装） |
| DrawnPanel | drawn_list_widget、返回/删除按钮 | updateDrawnList、updateDrawnButtonsState、extractDrawnItem、returnDrawnItem、deleteDrawnItem、editDrawnItem |
| SpinPanel（右侧卡片） | result_label、btn_extract、btn_spin、batch_frame 全家 | onSpinStarted、onSpinFinished、startBatchSpin、stopBatchSpin、_autoExtract、_finishBatch、_updateBatchButtonState、_onBatchCountChanged |
| SettingsPanel | ui/wheel 字体两个 QFontComboBox + 两个 QSpinBox、theme_combo、shadow_checkbox | applyUIFont、applyWheelFont、onUIFontChanged/Size、onWheelFontChanged/Size、onThemeChanged、onShadowToggled、_applyTheme、_isSystemDark、_onSystemThemeChanged、_initLowerAreaColors |
| MainWindow（留） | 全部布局与 splitter、wheel、几何恢复 | __init__、loadData、saveData/flushSave、updateWheelFromCurrentGroup、closeEvent、showEvent |

注：`btn_extract` 物理上在右侧单次抽取卡片里，但语义属于「抽出项目」；归属
SpinPanel 即可（updateExtractButtonState 随之留在 MainWindow 或移入
SpinPanel，实施时以引用最少跨面板为准）。

拆分顺序（降低单步风险，每步一提交、提交后跑四项验证链）：

- 4a：抽 `ui/save_scheduler.py`。去抖原样搬走（92-96 的定时器装配 +
  444-453 的调度/落盘），MainWindow 持一个 scheduler 实例，`saveData()` /
  `flushSave()` 保留同名方法转调（verify_gui:168 与 tests/gui/
  test_save_debounce.py 直接调用这两个名字，签名不能变）。
- 4b：按 Group → Items → Drawn → Settings 顺序拆（SpinPanel 与批量状态机
  耦合最深，放最后；如行数已达标也可不做 SpinPanel，在提交信息里说明）。
- 4c：`wheel.py` 409 行同样越过 400 行线（D2）。将 `SECTOR_COLORS` 与取色
  辅助迁入 `ui/palette.py`（与 R2 的 setPalette 落地衔接），paintEvent 的
  中心装饰与指针绘制（358-395）收成辅助方法，目标 ≤ 400 行。

验收：`wc -l src/luckywheel/ui/main_window.py` ≤ 400；wheel.py ≤ 400；
四项验证链全绿；批次 1 的契约快照测试不修改即通过。

### R5. renderCache 性能（D6）

本轮先用 cProfile 拿到 73ms 的去向，再用微基准把成本逐项隔离，结论与第一版
的候选猜测**不同**：瓶颈既不是字号测量也不是路径构建 API，而是**逐个扇区
描边**。

cProfile（n=200，预热后 5 次 renderCache，总 0.354s ≈ 71ms/次）：

    drawPath          1000 calls  tottime 0.294s  (83%)
    drawText          2000 calls  tottime 0.023s  (6.5%)
    renderCache          5 calls  tottime 0.019s
    horizontalAdvance  1000 calls  tottime 0.003s  (字号缓存已生效)
    contrast_text_color 1000 calls tottime 0.003s
    arcTo/moveTo       各 0.001s            (路径构建开销可忽略)

微基准（n=200、side=900、抗锯齿开、5 次均值）进一步隔离：

    A 现状：每扇区 path + drawPath + 2px 白描边    61.4 ms
    B drawPie + 2px 白描边                         61.9 ms  ← 与 A 等价，无收益
    C path + drawPath + NoPen（只填充）            16.6 ms
    D drawPie + NoPen                              17.2 ms
    F 只填充 + N+1 条半径线合并单路径描一次         22.3 ms
    外圆单独 drawEllipse 描边                       0.3 ms

即：2px 白描边占约 45ms（73%），填充约 16.6ms。据此设计的目标策略 J——
**填充全程 NoPen 一次遍历；N+1 条半径分隔线合并为单一路径描一次；外圆单独
drawEllipse**——实测：

    n=200：62.1 ms → 19.8 ms（3.1×，达到 <30ms 验收线）
    n=41 ：13.5 ms →  4.5 ms
    n=8  ： 1.4 ms →  0.9 ms

视觉等价性论证：现状每个扇区描自己的完整轮廓（两条半径边 + 一段弧），相邻扇区
共享的半径边被描两遍、弧段首尾相接恰铺满整圆。新策略把每条半径边描一遍、外圆
描一遍，覆盖的像素集合相同（白色 2px、相同抗锯齿）。唯一理论差异是共享边由
「描两遍」变「描一遍」时，抗锯齿边缘像素的 coverage 累积略有不同（预计个位数
像素、通道差 ≤ 8）。这不构成功能变化，但必须用测量说话，不能凭感觉。

**实测发现的陷阱（实施时必须避开）**：把半径线与外圆（`addEllipse`）放进**同一
个** QPainterPath 一次 drawPath，耗时从 22ms 恶化到 345ms（5.6×，比现状还慢
5 倍）。外圆必须单独一次 drawEllipse/drawPath。原因未深究（疑似多子路径合判
时栅格化走慢路径），但现象稳定复现，作为实现约束记录。

配套改动：

1. **80ms resize 去抖 + 旧 pixmap 拉伸兜底**（v1 规划原文方案）。注意这与现有
   测试冲突：`tests/characterization/test_render_cache.py` 的
   TestCacheGuardOnResize 三条用例断言「resize 立即失效缓存」。去抖后语义变为
   「resize 标记 pending 并起 80ms 单次定时器，到点才失效重建；窗口内
   paintEvent 用旧 pixmap 拉伸绘制」。批次 5 必须同步改写这三条用例（语义变化
   先写测试再改实现），并新增打桩用例：「窗口内连续 resize 不触发
   renderCache；停止 80ms 后恰好重建一次」。重建窗口内拉伸旧图会短暂模糊，
   属可接受折代（规划原文即此方案），写入 CHANGELOG。
2. **批量抽取的隐性成本**：每轮 `_autoExtract` → `updateWheelFromCurrentGroup`
   → `wheel.setItems` → 缓存失效 → 下一帧 paintEvent 同步重建（n=200 时现状
   约 62ms/轮）。优化后约 20ms/轮，这也是优化在交互路径上的主要收益。
3. 像素级回归测试：对固定 items/尺寸渲染 cached_pixmap，采样断言——扇区内部
   像素色 = 注入 palette 对应色、半径边附近存在白色像素、外圆存在白色像素、
   与优化前基线图相比 >99.9% 像素相同且最大通道差 ≤ 8。基线图在批次 5 第一个
   提交里先用现状实现生成并入库 tests/data/（PNG 或哈希），后续实现改动都
   对照它。

### R6. CI 门禁与二进制守卫（D7）

二进制守卫是纯增量步骤，本地 `git ls-files` 已验证为空，加上即绿，零功能风险。
实现注意：ci.yml 跑在 windows-latest，`run:` 默认 shell 是 pwsh，守卫步骤须
显式 `shell: bash`（GitHub Windows runner 自带 Git Bash）。覆盖率阈值不能盲调：
本地无 pytest-cov/coverage，拿不到实测值。方案：先把门禁步骤改为「打印覆盖率、
不设 fail-under」，由 CI 实跑一轮拿到 core 与整体真实数字后，再按「core ≥ 90%、
整体 ≥ 60%」的规划线收紧。YAML 语法可本地用 `pre-commit run check-yaml --all`
验证。另：ci.yml 目前只有 `--entry main` 冒烟，缺 `--entry module`（与本文
验证链第四项不一致），批次 6 一并补上，零风险。

### R7. git 历史收尾（D1，不可逆）

未执行三项及其依赖关系（关键）：**gc 瘦身必须在 force push 之后**。本地
`refs/remotes/origin/main` 仍指向重写前历史，旧对象经该 ref 可达，
`git gc --prune=now` 不会回收它们——先 gc 再 push 等于白做。正确次序：

1. 确认 GitHub 端 4 个 Release（v1.0.1–v1.0.4）与 tag 的关联状态，以及旧
   exe 资产是否仍在各 Release 页可下载（v2 P6 要求；本机无 gh，需在有
   gh 的环境或网页人工确认，这是 push 的前置闸门）；
2. `git push --force --all && git push --force --tags`（此步使所有本地
   clone/fork 失效，是计划中唯一不可逆操作，执行前需用户明确确认）；
3. 验证：全新 `git clone` 后 `python -m luckywheel` 可启动、
   `git count-objects -vH` 在 clone 中为 KB 量级、GitHub 上 4 个 Release
   仍显示资产；
4. `git reflog expire --expire=now --all && git gc --prune=now --aggressive`，
   再以 `git count-objects -vH` 验证本地 .git 降到 2MB 量级；
5. 删除误建的 `LuckyWheel` tag（本地 + 远程 `git push origin :LuckyWheel`）。
   注意 `v1.0.1` 与 `v1.0.4` 现同指 `1201750`，删 tag 前确认这不是重写引入
   的意外。

---

## 第二部分：Plan——批次、改动与验证

> 每批的「完成定义」= 四项验证链全绿 + CHANGELOG/提交信息记录行为变化（若有）。
> 批次 7 之前的所有批次互不依赖 git 历史状态，可随时中止。
> 本文档被 `.gitignore:34`（`docs/`）覆盖，属本地规划文档，不随批次提交。

### 批次 1：补网（零功能改动）

- 新增 `tests/statistical/test_planned_spin.py`。**参数按 σ 数学重算**（第一版
  的「20 万次 + count=41 + <1.5%」实测必红，证据：seed 20260921、count=41、
  n=200k 时最大相对偏差 3.997%，而该情形 σ=1.414%，1.5% 仅 1.06σ——必挂）。
  修正设计：固定种子（CI 完全确定性，无 flaky）+ 每 count 独立样本量
  n = 40000·(c−1)，使 σ 恒为 0.5%、1.5% 恰为 3σ。已本地预跑通过：

      count=4  n=120,000   seed=20260925  实测 0.623%
      count=8  n=280,000   seed=20260929  实测 0.906%
      count=10 n=360,000   seed=20260931  实测 1.464%
      count=41 n=1,600,000 seed=20260962  实测 1.126%
      合计 4.0s（plan_spin 实测 1.65µs/次）

  docstring 记录公式 σ=sqrt((c−1)/n) 与上述实测值；与 test_fairness.py 的旧
  实现基线（偏差 10~12%）同目录对照。
- `tests/unit/test_spin.py:50` 不变式 count 由 `[1,2,3,4,8,10,41]` 扩为
  1..60 逐值，每 count 100 个种子（实测 6000 次 plan+sector_at 共 0.01s）。
- 新增 `tests/characterization/test_window_contract.py`：钉住 R4 列出的
  verify_gui 属性契约（构造后逐个 assert hasattr 且类型正确）+
  `applyUIFont` 后关键控件字体一致 + `_applyTheme` 后采样控件调色板——
  拆面板期间的护网。
- 验证链 + `pytest --collect-only -q` 记录测试总数变化（基线 250）。

### 批次 2：入口修复（R1）

- `app.py`：`create_window` 改为 `from luckywheel.ui.main_window import
  MainWindow`，删 19 行过期注释。
- `main.py`：`__main__` 段收缩为转调 `luckywheel.app:main`（与 app.py:35-38
  逐行等价的序列合并），**保留四个 re-export**（13-14 行不动）。
- 新增验证（人工步骤，写入提交信息）：临时目录下
  `cd /tmp && QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -c "...create_window..."`
  复现原 ImportError 场景，修复后应打印 `create_window OK: MainWindow`
  （修复前已实测复现 `ModuleNotFoundError: No module named 'main'`）。
- 双入口 GUI 冒烟重点看「启动耗时」行无异常。

### 批次 3：调色板与死代码（R2、R3）

- `wheel.py`：`SECTOR_COLORS` 改 tuple；新增 `setPalette`；renderCache 用
  `self._palette`（默认 SECTOR_COLORS）。
- `main_window.py`：116 行改为副本 shuffle 后暂存，601 行 wheel 创建后注入；
  101/424/481 的 print 改 `_notify`（singleShot 延迟 + QMessageBox）；
  删 766 行注释死代码与 610-612 重复语句。
- 新增 `tests/gui/conftest.py` autouse fixture：QMessageBox 三静态方法替换为
  记录器，测试套件对通知免疫。
- 新增 palette 多重集与序列测试（见 R2）。
- 验收补充：冒烟两项若挂起 >60s 即视为通知误触发，批次失败。

### 批次 4：main_window 拆分（R4）

- 严格按 R4 的顺序与规则：4a save_scheduler → 4b 四面板（每面板一提交，
  Settings 最后）→ 4c wheel.py 瘦身（palette 模块 + 绘制辅助方法）。
- 每提交后跑四项验证链；`wheel`、`left_panel`、`list_splitter`、`splitter`
  与 verify_gui 契约属性保持直属/转发可达。
- 验收：`wc -l src/luckywheel/ui/main_window.py` ≤ 400；wheel.py ≤ 400；
  批次 1 的契约快照测试不修改即通过。

### 批次 5：renderCache 性能（R5）

- 第一个提交：先落像素级回归基线（现状实现渲染固定用例存
  tests/data/），再改实现。
- 实现按 R5 的策略 J：填充 NoPen 一次遍历 → N+1 条半径线单路径描一次 →
  外圆单独 drawEllipse。**禁止**把外圆与半径线放进同一路径（345ms 陷阱）。
- 同步改写 TestCacheGuardOnResize 三条用例语义并新增去抖打桩用例
  （「窗口内 resize 不重建、停止 80ms 后重建一次、窗口内用旧图拉伸」）。
- 验收：n=8/41/200 的 benchmark 前后对照表写入提交信息（本地实测预期
  19.8/4.5/0.9ms 量级），n=200 < 30ms；像素回归 >99.9% 相同、最大通道差 ≤ 8。

### 批次 6：CI（R6）

- ci.yml 增二进制守卫步骤（`shell: bash`，`git ls-files | grep -E
  '\.(exe|ttf)$'` 命中即败）；补 `--entry module` 冒烟步骤。
- 覆盖率步骤暂改为只打印（去掉 --cov-fail-under，增整体 --cov 报告），待 CI
  实跑一轮后按规划线收紧（该调整可能落在本计划之后的跟进批）。
- 本地用 `pre-commit run check-yaml --all` 验 YAML 语法；四项验证链照跑
  （本地无 pytest-cov，覆盖率步骤的实跑验证只能由 CI 完成，写入提交信息）。

### 批次 7：git 历史收尾（R7，需用户确认后执行）

- 严格按 R7 的 1→5 次序；步骤 2（force push）执行前单独请求确认；
  任一步验证不过即停并回滚到上一状态（push 前本地状态可经 origin 恢复）。

### Backlog（本次不做）

- v2 P3 条目稳定 id（`Entry(id, text)`，数据模型升级，影响 wheel_data.json
  序列化格式，值得单独立项）；
- v1 目标结构图更新（packaging/ → scripts/）、tests/gui 命名对齐规划图；
- `scripts/verify_gui.py` 的文档来历补注；
- wheel.py:215 对比色取 `sector_colors[num - 1 - i]` 的反直觉索引（现行正确，
  但有注释保护即可，不值得改代码）。
