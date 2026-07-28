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

/** Разбить «Label: url» из socials на компоненты. */
export function parseSocial(s: string): { label: string; url: string } {
  const [label, ...rest] = s.split(":");
  return { label: label.trim(), url: rest.join(":").trim() };
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
