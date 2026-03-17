# PyInstaller spec for Kalien Farmer
# Build: pip install pyinstaller && pyinstaller kalien-farmer.spec
# Output: dist/kalien-farmer (single executable)

import sys
import os

block_cipher = None
is_windows = sys.platform == 'win32'
engine_binary = 'engine/kalien.exe' if is_windows else 'engine/kalien'

a = Analysis(
    ['kalien-farmer.py'],
    pathex=[],
    binaries=[(engine_binary, 'engine')] if os.path.exists(engine_binary) else [],
    datas=[
        ('kalien/dashboard/page.html', 'kalien/dashboard'),
        ('runner.py', '.'),
    ],
    hiddenimports=['kalien', 'kalien.runner', 'kalien.dashboard', 'kalien.dashboard.server'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest'],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='kalien-farmer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=None,
)
