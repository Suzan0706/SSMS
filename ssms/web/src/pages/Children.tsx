import { FormEvent, useCallback, useEffect, useState } from "react";

import { useList } from "../academic";
import { api, ApiError } from "../api";
import BoardingRequest from "../boarding";
import { clock, todayEat } from "../dates";
import { money, Statement, StatementView } from "../finance";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";
import { AnnouncementList, AnnouncementRow } from "./Announcements";
import { DepositForm } from "./Bank";
import { HomeworkDue, Progress } from "./Progress";
import StudentResults from "./StudentResults";

interface Child {
  student_id: string;
  admission_no: string;
  full_name: string;
  class_code: string | null;
  stream_name: string | null;
  outstanding_tzs: string;
  credit_tzs: string;
  today_status: "PRESENT" | "ABSENT" | "LATE" | "EXCUSED" | null;
  gate_in_at: string | null;
}

interface Month {
  days: Array<{ day: string; status: string | null; gate_in_at: string | null }>;
  present: number;
  late: number;
  absent: number;
  absent_this_week: number;
}

const WORD = { PRESENT: "present", ABSENT: "absent", LATE: "late", EXCUSED: "excused" } as const;
const SYMBOL: Record<string, string> = { PRESENT: "✓", LATE: "L", ABSENT: "✗", EXCUSED: "E" };

export function MonthView({ studentId }: { studentId: string }) {
  const [, t] = useLang();
  const [month, setMonth] = useState<Month | null>(null);
  useEffect(() => {
    const to = todayEat();
    api<Month>(`/students/${studentId}/attendance?from=${to.slice(0, 8)}01&to=${to}`).then(setMonth).catch(() => undefined);
  }, [studentId]);
  if (!month) return null;
  return (
    <div className="space-y-2 text-sm" data-testid="month-attendance">
      {month.absent_this_week >= 3 && (
        <p role="alert" className="rounded bg-red-50 p-2 text-red-800">⚠ {t("absentThisWeek")}: {month.absent_this_week}</p>)}
      <p>{t("present")}: {month.present} · {t("late")}: {month.late} · {t("absent")}: {month.absent}</p>
      <ul className="grid grid-cols-5 gap-1 sm:grid-cols-7">
        {month.days.map((d) => (
          <li key={d.day} title={d.gate_in_at ? `${t("gateIn")} ${clock(d.gate_in_at)}` : undefined}
            className={`rounded border px-1 py-1 text-center ${d.status === "ABSENT" ? "border-red-300 bg-red-50" : "border-slate-200"}`}>
            <span className="block text-xs text-slate-500">{d.day.slice(8)}</span>
            {d.status ? SYMBOL[d.status] : d.gate_in_at ? "✓" : "·"}
          </li>))}
      </ul>
    </div>
  );
}

function PayPrompt({ statement }: { statement: Statement }) {
  const [, t] = useLang();
  const open = statement.invoices.filter((i) => Number(i.balance_tzs) > 0 && i.status !== "CANCELLED");
  const [form, setForm] = useState({ invoice_id: open[0]?.id ?? "", phone: "", channel: "MPESA" });
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  if (!open.length) return null;
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/payments/push", { body: form });
      setError(null);
      setSent(true);
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <form className="grid gap-2 rounded-md bg-slate-50 p-3 sm:grid-cols-4 sm:items-end" onSubmit={submit}>
      <div className="sm:col-span-4"><ErrorBox error={error} /></div>
      <Field label={t("invoices")}>
        <Select value={form.invoice_id} onChange={(e) => setForm({ ...form, invoice_id: e.target.value })}>
          {open.map((i) => <option key={i.id} value={i.id}>{i.invoice_no} · {money(i.balance_tzs)}</option>)}
        </Select>
      </Field>
      <Field label={t("channel")}>
        <Select value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })}>
          {["MPESA", "TIGOPESA", "AIRTEL", "HALOPESA"].map((c) => <option key={c}>{c}</option>)}
        </Select>
      </Field>
      <Field label={t("phone")}><Input type="tel" required placeholder="07XXXXXXXX" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
      <Button type="submit">{t("pay")}</Button>
      {sent && <p className="text-sm text-brand-700 sm:col-span-4">✓ {t("payPrompt")}</p>}
    </form>
  );
}

export default function Children() {
  const [, t] = useLang();
  const [children, reload] = useList<Child>("/me/children");
  const [picked, setPicked] = useState("");
  const [statement, setStatement] = useState<Statement | null>(null);
  const [news, setNews] = useState<AnnouncementRow[]>([]);
  useEffect(() => { api<AnnouncementRow[]>("/announcements").then(setNews).catch(() => undefined); }, []);
  const load =useCallback(async (id: string) => setStatement(await api<Statement>(`/students/${id}/statement`)), []);
  useEffect(() => { if (picked) load(picked); }, [picked, load]);
  useEffect(() => { if (!picked && children.length === 1) setPicked(children[0].student_id); }, [children, picked]);

  return (
    <div className="space-y-4">
      <Card title={t("myChildren")}>
        <ul className="divide-y text-sm" data-testid="children">
          {children.map((c) => (
            <li key={c.student_id}>
              <button className={`flex w-full flex-wrap justify-between gap-2 py-2 text-left ${picked === c.student_id ? "font-semibold" : ""}`}
                onClick={() => setPicked(c.student_id)}>
                <span>{c.full_name} · {c.admission_no} · {c.class_code ?? ""} {c.stream_name ?? ""}</span>
                <span className="flex flex-wrap gap-1">
                  <Badge>{t("today")}: {c.today_status ? t(WORD[c.today_status])
                    : c.gate_in_at ? `${t("gateIn")} ${clock(c.gate_in_at)}` : t("notMarked")}</Badge>
                  {Number(c.outstanding_tzs) > 0 ? <Badge>{t("outstanding")}: TZS {money(c.outstanding_tzs)}</Badge> : <Badge>✓</Badge>}
                </span>
              </button>
            </li>))}
          {children.length === 0 && <li className="py-4 text-center text-slate-500">{t("noResults")}</li>}
        </ul>
      </Card>
      {picked && <Card title={t("results")}><StudentResults key={picked} studentId={picked} /></Card>}
      {picked && <Card title={t("progress")}><Progress key={picked} studentId={picked} /></Card>}
      {picked && <Card title={t("homework")}><HomeworkDue key={picked} studentId={picked} /></Card>}
      {picked && <Card title={t("attendance")}><MonthView key={picked} studentId={picked} /></Card>}
      {picked && <Card title={t("boarding")}><BoardingRequest key={picked} studentId={picked} /></Card>}
      {statement && (
        <Card title={`${t("statement")} — ${statement.full_name}`}>
          <div className="space-y-4">
            <StatementView statement={statement} />
            <PayPrompt key={statement.student_id} statement={statement} />
            <details className="text-sm">
              <summary className="cursor-pointer text-brand-700">{t("reportDeposit")}</summary>
              <div className="pt-2"><DepositForm studentId={statement.student_id} onDone={() => { load(statement.student_id); reload(); }} /></div>
            </details>
          </div>
        </Card>
      )}
      <Card title={t("announcements")}><AnnouncementList items={news} /></Card>
    </div>
  );
}
