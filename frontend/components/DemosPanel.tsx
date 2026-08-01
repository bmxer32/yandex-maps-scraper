"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Check,
  Copy,
  ExternalLink,
  Globe,
  Loader2,
  MessageCircle,
  RefreshCw,
  Search as SearchIcon,
  Trash2,
} from "lucide-react";
import type { DemoStatus } from "@/lib/types";
import { DEMO_STATE_LABELS, isDemoPending } from "@/lib/types";
import type { UseDemos } from "@/lib/useDemos";
import { cn, formatNumber } from "@/lib/utils";
import { Badge, Button, Input } from "@/components/ui";

type Filter = "all" | "opened" | "problem";

/** Раздел «Демо»: что разослано, кто открыл, что удалить. */
export function DemosPanel({ demos }: { demos: UseDemos }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [refreshing, setRefreshing] = useState(false);

  const all = useMemo(() => Object.values(demos.demos), [demos.demos]);

  const stats = useMemo(
    () => ({
      total: all.length,
      opened: all.filter((d) => d.opened_count > 0).length,
      engaged: all.filter((d) => d.message_count >= 3).length,
      problem: all.filter((d) => d.status === "thin" || d.status === "failed").length,
    }),
    [all],
  );

  const rows = useMemo(() => {
    let list = all;
    if (filter === "opened") list = list.filter((d) => d.opened_count > 0);
    if (filter === "problem")
      list = list.filter((d) => d.status === "thin" || d.status === "failed");

    if (query.trim()) {
      const q = query.toLowerCase().trim();
      list = list.filter((d) =>
        [d.name ?? "", d.website ?? "", d.slug].join(" ").toLowerCase().includes(q),
      );
    }
    // Сначала те, кто открывал: с ними и нужно работать.
    return [...list].sort(
      (a, b) => b.opened_count - a.opened_count || b.message_count - a.message_count,
    );
  }, [all, filter, query]);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await demos.refresh();
    } finally {
      setRefreshing(false);
    }
  }

  if (!demos.config?.enabled) {
    return (
      <div className="rounded-lg border border-border p-8 text-center text-sm text-muted-foreground">
        Интеграция с ИИ-ассистентом не настроена — задайте KB_BASE_URL и KB_API_KEY
        в <code className="rounded bg-secondary px-1">backend/.env</code>.
      </div>
    );
  }

  return (
    <div className="animate-fade-in space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="px-3 py-1 text-sm">
            <Bot className="mr-1 h-3 w-3" />
            {formatNumber(stats.total)} демо
          </Badge>
          <Badge variant="success" className="px-3 py-1 text-sm">
            {formatNumber(stats.opened)} открыли
          </Badge>
          <Badge variant="default" className="px-3 py-1 text-sm">
            {formatNumber(stats.engaged)} задали 3+ вопроса
          </Badge>
          {stats.problem > 0 && (
            <Badge variant="warning" className="px-3 py-1 text-sm">
              <AlertTriangle className="mr-1 h-3 w-3" />
              {formatNumber(stats.problem)} с проблемой
            </Badge>
          )}
        </div>

        <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing}>
          <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
          Обновить
        </Button>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по компании, сайту, метке…"
            className="pl-9"
          />
        </div>
        <div className="flex rounded-md border border-border p-0.5">
          {(["all", "opened", "problem"] as Filter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                "rounded px-3 py-1.5 text-xs font-medium transition-colors",
                filter === f
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {f === "all" && "Все"}
              {f === "opened" && "Открыли"}
              {f === "problem" && "С проблемой"}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-border">
        <div className="max-h-[70vh] overflow-auto">
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 z-10 bg-card/95 backdrop-blur">
              <tr className="border-b border-border">
                <th className="px-3 py-3 text-left">Компания</th>
                <th className="hidden px-3 py-3 text-left md:table-cell">Сайт</th>
                <th className="px-3 py-3 text-left">Статус</th>
                <th className="px-3 py-3 text-left">Ссылка</th>
                <th className="px-3 py-3 text-right">Открытий</th>
                <th className="px-3 py-3 text-right">Вопросов</th>
                <th className="w-10 px-3 py-3" />
              </tr>
            </thead>
            <tbody>
              {rows.map((demo) => (
                <DemoRow key={demo.slug} demo={demo} onDelete={demos.remove} />
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-12 text-center text-muted-foreground">
                    {all.length === 0
                      ? "Демо ещё не заводили — соберите организации и нажмите «Сделать демо»"
                      : "Ничего не найдено по фильтрам"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        Показано {formatNumber(rows.length)} из {formatNumber(all.length)}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function DemoRow({
  demo,
  onDelete,
}: {
  demo: DemoStatus;
  onDelete: (slug: string) => Promise<void>;
}) {
  const [copied, setCopied] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function copyLink() {
    if (!demo.link) return;
    try {
      await navigator.clipboard.writeText(demo.link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* буфер недоступен — ссылка рядом кликабельна */
    }
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await onDelete(demo.slug);
    } finally {
      setDeleting(false);
      setConfirming(false);
    }
  }

  return (
    <tr className="border-b border-border/50 transition-colors hover:bg-secondary/30">
      <td className="px-3 py-3 align-top">
        <div className="font-medium leading-tight">{demo.name ?? demo.slug}</div>
        <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">{demo.slug}</div>
      </td>

      <td className="hidden max-w-xs px-3 py-3 align-top md:table-cell">
        {demo.website ? (
          <a
            href={demo.website}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-primary hover:underline"
          >
            <Globe className="h-3 w-3" />
            <span className="max-w-[220px] truncate">{demo.website}</span>
          </a>
        ) : (
          <span className="text-muted-foreground/40">—</span>
        )}
      </td>

      <td className="px-3 py-3 align-top">
        <DemoStatusBadge demo={demo} />
      </td>

      <td className="px-3 py-3 align-top">
        {demo.link ? (
          <div className="flex items-center gap-1.5">
            <a
              href={demo.link}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              <ExternalLink className="h-3 w-3" />
              открыть
            </a>
            <button
              onClick={copyLink}
              title="Скопировать ссылку"
              className="text-muted-foreground transition-colors hover:text-foreground"
            >
              {copied ? (
                <Check className="h-3 w-3 text-success" />
              ) : (
                <Copy className="h-3 w-3" />
              )}
            </button>
          </div>
        ) : (
          <span className="text-[10px] text-muted-foreground">нет username бота</span>
        )}
      </td>

      <td className="px-3 py-3 text-right align-top font-mono text-xs">
        {demo.opened_count > 0 ? (
          <span className="text-success">{demo.opened_count}</span>
        ) : (
          <span className="text-muted-foreground/40">0</span>
        )}
      </td>

      <td className="px-3 py-3 text-right align-top font-mono text-xs">
        {demo.message_count > 0 ? (
          <span className="inline-flex items-center gap-1">
            <MessageCircle className="h-3 w-3 text-muted-foreground" />
            {demo.message_count}
          </span>
        ) : (
          <span className="text-muted-foreground/40">0</span>
        )}
      </td>

      <td className="px-3 py-3 align-top">
        {confirming ? (
          <div className="flex items-center gap-1">
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="rounded bg-destructive px-2 py-0.5 text-[10px] font-medium text-destructive-foreground disabled:opacity-50"
            >
              {deleting ? "…" : "Удалить"}
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="text-[10px] text-muted-foreground hover:text-foreground"
            >
              отмена
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirming(true)}
            title="Удалить демо вместе с базой знаний"
            className="text-muted-foreground transition-colors hover:text-destructive"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </td>
    </tr>
  );
}

function DemoStatusBadge({ demo }: { demo: DemoStatus }) {
  if (isDemoPending(demo.status)) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
        {DEMO_STATE_LABELS[demo.status]}
      </span>
    );
  }

  if (demo.status === "ready") {
    return (
      <span className="inline-flex items-center rounded-full bg-success/10 px-2 py-0.5 text-[10px] font-medium text-success">
        {DEMO_STATE_LABELS.ready}
        {demo.pages_indexed > 0 && ` · ${demo.pages_indexed} стр.`}
      </span>
    );
  }

  const warn = demo.status === "thin";
  return (
    <span
      title={demo.error ?? undefined}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium",
        warn ? "bg-warning/10 text-warning" : "bg-destructive/10 text-destructive",
      )}
    >
      <AlertTriangle className="h-2.5 w-2.5" />
      {DEMO_STATE_LABELS[demo.status]}
    </span>
  );
}
