"""
Роуты раздела «В работе».

GET    /api/work/list      — все конторы в работе
POST   /api/work/add       — добавить (звёздочкой из таблицы), пачкой можно
PATCH  /api/work/{key}     — статус, заметка, напоминание
DELETE /api/work/{key}     — убрать из работы
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from loguru import logger

from ..models.work import WorkAddRequest, WorkItem, WorkUpdateRequest
from ..services import work_service

router = APIRouter(prefix="/api/work", tags=["work"])


@router.get("/list", response_model=list[WorkItem])
async def list_work() -> list[WorkItem]:
    return await work_service.list_items()


@router.post("/add", response_model=list[WorkItem])
async def add_work(req: WorkAddRequest) -> list[WorkItem]:
    try:
        return await work_service.add(req.items)
    except Exception as exc:
        logger.exception("Не удалось добавить в работу")
        raise HTTPException(status_code=500, detail=f"Не удалось добавить: {exc}") from exc


@router.patch("/{key:path}", response_model=WorkItem)
async def update_work(key: str, req: WorkUpdateRequest) -> WorkItem:
    item = await work_service.update(
        key,
        status=req.status,
        note=req.note,
        remind_at=req.remind_at,
        clear_remind=req.clear_remind,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Контора не в работе")
    return item


@router.delete("/{key:path}")
async def remove_work(key: str) -> dict:
    if not await work_service.remove(key):
        raise HTTPException(status_code=404, detail="Контора не в работе")
    return {"removed": key}
