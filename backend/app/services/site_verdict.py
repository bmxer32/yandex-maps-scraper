"""
Третья ступень: вердикт модели по тексту главной страницы.

Регулярками не отличить сеть из двенадцати филиалов от одиночной студии и не
понять, есть ли на сайте вообще что продавать. Здесь это делает модель — один
вызов на компанию, только для тех, у кого главная скачалась.

Провайдеры пробуются цепочкой, пока кто-то не ответит:

1. Gemini — все заданные ключи по очереди (лимит бесплатного тира считается
   на проект, поэтому ключи с разных аккаунтов складываются);
2. Groq — бесплатный тир, OpenAI-совместимый API;
3. OpenRouter — бесплатные модели, тот же формат запроса.

Никто не ответил — ступень молча пропускается, первые две продолжают
работать. Отсутствие вердикта никогда не понижает клиента: незнание
трактуется в его пользу.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Optional

import httpx
from loguru import logger

from ..config import settings

_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)

_COMMON_RULES = """Правила:
- «мимо» ставь ТОЛЬКО при явном основании. Если данных мало или ты не уверен — «сомнительно» и «не понял». Не угадывай.
- Сеть, франшиза или федеральный бренд — «мимо» по ОБЕИМ услугам: решения там принимают централизованно, локальный подрядчик им не нужен.
- Одиночная студия или небольшая местная компания — нормальный клиент.

Ответь ТОЛЬКО JSON без пояснений:
{{"scale":"...","alive":"...","sellable":true,"verdict":"...","reason":"...","web":"...","web_reason":"..."}}"""

# Компанию с обходимым сайтом оцениваем по тексту главной и по тому, на чём
# сайт сделан: технические признаки решают вторую ось.
_PROMPT_SITE = """Ты помогаешь отобрать компании, которым можно предложить две услуги: ИИ-ассистента для ответов клиентам и разработку либо переделку сайта.

Компания «{name}». Ниже текст главной страницы её сайта.
Технические признаки сайта: {tech}

Определи:
1. scale — одиночный бизнес («одиночка»), сеть с филиалами («сеть»), франшиза («франшиза») или непонятно («не понял»).
2. alive — сайт поддерживают («живой»), забросили («заброшен») или непонятно («не понял»).
3. sellable — есть ли описание услуг или цен, по которым ассистент мог бы отвечать клиентам (true/false).
4. verdict — стоит ли предлагать ИИ-ассистента: «годится», «сомнительно» или «мимо».
5. reason — одна короткая фраза по-русски про ассистента.
6. web — стоит ли предлагать сайт: «годится» (сайт устарел, неудобен, плохо выглядит), «сомнительно» (рабочий, но простой либо без удобной онлайн-записи) или «мимо» (современный, удобный, записаться можно прямо на сайте).
   Для салонов, барбершопов, клиник и всего, куда записываются, отсутствие онлайн-записи на сайте — веский довод: клиенту приходится писать в мессенджер и ждать ответа администратора.
7. web_reason — одна короткая фраза по-русски про сайт.

{rules}

Текст страницы:
{text}"""

# У компании нет обходимого сайта — судим по названию и рубрикам. Именно этот
# путь ловит сети вроде 4hands: раньше такие вообще не доходили до модели и
# проходили как годные по одному числу отзывов.
_PROMPT_NO_SITE = """Ты помогаешь отобрать компании, которым можно предложить две услуги: ИИ-ассистента для ответов клиентам и разработку сайта.

Компания «{name}».
Город и адрес: {address}
Сфера: {categories}
В поле «сайт» у неё: {site_note}
Полноценного сайта нет.

Определи:
1. scale — это известная сеть или франшиза («сеть» / «франшиза»), одиночная местная компания («одиночка») или непонятно («не понял»). Ориентируйся на узнаваемость названия как бренда.
2. alive — «живой», «заброшен» или «не понял».
3. sellable — можно ли по такой компании собрать базу знаний для ассистента (true/false).
4. verdict — стоит ли предлагать ИИ-ассистента: «годится», «сомнительно» или «мимо».
5. reason — одна короткая фраза по-русски.
6. web — сайта нет, поэтому по умолчанию «годится» (его можно сделать с нуля). Ставь «мимо», только если это сеть или франшиза.
7. web_reason — одна короткая фраза по-русски.

{rules}"""

# Просим строгий JSON и прямо разрешаем «не понял» — модель, вынужденная
# выбирать из двух вариантов, начинает выдумывать.
@dataclass
class Verdict:
    scale: Optional[str] = None
    alive: Optional[str] = None
    sellable: Optional[bool] = None
    verdict: Optional[str] = None
    reason: Optional[str] = None
    # Вторая ось: редизайн или создание сайта.
    web: Optional[str] = None
    web_reason: Optional[str] = None
    error: Optional[str] = None
    # Кто именно ответил — видно в логах, когда основной провайдер кончился.
    provider: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.verdict is not None


_ALLOWED_VERDICT = {"годится", "сомнительно", "мимо"}
_ALLOWED_SCALE = {"одиночка", "сеть", "франшиза", "не понял"}
_ALLOWED_ALIVE = {"живой", "заброшен", "не понял"}


def _parse(raw: str) -> Verdict:
    """Достать JSON из ответа модели.

    Модель любит обернуть ответ в ```json — вырезаем первый объект по фигурным
    скобкам. Всё, что не распозналось, сводится к «не понял»: сломанный ответ
    не должен превращаться в приговор компании.
    """
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return Verdict(error="модель ответила не JSON")
    try:
        data = json.loads(match.group(0))
    except ValueError as exc:
        return Verdict(error=f"не разобрал JSON: {exc}")

    verdict = str(data.get("verdict", "")).strip().lower()
    scale = str(data.get("scale", "")).strip().lower()
    alive = str(data.get("alive", "")).strip().lower()

    web = str(data.get("web", "")).strip().lower()

    return Verdict(
        scale=scale if scale in _ALLOWED_SCALE else "не понял",
        alive=alive if alive in _ALLOWED_ALIVE else "не понял",
        sellable=bool(data.get("sellable")) if "sellable" in data else None,
        # Незнакомое значение трактуем как «сомнительно», а не как «мимо».
        verdict=verdict if verdict in _ALLOWED_VERDICT else "сомнительно",
        reason=(str(data.get("reason") or "").strip() or None),
        web=web if web in _ALLOWED_VERDICT else "сомнительно",
        web_reason=(str(data.get("web_reason") or "").strip() or None),
    )


# --- Провайдеры ------------------------------------------------------------
# Каждый возвращает сырой текст ответа. Порядок фиксированный: сначала все
# ключи Gemini, потом бесплатные тиры других вендоров. У каждого свой лимит,
# поэтому исчерпанный Gemini не оставляет нас без вердиктов.


@dataclass
class _Attempt:
    """Результат одной попытки: текст ответа либо причина неудачи."""

    raw: Optional[str] = None
    quota: bool = False          # упёрлись в лимит — есть смысл идти дальше
    error: Optional[str] = None
    provider: str = ""


async def _try_gemini(client: httpx.AsyncClient, key: str, prompt: str) -> _Attempt:
    url = _ENDPOINT.format(model=settings.verdict_model)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            # Нулевая температура: это классификация, а не сочинение.
            "temperature": 0,
            # Модель «размышляет», и эти токены идут в тот же бюджет: при 300
            # на мысли уходило 285, ответ обрывался на полуслове
            # (finishReason=MAX_TOKENS). Отключить мышление у этой модели
            # нельзя — thinkingBudget она отвергает с 400, — поэтому запас.
            "maxOutputTokens": 1500,
            # Просим сразу JSON — надёжнее, чем вырезать его регуляркой.
            "responseMimeType": "application/json",
        },
    }
    try:
        resp = await client.post(
            url, params={"key": key}, json=payload, timeout=settings.verdict_timeout
        )
    except httpx.HTTPError as exc:
        return _Attempt(error=f"недоступен: {type(exc).__name__}", provider="gemini")

    if resp.status_code == 429:
        return _Attempt(quota=True, error="лимит исчерпан", provider="gemini")
    if resp.status_code >= 400:
        return _Attempt(error=f"HTTP {resp.status_code}", provider="gemini")

    try:
        parts = resp.json()["candidates"][0]["content"]["parts"]
        return _Attempt(raw="".join(p.get("text", "") for p in parts), provider="gemini")
    except (KeyError, IndexError, ValueError):
        return _Attempt(error="неожиданный формат ответа", provider="gemini")


async def _try_openai_compatible(
    client: httpx.AsyncClient, *, base: str, key: str, model: str, prompt: str, provider: str
) -> _Attempt:
    """Groq и OpenRouter говорят на одном диалекте — обработчик общий."""
    try:
        resp = await client.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 400,
                "response_format": {"type": "json_object"},
            },
            timeout=settings.verdict_timeout,
        )
    except httpx.HTTPError as exc:
        return _Attempt(error=f"недоступен: {type(exc).__name__}", provider=provider)

    if resp.status_code == 429:
        return _Attempt(quota=True, error="лимит исчерпан", provider=provider)
    if resp.status_code >= 400:
        return _Attempt(error=f"HTTP {resp.status_code}", provider=provider)

    try:
        return _Attempt(
            raw=resp.json()["choices"][0]["message"]["content"], provider=provider
        )
    except (KeyError, IndexError, ValueError):
        return _Attempt(error="неожиданный формат ответа", provider=provider)


def providers() -> list[str]:
    """Список настроенных провайдеров по порядку — для диагностики и UI."""
    names = [f"gemini#{i + 1}" for i in range(len(settings.gemini_keys))]
    if settings.groq_api_key:
        names.append("groq")
    if settings.openrouter_api_key:
        names.append("openrouter")
    return names


def enabled() -> bool:
    """Есть ли хоть один настроенный провайдер."""
    return bool(providers())


async def classify(
    client: httpx.AsyncClient,
    name: str,
    text: str = "",
    *,
    tech: str = "",
    address: str = "",
    categories: str = "",
    site_note: str = "",
) -> Verdict:
    """Спросить модель про одну компанию. Никогда не бросает.

    Есть текст главной — судим по нему и по стеку сайта. Нет (только страница
    в соцсети, виджет записи или вообще ничего) — по названию, адресу и
    рубрикам. Второй путь появился ради сетей: раньше компании без сайта до
    модели не доходили вовсе и проходили как годные по одному числу отзывов.

    Провайдеры перебираются по очереди. На лимит переходим к следующему сразу
    — ждать минуту ради одной строки дороже, чем спросить другого вендора.
    Повторы с паузой остаются на случай, когда провайдер один.
    """
    if not enabled():
        return Verdict(error="не задан ни один ключ модели")

    if text.strip():
        prompt = _PROMPT_SITE.format(
            name=name,
            tech=tech or "ничего примечательного",
            text=text[: settings.verdict_text_limit],
            rules=_COMMON_RULES,
        )
    elif name.strip():
        prompt = _PROMPT_NO_SITE.format(
            name=name,
            address=address or "не указан",
            categories=categories or "не указана",
            site_note=site_note or "ничего",
            rules=_COMMON_RULES,
        )
    else:
        return Verdict(error="нечего показать модели")

    chain = [(lambda k=k: _try_gemini(client, k, prompt)) for k in settings.gemini_keys]
    if settings.groq_api_key:
        chain.append(
            lambda: _try_openai_compatible(
                client,
                base="https://api.groq.com/openai/v1",
                key=settings.groq_api_key,
                model=settings.groq_model,
                prompt=prompt,
                provider="groq",
            )
        )
    if settings.openrouter_api_key:
        chain.append(
            lambda: _try_openai_compatible(
                client,
                base="https://openrouter.ai/api/v1",
                key=settings.openrouter_api_key,
                model=settings.openrouter_model,
                prompt=prompt,
                provider="openrouter",
            )
        )

    quota_only = True
    last_error = "модель недоступна"

    for call in chain:
        attempt = await call()
        if attempt.raw is not None:
            parsed = _parse(attempt.raw)
            parsed.provider = attempt.provider
            if parsed.ok:
                return parsed
            last_error = parsed.error or "не разобрал ответ"
            quota_only = False
            continue
        last_error = f"{attempt.provider}: {attempt.error}"
        if not attempt.quota:
            quota_only = False

    # Провайдер один и он в лимите — подождать дешевле, чем оставить строку
    # без вердикта: она уйдёт в «сомнительно» и на ручную проверку.
    if quota_only and len(chain) == 1:
        for attempt_no in range(1, max(settings.verdict_retries, 1)):
            await asyncio.sleep(2 * attempt_no**2)
            attempt = await chain[0]()
            if attempt.raw is not None:
                parsed = _parse(attempt.raw)
                parsed.provider = attempt.provider
                if parsed.ok:
                    return parsed
            if not attempt.quota:
                break

    if quota_only:
        return Verdict(error="лимит запросов к модели исчерпан")
    logger.debug("Вердикт для {!r} не получен: {}", name, last_error)
    return Verdict(error=last_error)
