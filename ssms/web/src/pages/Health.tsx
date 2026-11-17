import { FormEvent, useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { todayEat } from "../dates";
import { useLang } from "../i18n";
import StudentPicker, { PickedStudent } from "../StudentPicker";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";

interface HealthRow { id: string; record_date: string; kind: string; notes: string | null; recorded_by_name: string }

export default function Health() {
  const auth = useAuth();
  const [, t] = useLang();
  const [student, setStudent] = useState<PickedStudent | null>(null);
  const [rows, setRows] = useState<HealthRow[]>([]);
  const [form, setForm] = useState({ record_date: todayEat(), kind: "CLINIC_VISIT", notes: "" });
  const [error, setError] = useState<ApiError | null>(null);
  const load = useCallback(async () => {
    if (!student) return;
    try {
      setRows(await api<HealthRow[]>(`/students/${student.id}/health-records`));
      setError(null);
    } catch (e) {
      setRows([]);
      setError(e as ApiError);
    }
  }, [student]);
  useEffect(() => { load(); }, [load]);
  async function add(e: FormEvent) {
    e.preventDefault();
    if (!student) return;
    try {
      await api(`/students/${student.id}/health-records`, { body: form });
      setForm({ ...form, notes: "" });
      await load();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <Card title={t("health")}>
      <p className="mb-2 text-xs text-slate-500">{t("healthNote")}</p>
      <StudentPicker onPick={setStudent} />
      {student && <p className="mt-2 text-sm font-semibold">{student.full_name} · {student.admission_no}</p>}
      <ErrorBox error={error} />
      <ul className="divide-y text-sm" data-testid="health-records">
        {rows.map((r) => (
          <li key={r.id} className="py-1.5"><span className="text-slate-500">{r.record_date}</span> <Badge>{r.kind}</Badge> {r.notes ?? "—"}
            <span className="text-xs text-slate-500"> · {r.recorded_by_name}</span></li>))}
      </ul>
      {student && !error && auth.can("health.manage") && (
        <form className="mt-3 grid gap-2 sm:grid-cols-4 sm:items-end" onSubmit={add}>
          <Field label={t("date")}><Input type="date" required value={form.record_date} onChange={(e) => setForm({ ...form, record_date: e.target.value })} /></Field>
          <Field label={t("kind")}>
            <Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              {["ALLERGY", "CONDITION", "CLINIC_VISIT", "VACCINATION"].map((k) => <option key={k}>{k}</option>)}
            </Select>
          </Field>
          <Field label={t("note")}><Input required minLength={2} maxLength={1000} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
          <Button type="submit">{t("save")}</Button>
        </form>
      )}
    </Card>
  );
}
