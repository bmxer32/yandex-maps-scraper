"""
Конфигурация приложения.
Все параметры можно перекрыть через .env файл или переменные окружения.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# Корень backend-пакета: .../backend
BACKEND_ROOT = Path(__file__).resolve().parent.parent
# Папка под SQLite-базу и кэш.
# В packaged режиме (Program Files) — данные в %LOCALAPPDATA%,
# run.py выставляет DATABASE_URL до импорта config.
DATA_DIR = BACKEND_ROOT / "data"
try:
    DATA_DIR.mkdir(exist_ok=True)
except (PermissionError, OSError):
    # Program Files readonly — игнорируем, DATABASE_URL укажет в LOCALAPPDATA
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Сервер ---
    host: str = "127.0.0.1"
    port: int = 8000
    # Явные origins (localhost/127.0.0.1 на стандартных dev-портах)
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]
    # Regex для dev-портов 3000–3099 — чтобы не править конфиг при смене порта
    cors_origin_regex: str = r"https?://(localhost|127\.0\.0\.1)(:\d{2,5})?"

    # --- Браузер / антидетект ---
    headless: bool = True
    # Диапазон задержек между действиями в секундах (имитация человека)
    min_delay: float = 1.8
    max_delay: float = 4.6
    # Сколько карточек максимально собирать за один запуск
    max_results: int = 1000
    # Сколько карточек подгружать пагинацией за один «скролл»
    page_size: int = 12

    # --- Прокси (опционально) ---
    # Формат: "http://user:pass@host:port" по одному на строку, или пусто
    proxies: list[str] = []
    # Менять прокси каждые N запросов (0 = не менять)
    rotate_every: int = 0

    # --- Капча (резерв) ---
    # Поддерживается 2captcha / anti-captcha.com
    captcha_api_key: str = ""
    captcha_provider: str = "2captcha"   # "2captcha" | "anticaptcha"

    # --- Второй проход по сайтам организаций ---
    enrich_sites: bool = True
    site_timeout: float = 6.0            # секунд на один сайт
    enrich_concurrency: int = 8          # параллельных запросов

    # --- БД ---
    database_url: str = f"sqlite+aiosqlite:///{DATA_DIR / 'yascraper.db'}"

    # --- Интеграция с kb_assistant (персональные демо ИИ-ассистента) ---
    # Пусто => вкладка «Демо» в интерфейсе скрыта, парсер работает как раньше.
    kb_base_url: str = ""                # напр. "http://127.0.0.1:8001"
    kb_api_key: str = ""                 # значение заголовка X-API-Key
    kb_bot_username: str = ""            # для ссылки t.me/<bot>?start=<slug>
    kb_max_pages: int = 30               # сколько страниц сайта краулить под демо
    kb_timeout: float = 20.0             # таймаут запроса к kb_assistant, сек

    @property
    def kb_enabled(self) -> bool:
        """Интеграция настроена только когда заданы и адрес, и ключ."""
        return bool(self.kb_base_url and self.kb_api_key)

    # --- Отбор клиентов (вердикты по сайтам) ---
    # Ключ Gemini для третьей ступени. Пусто => ступень пропускается,
    # механика и проба сайта продолжают работать.
    google_api_key: str = ""
    # Запасные ключи Gemini через запятую. Лимит бесплатного тира считается
    # на проект, поэтому ключи с разных аккаунтов складываются: упёрлись в
    # 429 по одному — берём следующий.
    google_api_keys_extra: str = ""
    # Запасные провайдеры с бесплатным тиром, совместимые с OpenAI API.
    # Пробуются по очереди, когда Gemini исчерпан. Ключ не задан — пропуск.
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    verdict_model: str = "gemini-flash-latest"
    verdict_timeout: float = 30.0
    verdict_text_limit: int = 8000     # знаков главной страницы в промпт
    # Бесплатный тир Gemini ограничен запросами в минуту: при восьми в
    # параллель половина выгрузки возвращала 429. Держим отдельно от проб.
    verdict_concurrency: int = 2
    verdict_retries: int = 3           # повторов при 429, с нарастающей паузой
    scan_concurrency: int = 8          # параллельных проб сайтов
    scan_timeout: float = 12.0         # таймаут одной пробы, сек
    min_reviews: int = 5               # мягкий порог «живого» бизнеса

    @property
    def gemini_keys(self) -> list[str]:
        """Все ключи Gemini по порядку: основной, затем запасные."""
        keys = [self.google_api_key.strip()]
        keys += [k.strip() for k in self.google_api_keys_extra.split(",")]
        # Дубли убираем, сохраняя порядок: повторный запрос тем же ключом
        # после 429 просто потратит время.
        seen: set[str] = set()
        return [k for k in keys if k and not (k in seen or seen.add(k))]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
