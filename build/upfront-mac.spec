# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Up Front Shop (macOS).
#
# Build with:
#     pyinstaller --clean --noconfirm build/upfront-mac.spec
#
# Produces:   dist/UpFrontShop.app           (the app bundle)
#             dist/UpFrontShop/              (the raw collected tree)

from PyInstaller.utils.hooks import collect_submodules
import os

block_cipher = None

# No win32 imports on macOS.
hidden = (
    collect_submodules("PySide6")
    + collect_submodules("reportlab")
)

a = Analysis(
    ["../main.py"],
    pathex=[".."],
    binaries=[],
    # Ship the resources/ folder next to the entrypoint so bundled_resource_dir()
    # can find it inside the .app/Contents/Resources.
    datas=[("../resources", "resources")],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "numpy", "pandas", "scipy",
        "PyQt5", "PyQt6", "IPython", "jupyter",
        "win32print", "win32api", "pywin32",
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
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,            # enables drag-and-drop onto the dock icon
    target_arch="arm64",            # Apple Silicon build; workflow sets this
    codesign_identity=None,
    entitlements_file=None,
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

# Wrap into a proper .app bundle so Finder treats it as an application.
app = BUNDLE(
    coll,
    name="UpFrontShop.app",
    # If a resources/app-icon.icns exists we use it; otherwise PyInstaller
    # supplies a default rocket icon. Either is fine.
    icon=None,
    bundle_identifier="com.upfrontauto.upfrontshop",
    info_plist={
        "CFBundleName": "Up Front Shop",
        "CFBundleDisplayName": "Up Front Shop",
        "CFBundleShortVersionString": "1.4.0",
        "CFBundleVersion": "1.4.0",
        "NSHighResolutionCapable": True,
        # We never listen on the network unsolicited, but printing via CUPS
        # counts as a local network thing; this calms Gatekeeper on newer macOS.
        "LSApplicationCategoryType": "public.app-category.business",
        "NSPrincipalClass": "NSApplication",
        "NSRequiresAquaSystemAppearance": False,  # allow dark mode
    },
)
