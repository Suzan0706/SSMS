import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { StreamRow, nameOf, useCurrentTerm, useList, Named } from "../academic";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { enqueue, keyOf, onChange, queued, resolve, sync } from "../offline";
import { Badge, Button, Card, ErrorBox, Select } from "../ui";

interface Assignment {
  stream_id: string;
  subject_id: string;
  subject_code: string;
  staff_name: string;
}

interface Sheet {
  locked: boolean;
  components: Array<{ id: string; code: string; max_score: string; weight: string }>;
  students: Array<{
    enrolment_id: string;
    admission_no: string;
    full_name: string;
    marks: Record<string, { score: string | null; is_absent: boolean; version: number; locked: boolean }>;
  }>;
}

const ABSENT = ["ABS", "X", "AB"];

function useQueue() {
  return useSyncExternalStore(onChange, () => JSON.stringify(queued()));
}

export default function Marks() {
  const auth = useAuth();
  const [lang, t] = useLang();
  const { year, terms, termId, setTermId } = useCurrentTerm();
  const all = auth.can("results.publish");
  const [assignments] = useList<Assignment>(year ? `/teaching-assignments?academic_year_id=${year.id}${all ? "" : "&mine=true"}` : null);
  const [streams] = useList<StreamRow>("/streams");
  const [classes] = useList<Named>("/classes");
  const [choice, setChoice] = useState("");
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [online, setOnline] = useState(navigator.onLine);
  const queueJson = useQueue();
  const queue = useMemo(() => JSON.parse(queueJson) as ReturnType<typeof queued>, [queueJson]);

  useEffect(() => { if (!choice && assignments[0]) setChoice(`${assignments[0].stream_id}|${assignments[0].subject_id}`); }, [assignments, choice]);
  const [streamId, subjectId] = choice.split("|");
  const streamLabel = (id: string) => {
    const s = streams.find((x) => x.id === id);
    return s ? `${classes.find((c) => c.id === s.class_id)?.code ?? ""} ${s.name}` : "";
  };

  const load = useCallback(async () => {
    if (!termId || !streamId || !subjectId) return;
    try {
      setSheet(await api<Sheet>(`/marks/sheet?term_id=${termId}&stream_id=${streamId}&subject_id=${subjectId}`));
      setError(null);
    } catch (e) {
      setError(e as ApiError);
    }
  }, [termId, streamId, subjectId]);
  useEffect(() => { load(); }, [load]);

  const flush = useCallback(async () => {
    try {
      const saved = await sync();
      if (Object.keys(saved).length) await load();
    } catch {
      /* offline or server unreachable: items stay queued */
    }
  }, [load]);

  useEffect(() => {
    const up = () => { setOnline(true); flush(); };
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => { window.removeEventListener("online", up); window.removeEventListener("offline", down); };
  }, [flush]);
  useEffect(() => {                                     // autosync shortly after typing stops
    const timer = setTimeout(() => { if (online) flush(); }, 800);
    return () => clearTimeout(timer);
  }, [queueJson, online, flush]);

  function edit(enrolmentId: string, componentId: string, raw: string) {
    const server = sheet?.students.find((s) => s.enrolment_id === enrolmentId)?.marks[componentId];
    const base = { enrolment_id: enrolmentId, subject_id: subjectId, component_id: componentId };
    const value = raw.trim().toUpperCase();
    if (value === "" && !server) return;
    const absent = ABSENT.includes(value);
    enqueue({ ...base, score: absent || value === "" ? null : value.replace(",", "."), is_absent: absent,
              version: queue[keyOf(base)]?.version ?? server?.version ?? 0 });
  }

  const pending = Object.values(queue).filter((m) => m.status === "pending").length;
  const conflicts = Object.entries(queue).filter(([, m]) => m.status === "conflict");

  return (
    <Card title={t("marks")}>
      <div className="mb-3 grid gap-2 sm:grid-cols-3">
        <Select aria-label={t("term")} value={termId} onChange={(e) => setTermId(e.target.value)}>
          {terms.map((x) => <option key={x.id} value={x.id}>{nameOf(x, lang)}</option>)}
        </Select>
        <Select aria-label={t("myClasses")} value={choice} onChange={(e) => setChoice(e.target.value)}>
          {assignments.map((a) => (
            <option key={`${a.stream_id}|${a.subject_id}`} value={`${a.stream_id}|${a.subject_id}`}>
              {streamLabel(a.stream_id)} · {a.subject_code}{all ? ` · ${a.staff_name}` : ""}
            </option>))}
        </Select>
        <div className="flex items-center gap-2 text-sm" data-testid="sync-state" data-pending={pending}>
          {!online && <Badge>offline</Badge>}
          {pending > 0 ? <span className="text-amber-800">{t("pendingSync")}: {pending}</span> : <span className="text-brand-700">{t("synced")} ✓</span>}
          {pending > 0 && online && <Button kind="plain" onClick={flush}>{t("syncNow")}</Button>}
        </div>
      </div>
      {!online && <p className="mb-2 text-sm text-amber-800">{t("offlineSaved")}</p>}
      <ErrorBox error={error} />
      {conflicts.map(([key, m]) => (
        <div key={key} className="mb-2 flex flex-wrap items-center gap-2 rounded bg-red-50 p-2 text-sm" role="alert">
          <span>{t("conflict")}: {sheet?.students.find((s) => s.enrolment_id === m.enrolment_id)?.full_name} ·
            {" "}{m.score ?? "ABS"} ↔ {m.server?.is_absent ? "ABS" : m.server?.score}</span>
          <Button kind="plain" onClick={() => resolve(key, true)}>{t("useMine")}</Button>
          <Button kind="plain" onClick={() => resolve(key, false)}>{t("useServer")}</Button>
        </div>))}
      {sheet?.locked && <p className="mb-2 text-sm text-slate-600">🔒 {t("locked")}</p>}
      {sheet && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b text-xs uppercase text-slate-500">
              <tr><th className="py-2">{t("name")}</th>
                {sheet.components.map((c) => <th key={c.id}>{c.code} <span className="normal-case">/{Number(c.max_score)}</span></th>)}</tr>
            </thead>
            <tbody>
              {sheet.students.map((s) => (
                <tr key={s.enrolment_id} className="border-b last:border-0">
                  <td className="py-1.5 pr-2"><span className="font-mono text-xs">{s.admission_no}</span> {s.full_name}</td>
                  {sheet.components.map((c) => {
                    const key = keyOf({ enrolment_id: s.enrolment_id, subject_id: subjectId, component_id: c.id });
                    const local = queue[key];
                    const server = s.marks[c.id];
                    const value = local ? (local.is_absent ? "ABS" : local.score ?? "")
                      : server ? (server.is_absent ? "ABS" : server.score ? String(Number(server.score)) : "") : "";
                    const state = local ? (local.status === "pending" ? "●" : "⚠") : server ? "✓" : "";
                    return (
                      <td key={c.id} className="pr-2">
                        <input aria-label={`${s.admission_no} ${c.code}`} defaultValue={value} key={`${key}:${value}`}
                          disabled={sheet.locked || server?.locked} inputMode="decimal" maxLength={6}
                          className="w-20 rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-100"
                          onBlur={(e) => { if (e.target.value !== value) edit(s.enrolment_id, c.id, e.target.value); }} />
                        <span className={`ml-1 text-xs ${state === "⚠" ? "text-red-700" : "text-slate-400"}`}>{state}</span>
                      </td>);
                  })}
                </tr>))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
