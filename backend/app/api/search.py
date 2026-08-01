"""
Роуты поиска и управления задачами.
POST   /api/search               — создать и запустить задачу
GET    /api/tasks                — список всех задач
GET    /api/task/{task_id}       — текущий прогресс + результат
GET    /api/task/{task_id}/stream — SSE-стрим прогресса в реальном времени
POST   /api/task/{task_id}/cancel — отменить задачу
GET    /api/geo/tree             — гео-дерево для каскадных селекторов
GET    /api/export/{task_id}     — выгрузить результат в xlsx/csv
"""
from __future__ import annotations

import asyncio
import io
import json
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from ..core.geo import get_geo_tree
from ..models.schemas import SearchRequest, TaskStage
from ..services import history_service
from ..services.search_service import run_search_pipeline
from ..services.task_manager import task_manager

router = APIRouter(prefix="/api", tags=["scraper"])


# ---------------------------------------------------------------------------
# География (для каскадных селекторов)
# ---------------------------------------------------------------------------
@router.get("/geo/tree")
async def geo_tree():
    """Дерево страна → регион → город → район/метро."""
    return [n.model_dump(mode="json") for n in get_geo_tree()]


# ---------------------------------------------------------------------------
# Создание / запуск задачи
# ---------------------------------------------------------------------------
@router.post("/search")
async def create_search(req: SearchRequest):
    """Создаём задачу и сразу запускаем в фоне."""
    logger.info("SEARCH REQUEST: category={!r} region={!r} city={!r} district={!r} metro={!r} limit={} fetch_web={} enrich={}",
                req.category, req.region_id, req.city_id, req.district_id,
                req.metro_id, req.limit, req.fetch_websites, req.enrich_sites)
    task_id = await task_manager.create(req)

    async def _runner() -> None:
        await run_search_pipeline(task_id, req)

    await task_manager.start(task_id, _runner())
    return {"task_id": task_id, "status": "started"}


# ---------------------------------------------------------------------------
# Список / статус задач
# ---------------------------------------------------------------------------
@router.get("/tasks")
async def list_tasks():
    return task_manager.list_all()


@router.get("/task/{task_id}")
async def task_detail(task_id: str):
    result = task_manager.get_result(task_id)
    if result is None:
        # Задачи живут в памяти: после перезапуска программы их там нет,
        # но завершённая выгрузка осталась в истории.
        result = await history_service.load_run(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="task not found")
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# История выгрузок
# ---------------------------------------------------------------------------
@router.get("/history")
async def history_list():
    """Недавние выгрузки — чтобы вернуться к ним, а не собирать заново."""
    return [
        {**r, "created_at": r["created_at"].isoformat()}
        for r in await history_service.list_runs()
    ]


@router.get("/history/{task_id}")
async def history_detail(task_id: str):
    """Открыть сохранённую выгрузку целиком."""
    result = await history_service.load_run(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="выгрузка не найдена")
    return result.model_dump(mode="json")


@router.delete("/history/{task_id}", status_code=204)
async def history_delete(task_id: str) -> None:
    if not await history_service.delete_run(task_id):
        raise HTTPException(status_code=404, detail="выгрузка не найдена")


# ---------------------------------------------------------------------------
# SSE-стрим прогресса
# ---------------------------------------------------------------------------
@router.get("/task/{task_id}/stream")
async def task_stream(task_id: str):
    """
    Server-Sent Events: толкаем обновления прогресса, пока задача не закончится.
    На фронте читается через EventSource.
    """
    if task_manager.get_progress(task_id) is None:
        raise HTTPException(status_code=404, detail="task not found")

    queue = await task_manager.subscribe(task_id)
    progress = task_manager.get_progress(task_id)
    final_stages = {TaskStage.DONE, TaskStage.FAILED, TaskStage.CANCELLED}

    async def event_generator():
        try:
            # Сразу шлём текущий снапшот
            yield {"event": "progress", "data": json.dumps(progress.model_dump(mode="json"), default=str)}

            while True:
                try:
                    snap = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # keepalive-комментарий, чтобы соединение не закрывалось
                    yield {"event": "ping", "data": "{}"}
                    continue

                yield {"event": "progress",
                       "data": json.dumps(snap.model_dump(mode="json"), default=str)}

                if snap.stage in final_stages:
                    break
        finally:
            task_manager.unsubscribe(task_id, queue)

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Отмена задачи
# ---------------------------------------------------------------------------
@router.post("/task/{task_id}/cancel")
async def cancel_task(task_id: str):
    ok = await task_manager.cancel(task_id)
    if not ok:
        raise HTTPException(status_code=400, detail="cannot cancel (not running?)")
    return {"task_id": task_id, "status": "cancelling"}


# ---------------------------------------------------------------------------
# Экспорт
# ---------------------------------------------------------------------------
@router.get("/export/{task_id}")
async def export_task(
    task_id: str,
    fmt: str = Query("xlsx", pattern="^(xlsx|csv)$"),
    only_with_website: bool = Query(False, description="только организации с сайтом"),
):
    """Выгрузка результата в xlsx или csv."""
    result = task_manager.get_result(task_id)
    if result is None:
        # Скачать Excel по выгрузке из истории — тот же сценарий, что и
        # открыть её в таблице: задачи в памяти не переживают перезапуск.
        result = await history_service.load_run(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="task not found")

    orgs = result.organizations
    if only_with_website:
        orgs = [o for o in orgs if o.website]

    rows = [
        {
            "Название": o.name,
            "Адрес": o.address or "",
            "Телефон": o.phone or "",
            # Второй номер и второй сайт бывают у каждой десятой карточки —
            # в выгрузке они нужны целиком, а не первым попавшимся.
            "Все телефоны": "; ".join(o.phones),
            "Сайт": o.website or "",
            "Все сайты": "; ".join(o.websites),
            "Email": o.email or "",
            "Соцсети": "; ".join(o.socials),
            "Часы работы": o.hours or "",
            "Рейтинг": o.rating if o.rating is not None else "",
            "Отзывы": o.reviews_count if o.reviews_count is not None else "",
            "Рубрики": "; ".join(o.categories),
            "Широта": o.lat if o.lat is not None else "",
            "Долгота": o.lon if o.lon is not None else "",
        }
        for o in orgs
    ]
    df = pd.DataFrame(rows)

    if fmt == "csv":
        data = df.to_csv(index=False).encode("utf-8-sig")
        media = "text/csv; charset=utf-8"
        fname = f"{task_id}.csv"
    else:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Организации")
        data = buf.getvalue()
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        fname = f"{task_id}.xlsx"

    headers = {"Content-Disposition": f'attachment; filename="{fname}"'}
    return StreamingResponse(io.BytesIO(data), media_type=media, headers=headers)
