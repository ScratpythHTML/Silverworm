# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Thread Wrapping Machine Control System
Build command: pyinstaller thread_wrapper.spec
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Application info
APP_NAME = "ThreadWrapperControl"
APP_VERSION = "1.0.0"

# Collect all necessary data
datas = []
hiddenimports = []

# Try to include Custom Widgets data if available
try:
    datas += collect_data_files('Custom_Widgets')
    hiddenimports += collect_submodules('Custom_Widgets')
except Exception:
    pass

a = Analysis(
    ['main_enhanced.py'],  # Use the enhanced version
    pathex=[],
    binaries=[],
    datas=datas + [
        ('style.json', '.'),
    ],
    hiddenimports=hiddenimports + [
        'PyQt6.QtCore',
        'PyQt6.QtGui', 
        'PyQt6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to True for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add path to .ico file if you have one
    version_file=None,
)

# For macOS, create an app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name=f'{APP_NAME}.app',
        icon=None,  # Add path to .icns file if you have one
        bundle_identifier='com.industrial.threadwrapper',
        info_plist={
            'CFBundleName': APP_NAME,
            'CFBundleDisplayName': 'Thread Wrapper Control',
            'CFBundleVersion': APP_VERSION,
            'CFBundleShortVersionString': APP_VERSION,
            'NSHighResolutionCapable': True,
        },
    )
