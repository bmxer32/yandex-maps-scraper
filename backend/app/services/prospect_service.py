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
    all_sites,
    classify_link,
    needs_booking,
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
        websites=item.websites,
        reviews_count=item.reviews_count,
        rating=item.rating,
        socials=item.socials,
        address=item.address,
        categories=item.categories,
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
        web=row.web or "maybe",
        web_reasons=list(row.web_reasons or []),
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
            row.web = v.web
            row.web_reasons = v.web_reasons
            row.duplicate_of = v.duplicate_of
            row.http_status = v.http_status
            row.text_len = v.text_len
            row.last_year = v.last_year
            row.scale = v.scale
            row.alive = v.alive
            row.checked_at = datetime.utcnow()
        await db.commit()


def _site_note(link_kind: str, org: Organization) -> str:
    """Что написать модели про поле «сайт».

    Ссылок бывает несколько — перечисляем все, иначе модель судит о компании
    по случайной из них.
    """
    sites = all_sites(org)
    main = sites[0] if sites else None
    extra = f" (ещё: {', '.join(sites[1:])})" if len(sites) > 1 else ""

    if link_kind == "social":
        return f"страница в соцсети ({main}){extra}"
    if link_kind == "booking":
        return f"виджет онлайн-записи ({main}){extra}"
    if link_kind == "builder":
        return f"сайт на конструкторе ({main}){extra}"
    if main:
        return f"{main}{extra}"
    return "ничего"


def _apply_probe(
    v: ProspectVerdict, probe: ProbeResult, *, booking_matters: bool = False
) -> None:
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
        # А вот для оси «сайт» лежащий сайт — прямой повод обратиться.
        if probe.error:
            v.web = VERDICT_GOOD
            v.web_reasons.append("сайт не отвечает")
        return

    now = datetime.now().year
    stale = probe.last_year is not None and now - probe.last_year >= 3
    if (stale or probe.text_len < 400) and v.verdict == VERDICT_GOOD:
        v.verdict = VERDICT_MAYBE

    # Ось «сайт»: устаревший стек — прямой повод предложить переделку.
    if probe.tech.outdated:
        v.web = VERDICT_GOOD
        v.web_reasons.extend(probe.tech.summary())
    elif probe.tech.builder:
        # Конструктор: сайт рабочий, переделывать нечего. Но причину назвать
        # надо — «возможно» без объяснения человеку ничего не даёт. И запись
        # тут проверяется так же: она к платформе отношения не имеет.
        v.web = VERDICT_MAYBE
        v.web_reasons.append("сайт на конструкторе — рабочий, но простой")
        if booking_matters:
            v.web_reasons.extend(probe.tech.booking_note())
    elif stale:
        v.web = VERDICT_GOOD
        v.web_reasons.append(f"сайт не обновляли с {probe.last_year} года")
    elif booking_matters and not probe.tech.booking:
        # Сайт современный, но записаться на нём нельзя: клиент пишет в
        # телеграм и ждёт ответа администратора. Переделывать нечего, а
        # дорабатывать есть что — «возможно», а не «годится».
        v.web = VERDICT_MAYBE
        v.web_reasons.extend(probe.tech.booking_note())
    else:
        # Отвечает, адаптивный, стек современный, записаться есть где.
        v.web = VERDICT_SKIP
        v.web_reasons.append("сайт современный")


def _apply_other_sites(
    v: ProspectVerdict,
    rest: list[tuple[str, ProbeResult]],
    *,
    booking_matters: bool = False,
) -> None:
    """Остальные сайты компании — могут только снять ось «сайт», не поставить.

    Живой современный сайт где-то во второй ссылке означает, что предлагать
    разработку нечего, каким бы ни был первый адрес. Обратное неверно: одна
    лишняя старая страница ещё не повод объявлять, что компании нужен сайт.
    """
    for url, probe in rest:
        if probe.ok and not probe.tech.outdated and probe.text_len >= 400:
            # Записи и здесь нет — сайт есть, но записаться клиенту негде.
            # Только там, где на время вообще записываются: магазину эта
            # придирка ни к чему, и занижать ему ось из-за неё нельзя.
            if booking_matters and not probe.tech.booking:
                v.web = VERDICT_MAYBE
                v.web_reasons.append(
                    f"сайт {site_key(url)} рабочий, но онлайн-записи на нём нет"
                )
            else:
                v.web = VERDICT_SKIP
                v.web_reasons.append(f"у компании уже есть рабочий сайт: {site_key(url)}")
            return


def _apply_llm(
    v: ProspectVerdict,
    verdict: site_verdict.Verdict,
    reviews: int,
    *,
    live_site: bool = False,
) -> None:
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
    if verdict.web_reason:
        v.web_reasons.append(verdict.web_reason)

    chain = verdict.scale in ("сеть", "франшиза")
    if chain:
        # Сеть закрывает обе оси разом: ни ассистента, ни сайт локальному
        # подрядчику там не закажут — решают централизованно. Именно это
        # пропускалось раньше, и 4hands висел среди приоритетных.
        v.verdict = VERDICT_SKIP
        v.web = VERDICT_SKIP
        return

    if verdict.verdict == "мимо":
        if reviews >= 20:
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

    # Ось «сайт»: модель уточняет то, что дали правила и признаки стека.
    if verdict.web == "мимо":
        v.web = VERDICT_SKIP
    elif verdict.web == "годится":
        # Проба уже видела живой современный сайт — значит, вопрос не в том,
        # что сайта нет, а в его наполнении. Это «возможно», а не готовая
        # цель: идти предлагать разработку тому, у кого сайт есть, — стыдно.
        v.web = VERDICT_MAYBE if live_site else VERDICT_GOOD
    elif verdict.web == "сомнительно" and v.web == VERDICT_GOOD:
        v.web = VERDICT_MAYBE


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
        # Пробуем каждый собственный сайт компании, а не только первый: у той
        # же карточки рядом с настоящим сайтом висит ссылка на онлайн-запись.
        for url in all_sites(org):
            if classify_link(url) == LINK_OWN:
                to_probe.append((idx, url))

    # --- Ступень 2 ---
    probes = await probe_many(
        [u for _, u in to_probe],
        concurrency=settings.scan_concurrency,
        timeout=settings.scan_timeout,
    )
    by_idx: dict[int, list[tuple[str, ProbeResult]]] = {}
    for idx, url in to_probe:
        probe = probes.get(url)
        if probe is not None:
            by_idx.setdefault(idx, []).append((url, probe))

    for idx, results in by_idx.items():
        # Главный — первый по порядку карточки, он и решает про демо.
        wants_booking = needs_booking(orgs[idx])
        _apply_probe(verdicts[idx], results[0][1], booking_matters=wants_booking)
        _apply_other_sites(verdicts[idx], results[1:], booking_matters=wants_booking)

    # --- Ступень 3 ---
    # Модель смотрит ВСЕХ, а не только владельцев обходимого сайта. Раньше
    # компания с виджетом записи вместо сайта до неё не доходила и проходила
    # по одному числу отзывов — так федеральная франшиза 4hands оказывалась
    # среди приоритетных.
    classified = 0
    quota_hit = 0
    if site_verdict.enabled():
        # Главная страница главного сайта — она уходит в промпт.
        probe_by_idx = {idx: results[0][1] for idx, results in by_idx.items()}
        pending = [idx for idx, v in enumerate(verdicts) if v.checked_at and v.name]

        if pending:
            # Свой лимит: у модели ограничение по запросам в минуту, у проб
            # сайтов — нет. Общий семафор упирался в 429.
            sem = asyncio.Semaphore(settings.verdict_concurrency)
            async with httpx.AsyncClient() as client:

                async def one(idx: int) -> None:
                    nonlocal classified, quota_hit
                    async with sem:
                        v = verdicts[idx]
                        org = orgs[idx]
                        probe = probe_by_idx.get(idx)
                        has_text = probe is not None and probe.ok and probe.text_len >= 200

                        res = await site_verdict.classify(
                            client,
                            v.name or "",
                            probe.text if has_text else "",
                            tech="; ".join(probe.tech.summary()) if has_text else "",
                            address=org.address or "",
                            categories=", ".join(org.categories or []),
                            site_note=_site_note(v.link_kind, org),
                        )
                        if res.ok:
                            classified += 1
                        elif res.error and "лимит" in res.error:
                            quota_hit += 1
                        live = any(
                            p.ok and not p.tech.outdated and p.text_len >= 400
                            for _, p in by_idx.get(idx, [])
                        )
                        _apply_llm(v, res, org.reviews_count or 0, live_site=live)

                await asyncio.gather(*(one(i) for i in pending))

    fresh = [v for v in verdicts if v.site and v.site not in cached]
    if fresh:
        try:
            await _save(fresh)
        except Exception:
            logger.exception("Не удалось сохранить вердикты в кэш")

    return verdicts, classified, quota_hit
