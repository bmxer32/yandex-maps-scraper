"""
Асинхронная SQLAlchemy + SQLite.
Храним историю поисков и кэш карточек по permalink Яндекса,
чтобы при повторных запросах не дёргать карты лишний раз.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..config import settings


class Base(DeclarativeBase):
    pass


class OrganizationRow(Base):
    """Кэш одной организации (уникальна по permalink Яндекса)."""
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    permalink: Mapped[Optional[str]] = mapped_column(String, index=True, unique=True)
    name: Mapped[str] = mapped_column(String, index=True)
    address: Mapped[Optional[str]] = mapped_column(Text)
    lat: Mapped[Optional[float]] = mapped_column(Float)
    lon: Mapped[Optional[float]] = mapped_column(Float)
    phone: Mapped[Optional[str]] = mapped_column(String)
    website: Mapped[Optional[str]] = mapped_column(Text)
    email: Mapped[Optional[str]] = mapped_column(Text)
    # соцсети и рубрики храним как JSON-массивы
    socials: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    categories: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    hours: Mapped[Optional[str]] = mapped_column(Text)
    rating: Mapped[Optional[float]] = mapped_column(Float)
    reviews_count: Mapped[Optional[int]] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class SiteVerdictRow(Base):
    """Кэш вердикта по сайту компании (ключ — домен без схемы и www).

    Оценка стоит запроса к сайту и вызова модели, а один и тот же бизнес
    попадается в разных выгрузках. Держим результат, чтобы повторное
    сканирование не платило за него снова.
    """
    __tablename__ = "site_verdicts"

    site: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String)
    website: Mapped[Optional[str]] = mapped_column(Text)
    link_kind: Mapped[Optional[str]] = mapped_column(String)   # own|social|booking|builder|none
    demo: Mapped[Optional[str]] = mapped_column(String)        # auto|manual
    verdict: Mapped[Optional[str]] = mapped_column(String)     # good|maybe|skip
    reasons: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    # Вторая ось: сделать или переделать сайт.
    web: Mapped[Optional[str]] = mapped_column(String)
    web_reasons: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    duplicate_of: Mapped[Optional[str]] = mapped_column(String)
    http_status: Mapped[Optional[int]] = mapped_column(Integer)
    text_len: Mapped[Optional[int]] = mapped_column(Integer)
    last_year: Mapped[Optional[int]] = mapped_column(Integer)
    scale: Mapped[Optional[str]] = mapped_column(String)
    alive: Mapped[Optional[str]] = mapped_column(String)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class SearchHistoryRow(Base):
    """Завершённая выгрузка целиком: запрос, результат и счётчики.

    Задачи живут в памяти, поэтому после перезапуска программы результат
    пропадал и приходилось парсить заново — а это минуты работы браузера и
    лишняя нагрузка на Яндекс. Организации храним прямо здесь: тридцать-
    тысяча карточек это сотни килобайт, SQLite такое держит спокойно, а
    раскладывать их по таблицам ради истории просмотров незачем.
    """
    __tablename__ = "search_history"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # task_id
    request_json: Mapped[str] = mapped_column(Text)            # сериализованный SearchRequest
    found_count: Mapped[int] = mapped_column(Integer, default=0)
    # Разбор запроса для списка — чтобы не парсить JSON ради подписи строки.
    category: Mapped[Optional[str]] = mapped_column(String)
    location: Mapped[Optional[str]] = mapped_column(String)
    with_website: Mapped[int] = mapped_column(Integer, default=0)
    organizations: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Engine / session
# ---------------------------------------------------------------------------
engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)
AsyncSessionLocal = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def _add_missing_columns(conn) -> None:
    """Досоздать колонки, появившиеся после того, как таблица уже была создана.

    Alembic в парсере нет, а `create_all` существующие таблицы не трогает:
    добавив поле в модель, получаешь «no such column» на живой базе. SQLite
    умеет ADD COLUMN, и для дописывания необязательных полей этого хватает.
    Переименования и смену типов так не сделать — если понадобятся, придётся
    заводить настоящие миграции.
    """
    for table in Base.metadata.sorted_tables:
        existing = {
            row[1]
            for row in (await conn.exec_driver_sql(f"PRAGMA table_info('{table.name}')")).fetchall()
        }
        if not existing:
            continue  # таблицы ещё нет — её создаст create_all
        for column in table.columns:
            if column.name in existing:
                continue
            ddl = column.type.compile(engine.dialect)
            default = ""
            if column.default is not None and getattr(column.default, "is_scalar", False):
                default = f" DEFAULT {column.default.arg!r}"
            await conn.exec_driver_sql(
                f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl}{default}'
            )


async def init_db() -> None:
    """Создать таблицы при старте приложения и дописать новые колонки."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _add_missing_columns(conn)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
