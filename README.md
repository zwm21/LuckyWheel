# LuckyWheel 幸运大转盘

一个基于 PyQt6 的桌面抽签程序：多分组管理、手动或批量导入项目、转盘动画、
明暗主题、字体切换，所有数据自动保存到本地 JSON。

抽奖采用「先等概率选中目标，再把动画演到对应位置」的方式，落点均匀性不依赖
浮点物理模拟，也不会出现传统摩擦衰减式转盘的边缘偏差。

## 环境要求

- Python 3.9 或更高版本
- 依赖只有 PyQt6（`>=6.5,<7`）

## 运行方式

安装依赖：

```
pip install PyQt6
```

在项目目录下任选一种入口：

```
python main.py            # 旧入口，保留给既有快捷方式
python -m luckywheel      # 模块入口，与上一行完全等价
```

安装为包之后还可以直接使用 `luckywheel` 命令：

```
pip install .
luckywheel
```

开发模式（含测试与检查工具）建议安装 editable 依赖组：

```
pip install -e ".[dev]"
```

## 测试与代码检查

```
pytest -q                          # 全部测试（offscreen 运行，不会弹窗）
pytest tests/unit                  # 只跑算法层测试，零 Qt 依赖
ruff check . && ruff format --check .
python scripts/verify_gui.py --entry main   # GUI 冒烟：启动、抽奖、保存、关闭
```

测试目录按验证对象分层：`tests/unit` 对应 `core/` 算法，`tests/gui` 覆盖界面
行为（主题、布局、抽取、几何恢复），`tests/statistical` 对转盘落点做卡方检验，
`tests/characterization` 钉住重构前已确认的现状行为。`scripts/verify_gui.py` 会
把数据隔离到 `build/verify/`，不会读写你的真实 `wheel_data.json`。

## 打包 EXE

双击 `build_exe.bat`，或执行：

```
python scripts/build_exe.py
```

字体是可选的。仓库不内置任何字体文件（版权归属原作者），如需内嵌，把
`HYWenHei-65W.ttf` 之类的文件放入 `assets/fonts/`，打包脚本会自动检测并打入；
查找顺序由 `core/paths.py` 统一给出——打包版先看 exe 解包目录，源码运行时按
`assets/fonts/` → 程序所在目录，全部失败时回退为 Microsoft YaHei。不放字体不
影响功能，只影响界面与转盘文字的字体。

打包产物在 `dist/LuckyWheel.exe`，双击即可运行，无需 Python 环境。

## 项目结构

```
main.py                      兼容 wrapper：转发到 luckywheel.ui
src/luckywheel/
  core/                      零 Qt 依赖的纯算法
    models.py               条目与分组数据模型
    storage.py              JSON 读写、版本迁移、原子写与备份
    spin.py                 抽奖逻辑：等概率选中 + 旋转规划
    layout.py               转盘扇区几何与字号自适应
    paths.py                数据文件与字体的查找路径
  ui/
    main_window.py          主窗口：装配、数据读写、几何恢复与面板编排
    wheel.py                转盘控件（渲染、动画、命中判定）
    theme.py                明暗主题调色板与 QSS 模板
    palette.py              扇区默认配色池
    save_scheduler.py       保存去抖调度
    bootstrap.py            内嵌字体加载与非模态提示
    panels/                 左栏与抽取卡片的面板
      base.py               面板公共基类
      group_panel.py        分组增删改
      items_panel.py        项目编辑、拖拽排序、批量导入
      drawn_panel.py        抽出项目列表与操作
      settings_panel.py     字体、阴影、主题设置
      spin_panel.py         单次/批量抽取与结果展示
  app.py                    入口（create_window / run / main）
  __main__.py               python -m luckywheel 的入口
tests/                      见上文
scripts/
  build_exe.py              字体可选的打包脚本
  verify_gui.py             offscreen GUI 冒烟
  precommit_no_binaries.py  pre-commit 守卫：拒绝二进制入库
```

## 功能说明

- 支持手动添加、删除、编辑抽签项目，可批量导入（每行一个项目）。
- 项目列表支持拖拽排序和随机打乱。
- 多个分组独立管理，可重命名或删除分组。
- 转盘动画：点击转盘中心或下方按钮开始旋转，停止后显示选中结果。
- **不放回批量抽取**：设定抽取次数 N，自动连续抽 N 次，每次抽出的项目不再放回，
  抽完自动停止。
- 右下角字体选择框可更换界面与转盘文字的字体。
- 文字阴影开关可控制转盘文字是否带阴影。
- 明暗主题跟随系统或手动切换，列表高度可拖拽调整并记住。
- 所有设置和项目数据自动保存，窗口位置与大小在下次启动时恢复（会校验是否落在
  当前屏幕内）。

## 注意事项

- 数据文件 `wheel_data.json` 与程序存放在同一目录，建议备份以防丢失；保存采用
  临时文件 + 原子替换，并额外保留 `.bak`，文件损坏时不会被静默覆盖。
- 打包后的 EXE 可能被部分杀毒软件误报，请添加信任。
- 使用第三方字体请注意其授权条款。
