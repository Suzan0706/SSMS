import { FormEvent, useCallback, useEffect, useState } from "react";

import { nameOf, useCurrentTerm, useList } from "../academic";
import { api, ApiError } from "../api";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";

export interface HostelRow { id: string; name: string; gender: string; rooms: number; beds: number }
interface Room { id: string; hostel_id: string; name: string; capacity: number }
export interface RequestRow { id: string; student_id: string; admission_no: string; full_name: string; gender: string;
  term_id: string; preferred_hostel_id: string | null; status: string; note: string | null; room: string | null }
interface Occupancy { beds: number; used: number; rooms: Array<{ room_id: string; name: string; capacity: number;
  occupants: Array<{ allocation_id: string; full_name: string; admission_no: string }> }> }

function Requests({ termId, hostels, onDecided }: { termId: string; hostels: HostelRow[]; onDecided: () => void }) {
  const [, t] = useLang();
  const [rows, setRows] = useState<RequestRow[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [pick, setPick] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const load = useCallback(() => {
    if (termId) api<RequestRow[]>(`/accommodation-requests?term_id=${termId}&status=PENDING`).then(setRows).catch(() => undefined);
  }, [termId]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    Promise.all(hostels.map((h) => api<Room[]>(`/hostel-rooms?hostel_id=${h.id}`))).then((r) => setRooms(r.flat())).catch(() => undefined);
  }, [hostels]);
  const roomLabel = (r: Room) => `${hostels.find((h) => h.id === r.hostel_id)?.name ?? ""} / ${r.name}`;
  async function decide(row: RequestRow, approve: boolean) {
    try {
      await api(`/accommodation-requests/${row.id}/decide`, { body: { approve, room_id: approve ? pick[row.id] : null } });
      setError(null);
      load();
      onDecided();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  return (
    <div className="space-y-2">
      <ErrorBox error={error} />
      <ul className="divide-y text-sm" data-testid="requests">
        {rows.map((r) => {
          const fits = rooms.filter((room) => {
            const hostel = hostels.find((h) => h.id === room.hostel_id);
            return hostel && (hostel.gender === "MIXED" || hostel.gender === r.gender);
          });
          return (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>{r.full_name} · {r.admission_no} · {r.gender}
                {r.preferred_hostel_id && <span className="text-slate-500"> → {hostels.find((h) => h.id === r.preferred_hostel_id)?.name}</span>}</span>
              <span className="flex items-center gap-2">
                <Select aria-label={`${r.full_name} ${t("room")}`} value={pick[r.id] ?? ""} onChange={(e) => setPick({ ...pick, [r.id]: e.target.value })}>
                  <option value="">{t("room")}</option>
                  {fits.map((room) => <option key={room.id} value={room.id}>{roomLabel(room)}</option>)}
                </Select>
                <Button disabled={!pick[r.id]} onClick={() => decide(r, true)}>{t("approve")}</Button>
                <Button kind="plain" onClick={() => decide(r, false)}>{t("reject")}</Button>
              </span>
            </li>);
        })}
        {rows.length === 0 && <li className="py-3 text-slate-500">{t("noResults")}</li>}
      </ul>
    </div>
  );
}

function OccupancyView({ hostel, termId }: { hostel: HostelRow; termId: string }) {
  const [, t] = useLang();
  const [data, setData] = useState<Occupancy | null>(null);
  const [room, setRoom] = useState({ name: "", capacity: "4" });
  const [error, setError] = useState<ApiError | null>(null);
  const load = useCallback(() => {
    if (termId) api<Occupancy>(`/hostels/${hostel.id}/occupancy?term_id=${termId}`).then(setData).catch(() => undefined);
  }, [hostel.id, termId]);
  useEffect(() => { load(); }, [load]);
  async function addRoom(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/hostel-rooms", { body: { hostel_id: hostel.id, name: room.name, capacity: Number(room.capacity) } });
      setRoom({ name: "", capacity: "4" });
      setError(null);
      load();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  async function vacate(id: string) {
    await api(`/hostel-allocations/${id}/vacate`, { method: "POST" });
    load();
  }
  if (!data) return null;
  return (
    <div className="space-y-2 text-sm">
      <ErrorBox error={error} />
      <p>{t("occupancy")}: <b>{data.used} / {data.beds}</b></p>
      <ul className="grid gap-2 sm:grid-cols-2">
        {data.rooms.map((r) => (
          <li key={r.room_id} className="rounded border p-2">
            <p className="font-semibold">{r.name} <span className="font-normal text-slate-500">{r.occupants.length}/{r.capacity}</span></p>
            {r.occupants.map((o) => (
              <p key={o.allocation_id} className="flex justify-between">{o.full_name}
                <button className="text-xs text-red-700 underline" onClick={() => vacate(o.allocation_id)}>{t("vacate")}</button></p>))}
          </li>))}
      </ul>
      <form className="flex flex-wrap items-end gap-2" onSubmit={addRoom}>
        <Field label={t("room")}><Input required value={room.name} onChange={(e) => setRoom({ ...room, name: e.target.value })} /></Field>
        <Field label={t("capacity")}><Input type="number" min={1} max={100} required value={room.capacity} onChange={(e) => setRoom({ ...room, capacity: e.target.value })} /></Field>
        <Button type="submit" kind="plain">{t("add")}</Button>
      </form>
    </div>
  );
}

export default function Hostel() {
  const [lang, t] = useLang();
  const { terms, termId, setTermId } = useCurrentTerm();
  const [hostels, reload] = useList<HostelRow>("/hostels");
  const [form, setForm] = useState({ name: "", gender: "F" });
  const [version, setVersion] = useState(0);                       // bumps after a decision: occupancy reloads
  const [error, setError] = useState<ApiError | null>(null);
  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/hostels", { body: form });
      setForm({ name: "", gender: "F" });
      setError(null);
      await reload();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <div className="space-y-4">
      <Card title={t("accommodationRequests")} actions={
        <Select aria-label={t("term")} value={termId} onChange={(e) => setTermId(e.target.value)}>
          {terms.map((x) => <option key={x.id} value={x.id}>{nameOf(x, lang)}</option>)}
        </Select>}>
        <Requests termId={termId} hostels={hostels} onDecided={() => setVersion((v) => v + 1)} />
      </Card>
      {hostels.map((h) => (
        <Card key={h.id} title={`${h.name} · ${h.gender}`}><OccupancyView key={version} hostel={h} termId={termId} /></Card>))}
      <Card title={t("hostels")}>
        <ErrorBox error={error} />
        <form className="flex flex-wrap items-end gap-2" onSubmit={create}>
          <Field label={t("name")}><Input required minLength={2} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label={t("gender")}>
            <Select value={form.gender} onChange={(e) => setForm({ ...form, gender: e.target.value })}>
              <option value="F">{t("female")}</option><option value="M">{t("male")}</option><option value="MIXED">{t("mixed")}</option>
            </Select>
          </Field>
          <Button type="submit">{t("add")}</Button>
        </form>
        <p className="mt-2 text-sm text-slate-500">{hostels.map((h) => `${h.name}: ${h.rooms} · ${h.beds}`).join(" — ")} <Badge>{hostels.length}</Badge></p>
      </Card>
    </div>
  );
}
