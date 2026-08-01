"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteDemo,
  getDemoConfig,
  getDemoStatuses,
  listDemos,
  provisionDemos,
} from "./api";
import type { DemoConfig, DemoStatus, Organization } from "./types";
import { isDemoPending } from "./types";
import { siteKey } from "./utils";

/** Как часто спрашивать, докрутился ли краул. */
const POLL_MS = 4000;

/** Как часто проверять, поднялся ли Docker-стек ассистента. */
const READY_POLL_MS = 3000;

export interface UseDemos {
  config: DemoConfig | null;
  /** Демо по ключу сайта — см. siteKey(). */
  demos: Record<string, DemoStatus>;
  /** Сайты, для которых сейчас идёт запрос на создание. */
  provisioning: Set<string>;
  error: string | null;
  clearError: () => void;
  create: (orgs: Organization[]) => Promise<void>;
  /** Удалить демо вместе с базой знаний. */
  remove: (slug: string) => Promise<void>;
  /** Перечитать список с сервера. */
  refresh: () => Promise<void>;
}

/**
 * Состояние персональных демо для таблицы результатов.
 *
 * Демо привязано к сайту организации, а не к позиции строки: одна и та же
 * компания может встретиться в двух выгрузках, и демо у неё одно.
 */
export function useDemos(): UseDemos {
  const [config, setConfig] = useState<DemoConfig | null>(null);
  const [demos, setDemos] = useState<Record<string, DemoStatus>>({});
  const [provisioning, setProvisioning] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  // Живой снимок для интервала опроса: иначе он замкнётся на demos первого
  // рендера и будет вечно опрашивать один и тот же список.
  const demosRef = useRef(demos);
  demosRef.current = demos;

  const merge = useCallback((items: DemoStatus[]) => {
    if (items.length === 0) return;
    setDemos((prev) => {
      const next = { ...prev };
      for (const item of items) {
        const key = siteKey(item.website);
        if (key) next[key] = item;
      }
      return next;
    });
  }, []);

  // Конфиг + уже заведённые демо. Приложение десктопное и перезапускается
  // часто, так что состояние восстанавливаем с сервера, а не держим локально.
  //
  // Docker-стек ассистента поднимается около минуты после старта программы,
  // поэтому опрашиваем конфиг, пока он не отзовётся готовым: иначе таблица
  // навсегда осталась бы в состоянии «ассистент запускается».
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const cfg = await getDemoConfig();
        if (cancelled) return;
        setConfig(cfg);

        if (!cfg.enabled) return; // интеграции нет — ждать нечего
        if (!cfg.ready) {
          timer = setTimeout(poll, READY_POLL_MS);
          return;
        }

        const existing = await listDemos();
        if (!cancelled) merge(existing);
      } catch {
        // Бэкенд парсера ещё не поднялся — не ошибка, пробуем снова.
        if (!cancelled) timer = setTimeout(poll, READY_POLL_MS);
      }
    };

    poll();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [merge]);

  // Пока хоть одно демо собирается — опрашиваем статусы.
  useEffect(() => {
    if (!config?.enabled) return;

    const pendingSlugs = Object.values(demos)
      .filter((d) => isDemoPending(d.status))
      .map((d) => d.slug);
    if (pendingSlugs.length === 0) return;

    const timer = setInterval(async () => {
      const slugs = Object.values(demosRef.current)
        .filter((d) => isDemoPending(d.status))
        .map((d) => d.slug);
      if (slugs.length === 0) return;
      try {
        merge(await getDemoStatuses(slugs));
      } catch {
        // Сеть моргнула — попробуем на следующем тике.
      }
    }, POLL_MS);

    return () => clearInterval(timer);
  }, [config?.enabled, demos, merge]);

  const create = useCallback(
    async (orgs: Organization[]) => {
      const items = orgs
        .filter((o) => o.website)
        .map((o) => ({ name: o.name, website: o.website as string }));
      if (items.length === 0) return;

      const keys = items.map((i) => siteKey(i.website));
      setProvisioning((prev) => new Set([...prev, ...keys]));
      setError(null);
      try {
        merge(await provisionDemos(items));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Не удалось создать демо");
      } finally {
        setProvisioning((prev) => {
          const next = new Set(prev);
          keys.forEach((k) => next.delete(k));
          return next;
        });
      }
    },
    [merge],
  );

  const remove = useCallback(async (slug: string) => {
    setError(null);
    try {
      await deleteDemo(slug);
      setDemos((prev) => {
        const next: Record<string, DemoStatus> = {};
        for (const [key, demo] of Object.entries(prev)) {
          if (demo.slug !== slug) next[key] = demo;
        }
        return next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось удалить демо");
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const items = await listDemos();
      // Полная замена, а не слияние: удалённые на сервере должны исчезнуть.
      const next: Record<string, DemoStatus> = {};
      for (const item of items) {
        const key = siteKey(item.website);
        if (key) next[key] = item;
      }
      setDemos(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось обновить список демо");
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return { config, demos, provisioning, error, clearError, create, remove, refresh };
}
