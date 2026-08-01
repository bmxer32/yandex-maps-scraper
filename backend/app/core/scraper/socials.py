"""
Проверка и нормализация ссылок на соцсети.

Извлечение из карточки и с сайта хватало всё, что похоже на соцсеть, включая
мусор: в выгрузке оказались `t.me/Салон` (юзернеймов кириллицей не бывает) и
`t.me/79110011147` (телефон без плюса не резолвится). Telegram на любой
несуществующий адрес отдаёт свою главную — клиент жал на «Telegram» и попадал
на telegram.org.

Правило: ссылка, ведущая не на аккаунт, а на сам сервис, бесполезна. Лучше
пустая ячейка, чем ссылка, которая никуда не ведёт.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

# Юзернейм в Telegram: латиница, начинается с буквы, 5–32 символа.
_TG_USERNAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{4,31}$")
# Приглашения в закрытые чаты и телефонные ссылки.
_TG_INVITE = re.compile(r"^\+[\w-]{5,}$")
_DIGITS = re.compile(r"^\d{7,15}$")

# Служебные пути, которые аккаунтом не являются.
_SERVICE_PATHS = {
    "", "share", "share/url", "login", "about", "faq", "apps", "download",
    "privacy", "terms", "press", "blog", "home", "explore", "signup",
    "accounts", "login.php", "sharer", "sharer.php", "intent", "help",
}


def _to_international(digits: str) -> str:
    """Российский номер в местной записи — к международной.

    В карточках телефон часто записан как 8 900 …, а Telegram и WhatsApp
    понимают только международный формат: ссылка на `+8900…` не откроется.
    """
    if len(digits) == 11 and digits.startswith("8"):
        return "7" + digits[1:]
    if len(digits) == 10 and digits.startswith("9"):
        return "7" + digits
    return digits


def _clean_path(url: str) -> str:
    """Путь без ведущего/хвостового слэша и без query."""
    parsed = urlparse(url)
    return parsed.path.strip("/").lower()


def normalize_social(label: str, url: str) -> Optional[str]:
    """Привести ссылку к рабочему виду или отбросить.

    Возвращает готовую строку «Label: url» либо None, если ссылка ведёт не на
    аккаунт компании. Телефон в Telegram без плюса — единственный случай, где
    чиним, а не выбрасываем: юзернейм не может состоять из одних цифр, значит
    это однозначно номер, и правильная форма ссылки `t.me/+<номер>`.
    """
    if not url or not url.startswith(("http://", "https://")):
        return None

    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = _clean_path(url)

    # Ссылка на сам сервис без аккаунта — бесполезна.
    if path in _SERVICE_PATHS:
        return None

    if host in ("t.me", "telegram.me", "telegram.org"):
        first = path.split("/")[0]
        if _DIGITS.match(first):
            # Телефон без плюса: t.me/79110011147 не резолвится, t.me/+79... да.
            return f"{label}: https://t.me/+{_to_international(first)}"
        if _TG_INVITE.match(first) or first.startswith("joinchat"):
            return f"{label}: {url}"
        if not _TG_USERNAME.match(first):
            # Кириллица, слишком коротко, начинается с цифры — не юзернейм.
            return None
        return f"{label}: {url}"

    if host in ("wa.me", "api.whatsapp.com", "whatsapp.com"):
        digits = re.sub(r"\D", "", path or urlparse(url).query)
        if not _DIGITS.match(digits):
            return None
        return f"{label}: https://wa.me/{_to_international(digits)}"

    if host in ("vk.com", "vkontakte.ru", "vk.ru", "ok.ru", "odnoklassniki.ru",
                "instagram.com", "facebook.com", "fb.com", "tiktok.com",
                "youtube.com", "youtu.be", "dzen.ru"):
        # Для остальных достаточно, чтобы был непустой не-служебный путь.
        return f"{label}: {url}" if path else None

    return f"{label}: {url}"


def normalize_all(socials: list[str]) -> list[str]:
    """Прогнать готовый список «Label: url» через проверку."""
    out: set[str] = set()
    for item in socials or []:
        label, _, url = item.partition(":")
        fixed = normalize_social(label.strip(), url.strip())
        if fixed:
            out.add(fixed)
    return sorted(out)


__all__ = ["normalize_social", "normalize_all"]
