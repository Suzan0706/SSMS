// Staff attendance: the day's register and the month's totals (FR-80). Approved leave shows on the register.
import { useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";
import { Tabs } from "../widgets";

interface DayRow { staff_id: string; staff_no: string; full_name: string; status: string | null; on_leave: boolean; time_in: string | null; time_out: string | null; note: string | null }
interface MonthRow { staff_id: string; full_name: string; present: number; late: number; absent: number; on_leave: number }
type Mark = { status: string; time_in: string; time_out: string; note: string };

const STATUSES = ["PRESENT", "LATE", "ABSENT", "ON_LEAVE"];
const today = () => new Date().toISOString().slice(0, 10);

function Register() {
  const auth = useAuth();
  const [, t] = useLang();
  const [day, setDay] = useState(today());
  const [rows, setRows] = useState<DayRow[]>([]);
  const [marks, setMarks] = useState<Record<string, Mark>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  const canTake = auth.can("staff_attendance.take");

  useEffect(() => {
    setSaved(false);
    let stale = false;  // a slower reply for a date no longer chosen must not overwrite the marks
    api<DayRow[]>(`/staff-attendance?on=${day}`).then((data) => {
      if (stale) return;
      setRows(data);
      setMarks(Object.fromEntries(data.map((r) => [r.staff_id, {
        status: r.status ?? (r.on_leave ? "ON_LEAVE" : ""), time_in: r.time_in?.slice(0, 5) ?? "", time_out: r.time_out?.slice(0, 5) ?? "", note: r.note ?? "" }])));
      setError(null);
    }).catch((e) => { if (!stale) setError(e as ApiError); });
    return () => { stale = true; };
  }, [day]);

  async function save() {
    const body = { marks: Object.entries(marks).filter(([, m]) => m.status).map(([staff_id, m]) => ({
      staff_id, status: m.status, time_in: m.time_in || null, time_out: m.time_out || null, note: m.note || null })) };
    try {
      await api(`/staff-attendance?on=${day}`, { method: "PUT", body });
      setSaved(true);
      setError(null);
    } catch (e) {
      setError(e as ApiError);
    }
  }

  const set = (id: string, patch: Partial<Mark>) => { setSaved(false); setMarks((m) => ({ ...m, [id]: { ...m[id], ...patch } })); };
  const marked = Object.values(marks).filter((m) => m.status).length;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("date")}><Input type="date" max={today()} value={day} onChange={(e) => setDay(e.target.value)} /></Field>
        {canTake && (
          <Button kind="plain" onClick={() => setMarks((m) => Object.fromEntries(Object.entries(m).map(([k, v]) => [k, v.status ? v : { ...v, status: "PRESENT" }])))}>
            {t("markRestPresent")}
          </Button>)}
        <p className="text-sm text-slate-600">{t("marked")}: {marked}/{rows.length}</p>
      </div>
      <ErrorBox error={error} />
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm" aria-label={t("staffAttendance")}>
          <thead><tr><th className="py-2 pr-3">{t("staffNo")}</th><th className="pr-3">{t("name")}</th><th className="pr-3">{t("status")}</th><th className="pr-3">{t("timeIn")}</th><th className="pr-3">{t("timeOut")}</th><th>{t("notes")}</th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const m = marks[r.staff_id] ?? { status: "", time_in: "", time_out: "", note: "" };
              return (
                <tr key={r.staff_id} className="border-b border-slate-100 last:border-0">
                  <td className="py-2 pr-3 font-mono text-xs">{r.staff_no}</td>
                  <td className="pr-3">{r.full_name}{r.on_leave && <span className="ml-2"><Badge>{t("onLeave")}</Badge></span>}</td>
                  <td className="pr-3">
                    <Select aria-label={`${t("status")}: ${r.full_name}`} disabled={!canTake} value={m.status} onChange={(e) => set(r.staff_id, { status: e.target.value })}>
                      <option value="">—</option>
                      {STATUSES.map((s) => <option key={s} value={s}>{t(s === "ON_LEAVE" ? "onLeave" : s === "PRESENT" ? "present" : s === "LATE" ? "late" : "absent")}</option>)}
                    </Select>
                  </td>
                  <td className="pr-3"><Input type="time" aria-label={t("timeIn")} disabled={!canTake} value={m.time_in} onChange={(e) => set(r.staff_id, { time_in: e.target.value })} /></td>
                  <td className="pr-3"><Input type="time" aria-label={t("timeOut")} disabled={!canTake} value={m.time_out} onChange={(e) => set(r.staff_id, { time_out: e.target.value })} /></td>
                  <td><Input aria-label={t("notes")} maxLength={200} disabled={!canTake} value={m.note} onChange={(e) => set(r.staff_id, { note: e.target.value })} /></td>
                </tr>);
            })}
          </tbody>
        </table>
      </div>
      {canTake && (
        <div className="flex items-center gap-3">
          <Button onClick={save} disabled={marked === 0}>{t("save")}</Button>
          {saved && <span role="status" className="text-sm text-brand-700">✓ {t("saved")}</span>}
        </div>)}
    </div>
  );
}

function Monthly() {
  const [, t] = useLang();
  const [month, setMonth] = useState(today().slice(0, 7));
  const [rows, setRows] = useState<MonthRow[]>([]);
  useEffect(() => {
    const [y, m] = month.split("-");
    api<MonthRow[]>(`/staff-attendance/monthly?year=${y}&month=${Number(m)}`).then(setRows).catch(() => setRows([]));
  }, [month]);
  return (
    <div className="space-y-3">
      <Field label={t("month")}><Input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="max-w-xs" /></Field>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm" aria-label={t("monthlyTotals")}>
          <thead><tr><th className="py-2 pr-3">{t("name")}</th><th className="pr-3">{t("present")}</th><th className="pr-3">{t("late")}</th><th className="pr-3">{t("absent")}</th><th>{t("onLeave")}</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.staff_id} className="border-b border-slate-100 last:border-0">
                <td className="py-2 pr-3">{r.full_name}</td><td className="pr-3">{r.present}</td><td className="pr-3">{r.late}</td>
                <td className={`pr-3 ${r.absent ? "font-semibold text-red-700" : ""}`}>{r.absent}</td><td>{r.on_leave}</td>
              </tr>))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function StaffAttendance() {
  const [, t] = useLang();
  const [tab, setTab] = useState<"day" | "month">("day");
  return (
    <Card title={t("staffAttendance")}>
      <Tabs label={t("staffAttendance")} value={tab} onChange={setTab} tabs={[["day", t("dailyRegister")], ["month", t("monthlyTotals")]]} />
      {tab === "day" ? <Register /> : <Monthly />}
    </Card>
  );
}
