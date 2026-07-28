"""
Антидетект-слой: маскируем headless-браузер под живого пользователя.
Цель — не словить бан Яндекса на первых же запросах.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from playwright.async_api import Browser, BrowserContext, Page

# playwright-stealth 2.x применяет патчи автоматически через Stealth().use_async(),
# поэтому ручной вызов не нужен. Импортируем, чтобы проверить доступность.
try:
    from playwright_stealth import Stealth
    _HAS_STEALTH = True
except Exception:                       # pragma: no cover
    Stealth = None                      # type: ignore
    _HAS_STEALTH = False


# Реалистичные десктоп-конфигурации: разрешение + соответствующий UA
_DESKTOP_PROFILES = [
    {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/129.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1920, "height": 1080},
        "locale": "ru-RU",
        "timezone": "Europe/Moscow",
        "platform": "Win32",
    },
    {
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/129.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1680, "height": 1050},
        "locale": "ru-RU",
        "timezone": "Europe/Moscow",
        "platform": "MacIntel",
    },
    {
        "user_agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1600, "height": 900},
        "locale": "ru-RU",
        "timezone": "Europe/Moscow",
        "platform": "Linux x86_64",
    },
]


@dataclass
class BrowserProfile:
    user_agent: str
    viewport: dict
    locale: str
    timezone: str
    platform: str

    @classmethod
    def random(cls) -> "BrowserProfile":
        return cls(**random.choice(_DESKTOP_PROFILES))


def make_stealth():
    """Вернёт объект Stealth для обёртки async_playwright(), либо None."""
    if not _HAS_STEALTH:
        return None
    try:
        return Stealth()
    except Exception:
        return None


async def human_delay(min_s: float, max_s: float) -> float:
    """Случайная 'человеческая' пауза. Возвращает длительность."""
    delay = random.uniform(min_s, max_s)
    import asyncio
    await asyncio.sleep(delay)
    return delay


async def human_scroll(page: Page, selector: str = "body") -> None:
    """Плавный скролл с рандомными шагами — как живой пользователь."""
    import asyncio
    steps = random.randint(3, 6)
    for _ in range(steps):
        delta = random.randint(250, 700)
        await page.mouse.wheel(0, delta)
        await asyncio.sleep(random.uniform(0.25, 0.7))


async def build_context(
    browser: Browser,
    profile: BrowserProfile,
    proxy_url: str | None = None,
) -> BrowserContext:
    """Создать контекст браузера с заданным профилем и (опц.) прокси."""
    context_kwargs: dict = {
        "user_agent": profile.user_agent,
        "viewport": profile.viewport,
        "locale": profile.locale,
        "timezone_id": profile.timezone,
        "java_script_enabled": True,
        "ignore_https_errors": True,
    }
    if proxy_url:
        context_kwargs["proxy"] = _parse_proxy_url(proxy_url)
    return await browser.new_context(**context_kwargs)


def _parse_proxy_url(url: str) -> dict:
    """'http://user:pass@host:port' -> {'server':..., 'username':..., 'password':...}"""
    from urllib.parse import urlparse
    p = urlparse(url)
    out: dict = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
    if p.username:
        out["username"] = p.username
    if p.password:
        out["password"] = p.password
    return out
