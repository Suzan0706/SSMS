// Small data hooks shared by the academic screens (reference lists are cached for the page's lifetime).
import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "./api";
import { Lang } from "./i18n";
import { getViewingYear, useViewingYear } from "./year";

export interface Named {
  id: string;
  code: string;
  name_en: string;
  name_sw: string;
}

export interface Year {
  id: string;
  name: string;
  is_current: boolean;
}

export interface Term {
  id: string;
  academic_year_id: string;
  term_no: number;
  name_en: string;
  name_sw: string;
  start_date: string;
  end_date: string;
}

export interface StreamRow {
  id: string;
  class_id: string;
  name: string;
  capacity: number;
  enrolled: number | null;
}

const cache = new Map<string, unknown>();

/** Cache entries are per year on screen, since the API answers some lists for that year. */
const keyOf = (path: string) => `${getViewingYear() ?? "current"}|${path}`;

/** GET a list; `null` path = not ready yet. reload() bypasses the cache. */
export function useList<T>(path: string | null): [T[], () => Promise<void>, ApiError | null] {
  const [items, setItems] = useState<T[]>(() => (path && (cache.get(keyOf(path)) as T[])) || []);
  const [error, setError] = useState<ApiError | null>(null);
  const reload = useCallback(async () => {
    if (!path) return;
    try {
      const data = await api<T[]>(path);
      cache.set(keyOf(path), data);
      setItems(data);
      setError(null);
    } catch (e) {
      setError(e as ApiError);
    }
  }, [path]);
  useEffect(() => {
    if (path && cache.has(keyOf(path))) setItems(cache.get(keyOf(path)) as T[]);
    reload();
  }, [path, reload]);
  return [items, reload, error];
}

export function nameOf(item: { name_en: string; name_sw: string } | undefined, lang: Lang): string {
  return item ? (lang === "sw" ? item.name_sw : item.name_en) : "";
}

/** The year on screen (chosen in the top bar, else the current one) and its terms; the default term is the one
 *  running today, else the first. */
export function useCurrentTerm(): { year?: Year; terms: Term[]; termId: string; setTermId: (id: string) => void } {
  const [years] = useList<Year>("/academic-years");
  const viewing = useViewingYear();
  const year = years.find((y) => y.id === viewing) ?? years.find((y) => y.is_current);
  const [terms] = useList<Term>(year ? `/terms?academic_year_id=${year.id}` : null);
  const [termId, setTermId] = useState("");
  useEffect(() => {
    if (termId || terms.length === 0) return;
    const today = new Date().toISOString().slice(0, 10);
    const running = terms.find((t) => t.start_date <= today && today <= t.end_date);
    setTermId((running ?? [...terms].sort((a, b) => a.start_date.localeCompare(b.start_date))[0]).id);
  }, [terms, termId]);
  return { year, terms, termId, setTermId };
}

export const DAYS: Record<Lang, string[]> = {
  sw: ["", "Jumatatu", "Jumanne", "Jumatano", "Alhamisi", "Ijumaa", "Jumamosi"],
  en: ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
};

export const PERIODS: Array<[string, string]> = [
  ["08:00", "08:40"], ["08:40", "09:20"], ["09:20", "10:00"], ["10:00", "10:40"], ["11:00", "11:40"],
  ["11:40", "12:20"], ["12:20", "13:00"], ["14:00", "14:40"], ["14:40", "15:20"],
];

export function newKey(): string {
  return crypto.randomUUID();
}
