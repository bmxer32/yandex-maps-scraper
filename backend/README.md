# Backend — Yandex Maps Scraper

FastAPI-приложение, которое парсит Яндекс.Карты через headless-браузер
(Playwright) и отдаёт данные об организациях: название, адрес, телефон,
сайт, email, соцсети, часы работы, рейтинг.

## Архитектура

```
app/
├── main.py                 — FastAPI-приложение
├── config.py               — настройки (через .env)
├── api/search.py           — HTTP-роуты + SSE-стрим прогресса
├── core/
│   ├── db.py               — асинхронная SQLite (SQLAlchemy)
│   ├── geo.py              — справочник страна→область→город→район/метро
│   └── scraper/
│       ├── yandex_maps.py  — ядро парсера (Playwright + перехват JSON)
│       ├── anti_detect.py  — stealth, профиль браузера, «человеческие» паузы
│       ├── proxy_pool.py   — round-robin пул прокси (опц.)
│       └── site_enricher.py — второй проход по сайтам: email + соцсети
├── models/schemas.py       — Pydantic-модели
└── services/
    ├── task_manager.py     — in-memory стор фоновых задач + SSE-события
    └── search_service.py   — оркестрация pipeline
```

## Установка

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# установить браузеры Playwright
playwright install chromium
playwright install-deps          # только на Linux
```

Скопируй `.env.example` в `.env` и поправь при необходимости.

## Запуск

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Документация API: http://127.0.0.1:8000/docs

## Основные эндпоинты

| Метод | URL                          | Что делает                              |
|------:|------------------------------|-----------------------------------------|
| GET   | `/api/geo/tree`              | Гео-дерево для каскадных селекторов     |
| POST  | `/api/search`                | Создать и запустить задачу парсинга     |
| GET   | `/api/tasks`                 | Список задач                            |
| GET   | `/api/task/{id}`             | Текущий прогресс + результат            |
| GET   | `/api/task/{id}/stream`      | SSE-стрим прогресса в реальном времени  |
| POST  | `/api/task/{id}/cancel`      | Отменить задачу                         |
| GET   | `/api/export/{id}?fmt=xlsx`  | Экспорт в .xlsx или .csv                |

## Важно про парсинг Яндекс.Карт

Яндекс активно защищает карты от автоматического сбора. Этот backend
спроектирован максимально устойчиво:

1. **Перехват JSON-ответов**, а не парсинг HTML — формат реже меняется.
2. **Stealth-патчи** (playwright-stealth + ручные `navigator.webdriver`/`plugins`).
3. **Рандомные профили браузера** (UA, viewport, timezone, locale).
4. **«Человеческие» задержки** между действиями.
5. **Ротация прокси** (если задать список в `.env`).
6. **Дозированное открытие карточек** за телефоном/сайтом.
7. **Кэш SQLite** по permalink Яндекса — повторные запросы быстрее.

Если Яндекс начнёт подсовывать капчу — в `.env` можно вписать ключ
`2captcha`/`anti-captcha.com`, интеграция заложена архитектурно.
