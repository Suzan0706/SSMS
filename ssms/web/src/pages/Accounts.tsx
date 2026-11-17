// Accounts: other income and expenses, reversals by a second person, income statement, cash book, fines (FR-87..89).
import { FormEvent, useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { money } from "../finance";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";
import { FileUpload, Modal, Tabs, Uploaded } from "../widgets";

interface Category { id: string; kind: "INCOME" | "EXPENSE"; name: string; account_code: string }
interface Entry {
  id: string; entry_no: string; entry_date: string; kind: string; category: string; amount_tzs: string; method: string;
  reference: string | null; party: string | null; description: string; status: string; reversal_pending: boolean;
  reversal_reason: string | null; requested_by_me: boolean; has_attachment: boolean;
}
interface Statement { income: Array<{ code: string; name: string; amount_tzs: string }>; expenses: Array<{ code: string; name: string; amount_tzs: string }>; total_income_tzs: string; total_expenses_tzs: string; net_tzs: string }
interface Book { opening_tzs: string; closing_tzs: string; lines: Array<{ date: string; journal_no: string; memo: string; money_in_tzs: string; money_out_tzs: string; balance_tzs: string }> }

const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => today().slice(0, 8) + "01";

function Period({ range, setRange }: { range: { from: string; to: string }; setRange: (r: { from: string; to: string }) => void }) {
  const [, t] = useLang();
  return (
    <div className="flex flex-wrap gap-3">
      <Field label={t("from")}><Input type="date" value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })} /></Field>
      <Field label={t("to")}><Input type="date" value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })} /></Field>
    </div>
  );
}

function Entries() {
  const auth = useAuth();
  const [, t] = useLang();
  const [categories, setCategories] = useState<Category[]>([]);
  const [rows, setRows] = useState<Entry[]>([]);
  const [range, setRange] = useState({ from: monthStart(), to: today() });
  const [version, setVersion] = useState(0);
  const [kind, setKind] = useState<"EXPENSE" | "INCOME">("EXPENSE");
  const [f, setF] = useState({ category_id: "", entry_date: today(), amount_tzs: "", method: "CASH", reference: "", party: "", description: "" });
  const [receipt, setReceipt] = useState<Uploaded | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [asking, setAsking] = useState<Entry | null>(null);
  const [reason, setReason] = useState("");
  const recorder = auth.can("accounts.record");
  const approver = auth.can("accounts.approve");
  useEffect(() => { api<Category[]>("/accounts/categories").then(setCategories).catch(() => setCategories([])); }, []);
  useEffect(() => {
    api<Entry[]>(`/accounts/entries?from=${range.from}&to=${range.to}`).then(setRows).catch((e) => setError(e as ApiError));
  }, [range, version]);

  async function record(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/accounts/entries", { body: { ...f, reference: f.reference || null, party: f.party || null, attachment_file_id: receipt?.id ?? null } });
      setF({ ...f, amount_tzs: "", reference: "", party: "", description: "" });
      setReceipt(null);
      setError(null);
      setVersion((v) => v + 1);
    } catch (err) {
      setError(err as ApiError);
    }
  }
  async function act(path: string, body: unknown) {
    try {
      await api(path, { body });
      setError(null);
      setAsking(null);
      setReason("");
      setVersion((v) => v + 1);
    } catch (err) {
      setError(err as ApiError);
    }
  }
  const total = (k: string) => rows.filter((r) => r.kind === k && r.status === "POSTED").reduce((a, r) => a + Number(r.amount_tzs), 0);
  return (
    <div className="space-y-5">
      {recorder && (
        <form onSubmit={record} className="grid gap-3 rounded-xl bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label={t("entryKind")}>
            <Select aria-label={t("entryKind")} value={kind} onChange={(e) => { setKind(e.target.value as "EXPENSE" | "INCOME"); setF({ ...f, category_id: "" }); }}>
              <option value="EXPENSE">{t("expense")}</option><option value="INCOME">{t("otherIncome")}</option>
            </Select>
          </Field>
          <Field label={t("category")}>
            <Select required aria-label={t("category")} value={f.category_id} onChange={(e) => setF({ ...f, category_id: e.target.value })}>
              <option value="">—</option>
              {categories.filter((c) => c.kind === kind).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </Select>
          </Field>
          <Field label={t("date")}><Input type="date" required max={today()} value={f.entry_date} onChange={(e) => setF({ ...f, entry_date: e.target.value })} /></Field>
          <Field label={t("amountTzs")}><Input type="number" required min={1} step="0.01" value={f.amount_tzs} onChange={(e) => setF({ ...f, amount_tzs: e.target.value })} /></Field>
          <Field label={t("paymentMethod")}>
            <Select aria-label={t("paymentMethod")} value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}>
              {["CASH", "BANK", "MOBILE_MONEY", "CHEQUE"].map((m) => <option key={m}>{m}</option>)}
            </Select>
          </Field>
          <Field label={kind === "EXPENSE" ? t("paidTo") : t("receivedFrom")}><Input maxLength={120} value={f.party} onChange={(e) => setF({ ...f, party: e.target.value })} /></Field>
          <Field label={t("reference")}><Input maxLength={60} value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} /></Field>
          <Field label={t("description")}><Input required minLength={3} maxLength={300} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <div className="flex flex-wrap items-center gap-3 sm:col-span-2 lg:col-span-4">
            {receipt ? <span className="text-sm">📎 {receipt.original_name}</span>
              : <FileUpload purpose="RECEIPT" accept=".pdf,.jpg,.jpeg,.png" label={t("attachReceipt")} onUploaded={setReceipt} />}
            <Button type="submit">{t("record")}</Button>
          </div>
        </form>)}
      <ErrorBox error={error} />
      <Period range={range} setRange={setRange} />
      <p className="text-sm text-slate-600">{t("otherIncome")}: <b>TZS {money(String(total("INCOME")))}</b> · {t("expense")}: <b>TZS {money(String(total("EXPENSE")))}</b></p>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm" aria-label={t("entries")}>
          <thead><tr><th className="py-2 pr-3">#</th><th className="pr-3">{t("date")}</th><th className="pr-3">{t("category")}</th><th className="pr-3">{t("description")}</th><th className="pr-3 text-right">TZS</th><th className="pr-3">{t("status")}</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-slate-100 last:border-0">
                <td className="py-2 pr-3 font-mono text-xs">{r.entry_no}</td><td className="whitespace-nowrap pr-3">{r.entry_date}</td>
                <td className="pr-3">{r.category}</td>
                <td className="pr-3">{r.description}{r.party && <span className="block text-xs text-slate-500">{r.party}{r.reference ? ` · ${r.reference}` : ""}</span>}
                  {r.reversal_pending && <span className="block text-xs text-accent-700">{t("reversalAsked")}: {r.reversal_reason}</span>}</td>
                <td className={`pr-3 text-right tabular-nums ${r.kind === "EXPENSE" ? "text-red-700" : "text-brand-700"}`}>{r.kind === "EXPENSE" ? "−" : "+"}{money(r.amount_tzs)}</td>
                <td className="pr-3"><Badge>{r.status}</Badge></td>
                <td>
                  <span className="flex gap-2">
                    {recorder && r.status === "POSTED" && !r.reversal_pending && <Button kind="plain" onClick={() => setAsking(r)}>{t("askReversal")}</Button>}
                    {approver && r.reversal_pending && !r.requested_by_me && (<>
                      <Button onClick={() => act(`/accounts/entries/${r.id}/reversal-decision`, { approve: true })}>{t("approve")}</Button>
                      <Button kind="plain" onClick={() => act(`/accounts/entries/${r.id}/reversal-decision`, { approve: false })}>{t("reject")}</Button>
                    </>)}
                  </span>
                </td>
              </tr>))}
          </tbody>
        </table>
      </div>
      <Modal open={asking !== null} title={`${t("askReversal")}: ${asking?.entry_no ?? ""}`} onClose={() => setAsking(null)}
        footer={<><Button kind="plain" onClick={() => setAsking(null)}>{t("cancel")}</Button>
          <Button disabled={reason.trim().length < 5} onClick={() => act(`/accounts/entries/${asking!.id}/reversal-request`, { reason })}>{t("askReversal")}</Button></>}>
        <p className="mb-3">{t("reversalNote")}</p>
        <Field label={t("reason")}><Input minLength={5} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </Modal>
    </div>
  );
}

function IncomeStatement() {
  const [, t] = useLang();
  const [range, setRange] = useState({ from: monthStart(), to: today() });
  const [data, setData] = useState<Statement | null>(null);
  useEffect(() => { api<Statement>(`/accounts/income-statement?from=${range.from}&to=${range.to}`).then(setData).catch(() => setData(null)); }, [range]);
  const section = (title: string, rows: Statement["income"], total: string) => (
    <section className="space-y-1">
      <h3 className="text-sm font-semibold">{title}</h3>
      {rows.map((r) => <p key={r.code} className="flex justify-between border-b border-slate-100 py-1 text-sm"><span>{r.code} · {r.name}</span><span className="tabular-nums">{money(r.amount_tzs)}</span></p>)}
      <p className="flex justify-between py-1 text-sm font-semibold"><span>{t("total")}</span><span className="tabular-nums">{money(total)}</span></p>
    </section>
  );
  return (
    <div className="space-y-4" data-testid="income-statement">
      <Period range={range} setRange={setRange} />
      {data && (
        <div className="grid max-w-3xl gap-6">
          {section(t("incomeLabel"), data.income, data.total_income_tzs)}
          {section(t("expense"), data.expenses, data.total_expenses_tzs)}
          <p className={`flex justify-between rounded-lg px-3 py-2 font-bold ${Number(data.net_tzs) < 0 ? "bg-red-50 text-red-800" : "bg-brand-50 text-brand-800"}`}>
            <span>{Number(data.net_tzs) < 0 ? t("netDeficit") : t("netSurplus")}</span><span className="tabular-nums">TZS {money(data.net_tzs)}</span>
          </p>
        </div>)}
    </div>
  );
}

function CashBook() {
  const [, t] = useLang();
  const [range, setRange] = useState({ from: monthStart(), to: today() });
  const [account, setAccount] = useState("1000");
  const [book, setBook] = useState<Book | null>(null);
  useEffect(() => { api<Book>(`/accounts/cash-book?account=${account}&from=${range.from}&to=${range.to}`).then(setBook).catch(() => setBook(null)); }, [range, account]);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <Field label={t("moneyAccount")}>
          <Select value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="1000">{t("cashOnHand")}</option><option value="1200">{t("bankLabel")}</option><option value="1110">{t("mobileMoney")}</option>
          </Select>
        </Field>
        <Period range={range} setRange={setRange} />
      </div>
      {book && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm" aria-label={t("cashBook")}>
            <thead><tr><th className="py-2 pr-3">{t("date")}</th><th className="pr-3">#</th><th className="pr-3">{t("description")}</th><th className="pr-3 text-right">{t("moneyIn")}</th><th className="pr-3 text-right">{t("moneyOut")}</th><th className="text-right">{t("balance")}</th></tr></thead>
            <tbody>
              <tr className="border-b border-slate-100 font-semibold"><td className="py-2 pr-3" colSpan={5}>{t("openingBalance")}</td><td className="text-right tabular-nums">{money(book.opening_tzs)}</td></tr>
              {book.lines.map((l, i) => (
                <tr key={i} className="border-b border-slate-100">
                  <td className="py-1.5 pr-3">{l.date}</td><td className="pr-3 font-mono text-xs">{l.journal_no}</td><td className="pr-3">{l.memo}</td>
                  <td className="pr-3 text-right tabular-nums">{Number(l.money_in_tzs) ? money(l.money_in_tzs) : ""}</td>
                  <td className="pr-3 text-right tabular-nums">{Number(l.money_out_tzs) ? money(l.money_out_tzs) : ""}</td>
                  <td className="text-right tabular-nums">{money(l.balance_tzs)}</td>
                </tr>))}
              <tr className="font-semibold"><td className="py-2 pr-3" colSpan={5}>{t("closingBalance")}</td><td className="text-right tabular-nums">{money(book.closing_tzs)}</td></tr>
            </tbody>
          </table>
        </div>)}
    </div>
  );
}

function Fines({ kind }: { kind: "late-fee" | "library-day" }) {
  const [, t] = useLang();
  const [f, setF] = useState({ amount_tzs: "", grace_days: "7" });
  const [current, setCurrent] = useState<{ amount_tzs: string; grace_days: number } | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const load = () => api<typeof current>(`/fine-rules/${kind}`).then((r) => { setCurrent(r); if (r) setF({ amount_tzs: String(Number(r.amount_tzs)), grace_days: String(r.grace_days) }); }).catch(() => undefined);
  useEffect(() => { load(); }, []);
  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      await api(`/fine-rules/${kind}`, { method: "PUT", body: { amount_tzs: f.amount_tzs, grace_days: Number(f.grace_days) } });
      setNotice(t("saved"));
      setError(null);
      load();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  async function apply() {
    try {
      const out = await api<{ charged: number }>("/fine-rules/late-fee/apply", { method: "POST" });
      setNotice(`${t("finesCharged")}: ${out.charged}`);
      setError(null);
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <section className="max-w-2xl space-y-4" aria-label={kind === "late-fee" ? t("lateFee") : t("libraryFine")}>
      <h3 className="text-sm font-semibold">{kind === "late-fee" ? t("lateFee") : t("libraryFine")}</h3>
      <p className="text-sm text-slate-600">{kind === "late-fee" ? t("lateFeeNote") : t("libraryFineNote")}</p>
      <form onSubmit={save} className="flex flex-wrap items-end gap-3">
        <Field label={t("amountTzs")}><Input type="number" required min={1} value={f.amount_tzs} onChange={(e) => setF({ ...f, amount_tzs: e.target.value })} /></Field>
        <Field label={t("graceDays")}><Input type="number" required min={0} max={365} value={f.grace_days} onChange={(e) => setF({ ...f, grace_days: e.target.value })} /></Field>
        <Button type="submit">{t("save")}</Button>
      </form>
      {current && kind === "late-fee" && <Button kind="plain" onClick={apply}>{t("applyLateFees")}</Button>}
      {notice && <p role="status" className="text-sm text-brand-700">✓ {notice}</p>}
      <ErrorBox error={error} />
    </section>
  );
}

export default function Accounts() {
  const auth = useAuth();
  const [, t] = useLang();
  type Tab = "entries" | "statement" | "book" | "fines";
  const tabs: Array<[Tab, string]> = [];
  if (auth.can("accounts.read", "accounts.record", "accounts.approve")) tabs.push(["entries", t("entries")], ["statement", t("incomeStatement")], ["book", t("cashBook")]);
  if (auth.can("fines.configure")) tabs.push(["fines", t("fines")]);
  const [tab, setTab] = useState<Tab>(tabs[0]?.[0] ?? "entries");
  return (
    <Card title={t("accountsTitle")}>
      <Tabs label={t("accountsTitle")} tabs={tabs} value={tab} onChange={setTab} />
      {tab === "entries" ? <Entries /> : tab === "statement" ? <IncomeStatement /> : tab === "book" ? <CashBook /> : <div className="space-y-8"><Fines kind="late-fee" /><Fines kind="library-day" /></div>}
    </Card>
  );
}
