// Teachers: publish study materials and set and mark homework for the classes they teach (FR-90 .. FR-93).
import { FormEvent, useEffect, useMemo, useState } from "react";

import { Named, nameOf, useCurrentTerm, useList } from "../academic";
import { api, ApiError, download } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";
import { FileUpload, Modal, Tabs, Uploaded, useConfirm } from "../widgets";
import { useStreams } from "./Students";

interface Assignment { stream_id: string; subject_id: string }
interface Material { id: string; subject: string; title: string; description: string | null; streams: string[]; file_name: string | null; link_url: string | null; published_by: string; created_at: string; mine: boolean }
interface HomeworkRow { id: string; subject: string; title: string; instructions: string; file_name: string | null; max_score: string | null; due_at: string; streams: string[]; set_by: string; expected: number; submitted: number; marked: number; mine: boolean }
interface Submission { id: string; submitted_at: string; is_late: boolean; file_name: string | null; body: string | null; score: string | null; feedback: string | null }
interface RosterRow { student_id: string; admission_no: string; full_name: string; stream: string; submission: Submission | null }

/** The subjects and streams this person may target: their teaching assignments, or everything for the office. */
function useTargets() {
  const auth = useAuth();
  const { year } = useCurrentTerm();
  const office = auth.can("academics.configure");
  const [subjects] = useList<Named>("/subjects");
  const streams = useStreams();
  const [mine] = useList<Assignment>(!office && year ? `/teaching-assignments?academic_year_id=${year.id}&mine=true` : null);
  return useMemo(() => {
    const subjectIds = office ? new Set(subjects.map((s) => s.id)) : new Set(mine.map((a) => a.subject_id));
    return {
      subjects: subjects.filter((s) => subjectIds.has(s.id)),
      streamsFor: (subjectId: string) => office ? streams
        : streams.filter((s) => mine.some((a) => a.subject_id === subjectId && a.stream_id === s.id)),
    };
  }, [office, subjects, streams, mine]);
}

function Targets({ subjectId, setSubjectId, picked, setPicked }: {
  subjectId: string; setSubjectId: (id: string) => void; picked: string[]; setPicked: (ids: string[]) => void;
}) {
  const [lang, t] = useLang();
  const { subjects, streamsFor } = useTargets();
  const streams = streamsFor(subjectId);
  return (
    <>
      <Field label={t("subject")}>
        <Select required aria-label={t("subject")} value={subjectId} onChange={(e) => { setSubjectId(e.target.value); setPicked([]); }}>
          <option value="">—</option>
          {subjects.map((s) => <option key={s.id} value={s.id}>{nameOf(s, lang)}</option>)}
        </Select>
      </Field>
      <fieldset className="sm:col-span-2">
        <legend className="mb-1.5 text-sm font-medium text-slate-700">{t("classes")}</legend>
        <div className="flex flex-wrap gap-3 text-sm">
          {streams.map((s) => (
            <label key={s.id} className="flex items-center gap-1.5">
              <input type="checkbox" checked={picked.includes(s.id)}
                onChange={(e) => setPicked(e.target.checked ? [...picked, s.id] : picked.filter((x) => x !== s.id))} />
              {s.label}
            </label>))}
          {subjectId && streams.length === 0 && <span className="text-slate-500">{t("noClassesForSubject")}</span>}
        </div>
      </fieldset>
    </>
  );
}

function Materials() {
  const [, t] = useLang();
  const [rows, setRows] = useState<Material[]>([]);
  const [version, setVersion] = useState(0);
  const [subjectId, setSubjectId] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [f, setF] = useState({ title: "", description: "", link_url: "" });
  const [file, setFile] = useState<Uploaded | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [confirm, confirmDialog] = useConfirm();
  useEffect(() => { api<Material[]>("/materials").then(setRows).catch((e) => setError(e as ApiError)); }, [version]);

  async function publish(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/materials", { body: { subject_id: subjectId, stream_ids: picked, title: f.title, description: f.description || null,
        ...(file ? { file_id: file.id } : { link_url: f.link_url }) } });
      setF({ title: "", description: "", link_url: "" });
      setFile(null);
      setPicked([]);
      setError(null);
      setVersion((v) => v + 1);
    } catch (err) {
      setError(err as ApiError);
    }
  }
  async function remove(m: Material) {
    if (await confirm(m.title, t("delete"))) {
      await api(`/materials/${m.id}`, { method: "DELETE" });
      setVersion((v) => v + 1);
    }
  }
  return (
    <div className="space-y-5">
      {confirmDialog}
      <form onSubmit={publish} className="grid gap-3 rounded-xl bg-slate-50 p-4 sm:grid-cols-2">
        <Targets subjectId={subjectId} setSubjectId={setSubjectId} picked={picked} setPicked={setPicked} />
        <Field label={t("title")}><Input required minLength={2} maxLength={150} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        <Field label={t("description")}><Input maxLength={1000} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <div className="space-y-2">
          {file ? <p className="text-sm">📎 {file.original_name} <button type="button" className="text-red-700 underline" onClick={() => setFile(null)}>{t("delete")}</button></p>
            : <FileUpload purpose="STUDY_MATERIAL" accept=".pdf,.docx,.pptx,.xlsx,.jpg,.jpeg,.png,.mp3,.mp4" label={t("attachFile")} onUploaded={setFile} />}
        </div>
        {!file && <Field label={t("orLink")}><Input type="url" placeholder="https://" value={f.link_url} onChange={(e) => setF({ ...f, link_url: e.target.value })} /></Field>}
        <div className="sm:col-span-2"><ErrorBox error={error} /><Button type="submit" className="mt-2" disabled={!subjectId || picked.length === 0}>{t("publish")}</Button></div>
      </form>
      <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200" aria-label={t("studyMaterials")}>
        {rows.map((m) => (
          <li key={m.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
            <div className="min-w-0 flex-1">
              <p className="font-medium">{m.title} <span className="text-xs text-slate-500">· {m.subject} · {m.streams.join(", ")}</span></p>
              {m.description && <p className="text-sm text-slate-600">{m.description}</p>}
              <p className="text-xs text-slate-500">{m.published_by} · {m.created_at.slice(0, 10)}</p>
            </div>
            {m.file_name && <Button kind="plain" onClick={() => download(`/materials/${m.id}/file`, m.file_name!)}>{m.file_name}</Button>}
            {m.link_url && <a href={m.link_url} target="_blank" rel="noopener noreferrer" className="text-sm text-brand-700 underline">{t("openLink")}</a>}
            {m.mine && <Button kind="plain" onClick={() => remove(m)}>{t("delete")}</Button>}
          </li>))}
        {rows.length === 0 && <li className="px-4 py-6 text-center text-sm text-slate-500">{t("noDataYet")}</li>}
      </ul>
    </div>
  );
}

function Marking({ homework, onClose }: { homework: HomeworkRow; onClose: () => void }) {
  const [, t] = useLang();
  const [rows, setRows] = useState<RosterRow[]>([]);
  const [edits, setEdits] = useState<Record<string, { score: string; feedback: string }>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const load = () => api<RosterRow[]>(`/homework/${homework.id}/submissions`).then(setRows).catch((e) => setError(e as ApiError));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [homework.id]);
  async function save(sub: Submission) {
    const edit = edits[sub.id] ?? { score: sub.score ?? "", feedback: sub.feedback ?? "" };
    try {
      await api(`/homework/submissions/${sub.id}`, { method: "PATCH", body: { score: edit.score || null, feedback: edit.feedback || null } });
      setError(null);
      load();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  return (
    <Modal open title={`${homework.title} · ${homework.submitted}/${homework.expected}`} onClose={onClose}
      footer={<Button kind="plain" onClick={onClose}>{t("close")}</Button>}>
      <ErrorBox error={error} />
      <ul className="max-h-[60vh] divide-y divide-slate-100 overflow-y-auto" aria-label={t("submissions")}>
        {rows.map((r) => {
          const sub = r.submission;
          const edit = sub ? edits[sub.id] ?? { score: sub.score ?? "", feedback: sub.feedback ?? "" } : null;
          return (
            <li key={r.student_id} className="space-y-2 py-3">
              <p className="flex flex-wrap items-center gap-2 font-medium">{r.full_name} <span className="text-xs text-slate-500">{r.stream}</span>
                {!sub && <Badge>{t("notSubmitted")}</Badge>}
                {sub?.is_late && <Badge>{t("lateSubmission")}</Badge>}
                {sub?.score != null && <Badge>{`${sub.score}${homework.max_score ? ` / ${homework.max_score}` : ""}`}</Badge>}
              </p>
              {sub && (
                <>
                  {sub.body && <p className="whitespace-pre-wrap rounded-lg bg-slate-50 p-2 text-sm">{sub.body}</p>}
                  {sub.file_name && <Button kind="plain" onClick={() => download(`/homework/submissions/${sub.id}/file`, sub.file_name!)}>{sub.file_name}</Button>}
                  <div className="flex flex-wrap items-end gap-2">
                    {homework.max_score && (
                      <Field label={t("score")}><Input aria-label={`${t("score")}: ${r.full_name}`} type="number" step="0.5" min={0} max={Number(homework.max_score)} className="w-24"
                        value={edit!.score} onChange={(e) => setEdits({ ...edits, [sub.id]: { ...edit!, score: e.target.value } })} /></Field>)}
                    <div className="min-w-[12rem] flex-1">
                      <Field label={t("feedback")}><Input aria-label={`${t("feedback")}: ${r.full_name}`} maxLength={2000} value={edit!.feedback}
                        onChange={(e) => setEdits({ ...edits, [sub.id]: { ...edit!, feedback: e.target.value } })} /></Field>
                    </div>
                    <Button onClick={() => save(sub)}>{t("save")}</Button>
                  </div>
                </>)}
            </li>);
        })}
      </ul>
    </Modal>
  );
}

function HomeworkTab() {
  const auth = useAuth();
  const [, t] = useLang();
  const [rows, setRows] = useState<HomeworkRow[]>([]);
  const [version, setVersion] = useState(0);
  const [subjectId, setSubjectId] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [f, setF] = useState({ title: "", instructions: "", max_score: "", due_at: "", notify_parents: false });
  const [file, setFile] = useState<Uploaded | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [marking, setMarking] = useState<HomeworkRow | null>(null);
  const [everyone, setEveryone] = useState(false);
  const [notice, setNotice] = useState("");
  useEffect(() => { api<HomeworkRow[]>(`/homework${everyone ? "?everyone=true" : ""}`).then(setRows).catch((e) => setError(e as ApiError)); }, [version, everyone]);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      const out = await api<{ sms_queued: number }>("/homework", { body: {
        subject_id: subjectId, stream_ids: picked, title: f.title, instructions: f.instructions, file_id: file?.id ?? null,
        max_score: f.max_score || null, due_at: new Date(f.due_at).toISOString(), notify_parents: f.notify_parents } });
      setF({ title: "", instructions: "", max_score: "", due_at: "", notify_parents: false });
      setFile(null);
      setPicked([]);
      setError(null);
      setVersion((v) => v + 1);
      setNotice(f.notify_parents ? `${t("homeworkSet")} · ${t("smsQueued")}: ${out.sms_queued}` : t("homeworkSet"));
    } catch (err) {
      setError(err as ApiError);
    }
  }
  const now = new Date().toISOString();
  return (
    <div className="space-y-5">
      <form onSubmit={create} className="grid gap-3 rounded-xl bg-slate-50 p-4 sm:grid-cols-2">
        <Targets subjectId={subjectId} setSubjectId={setSubjectId} picked={picked} setPicked={setPicked} />
        <Field label={t("title")}><Input required minLength={2} maxLength={150} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        <Field label={t("dueAt")}><Input type="datetime-local" required value={f.due_at} onChange={(e) => setF({ ...f, due_at: e.target.value })} /></Field>
        <div className="sm:col-span-2">
          <Field label={t("instructions")}><textarea className="control" rows={3} required minLength={3} maxLength={4000} value={f.instructions} onChange={(e) => setF({ ...f, instructions: e.target.value })} /></Field>
        </div>
        <Field label={t("maxScore")}><Input type="number" min={1} step="0.5" value={f.max_score} onChange={(e) => setF({ ...f, max_score: e.target.value })} /></Field>
        <div className="space-y-2">
          {file ? <p className="text-sm">📎 {file.original_name} <button type="button" className="text-red-700 underline" onClick={() => setFile(null)}>{t("delete")}</button></p>
            : <FileUpload purpose="HOMEWORK" accept=".pdf,.docx,.pptx,.xlsx,.jpg,.jpeg,.png" label={t("attachFile")} onUploaded={setFile} />}
        </div>
        <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={f.notify_parents} onChange={(e) => setF({ ...f, notify_parents: e.target.checked })} />{t("smsParents")}</label>
        <div className="sm:col-span-2"><ErrorBox error={error} /><Button type="submit" className="mt-2" disabled={!subjectId || picked.length === 0}>{t("setHomework")}</Button>
          {notice && <span role="status" className="ml-3 text-sm text-brand-700">✓ {notice}</span>}</div>
      </form>
      {auth.can("academics.configure") && (
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={everyone} onChange={(e) => setEveryone(e.target.checked)} />{t("allTeachers")}</label>)}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm" aria-label={t("homework")}>
          <thead><tr><th className="py-2 pr-3">{t("title")}</th><th className="pr-3">{t("subject")}</th><th className="pr-3">{t("classes")}</th><th className="pr-3">{t("dueAt")}</th><th className="pr-3">{t("submitted")}</th><th /></tr></thead>
          <tbody>
            {rows.map((h) => (
              <tr key={h.id} className="border-b border-slate-100 last:border-0">
                <td className="py-2 pr-3 font-medium">{h.title}</td><td className="pr-3">{h.subject}</td><td className="pr-3">{h.streams.join(", ")}</td>
                <td className={`whitespace-nowrap pr-3 ${h.due_at < now ? "text-slate-500" : ""}`}>{new Date(h.due_at).toLocaleString()}</td>
                <td className="pr-3 tabular-nums">{h.submitted}/{h.expected}{h.marked ? ` · ✓ ${h.marked}` : ""}</td>
                <td><Button kind="plain" onClick={() => setMarking(h)}>{t("markWork")}</Button></td>
              </tr>))}
          </tbody>
        </table>
      </div>
      {marking && <Marking homework={marking} onClose={() => { setMarking(null); setVersion((v) => v + 1); }} />}
    </div>
  );
}

export default function Teaching() {
  const auth = useAuth();
  const [, t] = useLang();
  const tabs: Array<["homework" | "materials", string]> = [];
  if (auth.can("homework.manage", "academics.configure")) tabs.push(["homework", t("homework")]);
  if (auth.can("materials.publish", "academics.configure")) tabs.push(["materials", t("studyMaterials")]);
  const [tab, setTab] = useState(tabs[0]?.[0] ?? "homework");
  return (
    <Card title={t("teachingResources")}>
      <Tabs label={t("teachingResources")} tabs={tabs} value={tab} onChange={setTab} />
      {tab === "homework" ? <HomeworkTab /> : <Materials />}
    </Card>
  );
}
