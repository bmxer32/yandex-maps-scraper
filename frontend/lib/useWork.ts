"use client";

import { useCallback, useEffect, useState } from "react";
import { addWork, listWork, removeWork, updateWork } from "./api";
import type { Organization, VerdictState, WorkItem, WorkStatus } from "./types";
import { workKey } from "./utils";

/** Организация плюс оценка на момент добавления — видно, зачем взяли. */
export type WorkCandidate = Organization & { verdict?: VerdictState; web?: VerdictState };

export interface UseWork {
  items: Record<string, WorkItem>;
  loading: boolean;
  error: string | null;
  clearError: () => void;
  /** Есть ли контора в работе — звёздочка в таблице спрашивает это. */
  has: (org: Organization) => boolean;
  add: (orgs: WorkCandidate[]) => Promise<void>;
  /** Убрать по ключу конторы. */
  remove: (key: string) => Promise<void>;
  patch: (
    key: string,
    patch: { status?: WorkStatus; note?: string; remind_at?: string | null; clear_remind?: boolean },
  ) => Promise<void>;
  reload: () => Promise<void>;
}

/**
 * Конторы в работе.
 *
 * Состояние поднято на страницу и общее у таблицы и раздела: звёздочка в
 * выдаче и список «В работе» показывают одно и то же, иначе добавил в одном
 * месте — не видно в другом.
 */
export function useWork(): UseWork {
  const [items, setItems] = useState<Record<string, WorkItem>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const merge = useCallback((list: WorkItem[]) => {
    setItems((prev) => {
      const next = { ...prev };
      for (const it of list) next[it.key] = it;
      return next;
    });
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const list = await listWork();
      setItems(Object.fromEntries(list.map((it) => [it.key, it])));
      setError(null);
    } catch {
      // Бэкенд ещё не поднялся — не ошибка, раздел просто пуст.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const add = useCallback(
    async (orgs: WorkCandidate[]) => {
      if (orgs.length === 0) return;
      try {
        merge(await addWork(orgs));
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Не удалось добавить в работу");
      }
    },
    [merge],
  );

  const remove = useCallback(async (key: string) => {
    try {
      await removeWork(key);
      setItems((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось убрать из работы");
    }
  }, []);

  const patch = useCallback<UseWork["patch"]>(async (key, body) => {
    try {
      const updated = await updateWork(key, body);
      setItems((prev) => ({ ...prev, [key]: updated }));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сохранить");
    }
  }, []);

  const has = useCallback((org: Organization) => !!items[workKey(org)], [items]);

  const clearError = useCallback(() => setError(null), []);

  return { items, loading, error, clearError, has, add, remove, patch, reload };
}
