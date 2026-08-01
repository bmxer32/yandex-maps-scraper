"""
Сервис поиска: связывает гео-справочник, парсер Яндекс.Карт и site-enricher
в один асинхронный pipeline. Запускается как фоновая задача из API-роута.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from loguru import logger

from ..core.geo import build_search_hint
from ..core.scraper.site_enricher import enrich_organizations
from ..core.scraper.yandex_maps import YandexMapsScraper
from ..models.schemas import SearchRequest, TaskStage
from .task_manager import task_manager


async def run_search_pipeline(task_id: str, request: SearchRequest) -> None:
    """
    Главная корутина фонового парсинга.
    Шаги:
      1. Собираем гео-подсказку.
      2. Парсим Яндекс.Карты (с прогрессом).
      3. (Опц.) Второй проход по сайтам организаций.
      4. Кладём результат в task_manager.
    """
    # 1) География. При точечном поиске не нужна: запрос уходит как есть,
    # иначе к телефону или ссылке приклеился бы «, Россия».
    geo_hint = "" if request.raw_query else build_search_hint(
        country_id=request.country_id,
        region_id=request.region_id,
        city_id=request.city_id,
        district_id=request.district_id,
        metro_id=request.metro_id,
    )
    logger.info("[{}] pipeline start: '{}', geo='{}'",
                task_id, request.category, geo_hint)

    state = task_manager._get(task_id)  # доступ к cancel_event
    cancel_event: asyncio.Event = state.cancel_event

    async def on_progress(
        stage: TaskStage,
        processed: int,
        total: int,
        with_website: int,
        without_website: int,
        message: str,
    ) -> None:
        await task_manager.update_progress(
            task_id,
            stage=stage,
            processed=processed,
            total=total,
            found_with_website=with_website,
            found_without_website=without_website,
            message=message,
        )

    # 2) Парсер Яндекс.Карт
    scraper = YandexMapsScraper()
    orgs = await scraper.run(
        request=request,
        geo_text=geo_hint,
        on_progress=on_progress,
        cancel_event=cancel_event,
    )

    # 3) Второй проход по сайтам (если разрешено и есть сайты)
    if request.enrich_sites and any(o.website for o in orgs):
        await task_manager.update_progress(
            task_id, stage=TaskStage.ENRICHING_SITES,
            message=f"Сайты: собираю email и соцсети у {sum(1 for o in orgs if o.website)} организаций…",
        )
        await enrich_organizations(
            orgs, on_progress=on_progress, cancel_event=cancel_event,
        )

    # 4) Сохраняем результат
    await task_manager.set_organizations(task_id, orgs)

    # Финальное сообщение с разбивкой
    with_site = sum(1 for o in orgs if o.website)
    await task_manager.update_progress(
        task_id,
        stage=TaskStage.DONE,
        processed=len(orgs),
        total=len(orgs),
        found_with_website=with_site,
        found_without_website=len(orgs) - with_site,
        message=(
            f"Готово: {len(orgs)} организаций. "
            f"С сайтом: {with_site}, без сайта: {len(orgs) - with_site}."
        ),
    )
