// Offline queue for marks: every edit is stored on the device first, then sent in batches when online.
// Each item carries the version it was based on, so the server can detect edits made elsewhere (conflicts).
import { api } from "./api";

export interface QueuedMark {
  enrolment_id: string;
  subject_id: string;
  component_id: string;
  score: string | null;
  is_absent: boolean;
  version: number;
  client_updated_at: string;
  status: "pending" | "conflict" | "error";
  server?: { score: string | null; is_absent: boolean; version: number };
  error_code?: string;
}

interface ItemResult {
  index: number;
  status: "ok" | "conflict" | "error";
  version: number | null;
  error_code: string | null;
  server: QueuedMark["server"] | null;
}

const KEY = "ssms.marks.queue.v1";
const listeners = new Set<() => void>();

export const keyOf = (m: Pick<QueuedMark, "enrolment_id" | "subject_id" | "component_id">) =>
  `${m.enrolment_id}|${m.subject_id}|${m.component_id}`;

function read(): Record<string, QueuedMark> {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "{}");
  } catch {
    return {};
  }
}

function write(queue: Record<string, QueuedMark>): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(queue));
  } catch {
    /* storage full or blocked: the in-memory edits are still sent by the next sync */
  }
  listeners.forEach((l) => l());
}

export function queued(): Record<string, QueuedMark> {
  return read();
}

export function onChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function enqueue(mark: Omit<QueuedMark, "status" | "client_updated_at">): void {
  const queue = read();
  queue[keyOf(mark)] = { ...mark, status: "pending", client_updated_at: new Date().toISOString() };
  write(queue);
}

/** Resolve a conflict: keep mine (re-send on top of the server version) or take the server value. */
export function resolve(key: string, keepMine: boolean): void {
  const queue = read();
  const item = queue[key];
  if (!item?.server) return;
  if (keepMine) queue[key] = { ...item, version: item.server.version, status: "pending", server: undefined };
  else delete queue[key];
  write(queue);
}

/** Send every pending item. Returns the new versions of saved marks (key -> version). */
export async function sync(): Promise<Record<string, number>> {
  const queue = read();
  const pending = Object.entries(queue).filter(([, m]) => m.status === "pending").slice(0, 500);
  if (pending.length === 0 || !navigator.onLine) return {};
  const items = pending.map(([, m]) => ({
    enrolment_id: m.enrolment_id, subject_id: m.subject_id, component_id: m.component_id,
    score: m.is_absent ? null : m.score, is_absent: m.is_absent, version: m.version, client_updated_at: m.client_updated_at,
  }));
  const out = await api<{ results: ItemResult[] }>("/marks/batch", { method: "PUT", body: { items } });
  const saved: Record<string, number> = {};
  const fresh = read();                                           // edits made while the request was in flight win
  for (const r of out.results) {
    const [key, sent] = pending[r.index];
    if (fresh[key]?.client_updated_at !== sent.client_updated_at) continue;
    if (r.status === "ok") {
      saved[key] = r.version ?? sent.version;
      delete fresh[key];
    } else {
      fresh[key] = { ...sent, status: r.status, server: r.server ?? undefined, error_code: r.error_code ?? undefined };
    }
  }
  write(fresh);
  return saved;
}
