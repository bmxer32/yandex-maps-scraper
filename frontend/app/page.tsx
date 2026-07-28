"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Map, Database, Github, Zap } from "lucide-react";
import type { GeoNode, SearchRequest, TaskProgress, TaskResult } from "@/lib/types";
import {
  cancelTask,
  createSearch,
  getGeoTree,
  getTask,
  subscribeProgress,
} from "@/lib/api";
import { isFinalStage } from "@/lib/types";
import { SearchForm } from "@/components/SearchForm";
import { ProgressView } from "@/components/ProgressView";
import { ResultsTable } from "@/components/ResultsTable";
import { Skeleton, Toast } from "@/components/ui";

export default function Home() {
  const [geoTree, setGeoTree] = useState<GeoNode[]>([]);
  const [geoLoading, setGeoLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const [progress, setProgress] = useState<TaskProgress | null>(null);
  const [result, setResult] = useState<TaskResult | null>(null);
  const [toast, setToast] = useState<{ msg: string; variant?: "default" | "destructive" } | null>(null);

  const unsubscribeRef = useRef<(() => void) | null>(null);

  // Загрузка гео-дерева один раз
  useEffect(() => {
    let alive = true;
    getGeoTree()
      .then((tree) => alive && setGeoTree(tree))
      .catch((e) => alive && setToast({ msg: `Не удалось загрузить географию: ${e.message}`, variant: "destructive" }))
      .finally(() => alive && setGeoLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  // Отписка от SSE при размонтировании
  useEffect(() => {
    return () => unsubscribeRef.current?.();
  }, []);

  const handleSubmit = useCallback(
    async (req: SearchRequest) => {
      setSubmitting(true);
      setResult(null);
      setProgress(null);
      try {
        const { task_id } = await createSearch(req);

        // Подписываемся на прогресс
        unsubscribeRef.current?.();
        unsubscribeRef.current = subscribeProgress(task_id, async (p) => {
          setProgress(p);
          if (isFinalStage(p.stage)) {
            // Тянем финальный результат
            try {
              const res = await getTask(task_id);
              setResult(res);
            } catch (e) {
              setToast({ msg: `Не удалось получить результат: ${(e as Error).message}`, variant: "destructive" });
            }
            unsubscribeRef.current?.();
            unsubscribeRef.current = null;
          }
        });
      } catch (e) {
        setToast({ msg: `Не удалось запустить поиск: ${(e as Error).message}`, variant: "destructive" });
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const handleCancel = useCallback(async () => {
    if (!progress) return;
    try {
      await cancelTask(progress.task_id);
    } catch {
      /* ниже по потоку обновится статусом cancelled */
    }
  }, [progress]);

  const handleDismiss = useCallback(() => {
    setProgress(null);
  }, []);

  return (
    <main className="min-h-screen">
      {/* Шапка */}
      <header className="sticky top-0 z-30 glass">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <div className="relative flex h-9 w-9 items-center justify-center rounded-lg bg-primary/15 text-primary">
              <Map className="h-5 w-5" />
              <span className="absolute -right-0.5 -top-0.5 flex h-2.5 w-2.5">
                <span className="absolute h-full w-full animate-ping rounded-full bg-primary/60" />
                <span className="h-full w-full rounded-full bg-primary" />
              </span>
            </div>
            <div>
              <h1 className="text-base font-semibold leading-tight">Yandex Maps Scraper</h1>
              <p className="text-[11px] leading-tight text-muted-foreground">
                Сфера · контакты · сайты · email
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <a
              href="http://127.0.0.1:8000/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="hidden items-center gap-1.5 rounded-md px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-secondary/50 hover:text-foreground sm:inline-flex"
            >
              <Database className="h-3.5 w-3.5" />
              API
            </a>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-secondary/30 px-2.5 py-1 text-[11px] text-muted-foreground">
              <Zap className="h-3 w-3 text-primary" />
              v0.1
            </span>
          </div>
        </div>
      </header>

      {/* Контент */}
      <div className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-6 sm:py-8">
        {/* Hero — только когда ничего ещё не запущено */}
        {!progress && !result && (
          <div className="mb-2 flex flex-col items-start gap-2">
            <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
              Сбор данных с Яндекс.Карт
            </h2>
            <p className="max-w-2xl text-sm text-muted-foreground">
              Введите сферу бизнеса, выберите локацию — соберём названия, адреса,
              телефоны, сайты, email и соцсети. Без API-ключей, через headless-браузер.
            </p>
          </div>
        )}

        {/* Форма (скрыта во время активного парсинга, но видна с результатами) */}
        {(!progress || isFinalStage(progress.stage)) && (
          geoLoading ? (
            <Skeleton className="h-[420px] w-full" />
          ) : (
            <SearchForm
              geoTree={geoTree}
              loading={submitting}
              onSubmit={handleSubmit}
              disabled={!!progress && !isFinalStage(progress.stage)}
            />
          )
        )}

        {/* Прогресс */}
        {progress && (
          <ProgressView
            progress={progress}
            onCancel={handleCancel}
            onDismiss={handleDismiss}
          />
        )}

        {/* Результаты */}
        {result && result.organizations.length > 0 && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-semibold">Результаты</h2>
              <span className="text-sm text-muted-foreground">
                · «{result.search.category}»
              </span>
            </div>
            <ResultsTable
              organizations={result.organizations}
              taskId={result.task_id}
            />
          </div>
        )}

        {/* Футер */}
        <footer className="mt-12 flex items-center justify-between border-t border-border pt-6 text-xs text-muted-foreground">
          <span>
            Backend: FastAPI + Playwright · Frontend: Next.js 15
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Github className="h-3.5 w-3.5" />
            локальный проект
          </span>
        </footer>
      </div>

      {/* Toast */}
      {toast && (
        <Toast
          message={toast.msg}
          variant={toast.variant}
          onClose={() => setToast(null)}
        />
      )}
    </main>
  );
}
