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
