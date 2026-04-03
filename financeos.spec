# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Finance OS — self-contained macOS .app"""

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
        ('samples', 'samples'),
    ],
    hiddenimports=[
        # Uvicorn
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # App routers
        'routers.dashboard',
        'routers.import_data',
        'routers.settings',
        'routers.ai',
        'routers.watchlist',
        'routers.xray',
        'routers.feed',
        # App services
        'services.csv_parser',
        'services.market',
        'services.portfolio',
        'services.ai_client',
        # Dependencies
        'multipart',
        'aiofiles',
        # pywebview native window
        'webview',
        'webview.platforms',
        'webview.platforms.cocoa',
        # macOS dock icon
        'AppKit',
        'Foundation',
        'objc',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'numpy.testing',
        'pytest',
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
    name='FinanceOS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='static/icon.icns',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FinanceOS',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Finance OS.app',
        icon='static/icon.icns',
        bundle_identifier='com.financeos.app',
        info_plist={
            'CFBundleName': 'Finance OS',
            'CFBundleDisplayName': 'Finance OS',
            'CFBundleVersion': '0.1.0',
            'CFBundleShortVersionString': '0.1.0',
            'CFBundleIconFile': 'icon.icns',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '10.15',
        },
    )
