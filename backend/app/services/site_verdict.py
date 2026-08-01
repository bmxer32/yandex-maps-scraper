"""
Третья ступень: вердикт модели по тексту главной страницы.

Регулярками не отличить сеть из двенадцати филиалов от одиночной студии и не
понять, есть ли на сайте вообще что продавать. Здесь это делает Gemini — один
вызов на компанию, только для тех, у кого главная скачалась.

Ключ не задан или модель недоступна — ступень молча пропускается, первые две
продолжают работать. Отсутствие вердикта никогда не понижает клиента: незнание
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


def enabled() -> bool:
    """Настроен ли ключ — без него ступень просто не выполняется."""
    return bool(settings.google_api_key)


async def classify(client: httpx.AsyncClient, name: str, text: str) -> Verdict:
    """Спросить модель про одну компанию. Никогда не бросает."""
    if not enabled():
        return Verdict(error="GOOGLE_API_KEY не задан")
    if not text.strip():
        return Verdict(error="нет текста страницы")

    prompt = _PROMPT.format(name=name, text=text[: settings.verdict_text_limit])
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

    resp = None
    for attempt in range(max(settings.verdict_retries, 1)):
        try:
            resp = await client.post(
                url,
                params={"key": settings.google_api_key},
                json=payload,
                timeout=settings.verdict_timeout,
            )
        except httpx.HTTPError as exc:
            logger.warning("Вердикт для {!r} не получен: {}", name, exc)
            return Verdict(error=f"модель недоступна: {type(exc).__name__}")

        if resp.status_code != 429:
            break
        # Бесплатный тир считает запросы в минуту. Ждём с нарастающей паузой:
        # компания без вердикта останется «сомнительной», то есть попадёт на
        # ручную проверку — дешевле подождать пару секунд.
        if attempt < settings.verdict_retries - 1:
            await asyncio.sleep(2 * (attempt + 1) ** 2)

    if resp is None:
        return Verdict(error="модель недоступна")

    if resp.status_code == 429:
        return Verdict(error="лимит запросов к модели исчерпан")
    if resp.status_code >= 400:
        logger.warning("Вердикт для {!r}: HTTP {} {}", name, resp.status_code, resp.text[:200])
        return Verdict(error=f"модель вернула {resp.status_code}")

    try:
        parts = resp.json()["candidates"][0]["content"]["parts"]
        raw = "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError, ValueError):
        return Verdict(error="неожиданный формат ответа модели")

    return _parse(raw)
