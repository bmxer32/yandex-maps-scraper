"""
Ядро парсера Яндекс.Карт (v2).

КАК РАБОТАЕТ (выяснено эмпирически в 2026):
- yandex.ru/maps редиректит на yandex.com/maps — используем .com сразу.
- Данные организаций рендерятся SERVER-SIDE прямо в HTML страницы.
  Структура: JSON-массив "items":[{"type":"business","title":...,
  "address":...,"coordinates":[lon,lat],"uri":"ymapsbm1://org?oid=<id>",
  "phones":[...],"features":[...],"workingHours":...,"ratingValue":...}]
- Для пагинации скроллим боковой список — новые организации добавляются в DOM.
- САЙТ и соцсети в превью отсутствуют → для них открываем карточку
  https://yandex.com/maps/org/<oid>/ по мере необходимости.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Awaitable, Callable, Optional

from loguru import logger
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PWTimeout,
    async_playwright,
)

from ...config import settings
from ...models.schemas import Organization, SearchRequest, TaskStage
from .anti_detect import (
    BrowserProfile,
    build_context,
    human_delay,
    human_scroll,
    make_stealth,
)
from .proxy_pool import proxy_pool


BASE_URL = "https://yandex.com/maps/"
ORG_CARD_URL = "https://yandex.com/maps/org/{oid}/"

ProgressCb = Callable[[TaskStage, int, int, int, int, str], Awaitable[None]]


class YandexMapsScraper:
    """Один запуск = одна поисковая сессия в headless-браузере."""

    def __init__(self) -> None:
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        # oid -> Organization
        self._found: dict[str, Organization] = {}

    # ------------------------------------------------------------------ API
    async def run(
        self,
        request: SearchRequest,
        geo_text: str,
        on_progress: Optional[ProgressCb] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> list[Organization]:
        query = _build_query(request.category, geo_text)
        logger.info("YandexMapsScraper: запрос = '{}'", query)

        try:
            # ВАЖНО: не оборачиваем async_playwright() в Stealth().use_async() —
            # в playwright-stealth 2.x эта обёртка конфликтует с загрузкой
            # страницы Яндекса (данные не доходят). Базовой маскировки через
            # navigator.webdriver init-script достаточно — yandex.com отдаёт
            # SSR-HTML с организациями без вопросов.
            async with async_playwright() as pw:
                self._browser = await pw.chromium.launch(
                    headless=settings.headless,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                    ],
                )
                await self._open_context_and_page()

                await self._emit(
                    on_progress,
                    TaskStage.PARSING_LIST, 0, request.limit, 0, 0,
                    f"Открываю карты: «{query}»",
                )
                await self._goto_search(query, cancel_event)
                await human_delay(settings.min_delay, settings.max_delay)

                # ---- Этап 1: листаем выдачу, парсим HTML ----
                await self._scroll_and_collect(
                    limit=request.limit,
                    on_progress=on_progress,
                    cancel_event=cancel_event,
                )

                # ---- Этап 2: достаём сайт/соцсети из карточек ----
                if request.fetch_websites:
                    await self._fill_missing_details(
                        request=request,
                        on_progress=on_progress,
                        cancel_event=cancel_event,
                    )

                results = list(self._found.values())[: request.limit]
                await self._emit(
                    on_progress,
                    TaskStage.PARSING_LIST,
                    len(results), len(results),
                    sum(1 for o in results if o.website),
                    sum(1 for o in results if not o.website),
                    "Парсинг Яндекс.Карт завершён",
                )
                return results

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Ошибка парсинга: {}", e)
            raise
        finally:
            await self._close()

    # ---------------------------------------------------- навигация / сбор

    async def _open_context_and_page(self) -> None:
        profile = BrowserProfile.random()
        proxy_url = proxy_pool.next()
        self._context = await build_context(self._browser, profile, proxy_url)
        await self._context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages',
                {get: () => ['ru-RU', 'ru', 'en-US', 'en']});
            Object.defineProperty(navigator, 'plugins',
                {get: () => [1,2,3,4,5]});
            """
        )
        self._page = await self._context.new_page()

    async def _goto_search(
        self,
        query: str,
        cancel_event: Optional[asyncio.Event],
    ) -> None:
        from urllib.parse import quote_plus
        url = f"{BASE_URL}?text={quote_plus(query)}"
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except PWTimeout:
            logger.warning("goto timeout, продолжаем собирать что есть")
        # Даём React-приложению отрисовать выдачу
        try:
            await self._page.wait_for_selector(
                "[class*='search'], [class*='business'], [class*='list']",
                timeout=12000,
            )
        except PWTimeout:
            pass
        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError()

    async def _scroll_and_collect(
        self,
        limit: int,
        on_progress: Optional[ProgressCb],
        cancel_event: Optional[asyncio.Event],
    ) -> None:
        """
        Скроллим боковой список выдачи. После каждой порции скролла берём
        page.content() и экстрактим организации. Новые (по oid) добавляем.
        """
        last_count = -1
        no_progress = 0
        max_rounds = max(30, limit // 10 + 5)

        for rnd in range(max_rounds):
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError()

            html = await self._page.content()
            added = self._extract_from_html(html)

            cur = len(self._found)
            with_site = sum(1 for o in self._found.values() if o.website)
            await self._emit(
                on_progress,
                TaskStage.PARSING_LIST,
                cur, limit,
                with_site, cur - with_site,
                f"Листаю выдачу… раунд {rnd + 1}, найдено {cur} (+{added})",
            )

            if cur >= limit:
                break
            if cur == last_count:
                no_progress += 1
                if no_progress >= 3:
                    logger.info("Выдача исчерпана на {} организациях", cur)
                    break
            else:
                no_progress = 0
            last_count = cur

            # Скроллим боковую панель выдачи
            await self._scroll_results_panel()
            await human_delay(settings.min_delay * 0.6, settings.max_delay * 0.7)

    async def _scroll_results_panel(self) -> None:
        """
        Скроллим именно панель списка организаций (а не всю страницу).
        У Яндекс.Карт контейнер выдачи имеет классы вида *search*list* / *scroll*.
        Пробуем несколько селекторов.
        """
        candidates = [
            "[class*='search-list']",
            "[class*='search-results']",
            "[class*='business-list']",
            "[class*='scroll__container']",
            "[class*='list-view']",
            "aside",
            "[class*='sidebar']",
        ]
        for sel in candidates:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    await el.evaluate(
                        "el => el.scrollTo(0, el.scrollHeight)"
                    )
                    return
            except Exception:
                continue
        # fallback — колесо мыши над панелью
        await human_scroll(self._page)

    # -------------------------------------------------- HTML-экстракция

    def _extract_from_html(self, html: str) -> int:
        """
        Достаём организации из HTML. Возвращаем сколько добавили.
        Стратегия: находим "items":[ ... ] и парсим сбалансированный JSON.
        """
        added = 0
        # 1) Пробуем найти массив items (основной путь)
        items = _extract_items_array(html)
        if items:
            for raw in items:
                org = _item_to_organization(raw)
                if org and org.permalink and org.permalink not in self._found:
                    self._found[org.permalink] = org
                    added += 1
                elif org and not org.permalink:
                    key = f"noid::{org.name}::{org.address}"
                    if key not in self._found:
                        self._found[key] = org
                        added += 1
            if added:
                return added

        # 2) Fallback: per-org extraction через uri-маркер
        for match in re.finditer(
            r'"uri"\s*:\s*"ymapsbm1://org\?oid=(\d+)"', html
        ):
            oid = match.group(1)
            if oid in self._found:
                continue
            # Контекст ± 4 КБ вокруг URI
            start = max(0, match.start() - 4000)
            end = min(len(html), match.end() + 4000)
            chunk = html[start:end]
            org = _chunk_to_organization(chunk, oid)
            if org:
                self._found[oid] = org
                added += 1
        return added

    # ---------------------------------------------- сайт / соцсети (карточки)

    async def _fill_missing_details(
        self,
        request: SearchRequest,
        on_progress: Optional[ProgressCb],
        cancel_event: Optional[asyncio.Event],
    ) -> None:
        # Сайт почти всегда отсутствует в превью — достаём из карточек.
        missing = [
            o for o in self._found.values()
            if o.permalink and o.permalink.isdigit() and not o.website
        ]
        if not missing:
            return

        total = len(missing)
        await self._emit(
            on_progress,
            TaskStage.PARSING_CARDS,
            0, total, 0, 0,
            f"Открываю {total} карточек за сайтами и соцсетями…",
        )

        for idx, org in enumerate(missing, start=1):
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError()
            try:
                await self._open_business_card(org)
            except Exception as e:  # noqa: BLE001
                logger.debug("card open failed for {}: {}", org.permalink, e)

            with_site = sum(1 for o in self._found.values() if o.website)
            without_site = len(self._found) - with_site
            await self._emit(
                on_progress,
                TaskStage.PARSING_CARDS,
                idx, total, with_site, without_site,
                f"Карточка {idx}/{total}",
            )
            await human_delay(settings.min_delay * 0.5, settings.max_delay * 0.6)

    async def _open_business_card(self, org: Organization) -> None:
        """
        Открываем страницу организации https://yandex.com/maps/org/<oid>/
        и достаём сайт + соцсети из SSR-HTML карточки.
        """
        if not org.permalink or not org.permalink.isdigit():
            return
        url = ORG_CARD_URL.format(oid=org.permalink)
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PWTimeout:
            return
        try:
            await self._page.wait_for_selector(
                "[class*='business'], [class*='card'], [class*='tabs']",
                timeout=8000,
            )
        except PWTimeout:
            pass

        html = await self._page.content()
        _enrich_from_card_html(org, html)

    # ------------------------------------------------------------- helpers

    async def _emit(
        self,
        on_progress: Optional[ProgressCb],
        stage: TaskStage,
        processed: int,
        total: int,
        with_website: int,
        without_website: int,
        message: str,
    ) -> None:
        if on_progress is None:
            return
        try:
            await on_progress(
                stage, processed, total, with_website, without_website, message
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("progress cb error: {}", e)

    async def _close(self) -> None:
        for closer in (self._page, self._context, self._browser):
            try:
                if closer is not None:
                    await closer.close()
            except Exception:
                pass
        self._page = self._context = self._browser = None


# ===========================================================================
# Чистые функции парсинга (тестируемые без браузера)
# ===========================================================================

def _build_query(category: str, geo_text: str) -> str:
    parts = [p.strip() for p in (category, geo_text) if p and p.strip()]
    return ", ".join(parts)


def _extract_items_array(html: str) -> list[dict]:
    """
    Найти в HTML массив "items":[ {...}, {...} ] и распарсить его.
    Используем ручной баланс скобок — json.loads не справится с обрезанным JSON.
    """
    results: list[dict] = []
    needle = '"items":['
    pos = 0
    while True:
        idx = html.find(needle, pos)
        if idx < 0:
            break
        start = idx + len(needle) - 1   # указывает на '['
        arr = _read_balanced(html, start, '[', ']')
        if arr:
            try:
                parsed = json.loads(arr)
                if isinstance(parsed, list):
                    results.extend(x for x in parsed if isinstance(x, dict))
            except json.JSONDecodeError:
                # Может быть обрезано — попробуем починить хвост
                fixed = _try_repair_json(arr)
                if fixed:
                    try:
                        parsed = json.loads(fixed)
                        if isinstance(parsed, list):
                            results.extend(x for x in parsed if isinstance(x, dict))
                    except json.JSONDecodeError:
                        pass
        pos = idx + len(needle)
        if len(results) > 5000:        # защита от безумного HTML
            break
    return results


def _read_balanced(s: str, start: int, open_ch: str, close_ch: str) -> Optional[str]:
    """
    Начиная с позиции start (где s[start] == open_ch) прочитать подстроку
    до парной закрывающей скобки, учитывая строки и вложенность.
    """
    if start >= len(s) or s[start] != open_ch:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if escape:
            escape = False
            continue
        if ch == '\\' and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def _try_repair_json(text: str) -> Optional[str]:
    """Обрезанный JSON — пытаемся закрыть скобки, чтобы он стал валидным."""
    open_sq = text.count('[') - text.count(']')
    open_cu = text.count('{') - text.count('}')
    # обрезаем возможный мусор в конце
    last_close = max(text.rfind('}'), text.rfind(']'))
    if last_close > 0:
        candidate = text[: last_close + 1] + (']' * open_sq) + ('}' * open_cu)
        return candidate
    return None


def _item_to_organization(item: dict) -> Optional[Organization]:
    """Превратить один элемент массива items в Organization."""
    if item.get("type") not in ("business", None):
        return None
    title = item.get("title")
    if not title:
        return None

    oid = item.get("id") or _oid_from_uri(item.get("uri") or "")

    coords = item.get("coordinates") or item.get("displayCoordinates")
    lat = lon = None
    if isinstance(coords, list) and len(coords) == 2:
        lon, lat = coords[0], coords[1]

    phones = item.get("phones") or []
    phone = None
    if phones and isinstance(phones, list):
        first = phones[0]
        phone = first.get("number") or first.get("value") if isinstance(first, dict) else str(first)

    # Рубрики
    cats: list[str] = []
    raw_cats = item.get("rubrics") or item.get("categories")
    if isinstance(raw_cats, list):
        cats = [c.get("name") if isinstance(c, dict) else str(c) for c in raw_cats]
    # features — дополнительные услуги/категории
    feats = item.get("features")
    if isinstance(feats, list) and not cats:
        cats = [f.get("name") for f in feats
                if isinstance(f, dict) and f.get("name")]

    # Рейтинг и отзывы — лежат во вложенном ratingData
    rating_data = item.get("ratingData") or {}
    if not isinstance(rating_data, dict):
        rating_data = {}
    rating = rating_data.get("ratingValue") or item.get("ratingValue") or item.get("rating")
    if isinstance(rating, dict):
        rating = rating.get("value")
    reviews = (
        rating_data.get("reviewCount")
        or rating_data.get("ratingCount")
        or item.get("numberOfVotes")
        or item.get("reviewsCount")
    )

    hours = item.get("workingHours") or item.get("hours")
    if isinstance(hours, list):
        # [{"type":"openHours","text":"Открыто до 21:00",...}]
        hours_text = next(
            (h.get("text") or h.get("short_text")
             for h in hours if isinstance(h, dict) and (h.get("text") or h.get("short_text"))),
            None,
        )
        hours = hours_text

    # Соцсети: в превью их нет — достаём позже из карточки организации.
    # (metrika.goals — общие цели счётчика, не персональные ссылки.)
    socials: list[str] = []

    return Organization(
        name=str(title),
        address=item.get("address") or item.get("description"),
        lat=float(lat) if lat is not None else None,
        lon=float(lon) if lon is not None else None,
        phone=str(phone) if phone else None,
        website=None,                # почти всегда отсутствует в превью
        email=None,
        socials=socials,
        hours=str(hours) if hours else None,
        rating=float(rating) if rating is not None else None,
        reviews_count=int(reviews) if reviews is not None else None,
        categories=cats,
        permalink=str(oid) if oid else None,
    )


def _chunk_to_organization(chunk: str, oid: str) -> Optional[Organization]:
    """Fallback: когда массив items не распарсился, собираем поля по regex."""
    title = _re_first(chunk, r'"title"\s*:\s*"([^"]{2,200})"')
    if not title:
        return None
    address = _re_first(chunk, r'"address"\s*:\s*"([^"]{2,400})"') \
        or _re_first(chunk, r'"description"\s*:\s*"([^"]{2,400})"')
    phone_m = re.search(
        r'"phones"\s*:\s*\[\s*\{[^}]*"value"\s*:\s*"([^"]+)"', chunk
    )
    phone = phone_m.group(1) if phone_m else None
    coords_m = re.search(
        r'"coordinates"\s*:\s*\[\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\]', chunk
    )
    lat = float(coords_m.group(2)) if coords_m else None
    lon = float(coords_m.group(1)) if coords_m else None
    rating_m = re.search(r'"ratingValue"\s*:\s*([-\d.]+)', chunk)
    rating = float(rating_m.group(1)) if rating_m else None
    return Organization(
        name=title,
        address=address,
        lat=lat, lon=lon,
        phone=phone,
        website=None,
        categories=[],
        rating=rating,
        permalink=oid,
    )


def _enrich_from_card_html(org: Organization, html: str) -> None:
    """
    Из SSR-HTML карточки организации достаём сайт, email, соцсети, телефон.
    Карточка содержит обычные <a href> ссылки: сайт организации — первая
    ссылка, которая НЕ ведёт на Яндекс/метрику/соцсеть.
    """
    # Домены, которые НЕ являются сайтом организации
    _NON_SITE = (
        "yandex.", "ya.ru", "yastatic", "avatars.mds", "clck",
        "passport", "metrika", "mc.yandex", "an.yandex", "adsystem",
        "static-mon", "surveys.yandex", "bing.com", "google.com",
        "apple.com", "maps.yandex",
    )
    _SOCIAL_DOMAINS = (
        "vk.com", "vkontakte.ru", "t.me", "telegram.me", "ok.ru",
        "odnoklassniki.ru", "instagram.com", "facebook.com", "fb.com",
        "wa.me", "whatsapp.com", "youtube.com", "youtu.be", "tiktok.com",
        "dzen.ru", "viber.com",
    )

    # --- Собираем все ссылки в карточке ---
    all_links = re.findall(r'href="(https?://[^"\s<>]+)"', html)

    if not org.website:
        # Сайт = первая ссылка, не Яндекс/метрика/соцсеть/почта
        for href in all_links:
            host = re.sub(r"^https?://(www\.)?", "", href).split("/")[0].lower()
            if any(bad in host for bad in _NON_SITE):
                continue
            if any(soc in host for bad in _SOCIAL_DOMAINS for soc in [bad] if bad in host):
                continue
            if host.endswith(".png") or host.endswith(".jpg"):
                continue
            # Чистим UTM-мусор и Яндекс-трекинг из query
            clean = re.sub(r"[?&#].*$", "", href)
            # Декодируем HTML-сущности
            clean = clean.replace("&amp;", "&")
            org.website = clean
            break

    if not org.email:
        # email — ищем в mailto, потом в тексте (с блэклистом Яндекса/CDN)
        _EMAIL_BLACKLIST = ("yandex", "sentry", "example", "maps.yandex",
                            "vk-portal", "noreply", "no-reply",
                            "wixpress", ".png", ".jpg", "2x.png", "ugcres",
                            "@yandex-team", "donotreply")
        m = re.search(r'mailto:([\w.+-]+@[\w.-]+\.\w{2,})', html)
        if m and not any(b in m.group(1).lower() for b in _EMAIL_BLACKLIST):
            org.email = m.group(1)
        else:
            for em in re.findall(r'\b([\w.+-]+@[\w.-]+\.\w{2,})\b', html):
                if not any(b in em.lower() for b in _EMAIL_BLACKLIST):
                    org.email = em
                    break

    # --- Соцсети ---
    new_socials = set(org.socials)
    label_map = {
        "vk.com": "VK", "vkontakte.ru": "VK",
        "t.me": "Telegram", "telegram.me": "Telegram",
        "ok.ru": "Odnoklassniki", "odnoklassniki.ru": "Odnoklassniki",
        "instagram.com": "Instagram",
        "facebook.com": "Facebook", "fb.com": "Facebook",
        "wa.me": "WhatsApp", "whatsapp.com": "WhatsApp",
        "youtube.com": "YouTube", "youtu.be": "YouTube",
        "tiktok.com": "TikTok", "dzen.ru": "Dzen",
    }
    # Яндекса собственные соцсети/каналы — отбрасываем
    _YANDEX_SOCIAL_PATTERNS = (
        "yandex", "mapsyandex", "ya.ru", "yandex.maps",
    )
    for href in all_links:
        host = re.sub(r"^https?://(www\.)?", "", href).split("/")[0].lower()
        for dom, label in label_map.items():
            if host == dom or host.endswith("." + dom):
                # Проверяем, что это НЕ яндексовская страница в соцсети
                full_lower = href.lower()
                if any(p in full_lower for p in _YANDEX_SOCIAL_PATTERNS):
                    break
                new_socials.add(f"{label}: {href}")
                break
    org.socials = sorted(new_socials)

    if not org.phone:
        m = re.search(r'href="tel:\+?(\d[\d()\-\s]{6,20})"', html)
        if m:
            org.phone = "+" + re.sub(r"\D", "", m.group(1))


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _oid_from_uri(uri: str) -> Optional[str]:
    m = re.search(r'oid=(\d+)', uri)
    return m.group(1) if m else None


def _re_first(text: str, pattern: str) -> Optional[str]:
    m = re.search(pattern, text)
    return m.group(1) if m else None
