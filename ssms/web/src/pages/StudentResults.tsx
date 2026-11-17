import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { nameOf, useCurrentTerm } from "../academic";
import { api, ApiError, download } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Select } from "../ui";

interface Results {
  admission_no: string;
  summary: { average_score: string; total_points: number | null; division: string | null; class_position: number;
             class_size: number };
  subjects: Array<{ published_result_id: string; subject_code: string; subject_name_en: string; subject_name_sw: string;
                    final_score: string; letter_grade: string; subject_position: number; out_of: number; amended: boolean }>;
  attendance: { present: number; sessions: number };
}

export default function StudentResults({ studentId }: { studentId: string }) {
  const auth = useAuth();
  const [lang, t] = useLang();
  const [params] = useSearchParams();
  const { terms, termId, setTermId } = useCurrentTerm();
  const [results, setResults] = useState<Results | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => { const wanted = params.get("term"); if (wanted) setTermId(wanted); }, [params, setTermId]);

  const load = useCallback(async () => {
    if (!termId) return;
    try {
      setResults(await api<Results>(`/students/${studentId}/results?term_id=${termId}`));
      setError(null);
    } catch (e) {
      setResults(null);
      setError((e as ApiError).status === 404 ? null : (e as ApiError));
    }
  }, [studentId, termId]);
  useEffect(() => { load(); }, [load]);

  async function requestChange(resultId: string, current: string) {
    const score = window.prompt(`${t("newScore")} (0–100)`, current);
    const reason = score ? window.prompt(t("reason")) : null;
    if (!score || !reason) return;
    try {
      await api(`/published-results/${resultId}/amendments`, { body: { new_score: score, reason } });
      setError(null);
    } catch (e) {
      setError(e as ApiError);
    }
  }

  return (
    <Card title={t("results")} actions={
      <Select aria-label={t("term")} value={termId} onChange={(e) => setTermId(e.target.value)} className="w-48">
        {terms.map((x) => <option key={x.id} value={x.id}>{nameOf(x, lang)}</option>)}
      </Select>}>
      <ErrorBox error={error} />
      {!results && !error && <p className="text-sm text-slate-500">{t("notPublished")}</p>}
      {results && (
        <div data-testid="student-results">
          <p className="mb-2 text-sm">
            {t("average")} <b>{Number(results.summary.average_score).toFixed(1)}</b> · {t("division")} <b>{results.summary.division ?? "—"}</b>
            {" "}· {t("position")} {results.summary.class_position}/{results.summary.class_size}
            {" "}· {results.attendance.present}/{results.attendance.sessions}
          </p>
          <table className="mb-3 w-full text-left text-sm">
            <tbody>
              {results.subjects.map((s) => (
                <tr key={s.published_result_id} className="border-b last:border-0">
                  <td className="py-1.5">{lang === "sw" ? s.subject_name_sw : s.subject_name_en} {s.amended && <Badge>*</Badge>}</td>
                  <td>{Number(s.final_score).toFixed(1)}</td><td><b>{s.letter_grade}</b></td>
                  <td>{s.subject_position}/{s.out_of}</td>
                  <td>{auth.can("results.amend_request") && (
                    <button className="text-xs text-brand-700 underline" onClick={() => requestChange(s.published_result_id, s.final_score)}>
                      {t("requestChange")}</button>)}</td>
                </tr>))}
            </tbody>
          </table>
          <Button kind="plain" onClick={() => download(`/students/${studentId}/report-card?term_id=${termId}&lang=${lang}`,
            `report-${results.admission_no}.pdf`).catch((e) => setError(e))}>{t("reportCard")} (PDF)</Button>
        </div>
      )}
    </Card>
  );
}
