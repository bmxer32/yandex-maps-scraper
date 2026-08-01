/**
 * Клиент к FastAPI бэкенду.
 * Все URL берутся из NEXT_PUBLIC_API_URL (по умолчанию http://127.0.0.1:8000).
 */
import type {
  DemoConfig,
  DemoStatus,
  GeoNode,
  HistoryRun,
  ProspectVerdict,
  ScanResult,
  SearchRequest,
  TaskProgress,
  TaskResult,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

/** Универсальный обработчик ответа. */
async function handle<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const text = await resp.text().catch(() => resp.statusText);
    throw new Error(`API ${resp.status}: ${text}`);
  }
  return (await resp.json()) as T;
}

/* ------------------------------------------------------------------ */

export async function getGeoTree(): Promise<GeoNode[]> {
  // no-store — иначе Next.js закэширует дерево навсегда, и при изменении
  // id на бэкенде фронт продолжит слать старые (несуществующие) id.
  const resp = await fetch(`${API_URL}/api/geo/tree`, { cache: "no-store" });
  return handle<GeoNode[]>(resp);
}

export async function createSearch(req: SearchRequest): Promise<{ task_id: string }> {
  const resp = await fetch(`${API_URL}/api/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return handle<{ task_id: string }>(resp);
}

export async function getTask(taskId: string): Promise<TaskResult> {
  const resp = await fetch(`${API_URL}/api/task/${taskId}`);
  return handle<TaskResult>(resp);
}

export async function listTasks(): Promise<TaskProgress[]> {
  const resp = await fetch(`${API_URL}/api/tasks`);
  return handle<TaskProgress[]>(resp);
}

export async function cancelTask(taskId: string): Promise<void> {
  await fetch(`${API_URL}/api/task/${taskId}/cancel`, { method: "POST" });
}

/* Экспорт: просто возвращаем URL, фронт качает напрямую. */
export function exportUrl(
  taskId: string,
  fmt: "xlsx" | "csv" = "xlsx",
  onlyWithWebsite = false,
): string {
  const params = new URLSearchParams({ fmt });
  if (onlyWithWebsite) params.set("only_with_website", "true");
  return `${API_URL}/api/export/${taskId}?${params.toString()}`;
}

/* ------------------------------------------------------------------ */
/* История выгрузок                                                    */
/* ------------------------------------------------------------------ */

/** Недавние выгрузки — задачи живут в памяти и перезапуск их не переживает. */
export async function listHistory(): Promise<HistoryRun[]> {
  const resp = await fetch(`${API_URL}/api/history`, { cache: "no-store" });
  return handle<HistoryRun[]>(resp);
}

/** Открыть сохранённую выгрузку целиком, без повторного парсинга. */
export async function loadHistoryRun(taskId: string): Promise<TaskResult> {
  const resp = await fetch(`${API_URL}/api/history/${taskId}`, { cache: "no-store" });
  return handle<TaskResult>(resp);
}

export async function deleteHistoryRun(taskId: string): Promise<void> {
  const resp = await fetch(`${API_URL}/api/history/${taskId}`, { method: "DELETE" });
  if (!resp.ok && resp.status !== 204) {
    throw new Error(`API ${resp.status}`);
  }
}

/* ------------------------------------------------------------------ */
/* Отбор клиентов                                                      */
/* ------------------------------------------------------------------ */

/** Оценить организации: тип ссылки, дубли, проба сайта, вердикт модели. */
export async function scanProspects(
  items: {
    name: string;
    website: string | null;
    reviews_count: number | null;
    rating: number | null;
    socials: string[];
    /** Все сайты компании: судить о «нужен ли сайт» по одному нельзя. */
    websites: string[];
    /** Город и рубрики: у компании без сайта это всё, по чему модель её узнаёт. */
    address: string | null;
    categories: string[];
  }[],
  refresh = false,
): Promise<ScanResult> {
  const resp = await fetch(`${API_URL}/api/prospects/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items, refresh }),
  });
  return handle<ScanResult>(resp);
}

/** Уже посчитанные вердикты — чтобы не пересчитывать при возврате к выдаче. */
export async function getVerdicts(sites: string[]): Promise<ProspectVerdict[]> {
  if (sites.length === 0) return [];
  const params = new URLSearchParams();
  sites.forEach((s) => params.append("site", s));
  const resp = await fetch(`${API_URL}/api/prospects/verdicts?${params.toString()}`, {
    cache: "no-store",
  });
  return handle<ProspectVerdict[]>(resp);
}

/* ------------------------------------------------------------------ */
/* Персональные демо ИИ-ассистента                                     */
/* ------------------------------------------------------------------ */

/** Настроена ли интеграция с kb_assistant. Кнопка «Демо» скрыта, если нет. */
export async function getDemoConfig(): Promise<DemoConfig> {
  const resp = await fetch(`${API_URL}/api/demos/config`, { cache: "no-store" });
  return handle<DemoConfig>(resp);
}

/** Завести демо пачке организаций: краул сайта идёт в фоне. */
export async function provisionDemos(
  items: { name: string; website: string }[],
): Promise<DemoStatus[]> {
  const resp = await fetch(`${API_URL}/api/demos/provision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  const data = await handle<{ items: DemoStatus[] }>(resp);
  return data.items;
}

/** Статусы конкретных демо — для опроса, пока идёт краул. */
export async function getDemoStatuses(slugs: string[]): Promise<DemoStatus[]> {
  if (slugs.length === 0) return [];
  const params = new URLSearchParams();
  slugs.forEach((s) => params.append("slug", s));
  const resp = await fetch(`${API_URL}/api/demos/status?${params.toString()}`, {
    cache: "no-store",
  });
  const data = await handle<{ items: DemoStatus[] }>(resp);
  return data.items;
}

/** Удалить демо вместе с собранной базой знаний. */
export async function deleteDemo(slug: string): Promise<void> {
  const resp = await fetch(`${API_URL}/api/demos/${encodeURIComponent(slug)}`, {
    method: "DELETE",
  });
  if (!resp.ok && resp.status !== 204) {
    const text = await resp.text().catch(() => resp.statusText);
    throw new Error(`API ${resp.status}: ${text}`);
  }
}

/** Все заведённые демо — чтобы таблица знала о них после перезапуска. */
export async function listDemos(): Promise<DemoStatus[]> {
  const resp = await fetch(`${API_URL}/api/demos/list`, { cache: "no-store" });
  const data = await handle<{ items: DemoStatus[] }>(resp);
  return data.items;
}

/**
 * Подписка на SSE-стрим прогресса задачи.
 * Возвращает функцию отписки.
 */
export function subscribeProgress(
  taskId: string,
  onProgress: (p: TaskProgress) => void,
  onError?: (e: Event) => void,
): () => void {
  const url = `${API_URL}/api/task/${taskId}/stream`;
  const es = new EventSource(url);

  es.addEventListener("progress", (e) => {
    try {
      const data = JSON.parse((e as MessageEvent).data) as TaskProgress;
      onProgress(data);
    } catch (err) {
      console.error("SSE parse error", err);
    }
  });

  es.onerror = (e) => {
    if (onError) onError(e);
    // EventSource сам переподключится; но при финальных стейджах бэкенд
    // закрывает поток, так что закроем руками, чтобы не было цикла.
  };

  return () => es.close();
}
