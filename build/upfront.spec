# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Up Front Shop (Windows).
#
# Build with:
#     pyinstaller --clean --noconfirm build\upfront.spec
#
# Produces:   dist\UpFrontShop\UpFrontShop.exe   (+ supporting files)

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hidden = (
    collect_submodules("PySide6")
    + collect_submodules("reportlab")
    + ["win32print", "win32api"]
)

a = Analysis(
    ["..\\main.py"],
    pathex=[".."],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "numpy", "pandas", "scipy",
        "PyQt5", "PyQt6", "IPython", "jupyter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="UpFrontShop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                  # no black console window on launch
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                       # replace with .ico if you have one
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="UpFrontShop",
)
