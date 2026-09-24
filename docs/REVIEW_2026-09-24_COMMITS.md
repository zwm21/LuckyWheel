# 近四批提交审查：结论与修复计划（2026-09-24）

审查对象：`e216461`（批次 A 仓库卫生）、`741470e`（批次 B 健壮性）、`b9141ae`（批次 C 代码质量）、
`1e20c51`（批次 D 渲染与列表优化）。方法：三路并行专项审查（批次 D / 批次 B / 批次 A+C）
+ 逐条自主复核，关键项本地实测复现。基线：`pytest` 420 passed、`ruff check`/`format --check` 干净。

## 1. 发现汇总（按严重度）

| # | 严重度 | 位置 | 问题 | 实测证据 |
|---|---|---|---|---|
| D1 | 高 | `ui/wheel.py:286-301` | `setItems` 短路与别名叠加：`self.items = items` 不拷贝，wheel.items 与 group["items"] 是同一对象；`items is self.items` 最先命中，恰是"调用方原地改过内容"的场景，短路跳过 `_invalidate_cache()` 与 `update()`，转盘继续画旧 pixmap。批量抽取每轮 pop 后，可见扇区与 `determineResult` 宣布的中奖项不一致；日常"添加/打乱"后转盘不刷新 | 代码走读确认；批量路径 `spin_panel.pop → refresh → setItems(同一对象)` 是每条日常路径 |
| B1 | 高 | `core/storage.py:157` | `UnicodeDecodeError`（ValueError 子类，非 OSError）不被捕获，穿透 `loadData` → `MainWindow.__init__`，程序起不来。中文 Windows 记事本按默认 ANSI(GBK) 保存含中文的数据文件即触发 | `build/probe_review_encoding.py` 实测：GBK 文件 `RAISED: UnicodeDecodeError` |
| B2 | 中高 | `core/storage.py:157` | `encoding="utf-8"` 不剥 BOM，记事本"UTF-8"选项保存的合法文件必然 `JSONDecodeError` → 整份数据被隔离改名，无恢复入口 | 实测：BOM 文件被隔离为 `bom.corrupt-20260924-171827.json` |
| A1 | 高 | `core/models.py:169-174`（`default_state`） | 批次 A 第 4 项的字体回退在主场景未生效：文件不存在/被隔离走 `default_state()`，其字体家族默认 `"Microsoft YaHei"`（非 None），`loadData` 的 `state.x or self.x` 回退不触发，内嵌字体被丢弃并在 `:194-196` 写盘固化 | 实测 `default_state().ui_font_family == 'Microsoft YaHei'` |
| A2 | 中 | `core/paths.py:100-109` | frozen 模式下 `parents[3]` 指向 `%TEMP%`，候选 `%TEMP%/assets/fonts/` 排第 2（在 exe 旁之前），用户态可写目录可被预置同名 ttf 劫持 | 代码走读确认 onefile 下 `__file__` 位于 `_MEIPASS` |
| B3 | 中 | `storage.py:151-156` | 8 MiB 超限=整文件隔离；与 `MAX_ENTRIES_PER_GROUP(10万) × MAX_TEXT_LENGTH(2000)` ≈ 200 MB 的理论上限互相拆台，长文本数据的截断路径永不可达 | 常量推算 |
| B4 | 中 | `storage.py:29` | 分组数无上限：<8 MiB 可塞约 18 万空分组，`group_panel.updateGroupCombo` 逐组 addItem；单组 10 万条超出 UI 可承受量级 | 代码走读 |
| B5 | 低-中 | `storage.py:66-83` | warnings 列表本身无上限（仅限制展示），8 MiB 最多产生约 140 万条告警字符串常驻 | 常量推算 |
| B6 | 低 | `storage.py:220-229` | `.bak` 不 fsync；`copy2` 以 "wb" 直开目标，中途失败毁掉上一份好备份；复制 mode 使源只读时后续备份静默失效 | 代码走读 |
| B7 | 低 | `storage.py:108/155/169/178` | 告警可诊断性：`current_group: true` 报"越界"实为类型错误；隔离告警给 glob 形式文件名，用户找不到被隔离的文件 | 代码走读 |
| B8 | 低 | `models.py:16-18` | clamp 上界与控件范围不一致：`MAX_FONT_SIZE=200` vs spinbox 72、`MAX_BATCH_SPIN_COUNT=1000` vs 999，手改 JSON 的大值过 clamp 后被 `setValue` 静默夹回 | 代码走读 |
| D2 | 中 | `tests/characterization/test_current_main_behavior.py:289-306` | 死导入守卫 `_import_lines()` 只扫行首，多行 import 续行永不被扫——批次 D 把 import 拆成多行后，`REMOVED_NAMES` 里的 `QFontMetrics` 守卫被静默绕开 | 代码走读 |
| D3 | 低 | `core/layout.py:89-98` | `FontSizeCache` 删除三处 clear 后无淘汰机制，批量抽取期间键单调增长（量级几 MB，非功能问题） | 代码走读 |
| C1 | 低 | `ui/wheel.py:134-135/465` | 半径推导收敛只完成 1/3：`paintEvent` 已改 `WHEEL_RADIUS_RATIO`，`renderCache` 与 `mousePressEvent` 仍各自持一份 `WHEEL_DIAMETER_RATIO/2` | 数值恒等，无行为变化 |
| C2 | 低 | `tests/characterization/test_pixel_baseline.py:39` | 测试侧 `RADIUS_FRACTION = 0.44` 硬编码仍在，改 layout 常量时测试静默测旧几何 | 代码走读 |
| C3 | 低 | `ui/wheel.py:84`、`models.py:83-88` | `_invalidate_cache` docstring 写"六个 setter"实为 5 个+resize；`to_dict` 的 None 跳过分支生产不可达，注释指向不存在的路径 | 代码走读 |
| C4 | 提示 | `storage.py:38-40` vs `models.py` | `_is_int` 在 core 层两份实现，有漂移风险 | 代码走读 |

## 2. 已验证无问题的点（节选）

- 批次 D 的 `_measure` 两条测量路径等价（绘制与测量字体构造逐字相同；`setPixelSize` 置 pointSize=-1 无混用；`TestMeasurementPathsAgree` 按 dpr 钉住）；`FontSizeCache` 的 namespace 键完备且 None 可哈希不撞键；`sync_list_items` 行号推演全部边界正确（前后缀不重叠、删中间段行号递减、选中项保留）。
- 批次 B 的 clamp 上界不过紧（UI 可达值全部低于新上界，负坐标保留支持多屏）；`RecursionError` 捕获位置充分；备份保留语义正确（任一步失败原文件都在原地）。
- 批次 A 的 None 链条：`loadData` 的 `or` 保证窗口属性非 None；用户切过字体后 save→load 往返闭合；`bootstrap` 委托 paths 后候选集合对既有可用位置是超集；四处死代码确无调用方（含 build/ 下 11 个探针）；`updating_list` 只读 property 的写入点全部在 `updateWheelFromCurrentGroup` 内成对；fixture 下沉后语义等价。

## 3. 修复计划（四批，各自独立提交）

每批完成跑同一条验证链：`pytest`（计数不低于 420 且无新增失败）、`ruff check` +
`format --check`、`scripts/verify_gui.py --entry main|module`（各 12 个 `[ok]`）。

- **批次 1**（D1，用户可见回归）：`setItems` 改防御性拷贝 `new_items = list(items)` 并按值比较，删 `items is self.items or`；补回归测试（原地 pop 后 pixmap 必须失效）。顺带 D2：死导入守卫改 `ast.parse` 收集导入名。
- **批次 2**（B1/B2，启动崩溃与数据搬家）：`load_state` 读取改 `utf-8-sig` 并捕获 `UnicodeDecodeError`，与 JSON 损坏同等隔离；补 GBK/BOM 两条回归。
- **批次 3**（A1/A2，字体链路）：`default_state()` 字体家族显式传 None 让回退真正接通；`paths` 的仓库根 assets 候选限非 frozen；补首启字体断言。
- **批次 4**（其余中低危收敛）：B4 分组数上限、B5 warnings 上限、B6 .bak 走 tmp+replace+fsync、B7 告警确切文件名与文案、B8 clamp 常量与控件对齐、C4 `_is_int` 单份实现、D3 缓存容量上限、C1 半径推导剩余两处收敛、C2 测试侧引用常量、C3 注释/docstring 修正。

不做的：B3 的 8 MiB 梯度设计（正常用户够用，改梯度增加复杂度，仅在告警中给确切路径）；
A2 之外的候选面进一步收窄（src/luckywheel/ui/ 无字体，无实际回归，仅记录）。

## 4. 风险

批次 1/2/3 修的是"程序起不来/画面与数据不一致/修复未生效"类缺陷，最坏情况是回到修复前的行为。
批次 4 全部是收敛与文案，B8 会把"手改 JSON 设超过控件范围的值"从"被 setValue 静默夹回"
变为"clamp 回落默认值"，两者用户都看不到原值，方向一致。

## 5. 实施记录（全部完成）

| 提交 | 内容 | 发现 |
|---|---|---|
| `08a818a` | setItems 防御性拷贝 + 死导入守卫改 ast | D1、D2 |
| `151e091` | load_state 编码修复（GBK 捕获、BOM 剥离） | B1、B2 |
| `6291c2d` | default_state 字体 None + frozen 候选面收敛 | A1、A2 |
| `f7d5721` | storage 资源上限（分组数、告警总量、备份原子性、隔离告警确切文件名、_is_int 单份） | B4、B5、B6、B7、C4 |
| `c18cc17` | FontSizeCache 容量上界、半径推导剩余两处、测试侧引用常量、注释修正 | D3、C1、C2、C3 |

评估后不改的项：

- **B3**（8 MiB 超限=整文件隔离，与单组上限互相拆台）：正常抽奖场景远够用，
  改造梯度（读入后截断而非隔离）会增加复杂度与新的失败面；已在隔离告警中给出
  确切文件名，用户数据可手动找回。
- **B8**（clamp 上界与 spinbox 范围不一致）：对齐常量会让手改 JSON 的大值从
  "被 setValue 夹到控件上限"变为"clamp 回落默认值"，离用户意图更远；Qt 控件的
  夹取是标准行为，维持现状。
- **A2 之外的候选面收窄**（非 frozen 不再看 `src/luckywheel/ui/`）：该位置无
  字体、非文档承诺来源，新候选集合对既有可用位置是超集，无用户可见回归，
  仅在此记录。

每批验证链均为 `pytest`（420 → 432 passed，无失败）、`ruff check` +
`format --check` 干净、`verify_gui --entry main|module` 各 12 个 `[ok]`；
B1/B2 另以 build 探针端到端复验（GBK 由抛异常变为隔离+默认数据、BOM 由被
隔离变为正常加载）。
