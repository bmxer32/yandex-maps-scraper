"""
Entry point для собранного PyInstaller exe.
Здесь настраиваем окружение ДО импорта uvicorn/playwright,
чтобы packaged exe нашёл bundled браузеры.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _setup_packaged_env() -> None:
    """В packaged режиме указываем Playwright где лежат браузеры."""
    if not getattr(sys, "frozen", False):
        return  # dev-режим — ничего не делаем

    base = Path(sys.executable).resolve().parent
    # Браузеры лежат рядом с exe в папке browsers/ms-playwright/<browser>
    ms_playwright = base / "browsers" / "ms-playwright"
    if ms_playwright.exists():
        # PLAYWRIGHT_BROWSERS_PATH указывает на ПАПКУ, ВНУТРИ которой ms-playwright
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(base / "browsers")

    # Рабочая папка — куда складывать SQLite и кэш
    data_dir = base / "data"
    data_dir.mkdir(exist_ok=True)
    os.environ.setdefault("DATABASE_URL",
                          f"sqlite+aiosqlite:///{data_dir / 'yascraper.db'}")


_setup_packaged_env()

# ЯВНЫЕ импорты — чтобы PyInstaller нашёл все зависимости.
# uvicorn.run("app.main:app") принимает строку, и статический анализатор
# PyInstaller её не раскрывает. Поэтому тащим app.main и все тяжёлые
# библиотеки явно сюда.
import uvicorn  # noqa: E402
import fastapi  # noqa: E402
import loguru  # noqa: E402
import pydantic  # noqa: E402
import sqlalchemy  # noqa: E402
import httpx  # noqa: E402
import playwright  # noqa: E402
import pandas  # noqa: E402
import openpyxl  # noqa: E402
import lxml  # noqa: E402
import sse_starlette  # noqa: E402

from app.main import app  # noqa: E402  — цепочка тащит все роуты/модели
from app.config import settings  # noqa: E402


def main() -> None:
    # Передаём сам объект app, а не строку — надёжнее и в runtime
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
