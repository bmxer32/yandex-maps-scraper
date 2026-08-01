"""
Pydantic-схемы: запросы, ответы, внутренние сущности.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


# ---------------------------------------------------------------------------
# География
# ---------------------------------------------------------------------------
class GeoLevel(str, Enum):
    """Уровень локации в каскаде."""
    COUNTRY = "country"
    REGION = "region"          # область / край / республика
    CITY = "city"
    DISTRICT = "district"      # район города
    METRO = "metro"            # станция метро


class GeoNode(BaseModel):
    """Узел географического дерева (для каскадных селекторов в UI)."""
    id: str                    # стабильный идентификатор (slug)
    name: str                  # «Москва», «Адмиралтейский район»
    level: GeoLevel
    parent_id: Optional[str] = None
    # Текстовая подсказка для поиска на Яндекс.Картах
    search_hint: str           # например «Москва, район Адмиралтейский»


# ---------------------------------------------------------------------------
# Запрос поиска
# ---------------------------------------------------------------------------
class SearchRequest(BaseModel):
    """Входная форма с UI."""
    category: str = Field(..., description="Сфера/рубрика: 'стоматологии', 'автосервисы'")
    # Точечный поиск: название, адрес, телефон или ссылка на карточку в
    # Яндекс.Картах. Задан — гео и рубрика не используются, запрос уходит
    # как есть. Нужен, когда клиент уже известен и надо просто добавить его
    # в список, а не собирать всю нишу целиком.
    raw_query: Optional[str] = Field(None, description="Точечный поиск по тексту или ссылке")
    country_id: str = Field("ru", description="Страна, по умолчанию Россия")
    region_id: Optional[str] = Field(None, description="Область / край")
    city_id: Optional[str] = Field(None, description="Город")
    district_id: Optional[str] = Field(None, description="Район (для крупных городов)")
    metro_id: Optional[str] = Field(None, description="Станция метро")
    limit: int = Field(500, ge=1, le=1000, description="Сколько карточек собрать")
    # Этап 2: открывать карточки организаций на Яндексе за сайтами и соцсетями.
    # Медленный (~2 сек на карточку), но без него сайтов не будет совсем.
    fetch_websites: bool = Field(True, description="Открывать карточки за сайтами")
    # Этап 3: второй проход по сайтам организаций (httpx) за email и соцсетями.
    enrich_sites: bool = Field(True, description="Собирать email и соцсети с сайтов")


# ---------------------------------------------------------------------------
# Карточка организации (итоговая)
# ---------------------------------------------------------------------------
class Organization(BaseModel):
    """Одна строка результата."""
    name: str
    address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    phone: Optional[str] = None
    # Все телефоны карточки, с городом: «+7 (988) 508-84-88 (Сочи)». У сетевых
    # салонов первым идёт московский номер, а звонить нужно в местный.
    phones: list[str] = Field(default_factory=list)
    website: Optional[str] = None         # None => сайта нет (важный кейс для UI)
    # Все сайты компании в порядке карточки. Их бывает несколько, и решать
    # «нужен ли сайт» по одному нельзя: у салона может быть нормальный сайт
    # и вторая ссылка на страницу записи.
    websites: list[str] = Field(default_factory=list)
    email: Optional[str] = None
    socials: list[str] = Field(default_factory=list)  # vk, telegram, instagram...
    hours: Optional[str] = None
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    categories: list[str] = Field(default_factory=list)
    # Внутреннийpermalink Яндекса (для дедупликации и кэша)
    permalink: Optional[str] = None


# ---------------------------------------------------------------------------
# Состояние фоновой задачи
# ---------------------------------------------------------------------------
class TaskStage(str, Enum):
    QUEUED = "queued"
    PARSING_LIST = "parsing_list"          # листаем выдачу Яндекса
    PARSING_CARDS = "parsing_cards"        # открываем карточки за телефоном/сайтом
    ENRICHING_SITES = "enriching_sites"    # второй проход по сайтам организаций
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskProgress(BaseModel):
    """Снапшот прогресса, который стримится в UI."""
    task_id: str
    stage: TaskStage
    processed: int = 0
    total: int = 0
    found_with_website: int = 0
    found_without_website: int = 0
    message: str = ""
    started_at: datetime
    updated_at: datetime
    error: Optional[str] = None

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 0.0
        return round(100.0 * self.processed / self.total, 1)


class TaskResult(BaseModel):
    """Финальный ответ по задаче."""
    task_id: str
    progress: TaskProgress
    organizations: list[Organization]
    search: SearchRequest
