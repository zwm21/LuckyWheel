"""启动期辅助：内嵌字体加载与「延后到事件循环」的非模态提示。

为什么单独一个模块：MainWindow 在构造阶段（loadData、__init__）就要
提示用户，而模态框会把启动流程连同自动化脚本一起卡死。提示实现收敛在
这里，测试只需替换本模块的 `show_info` 一个名字就能把弹窗换成记录器
（tests/conftest.py 的 no_modal_dialogs）。
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QMessageBox

from luckywheel.core import paths


def loadEmbeddedFont(font_filename):
    """加载内嵌字体并返回族名，失败返回 None。

    查找顺序收敛在 core.paths.font_candidates（frozen 解包目录 → 仓库
    assets/fonts → 程序旁边），此处不再另写一套：源码运行与打包版因此
    用同一份字体，字号求解测得的度量才与生产一致。
    """
    font_path = paths.find_embedded_font(font_filename)
    if font_path is None:
        return None
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id != -1:
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            return families[0]  # 返回族名
    return None


def show_info(parent, title, text):
    """非模态信息框。

    必须是**非模态**：这些提示在启动阶段（loadData / __init__）就会触发，
    模态框会把启动流程乃至自动化脚本一起卡死。

    生命周期：以 parent 为属主，Qt 负责随窗口销毁；关闭时自行删除。
    """
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.setWindowModality(Qt.WindowModality.NonModal)
    box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    box.show()


def notify(parent, message, title="提示"):
    """延后到事件循环再弹提示。

    直接弹会重入事件循环（QMessageBox.show 也要等事件循环才显示），
    在保存失败这类"正在处理一件事"的上下文里表现为卡顿或递归；
    singleShot(0) 让当前调用先走完。窗口已销毁时定时器回调会拿到
    失效的 C++ 对象，这里吞掉 RuntimeError。
    """

    def popup():
        try:
            show_info(parent, title, message)
        except RuntimeError:
            pass  # 窗口在定时器触发前已被销毁

    QTimer.singleShot(0, popup)
