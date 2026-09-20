#!/usr/bin/env python
"""GUI 冒烟验证：在 offscreen 平台完整走一遍应用生命周期。

用途：重构每个阶段跑一次，确认程序仍能启动、构建界面、切换主题、
执行旋转与批量抽取、保存数据并正常退出。运行方式（仓库根目录）：

    python scripts/verify_gui.py --entry main     # 旧入口 main.py
    python scripts/verify_gui.py --entry module   # 新入口 python -m luckywheel

截图输出到 build/verify/*.png，可直接打开检查。
退出码：0 全部通过，1 存在失败项。
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyqt6")

OUT_DIR = ROOT / "build" / "verify"
SANDBOX_DATA = OUT_DIR / "wheel_data.json"
SEED_DATA = OUT_DIR / "wheel_data.seed.json"
SPIN_TIMEOUT = 15.0


def isolate_data_file(window):
    """把窗口的数据文件切到沙箱路径，冒烟绝不写用户的真实 wheel_data.json。

    首次运行时把当前真实数据复制为 seed（只读一次，之后冒烟不再触碰它），
    之后每次冒烟都从 seed 恢复沙箱副本。构造窗口时 loadData 只读不写
    （读取成功不会触发写回），所以真实文件不会被修改。
    """
    if not SEED_DATA.exists():
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        real = Path(window.data_file)
        if real.exists():
            SEED_DATA.write_bytes(real.read_bytes())
        else:
            SEED_DATA.write_text("{}", encoding="utf-8")
    SANDBOX_DATA.write_bytes(SEED_DATA.read_bytes())
    window.data_file = str(SANDBOX_DATA)


def make_app():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def check(name, fn, failures):
    try:
        fn()
        print(f"  [ok] {name}")
    except Exception as exc:  # noqa: BLE001 - 冒烟脚本须汇总所有失败而非中断
        failures.append(name)
        print(f"  [FAIL] {name}: {type(exc).__name__}: {exc}")


def wait(predicate, timeout, interval=0.005, app=None):
    """轮询 predicate 直至为真；必须周期性泵事件循环，否则 QTimer 不触发。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if app is not None:
            app.processEvents()
        if predicate():
            return True
        time.sleep(interval)
    return False


def load_window(entry, app):
    if entry == "main":
        import main as legacy

        return legacy.MainWindow()
    from luckywheel.app import run

    return run(app)


def verify(window, app):
    failures = []

    def shot(name):
        (OUT_DIR / name).parent.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(OUT_DIR / name))

    def require(cond, msg):
        if not cond:
            raise AssertionError(msg)

    print("== 生命周期 ==")
    check("窗口已创建且有标题", lambda: require(bool(window.windowTitle()), "标题为空"), failures)
    window.resize(1100, 720)
    window.show()
    app.processEvents()
    check("分组下拉有选项", lambda: require(window.group_combo.count() > 0, "无分组"), failures)
    check("转盘已装配项目", lambda: require(len(window.wheel.items) > 0, "转盘为空"), failures)
    check(
        "列表与转盘项目一致",
        lambda: require(window.list_widget.count() == len(window.wheel.items), "数量不一致"),
        failures,
    )
    shot("startup.png")

    print("== 主题切换 ==")
    for idx, label in enumerate(("浅色", "深色", "跟随系统")):

        def switch(i=idx, lb=label):
            window.theme_combo.setCurrentIndex(i)
            app.processEvents()

        check(f"切换到{label}", switch, failures)
        shot(f"theme_{label}.png")

    print("== 单次旋转 ==")

    def single_spin():
        items = window.groups[window.current_group_index]["items"]
        window.wheel.setItems(items or ["A", "B", "C"])
        # 冒烟加速：动画时长除以该系数，数秒内跑完
        window.wheel.speed_scale = 40.0
        window.wheel.startSpin()
        require(wait(lambda: not window.wheel.spinning, SPIN_TIMEOUT, app=app), "旋转超时")
        require(bool(window.result_label.text()), "结果标签为空")

    check("旋转到停止并显示结果", single_spin, failures)
    shot("after_spin.png")

    print("== 批量抽取 ==")

    def batch_spin():
        window.wheel.speed_scale = 20.0
        n = min(3, len(window.groups[window.current_group_index]["items"]))
        window.batch_spinbox.setValue(max(1, n))
        before = len(window.groups[window.current_group_index]["items"])
        if before == 0:
            return  # 空分组无可抽，跳过
        window.startBatchSpin()
        require(
            wait(
                lambda: window.batch_remaining <= 0 and not window.btn_stop_batch.isEnabled(),
                SPIN_TIMEOUT * 6,
                app=app,
            ),
            "批量抽取超时",
        )
        after = len(window.groups[window.current_group_index]["items"])
        drawn = len(window.groups[window.current_group_index].get("drawn_items", []))
        require(after < before, f"项目数未减少：{before} -> {after}")
        require(drawn > 0, "抽出列表为空")

    check("不放回批量抽取", batch_spin, failures)
    shot("after_batch.png")

    print("== 数据 ==")

    def roundtrip():
        window.saveData()
        with open(window.data_file, encoding="utf-8") as f:
            data = json.load(f)
        require("groups" in data, "数据文件缺少 groups")
        require(data["groups"][0]["items"] is not None, "items 为 None")

    check("保存后数据文件可读回", roundtrip, failures)

    print("== 关闭 ==")
    check("closeEvent 不抛异常", window.close, failures)
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry", choices=["main", "module"], default="main")
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    app = make_app()
    print(f"== GUI smoke ({args.entry}) ==")
    t0 = time.perf_counter()
    window = load_window(args.entry, app)
    print(f"  启动耗时: {(time.perf_counter() - t0) * 1000:.0f} ms")
    isolate_data_file(window)
    window.loadData()
    print(f"  数据文件已隔离: {window.data_file}")

    failures = verify(window, app)
    if failures:
        print(f"\n== {len(failures)} 项失败: {', '.join(failures)} ==")
        return 1
    print("\n== 全部通过 ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
