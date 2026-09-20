"""应用数据模型与序列化（零 Qt 依赖）。"""

from dataclasses import dataclass, field

SCHEMA_VERSION = 2

DEFAULT_UI_FONT = "Microsoft YaHei"
DEFAULT_WHEEL_FONT = "Microsoft YaHei"
DEFAULT_GROUP_NAME = "默认分组"
THEMES = ("light", "dark", "system")


@dataclass
class Group:
    """一个抽签分组。items 为待抽条目，drawn 为已抽出（不放回）条目。

    条目一律按索引操作（插入/删除/抽出），不按文本匹配——
    重复文本（真实数据中常见，如 41 项里 15 个 "1"）不会因此错删。
    """

    name: str = DEFAULT_GROUP_NAME
    items: list = field(default_factory=list)
    drawn: list = field(default_factory=list)

    def to_dict(self):
        return {"name": self.name, "items": list(self.items), "drawn_items": list(self.drawn)}

    @classmethod
    def from_dict(cls, data):
        return cls(
            name=data.get("name", DEFAULT_GROUP_NAME),
            items=list(data.get("items", [])),
            drawn=list(data.get("drawn_items", [])),
        )


@dataclass
class AppState:
    """可持久化的全部应用状态。"""

    groups: list = field(default_factory=list)
    current_group: int = 0
    ui_font_family: str = DEFAULT_UI_FONT
    ui_font_size: int = 9
    wheel_font_family: str = DEFAULT_WHEEL_FONT
    wheel_font_size: int = 0  # 0 = 自动
    shadow_enabled: bool = True
    window_geometry: object = None  # [x, y, w, h] 或 None
    splitter_sizes: object = None  # [left, right] 或 None
    list_height: int = 200
    drawn_list_height: int = 120
    batch_spin_count: int = 3
    theme: str = "light"
    version: int = SCHEMA_VERSION

    @property
    def current_group_object(self):
        if 0 <= self.current_group < len(self.groups):
            return self.groups[self.current_group]
        return None

    def to_dict(self):
        data = {
            "version": self.version,
            "groups": [g.to_dict() for g in self.groups],
            "current_group": self.current_group,
            "ui_font_family": self.ui_font_family,
            "ui_font_size": self.ui_font_size,
            "wheel_font_family": self.wheel_font_family,
            "wheel_font_size": self.wheel_font_size,
            "shadow_enabled": self.shadow_enabled,
            "list_height": self.list_height,
            "drawn_list_height": self.drawn_list_height,
            "batch_spin_count": self.batch_spin_count,
            "theme": self.theme,
        }
        if self.window_geometry is not None:
            data["window_geometry"] = list(self.window_geometry)
        if self.splitter_sizes is not None:
            data["splitter_sizes"] = list(self.splitter_sizes)
        return data

    @classmethod
    def from_dict(cls, data):
        groups = [Group.from_dict(g) for g in data.get("groups", [])]
        # 旧格式的 font_family 字段：ui 与转盘字体曾共用
        legacy_font = data.get("font_family")
        state = cls(
            groups=groups,
            current_group=data.get("current_group", 0),
            ui_font_family=data.get("ui_font_family", legacy_font or DEFAULT_UI_FONT),
            ui_font_size=data.get("ui_font_size", 9),
            wheel_font_family=data.get("wheel_font_family", legacy_font or DEFAULT_WHEEL_FONT),
            wheel_font_size=data.get("wheel_font_size", 0),
            shadow_enabled=data.get("shadow_enabled", True),
            window_geometry=data.get("window_geometry"),
            splitter_sizes=data.get("splitter_sizes"),
            list_height=data.get("list_height", 200),
            drawn_list_height=data.get("drawn_list_height", 120),
            batch_spin_count=data.get("batch_spin_count", 3),
            theme=data.get("theme", "light"),
            version=data.get("version", SCHEMA_VERSION),
        )
        state.clamp()
        return state

    def clamp(self):
        """把引用外部数据后的取值收敛到合法范围。"""
        if not self.groups:
            self.groups = [Group()]
            self.current_group = 0
        if not 0 <= self.current_group < len(self.groups):
            self.current_group = 0
        if self.theme not in THEMES:
            self.theme = "light"
        # isinstance(x, bool) 要先排除：bool 是 int 子类，True 会混过字号校验
        if not _is_int(self.ui_font_size) or self.ui_font_size < 1:
            self.ui_font_size = 9
        if not _is_int(self.wheel_font_size) or self.wheel_font_size < 0:
            self.wheel_font_size = 0
        if not _is_int(self.batch_spin_count) or self.batch_spin_count < 1:
            self.batch_spin_count = 3


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def default_state():
    """新装/数据不可用时的初始状态。"""
    return AppState(
        groups=[Group(name=DEFAULT_GROUP_NAME, items=["选项1", "选项2", "选项3"], drawn=[])],
        current_group=0,
    )
