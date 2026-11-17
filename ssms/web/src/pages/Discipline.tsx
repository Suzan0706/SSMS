import { FormEvent, useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { todayEat } from "../dates";
import { useLang } from "../i18n";
import StudentPicker, { PickedStudent } from "../StudentPicker";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";

const CATEGORIES = ["LATENESS", "TRUANCY", "FIGHTING", "BULLYING", "THEFT", "CHEATING", "PROPERTY_DAMAGE", "OTHER"];

interface Incident { id: string; student_id: string; full_name: string; admission_no: string; incident_date: string; category: string;
  description: string; action_taken: string | null; resolution: string | null; status: string; parent_notified_at: string | null;
  recorded_by: string; recorded_by_name: string }

function Resolve({ item, onDone }: { item: Incident; onDone: () => void }) {
  const [, t] = useLang();
  const [resolution, setResolution] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api(`/discipline-records/${item.id}`, { method: "PATCH", body: { resolution, resolve: true } });
      onDone();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <form className="mt-1 flex flex-wrap gap-2" onSubmit={submit}>
      <ErrorBox error={error} />
      <Input required minLength={3} placeholder={t("resolution")} aria-label={`${t("resolution")} ${item.full_name}`} value={resolution} onChange={(e) => setResolution(e.target.value)} />
      <Button type="submit" kind="plain">{t("resolve")}</Button>
    </form>
  );
}

export default function Discipline() {
  const auth = useAuth();
  const [, t] = useLang();
  const [status, setStatus] = useState("OPEN");
  const [rows, setRows] = useState<Incident[]>([]);
  const [student, setStudent] = useState<PickedStudent | null>(null);
  const [form, setForm] = useState({ incident_date: todayEat(), category: "LATENESS", description: "", action_taken: "", notify_parent: true });
  const [error, setError] = useState<ApiError | null>(null);
  const load = useCallback(() => api<Incident[]>(`/discipline-records${status ? `?status=${status}` : ""}`).then(setRows).catch(() => undefined), [status]);
  useEffect(() => { load(); }, [load]);
  const mine = (i: Incident) => i.recorded_by === auth.session?.user.id || auth.can("discipline.read");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!student) return;
    try {
      await api("/discipline-records", { body: { ...form, student_id: student.id, action_taken: form.action_taken || null } });
      setStudent(null);
      setForm({ ...form, description: "", action_taken: "" });
      setError(null);
      load();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <div className="space-y-4">
      {auth.can("discipline.manage") && (
        <Card title={t("newIncident")}>
          <form className="space-y-2" onSubmit={submit}>
            <ErrorBox error={error} />
            {student ? <p className="text-sm font-semibold">{student.full_name} · {student.admission_no}</p> : <StudentPicker onPick={setStudent} />}
            <div className="grid gap-2 sm:grid-cols-2">
              <Field label={t("date")}><Input type="date" required max={todayEat()} value={form.incident_date} onChange={(e) => setForm({ ...form, incident_date: e.target.value })} /></Field>
              <Field label={t("category")}>
                <Select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                  {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
                </Select>
              </Field>
            </div>
            <Field label={t("message")}>
              <textarea required minLength={3} maxLength={1000} rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
            </Field>
            <Field label={t("actionTaken")}><Input maxLength={500} value={form.action_taken} onChange={(e) => setForm({ ...form, action_taken: e.target.value })} /></Field>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.notify_parent}
              onChange={(e) => setForm({ ...form, notify_parent: e.target.checked })} />{t("notifyParent")}</label>
            <Button type="submit" disabled={!student}>{t("save")}</Button>
          </form>
        </Card>
      )}
      <Card title={t("discipline")} actions={
        <Select aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="OPEN">OPEN</option><option value="RESOLVED">RESOLVED</option><option value="">{t("allStatuses")}</option>
        </Select>}>
        <ul className="divide-y text-sm" data-testid="incidents">
          {rows.map((i) => (
            <li key={i.id} className="py-2">
              <p className="flex flex-wrap justify-between gap-2"><span><b>{i.full_name}</b> · {i.incident_date} · {i.category}</span>
                <span className="flex gap-1"><Badge>{i.status}</Badge>{i.parent_notified_at && <Badge>SMS ✓</Badge>}</span></p>
              <p className="text-slate-700">{i.description}</p>
              <p className="text-xs text-slate-500">{i.recorded_by_name}{i.action_taken ? ` · ${i.action_taken}` : ""}{i.resolution ? ` · ${i.resolution}` : ""}</p>
              {i.status === "OPEN" && mine(i) && <Resolve item={i} onDone={load} />}
            </li>))}
          {rows.length === 0 && <li className="py-2 text-slate-500">{t("noResults")}</li>}
        </ul>
      </Card>
    </div>
  );
}
