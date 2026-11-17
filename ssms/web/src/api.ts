// API client on Axios. The access token lives in memory only; the refresh token is an httpOnly cookie the browser
// sends to /api/v1/auth. A 401 triggers one silent refresh, then the request is retried once.
// Every page uses the functions below, never Axios directly, so the transport can change without touching them.
import axios, { AxiosError, AxiosResponse } from "axios";

import { getLang } from "./i18n";
import { getViewingYear, loadYearFor } from "./year";

export const BASE = "/api/v1";

export interface ApiError {
  status: number;
  error_code: string;
  message: string;
  details: Array<Record<string, unknown>>;
}

export interface Session {
  access_token: string;
  expires_in: number;
  user: { id: string; full_name: string; username: string | null; language: string; must_change_password: boolean };
  school: { id: string; code: string; name: string; status: string };
  roles: string[];
  permissions: string[];
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

let token: string | null = null;
let refreshing: Promise<Session | null> | null = null;
let onSession: (s: Session | null) => void = () => {};

export function bindSession(listener: (s: Session | null) => void): void {
  onSession = listener;
}

export function applySession(session: Session | null): void {
  token = session?.access_token ?? null;
  if (session) loadYearFor(session.user.id);
  onSession(session);
}

const http = axios.create({ baseURL: BASE, withCredentials: true, timeout: 60_000 });

http.interceptors.request.use((config) => {
  config.headers.set("Accept-Language", getLang());
  if (token) config.headers.set("Authorization", `Bearer ${token}`);
  const year = getViewingYear();
  if (year) config.headers.set("X-Academic-Year", year);
  return config;
});

async function toError(error: unknown): Promise<ApiError> {
  const res = (error as AxiosError).response;
  if (!res) return { status: 0, error_code: "OFFLINE", message: "", details: [] };
  let body: unknown = res.data;
  if (body instanceof Blob) {
    try {
      body = JSON.parse(await body.text());
    } catch {
      body = null;
    }
  }
  if (body && typeof body === "object" && "error_code" in body) return { status: res.status, ...(body as Omit<ApiError, "status">) };
  return { status: res.status, error_code: "INTERNAL_ERROR", message: res.statusText, details: [] };
}

export function refreshSession(): Promise<Session | null> {
  refreshing ??= http
    .post<Session>("/auth/refresh")
    .then((res) => res.data)
    .catch(() => null)
    .then((s) => {
      applySession(s);
      return s;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

interface Options {
  method?: string;
  body?: unknown;
  form?: FormData;
  headers?: Record<string, string>;
}

async function send(path: string, opts: Options, retry: boolean, blob = false): Promise<AxiosResponse> {
  try {
    return await http.request({
      url: path,
      method: opts.method ?? (opts.body !== undefined || opts.form ? "POST" : "GET"),
      data: opts.form ?? opts.body,
      headers: opts.headers,
      responseType: blob ? "blob" : "json",
    });
  } catch (error) {
    const status = (error as AxiosError).response?.status;
    if (status === 401 && retry && !path.startsWith("/auth/") && (await refreshSession())) {
      return send(path, opts, false, blob);
    }
    throw await toError(error);
  }
}

export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  const res = await send(path, opts, true);
  return (res.status === 204 ? undefined : res.data) as T;
}

/** Download an authenticated file (templates, reports) and hand it to the browser. */
export async function download(path: string, filename: string): Promise<void> {
  const res = await send(path.replace(BASE, ""), {}, true, true);
  const url = URL.createObjectURL(res.data as Blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

/** An authenticated file as a local object URL, for showing an image or opening a document in a new tab. */
export async function objectUrl(path: string): Promise<string> {
  const res = await send(path.replace(BASE, ""), {}, true, true);
  return URL.createObjectURL(res.data as Blob);
}

/** Every page of a cursor-paged list (the API returns at most 50 rows per request). */
export async function fetchAll<T>(path: string): Promise<T[]> {
  const items: T[] = [];
  const sep = path.includes("?") ? "&" : "?";
  let cursor: string | null = null;
  do {
    const after: string = cursor ? `&cursor=${encodeURIComponent(cursor)}` : "";
    const page: Page<T> = await api<Page<T>>(`${path}${sep}limit=50${after}`);
    items.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor);
  return items;
}

export function fieldErrors(error: ApiError | null): Record<string, string> {
  const out: Record<string, string> = {};
  for (const d of error?.details ?? []) {
    if (typeof d.field === "string" && typeof d.message === "string") out[d.field] = d.message;
  }
  return out;
}
