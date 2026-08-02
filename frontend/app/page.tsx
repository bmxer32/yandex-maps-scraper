"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Map, Bot, Clock, Database, Github, Star, Zap } from "lucide-react";
import type { GeoNode, SearchRequest, TaskProgress, TaskResult } from "@/lib/types";
import {
  cancelTask,
  createSearch,
  getGeoTree,
  getTask,
  subscribeProgress,
} from "@/lib/api";
import { isFinalStage } from "@/lib/types";
import { useDemos } from "@/lib/useDemos";
import { useWork } from "@/lib/useWork";
import { cn } from "@/lib/utils";
import { SearchForm } from "@/components/SearchForm";
import { ProgressView } from "@/components/ProgressView";
import { ResultsTable } from "@/components/ResultsTable";
import { DemosPanel } from "@/components/DemosPanel";
import { HistoryPanel } from "@/components/HistoryPanel";
import { WorkPanel } from "@/components/WorkPanel";
import { Skeleton, Toast } from "@/components/ui";

type Tab = "search" | "history" | "work" | "demos";

export default function Home() {
  const [tab, setTab] = useState<Tab>("search");
  // Одно состояние демо на всё приложение: таблица результатов и раздел
  // «Демо» должны видеть одни и те же данные, иначе удаление в одном месте
  // не отражается в другом.
  const demos = useDemos();
  // Так же и работа: звёздочка в таблице и раздел «В работе» — одни данные.
  const work = useWork();
  const [geoTree, setGeoTree] = useState<GeoNode[]>([]);
  const [geoLoading, setGeoLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const [progress, setProgress] = useState<TaskProgress | null>(null);
  const [result, setResult] = useState<TaskResult | null>(null);
  const [toast, setToast] = useState<{ msg: string; variant?: "default" | "destructive" } | null>(null);

  const unsubscribeRef = useRef<(() => void) | null>(null);
  const demoCount = Object.keys(demos.demos).length;
  const workCount = Object.keys(work.items).length;

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
        <div className="mx-auto flex max-w-[1700px] items-center justify-between px-4 py-3 sm:px-6">
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
              v0.3.1
            </span>
          </div>
        </div>
      </header>

      {/* Разделы слева, содержимое справа. Сайдбар одинаков на всех вкладках:
          навигация не должна прыгать от того, что открыто. */}
      <div className="mx-auto flex max-w-[1700px] gap-6 px-4 py-6 sm:px-6 sm:py-8">
        <nav className="sticky top-[73px] hidden h-fit w-52 shrink-0 flex-col gap-1 lg:flex">
          {(
            [
              { id: "search" as Tab, label: "Поиск", icon: Map, count: 0 },
              { id: "history" as Tab, label: "История", icon: Clock, count: 0 },
              { id: "work" as Tab, label: "В работе", icon: Star, count: workCount },
              { id: "demos" as Tab, label: "Демо", icon: Bot, count: demoCount },
            ]
          ).map(({ id, label, icon: Icon, count }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={cn(
                "inline-flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                tab === id
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
              {count > 0 && (
                <span
                  className={cn(
                    "ml-auto rounded-full px-1.5 text-[10px]",
                    tab === id ? "bg-background/30" : "bg-secondary",
                  )}
                >
                  {count}
                </span>
              )}
            </button>
          ))}
        </nav>

        {/* На узком экране сайдбара нет — вкладки лентой сверху */}
        <div className="min-w-0 flex-1 space-y-6">
          <div className="flex gap-1 overflow-x-auto rounded-lg border border-border p-1 lg:hidden">
            {(
              [
                { id: "search" as Tab, label: "Поиск", icon: Map },
                { id: "history" as Tab, label: "История", icon: Clock },
                { id: "work" as Tab, label: "В работе", icon: Star },
                { id: "demos" as Tab, label: "Демо", icon: Bot },
              ]
            ).map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={cn(
                  "inline-flex shrink-0 items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors",
                  tab === id
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </div>

        {tab === "history" && (
          <div className="space-y-4">
            <div className="flex flex-col items-start gap-2">
              <h2 className="text-2xl font-bold tracking-tight">История выгрузок</h2>
              <p className="max-w-2xl text-sm text-muted-foreground">
                Собранное сохраняется автоматически. Откройте любую выгрузку —
                она загрузится целиком, без повторного парсинга Яндекс.Карт.
              </p>
            </div>
            <HistoryPanel
              onOpen={(res) => {
                setResult(res);
                setProgress(null);
                setTab("search");
              }}
            />
          </div>
        )}

        {tab === "work" && (
          <div className="space-y-4">
            <div className="flex flex-col items-start gap-2">
              <h2 className="text-2xl font-bold tracking-tight">В работе</h2>
              <p className="max-w-2xl text-sm text-muted-foreground">
                Конторы, за которые взялись. Данные лежат копией и не пропадут,
                когда выгрузка вытеснится из истории; новый парсинг обновит
                телефоны и оценку, а статус с заметкой останутся вашими.
              </p>
            </div>
            <WorkPanel work={work} demos={demos.demos} />
          </div>
        )}

        {tab === "demos" && (
          <div className="space-y-4">
            <div className="flex flex-col items-start gap-2">
              <h2 className="text-2xl font-bold tracking-tight">Разосланные демо</h2>
              <p className="max-w-2xl text-sm text-muted-foreground">
                Кто открыл ссылку и сколько вопросов задал. «Мало данных» — сайт
                отдал в основном служебные страницы, такое демо клиенту слать рано.
              </p>
            </div>
            <DemosPanel demos={demos} />
          </div>
        )}

        {/* Hero — только когда ничего ещё не запущено */}
        {tab === "search" && !progress && !result && (
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
        {tab === "search" && (!progress || isFinalStage(progress.stage)) && (
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
        {tab === "search" && progress && (
          <ProgressView
            progress={progress}
            onCancel={handleCancel}
            onDismiss={handleDismiss}
          />
        )}

        {/* Результаты */}
        {tab === "search" && result && result.organizations.length > 0 && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-semibold">Результаты</h2>
              <span className="text-sm text-muted-foreground">
                · «{result.search.category}»
              </span>
            </div>
            <ResultsTable
              work={work}
              organizations={result.organizations}
              taskId={result.task_id}
              demos={demos}
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
