"""
Простой round-robin пул прокси.
LO выбрал старт без платного API, но если Яндекс начнёт душнить —
сюда просто кладём список прокси, и парсер будет их крутить.
"""
from __future__ import annotations

import itertools
from typing import Optional

from ...config import settings


class ProxyPool:
    """Циклический итератор по прокси. Thread-safe в рамках asyncio."""

    def __init__(self, proxies: Optional[list[str]] = None) -> None:
        self._proxies: list[str] = list(proxies or settings.proxies)
        self._cycle = itertools.cycle(self._proxies) if self._proxies else None
        self._rotate_every: int = max(0, settings.rotate_every)
        self._counter: int = 0

    @property
    def has_proxies(self) -> bool:
        return bool(self._proxies)

    def next(self) -> Optional[str]:
        """Вернуть следующий прокси (или None, если пул пуст)."""
        if not self._cycle:
            return None
        self._counter += 1
        return next(self._cycle)

    def should_rotate(self, requests_done: int) -> bool:
        """Решает, не пора ли сменить прокси по счётчику запросов."""
        if not self.has_proxies or self._rotate_every <= 0:
            return False
        return requests_done > 0 and requests_done % self._rotate_every == 0


proxy_pool = ProxyPool()
