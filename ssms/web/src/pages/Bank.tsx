import { FormEvent, useState } from "react";

import { useList } from "../academic";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { money } from "../finance";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input } from "../ui";

interface Deposit {
  id: string;
  bank_reference: string;
  deposit_date: string;
  amount_tzs: string;
  student_id: string | null;
  depositor_name: string | null;
  status: string;
  note: string | null;
}

/** Deposit form shared by the bursar (here) and parents (children page). */
export function DepositForm({ studentId, onDone }: { studentId: string; onDone?: () => void }) {
  const [, t] = useLang();
  const [form, setForm] = useState({ bank_reference: "", deposit_date: "", amount_tzs: "", depositor_name: "" });
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/bank-deposits", { body: { ...form, student_id: studentId, depositor_name: form.depositor_name || null } });
      setError(null);
      setDone(true);
      setForm({ bank_reference: "", deposit_date: "", amount_tzs: "", depositor_name: "" });
      onDone?.();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <form className="grid gap-2 sm:grid-cols-2" onSubmit={submit}>
      <div className="sm:col-span-2"><ErrorBox error={error} /></div>
      <Field label={t("reference")}><Input required value={form.bank_reference} onChange={(e) => setForm({ ...form, bank_reference: e.target.value })} /></Field>
      <Field label={t("date")}><Input type="date" required value={form.deposit_date} onChange={(e) => setForm({ ...form, deposit_date: e.target.value })} /></Field>
      <Field label={t("amount")}><Input required inputMode="decimal" value={form.amount_tzs} onChange={(e) => setForm({ ...form, amount_tzs: e.target.value.replace(/,/g, "") })} /></Field>
      <Field label={t("payer")}><Input value={form.depositor_name} onChange={(e) => setForm({ ...form, depositor_name: e.target.value })} /></Field>
      <div className="flex items-center gap-3"><Button type="submit">{t("reportDeposit")}</Button>
        {done && <span className="text-sm text-brand-700">✓ {t("depositReported")}</span>}</div>
    </form>
  );
}

export default function Bank() {
  const auth = useAuth();
  const [, t] = useLang();
  const [deposits, reload] = useList<Deposit>("/bank-deposits?status=PENDING");
  const [error, setError] = useState<ApiError | null>(null);
  async function decide(id: string, confirm: boolean) {
    const note = confirm ? null : window.prompt(t("reason"));
    if (!confirm && !note) return;
    try {
      await api(`/bank-deposits/${id}/${confirm ? "confirm" : "reject"}`, { body: { note } });
      setError(null);
      await reload();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  return (
    <Card title={t("bank")}>
      <ErrorBox error={error} />
      <ul className="divide-y text-sm" data-testid="deposits">
        {deposits.map((d) => (
          <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span>{d.deposit_date} · <span className="font-mono">{d.bank_reference}</span> · {d.depositor_name ?? ""}</span>
            <b>TZS {money(d.amount_tzs)}</b>
            {auth.can("payments.confirm_bank") ? (
              <span className="flex gap-2"><Button onClick={() => decide(d.id, true)}>{t("confirm")}</Button>
                <Button kind="plain" onClick={() => decide(d.id, false)}>{t("reject")}</Button></span>
            ) : <Badge>{t("awaitingApproval")}</Badge>}
          </li>))}
        {deposits.length === 0 && <li className="py-4 text-center text-slate-500">{t("noResults")}</li>}
      </ul>
    </Card>
  );
}
