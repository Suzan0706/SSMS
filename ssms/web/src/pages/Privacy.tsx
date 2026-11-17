import { FormEvent, useCallback, useEffect, useState } from "react";

import { api, ApiError, download } from "../api";
import { useLang } from "../i18n";
import StudentPicker, { PickedStudent } from "../StudentPicker";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";
import { useConfirm } from "../widgets";

interface Dsr { id: string; subject_name: string; request_type: string; status: string; details: string | null;
  requested_at: string; due_at: string; overdue: boolean; has_file: boolean }
interface Person { user_id: string; label: string }

export default function Privacy() {
  const [, t] = useLang();
  const [confirm, confirmDialog] = useConfirm();
  const [rows, setRows] = useState<Dsr[]>([]);
  const [student, setStudent] = useState<PickedStudent | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [form, setForm] = useState({ subject_user_id: "", request_type: "EXPORT", details: "" });
  const [error, setError] = useState<ApiError | null>(null);
  const load = useCallback(() => api<Dsr[]>("/data-subject-requests").then(setRows).catch(() => undefined), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!student) return;
    Promise.all([
      api<{ user_id: string; full_name: string }>(`/students/${student.id}`),
      api<Array<{ user_id: string; full_name: string; relationship: string }>>(`/students/${student.id}/guardians`),
    ]).then(([s, guardians]) => {
      const list = [{ user_id: s.user_id, label: `${s.full_name} (${t("student")})` },
        ...guardians.map((g) => ({ user_id: g.user_id, label: `${g.full_name} (${g.relationship})` }))];
      setPeople(list);
      setForm((f) => ({ ...f, subject_user_id: list[0].user_id }));
    }).catch((e) => setError(e as ApiError));
  }, [student, t]);

  async function run(action: () => Promise<unknown>) {
    try {
      await action();
      setError(null);
      await load();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  function create(e: FormEvent) {
    e.preventDefault();
    run(async () => {
      await api("/data-subject-requests", { body: { ...form, details: form.details || null } });
      setStudent(null);
      setPeople([]);
      setForm({ subject_user_id: "", request_type: "EXPORT", details: "" });
    });
  }
  const act = (r: Dsr, path: string) => run(() => api(`/data-subject-requests/${r.id}/${path}`, { method: "POST" }));
  const finish = (r: Dsr, status: string) => {
    const note = window.prompt(t("note")) ?? "";
    return run(() => api(`/data-subject-requests/${r.id}`, { method: "PATCH", body: { status, note: note || null } }));
  };

  return (
    <div className="space-y-4">
      {confirmDialog}
      <Card title={t("privacy")}>
        <ErrorBox error={error} />
        <p className="mb-2 text-xs text-slate-500">{t("privacyNote")}</p>
        <ul className="divide-y text-sm" data-testid="dsr-list">
          {rows.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span><b>{r.subject_name}</b> · {r.request_type} · {r.requested_at.slice(0, 10)}
                {r.details && <span className="block text-xs text-slate-500">{r.details}</span>}</span>
              <span className="flex flex-wrap items-center gap-2">
                <Badge>{r.status}</Badge>
                {r.overdue && <Badge>⚠ {t("overdue")} {r.due_at.slice(0, 10)}</Badge>}
                {["RECEIVED", "IN_PROGRESS"].includes(r.status) && (
                  <>
                    {r.request_type === "EXPORT" && <Button kind="plain" onClick={() => act(r, "export")}>{t("exportData")}</Button>}
                    {r.request_type === "DELETE" && (
                      <Button kind="plain" onClick={async () => (await confirm(t("anonymiseConfirm"), t("anonymise"))) && act(r, "anonymise")}>{t("anonymise")}</Button>)}
                    {r.request_type === "CORRECT" && <Button kind="plain" onClick={() => finish(r, "COMPLETED")}>{t("markDone")}</Button>}
                    <Button kind="plain" onClick={() => finish(r, "REJECTED")}>{t("reject")}</Button>
                  </>
                )}
                {r.has_file && (
                  <button className="text-brand-700 underline" onClick={() => download(`/data-subject-requests/${r.id}/file`, `data-${r.id}.json`)}>{t("download")}</button>)}
              </span>
            </li>))}
          {rows.length === 0 && <li className="py-3 text-slate-500">{t("noResults")}</li>}
        </ul>
      </Card>
      <Card title={t("newRequest")}>
        <form className="space-y-2" onSubmit={create}>
          {student ? <p className="text-sm font-semibold">{student.full_name} · {student.admission_no}</p> : <StudentPicker onPick={setStudent} />}
          {people.length > 0 && (
            <div className="grid gap-2 sm:grid-cols-3">
              <Field label={t("person")}>
                <Select value={form.subject_user_id} onChange={(e) => setForm({ ...form, subject_user_id: e.target.value })}>
                  {people.map((p) => <option key={p.user_id} value={p.user_id}>{p.label}</option>)}
                </Select>
              </Field>
              <Field label={t("requestType")}>
                <Select value={form.request_type} onChange={(e) => setForm({ ...form, request_type: e.target.value })}>
                  <option value="EXPORT">EXPORT</option><option value="CORRECT">CORRECT</option><option value="DELETE">DELETE</option>
                </Select>
              </Field>
              <Field label={t("note")}><Input maxLength={500} value={form.details} onChange={(e) => setForm({ ...form, details: e.target.value })} /></Field>
            </div>
          )}
          <Button type="submit" disabled={!form.subject_user_id}>{t("save")}</Button>
        </form>
      </Card>
    </div>
  );
}
