// Leave: ask for your own leave or a student's, follow it, and (with leave.decide) decide and set leave types (FR-81).
import { FormEvent, useEffect, useState } from "react";

import { nameOf, useList } from "../academic";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import StudentPicker, { PickedStudent } from "../StudentPicker";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";
import { Modal, Tabs } from "../widgets";

interface LeaveType { id: string; name_en: string; name_sw: string; applies_to: "STAFF" | "STUDENT"; days_per_year: number | null }
interface LeaveRow {
  id: string; type_name: string; person: string; staff_id: string | null; student_id: string | null; start_date: string; end_date: string;
  days: number; reason: string; status: string; decision_note: string | null; requested_by_me: boolean; created_at: string;
}

function LeaveList({ scope, version, onChange }: { scope: "mine" | "all"; version: number; onChange: () => void }) {
  const [, t] = useLang();
  const [status, setStatus] = useState(scope === "all" ? "PENDING" : "");
  const [rows, setRows] = useState<LeaveRow[]>([]);
  const [deciding, setDeciding] = useState<{ row: LeaveRow; approve: boolean } | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    api<LeaveRow[]>(`/leave-requests?scope=${scope}${status ? `&status=${status}` : ""}`).then(setRows).catch((e) => setError(e as ApiError));
  }, [scope, status, version]);

  async function decide() {
    if (!deciding) return;
    try {
      await api(`/leave-requests/${deciding.row.id}/decide`, { body: { approve: deciding.approve, note: note || null } });
      setDeciding(null);
      setNote("");
      onChange();
    } catch (e) {
      setError(e as ApiError);
      setDeciding(null);
    }
  }

  async function cancel(row: LeaveRow) {
    try {
      await api(`/leave-requests/${row.id}/cancel`, { method: "POST" });
      onChange();
    } catch (e) {
      setError(e as ApiError);
    }
  }

  return (
    <div className="space-y-3">
      {scope === "all" && (
        <Select aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)} className="max-w-xs">
          <option value="PENDING">PENDING</option><option value="APPROVED">APPROVED</option><option value="REJECTED">REJECTED</option><option value="">{t("allStatuses")}</option>
        </Select>)}
      <ErrorBox error={error} />
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm" aria-label={scope === "all" ? t("leaveToDecide") : t("myLeave")}>
          <thead><tr><th className="py-2 pr-3">{t("name")}</th><th className="pr-3">{t("leaveType")}</th><th className="pr-3">{t("dates")}</th><th className="pr-3">{t("days")}</th><th className="pr-3">{t("reason")}</th><th className="pr-3">{t("status")}</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-slate-100 last:border-0">
                <td className="py-2 pr-3">{r.person}</td><td className="pr-3">{r.type_name}</td>
                <td className="whitespace-nowrap pr-3">{r.start_date} → {r.end_date}</td><td className="pr-3">{r.days}</td>
                <td className="pr-3">{r.reason}{r.decision_note && <span className="block text-xs text-slate-500">{r.decision_note}</span>}</td>
                <td className="pr-3"><Badge>{r.status}</Badge></td>
                <td>
                  <span className="flex gap-2">
                    {scope === "all" && r.status === "PENDING" && !r.requested_by_me && (<>
                      <Button onClick={() => setDeciding({ row: r, approve: true })}>{t("approve")}</Button>
                      <Button kind="plain" onClick={() => setDeciding({ row: r, approve: false })}>{t("reject")}</Button>
                    </>)}
                    {r.requested_by_me && r.status === "PENDING" && <Button kind="plain" onClick={() => cancel(r)}>{t("cancel")}</Button>}
                  </span>
                </td>
              </tr>))}
          </tbody>
        </table>
      </div>
      <Modal open={deciding !== null} title={deciding?.approve ? t("approve") : t("reject")} onClose={() => setDeciding(null)}
        footer={<><Button kind="plain" onClick={() => setDeciding(null)}>{t("cancel")}</Button><Button onClick={decide}>{deciding?.approve ? t("approve") : t("reject")}</Button></>}>
        <p className="mb-3">{deciding?.row.person} · {deciding?.row.start_date} → {deciding?.row.end_date}</p>
        <Field label={t("notes")}><Input maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </Modal>
    </div>
  );
}

function Ask({ types, onDone }: { types: LeaveType[]; onDone: () => void }) {
  const auth = useAuth();
  const [lang, t] = useLang();
  const forStudents = auth.can("attendance.take") || auth.can("leave.decide");
  const [who, setWho] = useState<"me" | "student">(auth.can("leave.request") ? "me" : "student");
  const [student, setStudent] = useState<PickedStudent | null>(null);
  const [f, setF] = useState({ leave_type_id: "", start_date: "", end_date: "", reason: "" });
  const [error, setError] = useState<ApiError | null>(null);
  const kinds = types.filter((k) => k.applies_to === (who === "me" ? "STAFF" : "STUDENT"));
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/leave-requests", { body: { ...f, end_date: f.end_date || f.start_date, ...(who === "student" ? { student_id: student?.id } : {}) } });
      setF({ leave_type_id: "", start_date: "", end_date: "", reason: "" });
      setStudent(null);
      setError(null);
      onDone();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {forStudents && auth.can("leave.request") && (
        <Field label={t("leaveFor")}>
          <Select value={who} onChange={(e) => { setWho(e.target.value as "me" | "student"); setF({ ...f, leave_type_id: "" }); }}>
            <option value="me">{t("myself")}</option><option value="student">{t("aStudent")}</option>
          </Select>
        </Field>)}
      {who === "student" && (
        <div className="sm:col-span-2 lg:col-span-3">
          {student ? <p className="pt-6 text-sm font-semibold">{student.full_name} · {student.admission_no}</p> : <StudentPicker onPick={setStudent} />}
        </div>)}
      <Field label={t("leaveType")}>
        <Select required value={f.leave_type_id} onChange={(e) => setF({ ...f, leave_type_id: e.target.value })}>
          <option value="">—</option>
          {kinds.map((k) => <option key={k.id} value={k.id}>{nameOf(k, lang)}{k.days_per_year ? ` (${k.days_per_year})` : ""}</option>)}
        </Select>
      </Field>
      <Field label={t("from")}><Input type="date" required value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} /></Field>
      <Field label={t("to")}><Input type="date" value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} /></Field>
      <Field label={t("reason")}><Input required minLength={3} maxLength={500} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></Field>
      <div className="sm:col-span-2 lg:col-span-4"><ErrorBox error={error} /><Button type="submit" className="mt-2">{t("askLeave")}</Button></div>
    </form>
  );
}

function Types({ types, onDone }: { types: LeaveType[]; onDone: () => void }) {
  const [lang, t] = useLang();
  const [f, setF] = useState({ name_sw: "", name_en: "", applies_to: "STAFF", days_per_year: "" });
  const [error, setError] = useState<ApiError | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/leave-types", { body: { ...f, name_en: f.name_en || f.name_sw, days_per_year: f.days_per_year ? Number(f.days_per_year) : null } });
      setF({ name_sw: "", name_en: "", applies_to: "STAFF", days_per_year: "" });
      onDone();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <div className="space-y-4">
      <ul className="divide-y divide-slate-100 text-sm">
        {types.map((k) => <li key={k.id} className="flex justify-between py-2"><span>{nameOf(k, lang)}</span><span className="text-slate-500">{k.applies_to === "STAFF" ? t("staff") : t("students")}{k.days_per_year ? ` · ${k.days_per_year} ${t("days")}` : ""}</span></li>)}
      </ul>
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label={t("titleSw")}><Input required value={f.name_sw} onChange={(e) => setF({ ...f, name_sw: e.target.value })} /></Field>
        <Field label={t("titleEn")}><Input value={f.name_en} onChange={(e) => setF({ ...f, name_en: e.target.value })} /></Field>
        <Field label={t("leaveFor")}>
          <Select value={f.applies_to} onChange={(e) => setF({ ...f, applies_to: e.target.value })}><option value="STAFF">{t("staff")}</option><option value="STUDENT">{t("students")}</option></Select>
        </Field>
        <Field label={t("daysPerYear")}><Input type="number" min={1} max={366} value={f.days_per_year} onChange={(e) => setF({ ...f, days_per_year: e.target.value })} /></Field>
        <div className="sm:col-span-2 lg:col-span-4"><ErrorBox error={error} /><Button type="submit" className="mt-2">{t("save")}</Button></div>
      </form>
    </div>
  );
}

export default function Leave() {
  const auth = useAuth();
  const [, t] = useLang();
  const [types, reloadTypes] = useList<LeaveType>("/leave-types");
  const [version, setVersion] = useState(0);
  const decider = auth.can("leave.decide");
  const tabs: Array<["mine" | "all" | "types", string]> = [["mine", t("myLeave")]];
  if (decider) tabs.push(["all", t("leaveToDecide")], ["types", t("leaveTypes")]);
  const [tab, setTab] = useState<"mine" | "all" | "types">(decider ? "all" : "mine");
  const bump = () => setVersion((v) => v + 1);
  return (
    <div className="space-y-4">
      <Card title={t("askLeave")}><Ask types={types} onDone={bump} /></Card>
      <Card title={t("leave")}>
        <Tabs label={t("leave")} value={tab} onChange={setTab} tabs={tabs} />
        {tab === "types" ? <Types types={types} onDone={reloadTypes} /> : <LeaveList scope={tab} version={version} onChange={bump} />}
      </Card>
    </div>
  );
}
