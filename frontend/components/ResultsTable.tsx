"use client";

import { useMemo, useState } from "react";
import {
  ArrowUpDown,
  Download,
  ExternalLink,
  Globe,
  Mail,
  MessageCircle,
  Phone,
  Search as SearchIcon,
  Star,
} from "lucide-react";
import type { Organization } from "@/lib/types";
import { exportUrl } from "@/lib/api";
import {
  cn,
  formatNumber,
  formatPhone,
  normalizeUrl,
  parseSocial,
  shortenUrl,
} from "@/lib/utils";
import { Badge, Button, Input, buttonClass } from "@/components/ui";

type SiteFilter = "all" | "with" | "without";
type SortKey = "name" | "rating" | "reviews";
type SortDir = "asc" | "desc";

export function ResultsTable({
  organizations,
  taskId,
}: {
  organizations: Organization[];
  taskId: string;
}) {
  const [query, setQuery] = useState("");
  const [siteFilter, setSiteFilter] = useState<SiteFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

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
  }, [organizations, query, siteFilter, sortKey, sortDir]);

  const withSite = organizations.filter((o) => o.website).length;
  const withoutSite = organizations.length - withSite;

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

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
              </tr>
            </thead>
            <tbody>
              {filtered.map((org, i) => (
                <OrgRow key={org.permalink ?? `${org.name}-${i}`} org={org} />
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-12 text-center text-muted-foreground">
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
    </div>
  );
}

/* ------------------------------------------------------------------ */

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

function OrgRow({ org }: { org: Organization }) {
  const siteUrl = normalizeUrl(org.website);
  const hasSocials = org.socials.length > 0;

  return (
    <tr className="border-b border-border/50 transition-colors hover:bg-secondary/30">
      {/* Название */}
      <td className="px-3 py-3 align-top">
        <div className="font-medium leading-tight">{org.name}</div>
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

      {/* Телефон */}
      <td className="px-3 py-3 align-top">
        {org.phone ? (
          <a
            href={`tel:${org.phone.replace(/\D/g, "")}`}
            className="inline-flex items-center gap-1.5 text-foreground hover:text-primary"
          >
            <Phone className="h-3 w-3 text-muted-foreground" />
            <span className="font-mono text-xs">{formatPhone(org.phone)}</span>
          </a>
        ) : (
          <span className="text-muted-foreground/50">—</span>
        )}
      </td>

      {/* Сайт */}
      <td className="px-3 py-3 align-top">
        {siteUrl ? (
          <a
            href={siteUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="group inline-flex items-center gap-1.5 text-primary hover:underline"
          >
            <Globe className="h-3 w-3" />
            <span className="max-w-[180px] truncate">
              {shortenUrl(org.website)}
            </span>
            <ExternalLink className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-100" />
          </a>
        ) : (
          <span className="inline-flex items-center rounded-full bg-warning/10 px-2 py-0.5 text-[10px] font-medium text-warning">
            нет сайта
          </span>
        )}
      </td>

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
              {org.socials.slice(0, 3).map((s) => {
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
    </tr>
  );
}
