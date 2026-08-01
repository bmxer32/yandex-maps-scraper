"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getVerdicts, scanProspects } from "./api";
import type { Organization, ProspectVerdict } from "./types";
import { rowKey, siteKey } from "./utils";

export interface UseProspects {
  /** Вердикты по ключу сайта — тем же, каким склеиваются демо. */
  verdicts: Record<string, ProspectVerdict>;
  scanning: boolean;
  /** Сколько компаний оценила модель в последнем прогоне. */
  classified: number;
  /** Сколько остались без вердикта модели из-за лимита запросов. */
  quotaHit: number;
  llmEnabled: boolean;
  error: string | null;
  clearError: () => void;
  scan: (orgs: Organization[], refresh?: boolean) => Promise<void>;
}

/**
 * Оценка перспективности организаций.
 *
 * Вердикт — только метка и подсказка: строки из таблицы не исчезают и
 * выбор под демо не блокируется. Отсутствие вердикта ничего не понижает.
 */
export function useProspects(organizations: Organization[]): UseProspects {
  const [verdicts, setVerdicts] = useState<Record<string, ProspectVerdict>>({});
  const [scanning, setScanning] = useState(false);
  const [classified, setClassified] = useState(0);
  const [quotaHit, setQuotaHit] = useState(0);
  const [llmEnabled, setLlmEnabled] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Разложить вердикты по ключам строк.
   *
   * `orgs` — те организации, что уходили в запрос: бэкенд отвечает в том же
   * порядке, и по ним достаётся ключ для компаний без сайта. Без этого весь
   * сегмент «сайта нет» оставался бы без вердикта — а на оси «сайт» это
   * первые кандидаты.
   */
  const merge = useCallback((items: ProspectVerdict[], orgs?: Organization[]) => {
    if (items.length === 0) return;
    setVerdicts((prev) => {
      const next = { ...prev };
      items.forEach((v, i) => {
        const org = orgs && orgs.length === items.length ? orgs[i] : undefined;
        const key = v.site || siteKey(v.website) || (org ? rowKey(org) : "");
        if (key) next[key] = v;
      });
      return next;
    });
  }, []);

  // Подтягиваем уже посчитанное: оценка стоит запроса к сайту и вызова
  // модели, платить за неё повторно при возврате к выдаче незачем.
  const loadedFor = useRef<string>("");
  useEffect(() => {
    const sites = Array.from(
      new Set(organizations.map((o) => siteKey(o.website)).filter(Boolean)),
    );
    const signature = sites.join("|");
    if (!signature || signature === loadedFor.current) return;
    loadedFor.current = signature;

    let cancelled = false;
    getVerdicts(sites)
      .then((items) => {
        if (!cancelled) merge(items);
      })
      .catch(() => {
        // Бэкенд ещё не поднялся — не ошибка, оценка запускается вручную.
      });
    return () => {
      cancelled = true;
    };
  }, [organizations, merge]);

  const scan = useCallback(
    async (orgs: Organization[], refresh = false) => {
      if (orgs.length === 0) return;
      setScanning(true);
      setError(null);
      try {
        const res = await scanProspects(
          orgs.map((o) => ({
            name: o.name,
            website: o.website,
            reviews_count: o.reviews_count,
            rating: o.rating,
            socials: o.socials ?? [],
            address: o.address,
            categories: o.categories ?? [],
          })),
          refresh,
        );
        merge(res.items, orgs);
        setClassified(res.classified);
        setQuotaHit(res.quota_hit);
        setLlmEnabled(res.llm_enabled);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Не удалось оценить организации");
      } finally {
        setScanning(false);
      }
    },
    [merge],
  );

  const clearError = useCallback(() => setError(null), []);

  return { verdicts, scanning, classified, quotaHit, llmEnabled, error, clearError, scan };
}
