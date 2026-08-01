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

# --- Признаки того, что сайт пора переделывать -----------------------------
# Достаются из той же страницы, что уже скачана для оценки: отдельных запросов
# не нужно. На реальных сайтах из выгрузок это ловится уверенно — jQuery 1.10
# (это 2013 год), ссылки на .php, работа без TLS.
_VIEWPORT = re.compile(r"<meta[^>]+name=[\"']viewport", re.IGNORECASE)
_PHP_LINKS = re.compile(r"\.php[\"'?]", re.IGNORECASE)
_TABLE_LAYOUT = re.compile(r"<table[^>]*>\s*<tr", re.IGNORECASE)
_JQUERY = re.compile(r"jquery[.\-/]?(\d+)\.(\d+)", re.IGNORECASE)
# Настоящая онлайн-запись — это виджет платформы, где клиент сам выбирает
# мастера и время. По слову «Записаться» судить нельзя: сплошь и рядом такая
# кнопка ведёт в телеграм или к форме заявки, а значит клиент всё равно ждёт
# ответа администратора — то есть ровно тот случай, ради которого мы и идём.
_BOOKING_PLATFORM = re.compile(
    r"(yclients|dikidi\.(net|ru)|easyweek|sonline\.su|gbooking|yclients\.com"
    r"|n\d{5,}\.\w+|zapis-?online|booking\.\w+|sberbusiness\.booking)",
    re.IGNORECASE,
)
# Форма на странице — не запись, но и не «пишите в телеграм»: заявку оставить
# можно, время не выберешь.
_FORM = re.compile(r"<form[\s>]", re.IGNORECASE)
_GENERATOR = re.compile(
    r"<meta[^>]+name=[\"']generator[\"'][^>]+content=[\"']([^\"']+)", re.IGNORECASE
)
# Конструкторы ищем по служебным доменам, а не по слову в тексте: «wix» может
# оказаться внутри обычного слова и записать живой сайт в конструкторы.
_BUILDER = re.compile(
    r"(tilda(cdn)?\.(ws|com|cc)|static\.tildacdn|wixstatic\.com|parastorage\.com"
    r"|nethouse\.ru|u-?coz\.(ru|net)|s\.ucoz|a5\.ru|readymag|craftum)",
    re.IGNORECASE,
)
# Конструктор конструктору рознь. Tilda и Wix отдают живой адаптивный сайт —
# менять там нечего. uCoz, Nethouse и a5 — платформы нулевых, и вот это как раз
# кандидат на замену: ровно тот «старый сайт», который мы ищем.
_BUILDER_LEGACY = re.compile(r"(nethouse\.ru|u-?coz\.(ru|net)|s\.ucoz|a5\.ru)", re.IGNORECASE)


@dataclass
class TechSignals:
    """На чём сделан сайт — для оси «редизайн/создание сайта»."""

    responsive: bool = True          # есть <meta viewport>
    php_links: bool = False
    table_layout: bool = False
    jquery: Optional[str] = None     # версия, если нашлась
    jquery_old: bool = False         # ниже 3.x
    generator: Optional[str] = None  # CMS из <meta generator>
    builder: bool = False            # Tilda, Wix, uCoz и подобное
    legacy_builder: bool = False     # платформа нулевых: uCoz, Nethouse, a5
    no_tls: bool = False
    booking: bool = False            # виджет записи: клиент сам выбирает время
    form: bool = False               # хотя бы форма заявки

    def booking_note(self) -> list[str]:
        """Как на сайте записываются — отдельно от того, на чём он сделан.

        Свежая Tilda без записи — такой же повод для разговора, как старый
        самопис: пока записи нет, клиент пишет в мессенджер и ждёт ответа
        администратора.
        """
        if self.booking:
            return []
        if self.form:
            return ["на сайте только форма заявки, времени не выбрать"]
        return ["на сайте нельзя записаться — только мессенджер или звонок"]

    def summary(self) -> list[str]:
        """Человеческие формулировки — идут и в подсказку, и в промпт модели."""
        no_booking = self.booking_note()

        if self.legacy_builder:
            return ["сайт на устаревшем конструкторе (uCoz, Nethouse и подобные)"] + no_booking
        if self.builder:
            # У современного конструктора весь стек свой, обсуждать его нечего.
            return ["сайт на конструкторе"] + no_booking

        out: list[str] = list(no_booking)
        if not self.responsive:
            out.append("нет мобильной вёрстки")
        if self.no_tls:
            out.append("работает без HTTPS")
        if self.jquery_old:
            out.append(f"jQuery {self.jquery} — библиотека десятилетней давности")
        if self.table_layout:
            out.append("вёрстка таблицами")
        if self.php_links:
            out.append("ссылки на .php")
        if self.generator:
            out.append(f"CMS: {self.generator}")
        return out

    @property
    def outdated(self) -> bool:
        """Явно устаревший стек — кандидат на редизайн.

        На современном конструкторе признаки стека ничего не значат: Tilda сама
        отдаёт jQuery 1.10 со своего CDN, и по нему любой её сайт выглядел бы
        десятилетним. Такие идут отдельной, более мягкой пометкой. А вот
        платформа нулевых устарела сама по себе — тут признаки не нужны.
        """
        if self.legacy_builder:
            return True
        if self.builder:
            return False
        return (
            not self.responsive
            or self.no_tls
            or self.jquery_old
            or self.table_layout
            or self.php_links
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
    tech: TechSignals = field(default_factory=TechSignals)
    reasons: list[str] = field(default_factory=list)


def _tech(html: str, url: str) -> TechSignals:
    """Разобрать сырой HTML на признаки стека. Тот же проход, без новых запросов."""
    t = TechSignals()
    t.responsive = bool(_VIEWPORT.search(html))
    t.php_links = bool(_PHP_LINKS.search(html))
    t.table_layout = bool(_TABLE_LAYOUT.search(html))
    t.builder = bool(_BUILDER.search(html))
    t.legacy_builder = bool(_BUILDER_LEGACY.search(html))
    t.booking = bool(_BOOKING_PLATFORM.search(html))
    t.form = bool(_FORM.search(html))
    t.no_tls = url.lower().startswith("http://")

    m = _JQUERY.search(html)
    if m:
        major, minor = int(m.group(1)), int(m.group(2))
        t.jquery = f"{major}.{minor}"
        t.jquery_old = major < 3

    g = _GENERATOR.search(html)
    if g:
        t.generator = g.group(1).strip()[:60]
    return t


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

    html = resp.text[:400_000]
    text, last_year, chain = _analyze(html)
    res.ok = True
    res.text = text
    res.text_len = len(text)
    res.last_year = last_year
    res.chain_hint = chain
    # Итоговый адрес, а не исходный: сайт мог увести с http на https.
    res.tech = _tech(html, str(resp.url))
    res.reasons.extend(res.tech.summary())

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
