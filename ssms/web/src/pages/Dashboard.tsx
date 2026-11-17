import { useEffect, useState } from "react";

import { api } from "../api";
import { useAuth } from "../auth";
import { chosenRole } from "../chosenRole";
import { money } from "../finance";
import { useLang, Word } from "../i18n";
import { Icon } from "../icons";
import { Badge, Card } from "../ui";

type Role = "admin" | "bursar" | "teacher" | "librarian" | "receptionist";
// Chosen by permission, not role name, so a custom role still gets the right dashboard (FR-73).
const ROLES: Array<[Role, string]> = [["admin", "settings.update"], ["bursar", "finance.read"], ["teacher", "attendance.take"],
  ["librarian", "library.manage"], ["receptionist", "enrolment.manage"]];
interface Data { role: Role; tiles: Record<string, unknown>; series: Record<string, Array<Record<string, unknown>>>; generated_at: string }

function Tile({ label, value, note, icon, alert, testId }: { label: string; value: string; note?: string; icon: string; alert?: boolean; testId?: string }) {
  return (
    <div className="flex flex-col rounded-xl bg-slate-50 p-3 sm:p-4" data-testid={testId}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-slate-600 sm:text-sm">{label}</p>
        <span className={`hidden rounded-lg p-1.5 sm:block ${alert ? "bg-accent-100 text-accent-700" : "bg-white text-brand-600"}`}><Icon name={alert ? "alert" : icon} className="h-4 w-4" /></span>
      </div>
      <p className="mt-auto break-words pt-2 text-xl font-semibold tracking-tight tabular-nums sm:text-2xl">{value}</p>
      <p className="mt-1 min-h-[1rem] text-xs text-slate-500">{note}</p>
    </div>
  );
}

function Empty() {
  const [, t] = useLang();
  return <p className="rounded-lg bg-slate-50 py-8 text-center text-sm text-slate-500">{t("noDataYet")}</p>;
}

/** Horizontal bars with the value written beside each bar (readable without colour, at 360 px). */
function Bars({ rows, label }: { rows: Array<{ name: string; value: number; text: string }>; label: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <figure aria-label={label}>
      <figcaption className="mb-3 text-sm font-semibold">{label}</figcaption>
      {rows.every((r) => r.value === 0) ? <Empty /> : (
        <ul className="space-y-2 text-xs">
          {rows.map((r) => (
            <li key={r.name} title={`${r.name}: ${r.text}`} className="grid grid-cols-[4.5rem_1fr_auto] items-center gap-3">
              <span className="truncate text-slate-600">{r.name}</span>
              <span className="h-2.5 rounded-full bg-slate-100">
                {r.value > 0 && <span className="block h-full rounded-full bg-[#4f46e5]" style={{ width: `${Math.max(2, (r.value / max) * 100)}%` }} />}
              </span>
              <span className="font-medium tabular-nums">{r.text}</span>
            </li>))}
        </ul>
      )}
    </figure>
  );
}

/** Change over time: one thin column per day, on one baseline. Only the best day is labelled; hover shows each day. */
function Columns({ rows, label }: { rows: Array<{ name: string; value: number; text: string }>; label: string }) {
  const max = Math.max(0, ...rows.map((r) => r.value));
  const peak = rows.find((r) => r.value === max);
  return (
    <figure aria-label={label}>
      <figcaption className="mb-3 text-sm font-semibold">{label}</figcaption>
      {max === 0 ? <Empty /> : (
        <>
          <p className="mb-2 text-xs text-slate-600">{peak!.name}: <span className="font-semibold tabular-nums text-slate-900">TZS {peak!.text}</span></p>
          <ul className="flex h-28 items-end gap-1 border-b border-slate-200">
            {rows.map((r) => (
              <li key={r.name} title={`${r.name}: TZS ${r.text}`} className="group flex h-full flex-1 items-end rounded-t hover:bg-slate-100">
                {r.value > 0 && <span className="block w-full rounded-t bg-[#4f46e5] group-hover:bg-brand-700" style={{ height: `${Math.max(3, (r.value / max) * 100)}%` }} />}
                <span className="sr-only">{r.name}: TZS {r.text}</span>
              </li>))}
          </ul>
          <p className="mt-1 flex justify-between text-xs text-slate-500" aria-hidden="true"><span>{rows[0].name}</span><span>{rows[rows.length - 1].name}</span></p>
        </>
      )}
    </figure>
  );
}

/** Two groups in one bar on one scale, with a legend and the numbers written out. */
function SplitBars({ rows, label, first, second }: { rows: Array<{ name: string; a: number; b: number }>; label: string; first: string; second: string }) {
  const max = Math.max(1, ...rows.map((r) => r.a + r.b));
  return (
    <figure aria-label={label}>
      <figcaption className="mb-1 text-sm font-semibold">{label}</figcaption>
      <p className="mb-3 flex gap-4 text-xs text-slate-600">
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-[#4f46e5]" />{first}</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-[#d97706]" />{second}</span>
      </p>
      {rows.length === 0 ? <Empty /> : (
        <ul className="space-y-2 text-xs">
          {rows.map((r) => (
            <li key={r.name} title={`${r.name}: ${first} ${r.a}, ${second} ${r.b}`} className="grid grid-cols-[4.5rem_1fr_auto] items-center gap-3">
              <span className="truncate text-slate-600">{r.name}</span>
              <span className="flex h-2.5 gap-0.5 rounded-full bg-slate-100">
                {r.a > 0 && <span className="rounded-l-full bg-[#4f46e5]" style={{ width: `${(r.a / max) * 100}%` }} />}
                {r.b > 0 && <span className="rounded-r-full bg-[#d97706]" style={{ width: `${(r.b / max) * 100}%` }} />}
              </span>
              <span className="font-medium tabular-nums">{first} {r.a} · {second} {r.b}</span>
            </li>))}
        </ul>
      )}
    </figure>
  );
}

const pct = (v: unknown) => (v == null ? "—" : `${v}%`);

export default function Dashboard() {
  const auth = useAuth();
  const [, t] = useLang();
  // The role picked on the front page comes first when the account has it (an admin who also teaches, say).
  const picked = ({ school_admin: "admin", bursar: "bursar", teacher: "teacher", librarian: "librarian", receptionist: "receptionist" } as Record<string, Role>)[chosenRole() ?? ""];
  const preferred = ROLES.find(([r, permission]) => r === picked && auth.can(permission));
  const role: Role | null = (preferred ?? ROLES.find(([, permission]) => auth.can(permission)))?.[0] ?? null;
  const [data, setData] = useState<Data | null>(null);
  useEffect(() => { if (role) api<Data>(`/dashboards/${role}`).then(setData).catch(() => undefined); }, [role]);
  if (!role || !data) return null;
  const tl = data.tiles as Record<string, never>;
  const s = data.series;
  const money30 = (s.collections_30_days ?? []).slice(-14).map((d) => ({
    name: String(d.day).slice(5), value: Number(d.amount_tzs), text: money(String(d.amount_tzs)) }));

  return (
    <Card title={t("dashboard")}>
      <div className="space-y-4" data-testid={`dashboard-${role}`}>
        {role === "admin" && (
          <>
            <div className="grid grid-cols-2 gap-2 sm:gap-3 xl:grid-cols-4">
              <Tile icon="students" label={t("studentsActive")} value={String(tl.students_active)} testId="tile-students" />
              <Tile icon="staff" label={t("staffActive")} value={String(tl.staff_active)} />
              <Tile icon="attendance" label={t("attendanceToday")} value={pct(tl.attendance_today_pct)} note={`${t("registersTaken")}: ${tl.registers_taken}/${tl.streams}`} />
              <Tile icon="people" alert={Number(tl.chronic_absentees) > 0} label={t("chronic")} value={String(tl.chronic_absentees)} />
              <Tile icon="money" label={t("collected")} value={`TZS ${money(tl.collected_tzs)}`} note={`${t("collectionRate")}: ${pct(tl.collection_rate_pct)}`} />
              <Tile icon="money" label={t("outstanding")} value={`TZS ${money(tl.outstanding_tzs)}`} note={`${t("studentsOwing")}: ${tl.students_owing}`} />
              <Tile icon="sms" label={t("smsCredit")} value={String(tl.sms_credit)} />
              <Tile icon="check" alert={Object.values(tl.pending as Record<string, number>).some(Boolean)} label={t("pendingDecisions")} value={String(Object.values(tl.pending as Record<string, number>).reduce((a, b) => a + b, 0))}
                note={Object.entries(tl.pending as Record<string, number>).filter(([, n]) => n).map(([k, n]) => `${t(k as Word)} ${n}`).join(" · ")} />
            </div>
            <div className="grid gap-6 pt-2 lg:grid-cols-2">
              <SplitBars label={t("enrolmentByClass")} first={t("male")} second={t("female")} rows={(s.enrolment_by_class ?? []).map((c) => ({
                name: String(c.class), a: Number(c.M), b: Number(c.F) }))} />
              <Columns label={t("collections14")} rows={money30} />
            </div>
          </>
        )}
        {role === "bursar" && (
          <>
            <div className="grid grid-cols-2 gap-2 sm:gap-3 xl:grid-cols-4">
              <Tile icon="fees" label={t("billed")} value={`TZS ${money(tl.billed_tzs)}`} />
              <Tile icon="money" label={t("collected")} value={`TZS ${money(tl.collected_tzs)}`} note={pct(tl.collection_rate_pct)} />
              <Tile icon="money" label={t("outstanding")} value={`TZS ${money(tl.outstanding_tzs)}`} note={`${t("studentsOwing")}: ${tl.students_owing}`} />
              <Tile icon="fees" alert={Number(tl.overdue_invoices) > 0} label={t("overdueInvoices")} value={String(tl.overdue_invoices)} />
            </div>
            <div className="grid gap-6 pt-2 lg:grid-cols-3">
              <Columns label={t("collections14")} rows={money30} />
              <Bars label={t("channel")} rows={(s.collections_by_channel ?? []).map((c) => ({
                name: String(c.channel), value: Number(c.amount_tzs), text: money(String(c.amount_tzs)) }))} />
              <Bars label={t("aging")} rows={(s.aging ?? []).map((a) => ({
                name: String(a.bucket), value: Number(a.amount_tzs), text: money(String(a.amount_tzs)) }))} />
            </div>
          </>
        )}
        {role === "teacher" && (
          <>
            <div className="grid grid-cols-2 gap-2 sm:gap-3 xl:grid-cols-3">
              <Tile icon="attendance" label={t("registersTaken")} value={`${tl.registers_taken}/${tl.my_streams}`} note={tl.school_day ? "" : t("notSchoolDay")} />
              <Tile icon="discipline" label={t("openCases")} value={String(tl.open_discipline)} />
            </div>
            <ul className="divide-y text-sm">
              {(s.registers_today ?? []).map((r) => (
                <li key={String(r.stream_id)} className="flex justify-between py-1.5">
                  <span>{String(r.label)}{r.class_teacher ? " ★" : ""}</span>
                  <span>{Number(r.marked) ? `✓ ${r.marked} · ${t("absent")} ${r.absent}` : t("notMarked")}</span>
                </li>))}
            </ul>
          </>
        )}
        {role === "librarian" && (
          <>
            <div className="grid grid-cols-2 gap-2 sm:gap-3 xl:grid-cols-4">
              <Tile icon="library" label={t("bookTitles")} value={String(tl.titles)} note={`${t("copies")}: ${tl.copies}`} />
              <Tile icon="library" label={t("onLoan")} value={String(tl.on_loan)} />
              <Tile icon="timetable" label={t("dueThisWeek")} value={String(tl.due_this_week)} />
              <Tile icon="library" alert={Number(tl.overdue) > 0} label={t("overdueLoans")} value={String(tl.overdue)} />
            </div>
            <h3 className="text-sm font-semibold">{t("overdueLoans")}</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm" aria-label={t("overdueLoans")}>
                <thead><tr><th className="py-2 pr-3">{t("bookTitle")}</th><th className="pr-3">{t("borrower")}</th><th className="pr-3">{t("dueDate")}</th><th>{t("daysLate")}</th></tr></thead>
                <tbody>
                  {(s.overdue_loans ?? []).map((l, i) => (
                    <tr key={i} className="border-b border-slate-100 last:border-0">
                      <td className="py-2 pr-3">{String(l.title)}</td><td className="pr-3">{String(l.borrower)}</td>
                      <td className="pr-3">{String(l.due_date)}</td><td className="font-semibold text-red-700">{String(l.days_late)}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>
          </>
        )}
        {role === "receptionist" && (
          <>
            <div className="grid grid-cols-2 gap-2 sm:gap-3 xl:grid-cols-4">
              <Tile icon="enrolment" alert={Number(tl.waiting) > 0} label={t("applicationsWaiting")} value={String(tl.waiting)} />
              <Tile icon="enrolment" label={t("underReview")} value={String(tl.under_review)} />
              <Tile icon="check" label={t("approvedApplications")} value={String(tl.approved)} />
              <Tile icon="students" label={t("admittedThisMonth")} value={String(tl.admitted_this_month)} />
            </div>
            <h3 className="text-sm font-semibold">{t("latestApplications")}</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm" aria-label={t("latestApplications")}>
                <thead><tr><th className="py-2 pr-3">#</th><th className="pr-3">{t("name")}</th><th className="pr-3">{t("classStream")}</th><th className="pr-3">{t("status")}</th><th>{t("date")}</th></tr></thead>
                <tbody>
                  {(s.latest_applications ?? []).map((a) => (
                    <tr key={String(a.application_no)} className="border-b border-slate-100 last:border-0">
                      <td className="py-2 pr-3 font-mono text-xs">{String(a.application_no)}</td><td className="pr-3">{String(a.name)}</td>
                      <td className="pr-3">{String(a.class)}</td><td className="pr-3"><Badge>{String(a.status)}</Badge></td><td>{String(a.created_at)}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>
          </>
        )}
        <p className="text-right text-xs text-slate-400">{data.generated_at.slice(11, 16)}</p>
      </div>
    </Card>
  );
}
