# PyInstaller spec for Kalien Farmer
# Build: pip install pyinstaller && pyinstaller kalien-farmer.spec
# Output: dist/kalien-farmer (single executable)

import sys
import os

block_cipher = None
is_windows = sys.platform == 'win32'
engine_binary = 'engine/kalien.exe' if is_windows else 'engine/kalien'

# Collect engine binary + CUDA runtime DLLs if present
extra_binaries = []
if os.path.exists(engine_binary):
    extra_binaries.append((engine_binary, 'engine'))
if is_windows:
    import glob
    cuda_path = os.environ.get('CUDA_PATH', '')
    if cuda_path:
        cuda_bin = os.path.join(cuda_path, 'bin')
        for pattern in ['cudart64_*.dll', 'nvrtc64_*.dll', 'nvrtc-builtins64_*.dll']:
            for m in glob.glob(os.path.join(cuda_bin, pattern)):
                extra_binaries.append((m, '.'))

a = Analysis(
    ['kalien-farmer.py'],
    pathex=[],
    binaries=extra_binaries,
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
