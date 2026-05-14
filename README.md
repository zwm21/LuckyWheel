# LuckyWheel 幸运大转盘

一个基于 PyQt5 的桌面抽签程序，支持多分组管理、手动编辑项目、转盘动画和字体切换。

## 技术栈

- Python 3.10
- PyQt5
- PyInstaller（用于打包）

## 运行方式

### 安装依赖

Python 版本要求 3.8 及以上。依赖包仅需 PyQt5，执行以下命令安装：

```
pip install PyQt5
```

若需自行打包 EXE，还需安装 PyInstaller：

```
pip install pyinstaller
```

### 从源码运行

在项目目录下打开终端，执行：

```
python main.py
```

### 运行打包程序

已打包好的 `LuckyWheel.exe` 直接双击即可运行。打包方法：

1. 确保已安装 PyInstaller，并将字体文件（如 `HYWenHei-65W.ttf`）放入项目目录（可选）。
2. 双击 `build_exe.bat` 或执行以下命令：

```
pyinstaller --onefile --windowed --name="LuckyWheel" --add-data "HYWenHei-65W.ttf;." main.py
```

打包成功后，可执行文件位于 `dist` 文件夹。

## 功能说明

- 支持手动添加、删除、编辑抽签项目，可批量导入（每行一个项目）。
- 项目列表支持拖拽排序和随机打乱。
- 多个分组独立管理，可重命名或删除分组，各分组数据保存在 `wheel_data.json` 中。
- 转盘动画：点击转盘中心或下方按钮开始旋转，停止后显示选中结果。
- 右下角字体选择框可更换界面与转盘文字的字体。
- 文字阴影开关可控制转盘文字是否带阴影。
- 所有设置和项目数据会自动保存，下次启动恢复。

## 注意事项

- 程序默认字体为“汉仪文黑-65W”，若系统中未安装此字体，将回退为“Microsoft YaHei”。如使用自备字体文件（`HYWenHei-65W.ttf`），请将其放在与 `main.py` 同级目录，并注意字体版权。
- 打包后的 EXE 文件可能被部分杀毒软件误报，请添加信任。
- 数据文件 `wheel_data.json` 与程序存放于同一目录，建议备份以防丢失。