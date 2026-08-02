"""
Раздел «В работе»: конторы, с которыми уже что-то делаем.

Главное правило — **парсинг не трогает работу человека**. Повторная выгрузка
той же ниши обновляет телефоны, сайты и оценку, но статус, заметка и дата
напоминания остаются как были. Иначе пересобрал нишу — и потерял, кому уже
писал.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from loguru import logger
from sqlalchemy import select

from ..core.db import AsyncSessionLocal, WorkItemRow
from ..models.work import WORK_STATUSES, WorkItem


def work_key(org: dict) -> str:
    """Ключ конторы.

    permalink Яндекса стабилен и есть даже там, где нет ни сайта, ни телефона.
    Сайт ключом быть не может: у половины салонов его нет, и все они слиплись
    бы в одну запись.
    """
    permalink = (org.get("permalink") or "").strip()
    if permalink:
        return permalink
    name = (org.get("name") or "").strip().lower()
    address = (org.get("address") or "").strip().lower()
    return f"{name}|{address}"


def _row_to_model(row: WorkItemRow) -> WorkItem:
    return WorkItem(
        key=row.key,
        permalink=row.permalink,
        name=row.name,
        address=row.address,
        phone=row.phone,
        phones=list(row.phones or []),
        website=row.website,
        websites=list(row.websites or []),
        email=row.email,
        socials=list(row.socials or []),
        categories=list(row.categories or []),
        rating=row.rating,
        reviews_count=row.reviews_count,
        lat=row.lat,
        lon=row.lon,
        verdict=row.verdict,
        web=row.web,
        status=row.status or "new",
        note=row.note,
        demo_url=row.demo_url,
        remind_at=row.remind_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _fill_card(row: WorkItemRow, org: dict) -> None:
    """Переложить данные карточки в запись. Статуса и заметки не касается."""
    row.permalink = org.get("permalink") or row.permalink
    row.name = org.get("name") or row.name
    row.address = org.get("address") or row.address
    row.phone = org.get("phone") or row.phone
    row.phones = list(org.get("phones") or []) or list(row.phones or [])
    row.website = org.get("website") or row.website
    row.websites = list(org.get("websites") or []) or list(row.websites or [])
    row.email = org.get("email") or row.email
    row.socials = list(org.get("socials") or []) or list(row.socials or [])
    row.categories = list(org.get("categories") or []) or list(row.categories or [])
    if org.get("rating") is not None:
        row.rating = org["rating"]
    if org.get("reviews_count") is not None:
        row.reviews_count = org["reviews_count"]
    if org.get("lat") is not None:
        row.lat = org["lat"]
    if org.get("lon") is not None:
        row.lon = org["lon"]
    # Оценка приходит из таблицы, если её успели посчитать.
    if org.get("verdict"):
        row.verdict = org["verdict"]
    if org.get("web"):
        row.web = org["web"]


async def add(items: Iterable[dict]) -> list[WorkItem]:
    """Добавить конторы. Уже добавленную не дублируем — обновляем карточку."""
    out: list[WorkItem] = []
    async with AsyncSessionLocal() as db:
        for org in items:
            if not (org.get("name") or "").strip():
                continue
            key = work_key(org)
            row = await db.get(WorkItemRow, key)
            if row is None:
                row = WorkItemRow(key=key, name=org["name"], status="new")
                db.add(row)
            _fill_card(row, org)
            out.append(_row_to_model(row))
        await db.commit()
    return out


async def refresh(orgs: Iterable[dict]) -> int:
    """Обновить карточки тех, кто уже в работе. Новых не заводит.

    Зовётся после завершения выгрузки: раз уж Яндекс отдал свежие телефоны,
    пусть в разделе будут они, а не то, что было месяц назад.
    """
    updated = 0
    async with AsyncSessionLocal() as db:
        for org in orgs:
            key = work_key(org)
            row = await db.get(WorkItemRow, key)
            if row is None:
                continue
            _fill_card(row, org)
            updated += 1
        if updated:
            await db.commit()
    return updated


async def list_items() -> list[WorkItem]:
    """Все конторы в работе. Сортировка — в интерфейсе, тут порядок добавления."""
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(WorkItemRow).order_by(WorkItemRow.created_at.desc()))
        ).scalars()
        return [_row_to_model(r) for r in rows]


async def update(
    key: str,
    *,
    status: Optional[str] = None,
    note: Optional[str] = None,
    demo_url: Optional[str] = None,
    remind_at: Optional[datetime] = None,
    clear_remind: bool = False,
) -> Optional[WorkItem]:
    """Изменить статус, заметку или напоминание."""
    async with AsyncSessionLocal() as db:
        row = await db.get(WorkItemRow, key)
        if row is None:
            return None
        if status is not None:
            if status not in WORK_STATUSES:
                logger.warning("Неизвестный статус {!r} — не применяю", status)
            else:
                row.status = status
        if note is not None:
            row.note = note.strip() or None
        if demo_url is not None:
            row.demo_url = demo_url.strip() or None
        if clear_remind:
            row.remind_at = None
        elif remind_at is not None:
            row.remind_at = remind_at
        await db.commit()
        return _row_to_model(row)


async def remove(key: str) -> bool:
    """Убрать контору из работы. Демо и вердикты не трогаем — они сами по себе."""
    async with AsyncSessionLocal() as db:
        row = await db.get(WorkItemRow, key)
        if row is None:
            return False
        await db.delete(row)
        await db.commit()
        return True
