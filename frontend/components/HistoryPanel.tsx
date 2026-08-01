"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Clock,
  Globe,
  Loader2,
  MapPin,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { deleteHistoryRun, listHistory, loadHistoryRun } from "@/lib/api";
import type { HistoryRun, TaskResult } from "@/lib/types";
import { cn, formatNumber } from "@/lib/utils";
import { Badge, Button } from "@/components/ui";

/**
 * Недавние выгрузки.
 *
 * Задачи парсера живут в памяти, поэтому перезапуск программы стирал
 * результат и приходилось собирать заново — минуты работы браузера и лишние
 * запросы к Яндексу. Здесь сохранённые выгрузки открываются как есть.
 */
export function HistoryPanel({ onOpen }: { onOpen: (result: TaskResult) => void }) {
  const [runs, setRuns] = useState<HistoryRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [opening, setOpening] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setRuns(await listHistory());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить историю");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function open(taskId: string) {
    setOpening(taskId);
    try {
      onOpen(await loadHistoryRun(taskId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось открыть выгрузку");
    } finally {
      setOpening(null);
    }
  }

  async function remove(taskId: string) {
    try {
      await deleteHistoryRun(taskId);
      setRuns((prev) => prev.filter((r) => r.task_id !== taskId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось удалить");
    }
  }

  if (loading && runs.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-border p-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Загружаю историю…
      </div>
    );
  }

  return (
    <div className="animate-fade-in space-y-4">
      <div className="flex items-center justify-between">
        <Badge variant="outline" className="px-3 py-1 text-sm">
          <Clock className="mr-1 h-3 w-3" />
          {formatNumber(runs.length)} выгрузок
        </Badge>
        <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          Обновить
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm">
          {error}
        </div>
      )}

      {runs.length === 0 ? (
        <div className="rounded-lg border border-border p-8 text-center text-sm text-muted-foreground">
          Пока пусто. Соберите организации — выгрузка сохранится сюда сама,
          и после перезапуска её можно будет открыть без повторного парсинга.
        </div>
      ) : (
        <div className="grid gap-2">
          {runs.map((run) => (
            <div
              key={run.task_id}
              className="flex items-center justify-between gap-4 rounded-lg border border-border p-3 transition-colors hover:bg-secondary/30"
            >
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">
                  {run.category || "Без названия"}
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  {run.location && (
                    <span className="inline-flex items-center gap-1">
                      <MapPin className="h-3 w-3" />
                      {run.location}
                    </span>
                  )}
                  <span>{formatNumber(run.found_count)} организаций</span>
                  <span className="inline-flex items-center gap-1 text-success">
                    <Globe className="h-3 w-3" />
                    {formatNumber(run.with_website)} с сайтом
                  </span>
                  <span>{formatWhen(run.created_at)}</span>
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => open(run.task_id)}
                  disabled={opening === run.task_id}
                >
                  {opening === run.task_id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : null}
                  Открыть
                </Button>
                <button
                  onClick={() => remove(run.task_id)}
                  title="Удалить из истории"
                  className="text-muted-foreground transition-colors hover:text-destructive"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** «Сегодня 14:32» вместо голой даты — так быстрее находишь нужное. */
function formatWhen(iso: string): string {
  try {
    const d = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
    const today = new Date();
    const sameDay = d.toDateString() === today.toDateString();
    const time = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    if (sameDay) return `сегодня ${time}`;
    return `${d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" })} ${time}`;
  } catch {
    return iso;
  }
}
