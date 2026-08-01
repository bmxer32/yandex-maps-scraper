"""
Роуты персональных демо ИИ-ассистента.

GET  /api/demos/config    — настроена ли интеграция (UI прячет кнопку, если нет)
POST /api/demos/provision — завести демо пачке организаций и запустить краул
GET  /api/demos/status    — опросить статусы по списку slug

Парсер ходит в kb_assistant сам, а не из браузера: API-ключ остаётся на
бэкенде, и не нужен CORS на стороне kb_assistant.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from ..config import settings
from ..models.demo import (
    DemoConfig,
    DemoProvisionRequest,
    DemoProvisionResponse,
    DemoRequestItem,
    DemoStatus,
    DemoStatusResponse,
)
from ..services.demo_client import DemoClient, DemoClientError, demo_link, make_slug

router = APIRouter(prefix="/api/demos", tags=["demos"])

# Краул — сетевая операция на стороне kb_assistant; в параллель пускаем
# немного, чтобы не забить его очередь одной выгрузкой на сотню строк.
_PROVISION_CONCURRENCY = 4


@router.get("/config", response_model=DemoConfig)
async def demo_config() -> DemoConfig:
    """Настроена ли интеграция и поднялся ли уже kb_assistant."""
    if not settings.kb_enabled:
        return DemoConfig(enabled=False, max_pages=settings.kb_max_pages)

    return DemoConfig(
        enabled=True,
        ready=await DemoClient().ping(),
        bot_username=settings.kb_bot_username or None,
        max_pages=settings.kb_max_pages,
    )


def _to_status(payload: dict, item: DemoRequestItem | None = None) -> DemoStatus:
    """Ответ kb_assistant → строка для таблицы парсера."""
    slug = payload.get("slug", "")
    return DemoStatus(
        name=item.name if item else payload.get("company_name"),
        website=item.website if item else payload.get("site_url"),
        slug=slug,
        link=demo_link(slug),
        status=payload.get("status", "pending"),
        error=payload.get("status_error"),
        pages_indexed=payload.get("pages_indexed") or 0,
        opened_count=payload.get("opened_count") or 0,
        message_count=payload.get("message_count") or 0,
    )


@router.post("/provision", response_model=DemoProvisionResponse)
async def provision(req: DemoProvisionRequest) -> DemoProvisionResponse:
    """Завести демо для каждой организации и запустить краул её сайта."""
    if not settings.kb_enabled:
        raise HTTPException(
            status_code=503,
            detail="Интеграция с kb_assistant не настроена: задайте KB_BASE_URL и KB_API_KEY",
        )

    client = DemoClient()
    semaphore = asyncio.Semaphore(_PROVISION_CONCURRENCY)

    async def one(item: DemoRequestItem) -> DemoStatus:
        slug = make_slug(item.name, item.website)
        async with semaphore:
            try:
                created = await client.provision(
                    slug=slug,
                    company_name=item.name,
                    site_url=item.website,
                    max_pages=req.max_pages,
                )
                return _to_status(created or {"slug": slug}, item)
            except DemoClientError as exc:
                # Демо для этой организации уже заводили — показываем его
                # текущее состояние, а не ошибку: повторный клик по строке
                # в таблице должен быть безобидным.
                existing = await _try_fetch(client, slug)
                if existing is not None:
                    return _to_status(existing, item)
                logger.warning("Не удалось завести демо для {!r}: {}", item.name, exc)
                return DemoStatus(
                    name=item.name,
                    website=item.website,
                    slug=slug,
                    link=demo_link(slug),
                    status="error",
                    error=str(exc),
                )

    results = await asyncio.gather(*(one(item) for item in req.items))
    return DemoProvisionResponse(items=list(results))


@router.get("/list", response_model=DemoStatusResponse)
async def list_demos(opened_only: bool = False, limit: int = Query(200, ge=1, le=500)) -> DemoStatusResponse:
    """Все заведённые демо.

    Таблица зовёт это при загрузке: так строки помечаются как «демо уже есть»
    даже после перезапуска приложения, когда локального состояния нет.
    """
    if not settings.kb_enabled:
        return DemoStatusResponse(items=[])

    client = DemoClient()
    try:
        items = await client.list_targets(opened_only=opened_only, limit=limit)
    except DemoClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return DemoStatusResponse(items=[_to_status(it) for it in items])


@router.get("/status", response_model=DemoStatusResponse)
async def status(slug: list[str] = Query(default=[])) -> DemoStatusResponse:
    """Статусы демо по списку slug — один запрос на страницу таблицы."""
    if not settings.kb_enabled:
        raise HTTPException(status_code=503, detail="Интеграция с kb_assistant не настроена")
    if not slug:
        return DemoStatusResponse(items=[])

    client = DemoClient()
    try:
        items = await client.by_slugs(slug)
    except DemoClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return DemoStatusResponse(items=[_to_status(it) for it in items])


@router.delete("/{slug}", status_code=204)
async def delete_demo(slug: str, purge: bool = True) -> None:
    """Удалить демо. По умолчанию сносится и собранная база знаний."""
    if not settings.kb_enabled:
        raise HTTPException(status_code=503, detail="Интеграция с kb_assistant не настроена")
    try:
        await DemoClient().delete(slug, purge=purge)
    except DemoClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def _try_fetch(client: DemoClient, slug: str) -> dict | None:
    """Достать демо по slug, молча вернув None, если его нет."""
    try:
        found = await client.by_slugs([slug])
    except DemoClientError:
        return None
    return found[0] if found else None
