// Lesson (period) register: a teacher marks who was in each lesson they taught on a day (FR-82).
import { useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { useLang, Word } from "../i18n";
import { Button, Card, ErrorBox, Field, Input } from "../ui";

interface Lesson { slot_id: string; time_start: string; time_end: string; subject: string; stream: string; marked: number; expected: number }
interface Row { student_id: string; admission_no: string; full_name: string; status: string | null }

const STATUSES: Array<[string, Word]> = [["PRESENT", "present"], ["LATE", "late"], ["ABSENT", "absent"], ["EXCUSED", "excused"]];
const today = () => new Date().toISOString().slice(0, 10);

export default function Lessons() {
  const [, t] = useLang();
  const [day, setDay] = useState(today());
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [slot, setSlot] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [marks, setMarks] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => setSlot(null), [day]);  // a new day: choose its lesson again
  useEffect(() => {
    api<Lesson[]>(`/attendance/lessons?on=${day}`).then(setLessons).catch((e) => setError(e as ApiError));
  }, [day, version]);
  useEffect(() => {
    setSaved(false);
    if (!slot) return;
    let stale = false;
    api<Row[]>(`/attendance/lessons/${slot}?on=${day}`).then((data) => {
      if (stale) return;
      setRows(data);
      setMarks(Object.fromEntries(data.map((r) => [r.student_id, r.status ?? "PRESENT"])));
      setError(null);
    }).catch((e) => { if (!stale) setError(e as ApiError); });
    return () => { stale = true; };
  }, [slot, day]);

  async function save() {
    try {
      await api(`/attendance/lessons/${slot}?on=${day}`, { method: "PUT", body: { marks: Object.entries(marks).map(([student_id, status]) => ({ student_id, status })) } });
      setSaved(true);
      setError(null);
      setVersion((v) => v + 1);
    } catch (e) {
      setError(e as ApiError);
    }
  }

  const current = lessons.find((l) => l.slot_id === slot);
  return (
    <Card title={t("lessonRegister")}>
      <div className="space-y-4">
        <Field label={t("date")}><Input type="date" max={today()} value={day} onChange={(e) => setDay(e.target.value)} className="max-w-xs" /></Field>
        <ErrorBox error={error} />
        {lessons.length === 0 && <p className="py-4 text-sm text-slate-500">{t("noLessonsThatDay")}</p>}
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" aria-label={t("myLessons")}>
          {lessons.map((l) => (
            <li key={l.slot_id}>
              <button type="button" onClick={() => setSlot(l.slot_id)} aria-pressed={slot === l.slot_id}
                className={`w-full rounded-xl border p-3 text-left transition ${slot === l.slot_id ? "border-brand-500 bg-brand-50" : "border-slate-200 bg-white hover:border-brand-300"}`}>
                <span className="block text-xs font-semibold tabular-nums text-brand-600">{l.time_start.slice(0, 5)}–{l.time_end.slice(0, 5)}</span>
                <span className="block font-semibold">{l.subject} · {l.stream}</span>
                <span className="block text-xs text-slate-500">{l.marked ? `✓ ${l.marked}/${l.expected}` : t("notMarked")}</span>
              </button>
            </li>))}
        </ul>
        {current && (
          <div className="space-y-3">
            <h3 className="text-sm font-semibold">{current.subject} · {current.stream}</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm" aria-label={t("lessonRegister")}>
                <thead><tr><th className="py-2 pr-3">{t("admissionNo")}</th><th className="pr-3">{t("name")}</th><th>{t("status")}</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.student_id} className="border-b border-slate-100 last:border-0">
                      <td className="py-2 pr-3 font-mono text-xs">{r.admission_no}</td>
                      <td className="pr-3">{r.full_name}</td>
                      <td>
                        <div role="radiogroup" aria-label={`${t("status")}: ${r.full_name}`} className="flex flex-wrap gap-1">
                          {STATUSES.map(([value, word]) => (
                            <button key={value} type="button" role="radio" aria-checked={marks[r.student_id] === value}
                              onClick={() => { setSaved(false); setMarks({ ...marks, [r.student_id]: value }); }}
                              className={`rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ${marks[r.student_id] === value
                                ? value === "ABSENT" ? "bg-red-700 text-white ring-red-700" : "bg-brand-500 text-white ring-brand-500"
                                : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50"}`}>
                              {t(word)}
                            </button>))}
                        </div>
                      </td>
                    </tr>))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center gap-3">
              <Button onClick={save} disabled={rows.length === 0}>{t("save")}</Button>
              {saved && <span role="status" className="text-sm text-brand-700">✓ {t("saved")}</span>}
            </div>
          </div>)}
      </div>
    </Card>
  );
}
