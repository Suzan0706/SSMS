import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Named, nameOf, newKey, useCurrentTerm, useList } from "../academic";
import { api, ApiError, download } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Input, Select, TableTools } from "../ui";

interface Problem {
  problem: string;
  admission_no: string | null;
  student: string | null;
  subject: string | null;
  component: string | null;
  teacher: string | null;
  message_sw: string;
  message_en: string;
}

interface ClassResults {
  publication: { id: string; students: number; scheme_version: number; published_at: string };
  items: Array<{
    enrolment_id: string;
    student_id: string;
    admission_no: string;
    full_name: string;
    stream_name: string;
    average_score: string;
    total_points: number | null;
    division: string | null;
    class_position: number;
    results: Array<{ subject_code: string; letter_grade: string; amended: boolean }>;
  }>;
  next_cursor: string | null;
}

interface Amendment {
  id: string;
  status: string;
  admission_no: string;
  student: string;
  subject_code: string;
  old_score: string;
  new_score: string;
  reason: string;
  requested_by_name: string;
}

function Amendments() {
  const [, t] = useLang();
  const [items, reload] = useList<Amendment>("/amendments?status=PENDING");
  const [note, setNote] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  async function decide(id: string, approve: boolean) {
    try {
      await api(`/amendments/${id}/${approve ? "approve" : "reject"}`, { body: { note: note || (approve ? null : "—") } });
      setError(null);
      await reload();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  if (items.length === 0) return null;
  return (
    <Card title={t("amendments")}>
      <ErrorBox error={error} />
      <Input placeholder={t("note")} value={note} onChange={(e) => setNote(e.target.value)} className="mb-2" />
      <ul className="divide-y text-sm">
        {items.map((a) => (
          <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span>{a.admission_no} {a.student} · {a.subject_code}: {a.old_score} → <b>{a.new_score}</b>
              <span className="text-slate-500"> ({a.reason} — {a.requested_by_name})</span></span>
            <span className="flex gap-2">
              <Button onClick={() => decide(a.id, true)}>{t("approve")}</Button>
              <Button kind="plain" onClick={() => decide(a.id, false)}>{t("reject")}</Button>
            </span>
          </li>))}
      </ul>
    </Card>
  );
}

interface RankRow { position: number; admission_no: string; full_name: string; stream: string; score: number | null; grade: string | null }

/** One subject's published results for the class, best first; ties share a position (FR-86). */
function SubjectRanking({ termId, classId }: { termId: string; classId: string }) {
  const [lang, t] = useLang();
  const [subjects] = useList<Named>("/subjects");
  const [subjectId, setSubjectId] = useState("");
  const [rows, setRows] = useState<RankRow[]>([]);
  useEffect(() => {
    if (!subjectId) { setRows([]); return; }
    api<RankRow[]>(`/results/subject-ranking?term_id=${termId}&class_id=${classId}&subject_id=${subjectId}`).then(setRows).catch(() => setRows([]));
  }, [termId, classId, subjectId]);
  return (
    <section className="mt-6 space-y-3">
      <h3 className="text-sm font-semibold">{t("subjectRanking")}</h3>
      <Select aria-label={t("subjectRanking")} value={subjectId} onChange={(e) => setSubjectId(e.target.value)} className="sm:w-80">
        <option value="">—</option>
        {subjects.map((s) => <option key={s.id} value={s.id}>{nameOf(s, lang)}</option>)}
      </Select>
      {subjectId && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm" aria-label={t("subjectRanking")} data-testid="subject-ranking">
            <thead><tr><th className="py-2 pr-3">{t("position")}</th><th className="pr-3">{t("name")}</th><th className="pr-3">{t("classStream")}</th><th className="pr-3">{t("score")}</th><th>{t("grade")}</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.admission_no} className="border-b border-slate-100 last:border-0">
                  <td className="py-1.5 pr-3 font-semibold">{r.position}</td><td className="pr-3">{r.full_name}</td><td className="pr-3">{r.stream}</td>
                  <td className="pr-3 tabular-nums">{r.score == null ? "—" : Number(r.score).toFixed(1)}</td><td>{r.grade ?? "—"}</td>
                </tr>))}
            </tbody>
          </table>
        </div>)}
    </section>
  );
}

export default function Results() {
  const auth = useAuth();
  const [lang, t] = useLang();
  const { terms, termId, setTermId } = useCurrentTerm();
  const [classes] = useList<Named>("/classes");
  const [classId, setClassId] = useState("");
  const [problems, setProblems] = useState<{ ok: boolean; total: number; problems: Problem[] } | null>(null);
  const [results, setResults] = useState<ClassResults | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [publishKey, setPublishKey] = useState(newKey());
  const canPublish = auth.can("results.publish");
  useEffect(() => { if (!classId && classes[0]) setClassId(classes[0].id); }, [classes, classId]);

  const latest = useRef(0);                                           // only the newest term/class choice may show

  const load = useCallback(async () => {
    if (!termId || !classId) return;
    const run = ++latest.current;
    setError(null);
    setProblems(null);
    try {
      const path = `/results?term_id=${termId}&class_id=${classId}&limit=50`;
      const first = await api<ClassResults>(path);
      const items = [...first.items];
      for (let next = first.next_cursor; next;) {                     // a class can fill more than one page
        const page: ClassResults = await api<ClassResults>(`${path}&cursor=${encodeURIComponent(next)}`);
        items.push(...page.items);
        next = page.next_cursor;
      }
      if (run !== latest.current) return;
      setResults({ ...first, items });
    } catch (e) {
      if (run !== latest.current) return;
      setResults(null);
      if ((e as ApiError).status !== 404) setError(e as ApiError);
      else if (canPublish) {
        const check = await api<NonNullable<typeof problems>>(`/results/firewall?term_id=${termId}&class_id=${classId}`);
        if (run === latest.current) setProblems(check);
      }
    }
  }, [termId, classId, canPublish]);
  useEffect(() => { load(); setPublishKey(newKey()); }, [load]);

  async function publish() {
    try {
      await api("/results/publish", { body: { term_id: termId, class_id: classId }, headers: { "Idempotency-Key": publishKey } });
      await load();
    } catch (e) {
      setError(e as ApiError);
    }
  }

  return (
    <div className="space-y-4">
      {auth.can("results.amend_approve") && <Amendments />}
      <Card title={t("results")}>
        <div className="mb-3 grid gap-2 sm:grid-cols-3">
          <Select aria-label={t("term")} value={termId} onChange={(e) => setTermId(e.target.value)}>
            {terms.map((x) => <option key={x.id} value={x.id}>{nameOf(x, lang)}</option>)}
          </Select>
          <Select aria-label={t("classLabel")} value={classId} onChange={(e) => setClassId(e.target.value)}>
            {classes.map((c) => <option key={c.id} value={c.id}>{nameOf(c, lang)}</option>)}
          </Select>
        </div>
        <ErrorBox error={error} />
        {!results && !problems && <p className="text-sm text-slate-500">{t("notPublished")}</p>}
        {problems && (
          <div data-testid="firewall" data-ok={problems.ok}>
            <h3 className="mb-2 font-semibold">{t("firewall")}</h3>
            {problems.ok ? (
              <div className="flex items-center gap-3">
                <p className="text-sm text-brand-700">{t("readyToPublish")}</p>
                <Button onClick={publish}>{t("publish")}</Button>
              </div>
            ) : (
              <table className="w-full text-left text-sm">
                <tbody>
                  {problems.problems.map((p, i) => (
                    <tr key={i} className="border-b last:border-0">
                      <td className="py-1.5 pr-2"><Badge>{lang === "sw" ? p.message_sw : p.message_en}</Badge></td>
                      <td className="pr-2">{p.admission_no} {p.student}</td>
                      <td className="pr-2">{p.subject} {p.component}</td><td className="text-slate-500">{p.teacher}</td>
                    </tr>))}
                </tbody>
              </table>
            )}
          </div>
        )}
        {results && (
          <div data-testid="class-results">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-sm">
              <span>{t("published")} · v{results.publication.scheme_version} · {results.publication.students}</span>
              <Button kind="plain" onClick={() => download(`/results/report-cards?term_id=${termId}&class_id=${classId}`,
                "report-cards.pdf").catch((e) => setError(e))}>{t("classReportCards")}</Button>
            </div>
            <TableTools><div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b text-xs uppercase text-slate-500">
                  <tr><th className="py-2">{t("position")}</th><th>{t("name")}</th><th>{t("average")}</th>
                    <th>{t("division")}</th><th>{t("grade")}</th><th /></tr>
                </thead>
                <tbody>
                  {results.items.map((r) => (
                    <tr key={r.enrolment_id} className="border-b last:border-0">
                      <td className="py-1.5">{r.class_position}</td>
                      <td>{r.full_name} <span className="text-xs text-slate-500">{r.stream_name}</span></td>
                      <td>{Number(r.average_score).toFixed(1)}</td><td>{r.division ?? "—"}</td>
                      <td className="text-xs">{r.results.map((x) => `${x.subject_code} ${x.letter_grade}${x.amended ? "*" : ""}`).join(" · ")}</td>
                      <td><Link className="text-brand-700 underline" to={`/students/${r.student_id}?term=${termId}`}>
                        {t("reportCard")}</Link></td>
                    </tr>))}
                </tbody>
              </table>
            </div></TableTools>
            <SubjectRanking termId={termId} classId={classId} />
          </div>
        )}
      </Card>
    </div>
  );
}
