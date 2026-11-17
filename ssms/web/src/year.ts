// The academic year on screen (FR-72). null = the current year, which needs no header. Another year is sent to the API
// as X-Academic-Year; the API then shows that year's lists and refuses every change.
import { useSyncExternalStore } from "react";

let chosen: string | null = null;
let owner = "";
const listeners = new Set<() => void>();

const keyFor = (userId: string) => `ssms.year.${userId}`;

/** Called at sign-in: each person's choice is remembered on this device. */
export function loadYearFor(userId: string): void {
  owner = userId;
  try {
    chosen = localStorage.getItem(keyFor(userId));
  } catch {
    chosen = null;
  }
  listeners.forEach((l) => l());
}

export function setViewingYear(yearId: string | null): void {
  chosen = yearId;
  try {
    if (yearId) localStorage.setItem(keyFor(owner), yearId);
    else localStorage.removeItem(keyFor(owner));
  } catch {
    /* private mode: keep it for this tab only */
  }
  listeners.forEach((l) => l());
}

export function getViewingYear(): string | null {
  return chosen;
}

export function useViewingYear(): string | null {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => chosen,
  );
}
