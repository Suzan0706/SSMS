import { FormEvent, useCallback, useEffect, useState } from "react";

import { api, ApiError, Page } from "../api";
import { clock } from "../dates";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";

interface Entry { id: string; occurred_at: string; actor_user_id: string | null; action: string; entity_type: string;
  entity_id: string | null; before_data: Record<string, unknown> | null; after_data: Record<string, unknown> | null }

const ACTIONS = ["INSERT", "UPDATE", "DELETE", "LOGIN", "LOGIN_FAILED", "EXPORT", "VIEW_SENSITIVE", "PUBLISH", "ROLE_GRANT"];

/** Only the fields that changed (the database already removes *_hash and *_enc). */
function changes(before: Record<string, unknown> | null, after: Record<string, unknown> | null): string {
  const keys = new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})]);
  keys.delete("updated_at");
  return [...keys].filter((k) => JSON.stringify(before?.[k]) !== JSON.stringify(after?.[k]))
    .map((k) => `${k}: ${before ? JSON.stringify(before[k] ?? null) + " → " : ""}${JSON.stringify(after?.[k] ?? null)}`)
    .slice(0, 6).join("; ");
}

export default function Audit() {
  const [, t] = useLang();
  const [filters, setFilters] = useState({ entity: "", action: "", from: "" });
  const [items, setItems] = useState<Entry[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const load = useCallback(async (next: string | null = null) => {
    const q = new URLSearchParams({ limit: "50" });
    Object.entries(filters).forEach(([k, v]) => { if (v) q.set(k, k === "from" ? `${v}T00:00:00+03:00` : v); });
    if (next) q.set("cursor", next);
    try {
      const page = await api<Page<Entry>>(`/audit-logs?${q}`);
      setItems((old) => (next ? [...old, ...page.items] : page.items));
      setCursor(page.next_cursor ?? null);
      setError(null);
    } catch (e) {
      setError(e as ApiError);
    }
  }, [filters]);
  useEffect(() => { load(); }, [load]);
  return (
    <Card title={t("audit")}>
      <form className="mb-3 grid gap-2 sm:grid-cols-4 sm:items-end" onSubmit={(e: FormEvent) => { e.preventDefault(); load(); }}>
        <Field label={t("entity")}><Input placeholder="students" value={filters.entity} onChange={(e) => setFilters({ ...filters, entity: e.target.value.trim() })} /></Field>
        <Field label={t("action")}>
          <Select value={filters.action} onChange={(e) => setFilters({ ...filters, action: e.target.value })}>
            <option value="">—</option>{ACTIONS.map((a) => <option key={a}>{a}</option>)}
          </Select>
        </Field>
        <Field label={t("from")}><Input type="date" value={filters.from} onChange={(e) => setFilters({ ...filters, from: e.target.value })} /></Field>
      </form>
      <ErrorBox error={error} />
      <ul className="divide-y text-xs" data-testid="audit-list">
        {items.map((e) => (
          <li key={e.id} className="py-1.5">
            <p className="flex flex-wrap gap-2"><span className="text-slate-500">{e.occurred_at.slice(0, 10)} {clock(e.occurred_at)}</span>
              <Badge>{e.action}</Badge><span className="font-mono">{e.entity_type}</span></p>
            <p className="break-all text-slate-600">{changes(e.before_data, e.after_data)}</p>
          </li>))}
      </ul>
      {cursor && <Button kind="plain" onClick={() => load(cursor)}>{t("loadMore")}</Button>}
    </Card>
  );
}
