import { FormEvent, useEffect, useState } from "react";

import { Named, nameOf, useCurrentTerm, useList } from "../academic";
import { api, ApiError, download } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { Button, Card, ErrorBox, Field, Input, Select } from "../ui";

interface ExamSession {
  id: string;
  name_en: string;
  name_sw: string;
  kind: string;
  start_date: string;
  end_date: string;
}

interface Paper {
  id: string;
  class_id: string;
  subject_id: string;
  room_id: string | null;
  exam_date: string;
  time_start: string;
  time_end: string;
}

/** Candidate numbers, admit cards and the printed timetable of a session (FR-84, FR-85). */
function ExamDocuments({ sessionId }: { sessionId: string }) {
  const auth = useAuth();
  const [lang, t] = useLang();
  const [count, setCount] = useState<{ total: number; numbered: number } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState("");
  const canNumber = auth.can("exams.admit_cards");
  const load = () => api<Array<{ candidate_no: string | null }>>(`/exam-sessions/${sessionId}/candidates`)
    .then((rows) => setCount({ total: rows.length, numbered: rows.filter((r) => r.candidate_no).length })).catch(() => setCount(null));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setNotice(""); load(); }, [sessionId]);
  async function number() {
    try {
      const out = await api<{ numbered: number }>(`/exam-sessions/${sessionId}/candidates`, { body: {} });
      setNotice(`${t("candidatesNumbered")}: ${out.numbered}`);
      setError(null);
      load();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl bg-slate-50 p-3" data-testid="exam-documents">
      {count && <span className="text-sm text-slate-600">{t("candidates")}: {count.numbered}/{count.total}</span>}
      <Button kind="plain" onClick={() => download(`/exam-sessions/${sessionId}/timetable.pdf?lang=${lang}`, "exam-timetable.pdf")}>{t("examTimetablePdf")}</Button>
      {canNumber && <Button kind="plain" onClick={number}>{t("numberCandidates")}</Button>}
      {canNumber && count && count.numbered > 0 && (
        <Button onClick={() => download(`/exam-sessions/${sessionId}/admit-cards.pdf?lang=${lang}`, "admit-cards.pdf").catch((e) => setError(e))}>{t("admitCards")}</Button>)}
      {notice && <span role="status" className="text-sm text-brand-700">✓ {notice}</span>}
      <ErrorBox error={error} />
    </div>
  );
}

export default function Exams() {
  const auth = useAuth();
  const [lang, t] = useLang();
  const { terms, termId, setTermId } = useCurrentTerm();
  const [sessions] = useList<ExamSession>(termId ? `/exam-sessions?term_id=${termId}` : null);
  const [sessionId, setSessionId] = useState("");
  const [papers, reload] = useList<Paper>(sessionId ? `/exams?exam_session_id=${sessionId}` : null);
  const [classes] = useList<Named>("/classes");
  const [subjects] = useList<Named>("/subjects");
  const [rooms] = useList<{ id: string; code: string }>("/rooms");
  const [form, setForm] = useState({ class_id: "", subject_id: "", room_id: "", exam_date: "", time_start: "08:00", time_end: "10:30" });
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => { if (!sessionId && sessions[0]) setSessionId(sessions[0].id); }, [sessions, sessionId]);
  const code = (list: Array<{ id: string; code: string }>, id: string | null) => list.find((x) => x.id === id)?.code ?? "";

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/exams", { body: { ...form, exam_session_id: sessionId, room_id: form.room_id || null } });
      setError(null);
      await reload();
    } catch (err) {
      setError(err as ApiError);
    }
  }

  return (
    <Card title={t("exams")}>
      <div className="mb-3 flex flex-wrap gap-2">
        <Select aria-label={t("term")} className="sm:w-56" value={termId} onChange={(e) => { setTermId(e.target.value); setSessionId(""); }}>
          {terms.map((x) => <option key={x.id} value={x.id}>{nameOf(x, lang)}</option>)}
        </Select>
      <Select aria-label={t("session")} className="sm:w-96" value={sessionId} onChange={(e) => setSessionId(e.target.value)}>
        {sessions.map((s) => <option key={s.id} value={s.id}>{nameOf(s, lang)} ({s.start_date} – {s.end_date})</option>)}
      </Select>
      </div>
      {sessionId && <ExamDocuments sessionId={sessionId} />}
      <table className="mb-4 w-full text-left text-sm">
        <thead className="border-b text-xs uppercase text-slate-500">
          <tr><th className="py-2">{t("date")}</th><th>{t("start")}</th><th>{t("classLabel")}</th><th>{t("subject")}</th><th>{t("room")}</th></tr>
        </thead>
        <tbody>
          {papers.map((p) => (
            <tr key={p.id} className="border-b last:border-0">
              <td className="py-1.5">{p.exam_date}</td><td>{p.time_start.slice(0, 5)}–{p.time_end.slice(0, 5)}</td>
              <td>{code(classes, p.class_id)}</td><td>{code(subjects, p.subject_id)}</td><td>{code(rooms, p.room_id)}</td>
            </tr>))}
        </tbody>
      </table>
      {auth.can("exams.manage") && sessionId && (
        <form className="grid gap-2 sm:grid-cols-7 sm:items-end" onSubmit={submit}>
          <Field label={t("classLabel")}>
            <Select required value={form.class_id} onChange={(e) => setForm({ ...form, class_id: e.target.value })}>
              <option value="">—</option>{classes.map((c) => <option key={c.id} value={c.id}>{c.code}</option>)}
            </Select>
          </Field>
          <Field label={t("subject")}>
            <Select required value={form.subject_id} onChange={(e) => setForm({ ...form, subject_id: e.target.value })}>
              <option value="">—</option>{subjects.map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}
            </Select>
          </Field>
          <Field label={t("room")}>
            <Select value={form.room_id} onChange={(e) => setForm({ ...form, room_id: e.target.value })}>
              <option value="">—</option>{rooms.map((r) => <option key={r.id} value={r.id}>{r.code}</option>)}
            </Select>
          </Field>
          <Field label={t("date")}><Input type="date" required value={form.exam_date} onChange={(e) => setForm({ ...form, exam_date: e.target.value })} /></Field>
          <Field label={t("start")}><Input type="time" value={form.time_start} onChange={(e) => setForm({ ...form, time_start: e.target.value })} /></Field>
          <Field label={t("end")}><Input type="time" value={form.time_end} onChange={(e) => setForm({ ...form, time_end: e.target.value })} /></Field>
          <Button type="submit">{t("add")}</Button>
          <div className="sm:col-span-7"><ErrorBox error={error} /></div>
        </form>
      )}
    </Card>
  );
}
