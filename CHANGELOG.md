# 变更日志

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循语义化版本。

## [未发布]

### 新增
- 单次抽取的「停止」按钮（位于「抽出」与「开始旋转」之间）：旋转途中可
  手动中止，转盘停在当前角度不归位，且不产生中奖结果。与不放回批量抽取
  的「停止」互不接管——两者按 `batch_remaining` 区分模式，同一时刻只有
  一个可用。停止后显式清空 `last_result_index`，否则上一轮的中奖下标会
  残留，「抽出」会指向与当前指针无关的项目。
- `python -m luckywheel` 入口（`python main.py` 旧入口保留为兼容 wrapper）。
- `scripts/build_exe.py`：字体可选打包，不再要求仓库内置字体；GitHub Release
  自动构建（`.github/workflows/release.yml`）。
- `tests/`：特征测试、统计检验、offscreen GUI 冒烟（`scripts/verify_gui.py`）。
- CI（`.github/workflows/ci.yml`）：ruff + pytest + GUI 冒烟（Windows，
  Python 3.10/3.12/3.13），覆盖率门禁整体 75%、`core/` 90%。

### 变更
- **抽奖公平性**：旧实现按随机初速度+摩擦衰减停止，总转角跨度 2250°（6.25 圈），
  固定起点路径下扇区相对偏差达 +10~12%。新实现先等概率选中、再把动画演到对应
  位置，落点均匀性不再依赖浮点物理。
- **数据文件版本化**：`wheel_data.json` 增加 `version: 2` 字段；旧格式（无版本号）
  自动迁移，缺失字段按默认值补齐，类型异常项跳过而非崩溃。
- **原子写**：保存改为同目录临时文件 + `os.replace`，并保留 `.bak`；文件损坏时
  改名保留为 `wheel_data.corrupt-<时间戳>.json` 再启用默认值，不再静默覆盖。
- **保存去抖**：500ms 合并高频保存（字号微调、批量抽取每轮、拖拽排序等）。
- **按索引抽出**：抽出/批量抽取从"按文本匹配第一个"改为按指针命中的索引，
  重复条目不再错删；不再从界面标签反解结果文本。
- **文字对比色**：阈值由 `lightness > 50` 改为相对亮度判断，并取文字实际所在
  扇区的底色（此前因 `arcTo` 与文字定位角度方向相反而取错底色，恰因调色板
  全部为亮色而未暴露）。
- **字号自适应**：由逐像素递减改为二分查找，并对重复文本缓存结果（典型数据
  重复率约 42%）。
- **扇区描边批量化**：`renderCache` 的逐个扇区描边（微基准中占总耗时约 73%）
  改为「填充 NoPen 一次遍历 → N+1 条半径线合并为单一路径 → 外圆单独
  `drawEllipse`」。离屏重绘 side=900：n=8/41/200 由 2.9/17.8/70.6ms 降至
  2.3/8.0/26.5ms（字号缓存已预热，与 R5 微基准同法）。图元集合不变，但共享
  半径边由描两遍变描一遍、外圆由 `arcTo` 分段弧变 `drawEllipse`，抗锯齿合成
  结果与旧实现有可测差异（4183 像素、1.10% 字节不同，全部落在描边几何
  2.5px 带状区内，无真实缺陷），像素基线测试随之由「逐字节相同」改为
  「有界且受限」的结构化容忍。
- **转盘缓存**：仅 `min(w, h)` 或 `devicePixelRatio` 变化时失效，resize
  不再无条件重绘；按 `devicePixelRatio` 渲染，修复高 DPI 模糊。
- **resize 去抖**：拖动窗口边缘时 `resizeEvent` 密集到达，每次同步重建缓存在
  项目多时要几十毫秒（n=200 约 26ms）。改为 80ms 单次定时器去抖：窗口内只
  标记待生效边长并（重）起定时器，`paintEvent` 用旧缓存按新旧边长比拉伸兜底，
  停止 80ms 后才失效并按最新边长重建一次。窗口内画面会短暂模糊，是该方案的
  有意折衷。
- **旋转物理**：帧率无关（真实经过时间驱动），`setItems` 不再把旋转角归零。
- **界面结构**：单文件拆分为 `core/`（零 Qt 依赖）+ `ui/`；手写高度拖拽条替换
  为垂直 `QSplitter`；明暗主题合并为颜色 token + 单份 QSS 模板。
- **测试与脚本改为直接从 `luckywheel.*` 导入**：根级 `main.py` 只保留
  `MainWindow` 一个 re-export，供 `--entry main` 冒烟走旧入口。清单越长，
  这个兼容 wrapper 就越像事实上的 API 门面，重排 `ui/` 的模块划分反而要先
  绕过它。
- **列表刷新增量 diff**：批量抽取每轮原先对抽出列表与项目列表
  `clear()+addItems()` 全量重建——41 项每轮重建 41 个条目，并丢掉选中项与
  滚动位置，视觉上整表闪烁。改为只替换变化的那几行；转盘 `setItems` 在内容
  与顺序都未变时直接短路，省掉整次 pixmap 重建与字号重算。
- **测量路径**：字号求解原先每次测量都 `painter.setFont` 改动 pixmap 的
  painter 状态（41 项约 287 次），改走独立的 `QFontMetrics(QFont)`，与绘制
  前的文字预测量共用一条路径。两条路径对同一字体逐点相等由按 dpr 参数化的
  回归测试钉住，像素基线确认输出不变。字号缓存键纳入字体家族，不再依赖
  `setFontFamily`/`setItems` 手动 `clear()`。

### 修复
- 窗口几何恢复时不做屏幕边界校验，副屏未连接时窗口可能位于屏幕外。
- 深色主题下含滚动条控件若单独设 QSS 会切到 `QStyleSheetStyle` 渲染导致颜色
  错误（回归测试固定该约束）。
- **高 DPI 下转盘错乱**：`renderCache` 在已 `setDevicePixelRatio(dpr)` 的
  QPixmap 上又手动 `painter.scale(dpr, dpr)`，与 Qt 自身的 dpr 缩放叠加成
  dpr²，转盘被放大并移出画布。Windows 125%/150%/200% 缩放下必现；dpr=1 时
  1²=1 无差别，故 offscreen 冒烟与仅断言画布尺寸的特征测试都无法暴露。已删除
  手动缩放，特征测试改为按不透明像素 bbox 断言"居中且不触边"（dpr² 下跨度可能
  仍接近期望值，但圆心必然偏移并被画布裁切，故居中断言才是关键）。
- **三处永不失败的断言**：`or True` 短路的扇区颜色比对、拿窗口构造后的配色池
  与自己比的"未被原地改动"、在十几行 wrapper 里找 `QPropertyAnimation` 的死
  代码扫描。修复后逐条做了变异验证（人为引入缺陷确认能翻红）。特征测试不再
  断言 `wheel_data.json`（用户运行时数据、已 gitignore）的具体内容，改对着
  版本控制内的 `tests/data/legacy_v1.json`。
- **CI 覆盖率从未采集 `ui/`**：`--cov=src/luckywheel.ui` 是点号不是斜杠，既非
  路径也非可导入名。修正后按实测值加上门禁（整体 75%、`core/` 90%），二进制
  守卫的后缀集合与 `scripts/precommit_no_binaries.py` 对齐（补 `.otf`）。
- **源码运行永不加载内嵌字体**：`core/paths.py` 的 `parents[2]` 少退一层，
  `find_embedded_font` 从不命中 `assets/fonts/`，源码运行恒回退
  Microsoft YaHei，与打包版不一致（README 承诺的顺序实际未兑现）。修为
  `parents[3]`，`bootstrap.loadEmbeddedFont` 改为委托同一实现，并让
  `parse_state` 的字体家族缺键给 `None` 一路放行到 `loadData` 的回退。
- **损坏数据的兜底缺口**：`load_state` 现把 `RecursionError`、超过大小/条目数
  上限的文件一并按损坏处理（隔离保留为 `.corrupt-<时间戳>.json` 再启用默认值），
  多条告警合并为一次汇总提示而非每项一个弹窗；`save_state` 的备份从
  `os.replace` 改为 `shutil.copy2`，消除"先删旧再写新"两步之间的数据真空；
  `clamp` 为字号、列表高度、批量次数与窗口坐标补绝对上界，越界回落默认值。
- **数据文件编码的两处缺陷**：中文 Windows 记事本默认按 ANSI(GBK) 另存会让
  `read_text("utf-8")` 抛 `UnicodeDecodeError`——它是 `ValueError` 子类而非
  `OSError`，漏捕就穿透 `loadData` 直达 `MainWindow.__init__`，程序起不来；
  反过来，记事本"UTF-8"选项存的是带 BOM 的 UTF-8，而 `json` 不跳过前导
  `﻿`，合法文件被判成损坏并整份隔离搬家。现读取走 `utf-8-sig`，
  非 UTF-8 编码按损坏同等隔离。
- **落盘的换行翻译**：保存走文本模式且未指定 `newline`，Windows 下把
  `json.dumps(indent=2)` 的每个 LF 翻成 CRLF，而 `indent=2` 是一个条目一行
  ——于是"体积检查刚好通过"的数据存回去就越过 8 MiB 上限，下次启动被整份
  隔离，真实数据只剩在 `load_state` 从不读的 `.bak` 里（实测 3,800,386 字节
  的 payload 落盘 4,000,406 字节，膨胀恰为行数）。改为自己 `encode` 后二进制
  落盘。
- **孤立代理字符导致保存永久失败**：数据文件里的 `"\ud800"` 字面量是纯 ASCII
  字节，`json.loads` 照单接受、类型校验认它是 `str`，一路进 `AppState`；写盘时
  `encode("utf-8")` 抛 `UnicodeEncodeError`，不被 `except OSError` 接住，此后
  每次保存都失败、关窗的 `flushSave` 也失败，整场会话的改动无声丢失。现在
  载入边界把无法编码的字符替换为 U+FFFD，写盘侧另把该异常归入 `StorageError`。
- **告警累积峰值无界**：`MAX_WARNINGS` 的封顶只作用于单个 list，而分组告警在
  各自的局部 list 里攒到 1001 条后才盲 `extend`，1000 个分组峰值 100 万条
  字符串（实测 6.04 MiB 的文件 `tracemalloc` 峰值 148.1 MiB）。改为循环内即时
  截断并累计省略数，同一输入峰值降到 9.4 MiB。条目数上限也从"已保留条数"改按
  "已读位置"计——否则一组 140 万个 `null` 里保留数恒为 0，永远触不到上限。
- **只读 `.bak` 上备份静默失效**：`os.replace` 覆盖只读文件在 Windows 抛
  `PermissionError`，而备份失败被整个吞掉（备份不该阻塞主写入），于是用户看到
  保存成功、主文件已更新、`.bak` 停在上一版。备份改走 `mkstemp` + `fsync` +
  `replace`（`shutil.copy2` 会复制源的只读 mode，且中途失败会留下半截 `.bak`
  覆盖掉上一份好备份），并对只读目标去掉只读位后重试一次。
- **类型非法的字体家族击穿内嵌字体回退**：`clamp` 把非字符串的字体家族填成
  `Microsoft YaHei`，`loadData` 的 `state.x or self.x` 回退从此不触发，启动期
  选中的内嵌字体被丢弃且会被自动保存固化。改为一律回落 `None`。
- **frozen 判据不统一**：`program_dir()` 看 `sys.frozen`、`font_candidates()`
  看 `sys._MEIPASS`。PyInstaller 两种模式都设两者，但 cx_Freeze / py2exe 只设
  前者，那里"frozen 但无 `_MEIPASS`"，仓库根候选会从毫无意义的 `parents[3]`
  复活且仍排在 `program_dir()` 之前——字体加载劫持面换个打包器就重新敞开。
  判据收拢为 `is_frozen()`；候选去重键由 `str().lower()` 改 `os.path.normcase`，
  大小写敏感的文件系统上不再折叠掉真正不同的路径。
- **去抖到点的二次重建**：`_onResizeSettled` 只看缓存是否存在、不看边长是否
  已等于当前值，而去抖窗口内 `paintEvent` 可能因 dpr 变化按最终边长重建过，
  于是同一份图建两次。`_invalidate_cache` 也未停表、未清待生效边长，旧值能活
  过后续 resize。dpr 钳位收成一个两侧共用的取值函数（此前 `renderCache` 存
  钳后值而 `paintEvent` 拿原值比较，dpr 取到 0 就每帧全量重建）。
- **批量抽取的轮间停顿里按「停止」会多转一轮**：`QTimer.singleShot(400,
  wheel.startSpin)` 不可取消，`startSpin` 也不看批量状态。界面已显示"批量抽取
  完成"，400ms 后转盘又转一轮、宣布中奖、写上 `last_result_index` 并自动抽走
  一个项目。续转改经查 `batch_remaining` 的入口。
- **拖拽排序后旧中奖结果不失效**：排序不走 `updateWheelFromCurrentGroup`，
  结果标签与 `last_result_index` 都留着，而同一扇区下已换成别的项目——标签仍
  显示旧中奖项，「抽出」按旧下标 pop 的是另一项（宣布 A05 后把第 0 行拖到
  第 5 行，抽出拿走的是 A00）。
- **打包脚本与运行时的字体文件名脱钩**：`find_font()` 取 `assets/fonts/` 下
  第一个 `*.ttf`/`*.otf` 并按原名 `--add-data`，而运行时只认固定名
  `HYWenHei-65W.ttf`；放入别名字体时脚本报告"已内嵌"、运行时静默回退，两边都
  不报错。现优先取那个固定名，取到别名时显式警告；`assets/fonts/README.md`
  承诺的查找顺序也改为与实现一致。

### 移除
- `dist/LuckyWheel.exe` 出版本控制（改由 GitHub Release 分发）。历史重写前
  镜像备份已留存，v1.0.1~v1.0.4 的 exe 补挂至对应 Release。
- 五个从未使用的导入、`self.font_family` 死属性、调试 `print`、恒真/恒假分支、
  重复的指针坐标计算。
- `ui/wheel.py` 里与 `core/layout.py` 重复的字号求解实现与几何魔数。上面
  「字号自适应」一条此前只在 `core/layout.py` 里成立——那个模块生产代码
  从未导入，转盘跑的是自己那份略有分歧的副本（下界固定夹到 8、空文本提前
  返回）。现统一走 `core.layout`，下界改由调用方传入以保住「转盘字号设成
  6 就是 6」，空文本不再特殊处理以与逐像素递减的旧实现逐点相等。
