import { FormEvent, useCallback, useEffect, useState } from "react";

import { useList } from "../academic";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { todayEat } from "../dates";
import { useLang } from "../i18n";
import { Button, Card, ErrorBox, Field, Input, Select } from "../ui";

interface Venue { id: string; name: string; total_seats: number }
interface EventRow { id: string; venue_id: string; name: string; event_date: string; time_start: string; time_end: string; seats_occupied: number }

export default function Venues() {
  const auth = useAuth();
  const [, t] = useLang();
  const [venues, reloadVenues] = useList<Venue>("/venues");
  const [events, setEvents] = useState<EventRow[]>([]);
  const [form, setForm] = useState({ venue_id: "", name: "", event_date: todayEat(), time_start: "08:00", time_end: "10:00", seats: "0" });
  const [venueForm, setVenueForm] = useState({ name: "", seats: "" });
  const [error, setError] = useState<ApiError | null>(null);
  const load = useCallback(() => api<EventRow[]>(`/venue-events?from=${todayEat()}`).then(setEvents).catch(() => undefined), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (!form.venue_id && venues[0]) setForm((f) => ({ ...f, venue_id: venues[0].id })); }, [venues, form.venue_id]);
  const manage = auth.can("venues.manage");

  async function book(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/venue-events", { body: { venue_id: form.venue_id, name: form.name, event_date: form.event_date,
        time_start: form.time_start, time_end: form.time_end, seats_occupied: Number(form.seats) } });
      setError(null);
      setForm({ ...form, name: "" });
      load();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  async function addVenue(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/venues", { body: { name: venueForm.name, total_seats: Number(venueForm.seats) } });
      setVenueForm({ name: "", seats: "" });
      await reloadVenues();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  async function cancel(id: string) {
    await api(`/venue-events/${id}`, { method: "DELETE" });
    load();
  }
  return (
    <div className="space-y-4">
      <Card title={t("venues")}>
        <ErrorBox error={error} />
        {manage && (
          <form className="mb-4 grid gap-2 sm:grid-cols-6 sm:items-end" onSubmit={book}>
            <Field label={t("venue")}>
              <Select value={form.venue_id} onChange={(e) => setForm({ ...form, venue_id: e.target.value })}>
                {venues.map((v) => <option key={v.id} value={v.id}>{v.name} ({v.total_seats})</option>)}
              </Select>
            </Field>
            <Field label={t("event")}><Input required minLength={2} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label={t("date")}><Input type="date" required value={form.event_date} onChange={(e) => setForm({ ...form, event_date: e.target.value })} /></Field>
            <Field label={t("start")}><Input type="time" required value={form.time_start} onChange={(e) => setForm({ ...form, time_start: e.target.value })} /></Field>
            <Field label={t("end")}><Input type="time" required value={form.time_end} onChange={(e) => setForm({ ...form, time_end: e.target.value })} /></Field>
            <Field label={t("seats")}><Input type="number" min={0} value={form.seats} onChange={(e) => setForm({ ...form, seats: e.target.value })} /></Field>
            <Button type="submit">{t("book")}</Button>
          </form>
        )}
        <ul className="divide-y text-sm" data-testid="venue-events">
          {events.map((ev) => (
            <li key={ev.id} className="flex flex-wrap justify-between gap-2 py-1.5">
              <span>{ev.event_date} · {ev.time_start.slice(0, 5)}–{ev.time_end.slice(0, 5)} · <b>{ev.name}</b></span>
              <span className="text-slate-500">{venues.find((v) => v.id === ev.venue_id)?.name} · {ev.seats_occupied}
                {manage && <button className="ml-2 text-red-700 underline" onClick={() => cancel(ev.id)}>✕</button>}</span>
            </li>))}
          {events.length === 0 && <li className="py-2 text-slate-500">{t("noResults")}</li>}
        </ul>
      </Card>
      {manage && (
        <Card title={t("venue")}>
          <form className="flex flex-wrap items-end gap-2" onSubmit={addVenue}>
            <Field label={t("name")}><Input required minLength={2} value={venueForm.name} onChange={(e) => setVenueForm({ ...venueForm, name: e.target.value })} /></Field>
            <Field label={t("seats")}><Input type="number" min={1} required value={venueForm.seats} onChange={(e) => setVenueForm({ ...venueForm, seats: e.target.value })} /></Field>
            <Button type="submit" kind="plain">{t("add")}</Button>
          </form>
        </Card>
      )}
    </div>
  );
}
