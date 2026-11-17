import { FormEvent, useCallback, useEffect, useState } from "react";

import { Named, newKey, useList } from "../academic";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";

export interface AnnouncementRow {
  id: string;
  title: string;
  body: string;
  audience: string;
  publish_at: string;
  send_sms: boolean;
}

const AUDIENCES = ["SCHOOL", "STAFF", "PARENTS", "CLASS", "STREAM"] as const;

export function AnnouncementList({ items, onDelete }: { items: AnnouncementRow[]; onDelete?: (id: string) => void }) {
  const [, t] = useLang();
  return (
    <ul className="divide-y text-sm" data-testid="announcements">
      {items.map((a) => (
        <li key={a.id} className="py-2">
          <p className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-semibold">📢 {a.title}</span>
            <span className="flex items-center gap-2 text-xs text-slate-500">{a.publish_at.slice(0, 10)}
              {onDelete && <><Badge>{a.audience}{a.send_sms ? " · SMS" : ""}</Badge>
                <button className="text-red-700 underline" onClick={() => onDelete(a.id)}>✕</button></>}</span>
          </p>
          <p className="whitespace-pre-line text-slate-700">{a.body}</p>
        </li>))}
      {items.length === 0 && <li className="py-3 text-slate-500">{t("noResults")}</li>}
    </ul>
  );
}

interface EmailRow { id: string; to: string; subject: string; status: string; error: string | null; queued_at: string }

function EmailHistory() {
  const [, t] = useLang();
  const [rows, setRows] = useState<EmailRow[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const load = useCallback(() => api<EmailRow[]>("/email-messages?limit=50").then(setRows).catch(() => undefined), []);
  useEffect(() => { load(); }, [load]);
  async function test() {
    try {
      await api("/email-messages/test", { method: "POST" });
      setError(null);
      setTimeout(load, 1500);                      // the worker sends it in the background
    } catch (e) {
      setError(e as ApiError);
    }
  }
  return (
    <Card title={t("emailHistory")} actions={<Button kind="plain" onClick={test}>{t("sendTestEmail")}</Button>}>
      <ErrorBox error={error} />
      <ul className="divide-y text-sm" data-testid="email-history">
        {rows.map((r) => (
          <li key={r.id} className="flex flex-wrap justify-between gap-2 py-1.5">
            <span>{r.subject} <span className="text-slate-500">→ {r.to}</span></span>
            <span className="flex items-center gap-2 text-xs text-slate-500">{r.queued_at.slice(0, 16).replace("T", " ")}<Badge>{r.status}</Badge></span>
          </li>))}
        {rows.length === 0 && <li className="py-2 text-slate-500">{t("noResults")}</li>}
      </ul>
    </Card>
  );
}

function Compose({ onSent }: { onSent: () => void }) {
  const [, t] = useLang();
  const [classes] = useList<Named>("/classes");
  const [streams] = useList<{ id: string; name: string; class_id: string }>("/streams");
  const [form, setForm] = useState({ title: "", body: "", language: "sw", audience: "SCHOOL", target: "", send_sms: false, send_email: false });
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    const body = {
      title: form.title, body: form.body, language: form.language, audience: form.audience, send_sms: form.send_sms, send_email: form.send_email,
      class_id: form.audience === "CLASS" ? form.target : null, stream_id: form.audience === "STREAM" ? form.target : null,
    };
    try {
      const out = await api<{ sms_recipients: number; email_recipients: number }>("/announcements", { body, headers: { "Idempotency-Key": newKey() } });
      const sent = [form.send_sms && `${t("smsRecipients")}: ${out.sms_recipients}`, form.send_email && `${t("emailRecipients")}: ${out.email_recipients}`].filter(Boolean);
      setResult(sent.length ? sent.join(" · ") : t("saved"));
      setForm({ ...form, title: "", body: "" });
      setError(null);
      onSent();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  const targets = form.audience === "CLASS" ? classes.map((c) => ({ id: c.id, label: c.code }))
    : form.audience === "STREAM" ? streams.map((s) => ({ id: s.id, label: `${classes.find((c) => c.id === s.class_id)?.code ?? ""} ${s.name}` })) : [];
  return (
    <form className="space-y-2" onSubmit={submit}>
      <ErrorBox error={error} />
      <Field label={t("title")}><Input required minLength={3} maxLength={120} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
      <Field label={t("message")}>
        <textarea required minLength={3} maxLength={2000} rows={4} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })}
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
      </Field>
      <div className="grid gap-2 sm:grid-cols-3">
        <Field label={t("audience")}>
          <Select value={form.audience} onChange={(e) => setForm({ ...form, audience: e.target.value, target: "" })}>
            {AUDIENCES.map((a) => <option key={a}>{a}</option>)}
          </Select>
        </Field>
        {targets.length > 0 && (
          <Field label={form.audience === "CLASS" ? t("classLabel") : t("stream")}>
            <Select required value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })}>
              <option value="">—</option>
              {targets.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
            </Select>
          </Field>
        )}
        <Field label={t("language")}>
          <Select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
            <option value="sw">Kiswahili</option><option value="en">English</option>
          </Select>
        </Field>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={form.send_sms} onChange={(e) => setForm({ ...form, send_sms: e.target.checked })} />{t("sendSms")}
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={form.send_email} onChange={(e) => setForm({ ...form, send_email: e.target.checked })} />{t("sendEmail")}
      </label>
      <div className="flex items-center gap-3"><Button type="submit">{t("newAnnouncement")}</Button>
        {result && <span className="text-sm text-brand-700" data-testid="announce-result">✓ {result}</span>}</div>
    </form>
  );
}

export default function Announcements() {
  const auth = useAuth();
  const [, t] = useLang();
  const [items, setItems] = useState<AnnouncementRow[]>([]);
  const load = useCallback(() => api<AnnouncementRow[]>("/announcements").then(setItems).catch(() => undefined), []);
  useEffect(() => { load(); }, [load]);
  const sender = auth.can("announcements.send");
  async function remove(id: string) {
    await api(`/announcements/${id}`, { method: "DELETE" });
    await load();
  }
  return (
    <div className="space-y-4">
      {sender && <Card title={t("newAnnouncement")}><Compose onSent={load} /></Card>}
      <Card title={t("announcements")}><AnnouncementList items={items} onDelete={sender ? remove : undefined} /></Card>
      {auth.can("email.manage") && <EmailHistory />}
    </div>
  );
}
