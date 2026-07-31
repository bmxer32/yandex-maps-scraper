"""
Проверка интеграции с kb_assistant (персональные демо).

Запуск из папки backend:  python checks/demos_check.py

Сеть не трогаем: DemoClient подменяется заглушкой, проверяем контракт роутов
и генерацию slug. Pytest в проекте не используется — скрипт в стиле остальных
проверок (test_live.py, test_pipeline.py), но лежит вне backend/test_*.py,
который целиком в .gitignore, — иначе проверки терялись бы при клонировании.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

# Консоль Windows по умолчанию cp1251 — «галочки» в неё не влезают.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Скрипт лежит в backend/checks/, а пакет app — в backend/: без этого
# «python checks/demos_check.py» не найдёт app.config.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.services.demo_client import DemoClientError, demo_link, make_slug

_failures: list[str] = []


def check(condition: bool, label: str) -> None:
    if condition:
        print(f"  [ok]   {label}")
    else:
        print(f"  [FAIL] {label}")
        _failures.append(label)


# ---------------------------------------------------------------------------
# 1. Генерация slug
# ---------------------------------------------------------------------------
def test_slugs() -> None:
    print("\nslug из названия организации:")

    slug = make_slug("Стоматология «Люкс»", "https://lux-dent.ru")
    check(slug.startswith("stomatologiya_lyuks_"), f"кириллица транслитерируется: {slug}")
    check(
        all(c.isalnum() or c in "_-" for c in slug),
        "только символы, которые принимает Telegram в /start",
    )
    check(len(slug) <= 64, "укладывается в лимит Telegram (64 символа)")

    # Одинаковые названия в разных городах не должны схлопнуться в один slug:
    # slug уникален в базе kb_assistant, а названия организаций — нет.
    a = make_slug("Стоматология", "https://dent-msk.ru")
    b = make_slug("Стоматология", "https://dent-spb.ru")
    check(a != b, f"одинаковые названия с разными сайтами различаются: {a} / {b}")

    again = make_slug("Стоматология «Люкс»", "https://lux-dent.ru")
    check(slug == again, "slug стабилен между запусками")

    check(make_slug("", "https://x.ru").startswith("demo_"), "пустое название не ломает slug")
    check(make_slug("!!!", "https://x.ru").startswith("demo_"), "название без букв не ломает slug")


# ---------------------------------------------------------------------------
# 2. Ссылка на демо
# ---------------------------------------------------------------------------
def test_link() -> None:
    print("\nссылка для клиента:")

    settings.kb_bot_username = ""
    check(demo_link("acme") is None, "без username бота ссылки нет")

    settings.kb_bot_username = "@my_demo_bot"
    check(
        demo_link("acme") == "https://t.me/my_demo_bot?start=acme",
        "собачка в username отбрасывается",
    )


# ---------------------------------------------------------------------------
# 3. Роуты
# ---------------------------------------------------------------------------
async def test_routes() -> None:
    from app.api import demos as demos_mod
    from app.main import app

    transport = httpx.ASGITransport(app=app)

    # --- интеграция выключена ---
    print("\nинтеграция не настроена:")
    settings.kb_base_url = ""
    settings.kb_api_key = ""

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/demos/config")
        body = resp.json()
        check(resp.status_code == 200 and body["enabled"] is False,
              "config отдаёт enabled=false")
        check(body["ready"] is False, "ready=false, когда интеграции нет")

        resp = await c.post("/api/demos/provision",
                            json={"items": [{"name": "X", "website": "https://x.ru"}]})
        check(resp.status_code == 503, "provision отвечает 503, а не падает")

        resp = await c.get("/api/demos/list")
        check(resp.status_code == 200 and resp.json()["items"] == [],
              "list отдаёт пустой список, таблица не ломается")

    # --- интеграция включена, kb_assistant подменён ---
    print("\nинтеграция настроена (kb_assistant — заглушка):")
    settings.kb_base_url = "http://kb.local"
    settings.kb_api_key = "secret"
    settings.kb_bot_username = "my_demo_bot"

    calls: list[dict] = []

    class FakeClient:
        ready = True

        def __init__(self) -> None:
            pass

        async def ping(self):
            return FakeClient.ready

        async def provision(self, *, slug, company_name, site_url, max_pages=None):
            calls.append({"slug": slug, "site": site_url, "max_pages": max_pages})
            if site_url.endswith("dup.ru"):
                raise DemoClientError("Demo already exists")
            return {"slug": slug, "company_name": company_name, "site_url": site_url,
                    "status": "pending", "pages_indexed": 0,
                    "opened_count": 0, "message_count": 0}

        async def by_slugs(self, slugs):
            # Для дубля отдаём уже существующее демо — так повторный клик
            # по строке показывает статус, а не ошибку.
            return [{"slug": s, "company_name": "Дубль", "site_url": "https://dup.ru",
                     "status": "ready", "pages_indexed": 9,
                     "opened_count": 2, "message_count": 5} for s in slugs]

        async def list_targets(self, *, opened_only=False, limit=200):
            return [{"slug": "acme", "company_name": "Acme", "site_url": "https://acme.ru",
                     "status": "ready", "pages_indexed": 12,
                     "opened_count": 1, "message_count": 3}]

    demos_mod.DemoClient = FakeClient  # type: ignore[misc]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # Стек ещё поднимается: интеграция настроена, но не готова.
        FakeClient.ready = False
        body = (await c.get("/api/demos/config")).json()
        check(body["enabled"] is True and body["ready"] is False,
              "пока Docker-стек не ответил — enabled=true, ready=false")

        FakeClient.ready = True
        body = (await c.get("/api/demos/config")).json()
        check(body["ready"] is True, "как только kb_assistant ответил — ready=true")

        resp = await c.post("/api/demos/provision", json={
            "items": [
                {"name": "Клиника Люкс", "website": "https://lux.ru"},
                {"name": "Автосервис", "website": "https://avto.ru"},
            ],
            "max_pages": 15,
        })
        body = resp.json()
        check(resp.status_code == 200 and len(body["items"]) == 2, "провижинятся обе организации")
        check(all(i["status"] == "pending" for i in body["items"]),
              "статус pending — краул идёт в фоне")
        check(all(i["link"].startswith("https://t.me/my_demo_bot?start=") for i in body["items"]),
              "в ответе готовая ссылка для клиента")
        check(all(c_["max_pages"] == 15 for c_ in calls), "max_pages доходит до kb_assistant")

        # Повторный клик по уже заведённой строке
        resp = await c.post("/api/demos/provision",
                            json={"items": [{"name": "Дубль", "website": "https://dup.ru"}]})
        item = resp.json()["items"][0]
        check(item["status"] == "ready",
              "повтор по существующему демо показывает его статус, а не ошибку")
        check(item["opened_count"] == 2 and item["message_count"] == 5,
              "телеметрия открытий доезжает до таблицы")

        resp = await c.get("/api/demos/list")
        items = resp.json()["items"]
        check(len(items) == 1 and items[0]["website"] == "https://acme.ru",
              "list отдаёт заведённые демо с сайтом для сопоставления со строкой")


async def main() -> None:
    test_slugs()
    test_link()
    await test_routes()

    print()
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}")
        for f in _failures:
            print(f"  - {f}")
        sys.exit(1)
    print("Все проверки прошли.")


if __name__ == "__main__":
    asyncio.run(main())
