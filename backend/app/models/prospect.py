"""
Схемы отбора клиентов.

Две оси держим раздельно и в схеме тоже: `demo` отвечает на вопрос «соберём ли
базу знаний автоматом», `verdict` — «стоит ли вообще писать». Смешивать их
нельзя: у компании без сайта demo=manual и при этом verdict=good.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ScanRequestItem(BaseModel):
    name: str
    website: Optional[str] = None
    reviews_count: Optional[int] = None
    rating: Optional[float] = None
    socials: list[str] = Field(default_factory=list)
    # Город и рубрики. Для компании без сайта модель видит только их — по ним
    # и узнаётся федеральный бренд.
    address: Optional[str] = None
    categories: list[str] = Field(default_factory=list)


class ScanRequest(BaseModel):
    items: list[ScanRequestItem] = Field(..., min_length=1, max_length=500)
    # Пересчитать, даже если вердикт уже лежит в кэше.
    refresh: bool = False


class ProspectVerdict(BaseModel):
    """Итог по одной компании. Причины — человеческим языком, для подсказки."""

    site: str                       # ключ склейки со строкой таблицы
    name: Optional[str] = None
    website: Optional[str] = None

    link_kind: str = "none"         # own | social | booking | builder | none
    demo: str = "manual"            # auto | manual
    verdict: str = "maybe"          # good | maybe | skip — ИИ-ассистент
    reasons: list[str] = Field(default_factory=list)
    # Вторая ось: сделать или переделать сайт. Своя оценка и свои причины —
    # компания без сайта плоха для автодемо и при этом лучший клиент здесь.
    web: str = "maybe"              # good | maybe | skip
    web_reasons: list[str] = Field(default_factory=list)

    duplicate_of: Optional[str] = None
    http_status: Optional[int] = None
    text_len: Optional[int] = None
    last_year: Optional[int] = None
    scale: Optional[str] = None     # одиночка | сеть | франшиза | не понял
    alive: Optional[str] = None     # живой | заброшен | не понял
    checked_at: Optional[datetime] = None


class ScanResponse(BaseModel):
    items: list[ProspectVerdict]
    # Сколько компаний реально прошло через модель — чтобы в интерфейсе было
    # видно, работала третья ступень или ключ не задан.
    classified: int = 0
    llm_enabled: bool = False
    # Сколько не получили вердикт из-за лимита запросов. Бесплатный тир
    # Gemini считает запросы в минуту и в сутки; упершись в него, компании
    # остаются с механической оценкой, а не отсеиваются.
    quota_hit: int = 0
