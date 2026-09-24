"""数据文件读写：原子写、损坏保留、schema 迁移、类型校验（零 Qt 依赖）。

与旧实现的区别（旧问题见 docs/REFACTOR_PLAN_V2.md 1.2(E)(F)）：
- 写入改为同目录临时文件 + os.replace，崩溃不会留下截断的半文件；
  替换前把上一版保留为 .bak（用复制而非改名，见 save_state）；
- 读取失败（损坏）时把原件改名保留为 wheel_data.corrupt-<时间戳>.json，
  再启用默认值，绝不静默覆盖用户数据；
- 载入时做类型校验：缺键、类型不符的项被规整或跳过，不再 KeyError 崩溃；
- 磁盘格式带 version 字段，旧格式（无版本号）自动迁移。

外部数据文件是不可信输入：本模块对文件大小、条目数、单条长度、嵌套深度
与数值范围都设上限，超限按损坏处理并隔离原件，而不是让异常穿透到
MainWindow.__init__ 把程序变成起不来。
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

from .models import SCHEMA_VERSION, AppState, Group, default_state

# 外部数据文件的资源上限。数据文件是用户可编辑的 JSON，但"能打开"不等于
# "应该照单全收"：8 MiB 足以容纳数万条目，2 GB 的文件只可能是误操作或
# 恶意构造（实测 2 GB 文件加载 36 s、保存 17 s 并生成 2 GB .bak）。
MAX_DATA_FILE_BYTES = 8 * 1024 * 1024
# 单分组条目数上限：超出后截断而非全部拒绝，保留可用部分
MAX_ENTRIES_PER_GROUP = 100_000
# 单条文本长度上限：超长条目在转盘上本就无法显示，只会拖慢字号求解
MAX_TEXT_LENGTH = 2000


class StorageError(Exception):
    """存储层异常；具体信息附带原文件路径，便于界面提示。"""


def _is_int(value):
    """排除 bool：bool 是 int 子类，True 会混过 isinstance(x, int)。"""
    return isinstance(value, int) and not isinstance(value, bool)


def sanitize_group(data, index):
    """把单个 group 的原始 JSON 规整为合法 Group，返回 (group, warnings)。"""
    warnings = []
    if not isinstance(data, dict):
        return Group(name=f"分组{index + 1}"), [f"第 {index + 1} 个分组不是对象，已重建"]

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        name = f"分组{index + 1}"
        warnings.append(f"第 {index + 1} 个分组名非法，已设为 {name}")

    items = _sanitize_entries(data.get("items"), "items", index, warnings)
    drawn = _sanitize_entries(data.get("drawn_items", data.get("drawn")), "drawn", index, warnings)
    return Group(name=name.strip(), items=items, drawn=drawn), warnings


def _sanitize_entries(raw, field, index, warnings):
    """条目列表：非字符串项转字符串（如误输入数字），None/复合类型剔除。"""
    if not isinstance(raw, list):
        warnings.append(f"分组 {index + 1} 的 {field} 不是列表，已置空")
        return []
    cleaned = []
    for pos, item in enumerate(raw):
        if len(cleaned) >= MAX_ENTRIES_PER_GROUP:
            warnings.append(
                f"分组 {index + 1} 的 {field} 超过 {MAX_ENTRIES_PER_GROUP} 条，"
                f"其余 {len(raw) - pos} 条已忽略"
            )
            break
        if isinstance(item, str):
            # 超长条目截断：转盘上一个扇区放不下几千字，留着只会让字号求解
            # 每次都对同一段长文本做二分
            if len(item) > MAX_TEXT_LENGTH:
                warnings.append(f"分组 {index + 1} 的 {field}[{pos}] 过长，已截断")
                item = item[:MAX_TEXT_LENGTH]
            cleaned.append(item)
        elif isinstance(item, bool) or item is None or isinstance(item, (list, dict)):
            warnings.append(f"分组 {index + 1} 的 {field}[{pos}] 类型非法，已剔除")
        else:
            cleaned.append(str(item))
            warnings.append(f"分组 {index + 1} 的 {field}[{pos}] 转为字符串")
    return cleaned


def parse_state(data, source_name="数据"):
    """把已解析的 JSON 转为 AppState，返回 (state, warnings)。"""
    warnings = []
    if not isinstance(data, dict):
        return default_state(), [f"{source_name}顶层不是对象，已启用默认数据"]

    raw_groups = data.get("groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        warnings.append(f"{source_name}无有效分组，已启用默认数据")
        groups = []
        current = 0
    else:
        groups = []
        for i, g in enumerate(raw_groups):
            group, group_warnings = sanitize_group(g, i)
            warnings.extend(group_warnings)
            groups.append(group)
        current = data.get("current_group", 0)
        # 必须排除 bool：isinstance(True, int) 为真，混过后会被原样序列化回
        # JSON 变成 true，数据类型在读写往返中被静默改变
        if not _is_int(current) or not 0 <= current < len(groups):
            warnings.append("current_group 越界，已重置为 0")
            current = 0

    state = AppState(
        groups=groups if groups else default_state().groups,
        current_group=current,
        ui_font_family=data.get("ui_font_family", data.get("font_family")),
        ui_font_size=data.get("ui_font_size", AppState.ui_font_size),
        # 字体家族缺键时必须是 None 而不是默认字符串：MainWindow.loadData 用
        # `state.x or self.x` 保留启动期 loadEmbeddedFont 已确定的字体，若此处
        # 填了默认值，那个回退永远不触发，源码运行就永远用不到 assets/fonts/
        # 下的字体、与打包版不一致（该回退曾因这个原因完全失效）。
        wheel_font_family=data.get("wheel_font_family", data.get("font_family")),
        wheel_font_size=data.get("wheel_font_size", AppState.wheel_font_size),
        shadow_enabled=data.get("shadow_enabled", AppState.shadow_enabled),
        window_geometry=data.get("window_geometry"),
        splitter_sizes=data.get("splitter_sizes"),
        list_height=data.get("list_height", AppState.list_height),
        drawn_list_height=data.get("drawn_list_height", AppState.drawn_list_height),
        batch_spin_count=data.get("batch_spin_count", AppState.batch_spin_count),
        theme=data.get("theme", AppState.theme),
        version=data.get("version", SCHEMA_VERSION),
    )
    state.clamp()

    # schema 迁移钩子：version 2 → 未来版本在此扩展
    declared = data.get("version")
    if declared is None:
        warnings.append("旧格式（无 version 字段）已自动迁移为 v2")
    elif isinstance(declared, int) and declared > SCHEMA_VERSION:
        warnings.append(
            f"数据版本 v{declared} 高于本程序支持的最高版本 v{SCHEMA_VERSION}，不支持的字段将被忽略"
        )
    return state, warnings


def load_state(path):
    """读取数据文件。返回 (state, warnings)。任何损坏都保留原件不改写。"""
    path = Path(path)
    try:
        # 先查体积再读内容：2 GB 的文件读进内存要 36 s，且会让随后的保存
        # 生成同等体积的 .bak。st_size 不可信时（稀疏文件/特殊文件）由
        # 下面的读取异常兜底。
        if path.stat().st_size > MAX_DATA_FILE_BYTES:
            quarantine(path)
            return default_state(), [
                f"数据文件超过 {MAX_DATA_FILE_BYTES // (1024 * 1024)} MiB 上限，"
                f"已按损坏处理，原件保留为 {path.stem}.corrupt-*.json"
            ]
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default_state(), []
    except OSError as exc:
        return default_state(), [f"读取失败（{exc}），已启用默认数据"]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        quarantine(path)
        return default_state(), [
            f"数据文件损坏（{exc.msg} 于第 {exc.lineno} 行），"
            f"原件已保留为 {path.stem}.corrupt-*.json"
        ]
    except RecursionError:
        # 深度嵌套的 JSON 会让 json.loads 抛 RecursionError 而非
        # JSONDecodeError（实测 3000 层 {"a": 即触发）。它是 RuntimeError
        # 子类，漏捕就会穿透 loadData 直达 MainWindow.__init__，
        # 程序根本无法启动——而构造这种文件不需要任何合法 schema。
        quarantine(path)
        return default_state(), [
            f"数据文件嵌套层级过深，无法解析，原件已保留为 {path.stem}.corrupt-*.json"
        ]

    state, warnings = parse_state(data, source_name=path.name)
    return state, warnings


def quarantine(path):
    """把损坏的文件改名保留，而不是静默覆盖。"""
    stamp = _timestamp()
    candidate = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}.corrupt-{stamp}-{counter}{path.suffix}")
        counter += 1
    try:
        os.replace(path, candidate)
    except OSError:
        pass  # 保留失败也不阻塞启动，默认数据仍可用


def _timestamp():
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d-%H%M%S")


def save_state(path, state):
    """原子写入：临时文件 + os.replace，并在替换前留一份 .bak。

    备份必须用复制而非 os.replace 改名：改名会让活动文件先消失，此时崩溃
    或紧接着的第二步失败，目标路径就不存在了，而 load_state 从不读 .bak，
    用户看到的是"数据被清空"而非"上一次的数据"。复制的代价是同一份数据
    在磁盘上短暂存在两份，换取的是任何一步失败时原文件都还在原地。
    """
    path = Path(path)
    payload = json.dumps(state.to_dict(), ensure_ascii=False, indent=2)
    directory = path.parent if str(path.parent) else Path(".")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(directory))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            if path.exists():
                try:
                    shutil.copy2(path, _backup_path(path))
                except OSError:
                    pass  # 备份失败不阻塞主写入
            os.replace(tmp_name, path)
        except BaseException:
            # 任何一步失败都清理临时文件，不在数据目录留垃圾
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except OSError as exc:
        raise StorageError(f"保存失败: {exc}") from exc


def _backup_path(path):
    return path.with_name(path.name + ".bak")
