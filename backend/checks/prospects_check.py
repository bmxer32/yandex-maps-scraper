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


def test_card_sites_and_phones() -> None:
    """Карточка «Healthy Hair & Muse Beauty» — на ней мы и обожглись.

    Рекламная карусель «Товары и услуги» лежит в HTML раньше блока контактов,
    и её ссылка на страницу записи попадала в выгрузку вместо сайта. Компания
    выглядела как «нормального сайта нет» — и ей пошли делать сайт, который
    у неё был.
    """
    print("\nсайты и телефоны из карточки:")
    from app.core.scraper.yandex_maps import _phones_from_card, _sites_from_card

    html = (
        '<a target="_blank" href="https://musebeauty.ru" class="card-special-offers-view__item">'
        "<div>Наращивание волос</div></a>"
        '<div class="business-urls-view__url">'
        '<a itemprop="url" class="business-urls-view__link" href="http://healthyhairfamily.ru/">'
        "<span>healthyhairfamily.ru</span></a></div>"
        '<script>{"phones":[{"number":"+7 (966) 777-57-70","value":"+79667775770","info":"Москва"},'
        '{"number":"+7 (988) 508-84-88","value":"+79885088488","info":"Сочи"}],'
        '"urls":["http://healthyhairfamily.ru/","http://musebeauty.ru/"],'
        '"socialLinks":[{"type":"telegram","href":"https://t.me/healthyhairfamily"}]}</script>'
    )

    sites = _sites_from_card(html)
    check(sites and sites[0] == "http://healthyhairfamily.ru",
          "главный сайт — настоящий, а не ссылка из рекламной карусели")
    check(len(sites) == 2 and "http://musebeauty.ru" in sites,
          "второй сайт не потерялся")

    phones = _phones_from_card(html)
    check(len(phones) == 2, "оба телефона на месте")
    check(phones[0].endswith("(Москва)") and phones[1].endswith("(Сочи)"),
          "город при каждом номере")

    # Вёрстка без данных карточки — запасной путь по itemprop
    only_markup = html.split("<script>")[0]
    check(_sites_from_card(only_markup) == ["http://healthyhairfamily.ru"],
          "без JSON берём блок контактов, а не карусель")

    check(_sites_from_card("<a href='https://vk.com/x'>vk</a>") == [],
          "соцсеть сайтом не считается")


def test_several_sites() -> None:
    """Несколько ссылок: судим по лучшей, а не по первой попавшейся."""
    print("\nнесколько сайтов у компании:")
    from app.services.prospect_rules import best_link

    org = Organization(
        name="Салон",
        website="https://n123456.yclients.com",
        websites=["https://n123456.yclients.com", "https://salon.ru"],
        reviews_count=40,
    )
    kind, url = best_link(org)
    check(kind == "own" and url == "https://salon.ru", "настоящий сайт важнее виджета записи")

    base = evaluate(org)
    check(base["demo"] == "auto", "демо соберётся: обходимый сайт есть")
    check(base["web"] == "maybe", "не объявляем «нужен сайт» тому, у кого он есть")
    check(any("ссылок несколько" in r for r in base["reasons"]), "перечислили все ссылки")

    from app.services.site_probe import ProbeResult, TechSignals

    v = ProspectVerdict(site="x", name="X", verdict="good", web="good", demo="auto")
    prospect_service._apply_other_sites(
        v, [("https://salon.ru", ProbeResult(ok=True, status=200, text_len=5000))]
    )
    check(v.web == "skip", "живой современный сайт во второй ссылке снимает ось")

    # А там, где записываются на время, тот же сайт без записи ось не снимает
    # совсем: сайт есть, но клиенту всё равно приходится писать администратору.
    v = ProspectVerdict(site="x2", name="Салон", verdict="good", web="good", demo="auto")
    prospect_service._apply_other_sites(
        v,
        [("https://salon.ru", ProbeResult(ok=True, status=200, text_len=5000))],
        booking_matters=True,
    )
    check(v.web == "maybe", "второй сайт без записи — «возможно», а не «не нужен»")

    v = ProspectVerdict(site="y", name="Y", verdict="good", web="good", demo="auto")
    prospect_service._apply_other_sites(
        v,
        [("https://old.ru", ProbeResult(ok=True, status=200, text_len=5000,
                                        tech=TechSignals(php_links=True, responsive=False)))],
    )
    check(v.web == "good", "вторая старая страница не снимает и не добавляет ничего")

    # Модель не имеет права звать делать сайт тому, у кого он рабочий
    v = ProspectVerdict(site="z", name="Z", verdict="good", web="skip", demo="auto")
    prospect_service._apply_llm(
        v,
        site_verdict.Verdict(scale="одиночка", alive="живой", verdict="годится",
                             web="годится", web_reason="сайт бедный"),
        30,
        live_site=True,
    )
    check(v.web == "maybe", "при живом сайте «годится» от модели — только «возможно»")


def test_tech_signals() -> None:
    """Признаки берутся из той же страницы, что уже скачана для оценки."""
    print("\nпризнаки устаревшего сайта:")
    from app.services.site_probe import _tech

    old = _tech(
        '<html><head></head><body><table><tr><td>меню</td></tr></table>'
        '<a href="/index.php">Главная</a>'
        '<script src="/js/jquery-1.8.3.min.js"></script></body></html>',
        "http://old-site.ru/",
    )
    check(old.outdated, "старый стек распознан как устаревший")
    check(not old.responsive, "нет viewport → не адаптивный")
    check(old.no_tls, "http:// без TLS замечен")
    check(old.jquery_old and old.jquery == "1.8", "старая версия jQuery найдена")
    check(old.table_layout and old.php_links, "таблицы и .php замечены")

    modern = _tech(
        '<html><head><meta name="viewport" content="width=device-width">'
        '<script src="/app.js" type="module"></script></head><body>ok</body></html>',
        "https://new-site.ru/",
    )
    check(not modern.outdated, "современный сайт не помечен устаревшим")

    # Tilda отдаёт jQuery 1.10 со своего CDN: по нему любой её сайт выглядел
    # бы десятилетним, и вся выдача уехала бы в «редизайн» ложно.
    tilda = _tech(
        '<html><head></head><body>'
        '<script src="https://static.tildacdn.com/js/jquery-1.10.2.min.js"></script>'
        "</body></html>",
        "https://studio.ru/",
    )
    check(tilda.builder, "конструктор распознан")
    check(not tilda.outdated, "конструктор НЕ считается устаревшим — jQuery там платформенный")
    # Про стек конструктора говорить нечего, а вот про запись — есть: это
    # свойство сайта, а не платформы, и оно к делу относится.
    check(tilda.summary()[0] == "сайт на конструкторе",
          "у конструктора не перечисляем чужой стек")
    check(not any("jQuery" in s for s in tilda.summary()),
          "платформенный jQuery в причины не попал")

    tilda_booking = _tech(
        '<script src="https://static.tildacdn.com/js/jquery-1.10.2.min.js"></script>'
        '<a href="https://n1224963.yclients.com">Записаться</a>',
        "https://studio.ru/",
    )
    check(tilda_booking.summary() == ["сайт на конструкторе"],
          "конструктор с записью — сказать больше нечего")

    # …но конструктор конструктору рознь: uCoz — платформа нулевых, и это как
    # раз тот «старый сайт», ради которого ось и заводилась.
    ucoz = _tech(
        '<html><head><meta name="viewport" content="width=device-width"></head>'
        '<body><script src="//s.ucoz.net/src/uwnd.min.js"></script></body></html>',
        "https://salon.ucoz.ru/",
    )
    check(ucoz.legacy_builder and ucoz.outdated, "устаревший конструктор — кандидат на замену")
    check(not tilda.legacy_builder, "Tilda устаревшей не считается")


def test_online_booking() -> None:
    """Записью считается виджет, а не слово «Записаться».

    На сайте салона кнопка «Записаться» ведёт в телеграм — по тексту такой сайт
    выглядел бы как сайт с записью, хотя клиент там пишет администратору и ждёт.
    """
    print("\nонлайн-запись на сайте:")
    from app.services.prospect_rules import needs_booking
    from app.services.site_probe import _tech

    widget = _tech('<a href="https://n1224963.yclients.com">Записаться</a>', "https://s.ru")
    check(widget.booking, "виджет YCLIENTS — это запись")
    check(_tech('<a href="https://dikidi.net/#widget=51285">Записаться</a>', "https://s.ru").booking,
          "виджет DIKIDI — это запись")

    fake = _tech('<a href="https://t.me/salon">Записаться</a>', "https://s.ru")
    check(not fake.booking, "кнопка «Записаться» в телеграм записью не считается")
    check(fake.booking_note() == ["на сайте нельзя записаться — только мессенджер или звонок"],
          "формулировка про мессенджер")

    only_form = _tech("<form action='/send'><input name='tel'></form>", "https://s.ru")
    check(only_form.form and not only_form.booking, "форма — не запись")
    check(only_form.booking_note() == ["на сайте только форма заявки, времени не выбрать"],
          "форма описана отдельно")

    check(needs_booking(Organization(name="Студия", categories=["Салон красоты"])),
          "в салон записываются")
    check(needs_booking(Organization(name="Стоматология Улыбка", categories=[])),
          "в стоматологию записываются")
    check(not needs_booking(Organization(name="Пятёрочка", categories=["Продукты"])),
          "в магазин не записываются — правило его не трогает")

    from app.services.site_probe import ProbeResult, TechSignals

    v = ProspectVerdict(site="s", name="Салон", verdict="good", demo="auto")
    prospect_service._apply_probe(
        v, ProbeResult(ok=True, status=200, text_len=5000), booking_matters=True
    )
    check(v.web == "maybe", "современный сайт без записи — «возможно», а не «не нужен»")

    v = ProspectVerdict(site="m", name="Магазин", verdict="good", demo="auto")
    prospect_service._apply_probe(
        v, ProbeResult(ok=True, status=200, text_len=5000), booking_matters=False
    )
    check(v.web == "skip", "магазину запись не нужна — вердикт не портим")

    v = ProspectVerdict(site="b", name="Салон", verdict="good", demo="auto")
    prospect_service._apply_probe(
        v,
        ProbeResult(ok=True, status=200, text_len=5000, tech=TechSignals(booking=True)),
        booking_matters=True,
    )
    check(v.web == "skip", "запись есть — переделывать нечего")

    # Сайт салона на Tilda: переделывать нечего, но и записи нет — человек
    # должен видеть, почему строка «возможно», а не гадать.
    v = ProspectVerdict(site="t", name="Салон", verdict="good", demo="auto")
    prospect_service._apply_probe(
        v,
        ProbeResult(ok=True, status=200, text_len=5000, tech=TechSignals(builder=True)),
        booking_matters=True,
    )
    check(v.web == "maybe", "конструктор без записи — «возможно»")
    check(any("конструктор" in r for r in v.web_reasons)
          and any("записаться" in r for r in v.web_reasons),
          "названы обе причины: и конструктор, и отсутствие записи")

    v = ProspectVerdict(site="t2", name="Магазин", verdict="good", demo="auto")
    prospect_service._apply_probe(
        v,
        ProbeResult(ok=True, status=200, text_len=5000, tech=TechSignals(builder=True)),
        booking_matters=False,
    )
    check(not any("записаться" in r for r in v.web_reasons),
          "магазину про запись не пишем")


def test_web_axis() -> None:
    """Вторая ось живёт отдельно от первой: нет сайта — плохо для демо, но это лучший клиент."""
    print("\nось «сайт»:")
    check(evaluate(Organization(name="A", website=None))["web"] == "good",
          "сайта нет → лучший клиент на создание")
    check(evaluate(Organization(name="B", website="https://vk.ru/x"))["web"] == "good",
          "соцсеть вместо сайта → тоже цель")
    check(evaluate(Organization(name="C", website="https://x.tilda.ws"))["web"] == "maybe",
          "конструктор → сомнительно, а не цель")
    check(evaluate(Organization(name="D", website="https://salon.ucoz.ru"))["web"] == "good",
          "устаревший конструктор → цель на замену")

    from app.services.site_probe import ProbeResult, TechSignals

    v = ProspectVerdict(site="x", name="X", verdict="good", demo="auto")
    prospect_service._apply_probe(
        v, ProbeResult(ok=True, status=200, text_len=5000,
                       tech=TechSignals(responsive=False, php_links=True))
    )
    check(v.web == "good", "устаревший стек → «нужен сайт»")

    v = ProspectVerdict(site="y", name="Y", verdict="good", demo="auto")
    prospect_service._apply_probe(v, ProbeResult(ok=True, status=200, text_len=5000))
    check(v.web == "skip", "современный сайт → переделывать нечего")

    v = ProspectVerdict(site="z", name="Z", verdict="good", demo="auto")
    prospect_service._apply_probe(v, ProbeResult(ok=False, error="ConnectError"))
    check(v.web == "good", "сайт не отвечает → повод обратиться")


def test_chain_closes_both_axes() -> None:
    """Ровно тот случай, из-за которого 4hands висел среди приоритетных."""
    print("\nсеть закрывает обе оси:")
    v = ProspectVerdict(site="x", name="4hands", verdict="good", web="good", demo="manual")
    prospect_service._apply_llm(
        v,
        site_verdict.Verdict(scale="франшиза", alive="живой", verdict="мимо",
                             reason="федеральная сеть", web="мимо", web_reason="сайт централизован"),
        33,
    )
    check(v.verdict == "skip", "ассистент — мимо")
    check(v.web == "skip", "сайт — тоже мимо")

    v = ProspectVerdict(site="y", name="Одиночка", verdict="good", web="good", demo="auto")
    prospect_service._apply_llm(v, site_verdict.Verdict(error="лимит запросов к модели исчерпан"), 10)
    check(v.verdict == "good" and v.web == "good", "молчание модели не понижает ни одну ось")


def test_maps_url_parsing() -> None:
    """Ссылку на карточку надо открывать напрямую: поиск по ней ничего не даёт."""
    print("\nразбор ссылок на Яндекс.Карты:")
    from app.core.scraper.yandex_maps import oid_from_maps_url

    cases = {
        "https://yandex.ru/maps/org/108811824146/": "108811824146",
        "https://yandex.ru/maps/org/albera/1172396568/": "1172396568",
        "https://yandex.com/maps/54/novosibirsk/org/albera/171066077052/": "171066077052",
        "https://yandex.ru/maps/?ll=38.9,45.0&z=17": None,
        "Альбера Новосибирск": None,
        "+7 923 244-61-42": None,
        "": None,
    }
    for text, expect in cases.items():
        got = oid_from_maps_url(text)
        check(got == expect, f"{(text or '(пусто)')[:44]:<46} → {got}")


def test_social_links() -> None:
    """Ссылка на сам мессенджер вместо аккаунта — хуже, чем её отсутствие."""
    print("\nссылки на соцсети:")
    from app.core.scraper.socials import normalize_social as n

    # Реальные случаи из выгрузки: по ним клиент попадал на telegram.org.
    check(n("Telegram", "https://t.me/Салон") is None,
          "кириллический «юзернейм» отброшен")
    check(n("Telegram", "https://telegram.org") is None, "голый telegram.org отброшен")
    check(n("Telegram", "https://t.me/") is None, "t.me без пути отброшен")
    check(n("Telegram", "https://t.me/ab") is None, "слишком короткий юзернейм отброшен")
    check(n("VK", "https://vk.com/") is None, "vk.com без аккаунта отброшен")
    check(n("Facebook", "https://facebook.com/sharer.php") is None, "кнопка «поделиться» отброшена")

    check(n("Telegram", "https://t.me/abc_engschool") == "Telegram: https://t.me/abc_engschool",
          "нормальный юзернейм сохранён")
    check(n("Telegram", "https://t.me/79110011147") == "Telegram: https://t.me/+79110011147",
          "телефон без плюса починен")
    check(n("Telegram", "https://t.me/89006502424") == "Telegram: https://t.me/+79006502424",
          "местный формат 8… приведён к +7…")
    check(n("WhatsApp", "https://wa.me/89006502424") == "WhatsApp: https://wa.me/79006502424",
          "то же для WhatsApp")


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
    test_card_sites_and_phones()
    test_several_sites()
    test_tech_signals()
    test_online_booking()
    test_web_axis()
    test_chain_closes_both_axes()
    test_maps_url_parsing()
    test_social_links()
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
