"use client";

import { useMemo, useState } from "react";
import {
  Bell,
  Bot,
  ExternalLink,
  Globe,
  MapPin,
  Phone,
  Star,
  Trash2,
} from "lucide-react";
import type { DemoStatus, WorkItem, WorkStatus } from "@/lib/types";
import {
  VERDICT_LABELS,
  WEB_LABELS,
  WORK_STATUSES,
  WORK_STATUS_LABELS,
} from "@/lib/types";
import type { UseWork } from "@/lib/useWork";
import {
  cn,
  formatNumber,
  formatPhone,
  normalizeUrl,
  shortenUrl,
  siteKey,
  yandexMapsUrl,
} from "@/lib/utils";
import { Badge, Button, Input, Toast } from "@/components/ui";

/** Сегодня в полночь — с этим сравниваем дату напоминания. */
function today(): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d;
}

/** «2026-08-04» из даты — формат, который понимает <input type="date">. */
function toInputDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toISOString().slice(0, 10);
}

/** Человеческая подпись срока: «вчера», «сегодня», «04.08». */
function remindLabel(iso: string | null): { text: string; overdue: boolean } | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  d.setHours(0, 0, 0, 0);
  const days = Math.round((d.getTime() - today().getTime()) / 86_400_000);
  if (days === 0) return { text: "сегодня", overdue: true };
  if (days === -1) return { text: "вчера", overdue: true };
  if (days === 1) return { text: "завтра", overdue: false };
  return {
    text: d.toLocaleDateString("ru", { day: "2-digit", month: "2-digit" }),
    overdue: days < 0,
  };
}

const STATUS_TONE: Record<WorkStatus, string> = {
  new: "bg-muted text-muted-foreground",
  written: "bg-primary/10 text-primary",
  replied: "bg-warning/10 text-warning",
  client: "bg-success/10 text-success",
  refused: "bg-destructive/10 text-destructive",
};

/**
 * Конторы, с которыми работаем.
 *
 * Карточка тут лежит копией: история держит последние 50 выгрузок, и вытеснение
 * ниши не должно уносить контору, которой пишешь третью неделю. Повторный
 * парсинг обновит телефоны и оценку, но статус и заметку — только руками.
 */
export function WorkPanel({
  work,
  demos,
}: {
  work: UseWork;
  demos: Record<string, DemoStatus>;
}) {
  const [filter, setFilter] = useState<WorkStatus | "all" | "overdue">("all");
  const [noteDraft, setNoteDraft] = useState<Record<string, string>>({});

  const all = useMemo(
    () =>
      Object.values(work.items).sort((a, b) => {
        // Сначала просроченные, потом с ближайшим сроком, потом остальные.
        const ra = remindLabel(a.remind_at);
        const rb = remindLabel(b.remind_at);
        if (ra?.overdue !== rb?.overdue) return ra?.overdue ? -1 : 1;
        if (a.remind_at && b.remind_at) return a.remind_at.localeCompare(b.remind_at);
        if (a.remind_at !== b.remind_at) return a.remind_at ? -1 : 1;
        return (b.created_at ?? "").localeCompare(a.created_at ?? "");
      }),
    [work.items],
  );

  const counts = useMemo(() => {
    const out: Record<string, number> = { all: all.length, overdue: 0 };
    for (const s of WORK_STATUSES) out[s] = 0;
    for (const it of all) {
      out[it.status] = (out[it.status] ?? 0) + 1;
      if (remindLabel(it.remind_at)?.overdue) out.overdue += 1;
    }
    return out;
  }, [all]);

  const rows = useMemo(() => {
    if (filter === "all") return all;
    if (filter === "overdue") return all.filter((it) => remindLabel(it.remind_at)?.overdue);
    return all.filter((it) => it.status === filter);
  }, [all, filter]);

  if (work.loading && all.length === 0) {
    return <p className="py-12 text-center text-muted-foreground">Загружаю…</p>;
  }

  if (all.length === 0) {
    return (
      <div className="animate-fade-in rounded-xl border border-dashed border-border py-16 text-center">
        <Star className="mx-auto mb-3 h-8 w-8 text-muted-foreground/40" />
        <p className="font-medium">Тут пусто</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Отметьте звёздочкой контору в выдаче — она попадёт сюда и останется,
          даже когда выгрузка вытеснится из истории.
        </p>
      </div>
    );
  }

  return (
    <div className="animate-fade-in space-y-4">
      {work.error && <Toast message={work.error} onClose={work.clearError} variant="destructive" />}

      {/* Фильтр по статусу */}
      <div className="flex flex-wrap items-center gap-2">
        {(
          [
            ["all", `Все ${counts.all}`],
            ...WORK_STATUSES.map(
              (s) => [s, `${WORK_STATUS_LABELS[s]} ${counts[s]}`] as const,
            ),
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setFilter(id as WorkStatus | "all")}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-medium transition-colors",
              filter === id
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-muted/70",
            )}
          >
            {label}
          </button>
        ))}
        {counts.overdue > 0 && (
          <button
            onClick={() => setFilter("overdue")}
            className={cn(
              "ml-auto inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors",
              filter === "overdue"
                ? "bg-destructive text-destructive-foreground"
                : "bg-destructive/10 text-destructive hover:bg-destructive/20",
            )}
          >
            <Bell className="h-3 w-3" />
            {formatNumber(counts.overdue)} пора связаться
          </button>
        )}
      </div>

      <div className="space-y-2">
        {rows.map((it) => {
          const demo = it.website ? demos[siteKey(it.website)] : undefined;
          const remind = remindLabel(it.remind_at);
          const mapsUrl = yandexMapsUrl(it);
          const phones = it.phones.length ? it.phones : it.phone ? [it.phone] : [];
          const sites = it.websites.length ? it.websites : it.website ? [it.website] : [];
          const draft = noteDraft[it.key];

          return (
            <div
              key={it.key}
              className="rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/30"
            >
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                {/* Кто и где */}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-semibold">{it.name}</span>
                    {mapsUrl && (
                      <a
                        href={mapsUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        title="Открыть в Яндекс.Картах"
                        className="text-muted-foreground hover:text-primary"
                      >
                        <MapPin className="h-3.5 w-3.5" />
                      </a>
                    )}
                    {it.reviews_count != null && (
                      <span className="text-xs text-muted-foreground">
                        {formatNumber(it.reviews_count)} отз.
                      </span>
                    )}
                  </div>
                  {it.address && (
                    <p className="mt-0.5 truncate text-sm text-muted-foreground">{it.address}</p>
                  )}

                  {/* Контакты: все телефоны и все сайты */}
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                    {phones.map((p) => (
                      <a
                        key={p}
                        href={`tel:${p.replace(/\(.*?\)\s*$/, "").replace(/\D/g, "")}`}
                        className="inline-flex items-center gap-1.5 hover:text-primary"
                      >
                        <Phone className="h-3 w-3 text-muted-foreground" />
                        <span className="font-mono text-[11px]">
                          {formatPhone(p.replace(/\s*\(([^)]*[а-яА-Я][^)]*)\)\s*$/, ""))}
                        </span>
                      </a>
                    ))}
                    {sites.map((s) => (
                      <a
                        key={s}
                        href={normalizeUrl(s) ?? "#"}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="group inline-flex items-center gap-1.5 text-primary hover:underline"
                      >
                        <Globe className="h-3 w-3" />
                        {shortenUrl(s)}
                        <ExternalLink className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-100" />
                      </a>
                    ))}
                    {sites.length === 0 && (
                      <span className="text-xs text-muted-foreground">сайта нет</span>
                    )}
                  </div>

                  {/* Зачем взяли: обе оси отбора */}
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
                    {it.verdict && (
                      <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">
                        Ассистент: {VERDICT_LABELS[it.verdict]}
                      </span>
                    )}
                    {it.web && (
                      <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">
                        Сайт: {WEB_LABELS[it.web]}
                      </span>
                    )}
                    {demo && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-primary">
                        <Bot className="h-3 w-3" />
                        демо: {demo.opened_count > 0 ? "открыл" : "не открывал"}
                        {demo.message_count > 0 && `, ${demo.message_count} вопр.`}
                      </span>
                    )}
                  </div>
                </div>

                {/* Что с ней делаем */}
                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  <select
                    value={it.status}
                    onChange={(e) => work.patch(it.key, { status: e.target.value as WorkStatus })}
                    className={cn(
                      "h-8 cursor-pointer rounded-lg border-0 px-2 text-xs font-medium outline-none",
                      STATUS_TONE[it.status],
                    )}
                  >
                    {WORK_STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {WORK_STATUS_LABELS[s]}
                      </option>
                    ))}
                  </select>

                  <div className="flex items-center gap-1">
                    <Bell
                      className={cn(
                        "h-3.5 w-3.5",
                        remind?.overdue ? "text-destructive" : "text-muted-foreground",
                      )}
                    />
                    <input
                      type="date"
                      value={toInputDate(it.remind_at)}
                      onChange={(e) =>
                        work.patch(
                          it.key,
                          e.target.value
                            ? { remind_at: new Date(e.target.value).toISOString() }
                            : { clear_remind: true },
                        )
                      }
                      className={cn(
                        "h-8 rounded-lg border border-border bg-background px-2 text-xs outline-none focus:border-primary",
                        remind?.overdue && "border-destructive/50 text-destructive",
                      )}
                    />
                    {remind && (
                      <span
                        className={cn(
                          "text-[11px]",
                          remind.overdue ? "font-medium text-destructive" : "text-muted-foreground",
                        )}
                      >
                        {remind.text}
                      </span>
                    )}
                  </div>

                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => work.remove(it.key)}
                    title="Убрать из работы"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>

              {/* Заметка — сохраняется при уходе фокуса, чтобы не дёргать API на каждую букву */}
              <Input
                value={draft ?? it.note ?? ""}
                placeholder="Заметка: о чём договорились, что обещали…"
                onChange={(e) => setNoteDraft((p) => ({ ...p, [it.key]: e.target.value }))}
                onBlur={() => {
                  if (draft === undefined || draft === (it.note ?? "")) return;
                  work.patch(it.key, { note: draft });
                  setNoteDraft((p) => {
                    const next = { ...p };
                    delete next[it.key];
                    return next;
                  });
                }}
                className="mt-3 h-8 text-xs"
              />
            </div>
          );
        })}

        {rows.length === 0 && (
          <p className="py-10 text-center text-sm text-muted-foreground">
            В этом статусе никого нет.
          </p>
        )}
      </div>
    </div>
  );
}
