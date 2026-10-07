# WinLinAI PyInstaller Spec File
# Creates a standalone Windows executable
#
# Usage:
#   pyinstaller installer/winlinai.spec

# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

block_cipher = None

# Project root
project_root = Path(SPECPATH).parent

# Collect data files (themes, assets, knowledge data)
datas = [
    (str(project_root / 'themes'), 'themes'),
    (str(project_root / 'assets'), 'assets'),
    (str(project_root / 'src' / 'knowledge_data'), 'src/knowledge_data'),
]

# Hidden imports (modules that PyInstaller might miss)
hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'requests',
    'PIL',
    'PIL.Image',
    'yaml',
    'dotenv',
    'psutil',
    'tenacity',
    'jsonschema',
    'src.qt_app',
    'src.qt_chat',
    'src.qt_theme',
    'src.qt_tray',
    'src.qt_dialogs',
    'src.qt_conversation_actions',
    'src.windows_autostart',
    'src.windows_screenshot',
    'src.windows_system_actions',
    'src.windows_file_actions',
    'src.qt_file_dialogs',
    'src.platform.pwsh_output',
    'src.providers',
    'src.providers.base',
    'src.providers.openai_compatible',
    'src.providers.google',
    'src.providers.anthropic',
    'src.providers.cohere',
]

a = Analysis(
    [str(project_root / 'src' / 'app.py')],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'gi',  # GTK not needed on Windows
        'gtk',
        'cairo',
        'PyQt5',
        'PyQt6',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'tkinter',
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
    name='winlinai',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / 'assets' / 'io.github.linux_ai_assistant.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='winlinai',
)
