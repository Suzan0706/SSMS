import { FormEvent, useEffect, useMemo, useState } from "react";

import { DAYS, Named, nameOf, PERIODS, StreamRow, useCurrentTerm, useList } from "../academic";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";

interface Slot {
  id?: string;
  stream_id: string;
  subject_id: string;
  staff_id: string;
  room_id: string;
  day_of_week: number;
  time_start: string;
  time_end: string;
}

interface Assignment {
  stream_id: string;
  subject_id: string;
  subject_code: string;
  staff_id: string;
  staff_name: string;
}

interface CheckResult {
  ok: boolean;
  conflicts: Array<{ kind: string; time_start: string; time_end: string }>;
  problems: Array<{ code: string; detail: string }>;
  free_periods: Array<{ time_start: string; time_end: string }>;
}

const hhmm = (t: string) => t.slice(0, 5);

export default function Timetable() {
  const auth = useAuth();
  const [lang, t] = useLang();
  const canEdit = auth.can("timetable.manage");
  const { year, terms, termId, setTermId } = useCurrentTerm();
  const [classes] = useList<Named>("/classes");
  const [streams] = useList<StreamRow>("/streams");
  const [subjects] = useList<Named>("/subjects");
  const [rooms] = useList<{ id: string; code: string }>("/rooms");
  const [streamId, setStreamId] = useState("");
  const [assignments] = useList<Assignment>(year && streamId ? `/teaching-assignments?academic_year_id=${year.id}&stream_id=${streamId}` : null);
  const [slots, reload] = useList<Slot>(termId && streamId ? `/timetable?term_id=${termId}&stream_id=${streamId}` : null);
  const [draft, setDraft] = useState({ subject_id: "", room_id: "", day_of_week: 1, time_start: "08:00", time_end: "08:40" });
  const [checked, setChecked] = useState<CheckResult | null>(null);
  const [generated, setGenerated] = useState<{ placed: Slot[]; unplaced: unknown[] } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => { if (!streamId && streams[0]) setStreamId(streams[0].id); }, [streams, streamId]);
  const classCode = new Map(classes.map((c) => [c.id, c.code]));
  const subjectCode = new Map(subjects.map((s) => [s.id, s.code]));
  const roomCode = new Map(rooms.map((r) => [r.id, r.code]));
  const assignment = assignments.find((a) => a.subject_id === draft.subject_id);
  const body = useMemo(() => assignment && draft.room_id ? {
    term_id: termId, stream_id: streamId, staff_id: assignment.staff_id, ...draft,
  } : null, [assignment, draft, termId, streamId]);

  useEffect(() => {                                       // live check while the form changes
    if (!canEdit || !body) { setChecked(null); return; }
    const timer = setTimeout(() => api<CheckResult>("/timetable/check", { body }).then(setChecked).catch(() => setChecked(null)), 300);
    return () => clearTimeout(timer);
  }, [body, canEdit]);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!body) return;
    try {
      await api("/timetable/slots", { body });
      setError(null);
      await reload();
    } catch (err) {
      setError(err as ApiError);
    }
  }

  async function generate(persist: boolean) {
    try {
      const out = await api<{ placed: Slot[]; unplaced: unknown[] }>("/timetable/generate", {
        body: { term_id: termId, stream_ids: [streamId], replace: true, persist } });
      setGenerated(persist ? null : out);
      if (persist) await reload();
    } catch (err) {
      setError(err as ApiError);
    }
  }

  const shown = generated ? generated.placed : slots;
  const cell = (day: number, start: string) => shown.filter((s) => s.day_of_week === day && hhmm(s.time_start) <= start && start < hhmm(s.time_end));

  return (
    <div className="space-y-4">
      <Card title={t("timetable")}>
        <div className="mb-3 grid gap-2 sm:grid-cols-3">
          <Select aria-label={t("term")} value={termId} onChange={(e) => setTermId(e.target.value)}>
            {terms.map((x) => <option key={x.id} value={x.id}>{nameOf(x, lang)}</option>)}
          </Select>
          <Select aria-label={t("stream")} value={streamId} onChange={(e) => { setStreamId(e.target.value); setGenerated(null); }}>
            {streams.map((s) => <option key={s.id} value={s.id}>{classCode.get(s.class_id)} {s.name}</option>)}
          </Select>
          {canEdit && <Button kind="plain" onClick={() => generate(false)}>{t("generate")}</Button>}
        </div>
        {generated && (
          <div className="mb-3 flex flex-wrap items-center gap-3 rounded-md bg-amber-50 p-2 text-sm" data-testid="draft">
            <span>{t("draftReady")}: {t("placed")} {generated.placed.length}, {t("unplaced")} {generated.unplaced.length}</span>
            <Button onClick={() => generate(true)}>{t("saveTimetable")}</Button>
            <span className="text-xs text-amber-800">{t("replaceExisting")}</span>
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] table-fixed text-xs">
            <thead><tr><th className="w-16" />{[1, 2, 3, 4, 5, 6].map((d) => <th key={d} className="py-1">{DAYS[lang][d]}</th>)}</tr></thead>
            <tbody>
              {PERIODS.map(([start, end]) => (
                <tr key={start} className="border-t">
                  <td className="py-1 pr-1 text-slate-500">{start}–{end}</td>
                  {[1, 2, 3, 4, 5, 6].map((d) => (
                    <td key={d} className="p-0.5 align-top">
                      {cell(d, start).map((s, i) => (
                        <div key={s.id ?? i} className="rounded bg-brand-50 px-1 py-0.5">
                          <b>{subjectCode.get(s.subject_id)}</b> <span className="text-slate-500">{roomCode.get(s.room_id)}</span>
                        </div>))}
                    </td>))}
                </tr>))}
            </tbody>
          </table>
        </div>
      </Card>

      {canEdit && (
        <Card title={t("add")}>
          <form className="grid gap-2 sm:grid-cols-6 sm:items-end" onSubmit={save}>
            <Field label={t("subject")}>
              <Select name="subject_id" value={draft.subject_id} onChange={(e) => setDraft({ ...draft, subject_id: e.target.value })}>
                <option value="">—</option>
                {assignments.map((a) => <option key={a.subject_id} value={a.subject_id}>{a.subject_code} · {a.staff_name}</option>)}
              </Select>
            </Field>
            <Field label={t("room")}>
              <Select name="room_id" value={draft.room_id} onChange={(e) => setDraft({ ...draft, room_id: e.target.value })}>
                <option value="">—</option>
                {rooms.map((r) => <option key={r.id} value={r.id}>{r.code}</option>)}
              </Select>
            </Field>
            <Field label={t("day")}>
              <Select name="day_of_week" value={draft.day_of_week} onChange={(e) => setDraft({ ...draft, day_of_week: Number(e.target.value) })}>
                {[1, 2, 3, 4, 5, 6].map((d) => <option key={d} value={d}>{DAYS[lang][d]}</option>)}
              </Select>
            </Field>
            <Field label={t("start")}><Input type="time" value={draft.time_start} onChange={(e) => setDraft({ ...draft, time_start: e.target.value })} /></Field>
            <Field label={t("end")}><Input type="time" value={draft.time_end} onChange={(e) => setDraft({ ...draft, time_end: e.target.value })} /></Field>
            <Button type="submit" disabled={!checked?.ok}>{t("save")}</Button>
          </form>
          <ErrorBox error={error} />
          {checked && (
            <div className="mt-3 grid gap-3 text-sm sm:grid-cols-3" data-testid="check">
              <div><p className="font-semibold">{t("clashes")}</p>
                {checked.conflicts.map((c, i) => <p key={i} className="text-red-700">{c.kind} {hhmm(c.time_start)}–{hhmm(c.time_end)}</p>)}
                {checked.conflicts.length === 0 && <Badge>0</Badge>}</div>
              <div><p className="font-semibold">{t("problems")}</p>
                {checked.problems.map((p) => <p key={p.code} className="text-amber-800">{p.detail}</p>)}
                {checked.problems.length === 0 && <Badge>0</Badge>}</div>
              <div><p className="font-semibold">{t("freePeriods")}</p>
                <div className="flex flex-wrap gap-1">{checked.free_periods.map((f) => (
                  <button key={f.time_start} type="button" className="rounded bg-slate-100 px-1.5 text-xs"
                    onClick={() => setDraft({ ...draft, time_start: hhmm(f.time_start), time_end: hhmm(f.time_end) })}>
                    {hhmm(f.time_start)}</button>))}</div></div>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
