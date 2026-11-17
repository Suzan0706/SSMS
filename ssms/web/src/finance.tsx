import { useState } from "react";

import { api, ApiError, download } from "./api";
import { useAuth } from "./auth";
import { useLang } from "./i18n";
import { Badge, ErrorBox } from "./ui";

/** Money arrives as decimal strings; show it with thousands separators, never through float arithmetic. */
export function money(v: string | number | null | undefined): string {
  if (v == null) return "";
  const [whole, cents] = String(v).split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return cents && Number(cents) !== 0 ? `${grouped}.${cents}` : grouped;
}

export interface InvoiceRow {
  id: string;
  invoice_no: string;
  student_id: string;
  admission_no: string;
  student_name: string;
  due_date: string;
  total_tzs: string;
  paid_tzs: string;
  balance_tzs: string;
  status: string;
  control_number: string | null;
}

export interface PaymentRow {
  id: string;
  channel: string;
  external_ref: string;
  amount_tzs: string;
  status: string;
  received_at: string;
  receipt: { receipt_no: string } | null;
}

export interface Statement {
  student_id: string;
  admission_no: string;
  full_name: string;
  outstanding_tzs: string;
  credit_tzs: string;
  invoices: InvoiceRow[];
  payments: PaymentRow[];
}

export function StatementView({ statement, onChange }: { statement: Statement; onChange?: () => void }) {
  const auth = useAuth();
  const [lang, t] = useLang();
  const [error, setError] = useState<ApiError | null>(null);
  async function requestReversal(id: string) {
    const reason = window.prompt(t("reason"));
    if (!reason) return;
    try {
      await api(`/payments/${id}/reversal-requests`, { body: { reason } });
      onChange?.();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  return (
    <div className="space-y-2 text-sm" data-testid="statement">
      <ErrorBox error={error} />
      <p>{t("outstanding")}: <b data-testid="outstanding">TZS {money(statement.outstanding_tzs)}</b> · {t("credit")}: TZS {money(statement.credit_tzs)}</p>
      <ul className="divide-y">
        {statement.invoices.map((i) => (
          <li key={i.id} className="flex flex-wrap justify-between gap-2 py-1.5">
            <span className="font-mono text-xs">{i.invoice_no}</span>
            <span>{money(i.total_tzs)} · {t("balance")} {money(i.balance_tzs)} <Badge>{i.status}</Badge></span>
            {i.control_number && <span className="font-mono text-xs">{t("controlNumber")}: {i.control_number}</span>}
            <button className="text-brand-700 underline" onClick={() => download(`/invoices/${i.id}/pdf?lang=${lang}`, `${i.invoice_no}.pdf`)}>PDF</button>
          </li>))}
      </ul>
      <ul className="divide-y">
        {statement.payments.map((p) => (
          <li key={p.id} className="flex flex-wrap justify-between gap-2 py-1.5">
            <span>{p.received_at.slice(0, 10)} · {p.channel} · {p.external_ref}</span>
            <span>TZS {money(p.amount_tzs)} <Badge>{p.status}</Badge></span>
            <span className="flex gap-2">
              {p.receipt && (
                <button className="text-brand-700 underline"
                  onClick={() => download(`/payments/${p.id}/receipt?lang=${lang}`, `${p.receipt!.receipt_no}.pdf`)}>{p.receipt.receipt_no}</button>)}
              {auth.can("payments.reverse_request") && p.status === "CONFIRMED" && (
                <button className="text-red-700 underline" onClick={() => requestReversal(p.id)}>{t("requestReversal")}</button>)}
            </span>
          </li>))}
      </ul>
    </div>
  );
}
