import { FormEvent, useCallback, useEffect, useState } from "react";

import { Named, nameOf, newKey, useCurrentTerm, useList } from "../academic";
import { api, ApiError, download, fetchAll, Page } from "../api";
import { useAuth } from "../auth";
import { InvoiceRow, money, Statement, StatementView } from "../finance";
import { useLang, Word } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select, TableTools } from "../ui";

type Tab = "invoices" | "recordPayment" | "reversals" | "reconciliation" | "reports" | "feeSetup";

function useJob() {
  const [job, setJob] = useState<{ id: string; status: string; processed_items: number; error_count: number } | null>(null);
  useEffect(() => {
    if (!job || job.status === "SUCCEEDED" || job.status === "FAILED") return;
    const timer = setTimeout(() => api<typeof job>(`/jobs/${job.id}`).then(setJob).catch(() => undefined), 1200);
    return () => clearTimeout(timer);
  }, [job]);
  return [job, setJob] as const;
}

function Invoices() {
  const auth = useAuth();
  const [lang, t] = useLang();
  const { terms, termId, setTermId } = useCurrentTerm();
  const [classes] = useList<Named>("/classes");
  const [status, setStatus] = useState("");
  const [rows, setRows] = useState<InvoiceRow[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [due, setDue] = useState("");
  const [split, setSplit] = useState(false);
  const [job, setJob] = useJob();
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    if (!termId) return;
    const q = new URLSearchParams({ term_id: termId });
    if (status) q.set("status", status);
    try {
      setRows(await fetchAll<InvoiceRow>(`/invoices?${q}`));
    } catch (e) {
      setError(e as ApiError);
    }
  }, [termId, status]);
  useEffect(() => { load(); }, [load, job?.status]);

  async function generate(e: FormEvent) {
    e.preventDefault();
    const term = terms.find((x) => x.id === termId);
    const installments = split && term
      ? [{ due_date: due, percent: "60" }, { due_date: term.end_date, percent: "40" }] : [];
    try {
      setJob(await api("/invoices/generate", { body: { term_id: termId, class_ids: picked, due_date: due, installments },
                                              headers: { "Idempotency-Key": newKey() } }));
      setError(null);
    } catch (err) {
      setError(err as ApiError);
    }
  }

  async function controlNumber(id: string) {
    try {
      await api(`/invoices/${id}/control-number`, { method: "POST" });
      setTimeout(load, 800);
    } catch (e) {
      setError(e as ApiError);
    }
  }

  return (
    <div className="space-y-3">
      <ErrorBox error={error} />
      <div className="grid gap-2 sm:grid-cols-3">
        <Select aria-label={t("term")} value={termId} onChange={(e) => setTermId(e.target.value)}>
          {terms.map((x) => <option key={x.id} value={x.id}>{nameOf(x, lang)}</option>)}
        </Select>
        <Select aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t("allStatuses")}</option>
          {["UNPAID", "PARTIALLY_PAID", "FULLY_PAID", "OVERPAID", "CANCELLED"].map((s) => <option key={s}>{s}</option>)}
        </Select>
      </div>
      {auth.can("invoices.manage") && (
        <form className="flex flex-wrap items-end gap-3 rounded-md bg-slate-50 p-3 text-sm" onSubmit={generate}>
          <div className="flex flex-wrap gap-2">
            {classes.map((c) => (
              <label key={c.id} className="flex items-center gap-1">
                <input type="checkbox" checked={picked.includes(c.id)}
                  onChange={(e) => setPicked(e.target.checked ? [...picked, c.id] : picked.filter((x) => x !== c.id))} />
                {c.code}
              </label>))}
          </div>
          <Field label={t("dueDate")}><Input type="date" required value={due} onChange={(e) => setDue(e.target.value)} /></Field>
          <label className="flex items-center gap-1"><input type="checkbox" checked={split} onChange={(e) => setSplit(e.target.checked)} />{t("installments")}</label>
          <Button type="submit" disabled={!picked.length || !due}>{t("generateInvoices")}</Button>
          {job && <span data-testid="invoice-job" data-status={job.status}><Badge>{job.status}</Badge> {job.processed_items}</span>}
        </form>
      )}
      {termId && (
        <div className="mb-2 flex justify-end">
          <Button kind="plain" onClick={() => download(`/exports/invoices.csv?term_id=${termId}`, "invoices.csv")}>{t("exportCsv")}</Button>
        </div>)}
      <TableTools><div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b text-xs uppercase text-slate-500">
            <tr><th className="py-2">#</th><th>{t("student")}</th><th>{t("total")}</th><th>{t("paid")}</th>
              <th>{t("balance")}</th><th>{t("status")}</th><th>{t("controlNumber")}</th><th /></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b last:border-0">
                <td className="py-1.5 font-mono text-xs">{r.invoice_no}</td><td>{r.student_name}</td>
                <td>{money(r.total_tzs)}</td><td>{money(r.paid_tzs)}</td><td className="font-semibold">{money(r.balance_tzs)}</td>
                <td><Badge>{r.status}</Badge></td>
                <td className="font-mono text-xs">{r.control_number ?? (auth.can("invoices.manage") && Number(r.balance_tzs) > 0 && r.status !== "CANCELLED" ? (
                  <button className="text-brand-700 underline" onClick={() => controlNumber(r.id)}>{t("getControlNumber")}</button>) : "")}</td>
                <td><button className="text-brand-700 underline" onClick={() => download(`/invoices/${r.id}/pdf?lang=${lang}`, `${r.invoice_no}.pdf`)}>PDF</button></td>
              </tr>))}
          </tbody>
        </table>
      </div></TableTools>
    </div>
  );
}

function RecordPayment() {
  const [, t] = useLang();
  const [q, setQ] = useState("");
  const [matches, setMatches] = useState<Array<{ id: string; admission_no: string; full_name: string }>>([]);
  const [studentId, setStudentId] = useState("");
  const [statement, setStatement] = useState<Statement | null>(null);
  const [form, setForm] = useState({ channel: "CASH", external_ref: "", amount_tzs: "", payer_name: "", payer_phone: "" });
  const [saved, setSaved] = useState<{ id: string; receipt: { receipt_no: string } | null } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    if (q.trim().length < 2) { setMatches([]); return; }
    const timer = setTimeout(() => api<Page<{ id: string; admission_no: string; full_name: string }>>(
      `/students?q=${encodeURIComponent(q.trim())}&limit=10`).then((p) => setMatches(p.items)).catch(() => undefined), 250);
    return () => clearTimeout(timer);
  }, [q]);
  const loadStatement = useCallback(async (id: string) => setStatement(await api<Statement>(`/students/${id}/statement`)), []);
  useEffect(() => { if (studentId) loadStatement(studentId); }, [studentId, loadStatement]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const out = await api<{ id: string; receipt: { receipt_no: string } | null }>("/payments", {
        body: { ...form, student_id: studentId, received_at: new Date().toISOString(), payer_phone: form.payer_phone || null,
                payer_name: form.payer_name || null }, headers: { "Idempotency-Key": newKey() } });
      setSaved(out);
      setError(null);
      setForm({ ...form, external_ref: "", amount_tzs: "" });
      await loadStatement(studentId);
    } catch (err) {
      setError(err as ApiError);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="space-y-2">
        <Input placeholder={t("search")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("search")} />
        <ul className="divide-y text-sm">
          {matches.map((m) => (
            <li key={m.id}><button className={`w-full py-1.5 text-left ${m.id === studentId ? "font-semibold" : ""}`}
              onClick={() => { setStudentId(m.id); setSaved(null); }}>{m.admission_no} · {m.full_name}</button></li>))}
        </ul>
        {statement && <StatementView statement={statement} onChange={() => loadStatement(studentId)} />}
      </div>
      {studentId && (
        <form className="space-y-2" onSubmit={submit}>
          <ErrorBox error={error} />
          <Field label={t("channel")}>
            <Select name="channel" value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })}>
              <option value="CASH">CASH</option><option value="BANK">BANK</option>
            </Select>
          </Field>
          <Field label={t("reference")}><Input name="external_ref" required value={form.external_ref} onChange={(e) => setForm({ ...form, external_ref: e.target.value })} /></Field>
          <Field label={t("amount")}><Input name="amount_tzs" required inputMode="decimal" value={form.amount_tzs} onChange={(e) => setForm({ ...form, amount_tzs: e.target.value.replace(/,/g, "") })} /></Field>
          <Field label={t("payer")}><Input name="payer_name" value={form.payer_name} onChange={(e) => setForm({ ...form, payer_name: e.target.value })} /></Field>
          <Field label={t("phone")}><Input name="payer_phone" type="tel" value={form.payer_phone} onChange={(e) => setForm({ ...form, payer_phone: e.target.value })} /></Field>
          <Button type="submit">{t("saveAndReceipt")}</Button>
          {saved?.receipt && (
            <p className="text-sm text-brand-700" data-testid="receipt-no">✓ {t("receipt")} {saved.receipt.receipt_no}{" "}
              <button type="button" className="underline" onClick={() => download(`/payments/${saved.id}/receipt`, `${saved.receipt!.receipt_no}.pdf`)}>PDF</button></p>)}
        </form>
      )}
    </div>
  );
}

function Reversals() {
  const auth = useAuth();
  const [, t] = useLang();
  const [items, reload] = useList<{ id: string; external_ref: string; amount_tzs: string; student_name: string; reason: string;
                                    status: string; requested_by_name: string }>("/reversal-requests?status=PENDING");
  const [error, setError] = useState<ApiError | null>(null);
  async function decide(id: string, approve: boolean) {
    try {
      await api(`/reversal-requests/${id}/${approve ? "approve" : "reject"}`, { body: { note: null } });
      await reload();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  return (
    <div>
      <ErrorBox error={error} />
      <ul className="divide-y text-sm">
        {items.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span>{r.external_ref} · TZS {money(r.amount_tzs)} · {r.student_name} — {r.reason} ({r.requested_by_name})</span>
            {auth.can("payments.reverse_approve") ? (
              <span className="flex gap-2"><Button onClick={() => decide(r.id, true)}>{t("approve")}</Button>
                <Button kind="plain" onClick={() => decide(r.id, false)}>{t("reject")}</Button></span>
            ) : <Badge>{t("awaitingApproval")}</Badge>}
          </li>))}
        {items.length === 0 && <li className="py-4 text-center text-slate-500">{t("noResults")}</li>}
      </ul>
    </div>
  );
}

function Reconciliation() {
  const [, t] = useLang();
  const [runs, reload] = useList<{ id: string; run_date: string; channel: string; statement_total_tzs: string;
                                   system_total_tzs: string; status: string; exception_count: number }>("/reconciliation-runs");
  const [form, setForm] = useState({ run_date: "", channel: "MPESA" });
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const data = new FormData();
    data.append("run_date", form.run_date);
    data.append("channel", form.channel);
    data.append("file", file);
    try {
      await api("/reconciliation-runs", { form: data });
      setError(null);
      await reload();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <div className="space-y-3">
      <ErrorBox error={error} />
      <form className="grid gap-2 sm:grid-cols-4 sm:items-end" onSubmit={submit}>
        <Field label={t("date")}><Input type="date" required value={form.run_date} onChange={(e) => setForm({ ...form, run_date: e.target.value })} /></Field>
        <Field label={t("channel")}>
          <Select value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })}>
            {["GEPG", "MPESA", "TIGOPESA", "AIRTEL", "HALOPESA", "BANK", "CASH"].map((c) => <option key={c}>{c}</option>)}
          </Select>
        </Field>
        <Field label={t("statementFile")}><input type="file" accept=".csv" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
        <Button type="submit">{t("check")}</Button>
      </form>
      <ul className="divide-y text-sm">
        {runs.map((r) => (
          <li key={r.id} className="flex justify-between py-1.5">
            <span>{r.run_date} · {r.channel} · {money(r.statement_total_tzs)} / {money(r.system_total_tzs)}</span>
            <Badge>{r.status === "BALANCED" ? `✓ ${t("balanced")}` : `${t("exceptions")}: ${r.exception_count}`}</Badge>
          </li>))}
      </ul>
    </div>
  );
}

function Reports() {
  const auth = useAuth();
  const [, t] = useLang();
  const [aging, setAging] = useState<{ summary: Record<string, { count: number; balance_tzs: string }> } | null>(null);
  const [defaulters, setDefaulters] = useState<Array<{ admission_no: string; student: string; class_code: string | null;
                                                       outstanding_tzs: string }>>([]);
  const [sent, setSent] = useState<number | null>(null);
  useEffect(() => {
    api<typeof aging>("/reports/fees/aging").then(setAging).catch(() => undefined);
    api<{ rows: typeof defaulters }>("/reports/fees/defaulters").then((r) => setDefaulters(r.rows)).catch(() => undefined);
  }, []);
  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap gap-2">
        <Button kind="plain" onClick={() => download("/reports/fees/aging?format=xlsx", "aging.xlsx")}>{t("aging")} (Excel)</Button>
        <Button kind="plain" onClick={() => download("/reports/fees/defaulters?format=xlsx", "defaulters.xlsx")}>{t("defaulters")} (Excel)</Button>
        {auth.can("invoices.manage") && (
          <Button onClick={() => api<{ queued: number }>("/fees/reminders/run", { method: "POST" }).then((r) => setSent(r.queued))}>{t("sendReminders")}</Button>)}
        {sent !== null && <Badge>{t("remindersQueued")}: {sent}</Badge>}
      </div>
      {aging && (
        <table className="w-full max-w-md text-left">
          <tbody>
            {Object.entries(aging.summary).map(([bucket, v]) => (
              <tr key={bucket} className="border-b"><td className="py-1">{bucket}</td><td>{v.count}</td><td>TZS {money(v.balance_tzs)}</td></tr>))}
          </tbody>
        </table>
      )}
      <h3 className="font-semibold">{t("defaulters")}</h3>
      <ul className="divide-y">
        {defaulters.slice(0, 50).map((d) => (
          <li key={d.admission_no} className="flex justify-between py-1"><span>{d.admission_no} · {d.student} · {d.class_code}</span>
            <b>TZS {money(d.outstanding_tzs)}</b></li>))}
      </ul>
    </div>
  );
}

function FeeSetup() {
  const auth = useAuth();
  const [lang, t] = useLang();
  const [structures, reload] = useList<{ id: string; name: string; class_id: string; status: string; totals: Record<string, string> }>("/fee-structures");
  const [classes] = useList<Named>("/classes");
  const [error, setError] = useState<ApiError | null>(null);
  async function act(id: string, action: "approve" | "archive") {
    try {
      await api(`/fee-structures/${id}/${action}`, { method: "POST" });
      await reload();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  return (
    <div>
      <ErrorBox error={error} />
      <ul className="divide-y text-sm">
        {structures.map((s) => (
          <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span>{s.name} · {nameOf(classes.find((c) => c.id === s.class_id), lang)}</span>
            <span>{Object.values(s.totals).map(money).join(" + ")}</span>
            <span className="flex items-center gap-2"><Badge>{s.status === "DRAFT" ? t("draft") : s.status === "APPROVED" ? t("approved") : s.status}</Badge>
              {s.status === "DRAFT" && auth.can("settings.update") && <Button onClick={() => act(s.id, "approve")}>{t("approve")}</Button>}</span>
          </li>))}
      </ul>
    </div>
  );
}

export default function Fees() {
  const auth = useAuth();
  const [, t] = useLang();
  const tabs: Array<[Tab, boolean]> = [
    ["invoices", auth.can("finance.read")], ["recordPayment", auth.can("payments.record")],
    ["reversals", auth.can("payments.reverse_request", "payments.reverse_approve")],
    ["reconciliation", auth.can("reconciliation.run")], ["reports", auth.can("finance.read")],
    ["feeSetup", auth.can("fees.configure")],
  ];
  const visible = tabs.filter(([, ok]) => ok).map(([k]) => k);
  const [tab, setTab] = useState<Tab>(visible[0] ?? "invoices");
  return (
    <Card title={t("fees")}>
      <div className="mb-4 flex flex-wrap gap-2" role="tablist">
        {visible.map((k) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`rounded-full px-3 py-1 text-sm ${tab === k ? "bg-brand-500 text-white" : "bg-slate-100"}`}>{t(k as Word)}</button>))}
      </div>
      {tab === "invoices" && <Invoices />}
      {tab === "recordPayment" && <RecordPayment />}
      {tab === "reversals" && <Reversals />}
      {tab === "reconciliation" && <Reconciliation />}
      {tab === "reports" && <Reports />}
      {tab === "feeSetup" && <FeeSetup />}
    </Card>
  );
}
