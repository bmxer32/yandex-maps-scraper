import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Объединение классов tailwind с разрешением конфликтов (shadcn-style). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Чисто отформатировать телефон для показа. */
export function formatPhone(phone: string | null): string {
  if (!phone) return "—";
  const digits = phone.replace(/\D/g, "");
  if (digits.length === 11 && (digits[0] === "7" || digits[0] === "8")) {
    return `+7 ${digits.slice(1, 4)} ${digits.slice(4, 7)}-${digits.slice(7, 9)}-${digits.slice(9)}`;
  }
  return phone;
}

/** Сократить длинный URL для показа в таблице. */
export function shortenUrl(url: string | null, max = 38): string {
  if (!url) return "";
  try {
    const u = new URL(url.startsWith("http") ? url : `https://${url}`);
    const display = u.hostname.replace(/^www\./, "") + (u.pathname !== "/" ? u.pathname : "");
    return display.length > max ? display.slice(0, max - 1) + "…" : display;
  } catch {
    return url.length > max ? url.slice(0, max - 1) + "…" : url;
  }
}

/** Нормализовать сайт в полный URL для ссылки. */
export function normalizeUrl(url: string | null): string | null {
  if (!url) return null;
  return url.startsWith("http") ? url : `https://${url}`;
}

/**
 * Ключ сайта для сопоставления строки таблицы с заведённым демо.
 * Схема, www и хвостовой слэш отбрасываются: организация та же, даже если
 * Яндекс отдал «http://site.ru/», а kb_assistant вернул «https://www.site.ru».
 */
export function siteKey(url: string | null | undefined): string {
  if (!url) return "";
  return url
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, "")
    .replace(/^www\./, "")
    .replace(/\/+$/, "");
}

/**
 * Ключ строки таблицы для вердикта отбора.
 *
 * У компании без сайта `siteKey` пустой, и все такие строки слиплись бы в один
 * ключ. Для оси «сайт» это как раз лучшие клиенты — «сделать с нуля», — поэтому
 * им нужен свой ключ: название с адресом. Для демо ключ по-прежнему только
 * сайт: без сайта краулить нечего.
 */
export function rowKey(org: {
  name: string;
  website?: string | null;
  address?: string | null;
}): string {
  return siteKey(org.website) || `${org.name}|${org.address ?? ""}`.toLowerCase();
}

/**
 * Ключ конторы в разделе «В работе». Зеркалит `work_key` из бэкенда:
 * обе стороны должны считать одинаково, иначе звёздочка в таблице не сойдётся
 * с записью в разделе.
 *
 * permalink Яндекса стабилен и есть даже там, где нет ни сайта, ни телефона.
 */
export function workKey(org: {
  permalink?: string | null;
  name: string;
  address?: string | null;
}): string {
  const permalink = (org.permalink ?? "").trim();
  if (permalink) return permalink;
  return `${(org.name ?? "").trim().toLowerCase()}|${(org.address ?? "").trim().toLowerCase()}`;
}

/**
 * Ссылка на карточку организации в Яндекс.Картах.
 *
 * Парсер кладёт в `permalink` числовой id организации — по нему Яндекс сам
 * разворачивает полный адрес карточки. Если id почему-то нет, падаем на
 * поиск по координатам: показать место всё равно полезнее, чем ничего.
 */
export function yandexMapsUrl(org: {
  permalink?: string | null;
  lat?: number | null;
  lon?: number | null;
  name?: string;
}): string | null {
  if (org.permalink && /^\d+$/.test(org.permalink)) {
    return `https://yandex.ru/maps/org/${org.permalink}/`;
  }
  if (org.lat != null && org.lon != null) {
    const query = encodeURIComponent(org.name ?? "");
    return `https://yandex.ru/maps/?ll=${org.lon},${org.lat}&z=17&text=${query}`;
  }
  return null;
}

/** Разбить «Label: url» из socials на компоненты. */
export function parseSocial(s: string): { label: string; url: string } {
  const [label, ...rest] = s.split(":");
  return { label: label.trim(), url: rest.join(":").trim() };
}

/**
 * Ведёт ли ссылка на аккаунт, а не на сам сервис.
 *
 * Бэкенд такие уже отсеивает, но в истории лежат выгрузки, собранные до
 * этого — там встречается `t.me/Салон` и голый `telegram.org`. Telegram на
 * несуществующий адрес отдаёт свою главную, и клик выглядит как поломка.
 * Лучше не показать ссылку, чем показать ведущую в никуда.
 */
export function isUsefulSocial(url: string): boolean {
  if (!url || !/^https?:\/\//i.test(url)) return false;
  try {
    const u = new URL(url);
    const path = u.pathname.replace(/^\/|\/$/g, "");
    if (!path) return false;

    const host = u.hostname.replace(/^www\./, "").toLowerCase();
    if (host === "telegram.org") return false;

    if (host === "t.me" || host === "telegram.me") {
      const first = path.split("/")[0];
      // Юзернеймы в Telegram только латиницей; телефон — со знаком «+».
      return (
        /^[a-zA-Z][a-zA-Z0-9_]{4,31}$/.test(first) ||
        /^\+[\w-]{5,}$/.test(first) ||
        first.startsWith("joinchat")
      );
    }
    return true;
  } catch {
    return false;
  }
}

/**
 * Что в поле «сайт» сайтом не является — **только для сбора телеграм-контактов**.
 *
 * Сознательно отдельный список, а не общая классификация из отбора: там свои
 * оси и свой кэш вердиктов, и менять их ради выгрузки контактов нельзя.
 * Здесь вопрос ровно один — писать ли этой компании в телеграм как той, у кого
 * сайта нет.
 */
const _NOT_A_SITE = [
  // Мессенджеры и сокращатели: это способ написать, а не сайт.
  /(^|\.)viber\.(click|com)$/i,
  /(^|\.)vk\.(link|cc)$/i,
  /(^|\.)msng\.link$/i,
  /(^|\.)(vk\.(ru|com)|vkontakte\.ru|max\.ru|ok\.ru)$/i,
  /(^|\.)(t\.me|telegram\.me|wa\.me|api\.whatsapp\.com)$/i,
  /(^|\.)(instagram\.com|facebook\.com|youtube\.com|tiktok\.com)$/i,
  // Страницы онлайн-записи.
  /(^|\.)(yclients\.com|clients\.site|dikidi\.(net|ru|app)|easyweek\.\w+|sonline\.su)/i,
  /(^|\.)n\d{5,}\.\w+/i,
  // Конструкторы и «ссылка в шапке профиля».
  /(^|\.)(tilda\.ws|wixsite\.com|business\.site|taplink\.\w+|nethouse\.ru)$/i,
  /(^|\.)(umi\.ru|a5\.ru|ucoz\.\w+|jimdosite\.com|linktr\.ee)$/i,
];

/** Свой ли это сайт — в смысле сбора телеграм-контактов. */
function isRealSite(url: string | null | undefined): boolean {
  const host = siteKey(url).split("/")[0];
  if (!host) return false;
  return !_NOT_A_SITE.some((re) => re.test(host));
}

/**
 * Телеграм-контакты компаний **без своего сайта** — списком для рассылки.
 *
 * «Без сайта» значит, что писать в телеграм такой компании осмысленно: поля
 * нет вовсе, либо в нём ВКонтакте, виджет записи, конструктор или ссылка в
 * мессенджер. На живой выгрузке салонов своего сайта нет у 16 компаний из 35,
 * а совсем пустое поле — только у двух; считать по одному лишь пустому полю
 * значит потерять почти весь сегмент.
 *
 * Список «не сайт» здесь свой и на отбор клиентов не влияет — считаем одинаково
 * и до оценки, и после неё.
 *
 * В файл идут и юзернеймы, и телефоны: у половины таких компаний в телеграме
 * указан именно номер (`t.me/+79991234567`), и рассыльщики принимают оба вида.
 * Приглашения в закрытые чаты (`joinchat`, `t.me/+AbCdEf`) пропускаем — писать
 * по ним некому.
 */
export function telegramUsernames(
  orgs: {
    website?: string | null;
    websites?: string[] | null;
    socials?: string[] | null;
  }[],
): string[] {
  const out: string[] = [];
  const seen = new Set<string>();

  for (const org of orgs) {
    const links = org.websites?.length ? org.websites : org.website ? [org.website] : [];
    if (links.some(isRealSite)) continue;

    for (const raw of org.socials ?? []) {
      const { url } = parseSocial(raw);
      if (!isUsefulSocial(url)) continue;
      let host: string;
      let first: string;
      try {
        const u = new URL(url);
        host = u.hostname.replace(/^www\./, "").toLowerCase();
        first = u.pathname.replace(/^\/|\/$/g, "").split("/")[0];
      } catch {
        continue;
      }
      if (host !== "t.me" && host !== "telegram.me") continue;

      let contact: string | null = null;
      if (/^[a-zA-Z][a-zA-Z0-9_]{4,31}$/.test(first)) {
        contact = `@${first}`;
      } else {
        // Телефон: со знаком «+» или без него, но только цифры.
        const digits = first.replace(/^\+/, "");
        if (/^\d{10,15}$/.test(digits)) contact = `+${digits}`;
      }
      if (!contact) continue;

      const key = contact.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(contact);
    }
  }

  return out;
}

/** Скачать текст файлом — без обращения к бэкенду. */
export function downloadText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Число с разделителем тысяч. */
export function formatNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("ru-RU");
}

/** Превратить ISO-дату во время «ЧЧ:ММ:СС». */
export function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("ru-RU", { hour12: false });
  } catch {
    return iso;
  }
}

/** Прошедшее время в секундах между двумя ISO-датами. */
export function elapsedSeconds(start: string, end: string): number {
  try {
    return Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  } catch {
    return 0;
  }
}
