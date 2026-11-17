// Small UI kit: labelled inputs with server-side error messages, buttons, alerts.
import {
  ButtonHTMLAttributes, createContext, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, useContext, useEffect, useRef, useState,
} from "react";

/** The title shown in the page's title bar; a card with the same title does not repeat it on screen. */
export const PageTitle = createContext<string | null>(null);

import { ApiError } from "./api";
import { useLang } from "./i18n";

export function Field({ label, error, children }: { label: string; error?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1.5 block font-medium text-slate-700">{label}</span>
      {children}
      {error && <span className="mt-1 block text-xs font-medium text-red-700" role="alert">{error}</span>}
    </label>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`control ${props.className ?? ""}`} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`control ${props.className ?? ""}`} />;
}

export function Button({ kind = "primary", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { kind?: "primary" | "plain" }) {
  const look = kind === "primary"
    ? "bg-brand-500 text-white shadow-sm hover:bg-brand-600 active:bg-brand-700 disabled:bg-slate-200 disabled:text-slate-500 disabled:shadow-none"
    : "border border-slate-300 bg-white text-slate-700 shadow-sm hover:border-slate-400 hover:bg-slate-50 disabled:text-slate-400";
  return (
    <button {...props}
      className={`rounded-lg px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed ${look} ${props.className ?? ""}`} />
  );
}

export function ErrorBox({ error }: { error: ApiError | null }) {
  const [, t] = useLang();
  if (!error) return null;
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">
      {error.error_code === "OFFLINE" ? t("offline") : error.message}
    </div>
  );
}

export function Card({ title, actions, children }: { title?: string; actions?: ReactNode; children: ReactNode }) {
  const repeat = title != null && title === useContext(PageTitle);
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card sm:p-6">
      {repeat && !actions && <h2 className="sr-only">{title}</h2>}
      {(title || actions) && !(repeat && !actions) && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          {title && <h2 className={repeat ? "sr-only" : "text-lg font-semibold tracking-tight"}>{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

/**
 * Wraps a list table with a quick filter and a row count. Rows that do not match are hidden with the
 * `hidden` attribute, which React does not manage, so the table's own rendering is untouched.
 */
export function TableTools({ children }: { children: ReactNode }) {
  const [, t] = useLang();
  const box = useRef<HTMLDivElement>(null);
  const [q, setQ] = useState("");
  const [count, setCount] = useState({ shown: 0, total: 0 });
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const apply = () => {
      const rows = [...el.querySelectorAll<HTMLTableRowElement>("tbody > tr")];
      const needle = q.trim().toLowerCase();
      let shown = 0;
      for (const row of rows) {
        const hit = !needle || (row.textContent ?? "").toLowerCase().includes(needle);
        if (row.hidden === hit) row.hidden = !hit;
        if (hit) shown += 1;
      }
      setCount((c) => (c.shown === shown && c.total === rows.length ? c : { shown, total: rows.length }));
    };
    apply();
    const watch = new MutationObserver(apply);
    watch.observe(el, { childList: true, subtree: true, characterData: true });
    return () => watch.disconnect();
  }, [q]);
  return (
    <div ref={box}>
      {count.total > 5 && (
        <div role="search" className="mb-3 flex flex-wrap items-center gap-3">
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("filterRows")} aria-label={t("filterRows")}
            className="control max-w-xs" />
        </div>
      )}
      {children}
      {count.total > 0 && (
        <p className="mt-2 text-xs text-slate-500">{t("rowsShown")} {count.shown} {t("rowsOf")} {count.total}</p>
      )}
    </div>
  );
}

const GOOD =/^(ACTIVE|PAID|FULLY_PAID|PRESENT|APPROVED|BALANCED|CONFIRMED|COMPLETED|SUCCEEDED|MATCHED|PUBLISHED|SENT|DELIVERED|RESOLVED|RETURNED)$/;
const WAIT = /^(PENDING|PARTIAL|PARTIALLY_PAID|LATE|UNDER_REVIEW|SUBMITTED|DRAFT|RUNNING|QUEUED|ONBOARDING|OPEN|EXCUSED|REQUESTED)$/;
const BAD = /^(UNPAID|OVERDUE|OVERPAID|ABSENT|REJECTED|FAILED|CANCELLED|EXCEPTIONS|SUSPENDED|CLOSED|EXPIRED|REVERSED|AMOUNT_MISMATCH|MISSING_IN_SYSTEM|MISSING_IN_STATEMENT)$/;

function toneOf(children: ReactNode): string {
  if (typeof children !== "string") return "bg-slate-100 text-slate-700";
  if (GOOD.test(children)) return "bg-brand-50 text-brand-700 ring-brand-200";
  if (WAIT.test(children)) return "bg-accent-100 text-accent-700 ring-accent-300";
  if (BAD.test(children)) return "bg-red-50 text-red-800 ring-red-200";
  return "bg-slate-100 text-slate-700 ring-slate-200";
}

/** A status label. The colour comes from the status, and the word is always written, so colour is never alone. */
export function Badge({ children }: { children: ReactNode }) {
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ring-slate-200 ${toneOf(children)}`}>
      {typeof children === "string" ? children.replace(/_/g, " ") : children}
    </span>
  );
}
