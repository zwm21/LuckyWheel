# 最近十个提交的复审：结论与修复计划（2026-09-24）

审查对象：`e216461`（仓库卫生）、`741470e`（健壮性）、`b9141ae`（代码质量）、`1e20c51`（渲染与
列表优化）、`08a818a`（setItems 别名）、`151e091`（数据文件编码）、`6291c2d`（字体链路）、
`f7d5721`（storage 资源上限）、`c18cc17`（渲染侧收敛）、`fb4d85b`（审查报告）。

方法：两路并行专项审查（storage/models/paths 与 wheel/panels 渲染交互）+ 逐条自主复核，
关键项以 `build/` 下的一次性探针本地实测。基线：`pytest` 432 passed、`ruff check` /
`format --check` 干净、`verify_gui --entry main` 12 个 `[ok]`。

**总体结论**：这十个提交没有引入功能回归。`08a818a` 的私有拷贝、`1e20c51` 的列表增量 diff 与
字号缓存键、`151e091` 的编码处理、`6291c2d` 的字体回退都经实测确认语义正确（见第 2 节）。
但审查中发现 18 项缺陷，其中 2 项高危（S1/S2，都在数据文件写盘边界，均可实测复现），
4 项先于本轮提交存在且用户可见（U1 停止后多转一轮、U2 排序后旧结果不失效、S3 只读 `.bak`
上备份静默失效、D2 别名字体"报告已内嵌、运行时静默回退"）。

## 1. 发现汇总（按严重度）

| # | 严重度 | 位置 | 问题 | 实测证据 |
|---|---|---|---|---|
| S1 | 高 | `core/storage.py:264` | 落盘用文本模式（未给 `newline`），Windows 下把 `json.dumps(indent=2)` 的每个 LF 翻成 CRLF，而 `indent=2` 是一个条目一行——于是"体积检查刚好通过"的数据存回去就越过 `MAX_DATA_FILE_BYTES`，下次启动被整份隔离，真实数据只剩在 `load_state` 从不读的 `.bak` 里 | 探针：3,800,386 字节的 payload 落盘 4,000,406 字节，膨胀 200,020 = 换行数，恰好 1 字节/行 |
| S2 | 高 | `core/storage.py:265` | 数据文件里的孤立代理（`"\ud800"`）字面量是纯 ASCII 字节、`json.loads` 照单接受、`_sanitize_entries` 认它是 `str`，于是一路进 `AppState`；写盘时 `encode("utf-8")` 抛 `UnicodeEncodeError`——`ValueError` 子类，不被 `:281` 的 `except OSError` 接住，穿透 `save_state` 的 `StorageError` 契约。此后每次保存都失败、关窗的 `flushSave` 也失败，整场会话的改动无声丢失（`_write_state` 的宽 `except` 只保证不崩，不保证存下来） | 探针：载入成功，`save_state` 抛 `UnicodeEncodeError: surrogates not allowed`，临时文件无残留 |
| L1 | 中高 | `core/storage.py:118` | 告警峰值无界：`sanitize_group` 用自己的局部 list，`_warn` 的封顶是"每组各自 1001 条"；`parse_state` 循环内只 `extend`，循环结束后才截一次。`f7d5721` 声称的"告警总量上限"只对返回值成立 | 探针：6.04 MiB 文件（1000 组 × 1050 个 null）峰值 `len(warnings)` = 1,001,000，`tracemalloc` 峰值 148.1 MiB，返回值 1001 条 |
| L2 | 中 | `core/storage.py:75` | 条目上限按已保留条数（`len(cleaned)`）计而非已读位置：一组 140 万个 `null` 里 `cleaned` 恒为 0，永远触不到上限——构造成本最低的输入（每条 5 字节）拿到了唯一不受限的遍历 | 代码走读 + 探针（上限压到 5 时确认 `pos` 语义） |
| S3 | 中 | `core/storage.py:299` + `:271` | 只读 `.bak` 上 `os.replace` 在 Windows 抛 `PermissionError`，被 `except OSError: pass` 吞掉，备份静默失效。旧 `copy2` 会把只读源的 mode 复制到 `.bak`，因此既有只读 `wheel_data.json` 的用户其 `.bak` 至今是只读的——对他们新代码的备份和旧代码一样死，而 `f7d5721` 声称这一类已封掉 | 探针：`chmod` 只读后 `save_state` 不报错，`.bak` 内容未更新，主文件已更新 |
| U1 | 中 | `ui/panels/spin_panel.py:191` | 轮间 400ms 停顿里按「停止」会多转一轮：`QTimer.singleShot(400, wheel.startSpin)` 不可取消，`startSpin` 也不看批量状态。界面先显示"批量抽取完成"，400ms 后转盘又转一轮并宣布中奖、写上 `last_result_index`。先于本轮提交存在 | 子代理探针：停止后 `label=🎉 恭喜中奖: 1`、`last_result_index=6` |
| U2 | 中 | `ui/panels/items_panel.py:147-156` | 拖拽排序不走 `updateWheelFromCurrentGroup`，`result_label` 与 `last_result_index` 都留着。排序后同一扇区下已换成别的项目：标签仍显示旧中奖项，「抽出」按旧索引 pop 的是另一项。先于本轮提交存在 | 子代理探针：宣布 A05 后把行 0 拖到 5，标签仍是 A05，抽出 pop 的是 A00 |
| W1 | 中 | `ui/wheel.py:324-329` | 去抖到点的二次重建：`_onResizeSettled` 只看 `cached_pixmap is not None`，不看 `cached_size` 是否已等于当前边长。去抖窗口内任何失效（批量一轮的 `setItems`、字号 spinbox、阴影开关、dpr 变化）都让 `paintEvent` 已按最终边长重建过，定时器到点再强制重建一遍。附带：`_invalidate_cache` 不停定时器也不清 `_pending_side`，`resizeEvent` 的 `cached_size is None` 早退会把旧值搁在那儿 | 子代理探针：重建次数 1→2，且两次 `cached_size == side == 500`；`_pending_side=500` 能活过一次 resize 到 300 |
| W2 | 中 | `ui/wheel.py:233` | `1e20c51` 的测量改动在这一行严格劣于被它替换的代码：原行复用刚在 `:229` `setFont` 过的 `painter.fontMetrics()`（零额外成本），现行每个条目每次渲染都重进 `measure` 再造一份 `QFont`+`QFontMetrics`——包括 `fit()` 零求解的热缓存渲染 | 子代理 A/B（逐字复刻旧 `renderCache`）：输出像素完全一致；渲染耗时三组样本符号翻转（−4.6%/+1.6%、−9.5%/+2.2%、−0.4%/−3.2%），即噪声；单次测量 4.63µs vs 4.11µs |
| M1 | 低 | `core/models.py:114-117` | `clamp` 把类型非法的字体家族填成默认字符串而非 `None`，直接击穿 `6291c2d` 恢复的那条回退；紧邻的注释写的正好相反（"此处不得擅自填默认值"） | 子代理实测：`"ui_font_family": 5` → 窗口拿到 `Microsoft YaHei` 而非内嵌字体，随后被 `_write_state` 固化 |
| P1 | 低 | `core/paths.py:24` vs `:100` | frozen 判据不统一：`program_dir()` 看 `sys.frozen`，`font_candidates()` 看 `sys._MEIPASS`。PyInstaller 两种模式都设两者，故对本项目等价；cx_Freeze/py2exe 下"frozen 但无 `_MEIPASS`"，仓库根候选会从无意义的 `parents[3]` 复活且仍排在 `program_dir()` 之前——就是 `6291c2d` 要封的那个劫持面换了个打包器 | 代码走读 |
| P2 | 低 | `core/paths.py:117` | 候选去重键用 `str(c).lower()`，大小写敏感文件系统上会把真正不同的路径折叠掉 | 代码走读 |
| W3 | 低 | `ui/wheel.py:142` vs `:399` | dpr 钳位不对称：`renderCache` 把 `dpr <= 0` 钳到 1.0 并存钳后值，`paintEvent` 拿原值比较。真实 Qt 下取不到 0，但一旦为 0 就是每次 paintEvent 全量重建（旋转中即每帧） | 子代理探针（stub `devicePixelRatio`）：4 次重绘 5 次重建 |
| W4 | 低 | `ui/wheel.py:411`、`:129-131` | `cache_side = side if self.cached_size is None else ...` 是死代码：`cached_pixmap` 与 `cached_size` 在 `renderCache` 末尾同设、在 `_invalidate_cache` 同清，而这一行之前已 `cached_pixmap is None` 早退。另外空条目早退只清两项、漏 `cached_dpr`，与 `_invalidate_cache` 不一致 | 代码走读；随后否掉了报告初稿"`cached_size == 0` 时下一行 `ZeroDivisionError`"的说法——见第 6 节 |
| D1 | 低 | `assets/fonts/README.md:10` | 承诺的查找顺序"本目录 → 程序所在目录 → exe 解包目录"与 `font_candidates` 实际顺序（解包目录 → 本目录 → 程序目录）不符 | 代码对照 |
| D2 | 低 | `scripts/build_exe.py:27-34` | `find_font()` 取 `assets/fonts/` 下第一个 `*.ttf`/`*.otf` 并按原名 `--add-data`，而运行时只认固定名 `HYWenHei-65W.ttf`：放入别名字体时打包脚本报告"已内嵌"，运行时永远找不到、静默回退 | 代码对照 |
| D3 | 低 | `CHANGELOG.md` | 「未发布」段未记录本轮 8 个修复提交（`e216461`…`c18cc17`）的任何内容 | 文件走读 |
| D4 | 低 | `.gitignore` | 末尾缺换行 | 文件走读 |

## 2. 已验证无问题的点

- **`08a818a` 的私有拷贝安全**：12 处 `group["items"]` 变更全部经 `setItems`（直接或经
  `refresh_from_group`）；`wheel.items` 无外部读取方（只有内部 `len`/索引/迭代）。真实
  `MainWindow` 六轮批量抽取，每轮 `determineResult` 时 `wheel.items == group["items"]`、
  缓存 pixmap 来自同一列表、宣布项 `== group["items"][idx]`、`drawn_items == batch_results`。
  旋转中无 UI 路径可达 `updateWheelFromCurrentGroup`（触发点都在 `onSpinStarted` 禁用的
  `left_panel` 内，右侧的 `btn_extract` 显式禁用）。
- **`1e20c51` 的 `sync_list_items`**：1600 组穷举 `current × target` + 3000 组重复率高的随机对
  （字母表 `1ab1c`，长度 0~11）零不符，`changed` 恒等于 `current != target`。条目 flags 与
  `addItems` 逐位相同（`53`），InternalMove 拖拽不受影响；只发 `rowsInserted`/`rowsRemoved`，
  不发 `layoutChanged`/`modelReset`，故不会误触 `onItemsReordered`。中间删除后的选中项由
  `-1` 变成"保留并前移"，但三处调用点都显式重算 `next_row` 并 `setCurrentRow`，自动前移的
  行号与 `next_row` 在每个分支都相等。
- **`c18cc17` 的 `FontSizeCache` 容量上界**：中途 `clear` 既不改输出（`fit_font_size` 是纯函数；
  把 `MAX_ENTRIES` 压到 3 跑真实数据像素完全一致）也不会退化成二次——求解次数有 *n* 上界
  （真实数据 27 次，cap=4096 与 cap=3 相同；交错重复的最坏情形 28/29/30/40/41 对应
  cap=4096/26/10/3/1）。超过 4096 个唯一值后缓存只是不再跨渲染生效，而那时扇区宽 0.09°、
  字号已钉在 8px 下界。
- **`151e091` 的编码处理**：`utf-8-sig` 读 / `utf-8` 写对内容安全——BOM 载入即剥、不再写出，
  重复往返体积稳定（434 B → 434 B）。真正的两处隐患是 S1 与 S2，都不在 BOM 这条线上。
- **`f7d5721` 的备份失败面**：磁盘满（`fsync` 抛 `OSError`）、目标只读、备份失败三种情形都
  无临时文件残留，`except BaseException` 的清理是对的；"任一步失败原文件都在原地"成立。
- **`6291c2d` 的 `default_state()` 给 None**：穷举 8 处 `default_state()` 调用方，全部只经
  `MainWindow.loadData` 的 `or` 回填；无文件 / `null` / 非 str / 空串四种情形下窗口拿到的
  `ui_font_family`、`wheel_font_family` 都是 `str`，`settings_panel` 的字体下拉也拿到真实家族。
  数据文件存在时启动不触发自动保存（`pending_save=False`），不会把占位值写回。
  附带纠正一处注释前提：PyQt6 的 `QFont(None)` 不抛 `TypeError`，返回 `family=''`。

## 3. 修复计划（五批，各自独立提交）

每批完成跑同一条验证链：`pytest`（计数不低于 432 且无新增失败）、`ruff check` +
`ruff format --check`、`scripts/verify_gui.py --entry main|module`（各 12 个 `[ok]`）。

- **批次 1**（S1/S2/L2，数据文件边界）：`save_state` 改二进制落盘并自己 `encode`（同时消掉
  换行翻译与"临时文件已建才发现编码失败"），`UnicodeEncodeError` 归入 `StorageError`；载入侧
  对条目与分组名做 UTF-8 可编码性修补；条目上限改按已读位置计。补三条回归。
- **批次 2**（L1/S3，资源上限与备份可用性）：`parse_state` 循环内即截断并累计省略数（峰值从
  100 万降到约 2000）；`_copy_backup` 对只读目标的 `PermissionError` 去只读位重试一次。补两条回归。
- **批次 3**（M1/P1/P2，字体回退链与路径判据）：`clamp` 的非法字体家族回落 `None`；`paths`
  的 frozen 判据合并为 `sys.frozen or sys._MEIPASS`；去重键改 `os.path.normcase`。补回归。
- **批次 4**（W1~W4 + U1/U2，渲染与交互）：`:233` 改用已建好的 `font` 造 `QFontMetrics`；
  `_onResizeSettled` 增加"边长已一致就不重建"的判断，`_invalidate_cache` 一并清 `_pending_side`
  并停表；dpr 钳位收成一个取值函数供两侧共用；删 `cache_side` 死兜底、空条目早退改走
  `_invalidate_cache`；批量续转经一个查批量状态的方法而非直连 `startSpin`；拖拽排序清掉失效的
  `last_result_index` 与结果标签。补回归。
- **批次 5**（D1/D2/D3/D4，文档与卫生）：`assets/fonts/README.md` 的顺序改对；`build_exe.py`
  优先取运行时认的固定文件名、取到别名字体时显式警告名字不匹配；`CHANGELOG` 补本轮 8 个提交；
  `.gitignore` 补末尾换行。

## 4. 评估后不改的项

- **8 MiB 上限的全有全无**（前次审查记为 B3，已决定不改，本轮维持）：minify 过的 7 MiB 文件
  载入后按 `indent=2` 重排会显著变大，写回仍可能越限。给写侧加硬拒会造出"永远存不下去"的
  新状态，比现在的隔离（原件以 `.corrupt-<时间戳>` 名保留、告警给出确切文件名）更糟。批次 1
  消掉的是"平台相关的 1 字节/行膨胀"这一条人为诱因。
- **告警截断的优先级**：结构性汇总（超限截断）会被 1000 条逐项告警淹没而看不到。拆成"汇总/
  细节"两条队列要改 `_sanitize_entries` 的签名与三处调用点，收益只在已经是恶意输入的场景，
  而那时前 1000 条告警已足够说明问题。
- **`OSError` 读取失败不隔离**：保持现状。Windows 上更常见的是杀软/备份软件的瞬时占用，隔离
  会把能自愈的情形（下次启动照常读到）变成"数据被改名搬走"。代价是该会话内的保存会覆盖原件，
  但那需要用户在明确看到"读取失败，已启用默认数据"之后继续编辑。
- **`pip install .` 后的数据位置**：`program_dir()` 的 `parents[3]` 在安装树里指向 `<prefix>/Lib`，
  于是 `wheel_data.json` 落在 `Lib/` 下，两个字体候选也都不可能存在（ttf 不是包数据、按版权
  不随包分发）。实测确认。功能可用（该目录通常可写），只是位置不合惯例；改判据会让已按此
  运行的用户数据"消失"，且没有可靠的迁移依据，故只记录。
- **`sync_list_items` 返回值三处被忽略**：调用点都显式重算 `next_row` 并 `setCurrentRow`，
  与返回值无行为差异。

## 5. 风险

批次 1 与批次 2 改的是写盘路径，最坏情况是保存失败——但两批都只在原子写的既有框架内动，
临时文件清理与"任一步失败原文件在原地"的不变式由既有回归钉住。批次 1 把落盘从文本模式换成
二进制，既有数据文件（CRLF）读取不受影响（`json` 两种换行都吃）。

批次 3 的 `clamp` 改动会让"手改 JSON 把字体家族写成数字"从"回落 Microsoft YaHei"变成"回落到
启动期选中的内嵌字体"，方向与 `6291c2d` 一致。

批次 4 的 W2 改动需要确认 `QFontMetrics(font)` 与 `measure` 内部构造逐字相同（家族 + bold +
pixelSize），否则会静默改变每个扇区的字号——`TestMeasurementPathsAgree` 按 dpr 参数化钉住
这一点，像素基线测试另有一道。U1/U2 是先于本轮提交存在的用户可见缺陷，修完行为更接近
"停止就是停止""排序后旧结果失效"的直觉。

## 6. 实施记录

五批全部按第 3 节的计划落地，每批独立跑完整验证链后提交。

| 提交 | 内容 | 实施中的发现 |
|---|---|---|
| `7268f5b` | S1/S2/L2：`save_state` 改自己 `encode` 后二进制落盘；`UnicodeEncodeError` 归入 `StorageError`；载入侧 `_repair_text` 把不可编码字符换成 U+FFFD；条目上限改按已读位置 `pos` 计 | S2 的修复必须落在载入与写盘两侧：只在写盘侧归类异常，用户看到的仍是"每次保存都失败"；只在载入侧修补，手工构造的内存状态仍能触发。432 → 436 passed |
| `a1589e5` | L1/S3：`_merge_warnings` 在 `parse_state` 循环内即截断并返回省略数；`_copy_backup` 改 `mkstemp`+`fsync`+`replace`，只读目标去掉只读位重试一次 | 备份不能用 `shutil.copy2`：它会把源的只读 mode 一起复制过去（这正是既有用户 `.bak` 至今只读的原因），且中途失败会留下半截 `.bak` 覆盖掉上一份好备份。同一 6.04 MiB 输入 `tracemalloc` 峰值 148.1 → 9.4 MiB。436 → 439 passed |
| `6d89de2` | M1/P1/P2：`clamp` 的非法字体家族回落 `None`；frozen 判据收拢为 `is_frozen()`；去重键改 `os.path.normcase` | `tests/unit/test_storage.py::test_non_string_font_family_falls_back` 原先钉的是被修掉的行为（断言拿到 `Microsoft YaHei`），改断言为 `None`。探针确认改动后窗口解析到内嵌字体 `HYWenHei`，且启动不把 `5` 改写回文件。439 → 442 passed |
| `21f1999` | W1~W4 + U1/U2：`renderCache` 改用已建好的 `font` 造 `QFontMetrics`；`_onResizeSettled` 增加"边长已一致就不重建"；`_invalidate_cache` 一并清 `_pending_side` 并停表；dpr 钳位收成 `_device_pixel_ratio()`；删 `cache_side` 死兜底、空条目早退改走 `_invalidate_cache`；批量续转改经 `_continueBatch()`；拖拽排序清 `last_result_index` 与结果标签 | 复核时否掉了 W4 的一条更强说法：`min(w, h) == 0` 不可达——两个 `QSplitter` 都设了 `setChildrenCollapsible(False)`，`WheelWidget` 另有 `setMinimumSize(200, 200)`，`resize(0, 400)` 被直接钳住。故不加 `side <= 0` 守卫，只删死兜底，按此删掉了两条为不可达路径写的测试。W2 的等价性由探针穷举 4 个字体家族 × 1~200px × 10 个文本共 8000 组，度量零不符。442 → 454 passed |
| `fc70045` | D1/D2/D3/D4：`build_exe.py` 优先取运行时认的固定名并对别名字体显式警告、名字常量从 `core.paths` 导入；`README` 顺序改对；`CHANGELOG` 补本轮；`.gitignore` 补换行 | `build_exe.py` 用覆盖 `FONT_DIR` 的方式三路实测：固定名 → `(path, True)`，别名 → `(path, False)`，目录不存在 → `(None, False)`。454 passed（纯文档批次） |

U1/U2 的回归各自先用 `git stash` 把源文件退回旧版确认能翻红（各 4 条失败），再 `stash pop`，以免写出"无论怎样都通过"的测试——上一轮审查记录过三处这类断言。

最终状态：`pytest` 454 passed、`ruff check` / `ruff format --check` 干净、`verify_gui.py --entry main` 与 `--entry module` 各 12 个 `[ok]`。第 4 节列的五项维持不改。
