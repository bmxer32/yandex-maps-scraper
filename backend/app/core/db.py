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


class SearchHistoryRow(Base):
    """История поисковых запросов (чтобы показывать в UI «недавние»)."""
    __tablename__ = "search_history"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # task_id
    request_json: Mapped[str] = mapped_column(Text)            # сериализованный SearchRequest
    found_count: Mapped[int] = mapped_column(Integer, default=0)
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


async def init_db() -> None:
    """Создать таблицы при старте приложения."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
