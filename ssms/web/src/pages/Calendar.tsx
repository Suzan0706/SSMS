// School calendar: everyone sees the events for their audience; the office plans them (FR-99).
import { FormEvent, useState } from "react";

import { useList } from "../academic";
import { api, ApiError, fieldErrors } from "../api";
import { useAuth } from "../auth";
import { useLang, Word } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";
import { useConfirm } from "../widgets";

export interface SchoolEvent { id: string; title_en: string; title_sw: string; starts_on: string; ends_on: string; audience: string }

const blank = { title_sw: "", title_en: "", starts_on: "", ends_on: "", audience: "ALL" };

export function eventDates(e: SchoolEvent, lang: string): string {
  const fmt = new Intl.DateTimeFormat(lang === "sw" ? "sw-TZ" : "en-GB", { day: "numeric", month: "short" });
  const a = fmt.format(new Date(e.starts_on)), b = fmt.format(new Date(e.ends_on));
  return a === b ? a : `${a} – ${b}`;
}

export default function Calendar() {
  const auth = useAuth();
  const [lang, t] = useLang();
  const [events, reload] = useList<SchoolEvent>("/events");
  const [form, setForm] = useState(blank);
  const [error, setError] = useState<ApiError | null>(null);
  const [confirm, confirmDialog] = useConfirm();
  const canPlan = auth.can("calendar.manage");

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/events", { body: { ...form, title_en: form.title_en || form.title_sw, ends_on: form.ends_on || form.starts_on } });
      setForm(blank);
      setError(null);
      reload();
    } catch (err) {
      setError(err as ApiError);
    }
  }

  async function remove(ev: SchoolEvent) {
    if (!(await confirm(lang === "sw" ? ev.title_sw : ev.title_en, t("delete")))) return;
    await api(`/events/${ev.id}?reason=${encodeURIComponent("removed from the calendar")}`, { method: "DELETE" });
    reload();
  }

  const months = new Map<string, SchoolEvent[]>();
  for (const ev of events) {
    const key = new Intl.DateTimeFormat(lang === "sw" ? "sw-TZ" : "en-GB", { month: "long", year: "numeric" }).format(new Date(ev.starts_on));
    months.set(key, [...(months.get(key) ?? []), ev]);
  }

  return (
    <div className="space-y-4">
      {confirmDialog}
      {canPlan && (
        <Card title={t("newEvent")}>
          <form onSubmit={create} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Field label={t("titleSw")} error={fieldErrors(error).title_sw}>
              <Input required value={form.title_sw} onChange={(e) => setForm({ ...form, title_sw: e.target.value })} />
            </Field>
            <Field label={t("titleEn")}><Input value={form.title_en} onChange={(e) => setForm({ ...form, title_en: e.target.value })} /></Field>
            <Field label={t("from")}><Input type="date" required value={form.starts_on} onChange={(e) => setForm({ ...form, starts_on: e.target.value })} /></Field>
            <Field label={t("to")} error={fieldErrors(error).ends_on}><Input type="date" value={form.ends_on} onChange={(e) => setForm({ ...form, ends_on: e.target.value })} /></Field>
            <Field label={t("audience")}>
              <Select value={form.audience} onChange={(e) => setForm({ ...form, audience: e.target.value })}>
                {["ALL", "STAFF", "PARENTS", "STUDENTS"].map((a) => <option key={a} value={a}>{t(`audience${a}` as Word)}</option>)}
              </Select>
            </Field>
            <div className="sm:col-span-2 lg:col-span-5"><ErrorBox error={error} /><Button type="submit" className="mt-2">{t("save")}</Button></div>
          </form>
        </Card>
      )}
      <Card title={t("calendar")}>
        {events.length === 0 && <p className="py-6 text-center text-sm text-slate-500">{t("noEvents")}</p>}
        <div className="space-y-5" data-testid="calendar">
          {[...months.entries()].map(([month, list]) => (
            <section key={month}>
              <h3 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-500">{month}</h3>
              <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200">
                {list.map((ev) => (
                  <li key={ev.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                    <span className="w-28 shrink-0 font-semibold tabular-nums text-brand-700">{eventDates(ev, lang)}</span>
                    <span className="min-w-0 flex-1">{lang === "sw" ? ev.title_sw : ev.title_en}</span>
                    {ev.audience !== "ALL" && <Badge>{t(`audience${ev.audience}` as Word)}</Badge>}
                    {canPlan && <Button kind="plain" onClick={() => remove(ev)}>{t("delete")}</Button>}
                  </li>))}
              </ul>
            </section>
          ))}
        </div>
      </Card>
    </div>
  );
}
