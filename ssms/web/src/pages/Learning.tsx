// Students and parents: homework (hand in, see the score and feedback) and study materials (FR-90 .. FR-93).
import { useEffect, useState } from "react";

import { api, ApiError, download } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox } from "../ui";
import { FileUpload, Tabs, Uploaded } from "../widgets";

interface Submission { id: string; submitted_at: string; is_late: boolean; file_name: string | null; body: string | null; score: string | null; feedback: string | null; marked_at: string | null }
interface Item {
  id: string; student_id: string; student_name: string; subject: string; title: string; instructions: string; file_name: string | null;
  max_score: string | null; due_at: string; overdue: boolean; submission: Submission | null;
}
interface Material { id: string; subject: string; title: string; description: string | null; file_name: string | null; link_url: string | null; published_by: string; created_at: string }

function HandIn({ item, onDone }: { item: Item; onDone: () => void }) {
  const [, t] = useLang();
  const [body, setBody] = useState(item.submission?.body ?? "");
  const [file, setFile] = useState<Uploaded | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  async function send() {
    try {
      await api(`/homework/${item.id}/submission`, { method: "PUT", body: { body: body || null, file_id: file?.id ?? null } });
      setError(null);
      onDone();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  return (
    <div className="mt-3 space-y-2 rounded-xl bg-slate-50 p-3">
      <textarea className="control" rows={4} maxLength={8000} aria-label={`${t("yourAnswer")}: ${item.title}`} placeholder={t("yourAnswer")}
        value={body} onChange={(e) => setBody(e.target.value)} />
      <div className="flex flex-wrap items-center gap-3">
        {file ? <span className="text-sm">📎 {file.original_name}</span>
          : <FileUpload purpose="SUBMISSION" accept=".pdf,.docx,.jpg,.jpeg,.png" label={t("attachFile")} onUploaded={setFile} />}
        <Button onClick={send} disabled={!body.trim() && !file}>{item.submission ? t("replaceAnswer") : t("handIn")}</Button>
      </div>
      <ErrorBox error={error} />
    </div>
  );
}

function HomeworkList() {
  const auth = useAuth();
  const [lang, t] = useLang();
  const [items, setItems] = useState<Item[]>([]);
  const [version, setVersion] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const student = auth.can("homework.submit");
  useEffect(() => { api<Item[]>("/homework/mine").then(setItems).catch(() => setItems([])); }, [version]);
  const children = new Set(items.map((i) => i.student_id)).size > 1;
  const when = (iso: string) => new Intl.DateTimeFormat(lang === "sw" ? "sw-TZ" : "en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
  if (items.length === 0) return <p className="py-8 text-center text-sm text-slate-500">{t("noHomework")}</p>;
  return (
    <ul className="space-y-3" data-testid="my-homework">
      {items.map((h) => {
        const sub = h.submission;
        // a first answer may come late; once handed in, it can be replaced only before the deadline and before marking
        const canHandIn = student && !sub?.marked_at && !(sub && new Date(h.due_at) < new Date());
        return (
          <li key={`${h.id}-${h.student_id}`} className="rounded-xl border border-slate-200 p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-brand-600">{h.subject}{children ? ` · ${h.student_name}` : ""}</p>
                <p className="font-semibold">{h.title}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {sub ? <Badge>{sub.is_late ? t("lateSubmission") : t("handedIn")}</Badge> : h.overdue ? <Badge>OVERDUE</Badge> : <Badge>PENDING</Badge>}
                {sub?.score != null && <Badge>{`${sub.score}${h.max_score ? ` / ${h.max_score}` : ""}`}</Badge>}
              </div>
            </div>
            <p className="mt-1 text-sm text-slate-600">{t("dueAt")}: {when(h.due_at)}</p>
            <p className="mt-2 whitespace-pre-wrap text-sm">{h.instructions}</p>
            {h.file_name && <Button kind="plain" className="mt-2" onClick={() => download(`/homework/${h.id}/file`, h.file_name!)}>📎 {h.file_name}</Button>}
            {sub?.feedback && <p className="mt-3 rounded-lg bg-brand-50 p-2 text-sm"><b>{t("feedback")}:</b> {sub.feedback}</p>}
            {sub && !canHandIn && sub.body && <p className="mt-2 whitespace-pre-wrap text-sm text-slate-600"><b>{t("yourAnswer")}:</b> {sub.body}</p>}
            {canHandIn && (open === h.id ? <HandIn item={h} onDone={() => { setOpen(null); setVersion((v) => v + 1); }} />
              : <Button className="mt-3" onClick={() => setOpen(h.id)}>{sub ? t("replaceAnswer") : t("handIn")}</Button>)}
          </li>);
      })}
    </ul>
  );
}

function MaterialList() {
  const [, t] = useLang();
  const [items, setItems] = useState<Material[]>([]);
  useEffect(() => { api<Material[]>("/materials/mine").then(setItems).catch(() => setItems([])); }, []);
  if (items.length === 0) return <p className="py-8 text-center text-sm text-slate-500">{t("noDataYet")}</p>;
  return (
    <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200" data-testid="my-materials">
      {items.map((m) => (
        <li key={m.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
          <div className="min-w-0 flex-1">
            <p className="font-medium">{m.title} <span className="text-xs text-slate-500">· {m.subject}</span></p>
            {m.description && <p className="text-sm text-slate-600">{m.description}</p>}
            <p className="text-xs text-slate-500">{m.published_by} · {m.created_at.slice(0, 10)}</p>
          </div>
          {m.file_name && <Button kind="plain" onClick={() => download(`/materials/${m.id}/file`, m.file_name!)}>{t("download")}</Button>}
          {m.link_url && <a href={m.link_url} target="_blank" rel="noopener noreferrer" className="text-sm text-brand-700 underline">{t("openLink")}</a>}
        </li>))}
    </ul>
  );
}

interface ExamSessionRow { id: string; name: string; start_date: string; end_date: string; candidate_no: string }

/** Admit cards of the sessions in which the student has a candidate number (FR-85). */
function AdmitCards() {
  const [lang, t] = useLang();
  const [sessions, setSessions] = useState<ExamSessionRow[]>([]);
  useEffect(() => { api<ExamSessionRow[]>("/portal/exam-sessions").then(setSessions).catch(() => setSessions([])); }, []);
  if (sessions.length === 0) return <p className="py-8 text-center text-sm text-slate-500">{t("noAdmitCards")}</p>;
  return (
    <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200" data-testid="admit-cards">
      {sessions.map((s) => (
        <li key={s.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
          <div className="min-w-0 flex-1">
            <p className="font-medium">{s.name}</p>
            <p className="text-xs text-slate-500">{s.start_date} – {s.end_date} · {t("candidateNo")}: <b className="font-mono">{s.candidate_no}</b></p>
          </div>
          <Button kind="plain" onClick={() => download(`/portal/admit-card.pdf?exam_session_id=${s.id}&lang=${lang}`, "admit-card.pdf")}>{t("admitCard")}</Button>
        </li>))}
    </ul>
  );
}

export default function Learning() {
  const auth = useAuth();
  const [, t] = useLang();
  const [tab, setTab] = useState<"homework" | "materials" | "exams">("homework");
  const tabs: Array<["homework" | "materials" | "exams", string]> = [["homework", t("homework")], ["materials", t("studyMaterials")]];
  if (auth.can("portal.student")) tabs.push(["exams", t("admitCards")]);
  return (
    <Card title={t("myLearning")}>
      <Tabs label={t("myLearning")} value={tab} onChange={setTab} tabs={tabs} />
      {tab === "homework" ? <HomeworkList /> : tab === "materials" ? <MaterialList /> : <AdmitCards />}
    </Card>
  );
}
