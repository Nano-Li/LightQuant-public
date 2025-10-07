# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('hands/*', 'LightQuant/hands'),
        ('protocols/*', 'LightQuant/protocols'),
        ('strategy/*.py', 'LightQuant/strategy'),
        ('strategy/BinanceAnalyzer/*', 'LightQuant/strategy/BinanceAnalyzer'),
        ('strategy/GateAnalyzer/*', 'LightQuant/strategy/GateAnalyzer'),
        ('tools/*', 'LightQuant/tools'),
        ('ui/*.py', 'LightQuant/ui'),
        ('ui/pictures/*.png', 'LightQuant/ui/pictures'),
        ('ui/stg_param_widgets/*', 'LightQuant/ui/stg_param_widgets'),
        ('gate_api.txt', 'LightQuant'),
        ('*.py', 'LightQuant')
    ],
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name='main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='main',
)
