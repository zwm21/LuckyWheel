# LuckyWheel 重构：Research + Plan

调研日期：2026-09-20 ｜ 基线 commit：`3b51038` ｜ 代码规模：`main.py` 1515 行，单文件

---

## 第一部分：Research

### 1.1 现状的几个硬数字

仓库 `.git` 目录 289MB，而源码只有 67KB。原因是 `dist/LuckyWheel.exe` 被提交了 8 次，历史中留下 8 个约 37–38MB 的 blob，合计约 300MB。仓库是公开的，`origin` 为 `github.com/zwm21/LuckyWheel`，有 `v1.0.1`~`v1.0.4` 加一个误建的 `LuckyWheel` 共 5 个 tag。

65 次提交，从 commit message 看大量是「修复浅色主题…」「再修字体大小bug」「再修控件颜色初始化」这类连续返工，说明主题与字号这两块缺少可复现的验证手段，只能靠肉眼试错。这正是测试目录要优先覆盖的区域。

当前工作区的 `wheel_data.json` 里有 41 个条目，其中只有 17 个唯一值（`"1"` 出现 15 次，`"54"` 4 次，`"41"` 4 次）。这个事实后面会用到。

### 1.2 算法层面：确认存在的缺陷

**（A）抽奖结果不均匀 —— 这是最严重的问题。**

`startSpin` 取初速度 `600 + secrets.randbelow(1_500_000)/1000.0`，即 v ∈ [600, 2100)。`updateRotation` 每 30ms 以 `friction=0.98` 衰减，速度降到 5 以下停止。总转角近似为

```
Δ ≈ Σ v·0.98^k·0.03 = 1.5·v·(1 − 0.98ⁿ) ≈ 1.5v − 7.5
```

代入速度区间得 Δ ∈ [892.5, 3142.5)，跨度 2250° = **6.25 圈**。非整数圈意味着：四分之一的圆弧被覆盖 7 次，其余被覆盖 6 次，落点概率相差 7/6 ≈ 16.7%。

20 万次模拟实测（起始角固定为 0）：

| 扇区数 | 最低偏差 | 最高偏差 |
|---|---|---|
| 4 | −4.0% | **+10.5%** |
| 8 | −4.2% | **+11.9%** |
| 10 | −5.1% | **+11.4%** |

这个偏差在什么情况下生效，是关键：`setItems()` 会把 `self.rotation` 重置为 0，而 `updateWheelFromCurrentGroup()` 每次都调 `setItems()`。批量抽取的每一轮（`onSpinFinished` → `_autoExtract` → `updateWheelFromCurrentGroup`）、以及单次抽取后每按一次「抽出」，都会把起始角归零。**所以固定起点才是常见路径，偏差是持续生效的，而不是偶发。** 作为对照，若起始角自然累积（连续点「开始旋转」而不抽出），同样 20 万次模拟偏差被压到 ±1%。

**（B）抽出操作按文本匹配而非按索引。**

`WheelWidget.spinFinished` 发出的是 `(sector_index, text)`，但 `onSpinFinished(self, index, text)` 里 `index` 完全没被使用。`extractDrawnItem` 更进一步——它从界面标签里反解结果：

```python
if result.startswith("🎉 恭喜中奖: "):
    item_text = result.split("🎉 恭喜中奖: ", 1)[1]
```

然后 `group['items'].remove(item_text)` 删除**第一个**匹配项。结合 1.1 里「41 项中 15 个 `"1"`」的真实数据：指针停在第 30 个 `"1"` 上，被删掉的却是索引 3 的那个。对纯字符串而言结果多重集不变，所以用户看不出来，但消失的扇区不是指针指的那个，视觉上是错的；一旦将来给条目加权重、颜色或 ID，就变成真正的数据错误。`_autoExtract` 有同样的问题。

同时，把显示文案当数据解析本身就是脆弱设计：改一次提示语或做国际化，抽出功能就静默失效。

**（C）字号求解是线性递减。**

`renderCache` 对每个条目从 `radius*0.18` 开始，每次减 1 像素重新测量，直到塞得下。实测 41 个条目、900×900 窗口下共 **2409 次** `fontMetrics` 调用；二分查找只需约 287 次，**8.4 倍**差距。并且 41 项里只有 17 个唯一文本，相同文本重复求解了 2.4 倍。

**（D）缓存失效过于激进 + 未适配 HiDPI。**

`resizeEvent` 无条件把 `cached_pixmap` 和 `cached_size` 置空，于是 `paintEvent` 里 `self.cached_size != side` 这个守卫永远不会起作用——任何 resize 都触发全量重绘。实测 `renderCache` 耗时：n=8 为 6.7ms，n=41 为 23.2ms，n=200 为 **112ms**。拖拽窗口边缘时每秒几十个 resize 事件，n 大时直接卡死。

另外 `QPixmap(side, side)` 用的是逻辑像素，没有按 `devicePixelRatio` 放大，高 DPI 屏上转盘文字先低分辨率光栅化再放大，是糊的。

**（E）持久化不是原子写，且损坏即丢数据。**

`saveData` 直接 `open(..., 'w')` 覆写。写入过程中崩溃/断电 → 文件截断。而 `loadData` 捕获 `json.JSONDecodeError` 后**静默重置为默认值并立刻 `saveData()` 覆盖**——用户所有分组和抽签数据无声蒸发，连残骸都不留。

`saveData` 在代码里有 26 个调用点，包括字号 spinbox 的每一次 `valueChanged`（按住上箭头就是每格一次全量落盘）和批量抽取的每一轮。没有任何去抖。

**（F）JSON 输入零校验。**

`loadData` 只保证 `drawn_items` 存在。如果手工编辑的文件里某个 group 缺 `items` 键，`updateWheelFromCurrentGroup` 立刻 `KeyError` 崩溃；`groups` 是 dict 而非 list、`items` 里混入数字，同样会在运行时炸开。没有 schema 版本字段，将来迁移无从下手。

**（G）`window_geometry` 恢复不做屏幕边界校验。**

只检查了长度是否为 4。上次在副屏使用、这次副屏未接，窗口会恢复到屏幕外，用户无法用鼠标找回。

### 1.3 需要澄清的两点（避免「修」出新 bug）

**`determineResult` 是正确的，不要动它的公式。** 我一度怀疑它算反了：Qt 的 `QPainterPath.arcTo` 角度是逆时针（屏幕坐标下 y 向下），而文字定位用的 `(cos θ, sin θ)` 是顺时针，两者镜像。离屏渲染实测确认，文字 `A_i` 确实画在 `SECTOR_COLORS[n-1-i]` 的扇区上。但因为扇区边界集合 `{k·span mod 360}` 在镜像下自映射，每段文字仍精确居中于某个扇区，而且 `paintEvent` 的旋转与 `determineResult` 的反算用的是同一套屏幕角度，所以**指针下显示的文字与 `spinFinished` 报出的条目始终一致**（在 0°/30°/100°/217.3°/359° 逐一验证通过，`rot=0` 那次差异是恰好落在扇区边界上的平局，不是错误）。

**颜色配对反转目前不可见，但是个定时炸弹。** `renderCache` 里判断文字用黑还是白，取的是 `SECTOR_COLORS[i]`，而文字实际画在第 `n-1-i` 个扇区上——取错了底色。之所以没暴露，是因为阈值写的是 `lightness() > 50`，而调色板 32 个颜色的 lightness 范围是 91–229，**没有一个 ≤ 50**，所以永远走黑色分支。阈值本该是 ~128 或用相对亮度。谁哪天往调色板里加一个深色，文字就会在错误的扇区上变白。

### 1.4 结构与卫生

`main.py` 里 `MainWindow` 一个类承担了：UI 构建（`initUI` 单方法 320 行）、主题切换、JSON 持久化、分组 CRUD、条目 CRUD、批量抽取状态机、窗口几何管理。`WheelWidget` 则同时负责绘制、几何计算和旋转物理。没有任何一层能脱离 `QApplication` 单独测试。

手写的 `SplitterHandle`（53 行）加 `MainWindow.resizeEvent` 的高度钳制逻辑，实现了 `QSplitter` 本来就提供的功能，而且算错了：

```python
max_list = max(800, panel_h - 0)              # 注释说「面板高 − 200」，代码写的是 − 0
used_top = self.list_widget.height() + 6 - 180 # 符号可疑
max_drawn = max(600, panel_h - used_top - 40)
```

`max(800, ...)` 意味着上限永远不低于 800，钳制形同虚设。

死代码清单：`QPropertyAnimation`、`QEasingCurve`、`QAction`、`QFontMetrics` 四个导入从未使用；`self.font_family` 属性除了 `print("使用字体:", ...)` 这行调试输出外无人读取（真正生效的是 `ui_font_family` / `wheel_font_family`）；`determineResult` 里 `if sector_index >= num` 恒假；`paintEvent` 里 `pointer_tip` 算了两遍，第一遍结果直接丢弃；`random.shuffle(SECTOR_COLORS)` 原地打乱模块级常量。

`.gitignore` 只有 4 行，而且**把 `.gitignore` 自己也忽略了**（所以它其实没被 git 跟踪）。没有 `pyproject.toml`、没有 LICENSE、没有 CI、没有 lint 配置、没有依赖版本约束。`build_exe.bat` 硬编码 `--add-data "HYWenHei-65W.ttf;."`，而该字体被 gitignore 排除，新克隆者执行打包必然失败。

---

## 第二部分：Plan

已确认的四项决策：**重写 git 历史**、**改为先定结果再播动画**、**字体设为可选并降级**、**完整 src 包分层**。

### 2.0 目标结构

```
LuckyWheel/
├── pyproject.toml                 # 依赖、ruff、pytest、构建元数据
├── README.md  LICENSE  CHANGELOG.md
├── .gitignore  .gitattributes  .pre-commit-config.yaml
├── .github/workflows/{ci.yml,release.yml}
├── assets/fonts/README.md         # 说明自备字体放这里，目录本身不含字体
├── packaging/{luckywheel.spec,build.py}
├── docs/REFACTOR_PLAN.md
├── src/luckywheel/
│   ├── __init__.py  __main__.py  app.py
│   ├── core/                      # 零 Qt 依赖，纯 Python
│   │   ├── models.py              # Group / AppState dataclass
│   │   ├── spin.py                # 抽奖算法：选中者 + 目标角度
│   │   ├── layout.py              # 扇区几何 + 字号求解（测量函数注入）
│   │   ├── storage.py             # 原子写、schema 版本、迁移、校验
│   │   └── paths.py               # 数据文件与资源定位
│   └── ui/
│       ├── main_window.py  wheel_widget.py  dialogs.py
│       ├── theme.py  fonts.py  save_scheduler.py
│       └── panels/{group_panel.py,items_panel.py,settings_panel.py}
└── tests/
    ├── conftest.py
    ├── unit/{test_spin.py,test_layout.py,test_storage.py,test_models.py}
    ├── gui/{test_wheel_widget.py,test_main_window.py,test_theme.py}
    ├── statistical/test_fairness.py
    └── data/{valid_v2.json,legacy_v1.json,corrupt.json,hostile_types.json}
```

`core/` 不 import 任何 Qt，是整个方案的支点——公平性、迁移、字号求解都能用普通 pytest 秒级验证，不需要 `QApplication`。字号求解确实需要字体测量，做法是把测量能力作为参数注入：

```python
def fit_font_size(text, max_w, max_h, measure, *, start_px, min_px=8) -> int
```

`measure(text, px) -> (w, h)` 在生产代码里由 `QFontMetrics` 提供，测试里用确定性的假实现（如等宽假设），二分逻辑本身就完全可测了。

### 2.1 阶段 0：安全网（先做，约 2 小时）

动任何代码之前先建立可回退的基线。用 `git clone --mirror` 把当前仓库完整备份到工作区之外；把 `v1.0.1`~`v1.0.4` 对应的 4 个历史 exe 从 GitHub 下载归档到本地（历史重写后这些二进制会从仓库消失，需要补挂到 Release 才能让旧版本继续可下载）。

然后建 `pyproject.toml`（PyQt6 约束、pytest、pytest-qt、pytest-cov、ruff）、修正 `.gitignore`（当前把自己也忽略了，这条必须去掉；补 `dist/`、`build/`、`*.spec`、`__pycache__/`、`.venv/`、`wheel_data.json`）、建 `tests/` 骨架和 `conftest.py`（会话级 `qapp` fixture，`QT_QPA_PLATFORM=offscreen`）。

最关键的一步是**先写特征测试（characterization tests）**，把现有行为钉住：加载当前真实的 `wheel_data.json` 应得到 41 项 / 6 个已抽出项；给定固定 rotation，`determineResult` 应返回指针下的那一项；`renderCache` 在 n=8 时不抛异常且产出非空 pixmap。这些测试描述的是**现状**，用来保证后续重构不改变应该保持不变的行为。

验收：`pytest` 全绿，`ruff check` 通过。

### 2.2 阶段 1：仓库卫生与历史重写

先把二进制分发切到 GitHub Release：写 `.github/workflows/release.yml`，打 tag 时在 `windows-latest` 上跑 PyInstaller 并上传 exe 为 Release 资产。确认这条链路跑通、且阶段 0 归档的 4 个旧 exe 已补挂到对应 Release 之后，再动历史。

历史重写用 `git filter-repo --path dist --invert-paths`，清掉 `dist/` 的全部历史记录，`.git` 预期从 289MB 降到 2MB 量级。之后 `git push --force --all && git push --force --tags`，并顺手删掉误建的 `LuckyWheel` tag。**这一步不可逆，且会让所有已有 clone/fork 失效**，务必在备份镜像验证通过后再执行；执行后需要检查 GitHub 上 4 个 Release 是否仍正确关联到重写后的同名 tag。

同期补上 LICENSE、CHANGELOG、`.gitattributes`（统一换行符，标记二进制），以及 `.pre-commit-config.yaml`：ruff + ruff-format + check-json + end-of-file-fixer，再加一条本地 hook 直接拒绝任何 `dist/` 下的暂存文件，防止重蹈覆辙。CI 用 `ci.yml` 在 Windows + Python 3.10/3.12/3.13 上跑 lint 与 offscreen 测试。

字体按「可选并降级」处理：`scripts/build_exe.py` 检测 `assets/fonts/HYWenHei-65W.ttf` 是否存在，存在才追加 `--add-data`，不存在就打印提示继续打包；运行时 `fonts.py` 沿用已有的回退逻辑（找不到内嵌字体则用 Microsoft YaHei）。README 说明字体需自备及其版权归属。仓库任何时候都不包含该文件。

验收：`git count-objects -vH` 显示体积大幅下降；全新 `git clone` 后无需额外文件即可 `python -m luckywheel` 运行、`python scripts/build_exe.py` 成功打包。

### 2.3 阶段 2：抽离 core 层

把数据模型、存储、抽奖算法、几何计算从 `main.py` 搬进 `src/luckywheel/core/`，此阶段**只搬不改逻辑**（除了下面两个必须同步做的修复），靠阶段 0 的特征测试保证等价。

`storage.py` 有两处必须立刻改：写入改为「同目录临时文件 + `os.replace`」的原子写，并保留一份 `.bak`；读取遇到损坏文件时**改名保留为 `wheel_data.corrupt-<时间戳>.json` 再启用默认值**，绝不静默覆盖。同时引入 `"version": 2` 字段和从无版本号旧格式（即当前真实文件的样子）的迁移路径，以及类型校验——缺 `items` 键、`groups` 不是 list、条目不是字符串，都应被规整或跳过而不是崩溃。

`paths.py` 解决数据文件定位：保持「与 exe 同级」的便携特性，但在该目录不可写时（例如安装到 Program Files）自动回退到 `QStandardPaths.AppDataLocation` 并迁移已有文件。

对应测试：`test_storage.py` 覆盖往返、缺失文件、损坏文件保留原件、v1→v2 迁移、`os.replace` 被打桩抛异常时原文件完好、以及 `hostile_types.json` 里各种错误类型不崩溃。

验收：`core/` 覆盖率 ≥ 90%，且这些测试全部不依赖 `QApplication`。

### 2.4 阶段 3：算法修正

**公平性。** 新的 `core/spin.py` 提供纯函数：

```python
POINTER_ANGLE = 270.0

def sector_at(angle: float, count: int) -> int:
    return int(((POINTER_ANGLE - angle) % 360.0) / (360.0 / count))

def plan_spin(count, start_angle, rng, *, min_turns=4, extra_turns=3) -> SpinPlan:
    winner = rng.randbelow(count)              # 均匀性由此保证
    span = 360.0 / count
    target = (POINTER_ANGLE - (winner + 0.5) * span) % 360.0
    target = (target + jitter_within(span, rng)) % 360.0   # 扇区内抖动，保留自然观感
    delta = (target - start_angle) % 360.0
    return SpinPlan(winner, start_angle, (min_turns + rng.randbelow(extra_turns + 1)) * 360.0 + delta, ...)
```

关键不变式：`sector_at(start_angle + total_rotation, count) == winner`，对 count 从 1 到 60、每个 count 数百个随机种子逐一断言。抖动要保证落点距扇区边界有安全裕量，避免浮点边界歧义。

UI 侧 `WheelWidget` 改用 `QVariantAnimation` + `QEasingCurve.OutCubic`（或自定义摩擦衰减曲线以保持现有手感）把 `rotation` 从起始角推到 `start + total_rotation`，动画结束时直接 `emit spinFinished(plan.winner_index, items[plan.winner_index])`——结果不再是浮点物理的副产品。顺带把 `QPropertyAnimation` / `QEasingCurve` 这两个闲置导入用起来。`statistical/test_fairness.py` 做 20 万次卡方检验，断言最大偏差 < 1.5%（当前是 11.9%）。

**按索引抽出。** `MainWindow` 保存 `last_result_index`，`extractDrawnItem` 与 `_autoExtract` 改为 `group.items.pop(index)`，彻底删掉从 `result_label` 反解文本的那段代码。测试用 `["A", "A", "B"]` 构造，强制结果落在索引 1，断言被移除的是索引 1 而不是索引 0。

**字号二分。** `core/layout.py` 的 `fit_font_size` 用二分替代逐像素递减，并对 `(text, max_w, max_h)` 三元组做结果缓存（真实数据 41 项中 17 个唯一值，命中率 58%）。测试断言二分结果与原线性算法逐一相等——观感必须零变化。

**缓存与 HiDPI。** `resizeEvent` 改为只在 `min(width, height)` 真正变化时失效缓存（这样 `cached_size` 守卫才名副其实）；重建加 ~80ms 去抖，去抖窗口内先拉伸旧 pixmap 顶住，消除 n=200 时每帧 112ms 的卡顿。pixmap 按 `devicePixelRatio` 放大创建并 `setDevicePixelRatio`，修掉高 DPI 模糊。

**落盘去抖。** 新增 `ui/save_scheduler.py`，用 500ms 合并的 `QTimer` 承接全部 26 个保存调用点，`closeEvent` 强制 flush。批量抽取 999 次将从 999 次全量写盘降到个位数。

**顺带清理。** 文字对比色阈值 `> 50` 改为相对亮度判断并取用正确扇区的底色（见 1.3）；`window_geometry` 恢复时用 `QGuiApplication.screens()` 的并集做钳制；删除四个未使用导入、`self.font_family`、调试 `print`、恒假分支、重复的 `pointer_tip` 计算；`SECTOR_COLORS` 改为不可变元组，打乱时生成副本。

验收：`test_fairness.py` 通过；`renderCache` 基准从 112ms/200项 降到目标 30ms 以内；特征测试中「结果与指针下文字一致」仍然通过。

### 2.5 阶段 4：UI 分层

`MainWindow` 按职责拆成 `panels/` 下三个面板控件，`initUI` 那 320 行随之解体。手写的 `SplitterHandle` 整类删除，换成垂直 `QSplitter`，连带删掉 `resizeEvent` 里那段算错的钳制逻辑；`QSplitter.saveState()/restoreState()` 直接替代现有的高度手工持久化。

`theme.py` 把 `_applyTheme` 中两个近乎重复的分支合并成「颜色 token 字典 + 一份 QSS 模板」。这里有一条踩过坑的约束必须保留并写成注释和回归测试：**不要给带滚动条的控件单独设 QSS**，否则会切到 `QStyleSheetStyle` 渲染，导致浅色主题下出现深色滚动条（commit `b34d41d` 修的就是这个）。`test_theme.py` 针对它写回归用例。

GUI 测试用 pytest-qt：无条目时渲染「请添加项目」分支不崩；缓存仅在 `min(w,h)` 变化时重建（打桩计数 `renderCache` 调用次数）；`qtbot.waitSignal` 验证旋转信号携带的 winner 与 `plan_spin` 一致；批量抽取 N 次后 items 减少 N、drawn 增加 N 且无重复；几何恢复被钳制到可用屏幕内。

验收：单文件不超过 400 行；整体覆盖率 ≥ 60%，`core/` ≥ 90%。

### 2.6 阶段 5：收尾

README 重写（新的运行方式 `python -m luckywheel`、测试命令、打包命令、字体说明、公平性说明）；CHANGELOG 补齐；`release.yml` 全链路演练一次；给 CI 加覆盖率门禁。

### 2.7 风险与次序说明

阶段 1 的历史重写必须在备份镜像与 Release 链路都验证通过之后执行，且越早做越好——它会改写所有 commit hash，放在后面做意味着重构期间产生的提交也要一并被改写。这是整个计划里唯一不可逆的操作。

阶段 3 的公平性改动会改变旋转的内部实现，但对用户可见的行为（转几圈、停多久、观感）应当保持接近；如果实际手感变化明显，可以用自定义缓动曲线 `1-(1-t)^k` 拟合原来的摩擦衰减外观，公平性不受影响。

阶段 2 到 4 都建立在阶段 0 的特征测试之上。如果某个阶段中特征测试变红，先判断是重构引入的回归，还是该测试本身钉住的是一个 bug（例如颜色配对反转）——后者应当显式更新测试并在 CHANGELOG 记录行为变更。
