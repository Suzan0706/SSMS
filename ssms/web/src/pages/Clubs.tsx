import { FormEvent, useCallback, useEffect, useState } from "react";

import { DAYS } from "../academic";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import StudentPicker from "../StudentPicker";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";

interface Club { id: string; name: string; kind: string; patron_name: string | null; meeting_day: number | null; members: number }
interface Member { id: string; full_name: string; admission_no: string; role: string }

function Members({ club, onChange }: { club: Club; onChange: () => void }) {
  const [, t] = useLang();
  const [rows, setRows] = useState<Member[] | null>(null);
  const [role, setRole] = useState("MEMBER");
  const [error, setError] = useState<ApiError | null>(null);
  const load = useCallback(() => api<Member[]>(`/activities/${club.id}/members`).then(setRows).catch(() => setRows(null)), [club.id]);
  useEffect(() => { load(); }, [load]);
  if (rows === null) return null;                                   // not this user's club
  async function add(studentId: string) {
    try {
      await api(`/activities/${club.id}/members`, { body: { student_id: studentId, role } });
      setError(null);
      load();
      onChange();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  async function remove(id: string) {
    await api(`/activity-members/${id}`, { method: "DELETE" });
    load();
    onChange();
  }
  return (
    <div className="mt-2 space-y-2 text-sm">
      <ErrorBox error={error} />
      <ul className="divide-y">
        {rows.map((m) => (
          <li key={m.id} className="flex justify-between py-1"><span>{m.full_name} · {m.admission_no} {m.role !== "MEMBER" && <Badge>{m.role}</Badge>}</span>
            <button className="text-xs text-red-700 underline" onClick={() => remove(m.id)}>✕</button></li>))}
      </ul>
      <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
        <StudentPicker onPick={(s) => add(s.id)} label={`${t("addMember")} ${club.name}`} />
        <Select aria-label={t("role")} value={role} onChange={(e) => setRole(e.target.value)}>
          {["MEMBER", "LEADER", "CAPTAIN", "SECRETARY"].map((r) => <option key={r}>{r}</option>)}
        </Select>
      </div>
    </div>
  );
}

export default function Clubs() {
  const auth = useAuth();
  const [lang, t] = useLang();
  const [clubs, setClubs] = useState<Club[]>([]);
  const [open, setOpen] = useState("");
  const [form, setForm] = useState({ name: "", kind: "CLUB", meeting_day: "" });
  const [error, setError] = useState<ApiError | null>(null);
  const load = useCallback(() => api<Club[]>("/activities").then(setClubs).catch(() => undefined), []);
  useEffect(() => { load(); }, [load]);
  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/activities", { body: { name: form.name, kind: form.kind, meeting_day: form.meeting_day ? Number(form.meeting_day) : null } });
      setForm({ name: "", kind: "CLUB", meeting_day: "" });
      setError(null);
      load();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <div className="space-y-4">
      <Card title={t("clubs")}>
        <ul className="divide-y text-sm">
          {clubs.map((c) => (
            <li key={c.id} className="py-2">
              <button className="flex w-full flex-wrap justify-between gap-2 text-left" onClick={() => setOpen(open === c.id ? "" : c.id)}>
                <span className="font-semibold">{c.name} <Badge>{c.kind}</Badge></span>
                <span className="text-slate-500">{c.patron_name ?? ""}{c.meeting_day ? ` · ${DAYS[lang][c.meeting_day - 1] ?? ""}` : ""} · {c.members}</span>
              </button>
              {open === c.id && <Members club={c} onChange={load} />}
            </li>))}
        </ul>
      </Card>
      {auth.can("activities.manage") && (
        <Card title={t("newClub")}>
          <ErrorBox error={error} />
          <form className="flex flex-wrap items-end gap-2" onSubmit={create}>
            <Field label={t("name")}><Input required minLength={2} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label={t("kind")}>
              <Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>{["CLUB", "SPORT", "SOCIETY", "ARTS"].map((k) => <option key={k}>{k}</option>)}</Select>
            </Field>
            <Field label={t("day")}>
              <Select value={form.meeting_day} onChange={(e) => setForm({ ...form, meeting_day: e.target.value })}>
                <option value="">—</option>{DAYS[lang].map((d, i) => <option key={d} value={i + 1}>{d}</option>)}
              </Select>
            </Field>
            <Button type="submit">{t("add")}</Button>
          </form>
        </Card>
      )}
    </div>
  );
}
