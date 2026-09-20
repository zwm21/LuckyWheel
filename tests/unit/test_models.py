"""core.models：AppState/Group 序列化与收敛规则（零 Qt 依赖）。"""

import pytest

from luckywheel.core.models import SCHEMA_VERSION, AppState, Group, default_state


class TestGroup:
    def test_roundtrip(self):
        g = Group(name="组", items=["a", "b"], drawn=["c"])
        assert Group.from_dict(g.to_dict()) == g

    def test_from_dict_missing_keys(self):
        g = Group.from_dict({"name": "只有名字"})
        assert g.items == [] and g.drawn == []


class TestAppState:
    def test_to_dict_carries_version(self):
        assert default_state().to_dict()["version"] == SCHEMA_VERSION

    def test_roundtrip_default(self):
        state = default_state()
        assert AppState.from_dict(state.to_dict()) == state

    def test_roundtrip_full(self):
        state = AppState(
            groups=[Group("g1", ["a"], ["b"]), Group("g2", [], [])],
            current_group=1,
            ui_font_family="Font A",
            ui_font_size=11,
            wheel_font_family="Font B",
            wheel_font_size=20,
            shadow_enabled=False,
            window_geometry=[1, 2, 800, 600],
            splitter_sizes=[200, 500],
            list_height=222,
            drawn_list_height=150,
            batch_spin_count=5,
            theme="dark",
        )
        restored = AppState.from_dict(state.to_dict())
        assert restored == state

    def test_legacy_font_family_split(self):
        """旧格式 font_family 同时喂给 ui 与转盘字体。"""
        state = AppState.from_dict({"font_family": "旧字体", "groups": []})
        assert state.ui_font_family == "旧字体"
        assert state.wheel_font_family == "旧字体"

    def test_clamp_current_group_out_of_range(self):
        state = AppState.from_dict({"groups": [{"name": "g"}], "current_group": 7})
        assert state.current_group == 0

    def test_clamp_bad_theme(self):
        assert AppState.from_dict({"theme": "彩虹"}).theme == "light"

    def test_clamp_bad_font_size(self):
        assert AppState.from_dict({"ui_font_size": "九号"}).ui_font_size == 9
        assert AppState.from_dict({"wheel_font_size": -3}).wheel_font_size == 0

    def test_clamp_bad_window_geometry(self):
        """几何坏值收敛为 None，而不是带进 Qt 的 setGeometry。"""
        assert AppState.from_dict({"window_geometry": [1, 2]}).window_geometry is None
        assert AppState.from_dict({"window_geometry": "0,0,100,100"}).window_geometry is None
        assert AppState.from_dict({"window_geometry": [1, 2, 3, True]}).window_geometry is None
        good = AppState.from_dict({"window_geometry": [-8, 40, 1297, 721]})
        assert good.window_geometry == [-8, 40, 1297, 721]

    def test_clamp_bad_splitter_sizes(self):
        assert AppState.from_dict({"splitter_sizes": [264]}).splitter_sizes is None
        assert AppState.from_dict({"splitter_sizes": ["a", "b"]}).splitter_sizes is None
        good = AppState.from_dict({"splitter_sizes": [264, 1011]})
        assert good.splitter_sizes == [264, 1011]

    def test_clamp_bad_heights(self):
        assert AppState.from_dict({"list_height": -5}).list_height == 200
        assert AppState.from_dict({"drawn_list_height": None}).drawn_list_height == 120

    def test_clamp_bad_font_family(self):
        """字体家族会直接传给 QFont()，非字符串必须收敛。"""
        assert AppState.from_dict({"ui_font_family": 42}).ui_font_family == "Microsoft YaHei"
        assert AppState.from_dict({"wheel_font_family": ["a"]}).wheel_font_family == "Microsoft YaHei"

    def test_default_state_has_one_group(self):
        state = default_state()
        assert len(state.groups) == 1
        assert state.groups[0].items == ["选项1", "选项2", "选项3"]

    def test_current_group_object(self):
        state = default_state()
        assert state.current_group_object is state.groups[0]
        assert AppState(groups=()).current_group_object is None


@pytest.mark.parametrize("bad", [True, "x", 3.5])
def test_clamp_bad_batch_count(bad):
    assert AppState.from_dict({"batch_spin_count": bad}).batch_spin_count == 3
