"""
Схемы для персональных демо ИИ-ассистента (интеграция с kb_assistant).
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DemoConfig(BaseModel):
    """Состояние интеграции — UI по нему решает, что показывать.

    enabled — адрес и ключ заданы (иначе колонки «Демо» нет совсем);
    ready   — kb_assistant уже отвечает. Docker-стек поднимается около минуты,
              всё это время enabled=true, ready=false.
    """
    enabled: bool
    ready: bool = False
    bot_username: Optional[str] = None
    max_pages: int = 30


class DemoRequestItem(BaseModel):
    """Одна организация, которой делаем демо."""
    name: str = Field(..., description="Название организации")
    website: str = Field(..., description="Сайт — его и краулим в базу знаний")


class DemoProvisionRequest(BaseModel):
    items: list[DemoRequestItem] = Field(..., min_length=1, max_length=100)
    max_pages: Optional[int] = Field(None, ge=1, le=200)


class DemoStatus(BaseModel):
    """Состояние одного демо: и для ответа на создание, и для опроса."""
    name: Optional[str] = None
    website: Optional[str] = None
    slug: str
    link: Optional[str] = None
    # pending | crawling | ready | failed | error
    # "error" — сбой на стороне парсера (kb_assistant не ответил), не статус демо
    status: str
    error: Optional[str] = None
    pages_indexed: int = 0
    opened_count: int = 0
    message_count: int = 0


class DemoProvisionResponse(BaseModel):
    items: list[DemoStatus]


class DemoStatusResponse(BaseModel):
    items: list[DemoStatus]
