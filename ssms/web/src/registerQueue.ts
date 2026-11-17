// Offline queue for morning registers: every mark is stored on the device first, then sent when online.
// Each mark has its own client_record_id (the server ignores a repeat) and the time it was taken; when another phone
// marked the same student later, the server keeps that value and answers "conflict".
import { api } from "./api";

export type Mark = "PRESENT" | "ABSENT" | "LATE" | "EXCUSED";

export interface QueuedRecord {
  client_record_id: string;
  session_date: string;
  stream_id: string;
  student_id: string;
  status: Mark;
  captured_at: string;
  state: "pending" | "conflict" | "error";
  server?: { status: Mark; captured_at: string };
  error_code?: string;
}

interface SyncResult {
  client_record_id: string;
  result: "synced" | "conflict" | "error";
  code: string | null;
  server: QueuedRecord["server"] | null;
}

const KEY = "ssms.register.queue.v1";
const listeners = new Set<() => void>();

export const keyOf = (r: Pick<QueuedRecord, "session_date" | "stream_id" | "student_id">) =>
  `${r.session_date}|${r.stream_id}|${r.student_id}`;

function read(): Record<string, QueuedRecord> {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "{}");
  } catch {
    return {};
  }
}

function write(queue: Record<string, QueuedRecord>): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(queue));
  } catch {
    /* storage full or blocked: marks still in memory are sent by the next sync */
  }
  listeners.forEach((l) => l());
}

export function queued(): Record<string, QueuedRecord> {
  return read();
}

export function onChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function mark(records: Array<Pick<QueuedRecord, "session_date" | "stream_id" | "student_id" | "status">>): void {
  const queue = read();
  const now = new Date().toISOString();
  for (const r of records) {
    queue[keyOf(r)] = { ...r, client_record_id: crypto.randomUUID(), captured_at: now, state: "pending" };
  }
  write(queue);
}

/** Drop a conflicting or failed mark (the server value stays). */
export function discard(key: string): void {
  const queue = read();
  delete queue[key];
  write(queue);
}

/** Send every pending mark. Returns how many were saved. */
export async function sync(): Promise<number> {
  const queue = read();
  const pending = Object.entries(queue).filter(([, r]) => r.state === "pending").slice(0, 500);
  if (pending.length === 0 || !navigator.onLine) return 0;
  const items = pending.map(([, r]) => ({
    client_record_id: r.client_record_id, session_date: r.session_date, stream_id: r.stream_id,
    student_id: r.student_id, status: r.status, captured_at: r.captured_at,
  }));
  const out = await api<{ results: SyncResult[] }>("/attendance/sync", { body: { items } });
  const byId = new Map(out.results.map((r) => [r.client_record_id, r]));
  const fresh = read();                                           // marks changed while the request was in flight win
  let saved = 0;
  for (const [key, sent] of pending) {
    const r = byId.get(sent.client_record_id);
    if (!r || fresh[key]?.client_record_id !== sent.client_record_id) continue;
    if (r.result === "synced") {
      saved += 1;
      delete fresh[key];
    } else {
      fresh[key] = { ...sent, state: r.result, server: r.server ?? undefined, error_code: r.code ?? undefined };
    }
  }
  write(fresh);
  return saved;
}
