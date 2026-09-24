"""GUI：首启路径的字体回退。

批次 A 修了「数据文件已存在但没有字体字段」这一种情况（parse_state 缺键
给 None），但漏了文件不存在/被隔离时走的 default_state()——其字体家族
取 dataclass 默认值 Microsoft YaHei（非 None），loadData 的
`state.x or self.x` 回退不触发，启动期 loadEmbeddedFont 选中的内嵌字体
被丢弃，还会在 loadData 末尾的 saveData 里写盘固化。这里把整条链钉住。
"""

import json

import pytest

from luckywheel.ui import bootstrap


def test_fresh_install_keeps_embedded_font(qtbot, window, tmp_path):
    """数据文件不存在时构造的窗口必须保留内嵌字体，并原样落盘。"""
    embedded = bootstrap.loadEmbeddedFont("HYWenHei-65W.ttf")
    if embedded is None:
        pytest.skip("assets/fonts/ 下无内嵌字体，回退链无从验证")
    assert window.ui_font_family == embedded
    assert window.wheel_font_family == embedded

    # 回退值被写盘：下次启动从文件读回同一族名，不会固化成默认值
    window.flushSave()
    data = json.loads((tmp_path / "wheel_data.json").read_text(encoding="utf-8"))
    assert data["ui_font_family"] == embedded
    assert data["wheel_font_family"] == embedded
