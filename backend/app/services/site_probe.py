"""
Вторая ступень: скачиваем только главную страницу, без обхода сайта.

Один запрос на компанию вместо тридцати даёт четыре независимых сигнала:
отвечает ли сайт, не закрыт ли антиботом, свежий ли он, не сеть ли это.
На реальной выгрузке этого хватило, чтобы поймать и мёртвый сайт, и сайт
с копирайтом 2021 года.

Важно: 403 и таймаут — это наша техническая помеха, а не приговор бизнесу.
Такие компании уходят в «сомнительно» и «демо вручную», но не в отсев.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger

# Сайты часто закрыты от «незнакомых» клиентов — представляемся браузером.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru,en;q=0.9",
}

_TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.DOTALL | re.IGNORECASE)

# Год ищем ТОЛЬКО рядом с копирайтом. Первая версия брала максимальный год из
# всего текста — и фраза «работаем с 2015 года» записывала в заброшенные школу
# со 182 отзывами. Год сам по себе слишком слабый признак, чтобы трактовать
# его свободно.
_COPYRIGHT_YEAR = re.compile(
    r"(?:©|&copy;|\(c\)|все\s+права\s+защищены)[^.\n]{0,40}?(20[12]\d)"
    r"|(20[12]\d)[^.\n]{0,20}?(?:©|&copy;|все\s+права\s+защищены)",
    re.IGNORECASE,
)
_CHAIN = re.compile(
    r"филиал|наши\s+(студии|салоны|центры|школы)|сеть\s+(студий|салонов|центров|школ|клиник)"
    r"|франшиз|в\s+\d+\s+городах|представительств",
    re.IGNORECASE,
)


@dataclass
class ProbeResult:
    """Что удалось узнать по одной главной странице."""

    ok: bool = False
    status: Optional[int] = None
    error: Optional[str] = None
    text: str = ""
    text_len: int = 0
    last_year: Optional[int] = None
    chain_hint: bool = False
    reasons: list[str] = field(default_factory=list)


def _analyze(html: str) -> tuple[str, Optional[int], bool]:
    """Текст без разметки, год копирайта и намёк на сеть."""
    text = _TAGS.sub(" ", html)
    text = re.sub(r"\s+", " ", text).strip()

    now = datetime.now().year
    years = set()
    for m in _COPYRIGHT_YEAR.finditer(text):
        raw = m.group(1) or m.group(2)
        if raw and int(raw) <= now:
            years.add(int(raw))
    return text, (max(years) if years else None), bool(_CHAIN.search(text))


async def probe_site(client: httpx.AsyncClient, url: str, *, timeout: float = 12.0) -> ProbeResult:
    """Скачать главную и вытащить сигналы. Не бросает — ошибка это тоже сигнал."""
    res = ProbeResult()
    try:
        resp = await client.get(url, timeout=timeout, follow_redirects=True, headers=_HEADERS)
    except httpx.HTTPError as exc:
        res.error = type(exc).__name__
        res.reasons.append("сайт не отвечает — проверьте вручную, мог лечь на минуту")
        return res

    res.status = resp.status_code
    if resp.status_code >= 400:
        if resp.status_code in (401, 403, 429):
            res.reasons.append(
                f"сайт закрыт от автоматических запросов ({resp.status_code}) — "
                "демо придётся собирать вручную"
            )
        else:
            res.reasons.append(f"сайт отвечает ошибкой {resp.status_code}")
        return res

    text, last_year, chain = _analyze(resp.text[:400_000])
    res.ok = True
    res.text = text
    res.text_len = len(text)
    res.last_year = last_year
    res.chain_hint = chain

    if res.text_len < 400:
        res.reasons.append("на главной почти нет текста — скорее всего, рисуется скриптами")

    now = datetime.now().year
    if last_year is not None and now - last_year >= 3:
        res.reasons.append(f"копирайт на сайте — {last_year}, давно не обновляли")
    if chain:
        res.reasons.append("на сайте упоминаются филиалы или франшиза")

    return res


async def probe_many(
    urls: list[str], *, concurrency: int = 8, timeout: float = 12.0
) -> dict[str, ProbeResult]:
    """Проба пачки сайтов параллельно. Ключ результата — исходный URL."""
    if not urls:
        return {}

    sem = asyncio.Semaphore(concurrency)
    out: dict[str, ProbeResult] = {}

    async with httpx.AsyncClient(headers=_HEADERS) as client:

        async def one(url: str) -> None:
            async with sem:
                try:
                    out[url] = await probe_site(client, url, timeout=timeout)
                except Exception:
                    logger.exception("Проба сайта {} сорвалась", url)
                    out[url] = ProbeResult(error="unexpected")

        await asyncio.gather(*(one(u) for u in urls))

    return out
