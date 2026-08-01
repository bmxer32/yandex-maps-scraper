"""
Оркестрация отбора: три ступени от дешёвой к дорогой.

1. Механика — без сети (`prospect_rules`).
2. Проба главной — один запрос на компанию (`site_probe`).
3. Вердикт модели — один вызов, только для тех, у кого страница скачалась
   (`site_verdict`).

Понижать компанию до «мимо» имеет право только явная причина. Любая ошибка
на пути — недоступный сайт, молчащая модель, битый JSON — оставляет её в
«сомнительно», чтобы человек посмотрел сам.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import httpx
from loguru import logger
from sqlalchemy import select

from ..config import settings
from ..core.db import AsyncSessionLocal, SiteVerdictRow
from ..models.prospect import ProspectVerdict, ScanRequestItem
from ..models.schemas import Organization
from . import site_verdict
from .prospect_rules import (
    DEMO_AUTO,
    LINK_OWN,
    VERDICT_GOOD,
    VERDICT_MAYBE,
    VERDICT_SKIP,
    evaluate,
    find_duplicates,
    site_key,
)
from .site_probe import ProbeResult, probe_many


def _as_org(item: ScanRequestItem) -> Organization:
    """Строка запроса → Organization: правила написаны под неё."""
    return Organization(
        name=item.name,
        website=item.website,
        reviews_count=item.reviews_count,
        rating=item.rating,
        socials=item.socials,
    )


async def load_cached(sites: list[str]) -> dict[str, ProspectVerdict]:
    """Достать уже посчитанные вердикты по ключам сайтов."""
    keys = [s for s in sites if s]
    if not keys:
        return {}
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(SiteVerdictRow).where(SiteVerdictRow.site.in_(keys)))).scalars()
        return {r.site: _row_to_model(r) for r in rows}


def _row_to_model(row: SiteVerdictRow) -> ProspectVerdict:
    return ProspectVerdict(
        site=row.site,
        name=row.name,
        website=row.website,
        link_kind=row.link_kind or "none",
        demo=row.demo or "manual",
        verdict=row.verdict or "maybe",
        reasons=list(row.reasons or []),
        duplicate_of=row.duplicate_of,
        http_status=row.http_status,
        text_len=row.text_len,
        last_year=row.last_year,
        scale=row.scale,
        alive=row.alive,
        checked_at=row.checked_at,
    )


async def _save(verdicts: list[ProspectVerdict]) -> None:
    """Сложить вердикты в кэш. Ключ — сайт; без сайта не кэшируем."""
    async with AsyncSessionLocal() as db:
        for v in verdicts:
            if not v.site:
                continue
            row = await db.get(SiteVerdictRow, v.site)
            if row is None:
                row = SiteVerdictRow(site=v.site)
                db.add(row)
            row.name = v.name
            row.website = v.website
            row.link_kind = v.link_kind
            row.demo = v.demo
            row.verdict = v.verdict
            row.reasons = v.reasons
            row.duplicate_of = v.duplicate_of
            row.http_status = v.http_status
            row.text_len = v.text_len
            row.last_year = v.last_year
            row.scale = v.scale
            row.alive = v.alive
            row.checked_at = datetime.utcnow()
        await db.commit()


def _apply_probe(v: ProspectVerdict, probe: ProbeResult) -> None:
    """Наложить сигналы пробы.

    Проба принципиально НЕ ставит «мимо». Ни один её сигнал не является
    достаточным основанием: старый копирайт бывает у живой школы, 403 — это
    антибот, а не закрытый бизнес. Максимум, на что она имеет право, —
    понизить «годится» до «сомнительно» и оставить причину человеку.
    """
    v.http_status = probe.status
    v.text_len = probe.text_len
    v.last_year = probe.last_year
    v.reasons.extend(probe.reasons)

    if not probe.ok:
        # Сайт не отдался — это про нашу автоматику, а не про качество бизнеса.
        v.demo = "manual"
        if v.verdict == VERDICT_GOOD:
            v.verdict = VERDICT_MAYBE
        return

    now = datetime.now().year
    stale = probe.last_year is not None and now - probe.last_year >= 3
    if (stale or probe.text_len < 400) and v.verdict == VERDICT_GOOD:
        v.verdict = VERDICT_MAYBE


def _apply_llm(v: ProspectVerdict, verdict: site_verdict.Verdict, reviews: int) -> None:
    """Наложить вердикт модели — единственная ступень, которой можно отсеивать.

    С одной оговоркой: живой поток отзывов перевешивает вывод «заброшен».
    Модель видит только текст страницы, а десятки свежих отзывов на Картах
    means бизнес работает, каким бы старым ни выглядел сайт.
    """
    if verdict.error or not verdict.ok:
        if verdict.error:
            logger.debug("Вердикт модели для {!r}: {}", v.name, verdict.error)
        return

    v.scale = verdict.scale
    v.alive = verdict.alive if verdict.alive != "не понял" else v.alive
    if verdict.reason:
        v.reasons.append(verdict.reason)

    if verdict.verdict == "мимо":
        chain = verdict.scale in ("сеть", "франшиза")
        if not chain and reviews >= 20:
            # Отсев по «заброшен» при живых отзывах — противоречие, не верим.
            v.verdict = VERDICT_MAYBE
            v.reasons.append(
                f"модель сочла сайт неподходящим, но у компании {reviews} отзывов — проверьте сами"
            )
        else:
            v.verdict = VERDICT_SKIP
    elif verdict.verdict == "годится" and v.verdict != VERDICT_SKIP:
        v.verdict = VERDICT_GOOD
    elif verdict.verdict == "сомнительно" and v.verdict == VERDICT_GOOD:
        v.verdict = VERDICT_MAYBE


async def scan(
    items: list[ScanRequestItem], *, refresh: bool = False
) -> tuple[list[ProspectVerdict], int, int]:
    """Прогнать список через три ступени.

    Возвращает вердикты, число оценок модели и число компаний, которым
    вердикта не досталось из-за лимита запросов.
    """
    orgs = [_as_org(i) for i in items]
    dupes = find_duplicates(orgs)

    cached = {} if refresh else await load_cached([site_key(o.website) for o in orgs])

    verdicts: list[ProspectVerdict] = []
    to_probe: list[tuple[int, str]] = []

    for idx, org in enumerate(orgs):
        key = site_key(org.website)
        if key and key in cached:
            hit = cached[key]
            # Дубли считаются в рамках текущей выгрузки, кэш о них не знает.
            hit.duplicate_of = dupes.get(idx) or hit.duplicate_of
            verdicts.append(hit)
            continue

        base = evaluate(org, duplicate_of=dupes.get(idx), min_reviews=settings.min_reviews)
        v = ProspectVerdict(
            site=key,
            name=org.name,
            website=org.website,
            checked_at=datetime.utcnow(),
            **base,
        )
        verdicts.append(v)
        if base["link_kind"] == LINK_OWN and org.website:
            to_probe.append((idx, org.website))

    # --- Ступень 2 ---
    probes = await probe_many(
        [u for _, u in to_probe],
        concurrency=settings.scan_concurrency,
        timeout=settings.scan_timeout,
    )
    for idx, url in to_probe:
        probe = probes.get(url)
        if probe is not None:
            _apply_probe(verdicts[idx], probe)

    # --- Ступень 3 ---
    classified = 0
    quota_hit = 0
    if site_verdict.enabled():
        ready = [
            (idx, url)
            for idx, url in to_probe
            if (p := probes.get(url)) is not None and p.ok and p.text_len >= 200
        ]
        if ready:
            # Свой лимит: у модели ограничение по запросам в минуту, у проб
            # сайтов — нет. Общий семафор упирался в 429.
            sem = asyncio.Semaphore(settings.verdict_concurrency)
            async with httpx.AsyncClient() as client:

                async def one(idx: int, url: str) -> None:
                    nonlocal classified, quota_hit
                    async with sem:
                        probe = probes[url]
                        res = await site_verdict.classify(client, verdicts[idx].name or "", probe.text)
                        if res.ok:
                            classified += 1
                        elif res.error and "лимит" in res.error:
                            quota_hit += 1
                        _apply_llm(verdicts[idx], res, orgs[idx].reviews_count or 0)

                await asyncio.gather(*(one(i, u) for i, u in ready))

    fresh = [v for v in verdicts if v.site and v.site not in cached]
    if fresh:
        try:
            await _save(fresh)
        except Exception:
            logger.exception("Не удалось сохранить вердикты в кэш")

    return verdicts, classified, quota_hit
