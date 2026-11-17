// Monthly attendance sheet: days × students from the class register, with totals; prints on A4 landscape (FR-83).
import { useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { useLang } from "../i18n";
import { ErrorBox, Field, Input, Select } from "../ui";
import { useStreams } from "./Students";

interface Row { student_id: string; admission_no: string; full_name: string; marks: Record<string, string>; present: number; absent: number; late: number; excused: number }
interface Sheet { stream: string; year: number; month: number; days: string[]; rows: Row[] }

const TONE: Record<string, string> = { A: "font-bold text-red-700", L: "text-accent-700", E: "text-slate-500", P: "text-brand-700" };

export default function MonthlySheet() {
  const [, t] = useLang();
  const streams = useStreams();
  const [streamId, setStreamId] = useState("");
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => { if (!streamId && streams[0]) setStreamId(streams[0].id); }, [streams, streamId]);
  useEffect(() => {
    if (!streamId) return;
    const [y, m] = month.split("-");
    api<Sheet>(`/attendance/monthly-sheet?stream_id=${streamId}&year=${y}&month=${Number(m)}`)
      .then((s) => { setSheet(s); setError(null); }).catch((e) => setError(e as ApiError));
  }, [streamId, month]);

  return (
    <div className="space-y-3">
      <style>{"@media print { @page { size: A4 landscape; } }"}</style>
      <div className="flex flex-wrap gap-3 print:hidden">
        <Field label={t("classStream")}>
          <Select value={streamId} onChange={(e) => setStreamId(e.target.value)}>{streams.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</Select>
        </Field>
        <Field label={t("month")}><Input type="month" value={month} onChange={(e) => setMonth(e.target.value)} /></Field>
      </div>
      <ErrorBox error={error} />
      {sheet && (
        <>
          <p className="text-sm font-semibold">{t("attendance")} · {sheet.stream} · {month}</p>
          {sheet.days.length === 0 ? <p className="py-6 text-center text-sm text-slate-500">{t("noRegistersThatMonth")}</p> : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs" aria-label={t("monthlySheet")} data-testid="monthly-sheet">
                <thead>
                  <tr>
                    <th className="py-2 pr-2">{t("name")}</th>
                    {sheet.days.map((d) => <th key={d} className="px-1 text-center">{Number(d.slice(8))}</th>)}
                    <th className="px-1 text-center">P</th><th className="px-1 text-center">L</th><th className="px-1 text-center">A</th><th className="px-1 text-center">E</th>
                  </tr>
                </thead>
                <tbody>
                  {sheet.rows.map((r) => (
                    <tr key={r.student_id} className="border-b border-slate-100 last:border-0">
                      <td className="whitespace-nowrap py-1.5 pr-2">{r.full_name}</td>
                      {sheet.days.map((d) => <td key={d} className={`px-1 text-center ${TONE[r.marks[d]] ?? ""}`}>{r.marks[d] ?? "·"}</td>)}
                      <td className="px-1 text-center font-semibold">{r.present}</td><td className="px-1 text-center">{r.late}</td>
                      <td className={`px-1 text-center ${r.absent ? "font-bold text-red-700" : ""}`}>{r.absent}</td><td className="px-1 text-center">{r.excused}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>)}
          <p className="text-xs text-slate-500">P {t("present")} · L {t("late")} · A {t("absent")} · E {t("excused")}</p>
        </>)}
    </div>
  );
}
