import { useEffect, useState } from "react";

import { DAYS } from "../academic";
import { api, download } from "../api";
import BoardingRequest from "../boarding";
import { clock } from "../dates";
import { money, Statement, StatementView } from "../finance";
import { useLang } from "../i18n";
import { Badge, Button, Card } from "../ui";
import { AnnouncementList, AnnouncementRow } from "./Announcements";
import { MonthView } from "./Children";
import { HomeworkDue, Progress } from "./Progress";
import StudentResults from "./StudentResults";

interface Home { student_id: string; full_name: string; class_code: string | null; stream_name: string | null;
  outstanding_tzs: string; today_status: string | null; gate_in_at: string | null }
interface Club { id: string; activity_name: string; role: string }
interface Loan { id: string; title: string; due_date: string; returned_at: string | null; overdue: boolean }
interface Lesson { day_of_week: number; time_start: string; time_end: string; subject_code: string; subject_en: string;
  subject_sw: string; teacher: string; room: string }

export default function StudentHome() {
  const [lang, t] = useLang();
  const [home, setHome] = useState<Home | null>(null);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [statement, setStatement] = useState<Statement | null>(null);
  const [news, setNews] = useState<AnnouncementRow[]>([]);
  const [clubs, setClubs] = useState<Club[]>([]);
  const [loans, setLoans] = useState<Loan[]>([]);
  const [noCard, setNoCard] = useState(false);
  useEffect(() => {
    api<Home>("/me/student").then((h) => {
      setHome(h);
      api<Statement>(`/students/${h.student_id}/statement`).then(setStatement).catch(() => undefined);
    }).catch(() => undefined);
    api<Lesson[]>("/me/timetable").then(setLessons).catch(() => undefined);
    api<AnnouncementRow[]>("/announcements").then(setNews).catch(() => undefined);
    api<Club[]>("/me/activities").then(setClubs).catch(() => undefined);
    api<Loan[]>("/me/loans").then((l) => setLoans(l.filter((x) => !x.returned_at))).catch(() => undefined);
  }, []);
  const weekday = ((new Date().getDay() + 6) % 7) + 1;                // 1 = Monday, as in the timetable
  const today = lessons.filter((l) => l.day_of_week === weekday);
  if (!home) return null;
  return (
    <div className="space-y-4">
      <Card title={`${home.full_name} · ${home.class_code ?? ""} ${home.stream_name ?? ""}`}>
        <p className="flex flex-wrap gap-2 text-sm">
          <Badge>{t("today")}: {home.today_status ?? t("notMarked")}{home.gate_in_at ? ` · ${t("gateIn")} ${clock(home.gate_in_at)}` : ""}</Badge>
          <Badge>{t("outstanding")}: TZS {money(home.outstanding_tzs)}</Badge>
        </p>
        <p className="mt-3"><Button kind="plain" onClick={() => download(`/portal/id-card.pdf?lang=${lang}`, "id-card.pdf").catch(() => setNoCard(true))}>{t("myIdCard")}</Button>
          {noCard && <span className="ml-2 text-sm text-slate-500">{t("noResults")}</span>}</p>
      </Card>
      <Card title={`${t("myTimetable")} · ${DAYS[lang][weekday - 1] ?? ""}`}>
        <ul className="divide-y text-sm" data-testid="today-lessons">
          {today.map((l) => (
            <li key={`${l.time_start}${l.subject_code}`} className="flex justify-between py-1.5">
              <span>{l.time_start.slice(0, 5)}–{l.time_end.slice(0, 5)} · {lang === "sw" ? l.subject_sw : l.subject_en}</span>
              <span className="text-slate-500">{l.teacher} · {l.room}</span>
            </li>))}
          {today.length === 0 && <li className="py-2 text-slate-500">{t("noResults")}</li>}
        </ul>
      </Card>
      <Card title={t("homework")}><HomeworkDue /></Card>
      <Card title={t("results")}><StudentResults studentId={home.student_id} /></Card>
      <Card title={t("progress")}><Progress studentId={home.student_id} /></Card>
      <Card title={t("attendance")}><MonthView studentId={home.student_id} /></Card>
      <Card title={`${t("clubs")} · ${t("loans")}`}>
        <ul className="divide-y text-sm" data-testid="my-clubs">
          {clubs.map((c) => <li key={c.id} className="py-1">{c.activity_name} {c.role !== "MEMBER" && <Badge>{c.role}</Badge>}</li>)}
          {loans.map((l) => <li key={l.id} className={`py-1 ${l.overdue ? "text-red-700" : ""}`}>📚 {l.title} · {l.due_date}</li>)}
          {clubs.length + loans.length === 0 && <li className="py-1 text-slate-500">{t("noResults")}</li>}
        </ul>
      </Card>
      <Card title={t("boarding")}><BoardingRequest /></Card>
      {statement && <Card title={t("statement")}><StatementView statement={statement} /></Card>}
      <Card title={t("announcements")}><AnnouncementList items={news} /></Card>
    </div>
  );
}
