// Portal pieces shared by the parent and student homes: progress across terms and homework still to do.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { useLang } from "../i18n";
import { Badge } from "../ui";

interface TermRow { term_id: string; term: string; average: string | null; total_points: number | null; division: string | null; position: number | null; out_of: number }
interface HomeworkRow { id: string; student_id: string; subject: string; title: string; due_at: string; overdue: boolean; submission: { score: string | null } | null }

/** Average per published term as one bar each, with position and division beside it (academic progress). */
export function Progress({ studentId }: { studentId: string }) {
  const [, t] = useLang();
  const [rows, setRows] = useState<TermRow[] | null>(null);
  useEffect(() => { api<TermRow[]>(`/students/${studentId}/progress`).then(setRows).catch(() => setRows([])); }, [studentId]);
  if (rows === null) return null;
  if (rows.length === 0) return <p className="py-4 text-sm text-slate-500">{t("noPublishedResults")}</p>;
  return (
    <ul className="space-y-3" data-testid="progress" aria-label={t("progress")}>
      {rows.map((r) => {
        const avg = r.average == null ? null : Number(r.average);
        return (
          <li key={r.term_id}>
            <div className="mb-1 flex flex-wrap justify-between gap-2 text-sm">
              <span className="font-medium">{r.term}</span>
              <span className="text-slate-600">
                {t("average")}: <b className="tabular-nums">{avg == null ? "—" : avg.toFixed(1)}</b>
                {r.position != null && <> · {t("position")}: <b className="tabular-nums">{r.position}/{r.out_of}</b></>}
                {r.division && <> · {t("division")} <b>{r.division}</b></>}
              </span>
            </div>
            <div className="h-2.5 rounded-full bg-slate-100" aria-hidden="true">
              {avg != null && <div className="h-2.5 rounded-full bg-brand-500" style={{ width: `${Math.max(2, Math.min(100, avg))}%` }} />}
            </div>
          </li>);
      })}
    </ul>
  );
}

/** Homework not handed in yet, soonest first, with a link to the full list. */
export function HomeworkDue({ studentId }: { studentId?: string }) {
  const [lang, t] = useLang();
  const [rows, setRows] = useState<HomeworkRow[]>([]);
  useEffect(() => { api<HomeworkRow[]>("/homework/mine").then(setRows).catch(() => setRows([])); }, []);
  const due = rows
    .filter((h) => (!studentId || h.student_id === studentId) && !h.submission)
    .sort((a, b) => a.due_at.localeCompare(b.due_at));
  const when = (iso: string) => new Intl.DateTimeFormat(lang === "sw" ? "sw-TZ" : "en-GB", { weekday: "short", day: "numeric", month: "short" }).format(new Date(iso));
  return (
    <div data-testid="homework-due">
      {due.length === 0 ? <p className="text-sm text-slate-500">{t("noHomework")}</p> : (
        <ul className="divide-y text-sm">
          {due.slice(0, 5).map((h) => (
            <li key={`${h.id}-${h.student_id}`} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
              <span><span className="text-xs font-semibold uppercase text-brand-600">{h.subject}</span> · {h.title}</span>
              {h.overdue ? <Badge>OVERDUE</Badge> : <span className="text-slate-500">{t("dueAt")}: {when(h.due_at)}</span>}
            </li>))}
        </ul>)}
      <Link to="/learning" className="mt-2 inline-block text-sm font-medium text-brand-700 hover:underline">{t("myLearning")} →</Link>
    </div>
  );
}
