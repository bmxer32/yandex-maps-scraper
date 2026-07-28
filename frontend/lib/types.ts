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

export function isErrorStage(stage: TaskStage): boolean {
  return stage === "failed" || stage === "cancelled";
}
