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

# Просим строгий JSON и прямо разрешаем «не понял» — модель, вынужденная
# выбирать из двух вариантов, начинает выдумывать.
_PROMPT = """Ты помогаешь отобрать компании, которым имеет смысл предложить ИИ-ассистента для ответов клиентам.

Ниже текст главной страницы сайта компании «{name}».

Определи по тексту:
1. scale — это одиночный бизнес («одиночка»), сеть с филиалами («сеть»), франшиза («франшиза») или понять нельзя («не понял»).
2. alive — сайт выглядит поддерживаемым («живой»), заброшенным («заброшен») или понять нельзя («не понял»).
3. sellable — есть ли на сайте описание услуг или цен, по которым ассистент смог бы отвечать клиентам (true/false).
4. verdict — «годится», «сомнительно» или «мимо».
5. reason — одна короткая фраза по-русски, объясняющая вердикт.

Правила:
- «мимо» ставь ТОЛЬКО при явном основании: это сеть или франшиза, либо сайт заброшен, либо продавать по нему нечего.
- Если данных мало или ты не уверен — ставь «сомнительно» и «не понял». Не угадывай.
- Крупная сеть — «мимо»: решения там принимают централизованно.
- Отсутствие цен само по себе не повод для «мимо», если услуги описаны.

Ответь ТОЛЬКО JSON без пояснений:
{{"scale":"...","alive":"...","sellable":true,"verdict":"...","reason":"..."}}

Текст страницы:
{text}"""


@dataclass
class Verdict:
    scale: Optional[str] = None
    alive: Optional[str] = None
    sellable: Optional[bool] = None
    verdict: Optional[str] = None
    reason: Optional[str] = None
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

    return Verdict(
        scale=scale if scale in _ALLOWED_SCALE else "не понял",
        alive=alive if alive in _ALLOWED_ALIVE else "не понял",
        sellable=bool(data.get("sellable")) if "sellable" in data else None,
        # Незнакомое значение трактуем как «сомнительно», а не как «мимо».
        verdict=verdict if verdict in _ALLOWED_VERDICT else "сомнительно",
        reason=(str(data.get("reason") or "").strip() or None),
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


async def classify(client: httpx.AsyncClient, name: str, text: str) -> Verdict:
    """Спросить модель про одну компанию. Никогда не бросает.

    Провайдеры перебираются по очереди. На лимит переходим к следующему сразу
    — ждать минуту ради одной строки дороже, чем спросить другого вендора.
    Повторы с паузой остаются на случай, когда провайдер один.
    """
    if not enabled():
        return Verdict(error="не задан ни один ключ модели")
    if not text.strip():
        return Verdict(error="нет текста страницы")

    prompt = _PROMPT.format(name=name, text=text[: settings.verdict_text_limit])

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
