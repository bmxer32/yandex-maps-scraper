"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowUpDown,
  Bot,
  Check,
  Copy,
  Download,
  Filter,
  ExternalLink,
  Globe,
  ListChecks,
  Loader2,
  Mail,
  MapPin,
  MessageCircle,
  Phone,
  Search as SearchIcon,
  Sparkles,
  Star,
  Trash2,
} from "lucide-react";
import type { DemoStatus, Organization, ProspectVerdict } from "@/lib/types";
import { DEMO_STATE_LABELS, VERDICT_LABELS, WEB_LABELS, isDemoPending } from "@/lib/types";
import { exportUrl } from "@/lib/api";
import type { UseDemos } from "@/lib/useDemos";
import type { UseWork } from "@/lib/useWork";
import { useProspects } from "@/lib/useProspects";
import {
  cn,
  formatNumber,
  formatPhone,
  normalizeUrl,
  parseSocial,
  isUsefulSocial,
  rowKey,
  shortenUrl,
  telegramUsernames,
  downloadText,
  workKey,
  siteKey,
  yandexMapsUrl,
} from "@/lib/utils";
import { Badge, Button, Input, Toast, buttonClass } from "@/components/ui";

type SiteFilter = "all" | "with" | "without";
type SortKey = "name" | "rating" | "reviews";
type SortDir = "asc" | "desc";
/** Фильтр по вердикту. "manual" — отдельная ось: демо собирается не автоматом. */
type VerdictFilter = "all" | "good" | "maybe" | "skip" | "manual";

export function ResultsTable({
  organizations,
  taskId,
  demos,
  work,
}: {
  organizations: Organization[];
  taskId: string;
  /** Состояние демо поднято на страницу — оно общее с разделом «Демо». */
  demos: UseDemos;
  /** То же и для работы: звёздочка тут и список «В работе» — одни данные. */
  work: UseWork;
}) {
  const [query, setQuery] = useState("");
  const [siteFilter, setSiteFilter] = useState<SiteFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  // Выбранные строки — по ключу сайта: демо привязано к сайту, а не к позиции.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [verdictFilter, setVerdictFilter] = useState<VerdictFilter>("all");
  // По какой оси фильтруем и кого отмечает «Выбрать годных».
  const [axis, setAxis] = useState<"ai" | "web">("ai");

  const prospects = useProspects(organizations);
  const demoEnabled = demos.config?.enabled ?? false;
  // Стек ассистента в Docker поднимается около минуты после старта программы.
  const demoReady = demos.config?.ready ?? false;

  const filtered = useMemo(() => {
    let rows = organizations;

    // Текстовый поиск
    if (query.trim()) {
      const q = query.toLowerCase().trim();
      rows = rows.filter((o) =>
        [o.name, o.address ?? "", o.website ?? "", o.email ?? ""]
          .join(" ")
          .toLowerCase()
          .includes(q),
      );
    }

    // Фильтр по наличию сайта
    if (siteFilter === "with") rows = rows.filter((o) => !!o.website);
    if (siteFilter === "without") rows = rows.filter((o) => !o.website);

    // Фильтр по вердикту. Скрывает только по явному выбору — по умолчанию
    // виден весь список, чтобы ничего не потерялось незаметно.
    if (verdictFilter !== "all") {
      rows = rows.filter((o) => {
        const v = prospects.verdicts[rowKey(o)];
        if (!v) return false;
        if (verdictFilter === "manual") return v.demo === "manual";
        return (axis === "ai" ? v.verdict : v.web) === verdictFilter;
      });
    }

    // Сортировка
    const dir = sortDir === "asc" ? 1 : -1;
    rows = [...rows].sort((a, b) => {
      if (sortKey === "name") return a.name.localeCompare(b.name, "ru") * dir;
      const av = a.rating ?? -1;
      const bv = b.rating ?? -1;
      if (sortKey === "rating") return (av - bv) * dir;
      const ar = a.reviews_count ?? -1;
      const br = b.reviews_count ?? -1;
      return (ar - br) * dir;
    });

    return rows;
  }, [organizations, query, siteFilter, sortKey, sortDir, verdictFilter, axis, prospects.verdicts]);

  const withSite = organizations.filter((o) => o.website).length;
  const withoutSite = organizations.length - withSite;

  // Демо можно сделать только тем, у кого есть сайт: базу знаний собираем
  // краулом, краулить нечего — предлагать нечего.
  const selectableKeys = useMemo(
    () => filtered.filter((o) => o.website).map((o) => siteKey(o.website)),
    [filtered],
  );
  const selectedOrgs = useMemo(
    () => filtered.filter((o) => o.website && selected.has(siteKey(o.website))),
    [filtered, selected],
  );
  const allSelected =
    selectableKeys.length > 0 && selectableKeys.every((k) => selected.has(k));

  const demoStats = useMemo(() => {
    const all = Object.values(demos.demos);
    return {
      total: all.length,
      opened: all.filter((d) => d.opened_count > 0).length,
    };
  }, [demos.demos]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  function toggleRow(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleAll() {
    setSelected((prev) => {
      if (selectableKeys.every((k) => prev.has(k))) {
        const next = new Set(prev);
        selectableKeys.forEach((k) => next.delete(k));
        return next;
      }
      return new Set([...prev, ...selectableKeys]);
    });
  }

  /** Звёздочка: в работу и обратно. Оценка едет вместе — видно, зачем взяли. */
  function toggleWork(org: Organization) {
    const key = workKey(org);
    if (work.items[key]) {
      work.remove(key);
      return;
    }
    const v = prospects.verdicts[rowKey(org)];
    work.add([{ ...org, verdict: v?.verdict, web: v?.web }]);
  }

  /**
   * Телеграм-контакты видимых строк без своего сайта — по одному в строке.
   * Тип ссылки берём из вердикта: без него компания с ВК в поле «сайт»
   * считалась бы сайтовладельцем и в список бы не попала.
   */
  const tgUsernames = useMemo(
    () =>
      telegramUsernames(
        filtered.map((o) => ({ ...o, linkKind: prospects.verdicts[rowKey(o)]?.link_kind })),
      ),
    [filtered, prospects.verdicts],
  );

  function saveTelegram() {
    const stamp = new Date().toISOString().slice(0, 10);
    downloadText(`telegram-bez-sayta-${stamp}.txt`, tgUsernames.join("\n") + "\n");
  }

  async function makeDemos() {
    await demos.create(selectedOrgs);
    setSelected(new Set());
  }

  /** Отметить всех, кого оценка признала годными. Остальные остаются доступны. */
  function selectGood() {
    const keys = filtered
      .filter((o) => {
        const v = prospects.verdicts[rowKey(o)];
        return v?.verdict === "good" && v.demo === "auto";
      })
      .map((o) => siteKey(o.website))
      .filter(Boolean);
    setSelected(new Set(keys));
  }

  const scanStats = useMemo(() => {
    const rows = filtered.map((o) => prospects.verdicts[rowKey(o)]).filter(Boolean);
    return {
      rated: rows.length,
      good: rows.filter((v) => (axis === "ai" ? v.verdict : v.web) === "good").length,
      webGood: rows.filter((v) => v.web === "good").length,
      skip: rows.filter((v) => v.verdict === "skip").length,
      manual: rows.filter((v) => v.demo === "manual").length,
    };
  }, [filtered, prospects.verdicts, axis]);

  return (
    <div className="animate-fade-in space-y-4">
      {/* Toolbar */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="px-3 py-1 text-sm">
            {formatNumber(organizations.length)} организаций
          </Badge>
          <Badge variant="success" className="px-3 py-1 text-sm">
            <Globe className="mr-1 h-3 w-3" />
            {formatNumber(withSite)} с сайтом
          </Badge>
          <Badge variant="default" className="px-3 py-1 text-sm">
            {formatNumber(withoutSite)} без сайта
          </Badge>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Оценка перспективности */}
          <Button
            variant="outline"
            size="sm"
            onClick={() => prospects.scan(filtered)}
            disabled={prospects.scanning || filtered.length === 0}
            title="Классифицировать ссылки, проверить сайты и спросить модель"
          >
            {prospects.scanning ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Filter className="h-3.5 w-3.5" />
            )}
            Оценить
            {prospects.scanning && ` (${filtered.length})`}
          </Button>

          {scanStats.rated > 0 && (
            <>
              {/* Отметка строк ведёт только к сборке демо, а демо — про
                  ассистента. На оси «сайт» кнопка обещала бы не то. */}
              {axis === "ai" && (
                <Button variant="secondary" size="sm" onClick={selectGood}>
                  <ListChecks className="h-3.5 w-3.5" />
                  Выбрать годных ({scanStats.good})
                </Button>
              )}
              {axis === "web" && (
                <Badge variant="success" className="px-3 py-1 text-sm">
                  {formatNumber(scanStats.good)} под сайт
                </Badge>
              )}
              {axis === "ai" && scanStats.manual > 0 && (
                <Badge variant="outline" className="px-3 py-1 text-sm">
                  {formatNumber(scanStats.manual)} демо вручную
                </Badge>
              )}
            </>
          )}

          {/* Персональные демо ИИ-ассистента */}
          {demoEnabled && (
            <>
              {!demoReady && (
                <Badge variant="warning" className="px-3 py-1 text-sm">
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  ИИ-ассистент запускается…
                </Badge>
              )}
              {demoReady && demoStats.total > 0 && (
                <Badge variant="outline" className="px-3 py-1 text-sm">
                  <Bot className="mr-1 h-3 w-3" />
                  {formatNumber(demoStats.total)} демо
                  {demoStats.opened > 0 && ` · ${formatNumber(demoStats.opened)} открыли`}
                </Badge>
              )}
              <Button
                size="sm"
                onClick={makeDemos}
                title={demoReady ? undefined : "ИИ-ассистент ещё поднимается"}
                disabled={
                  !demoReady || selectedOrgs.length === 0 || demos.provisioning.size > 0
                }
              >
                {demos.provisioning.size > 0 ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5" />
                )}
                Сделать демо
                {selectedOrgs.length > 0 && ` (${selectedOrgs.length})`}
              </Button>
            </>
          )}

          {/* Экспорт */}
          <a
            href={exportUrl(taskId, "xlsx")}
            className={buttonClass("outline", "sm")}
          >
            <Download className="h-3.5 w-3.5" />
            Excel
          </a>
          <a
            href={exportUrl(taskId, "csv")}
            className={buttonClass("outline", "sm")}
          >
            <Download className="h-3.5 w-3.5" />
            CSV
          </a>
          <a
            href={exportUrl(taskId, "xlsx", true)}
            className={buttonClass("secondary", "sm")}
          >
            <Download className="h-3.5 w-3.5" />
            Excel (только сайты)
          </a>
          {/* Кому писать в телеграм: у кого сайта нет вовсе. Считается по
              видимым строкам — фильтры и оценка учитываются. */}
          {tgUsernames.length > 0 && (
            <Button variant="outline" size="sm" onClick={saveTelegram}>
              <MessageCircle className="h-3.5 w-3.5" />
              ТГ без сайта ({tgUsernames.length})
            </Button>
          )}
        </div>
      </div>

      {/* Поле поиска + фильтр */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по названию, адресу, сайту, email…"
            className="pl-9"
          />
        </div>

        {scanStats.rated > 0 && (
          <div className="flex rounded-md border border-border p-0.5">
            {([
              { id: "ai" as const, label: "ИИ-ассистент" },
              { id: "web" as const, label: "Сайт" },
            ]).map((a) => (
              <button
                key={a.id}
                onClick={() => setAxis(a.id)}
                className={cn(
                  "rounded px-3 py-1.5 text-xs font-medium transition-colors",
                  axis === a.id
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {a.label}
              </button>
            ))}
          </div>
        )}

        {scanStats.rated > 0 && (
          <div className="flex rounded-md border border-border p-0.5">
            {(["all", "good", "maybe", "skip", "manual"] as VerdictFilter[]).map((f) => (
              <button
                key={f}
                onClick={() => setVerdictFilter(f)}
                className={cn(
                  "rounded px-3 py-1.5 text-xs font-medium transition-colors",
                  verdictFilter === f
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {f === "all" && "Все"}
                {f === "good" && (axis === "ai" ? "Годные" : "Нужен сайт")}
                {f === "maybe" && "Сомнительные"}
                {f === "skip" && (axis === "ai" ? "Мимо" : "Не нужен")}
                {f === "manual" && "Демо вручную"}
              </button>
            ))}
          </div>
        )}

        <div className="flex rounded-md border border-border p-0.5">
          {(["all", "with", "without"] as SiteFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setSiteFilter(f)}
              className={cn(
                "rounded px-3 py-1.5 text-xs font-medium transition-colors",
                siteFilter === f
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {f === "all" && "Все"}
              {f === "with" && "С сайтом"}
              {f === "without" && "Без сайта"}
            </button>
          ))}
        </div>
      </div>

      {/* Таблица */}
      <div className="overflow-hidden rounded-lg border border-border">
        <div className="max-h-[70vh] overflow-auto">
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 z-10 bg-card/95 backdrop-blur">
              <tr className="border-b border-border">
                {demoEnabled && (
                  <th className="w-9 px-3 py-3">
                    <input
                      type="checkbox"
                      aria-label="Выбрать все строки с сайтом"
                      checked={allSelected}
                      onChange={toggleAll}
                      disabled={selectableKeys.length === 0}
                      className="h-3.5 w-3.5 cursor-pointer accent-[hsl(var(--primary))] disabled:cursor-not-allowed disabled:opacity-40"
                    />
                  </th>
                )}
                <th className="px-3 py-3 text-left">
                  <SortButton
                    label="Название"
                    active={sortKey === "name"}
                    dir={sortDir}
                    onClick={() => toggleSort("name")}
                  />
                </th>
                <th className="hidden px-3 py-3 text-left md:table-cell">
                  Адрес
                </th>
                <th className="px-3 py-3 text-left">Телефон</th>
                <th className="px-3 py-3 text-left">Сайт</th>
                {scanStats.rated > 0 && (
                  <>
                    <th className="px-3 py-3 text-left">Ассистент</th>
                    <th className="px-3 py-3 text-left">Сайт</th>
                  </>
                )}
                <th className="hidden px-3 py-3 text-left lg:table-cell">
                  Контакты
                </th>
                <th className="hidden px-3 py-3 text-right lg:table-cell">
                  <SortButton
                    label="Рейтинг"
                    active={sortKey === "rating"}
                    dir={sortDir}
                    onClick={() => toggleSort("rating")}
                    align="right"
                  />
                </th>
                {demoEnabled && <th className="px-3 py-3 text-left">Демо</th>}
              </tr>
            </thead>
            <tbody>
              {filtered.map((org, i) => {
                const key = siteKey(org.website);
                return (
                  <OrgRow
                    key={org.permalink ?? `${org.name}-${i}`}
                    org={org}
                    demoEnabled={demoEnabled}
                    demo={key ? demos.demos[key] : undefined}
                    selected={selected.has(key)}
                    provisioning={demos.provisioning.has(key)}
                    onToggle={() => key && toggleRow(key)}
                    onDeleteDemo={demos.remove}
                    verdict={prospects.verdicts[rowKey(org)]}
                    showVerdict={scanStats.rated > 0}
                    inWork={!!work.items[workKey(org)]}
                    onToggleWork={() => toggleWork(org)}
                  />
                );
              })}
              {filtered.length === 0 && (
                <tr>
                  <td
                    colSpan={(demoEnabled ? 8 : 6) + (scanStats.rated > 0 ? 2 : 0)}
                    className="px-3 py-12 text-center text-muted-foreground"
                  >
                    Ничего не найдено по фильтрам
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        Показано {formatNumber(filtered.length)} из {formatNumber(organizations.length)}
      </p>

      {demos.error && (
        <Toast message={demos.error} variant="destructive" onClose={demos.clearError} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */

/**
 * Вердикт по компании: цвет, подпись и причины в подсказке.
 *
 * Ничего не скрывает и ничего не запрещает — это подсказка человеку.
 * «Демо вручную» показываем отдельной строкой: это про нашу автоматику,
 * а не про качество клиента, и путать эти вещи нельзя.
 */
function VerdictCell({
  verdict,
  axis,
}: {
  verdict?: ProspectVerdict;
  axis: "ai" | "web";
}) {
  if (!verdict) {
    return <span className="text-muted-foreground/40">—</span>;
  }

  const state = axis === "ai" ? verdict.verdict : verdict.web;
  const reasons = axis === "ai" ? verdict.reasons : verdict.web_reasons;
  // На оси сайта «годится» значит «есть что переделать» — подписи свои.
  const label = axis === "ai" ? VERDICT_LABELS[state] : WEB_LABELS[state];

  const tone =
    state === "good"
      ? "bg-success/10 text-success"
      : state === "skip"
        ? "bg-destructive/10 text-destructive"
        : "bg-warning/10 text-warning";

  return (
    <div className="flex flex-col gap-1">
      <span
        title={reasons.join("\n") || undefined}
        className={cn(
          "inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium",
          tone,
        )}
      >
        {state === "good" ? (
          <Check className="h-2.5 w-2.5" />
        ) : (
          <AlertTriangle className="h-2.5 w-2.5" />
        )}
        {label}
      </span>

      {/* «Демо вручную» — про автоматику ассистента, к сайту отношения нет. */}
      {axis === "ai" && verdict.demo === "manual" && (
        <span className="text-[10px] text-muted-foreground">демо вручную</span>
      )}

      {reasons.length > 0 && (
        <span
          className="max-w-[200px] truncate text-[10px] text-muted-foreground/70"
          title={reasons.join("\n")}
        >
          {reasons[reasons.length - 1]}
        </span>
      )}
    </div>
  );
}

/** Удаление демо в два клика — сносится и собранная база знаний. */
function DeleteDemoButton({
  slug,
  confirming,
  setConfirming,
  onDelete,
}: {
  slug: string;
  confirming: boolean;
  setConfirming: (v: boolean) => void;
  onDelete: (slug: string) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);

  if (confirming) {
    return (
      <span className="inline-flex items-center gap-1">
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onDelete(slug);
            } finally {
              setBusy(false);
              setConfirming(false);
            }
          }}
          className="rounded bg-destructive px-1.5 py-0.5 text-[10px] font-medium text-destructive-foreground disabled:opacity-50"
        >
          {busy ? "…" : "Удалить"}
        </button>
        <button
          onClick={() => setConfirming(false)}
          className="text-[10px] text-muted-foreground hover:text-foreground"
        >
          нет
        </button>
      </span>
    );
  }

  return (
    <button
      onClick={() => setConfirming(true)}
      title="Удалить демо вместе с базой знаний"
      className="text-muted-foreground transition-colors hover:text-destructive"
    >
      <Trash2 className="h-3 w-3" />
    </button>
  );
}

function SortButton({
  label,
  active,
  dir,
  onClick,
  align = "left",
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
  align?: "left" | "right";
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 font-medium transition-colors",
        align === "right" && "flex-row-reverse",
        active ? "text-primary" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
      <ArrowUpDown className={cn("h-3 w-3", active && dir === "desc" && "rotate-180")} />
    </button>
  );
}

function OrgRow({
  org,
  demoEnabled,
  demo,
  selected,
  provisioning,
  onToggle,
  onDeleteDemo,
  verdict,
  showVerdict,
  inWork,
  onToggleWork,
}: {
  org: Organization;
  demoEnabled: boolean;
  demo?: DemoStatus;
  selected: boolean;
  provisioning: boolean;
  onToggle: () => void;
  onDeleteDemo: (slug: string) => Promise<void>;
  verdict?: ProspectVerdict;
  showVerdict: boolean;
  inWork: boolean;
  onToggleWork: () => void;
}) {
  // Старые выгрузки знают только один сайт и один телефон — падаем на них.
  const sites = org.websites?.length ? org.websites : org.website ? [org.website] : [];
  const phones = org.phones?.length ? org.phones : org.phone ? [org.phone] : [];
  // Ссылки, ведущие на сам сервис вместо аккаунта, не показываем: клик по
  // ним выглядит как поломка. В истории такие ещё встречаются.
  const socials = org.socials.filter((s) => isUsefulSocial(parseSocial(s).url));
  const hasSocials = socials.length > 0;
  const mapsUrl = yandexMapsUrl(org);

  return (
    <tr className="border-b border-border/50 transition-colors hover:bg-secondary/30">
      {/* Выбор строки под демо */}
      {demoEnabled && (
        <td className="px-3 py-3 align-top">
          {org.website ? (
            <input
              type="checkbox"
              aria-label={`Выбрать ${org.name}`}
              checked={selected}
              onChange={onToggle}
              className="mt-1 h-3.5 w-3.5 cursor-pointer accent-[hsl(var(--primary))]"
            />
          ) : null}
        </td>
      )}

      {/* Название */}
      <td className="px-3 py-3 align-top">
        <div className="flex items-start gap-1.5">
          {/* Взять в работу. Запись переживает вытеснение выгрузки из истории. */}
          <button
            onClick={onToggleWork}
            title={inWork ? "Убрать из работы" : "Взять в работу"}
            aria-label={inWork ? `Убрать ${org.name} из работы` : `Взять ${org.name} в работу`}
            className={cn(
              "mt-0.5 shrink-0 transition-colors",
              inWork
                ? "text-warning hover:text-warning/70"
                : "text-muted-foreground/40 hover:text-warning",
            )}
          >
            <Star className={cn("h-3.5 w-3.5", inWork && "fill-current")} />
          </button>
          <span className="font-medium leading-tight">{org.name}</span>
          {mapsUrl && (
            <a
              href={mapsUrl}
              target="_blank"
              rel="noopener noreferrer"
              title="Открыть в Яндекс.Картах"
              className="mt-0.5 shrink-0 text-muted-foreground/60 transition-colors hover:text-primary"
            >
              <MapPin className="h-3 w-3" />
            </a>
          )}
        </div>
        {org.categories.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {org.categories.slice(0, 2).map((c) => (
              <span
                key={c}
                className="rounded bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground"
              >
                {c}
              </span>
            ))}
          </div>
        )}
      </td>

      {/* Адрес */}
      <td className="hidden max-w-xs px-3 py-3 align-top text-muted-foreground md:table-cell">
        {org.address ?? "—"}
      </td>

      {/* Телефоны — все, с городом: у салона в Сочи первым идёт московский */}
      <td className="px-3 py-3 align-top">
        {phones.length > 0 ? (
          <div className="flex flex-col gap-1">
            {phones.map((p) => (
              <a
                key={p}
                href={`tel:${p.replace(/\(.*?\)\s*$/, "").replace(/\D/g, "")}`}
                title={p}
                className="inline-flex items-center gap-1.5 text-foreground hover:text-primary"
              >
                <Phone className="h-3 w-3 shrink-0 text-muted-foreground" />
                <span className="whitespace-nowrap font-mono text-[11px] leading-tight">
                  {formatPhone(p.replace(/\s*\(([^)]*[а-яА-Я][^)]*)\)\s*$/, ""))}
                </span>
                {/* Город берём из пометки Яндекса, если она была */}
                {/\(([^)]*[а-яА-Я][^)]*)\)\s*$/.test(p) && (
                  <span className="text-[10px] text-muted-foreground">
                    {p.match(/\(([^)]*[а-яА-Я][^)]*)\)\s*$/)?.[1]}
                  </span>
                )}
              </a>
            ))}
          </div>
        ) : (
          <span className="text-muted-foreground/50">—</span>
        )}
      </td>

      {/* Сайты — тоже все: рядом с настоящим часто висит страница записи */}
      <td className="px-3 py-3 align-top">
        {sites.length > 0 ? (
          <div className="flex flex-col gap-1">
            {sites.map((s) => (
              <a
                key={s}
                href={normalizeUrl(s) ?? "#"}
                target="_blank"
                rel="noopener noreferrer"
                title={s}
                className="group inline-flex items-center gap-1.5 text-primary hover:underline"
              >
                <Globe className="h-3 w-3 shrink-0" />
                <span className="max-w-[180px] truncate">{shortenUrl(s)}</span>
                <ExternalLink className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-100" />
              </a>
            ))}
          </div>
        ) : (
          <span className="inline-flex items-center rounded-full bg-warning/10 px-2 py-0.5 text-[10px] font-medium text-warning">
            нет сайта
          </span>
        )}
      </td>

      {/* Вердикт по перспективности */}
      {showVerdict && (
        <>
          <td className="px-3 py-3 align-top">
            <VerdictCell verdict={verdict} axis="ai" />
          </td>
          <td className="px-3 py-3 align-top">
            <VerdictCell verdict={verdict} axis="web" />
          </td>
        </>
      )}

      {/* Контакты: email + соцсети */}
      <td className="hidden px-3 py-3 align-top lg:table-cell">
        <div className="flex flex-col gap-1">
          {org.email ? (
            <a
              href={`mailto:${org.email}`}
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-primary"
            >
              <Mail className="h-3 w-3" />
              <span className="max-w-[180px] truncate">{org.email}</span>
            </a>
          ) : null}
          {hasSocials && (
            <div className="flex flex-wrap gap-1">
              {socials.slice(0, 3).map((s) => {
                const { label, url } = parseSocial(s);
                return (
                  <a
                    key={s}
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 rounded bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
                  >
                    <MessageCircle className="h-2.5 w-2.5" />
                    {label}
                  </a>
                );
              })}
            </div>
          )}
          {!org.email && !hasSocials && (
            <span className="text-muted-foreground/40">—</span>
          )}
        </div>
      </td>

      {/* Рейтинг */}
      <td className="hidden px-3 py-3 text-right align-top lg:table-cell">
        {org.rating !== null && org.rating !== undefined ? (
          <div className="flex flex-col items-end">
            <span className="inline-flex items-center gap-1 font-mono text-sm font-medium">
              <Star className="h-3 w-3 fill-warning text-warning" />
              {org.rating.toFixed(1)}
            </span>
            {org.reviews_count !== null && org.reviews_count !== undefined && (
              <span className="text-[10px] text-muted-foreground">
                {formatNumber(org.reviews_count)} отз.
              </span>
            )}
          </div>
        ) : (
          <span className="text-muted-foreground/40">—</span>
        )}
      </td>

      {/* Демо ИИ-ассистента */}
      {demoEnabled && (
        <td className="px-3 py-3 align-top">
          <DemoCell
            demo={demo}
            provisioning={provisioning}
            hasSite={!!org.website}
            onDelete={onDeleteDemo}
          />
        </td>
      )}
    </tr>
  );
}

/** Состояние демо для одной организации: ссылка, прогресс или причина отказа. */
function DemoCell({
  demo,
  provisioning,
  hasSite,
  onDelete,
}: {
  demo?: DemoStatus;
  provisioning: boolean;
  hasSite: boolean;
  onDelete: (slug: string) => Promise<void>;
}) {
  const [copied, setCopied] = useState(false);
  const [confirming, setConfirming] = useState(false);

  if (provisioning) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
        Завожу…
      </span>
    );
  }

  if (!demo) {
    return hasSite ? (
      <span className="text-muted-foreground/40">—</span>
    ) : (
      <span className="text-[10px] text-muted-foreground/50">нужен сайт</span>
    );
  }

  if (isDemoPending(demo.status)) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
        {DEMO_STATE_LABELS[demo.status]}
      </span>
    );
  }

  // «Мало данных» — не ошибка: ссылка рабочая, посмотреть можно, но клиенту
  // такое отправлять нельзя. Поэтому предупреждение, а не красный статус.
  if (demo.status === "thin") {
    return (
      <div className="flex flex-col gap-1">
        <span
          title={demo.error ?? "Сайт отдал мало полезного — отправлять клиенту рано"}
          className="inline-flex w-fit items-center gap-1 rounded-full bg-warning/10 px-2 py-0.5 text-[10px] font-medium text-warning"
        >
          <AlertTriangle className="h-2.5 w-2.5" />
          {DEMO_STATE_LABELS.thin}
        </span>
        <div className="flex items-center gap-2">
          {demo.link && (
            <a
              href={demo.link}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[10px] text-muted-foreground hover:text-foreground hover:underline"
            >
              проверить самому
            </a>
          )}
          <DeleteDemoButton
            slug={demo.slug}
            confirming={confirming}
            setConfirming={setConfirming}
            onDelete={onDelete}
          />
        </div>
      </div>
    );
  }

  if (demo.status !== "ready") {
    return (
      <span
        title={demo.error ?? undefined}
        className="inline-flex items-center rounded-full bg-destructive/10 px-2 py-0.5 text-[10px] font-medium text-destructive"
      >
        {DEMO_STATE_LABELS[demo.status]}
      </span>
    );
  }

  async function copyLink() {
    if (!demo?.link) return;
    try {
      await navigator.clipboard.writeText(demo.link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Буфер обмена недоступен — ссылка всё равно кликабельна рядом.
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1.5">
        {demo.link ? (
          <>
            <a
              href={demo.link}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              <Bot className="h-3 w-3" />
              Демо
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
          </>
        ) : (
          // Демо готово, но username бота не задан — ссылку собрать не из чего.
          <span className="font-mono text-[10px] text-muted-foreground">{demo.slug}</span>
        )}
        <DeleteDemoButton
          slug={demo.slug}
          confirming={confirming}
          setConfirming={setConfirming}
          onDelete={onDelete}
        />
      </div>

      <span className="text-[10px] text-muted-foreground">
        {demo.pages_indexed > 0 && `${demo.pages_indexed} стр.`}
        {demo.opened_count > 0 && (
          <span className="ml-1 text-success">
            · открыл{demo.message_count > 0 && `, ${demo.message_count} вопр.`}
          </span>
        )}
      </span>
    </div>
  );
}
