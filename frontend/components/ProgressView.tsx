"use client";

import { CheckCircle2, Circle, Loader2, XCircle, X } from "lucide-react";
import {
  STAGE_LABELS,
  STAGE_ORDER,
  isFinalStage,
  isErrorStage,
  type TaskProgress,
  type TaskStage,
} from "@/lib/types";
import { cn, elapsedSeconds, formatNumber, formatTime } from "@/lib/utils";
import { Badge, Button } from "@/components/ui";

function StageIcon({
  stage,
  current,
}: {
  stage: TaskStage;
  current: TaskStage;
}) {
  const idx = STAGE_ORDER.indexOf(stage);
  const curIdx = STAGE_ORDER.indexOf(current);
  const isError = isErrorStage(current);

  if (isError && idx >= curIdx - 1) {
    return <XCircle className="h-4 w-4 text-destructive" />;
  }
  if (isFinalStage(current) && !isError && idx <= STAGE_ORDER.indexOf("done")) {
    return <CheckCircle2 className="h-4 w-4 text-success" />;
  }
  if (idx < curIdx) {
    return <CheckCircle2 className="h-4 w-4 text-success" />;
  }
  if (idx === curIdx) {
    return <Loader2 className="h-4 w-4 animate-spin text-primary" />;
  }
  return <Circle className="h-4 w-4 text-muted-foreground/40" />;
}

export function ProgressView({
  progress,
  onCancel,
  onDismiss,
}: {
  progress: TaskProgress;
  onCancel: () => void;
  onDismiss: () => void;
}) {
  const percent = progress.total > 0
    ? Math.round((progress.processed / progress.total) * 100)
    : 0;
  const elapsed = elapsedSeconds(progress.started_at, progress.updated_at);
  const isError = isErrorStage(progress.stage);
  const isFinal = isFinalStage(progress.stage);

  return (
    <div className="animate-fade-in rounded-lg border border-border bg-card p-5 shadow-sm">
      {/* Шапка */}
      <div className="mb-4 flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "status-dot",
                isFinal && !isError && "done",
                isFinal && isError && "error",
                !isFinal && "live",
              )}
            />
            <h3 className="text-base font-semibold">
              {STAGE_LABELS[progress.stage]}
            </h3>
            {isFinal && !isError && (
              <Badge variant="success">завершено</Badge>
            )}
            {isError && (
              <Badge variant="destructive">
                {progress.stage === "cancelled" ? "отменено" : "ошибка"}
              </Badge>
            )}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{progress.message}</p>
        </div>

        <div className="flex items-center gap-2">
          {!isFinal && (
            <Button variant="outline" size="sm" onClick={onCancel}>
              <X className="h-3.5 w-3.5" />
              Отменить
            </Button>
          )}
          {isFinal && (
            <Button variant="ghost" size="sm" onClick={onDismiss}>
              Скрыть
            </Button>
          )}
        </div>
      </div>

      {/* Прогресс-бар */}
      {!isFinal && (
        <div className="mb-4">
          <div className="mb-1.5 flex items-center justify-between text-xs">
            <span className="font-mono text-muted-foreground">
              {formatNumber(progress.processed)} / {formatNumber(progress.total)}
            </span>
            <span className="font-mono font-semibold text-primary">{percent}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
            <div
              className="h-full rounded-full bg-primary transition-all duration-500 ease-out"
              style={{ width: `${Math.max(2, percent)}%` }}
            />
          </div>
        </div>
      )}

      {/* Статистика в ряд */}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="С сайтом" value={progress.found_with_website} tone="success" />
        <Stat label="Без сайта" value={progress.found_without_website} tone="muted" />
        <Stat
          label="Всего найдено"
          value={progress.found_with_website + progress.found_without_website}
        />
        <Stat label="Время" value={`${elapsed}s`} mono />
      </div>

      {/* Этапы как чек-лист */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border pt-4">
        {STAGE_ORDER.filter((s) => s !== "queued").map((stage, i, arr) => (
          <div key={stage} className="flex items-center gap-2">
            <StageIcon stage={stage} current={progress.stage} />
            <span
              className={cn(
                "text-xs",
                STAGE_ORDER.indexOf(progress.stage) === STAGE_ORDER.indexOf(stage)
                  ? "font-medium text-foreground"
                  : STAGE_ORDER.indexOf(progress.stage) > STAGE_ORDER.indexOf(stage)
                    ? "text-muted-foreground"
                    : "text-muted-foreground/50",
              )}
            >
              {STAGE_LABELS[stage]}
            </span>
            {i < arr.length - 1 && (
              <span className="text-muted-foreground/30">→</span>
            )}
          </div>
        ))}
      </div>

      {/* Ошибка */}
      {progress.error && (
        <div className="mt-4 rounded-md border border-destructive/30 bg-destructive/10 p-3">
          <p className="font-mono text-xs text-destructive">{progress.error}</p>
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "default",
  mono = false,
}: {
  label: string;
  value: number | string;
  tone?: "default" | "success" | "muted";
  mono?: boolean;
}) {
  return (
    <div className="rounded-md border border-border bg-secondary/20 px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-0.5 text-lg font-semibold",
          mono && "font-mono",
          tone === "success" && "text-success",
          tone === "muted" && "text-muted-foreground",
        )}
      >
        {typeof value === "number" ? formatNumber(value) : value}
      </div>
    </div>
  );
}
