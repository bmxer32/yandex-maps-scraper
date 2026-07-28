"""
Точка входа FastAPI.
Запуск (из папки backend):
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from .api.search import router as scraper_router
from .config import settings
from .core.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Старт/шатдаун: поднимаем БД."""
    logger.info("init DB…")
    await init_db()
    logger.info("Yandex.Maps scraper backend ready on http://{}:{}",
                settings.host, settings.port)
    yield
    logger.info("shutdown.")


app = FastAPI(
    title="Yandex Maps Scraper",
    description="Сбор данных с Яндекс.Карт: сфера, контакты, сайты, email.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS для фронтенда на dev-портах (любой localhost-порт разрешён)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scraper_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
