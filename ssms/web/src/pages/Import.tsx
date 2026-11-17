import { FormEvent, useEffect, useState } from "react";

import { api, ApiError, download, Page } from "../api";
import { useAuth } from "../auth";
import { useLang, Word } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Select } from "../ui";

type Kind = "students" | "guardians" | "staff";

interface Job {
  id: string;
  kind: string;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
  total_items: number | null;
  processed_items: number;
  error_count: number;
  created_at: string;
  error_report_url: string | null;
  result_url: string | null;
}

const STATUS_WORD: Record<string, Word> = {
  QUEUED: "jobQueued", RUNNING: "jobRunning", SUCCEEDED: "jobSucceeded", FAILED: "jobFailed", CANCELLED: "jobFailed",
};

export default function Import() {
  const auth = useAuth();
  const [, t] = useLang();
  const kinds: Kind[] = [
    ...(auth.can("students.import") ? (["students", "guardians"] as Kind[]) : []),
    ...(auth.can("staff.manage") ? (["staff"] as Kind[]) : []),
  ];
  const [kind, setKind] = useState<Kind>(kinds[0] ?? "students");
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const refreshJobs = () => api<Page<Job>>("/jobs?limit=10").then((p) => setJobs(p.items)).catch(() => undefined);
  useEffect(() => { refreshJobs(); }, []);

  useEffect(() => {                                        // poll the current job until it finishes
    if (!job || job.status === "SUCCEEDED" || job.status === "FAILED") return;
    const timer = setTimeout(() => api<Job>(`/jobs/${job.id}`).then((j) => {
      setJob(j);
      if (j.status === "SUCCEEDED" || j.status === "FAILED") refreshJobs();
    }).catch((e) => setError(e)), 1500);
    return () => clearTimeout(timer);
  }, [job]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      setJob(await api<Job>(`/imports/${kind}`, { form, headers: { "Idempotency-Key": crypto.randomUUID() } }));
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  }

  const files = (j: Job) => (
    <span className="flex gap-3">
      {j.error_report_url && <button className="text-red-700 underline" onClick={() => download(j.error_report_url!, `errors-${j.id}.xlsx`)}>{t("errorReport")}</button>}
      {j.result_url && <button className="text-brand-700 underline" onClick={() => download(j.result_url!, `result-${j.id}.xlsx`)}>{t("resultFile")}</button>}
    </span>
  );

  return (
    <div className="space-y-4">
      <Card title={t("imports")}>
        <p className="mb-3 text-sm text-slate-600">{t("importNote")}</p>
        <ErrorBox error={error} />
        <form className="mt-3 grid gap-3 sm:grid-cols-3 sm:items-end" onSubmit={submit}>
          <Field label={t("importKind")}>
            <Select name="kind" value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
              {kinds.map((k) => <option key={k} value={k}>{k}</option>)}
            </Select>
          </Field>
          <Field label={t("chooseFile")}>
            <input name="file" type="file" required accept=".xlsx,.csv" className="block w-full text-sm"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </Field>
          <div className="flex gap-2">
            <Button type="submit" disabled={busy || !file}>{t("upload")}</Button>
            <Button type="button" kind="plain" onClick={() => download(`/imports/templates/${kind}`, `ssms-${kind}-template.xlsx`)}>
              {t("downloadTemplate")}
            </Button>
          </div>
        </form>
        {job && (
          <div className="mt-4 rounded-md border border-slate-200 p-3 text-sm" data-testid="job-status" data-status={job.status}>
            <div className="flex flex-wrap items-center gap-3">
              <Badge>{t(STATUS_WORD[job.status])}</Badge>
              <span>{t("rows")}: {job.processed_items}/{job.total_items ?? "?"}</span>
              {job.error_count > 0 && <span className="text-red-700">✗ {job.error_count}</span>}
              {files(job)}
            </div>
          </div>
        )}
      </Card>
      <Card title={t("recentJobs")}>
        <ul className="divide-y text-sm">
          {jobs.map((j) => (
            <li key={j.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>{new Date(j.created_at).toLocaleString()} · {j.kind}</span>
              <span className="flex items-center gap-3"><Badge>{t(STATUS_WORD[j.status])}</Badge>{files(j)}</span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
