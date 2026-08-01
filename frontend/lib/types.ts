/**
 * Типы данных — зеркало Pydantic-схем бэкенда.
 * Держим в одном месте, чтобы при изменении API править только тут.
 */

export type GeoLevel = "country" | "region" | "city" | "district" | "metro";

export interface GeoNode {
  id: string;
  name: string;
  level: GeoLevel;
  parent_id: string | null;
  search_hint: string;
}

export interface SearchRequest {
  category: string;
  /**
   * Точечный поиск: название, адрес, телефон или ссылка на карточку в
   * Яндекс.Картах. Задан — гео и рубрика не используются, запрос уходит
   * как есть.
   */
  raw_query?: string | null;
  country_id?: string;
  region_id?: string | null;
  city_id?: string | null;
  district_id?: string | null;
  metro_id?: string | null;
  limit: number;
  fetch_websites: boolean;
  enrich_sites: boolean;
}

export interface Organization {
  name: string;
  address: string | null;
  lat: number | null;
  lon: number | null;
  phone: string | null;
  website: string | null;
  email: string | null;
  socials: string[];
  hours: string | null;
  rating: number | null;
  reviews_count: number | null;
  categories: string[];
  permalink: string | null;
}

export type TaskStage =
  | "queued"
  | "parsing_list"
  | "parsing_cards"
  | "enriching_sites"
  | "done"
  | "failed"
  | "cancelled";

export interface TaskProgress {
  task_id: string;
  stage: TaskStage;
  processed: number;
  total: number;
  found_with_website: number;
  found_without_website: number;
  message: string;
  started_at: string;
  updated_at: string;
  error: string | null;
}

export interface TaskResult {
  task_id: string;
  progress: TaskProgress;
  organizations: Organization[];
  search: SearchRequest;
}

/* Человекочитаемые подписи этапов */
export const STAGE_LABELS: Record<TaskStage, string> = {
  queued: "В очереди",
  parsing_list: "Листаю выдачу Яндекс.Карт",
  parsing_cards: "Открываю карточки организаций",
  enriching_sites: "Собираю email и соцсети с сайтов",
  done: "Готово",
  failed: "Ошибка",
  cancelled: "Отменено",
};

export const STAGE_ORDER: TaskStage[] = [
  "queued",
  "parsing_list",
  "parsing_cards",
  "enriching_sites",
  "done",
];

export function isFinalStage(stage: TaskStage): boolean {
  return stage === "done" || stage === "failed" || stage === "cancelled";
}

/* ------------------------------------------------------------------ */
/* История выгрузок                                                     */
/* ------------------------------------------------------------------ */

/** Строка списка недавних выгрузок — без самих организаций. */
export interface HistoryRun {
  task_id: string;
  category: string;
  location: string;
  found_count: number;
  with_website: number;
  created_at: string;
}

/* ------------------------------------------------------------------ */
/* Отбор клиентов                                                       */
/* ------------------------------------------------------------------ */

/** Что лежит в поле «сайт»: свой сайт, соцсеть, виджет записи, конструктор. */
export type LinkKind = "own" | "social" | "booking" | "builder" | "none";

/**
 * Две независимые оси, их нельзя смешивать.
 * `demo`   — соберём ли базу знаний автоматом (нужен обходимый сайт);
 * `verdict` — стоит ли вообще писать этой компании.
 * У школы с одной страницей ВКонтакте demo="manual" и при этом verdict="good".
 */
export type DemoFitness = "auto" | "manual";
export type VerdictState = "good" | "maybe" | "skip";

export interface ProspectVerdict {
  site: string;
  name: string | null;
  website: string | null;
  link_kind: LinkKind;
  demo: DemoFitness;
  verdict: VerdictState;
  reasons: string[];
  duplicate_of: string | null;
  http_status: number | null;
  text_len: number | null;
  last_year: number | null;
  scale: string | null;
  alive: string | null;
  checked_at: string | null;
}

export interface ScanResult {
  items: ProspectVerdict[];
  classified: number;
  llm_enabled: boolean;
  quota_hit: number;
}

export const VERDICT_LABELS: Record<VerdictState, string> = {
  good: "Годится",
  maybe: "Сомнительно",
  skip: "Мимо",
};

/* ------------------------------------------------------------------ */
/* Персональные демо ИИ-ассистента (интеграция с kb_assistant)          */
/* ------------------------------------------------------------------ */

export interface DemoConfig {
  /** Адрес и ключ kb_assistant заданы — колонку «Демо» вообще показываем. */
  enabled: boolean;
  /** kb_assistant уже отвечает. Docker-стек поднимается около минуты. */
  ready: boolean;
  bot_username: string | null;
  max_pages: number;
}

/**
 * "pending" / "crawling" — база знаний ещё собирается,
 * "ready" — ссылку можно отправлять клиенту,
 * "thin" — собралось, но отвечать нечем: сайт отдал в основном служебные
 *          страницы. Ссылка рабочая, но клиенту такое слать нельзя,
 * "failed" — сайт не удалось прокраулить,
 * "error" — сбой обращения к kb_assistant (не статус самого демо).
 */
export type DemoState =
  | "pending"
  | "crawling"
  | "ready"
  | "thin"
  | "failed"
  | "error";

export interface DemoStatus {
  name: string | null;
  website: string | null;
  slug: string;
  link: string | null;
  status: DemoState;
  error: string | null;
  pages_indexed: number;
  opened_count: number;
  message_count: number;
}

export const DEMO_STATE_LABELS: Record<DemoState, string> = {
  pending: "В очереди",
  crawling: "Собираю сайт",
  ready: "Готово",
  thin: "Мало данных",
  failed: "Не вышло",
  error: "Ошибка связи",
};

/** Демо ещё в работе — таблица продолжает опрашивать статус. */
export function isDemoPending(status: DemoState): boolean {
  return status === "pending" || status === "crawling";
}

export function isErrorStage(stage: TaskStage): boolean {
  return stage === "failed" || stage === "cancelled";
}
