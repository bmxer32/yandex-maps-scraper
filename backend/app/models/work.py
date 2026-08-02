"""
Схемы раздела «В работе».

Запись состоит из двух половин, и смешивать их нельзя:

* **карточка** — копия данных из Яндекса, её обновляет парсинг;
* **работа** — статус, заметка, напоминание. Это написал человек, и никакой
  повторный парсинг права их трогать не имеет.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

# Порядок важен: в таком виде статусы идут в фильтре над списком.
WORK_STATUSES = ("new", "written", "replied", "client", "refused")

STATUS_LABELS = {
    "new": "Новый",
    "written": "Написал",
    "replied": "Ответили",
    "client": "Клиент",
    "refused": "Отказ",
}


class WorkItem(BaseModel):
    """Одна контора в работе."""

    key: str
    permalink: Optional[str] = None

    name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    phones: list[str] = Field(default_factory=list)
    website: Optional[str] = None
    websites: list[str] = Field(default_factory=list)
    email: Optional[str] = None
    socials: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    verdict: Optional[str] = None
    web: Optional[str] = None

    status: str = "new"
    note: Optional[str] = None
    remind_at: Optional[datetime] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class WorkAddRequest(BaseModel):
    """Добавить конторы в работу — звёздочкой из таблицы, по одной или пачкой."""

    # Организации приходят целиком: раздел не должен зависеть от того,
    # сохранилась ли выгрузка, из которой контору взяли.
    items: list[dict] = Field(..., min_length=1, max_length=500)


class WorkUpdateRequest(BaseModel):
    """Правка того, что ведёт человек. Поля необязательные — что прислали, то и меняем."""

    status: Optional[str] = None
    note: Optional[str] = None
    # Пустая строка — снять напоминание; None — не трогать.
    remind_at: Optional[datetime] = None
    clear_remind: bool = False
