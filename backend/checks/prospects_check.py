"""
Проверка отбора клиентов.

Запуск из папки backend:  python checks/prospects_check.py

Сеть не трогаем — вызовы модели и пробы сайтов подменяются заглушками.
Главное, что проверяем: ни одна компания не отсеивается по слабому признаку.
Ошибка в эту сторону дороже всех остальных: потерянный клиент не вернётся,
а лишняя строка в списке стоит одного взгляда.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.prospect import ProspectVerdict  # noqa: E402
from app.models.schemas import Organization  # noqa: E402
from app.services import prospect_service, site_verdict  # noqa: E402
from app.services.prospect_rules import (  # noqa: E402
    LINK_BOOKING,
    LINK_BUILDER,
    LINK_NONE,
    LINK_OWN,
    LINK_SOCIAL,
    classify_link,
    evaluate,
    find_duplicates,
    site_key,
)
from app.services.site_probe import ProbeResult, _analyze  # noqa: E402

_failures: list[str] = []


def check(cond: bool, label: str) -> None:
    if cond:
        print(f"  [ok]   {label}")
    else:
        print(f"  [FAIL] {label}")
        _failures.append(label)


# ---------------------------------------------------------------------------
def test_link_kinds() -> None:
    print("\nчто лежит в поле «сайт»:")
    cases = {
        "https://vk.ru/lekoschool": LINK_SOCIAL,
        "http://vk.ru/club89565701": LINK_SOCIAL,
        "https://max.ru/u/f9LHodD0": LINK_SOCIAL,
        "https://t.me/someschool": LINK_SOCIAL,
        "https://artlingva.clients.site/": LINK_BOOKING,
        "https://n479766.yclients.com/company/45407": LINK_BOOKING,
        "https://school.tilda.ws/": LINK_BUILDER,
        "https://saavedra.ru/": LINK_OWN,
        "http://www.lingvo-centre.ru/": LINK_OWN,
        None: LINK_NONE,
    }
    for url, expect in cases.items():
        got = classify_link(url)
        check(got == expect, f"{str(url)[:42]:<44} → {got}")

    check(site_key("https://WWW.Example.RU/path/") == "example.ru", "ключ сайта нормализуется")
    check(site_key(None) == "", "пустой сайт даёт пустой ключ")


def test_social_is_not_a_bad_client() -> None:
    """Ключевое правило: нет сайта — это не «мимо», а «демо вручную»."""
    print("\nсоцсеть вместо сайта — не приговор клиенту:")
    org = Organization(name="Школа Леко", website="https://vk.ru/lekoschool", reviews_count=26)
    res = evaluate(org)
    check(res["demo"] == "manual", "демо помечено как ручное")
    check(res["verdict"] == "good", "клиент остаётся годным — ему ассистент нужнее всех")


def test_duplicates() -> None:
    print("\nдубли карточек:")
    orgs = [
        Organization(name="Индиго", website="https://indigo-centre.com/"),
        Organization(name="Индиго", website="https://indigo-centre.com/"),
        Organization(name="Другая", website="https://other.ru/"),
        Organization(name="Соцсеть А", website="https://vk.ru/a"),
        Organization(name="Соцсеть Б", website="https://vk.ru/b"),
    ]
    d = find_duplicates(orgs)
    check(1 in d and d[1] == "Индиго", "второй одинаковый сайт помечен дублем")
    check(2 not in d, "разные компании дублями не считаются")
    check(3 not in d and 4 not in d, "разные страницы ВКонтакте не склеиваются по домену")


def test_thresholds() -> None:
    print("\nпороги по отзывам:")
    check(evaluate(Organization(name="A", website="https://a.ru", reviews_count=50))["verdict"] == "good",
          "много отзывов → годится")
    check(evaluate(Organization(name="B", website="https://b.ru", reviews_count=0))["verdict"] == "maybe",
          "ноль отзывов → сомнительно, но НЕ мимо")
    check(evaluate(Organization(name="C", website="https://c.ru", reviews_count=2))["verdict"] == "maybe",
          "мало отзывов → сомнительно")


def test_probe_never_skips() -> None:
    """Проба не имеет права отсеивать: 403 — антибот, старый копирайт — не факт."""
    print("\nпроба сайта никого не отсеивает:")
    for label, probe in [
        ("сайт не отвечает", ProbeResult(ok=False, error="ConnectError")),
        ("403 от антибота", ProbeResult(ok=False, status=403)),
        ("копирайт 2019", ProbeResult(ok=True, status=200, text_len=5000, last_year=2019)),
        ("почти нет текста", ProbeResult(ok=True, status=200, text_len=100)),
    ]:
        v = ProspectVerdict(site="x", name="X", verdict="good", demo="auto")
        prospect_service._apply_probe(v, probe)
        check(v.verdict != "skip", f"{label}: вердикт «{v.verdict}», не «мимо»")

    v = ProspectVerdict(site="x", name="X", verdict="good", demo="auto")
    prospect_service._apply_probe(v, ProbeResult(ok=False, status=403))
    check(v.demo == "manual", "недоступный сайт → демо вручную")


def test_year_only_from_copyright() -> None:
    """Первая версия брала любой год и хоронила школу со 182 отзывами."""
    print("\nгод берём только у копирайта:")
    _, year, _ = _analyze("<p>Работаем с 2015 года, обучили 5000 учеников</p>")
    check(year is None, "«работаем с 2015 года» не считается копирайтом")
    _, year, _ = _analyze("<footer>© 2019 Школа</footer>")
    check(year == 2019, "копирайт распознаётся")
    _, _, chain = _analyze("<p>Филиалы в 12 городах</p>")
    check(chain, "упоминание филиалов замечено")


def test_llm_can_skip_but_reviews_protect() -> None:
    print("\nотсеивать может только модель, и не вопреки отзывам:")
    v = ProspectVerdict(site="x", name="Сеть", verdict="good", demo="auto")
    prospect_service._apply_llm(
        v, site_verdict.Verdict(scale="франшиза", alive="живой", verdict="мимо", reason="сеть"), 100
    )
    check(v.verdict == "skip", "сеть отсеивается даже при сотне отзывов")

    v = ProspectVerdict(site="y", name="Живой", verdict="good", demo="auto")
    prospect_service._apply_llm(
        v, site_verdict.Verdict(scale="одиночка", alive="заброшен", verdict="мимо", reason="старый сайт"), 50
    )
    check(v.verdict == "maybe", "«заброшен» при 50 отзывах не отсеивает — это противоречие")

    v = ProspectVerdict(site="z", name="Молчание", verdict="good", demo="auto")
    prospect_service._apply_llm(v, site_verdict.Verdict(error="лимит запросов к модели исчерпан"), 10)
    check(v.verdict == "good", "молчание модели ничего не понижает")


def test_broken_model_answer() -> None:
    print("\nсломанный ответ модели:")
    check(site_verdict._parse("не json вовсе").error is not None, "мусор помечен ошибкой")
    check(site_verdict._parse('{"verdict":"уничтожить"}').verdict == "сомнительно",
          "незнакомый вердикт трактуется как «сомнительно», а не «мимо»")
    v = site_verdict._parse('```json\n{"verdict":"годится","scale":"одиночка"}\n```')
    check(v.verdict == "годится", "JSON в блоке кода разбирается")


async def test_provider_chain() -> None:
    """Кончился один провайдер — спрашиваем следующего, а не сдаёмся."""
    print("\nцепочка провайдеров:")
    import httpx

    from app.config import settings as cfg

    calls: list[str] = []

    async def fake_gemini(client, key, prompt):
        calls.append(f"gemini:{key}")
        return site_verdict._Attempt(quota=True, error="лимит исчерпан", provider="gemini")

    async def fake_openai(client, *, base, key, model, prompt, provider):
        calls.append(provider)
        return site_verdict._Attempt(
            raw='{"scale":"одиночка","alive":"живой","sellable":true,'
                '"verdict":"годится","reason":"живая студия"}',
            provider=provider,
        )

    orig_g, orig_o = site_verdict._try_gemini, site_verdict._try_openai_compatible
    orig_key, orig_extra, orig_groq = cfg.google_api_key, cfg.google_api_keys_extra, cfg.groq_api_key
    try:
        site_verdict._try_gemini = fake_gemini
        site_verdict._try_openai_compatible = fake_openai
        cfg.google_api_key, cfg.google_api_keys_extra, cfg.groq_api_key = "k1", "k2", "gk"

        check(site_verdict.providers() == ["gemini#1", "gemini#2", "groq"], "порядок провайдеров")

        async with httpx.AsyncClient() as c:
            v = await site_verdict.classify(c, "Студия", "Маникюр, педикюр, цены на сайте.")
        check(v.verdict == "годится", "вердикт получен от запасного провайдера")
        check(v.provider == "groq", f"ответил {v.provider}")
        check(calls == ["gemini:k1", "gemini:k2", "groq"], "оба ключа Gemini перебраны до groq")

        # Все в лимите — вердикта нет, но это НЕ отсев.
        site_verdict._try_openai_compatible = fake_gemini_like = (
            lambda client, *, base, key, model, prompt, provider: _quota(provider)
        )
        async with httpx.AsyncClient() as c:
            v2 = await site_verdict.classify(c, "Студия", "текст")
        check("лимит" in (v2.error or ""), "все провайдеры в лимите → ошибка про лимит")
        check(v2.verdict is None, "вердикта нет — компания останется как есть")
    finally:
        site_verdict._try_gemini, site_verdict._try_openai_compatible = orig_g, orig_o
        cfg.google_api_key, cfg.google_api_keys_extra, cfg.groq_api_key = orig_key, orig_extra, orig_groq


async def _quota(provider: str):
    return site_verdict._Attempt(quota=True, error="лимит исчерпан", provider=provider)


async def test_nothing_is_lost() -> None:
    """Главная гарантия: сколько строк пришло, столько и вернулось."""
    print("\nни одна строка не теряется:")
    from app.models.prospect import ScanRequestItem

    items = [
        ScanRequestItem(name="С сайтом", website="https://example.invalid", reviews_count=30),
        ScanRequestItem(name="ВКонтакте", website="https://vk.ru/x", reviews_count=10),
        ScanRequestItem(name="Без сайта", website=None, reviews_count=0),
    ]
    verdicts, _, _ = await prospect_service.scan(items, refresh=True)
    check(len(verdicts) == len(items), f"вернулось {len(verdicts)} из {len(items)}")
    check(all(v.verdict in ("good", "maybe", "skip") for v in verdicts), "все вердикты валидны")


async def main() -> None:
    test_link_kinds()
    test_social_is_not_a_bad_client()
    test_duplicates()
    test_thresholds()
    test_probe_never_skips()
    test_year_only_from_copyright()
    test_llm_can_skip_but_reviews_protect()
    test_broken_model_answer()
    await test_provider_chain()
    await test_nothing_is_lost()

    print()
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}")
        for f in _failures:
            print(f"  - {f}")
        sys.exit(1)
    print("Все проверки прошли.")


if __name__ == "__main__":
    asyncio.run(main())
