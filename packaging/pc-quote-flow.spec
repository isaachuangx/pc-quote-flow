# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（Task 10）：单文件 onefile、windowed（console=False）。

- 入口：packaging/entry.py 薄封装，复用 src/pc_quote_flow/__main__.py 的 main()
  （__main__.py 的包内相对导入无法被 PyInstaller 顶层脚本方式解析，见 entry.py 注释）。
- datas 为空：samples/ 虚构样例不打包进 exe（随仓库分发，UAT 直接打开）。
- --selftest：frozen 模式无 stdout，以退出码表达结果（0=通过），并把同样输出写
  %TEMP%/pc-quote-flow-selftest.log（ui/app.py run_selftest，R22⑦）。
- 构建：.venv/Scripts/python.exe packaging/build.py（产物 dist/pc-quote-flow.exe，
  build/ 与 dist/ 已被 .gitignore 排除，不入库）。
"""
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # packaging/ 的上一级＝仓库根
SRC = ROOT / "src"

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[],  # 样例不打包（红线1：虚构样例留在仓库 samples/，不嵌入 exe）
    hiddenimports=[
        "pc_quote_flow",
        "pc_quote_flow.ui.app",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "openpyxl",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="pc-quote-flow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed：无控制台；自检结果以退出码 + %TEMP% 日志表达
    icon=None,
)
