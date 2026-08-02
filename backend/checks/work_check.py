"""
Проверки раздела «В работе».

Главное, что здесь охраняется: повторный парсинг обновляет карточку и
НЕ трогает то, что вёл человек. Потерять «кому я уже писал» из-за пересбора
ниши — худшее, что этот раздел может сделать.

Запуск:  python checks/work_check.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# База — временная: проверки не должны трогать рабочую.
_TMP = Path(tempfile.mkdtemp(prefix="work-check-")) / "check.db"
import os  # noqa: E402

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP.as_posix()}"

from app.core.db import init_db  # noqa: E402
from app.services import work_service  # noqa: E402
from app.services.work_service import work_key  # noqa: E402

_failed: list[str] = []


def check(cond: bool, label: str) -> None:
    print(f"  [{'ok' if cond else '--'}]   {label}")
    if not cond:
        _failed.append(label)


def test_keys() -> None:
    print("\nключ конторы:")
    check(work_key({"permalink": "19876153590", "name": "Салон"}) == "19876153590",
          "permalink важнее названия")
    # Сайт ключом быть не может: у половины салонов его нет.
    a = work_key({"name": "Эстетика", "address": "Краснодар, Северная 1"})
    b = work_key({"name": "Эстетика", "address": "Краснодар, Красная 5"})
    check(a != b, "без permalink различаем по адресу")
    check(work_key({"name": "Эстетика", "address": "КРАСНОДАР, Северная 1"}) == a,
          "регистр адреса ключ не меняет")


async def test_add_and_update() -> None:
    print("\nдобавление и работа человека:")
    org = {
        "permalink": "111",
        "name": "Эстетика",
        "address": "Краснодар",
        "phone": "+7 918 123-45-67",
        "phones": ["+7 918 123-45-67 (Краснодар)"],
        "website": "https://estetika.ru",
        "websites": ["https://estetika.ru"],
        "socials": ["Telegram|https://t.me/estetika"],
        "categories": ["Салон красоты"],
        "reviews_count": 40,
        "verdict": "good",
        "web": "good",
    }
    added = await work_service.add([org])
    check(len(added) == 1 and added[0].status == "new", "добавилась со статусом «Новый»")
    check(added[0].phones == ["+7 918 123-45-67 (Краснодар)"], "телефоны скопированы")

    again = await work_service.add([org])
    items = await work_service.list_items()
    check(len(items) == 1 and len(again) == 1, "повторное добавление не двоит")

    upd = await work_service.update("111", status="written", note="обещали ответить")
    check(upd is not None and upd.status == "written", "статус меняется")
    check(upd.note == "обещали ответить", "заметка сохраняется")

    bad = await work_service.update("111", status="какой-то")
    check(bad is not None and bad.status == "written",
          "неизвестный статус игнорируется, а не затирает текущий")

    check(await work_service.update("нет-такой") is None, "неизвестный ключ — None")

    # Ссылка на нашу работу: демо-сайт, макет, ссылка на ассистента.
    upd = await work_service.update("111", demo_url="https://demo.nashe.ru/estetika")
    check(upd.demo_url == "https://demo.nashe.ru/estetika", "ссылка на демо сохраняется")
    check(upd.website == "https://estetika.ru",
          "сайт клиента и наша ссылка живут отдельно")
    check((await work_service.update("111", demo_url="  ")).demo_url is None,
          "пустая строка стирает ссылку")
    await work_service.update("111", demo_url="https://demo.nashe.ru/estetika")


async def test_rescan_keeps_work() -> None:
    print("\nповторный парсинг:")
    # Тот же permalink, но Яндекс отдал новый телефон и второй сайт.
    fresh = {
        "permalink": "111",
        "name": "Эстетика",
        "address": "Краснодар, Северная 1",
        "phone": "+7 918 999-00-11",
        "phones": ["+7 918 999-00-11 (Краснодар)", "+7 861 222-33-44 (Краснодар)"],
        "website": "https://estetika.ru",
        "websites": ["https://estetika.ru", "https://estetika-zapis.ru"],
        "reviews_count": 58,
    }
    touched = await work_service.refresh([fresh])
    check(touched == 1, "запись в работе обновилась")

    item = (await work_service.list_items())[0]
    check(item.phone == "+7 918 999-00-11", "телефон свежий")
    check(len(item.phones) == 2 and len(item.websites) == 2, "оба телефона и оба сайта")
    check(item.reviews_count == 58, "отзывы обновились")
    check(item.status == "written", "СТАТУС НЕ ТРОНУТ")
    check(item.note == "обещали ответить", "ЗАМЕТКА НЕ ТРОНУТА")
    check(item.demo_url == "https://demo.nashe.ru/estetika", "НАША ССЫЛКА НЕ ТРОНУТА")

    # Контору, которой в работе нет, refresh не заводит: раздел наполняется
    # только руками, иначе туда свалится вся выгрузка.
    before = len(await work_service.list_items())
    await work_service.refresh([{"permalink": "222", "name": "Посторонняя"}])
    check(len(await work_service.list_items()) == before,
          "чужая контора сама в работу не попадает")


async def test_remove() -> None:
    print("\nудаление:")
    check(await work_service.remove("111") is True, "убрали из работы")
    check(await work_service.remove("111") is False, "повторное удаление — False")
    check(await work_service.list_items() == [], "список пуст")


async def main() -> None:
    await init_db()
    test_keys()
    await test_add_and_update()
    await test_rescan_keeps_work()
    await test_remove()

    print()
    if _failed:
        print(f"ПРОВАЛЕНО: {len(_failed)}")
        for f in _failed:
            print(f"  - {f}")
        sys.exit(1)
    print("Все проверки прошли.")


asyncio.run(main())
