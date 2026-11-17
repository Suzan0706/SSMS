import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { api, ApiError, download } from "../api";
import { useAuth } from "../auth";
import { clock, todayEat } from "../dates";
import { useLang, Word } from "../i18n";
import { discard, keyOf, mark, Mark, onChange, queued, sync } from "../registerQueue";
import { Badge, Button, Card, ErrorBox, Field, Input, Select, TableTools } from "../ui";
import MonthlySheet from "./MonthlySheet";

interface RegisterStudent {
  student_id: string;
  admission_no: string;
  full_name: string;
  status: Mark | null;
  gate_in_at: string | null;
}

interface Register {
  session_id: string | null;
  session_date: string;
  stream_id: string;
  stream_label: string;
  closed_at: string | null;
  school_day: boolean;
  reason: string | null;
  students: RegisterStudent[];
}

const MARKS: Array<[Mark, string, Word]> = [["PRESENT", "P", "present"], ["ABSENT", "A", "absent"], ["LATE", "L", "late"], ["EXCUSED", "E", "excused"]];

function useQueue() {
  return useSyncExternalStore(onChange, () => JSON.stringify(queued()));
}

function RegisterTab() {
  const [, t] = useLang();
  const [streams, setStreams] = useState<Array<{ stream_id: string; label: string; class_teacher: boolean }>>([]);
  const [streamId, setStreamId] = useState("");
  const [day, setDay] = useState(todayEat());
  const [register, setRegister] = useState<Register | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [online, setOnline] = useState(navigator.onLine);
  const queueJson = useQueue();
  const queue = useMemo(() => JSON.parse(queueJson) as ReturnType<typeof queued>, [queueJson]);

  useEffect(() => {
    api<typeof streams>("/attendance/my-streams").then((s) => { setStreams(s); if (s[0]) setStreamId(s[0].stream_id); })
      .catch((e) => setError(e as ApiError));
  }, []);
  const load = useCallback(async () => {
    if (!streamId) return;
    try {
      setRegister(await api<Register>(`/attendance/register?stream_id=${streamId}&date=${day}`));
      setError(null);
    } catch (e) {
      if ((e as ApiError).error_code !== "OFFLINE") setError(e as ApiError);
    }
  }, [streamId, day]);
  useEffect(() => { load(); }, [load]);

  const flush = useCallback(async () => {
    try {
      if (await sync()) await load();
    } catch {
      /* offline or server unreachable: marks stay queued */
    }
  }, [load]);
  useEffect(() => {
    const up = () => { setOnline(true); flush(); };
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => { window.removeEventListener("online", up); window.removeEventListener("offline", down); };
  }, [flush]);
  useEffect(() => {
    const timer = setTimeout(() => { if (online) flush(); }, 600);
    return () => clearTimeout(timer);
  }, [queueJson, online, flush]);

  const here = (studentId: string) => queue[keyOf({ session_date: day, stream_id: streamId, student_id: studentId })];
  const shown = (s: RegisterStudent) => here(s.student_id)?.status ?? s.status;
  const pending = Object.values(queue).filter((r) => r.state === "pending").length;
  const problems = Object.entries(queue).filter(([, r]) => r.state !== "pending");
  const set = (studentId: string, status: Mark) => mark([{ session_date: day, stream_id: streamId, student_id: studentId, status }]);
  const allPresent = () => mark((register?.students ?? []).filter((s) => !shown(s))
    .map((s) => ({ session_date: day, stream_id: streamId, student_id: s.student_id, status: "PRESENT" as Mark })));
  const counts = MARKS.map(([m]) => (register?.students ?? []).filter((s) => shown(s) === m).length);

  async function close() {
    if (!register?.session_id) return;
    try {
      await api(`/attendance/sessions/${register.session_id}/close`, { method: "POST" });
      await load();
    } catch (e) {
      setError(e as ApiError);
    }
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-3">
        <Select aria-label={t("stream")} value={streamId} onChange={(e) => setStreamId(e.target.value)}>
          {streams.map((s) => <option key={s.stream_id} value={s.stream_id}>{s.label}{s.class_teacher ? " ★" : ""}</option>)}
        </Select>
        <Input type="date" aria-label={t("date")} value={day} max={todayEat()} onChange={(e) => setDay(e.target.value)} />
        <div className="flex items-center gap-2 text-sm" data-testid="sync-state" data-pending={pending}>
          {!online && <Badge>offline</Badge>}
          {pending > 0 ? <span className="text-amber-800">{t("pendingSync")}: {pending}</span> : <span className="text-brand-700">{t("synced")} ✓</span>}
          {pending > 0 && online && <Button kind="plain" onClick={flush}>{t("syncNow")}</Button>}
        </div>
      </div>
      {!online && <p className="text-sm text-amber-800">{t("offlineSaved")}</p>}
      <ErrorBox error={error} />
      {problems.map(([key, r]) => (
        <div key={key} role="alert" className="flex flex-wrap items-center gap-2 rounded bg-red-50 p-2 text-sm">
          <span>{register?.students.find((s) => s.student_id === r.student_id)?.full_name ?? r.student_id} ·{" "}
            {r.state === "conflict" ? `${t("conflict")}: ${r.server?.status}` : r.error_code}</span>
          <Button kind="plain" onClick={() => discard(key)}>{t("useServer")}</Button>
        </div>))}
      {register && !register.school_day && <p className="rounded bg-amber-50 p-2 text-sm">{t("notSchoolDay")} ({register.reason})</p>}
      {register && register.school_day && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Button kind="plain" onClick={allPresent}>{t("allPresent")}</Button>
            {MARKS.map(([m, , w], i) => <Badge key={m}>{t(w)}: {counts[i]}</Badge>)}
            {register.closed_at ? <Badge>{t("registerClosed")} ✓</Badge>
              : register.session_id && pending === 0 && <Button onClick={close}>{t("closeRegister")}</Button>}
          </div>
          <ul className="divide-y text-sm" data-testid="register">
            {register.students.map((s) => (
              <li key={s.student_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span>{s.full_name} <span className="text-xs text-slate-500">{s.admission_no}</span>
                  {s.gate_in_at && <span className="ml-2 text-xs text-brand-700">{t("gateIn")} {clock(s.gate_in_at)}</span>}</span>
                <span className="flex gap-1" role="group" aria-label={s.full_name}>
                  {MARKS.map(([m, letter, w]) => (
                    <button key={m} type="button" title={t(w)} aria-label={`${s.full_name} ${t(w)}`} aria-pressed={shown(s) === m}
                      onClick={() => set(s.student_id, m)}
                      className={`h-9 w-9 rounded border text-sm font-semibold ${shown(s) === m ? "border-brand-700 bg-brand-500 text-white" : "border-slate-300"}`}>
                      {letter}
                    </button>))}
                </span>
              </li>))}
          </ul>
        </>
      )}
    </div>
  );
}

interface ReportRow { student_id: string; admission_no: string; full_name: string; present: number; late: number; absent: number; excused: number; rate_pct: number | null }

function ReportsTab() {
  const [, t] = useLang();
  const [streams, setStreams] = useState<Array<{ id: string; name: string; class_id: string }>>([]);
  const [classes, setClasses] = useState<Array<{ id: string; code: string }>>([]);
  const [streamId, setStreamId] = useState("");
  const monthStart = todayEat().slice(0, 8) + "01";
  const [range, setRange] = useState({ from: monthStart, to: todayEat() });
  const [rows, setRows] = useState<ReportRow[]>([]);
  const [days, setDays] = useState(0);
  const [chronic, setChronic] = useState<Array<{ student_id: string; full_name: string; stream_label: string | null; days_absent: number }>>([]);
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    api<typeof streams>("/streams").then((s) => { setStreams(s); if (s[0]) setStreamId(s[0].id); }).catch(() => undefined);
    api<typeof classes>("/classes").then(setClasses).catch(() => undefined);
    api<typeof chronic>("/attendance/chronic").then(setChronic).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!streamId) return;
    api<{ rows: ReportRow[]; register_days: number }>(`/attendance/reports?stream_id=${streamId}&from=${range.from}&to=${range.to}`)
      .then((r) => { setRows(r.rows); setDays(r.register_days); setError(null); }).catch((e) => setError(e as ApiError));
  }, [streamId, range]);
  const label = (s: { name: string; class_id: string }) => `${classes.find((c) => c.id === s.class_id)?.code ?? ""} ${s.name}`;
  return (
    <div className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-4 sm:items-end">
        <Field label={t("stream")}>
          <Select value={streamId} onChange={(e) => setStreamId(e.target.value)}>
            {streams.map((s) => <option key={s.id} value={s.id}>{label(s)}</option>)}
          </Select>
        </Field>
        <Field label={t("from")}><Input type="date" value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })} /></Field>
        <Field label={t("to")}><Input type="date" value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })} /></Field>
        <Button kind="plain" onClick={() => download(`/attendance/reports?stream_id=${streamId}&from=${range.from}&to=${range.to}&format=xlsx`, `attendance-${range.from}-${range.to}.xlsx`)}>Excel</Button>
        <Button kind="plain" onClick={() => download(`/exports/attendance.csv?stream_id=${streamId}&from=${range.from}&to=${range.to}`, `attendance-${range.from}-${range.to}.csv`)}>CSV</Button>
      </div>
      <ErrorBox error={error} />
      <p className="text-sm text-slate-600">{t("register")}: {days}</p>
      <TableTools><div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b text-xs uppercase text-slate-500">
            <tr><th className="py-2">{t("name")}</th><th>{t("present")}</th><th>{t("late")}</th><th>{t("absent")}</th><th>{t("excused")}</th><th>{t("rate")}</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.student_id} className="border-b last:border-0">
                <td className="py-1.5">{r.full_name}</td><td>{r.present}</td><td>{r.late}</td>
                <td className={r.absent ? "font-semibold text-red-700" : ""}>{r.absent}</td><td>{r.excused}</td>
                <td>{r.rate_pct == null ? "—" : `${r.rate_pct}%`}</td>
              </tr>))}
          </tbody>
        </table>
      </div></TableTools>
      <h3 className="text-sm font-semibold">{t("chronic")}</h3>
      <ul className="divide-y text-sm">
        {chronic.map((c) => <li key={c.student_id} className="flex justify-between py-1"><span>{c.full_name} · {c.stream_label}</span><Badge>{c.days_absent}</Badge></li>)}
        {chronic.length === 0 && <li className="py-2 text-slate-500">{t("noResults")}</li>}
      </ul>
    </div>
  );
}

export default function Attendance() {
  const auth = useAuth();
  const [, t] = useLang();
  const tabs = ([["register", auth.can("attendance.take")], ["reports", auth.can("attendance.read")], ["monthlySheet", auth.can("attendance.read")]] as Array<["register" | "reports" | "monthlySheet", boolean]>)
    .filter(([, ok]) => ok).map(([k]) => k);
  const [tab, setTab] = useState(tabs[0] ?? "register");
  return (
    <Card title={t("attendance")}>
      {tabs.length > 1 && (
        <div className="mb-4 flex gap-2" role="tablist">
          {tabs.map((k) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
              className={`rounded-full px-3 py-1 text-sm ${tab === k ? "bg-brand-500 text-white" : "bg-slate-100"}`}>{t(k)}</button>))}
        </div>
      )}
      {tab === "register" ? <RegisterTab /> : tab === "reports" ? <ReportsTab /> : <MonthlySheet />}
    </Card>
  );
}
