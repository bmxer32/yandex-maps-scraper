"""
Второй проход: для каждой организации, у которой есть сайт, открываем его
и достаём email + ссылки на соцсети. Делается через httpx (быстро, без
браузера) с ограничением параллелизма и таймаутами.

Осторожность:
- www.example.com и example.com считаем одним сайтом
- игнорируем mailto с заглушками (sentry, yandex-collect и т.п.)
- социальные ссылки распознаём по доменам
"""
from __future__ import annotations

import asyncio
import re
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger
from lxml import html as lxml_html

from ...config import settings
from .socials import normalize_all
from ...models.schemas import Organization, TaskStage


ProgressCb = "callable"  # псевдоним для читаемости


# Домены соцсетей, которые умеем распознавать
_SOCIAL_DOMAINS = {
    "vk.com": "VK",
    "vkontakte.ru": "VK",
    "t.me": "Telegram",
    "telegram.me": "Telegram",
    "ok.ru": "Odnoklassniki",
    "odnoklassniki.ru": "Odnoklassniki",
    "facebook.com": "Facebook",
    "fb.com": "Facebook",
    "instagram.com": "Instagram",
    "tiktok.com": "TikTok",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "wa.me": "WhatsApp",
    "whatsapp.com": "WhatsApp",
    "dzen.ru": "Dzen",
}

# Email-паттерн
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Почтовые заглушки, которые часто встречаются на сайтах и нам НЕ нужны
_EMAIL_BLACKLIST = (
    "sentry.io", "example.com", "yandex.ru/collect", "@sentry",
    ".png@", ".jpg@", ".gif@", "2x.png", "webp", "svg",
    # Технические ящики соцсетей/метрики/CDN
    "vk-portal.net", "@yandex-team", "@yandex.ru",
    "noreply", "no-reply", "donotreply",
    "@example", "@test", "@localhost",
    "@wixpress.com", "@ugcres.cdn",
    "sentry@",
)


async def enrich_organizations(
    orgs: list[Organization],
    on_progress=None,
    cancel_event: Optional[asyncio.Event] = None,
) -> list[Organization]:
    """
    Для организаций с website: идём на сайт, тащим email + соцсети.
    Возвращает тот же список (мутирует поля email/socials на месте).
    """
    targets = [o for o in orgs if o.website]
    if not targets:
        return orgs

    total = len(targets)
    sem = asyncio.Semaphore(settings.enrich_concurrency)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/129.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }

    async with httpx.AsyncClient(
        headers=headers,
        timeout=settings.site_timeout,
        follow_redirects=True,
        verify=False,
    ) as client:

        async def worker(idx: int, org: Organization) -> None:
            async with sem:
                if cancel_event and cancel_event.is_set():
                    raise asyncio.CancelledError()
                await _enrich_one(client, org)
                if on_progress is not None:
                    await on_progress(
                        TaskStage.ENRICHING_SITES,
                        idx, total,
                        0, 0,
                        f"Сайты: {idx}/{total}",
                    )

        tasks = [
            asyncio.create_task(worker(i + 1, o))
            for i, o in enumerate(targets)
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    return orgs


async def _enrich_one(client: httpx.AsyncClient, org: Organization) -> None:
    """Открыть сайт организации и достать email + соцсети."""
    try:
        # Нормализуем URL
        url = _normalize_url(org.website)
        if not url:
            return
        resp = await client.get(url)
        if resp.status_code >= 400:
            return
        html = resp.text
    except Exception as e:  # noqa: BLE001
        logger.debug("enrich site {} error: {}", org.website, e)
        return

    base = str(resp.url)
    tree = lxml_html.fromstring(html)

    # --- Email ---
    if not org.email:
        emails = set()
        # 1) mailto: ссылки
        for node in tree.xpath('//a[starts-with(@href,"mailto:")]'):
            mail = (node.get("href") or "").replace("mailto:", "")
            if mail and _is_good_email(mail):
                emails.add(mail.strip())
        # 2) email в тексте страницы
        if not emails:
            for match in _EMAIL_RE.findall(html):
                if _is_good_email(match):
                    emails.add(match)
        if emails:
            org.email = sorted(emails, key=len)[0]

    # --- Соцсети ---
    if not org.socials:
        socials: set[str] = set()
        for a in tree.xpath('//a[@href]'):
            href = a.get("href") or ""
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            full = urljoin(base, href)
            host = (urlparse(full).hostname or "").lower().lstrip("www.")
            for dom, label in _SOCIAL_DOMAINS.items():
                if host == dom or host.endswith("." + dom):
                    socials.add(f"{label}: {full}")
                    break
        if socials:
            org.socials = normalize_all(sorted(socials))


def _normalize_url(raw: str) -> Optional[str]:
    raw = raw.strip()
    if not raw:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = "http://" + raw
    parsed = urlparse(raw)
    if not parsed.hostname:
        return None
    return raw


def _is_good_email(email: str) -> bool:
    e = email.strip().lower()
    if not e or " " in e:
        return False
    if any(bad in e for bad in _EMAIL_BLACKLIST):
        return False
    if e.endswith((".png", ".jpg", ".gif", ".webp", ".svg")):
        return False
    return "@" in e and "." in e.split("@")[-1]
