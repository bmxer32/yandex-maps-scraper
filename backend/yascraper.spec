# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec для backend Yandex Maps Scraper.
Собирает onedir (не onefile — Playwright не дружит с onefile).
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Скрытые импорты — uvicorn/playwright/fastapi любят ленивый импорт
hiddenimports = []
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("fastapi")
hiddenimports += collect_submodules("starlette")
hiddenimports += collect_submodules("pydantic")
hiddenimports += collect_submodules("pydantic_core")
hiddenimports += collect_submodules("playwright")
hiddenimports += collect_submodules("playwright.async_api")
hiddenimports += [
    "aiosqlite",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "anyio._backends._asyncio",
    "sse_starlette",
    "sse_starlette.sse",
    "httpx",
    "httpx._transports",
    "httpx._transports.default",
    "lxml",
    "lxml._elementpath",
    "pandas",
    "openpyxl",
    "email_validator",
    "dns.resolver",
]

# Дата-файлы — код и ассеты
datas = []
datas += collect_data_files("playwright")
datas += [("app", "app")]
datas += [("data", "data")] if __import__("os").path.isdir("data") else []

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Отсекаем лишнее — уменьшает размер
        "tkinter",
        "matplotlib",
        "scipy",
        "PIL",
        "pytest",
        "IPython",
        "notebook",
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
    name="yascraper-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                    # UPX ломает некоторые .dll
    console=True,                 # консоль для логов (скрыта в Electron)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                    # иконку добавим позже
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="yascraper-backend",
)
