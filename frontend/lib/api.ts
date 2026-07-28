/**
 * Клиент к FastAPI бэкенду.
 * Все URL берутся из NEXT_PUBLIC_API_URL (по умолчанию http://127.0.0.1:8000).
 */
import type {
  GeoNode,
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
