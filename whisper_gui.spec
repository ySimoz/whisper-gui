# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification file for bundling Whisper GUI across Windows, macOS, and Linux."""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

# Collect all resources and data files for critical packages
docx_datas = collect_data_files('docx')
whisper_datas = collect_data_files('faster_whisper')

# Collect ctranslate2 dynamic libraries and assets
ctranslate2_datas, ctranslate2_binaries, ctranslate2_hiddenimports = collect_all('ctranslate2')

# Collect av (PyAV) submodules
av_datas, av_binaries, av_hiddenimports = collect_all('av')

datas = []
datas += docx_datas
datas += whisper_datas
datas += ctranslate2_datas
datas += av_datas

binaries = []
binaries += ctranslate2_binaries
binaries += av_binaries

# If local ffmpeg/ffprobe binaries are in ./bin, include them
project_root = Path.cwd()
local_bin_dir = project_root / 'bin'
if local_bin_dir.is_dir():
    for f in local_bin_dir.iterdir():
        if f.is_file():
            binaries.append((str(f), 'bin'))

hiddenimports = [
    'whisper_gui',
    'whisper_gui.platform_utils',
    'whisper_gui.audio_utils',
    'whisper_gui.docx_exporter',
    'whisper_gui.models',
    'whisper_gui.transcriber',
    'whisper_gui.llm_cleaner',
    'whisper_gui.worker',
    'whisper_gui.ui',
    'whisper_gui.ui.theme',
    'whisper_gui.ui.main_window',
    'whisper_gui.ui.range_selector',
    'whisper_gui.ui.settings_panel',
    'whisper_gui.ui.llm_panel',
    'whisper_gui.ui.track_list_widget',
    'whisper_gui.ui.transcript_view',
    'faster_whisper',
    'ctranslate2',
    'docx',
    'PySide6',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'huggingface_hub',
    'tokenizers',
    'onnxruntime',
    'numpy',
] + ctranslate2_hiddenimports + av_hiddenimports

a = Analysis(
    ['main.py'],
    pathex=['src', '.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'torch'],
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
    name='WhisperGUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Windowed GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WhisperGUI',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='WhisperGUI.app',
        icon=None,
        bundle_identifier='com.whispergui.app',
        info_plist={
            'CFBundleName': 'Whisper Transcriber',
            'CFBundleDisplayName': 'Whisper Transcriber',
            'CFBundleIdentifier': 'com.whispergui.app',
            'CFBundleVersion': '1.0.0',
            'CFBundleShortVersionString': '1.0.0',
            'NSHighResolutionCapable': 'True',
            'NSRequiresAquaSystemAppearance': 'False',
        },
    )
