"""
Клиент к kb_assistant — сервису ИИ-ассистента.

Парсер даёт список организаций с сайтами; kb_assistant краулит сайт клиента
в базу знаний и выдаёт персональную демо-ссылку в Telegram. Здесь только
транспорт: ключ живёт на бэкенде и в браузер не попадает.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

import httpx
from loguru import logger

from ..config import settings

# Транслитерация для slug: имена организаций почти всегда кириллицей,
# а Telegram принимает в /start-параметре только [A-Za-z0-9_-].
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def make_slug(company_name: str, website: Optional[str] = None) -> str:
    """Собрать slug для деплинка: транслит названия + хвост хэша сайта.

    Хэш нужен, чтобы две «Стоматологии» из разных городов не столкнулись:
    slug уникален в базе kb_assistant, а названия организаций — нет.
    """
    lowered = (company_name or "").strip().lower()
    translit = "".join(_TRANSLIT.get(ch, ch) for ch in lowered)
    base = re.sub(r"[^a-z0-9]+", "_", translit).strip("_")[:40]
    if not base:
        base = "demo"

    seed = (website or company_name or "").strip().lower()
    suffix = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:6]
    return f"{base}_{suffix}"


def demo_link(slug: str) -> Optional[str]:
    """Готовая ссылка для клиента, если известен username бота."""
    if not settings.kb_bot_username:
        return None
    return f"https://t.me/{settings.kb_bot_username.lstrip('@')}?start={slug}"


class DemoClientError(RuntimeError):
    """kb_assistant недоступен или ответил ошибкой."""


class DemoClient:
    """Тонкая обёртка над REST kb_assistant (/api/v1/outreach)."""

    def __init__(self) -> None:
        if not settings.kb_enabled:
            raise DemoClientError(
                "Интеграция с kb_assistant не настроена: задайте KB_BASE_URL и KB_API_KEY"
            )
        root = settings.kb_base_url.rstrip("/")
        self._base = root + "/api/v1/outreach"
        self._health_url = root + "/api/v1/health/ready"
        self._headers = {"X-API-Key": settings.kb_api_key}
        self._timeout = settings.kb_timeout

    async def ping(self) -> bool:
        """Отвечает ли kb_assistant уже.

        Стек в Docker поднимается полминуты, поэтому «настроен» и «готов» —
        разные вещи: интерфейс на этот флаг показывает «ассистент запускается».
        """
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(self._health_url)
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self._base}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(method, url, headers=self._headers, **kwargs)
        except httpx.HTTPError as exc:
            logger.error("kb_assistant недоступен: {} {} — {}", method, url, exc)
            raise DemoClientError(f"kb_assistant недоступен: {exc}") from exc

        if resp.status_code >= 400:
            detail = _error_text(resp)
            logger.warning("kb_assistant {} {} -> {}: {}", method, url, resp.status_code, detail)
            raise DemoClientError(detail)

        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    async def provision(
        self,
        *,
        slug: str,
        company_name: str,
        site_url: str,
        max_pages: Optional[int] = None,
    ) -> dict:
        """Завести демо и запустить краул сайта в фоне."""
        return await self._request(
            "POST",
            "/provision",
            json={
                "slug": slug,
                "company_name": company_name,
                "site_url": site_url,
                "max_pages": max_pages or settings.kb_max_pages,
            },
        )

    async def by_slugs(self, slugs: list[str]) -> list[dict]:
        """Статусы пачки демо одним запросом — на страницу таблицы, не на строку."""
        if not slugs:
            return []
        data = await self._request("GET", "/targets/by-slug", params=[("slug", s) for s in slugs])
        return (data or {}).get("items", [])

    async def list_targets(self, *, opened_only: bool = False, limit: int = 200) -> list[dict]:
        """Все демо, недавно открытые сверху."""
        data = await self._request(
            "GET",
            "/targets",
            params={"opened_only": str(opened_only).lower(), "limit": limit},
        )
        return (data or {}).get("items", [])

    async def delete(self, slug: str, *, purge: bool = True) -> None:
        """Удалить демо вместе с собранной базой знаний.

        purge=True по умолчанию: демо удаляют, чтобы пересобрать сайт, и
        старые чанки иначе подмешались бы к новому обходу.
        """
        await self._request("DELETE", f"/targets/{slug}", params={"purge": str(purge).lower()})


def _error_text(resp: httpx.Response) -> str:
    """Достать человекочитаемую ошибку из ответа kb_assistant."""
    try:
        body = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}"
    for key in ("detail", "message", "error"):
        value = body.get(key) if isinstance(body, dict) else None
        if isinstance(value, str) and value:
            return value
    return f"HTTP {resp.status_code}"
