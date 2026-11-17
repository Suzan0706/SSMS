import { useCallback, useEffect, useState } from "react";

import { Named, StreamRow, nameOf, useList } from "../academic";
import { api, ApiError, download, fetchAll } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Input, Select } from "../ui";

const STATUSES = ["UNDER_REVIEW", "REQUIREMENTS_PENDING", "APPROVED", "REJECTED", "CANCELLED"];

interface Row {
  id: string;
  application_no: string;
  status: string;
  class_id: string;
  student_name: string;
  submitted_at: string | null;
}

interface Application {
  id: string;
  application_no: string;
  status: string;
  class_id: string;
  student: { admission_no: string; full_name: string; date_of_birth: string | null };
  checklist: Array<{ requirement_id: string; name_en: string; name_sw: string; is_required: boolean;
                     document_id: string | null; status: string }>;
  documents: Array<{ id: string; file_name: string; comment: string | null }>;
}

export default function Enrolment() {
  const auth = useAuth();
  const [lang, t] = useLang();
  const [status, setStatus] = useState("UNDER_REVIEW");
  const [rows, setRows] = useState<Row[]>([]);
  const [current, setCurrent] = useState<Application | null>(null);
  const [classes] = useList<Named>("/classes");
  const [streams] = useList<StreamRow>("/streams");
  const [streamId, setStreamId] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await fetchAll<Row>(`/enrolment-applications?status=${status}`));
    } catch (e) {
      setError(e as ApiError);
    }
  }, [status]);
  useEffect(() => { load(); }, [load]);

  async function act(promise: Promise<Application>) {
    try {
      setCurrent(await promise);
      setError(null);
      setComment("");
      await load();
    } catch (e) {
      setError(e as ApiError);
    }
  }

  const open = (id: string) => act(api<Application>(`/enrolment-applications/${id}`));
  const classStreams = streams.filter((s) => s.class_id === current?.class_id);
  const className = (id: string) => nameOf(classes.find((c) => c.id === id), lang);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title={t("applications")}>
        <Select aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)} className="mb-3">
          {STATUSES.map((s) => <option key={s}>{s}</option>)}
        </Select>
        <ul className="divide-y text-sm">
          {rows.map((r) => (
            <li key={r.id}>
              <button className="flex w-full justify-between py-2 text-left hover:bg-slate-50" onClick={() => open(r.id)}>
                <span><span className="font-mono text-xs">{r.application_no}</span> {r.student_name}</span>
                <span className="text-slate-500">{className(r.class_id)}</span>
              </button>
            </li>))}
          {rows.length === 0 && <li className="py-4 text-center text-slate-500">{t("noResults")}</li>}
        </ul>
      </Card>

      {current && (
        <Card title={`${current.application_no} · ${current.student.full_name}`} actions={<Badge>{current.status}</Badge>}>
          <ErrorBox error={error} />
          <p className="mb-2 text-sm text-slate-600">{className(current.class_id)} · {current.student.admission_no}</p>
          <h3 className="mb-1 font-semibold">{t("documents")}</h3>
          <ul className="mb-3 divide-y text-sm">
            {current.checklist.map((item) => (
              <li key={item.requirement_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span>{lang === "sw" ? item.name_sw : item.name_en}{item.is_required ? " *" : ""} <Badge>{item.status === "MISSING" ? t("missing") : item.status}</Badge></span>
                {item.document_id && (
                  <span className="flex gap-2">
                    <button className="text-brand-700 underline" onClick={() => download(`/enrolment-documents/${item.document_id}/download`,
                      current.documents.find((d) => d.id === item.document_id)?.file_name ?? "document")}>{t("download")}</button>
                    {auth.can("enrolment.validate") && <>
                      <button className="text-brand-700" onClick={() => act(api(`/enrolment-documents/${item.document_id}`, {
                        method: "PATCH", body: { status: "VALID" } }))}>✓ {t("valid")}</button>
                      <button className="text-red-700" onClick={() => act(api(`/enrolment-documents/${item.document_id}`, {
                        method: "PATCH", body: { status: "INVALID", comment } }))}>✗ {t("invalid")}</button>
                    </>}
                  </span>)}
              </li>))}
          </ul>
          {auth.can("enrolment.validate", "enrolment.decide") && (
            <Input placeholder={`${t("note")} / ${t("reason")}`} value={comment} onChange={(e) => setComment(e.target.value)} className="mb-2" />
          )}
          {auth.can("enrolment.decide") && current.status === "UNDER_REVIEW" && (
            <div className="flex flex-wrap gap-2">
              <Select aria-label={t("stream")} value={streamId} onChange={(e) => setStreamId(e.target.value)} className="w-40">
                <option value="">{t("stream")}</option>
                {classStreams.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.enrolled ?? 0}/{s.capacity})</option>)}
              </Select>
              <Button disabled={!streamId} onClick={() => act(api(`/enrolment-applications/${current.id}/approve`, {
                body: { stream_id: streamId, note: comment || "Approved" } }))}>{t("approve")}</Button>
              <Button kind="plain" disabled={comment.length < 3} onClick={() => act(api(`/enrolment-applications/${current.id}/reject`, {
                body: { reason: comment } }))}>{t("reject")}</Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
