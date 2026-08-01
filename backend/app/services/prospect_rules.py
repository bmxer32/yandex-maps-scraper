"""
Механический отбор: то, что видно без единого сетевого запроса.

Правило всей подсистемы — ничего не выбрасывать. Здесь только расставляются
метки и причины; решение всегда остаётся за человеком, а неуверенность
трактуется в пользу клиента.

Две независимые оси, их принципиально нельзя смешивать:

* **demo**  — можно ли собрать базу знаний автоматом (нужен обходимый сайт);
* **verdict** — стоит ли вообще писать этой компании.

Школа с одной страницей ВКонтакте вместо сайта плоха по первой оси и при этом
лучший клиент по второй: ассистент нужнее всех тому, у кого нет даже сайта.
Свести оси в одну — значит выкинуть самый нуждающийся сегмент.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Optional
from urllib.parse import urlparse

from ..models.schemas import Organization

# --- Что на самом деле лежит в поле «сайт» -------------------------------
# На выгрузке языковых школ Краснодара таких оказалось 9 из 30.
_SOCIAL = re.compile(
    r"(^|\.)(vk\.(ru|com)|vkontakte\.ru|max\.ru|t\.me|telegram\.me|instagram\.com"
    r"|facebook\.com|ok\.ru|youtube\.com|tiktok\.com|wa\.me|api\.whatsapp\.com)$",
    re.IGNORECASE,
)
_BOOKING = re.compile(
    r"(^|\.)(yclients\.com|clients\.site|dikidi\.(net|ru)|n\d{5,}\.\w+)",
    re.IGNORECASE,
)
_BUILDER = re.compile(
    r"(^|\.)(tilda\.ws|wixsite\.com|business\.site|taplink\.\w+|nethouse\.ru"
    r"|umi\.ru|a5\.ru|ucoz\.\w+|jimdosite\.com)$",
    re.IGNORECASE,
)

LINK_OWN = "own"
LINK_SOCIAL = "social"
LINK_BOOKING = "booking"
LINK_BUILDER = "builder"
LINK_NONE = "none"

_LINK_LABELS = {
    LINK_SOCIAL: "вместо сайта — страница в соцсети",
    LINK_BOOKING: "вместо сайта — виджет онлайн-записи",
    LINK_BUILDER: "сайт на конструкторе, страниц обычно мало",
    LINK_NONE: "сайта нет",
}

# Демо собирается автоматом только по своему сайту.
DEMO_AUTO = "auto"
DEMO_MANUAL = "manual"

# Перспективность клиента. «maybe» — состояние по умолчанию для всего,
# в чём нет уверенности: терять клиента из-за догадки дороже, чем лишний раз
# показать его человеку.
VERDICT_GOOD = "good"
VERDICT_MAYBE = "maybe"
VERDICT_SKIP = "skip"


def site_key(url: Optional[str]) -> str:
    """Домен без схемы, www и хвостового слэша — ключ склейки и кэша.

    Зеркалит `siteKey` из frontend/lib/utils.ts: обе стороны должны считать
    один и тот же ключ, иначе вердикт не сойдётся со строкой таблицы.
    """
    if not url:
        return ""
    raw = url.strip().lower()
    host = urlparse(raw if "//" in raw else f"//{raw}").netloc or raw
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def classify_link(url: Optional[str]) -> str:
    """Что лежит в поле «сайт»: свой сайт, соцсеть, виджет записи, конструктор."""
    host = site_key(url)
    if not host:
        return LINK_NONE
    if _SOCIAL.search(host):
        return LINK_SOCIAL
    if _BOOKING.search(host):
        return LINK_BOOKING
    if _BUILDER.search(host):
        return LINK_BUILDER
    return LINK_OWN


def has_messenger(org: Organization) -> bool:
    """Есть ли канал доставки ссылки — телеграм или whatsapp в соцсетях."""
    blob = " ".join(org.socials or []).lower()
    return any(k in blob for k in ("telegram", "t.me", "whatsapp", "wa.me"))


def find_duplicates(orgs: Iterable[Organization]) -> dict[int, str]:
    """Индекс организации → на какую запись она похожа.

    Яндекс отдаёт у одной компании несколько карточек (разные филиалы, старые
    записи). На выгрузке школ так задвоились четыре компании. Это не повод
    считать их плохими — просто демо им нужно одно, а не два.
    """
    items = list(orgs)
    by_host: dict[str, int] = {}
    by_name: dict[str, int] = {}
    dupes: dict[int, str] = {}

    for i, org in enumerate(items):
        host = site_key(org.website)
        # Соцсети и виджеты записи специально не склеиваем по домену: vk.ru
        # общий у всех, иначе половина выдачи стала бы «дублями».
        if host and classify_link(org.website) == LINK_OWN:
            if host in by_host:
                dupes[i] = items[by_host[host]].name
                continue
            by_host[host] = i

        name = re.sub(r"[^\w]+", "", (org.name or "").lower())
        if name:
            if name in by_name:
                dupes.setdefault(i, items[by_name[name]].name)
            else:
                by_name[name] = i

    return dupes


def evaluate(
    org: Organization,
    *,
    duplicate_of: Optional[str] = None,
    min_reviews: int = 5,
) -> dict:
    """Первая ступень: метки и причины без единого запроса в сеть.

    Возвращает заготовку вердикта. Ступени 2 и 3 её уточняют, но понизить
    до «мимо» может только явная причина — не догадка.
    """
    kind = classify_link(org.website)
    reasons: list[str] = []

    demo = DEMO_AUTO if kind == LINK_OWN else DEMO_MANUAL
    if kind != LINK_OWN:
        reasons.append(_LINK_LABELS[kind])

    # Осознанно не понижаем вердикт из-за отсутствия сайта: это довод в пользу
    # клиента, а не против него. Меняется только способ подачи демо.
    verdict = VERDICT_MAYBE

    reviews = org.reviews_count or 0
    if reviews >= max(min_reviews, 1) * 2:
        verdict = VERDICT_GOOD
        reasons.append(f"отзывов {reviews} — бизнес живой")
    elif reviews >= min_reviews:
        verdict = VERDICT_GOOD
        reasons.append(f"отзывов {reviews}")
    elif reviews == 0:
        reasons.append("нет отзывов — возможно, новые или карточка заброшена")
    else:
        reasons.append(f"мало отзывов ({reviews})")

    if duplicate_of:
        reasons.append(f"похоже на дубль карточки «{duplicate_of}»")

    if has_messenger(org):
        reasons.append("есть мессенджер для связи")

    return {
        "link_kind": kind,
        "demo": demo,
        "verdict": verdict,
        "reasons": reasons,
        "duplicate_of": duplicate_of,
    }
