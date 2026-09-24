"""应用数据模型与序列化（零 Qt 依赖）。"""

from dataclasses import dataclass, field

SCHEMA_VERSION = 2

DEFAULT_UI_FONT = "Microsoft YaHei"
DEFAULT_WHEEL_FONT = "Microsoft YaHei"
DEFAULT_GROUP_NAME = "默认分组"
THEMES = ("light", "dark", "system")

# 数值上界。这些字段全部来自外部数据文件，随后直接进 QFont/QRect/
# setSizes——C++ 侧是 int，超范围的 Python 大整数会在边界检查处抛
# OverflowError，而它发生在 MainWindow.__init__ 里，表现为程序起不来。
# 32767 是 Win32 短整型上界，也是 QWidget 尺寸的实际可用上限。
MAX_FONT_SIZE = 200
MAX_LIST_HEIGHT = 20000
MAX_BATCH_SPIN_COUNT = 1000
MAX_COORD = 32767
MIN_COORD = -32768


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
        """从 dict 构造。UI 层的 groups 全程以 dict 形态持有（面板直接按
        "items"/"drawn_items" 读写），落盘时由这里转回 Group——这是两套
        表示之间的桥，不是可删的死代码。
        """
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

    def to_dict(self):
        data = {
            "version": self.version,
            "groups": [g.to_dict() for g in self.groups],
            "current_group": self.current_group,
            "ui_font_size": self.ui_font_size,
            "wheel_font_size": self.wheel_font_size,
            "shadow_enabled": self.shadow_enabled,
            "list_height": self.list_height,
            "drawn_list_height": self.drawn_list_height,
            "batch_spin_count": self.batch_spin_count,
            "theme": self.theme,
        }
        # 字体家族为 None（数据文件未记录）时不写键，让下次读取继续走
        # loadEmbeddedFont 的回退，而不是把某个默认值固化成用户选择
        if self.ui_font_family is not None:
            data["ui_font_family"] = self.ui_font_family
        if self.wheel_font_family is not None:
            data["wheel_font_family"] = self.wheel_font_family
        if self.window_geometry is not None:
            data["window_geometry"] = list(self.window_geometry)
        if self.splitter_sizes is not None:
            data["splitter_sizes"] = list(self.splitter_sizes)
        return data

    def clamp(self):
        """把引用外部数据后的取值收敛到合法范围。

        上下界都要收：下界防 0/负数让控件退化，上界防超大整数进 Qt 的
        int 参数时抛 OverflowError（该异常发生在 MainWindow.__init__，
        用户看到的是程序根本无法启动）。
        """
        if not self.groups:
            self.groups = [Group()]
            self.current_group = 0
        if not _is_int(self.current_group) or not 0 <= self.current_group < len(self.groups):
            self.current_group = 0
        if self.theme not in THEMES:
            self.theme = "light"
        # 字体家族直接进 QFont()，非字符串会 TypeError。None 是合法值，表示
        # "数据文件未记录"，由调用方（MainWindow.loadData）用启动期
        # loadEmbeddedFont 的选择回填；此处不得擅自填默认值，否则那个回退
        # 永远不触发，源码运行与打包版字体不一致。
        if self.ui_font_family is not None and not isinstance(self.ui_font_family, str):
            self.ui_font_family = DEFAULT_UI_FONT
        if self.wheel_font_family is not None and not isinstance(self.wheel_font_family, str):
            self.wheel_font_family = DEFAULT_WHEEL_FONT
        # isinstance(x, bool) 要先排除：bool 是 int 子类，True 会混过字号校验
        if not _is_int(self.ui_font_size) or not 1 <= self.ui_font_size <= MAX_FONT_SIZE:
            self.ui_font_size = 9
        if not _is_int(self.wheel_font_size) or not 0 <= self.wheel_font_size <= MAX_FONT_SIZE:
            self.wheel_font_size = 0
        if not _is_int(self.batch_spin_count) or not 1 <= self.batch_spin_count <= (
            MAX_BATCH_SPIN_COUNT
        ):
            self.batch_spin_count = 3
        # 几何/高度字段直接来自外部文件：旧实现在 loadData 里手写长度检查，
        # 收拢到此处统一收敛，避免坏值进入 Qt 的 setGeometry/setSizes
        if not _is_int_list(self.window_geometry, 4):
            self.window_geometry = None
        elif not self._geometry_in_range(self.window_geometry):
            self.window_geometry = None
        if not _is_int_list(self.splitter_sizes, 2):
            self.splitter_sizes = None
        elif not self._geometry_in_range(self.splitter_sizes):
            self.splitter_sizes = None
        if not _is_int(self.list_height) or not 1 <= self.list_height <= MAX_LIST_HEIGHT:
            self.list_height = 200
        if not _is_int(self.drawn_list_height) or not 1 <= self.drawn_list_height <= (
            MAX_LIST_HEIGHT
        ):
            self.drawn_list_height = 120

    @staticmethod
    def _geometry_in_range(values):
        """几何数值范围检查：坐标可负（多屏布局），尺寸必须为正。"""
        if len(values) == 4:
            # window_geometry: [x, y, w, h]
            x, y, w, h = values
            return (
                MIN_COORD <= x <= MAX_COORD
                and MIN_COORD <= y <= MAX_COORD
                and 1 <= w <= MAX_COORD
                and 1 <= h <= MAX_COORD
            )
        # splitter_sizes: [left, right]
        return all(1 <= v <= MAX_COORD for v in values)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_int_list(value, length):
    return (
        isinstance(value, (list, tuple)) and len(value) == length and all(_is_int(v) for v in value)
    )


def default_state():
    """新装/数据不可用时的初始状态。"""
    return AppState(
        groups=[Group(name=DEFAULT_GROUP_NAME, items=["选项1", "选项2", "选项3"], drawn=[])],
        current_group=0,
        # 字体家族必须是 None（"数据未记录"）而不是 dataclass 默认的
        # Microsoft YaHei：文件不存在/被隔离走的就是这里，若非 None，
        # MainWindow.loadData 的 `state.x or self.x` 回退不触发，启动期
        # loadEmbeddedFont 选中的内嵌字体被丢弃，还会在 loadData 末尾的
        # saveData 里写盘固化——首启路径从此每次启动都从文件读回同一个
        # 默认值，与打包版字体不一致。
        ui_font_family=None,
        wheel_font_family=None,
    )
