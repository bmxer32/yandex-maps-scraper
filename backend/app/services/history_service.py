"""
История выгрузок.

Задачи парсера живут в памяти, и после перезапуска программы результат
пропадал — приходилось собирать заново, тратя минуты работы браузера и
дёргая Яндекс без нужды. Здесь завершённые выгрузки складываются в SQLite
целиком, чтобы к ним можно было вернуться.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import delete, select

from ..core.db import AsyncSessionLocal, SearchHistoryRow
from ..core.geo import get_geo_tree
from ..models.schemas import Organization, SearchRequest, TaskResult

# Сколько выгрузок держим. Старые вытесняются: история нужна, чтобы вернуться
# к недавней работе, а не чтобы копить всё подряд.
MAX_RUNS = 50

_geo_names: dict[str, str] = {}


def _location_label(req: SearchRequest) -> str:
    """Человеческая подпись места: «Москва · Центральный» вместо id."""
    global _geo_names
    if not _geo_names:
        try:
            _geo_names = {n.id: n.name for n in get_geo_tree()}
        except Exception:
            logger.exception("Не смог загрузить гео-дерево для подписи истории")
            _geo_names = {"__failed__": ""}

    parts = [
        _geo_names.get(x or "")
        for x in (req.region_id, req.city_id, req.district_id, req.metro_id)
    ]
    return " · ".join(p for p in parts if p)


async def save_run(result: TaskResult) -> None:
    """Сохранить завершённую выгрузку. Не бросает — история не критична."""
    if not result.organizations:
        return
    try:
        orgs = [o.model_dump(mode="json") for o in result.organizations]
        async with AsyncSessionLocal() as db:
            row = await db.get(SearchHistoryRow, result.task_id)
            if row is None:
                row = SearchHistoryRow(id=result.task_id)
                db.add(row)
            row.request_json = result.search.model_dump_json()
            row.found_count = len(orgs)
            row.category = result.search.category
            row.location = _location_label(result.search)
            row.with_website = sum(1 for o in orgs if o.get("website"))
            row.organizations = orgs
            row.created_at = datetime.utcnow()
            await db.commit()

            # Вытесняем старое, чтобы база не росла бесконечно.
            ids = (
                await db.execute(
                    select(SearchHistoryRow.id)
                    .order_by(SearchHistoryRow.created_at.desc())
                    .offset(MAX_RUNS)
                )
            ).scalars().all()
            if ids:
                await db.execute(delete(SearchHistoryRow).where(SearchHistoryRow.id.in_(ids)))
                await db.commit()
    except Exception:
        logger.exception("Не удалось сохранить выгрузку {} в историю", result.task_id)


async def list_runs() -> list[dict]:
    """Список выгрузок для интерфейса — без самих организаций."""
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(SearchHistoryRow).order_by(SearchHistoryRow.created_at.desc())
            )
        ).scalars().all()
    return [
        {
            "task_id": r.id,
            "category": r.category or "",
            "location": r.location or "",
            "found_count": r.found_count,
            "with_website": r.with_website,
            "created_at": r.created_at,
        }
        for r in rows
    ]


async def load_run(task_id: str) -> Optional[TaskResult]:
    """Достать выгрузку целиком — чтобы открыть её в таблице без парсинга."""
    async with AsyncSessionLocal() as db:
        row = await db.get(SearchHistoryRow, task_id)
    if row is None:
        return None

    try:
        search = SearchRequest(**json.loads(row.request_json))
    except Exception:
        logger.exception("Битый запрос в истории {}", task_id)
        return None

    orgs = [Organization(**o) for o in (row.organizations or [])]
    from ..models.schemas import TaskProgress, TaskStage

    return TaskResult(
        task_id=task_id,
        progress=TaskProgress(
            task_id=task_id,
            stage=TaskStage.DONE,
            processed=len(orgs),
            total=len(orgs),
            found_with_website=row.with_website,
            found_without_website=len(orgs) - row.with_website,
            message="Из истории",
            started_at=row.created_at,
            updated_at=row.created_at,
        ),
        organizations=orgs,
        search=search,
    )


async def delete_run(task_id: str) -> bool:
    async with AsyncSessionLocal() as db:
        row = await db.get(SearchHistoryRow, task_id)
        if row is None:
            return False
        await db.delete(row)
        await db.commit()
    return True
