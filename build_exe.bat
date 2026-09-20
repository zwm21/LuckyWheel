@echo off
chcp 65001 >nul
title 一键打包 LuckyWheel

:: 进入脚本所在目录
cd /d "%~dp0"

echo [*] 检查 Python 环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] 未找到 python，请先安装 Python 3.9+ 并加入 PATH。
    pause
    exit /b 1
)

echo [*] 检查 PyInstaller 是否安装...
pyinstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] PyInstaller 未安装，正在自动安装...
    pip install pyinstaller
    if %errorlevel% neq 0 (
        echo [X] 安装失败，请手动执行: pip install pyinstaller
        pause
        exit /b 1
    )
)

echo [*] 开始打包（字体可选，详见 assets\fonts\README.md）...
python "%~dp0scripts\build_exe.py"
if %errorlevel% neq 0 (
    echo [X] 打包失败，请检查上方错误信息。
    pause
    exit /b 1
)

echo.
echo [√] 打包完成，exe 文件位于: %~dp0dist\LuckyWheel.exe
echo.
pause
