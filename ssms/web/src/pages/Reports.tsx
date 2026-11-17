import { FormEvent, useEffect, useState } from "react";

import { Named, nameOf, newKey, useCurrentTerm, useList } from "../academic";
import { api, ApiError, download } from "../api";
import { useAuth } from "../auth";
import { useLang, Word } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";

const TYPES = ["enrolment", "attendance", "results", "fees", "staff", "student-status", "transactions"] as const;
const LABEL: Record<(typeof TYPES)[number], Word> = {
  enrolment: "enrolment", attendance: "attendance", results: "results", fees: "fees", staff: "staff",
  "student-status": "studentStatus", transactions: "transactions",
};
interface Preview { columns: string[]; rows: Array<Record<string, string>>; total: number }
interface Job { id: string; status: string; processed_items: number }

function useJob(): [Job | null, (j: Job) => void] {
  const [job, setJob] = useState<Job | null>(null);
  useEffect(() => {
    if (!job || job.status === "SUCCEEDED" || job.status === "FAILED") return;
    const timer = setTimeout(() => api<Job>(`/jobs/${job.id}`).then(setJob).catch(() => undefined), 1000);
    return () => clearTimeout(timer);
  }, [job]);
  return [job, setJob];
}

function JobBadge({ job, name }: { job: Job | null; name: string }) {
  const [, t] = useLang();
  if (!job) return null;
  return (
    <span className="flex items-center gap-2 text-sm" data-testid="export-job" data-status={job.status}>
      <Badge>{job.status}</Badge>
      {job.status === "SUCCEEDED" && (
        <button className="text-brand-700 underline" onClick={() => download(`/jobs/${job.id}/files/result`, name)}>{t("download")}</button>)}
    </span>
  );
}

function ReportTab() {
  const auth = useAuth();
  const [lang, t] = useLang();
  const { terms, termId, setTermId } = useCurrentTerm();
  const [classes] = useList<Named>("/classes");
  const [type, setType] = useState<(typeof TYPES)[number]>("enrolment");
  const [filters, setFilters] = useState({ class_id: "", date_from: "", date_to: "", status: "" });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [job, setJob] = useJob();
  const [format, setFormat] = useState("xlsx");
  const query = () => {
    const q = new URLSearchParams();
    if (termId && ["results", "fees", "attendance"].includes(type)) q.set("term_id", termId);
    Object.entries(filters).forEach(([k, v]) => { if (v) q.set(k, v); });
    return q;
  };
  async function show(e?: FormEvent) {
    e?.preventDefault();
    try {
      setPreview(await api<Preview>(`/reports/${type}?${query()}`));
      setError(null);
    } catch (err) {
      setPreview(null);
      setError(err as ApiError);
    }
  }
  async function exportAll() {
    const body: Record<string, string> = { format };
    query().forEach((v, k) => { body[k] = v; });
    try {
      setJob(await api<Job>(`/reports/${type}/export`, { body, headers: { "Idempotency-Key": newKey() } }));
      setError(null);
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <div className="space-y-3">
      <form className="grid gap-2 sm:grid-cols-6 sm:items-end" onSubmit={show}>
        <Field label={t("reports")}>
          <Select value={type} onChange={(e) => { setType(e.target.value as typeof type); setPreview(null); }}>
            {TYPES.map((x) => <option key={x} value={x}>{t(LABEL[x])}</option>)}
          </Select>
        </Field>
        <Field label={t("term")}>
          <Select value={termId} onChange={(e) => setTermId(e.target.value)}>
            {terms.map((x) => <option key={x.id} value={x.id}>{nameOf(x, lang)}</option>)}
          </Select>
        </Field>
        <Field label={t("classLabel")}>
          <Select value={filters.class_id} onChange={(e) => setFilters({ ...filters, class_id: e.target.value })}>
            <option value="">—</option>{classes.map((c) => <option key={c.id} value={c.id}>{c.code}</option>)}
          </Select>
        </Field>
        <Field label={t("from")}><Input type="date" value={filters.date_from} onChange={(e) => setFilters({ ...filters, date_from: e.target.value })} /></Field>
        <Field label={t("to")}><Input type="date" value={filters.date_to} onChange={(e) => setFilters({ ...filters, date_to: e.target.value })} /></Field>
        <Button type="submit">{t("preview")}</Button>
      </form>
      <ErrorBox error={error} />
      {preview && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span data-testid="report-total">{t("rowsTotal")}: {preview.total}{preview.total > preview.rows.length ? ` (${preview.rows.length})` : ""}</span>
            {auth.can("reports.export") && (
              <span className="flex items-center gap-2">
                <Select aria-label={t("format")} value={format} onChange={(e) => setFormat(e.target.value)} className="w-24">
                  <option value="xlsx">Excel</option><option value="csv">CSV</option><option value="pdf">PDF</option>
                </Select>
                <Button kind="plain" onClick={exportAll}>{t("exportAll")}</Button>
                <JobBadge job={job} name={`${type}.${format}`} />
              </span>
            )}
          </div>
          <div className="max-h-[60vh] overflow-auto">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-white"><tr>{preview.columns.map((c) => <th key={c} className="border-b px-1 py-1.5">{c}</th>)}</tr></thead>
              <tbody>
                {preview.rows.map((r, i) => (
                  <tr key={i} className="border-b last:border-0">{preview.columns.map((c) => <td key={c} className="px-1 py-1">{r[c]}</td>)}</tr>))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function ComplianceTab() {
  const [, t] = useLang();
  const [years] = useList<{ id: string; name: string; is_current: boolean }>("/academic-years");
  const [yearId, setYearId] = useState("");
  const [picked, setPicked] = useState<string[]>(["ENROLMENT", "ATTENDANCE", "RESULTS", "STAFF"]);
  const [job, setJob] = useJob();
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => { if (!yearId) setYearId(years.find((y) => y.is_current)?.id ?? ""); }, [years, yearId]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      setJob(await api<Job>("/compliance-exports", { body: { templates: picked, academic_year_id: yearId, format: "xlsx" },
        headers: { "Idempotency-Key": newKey() } }));
      setError(null);
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <form className="space-y-3 text-sm" onSubmit={submit}>
      <ErrorBox error={error} />
      <p className="text-xs text-slate-500">{t("complianceNote")}</p>
      <Field label={t("year")}>
        <Select value={yearId} onChange={(e) => setYearId(e.target.value)} className="max-w-xs">
          {years.map((y) => <option key={y.id} value={y.id}>{y.name}</option>)}
        </Select>
      </Field>
      <div className="flex flex-wrap gap-3">
        {["ENROLMENT", "ATTENDANCE", "RESULTS", "STAFF"].map((tpl) => (
          <label key={tpl} className="flex items-center gap-1">
            <input type="checkbox" checked={picked.includes(tpl)}
              onChange={(e) => setPicked(e.target.checked ? [...picked, tpl] : picked.filter((x) => x !== tpl))} />{tpl}
          </label>))}
      </div>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={!picked.length || !yearId}>{t("exportAll")}</Button>
        <JobBadge job={job} name="compliance.xlsx" />
      </div>
    </form>
  );
}

export default function Reports() {
  const auth = useAuth();
  const [, t] = useLang();
  const [tab, setTab] = useState<"reports" | "compliance">("reports");
  return (
    <Card title={t("reports")}>
      {auth.can("reports.export") && (
        <div className="mb-4 flex gap-2" role="tablist">
          {(["reports", "compliance"] as const).map((k) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
              className={`rounded-full px-3 py-1 text-sm ${tab === k ? "bg-brand-500 text-white" : "bg-slate-100"}`}>{t(k)}</button>))}
        </div>
      )}
      {tab === "reports" ? <ReportTab /> : <ComplianceTab />}
    </Card>
  );
}
