import { FormEvent, useCallback, useEffect, useState } from "react";

import { api, ApiError, download } from "../api";
import { useAuth } from "../auth";
import { money } from "../finance";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";
import { useConfirm } from "../widgets";
import { useStreams } from "./Students";

interface Book { id: string; isbn: string | null; title: string; author: string | null; copies: number; on_loan: number; available: number }
interface Loan { id: string; title: string; borrower_name: string; due_date: string; overdue: boolean; fine_tzs?: string | null }
interface Named { id: string; name: string }
interface LibraryCard { id: string; card_no: string; full_name: string; admission_no: string | null; class_stream: string | null }

/** Who borrows: a library card number (LC-...) or an admission number. */
const borrower = (value: string) => (/^lc-/i.test(value.trim()) ? { card_no: value.trim() } : { admission_no: value.trim() });

/** Library cards of a stream: issue to everyone without one, print eight per page, revoke a lost card (FR-96). */
function Cards() {
  const [, t] = useLang();
  const streams = useStreams();
  const [streamId, setStreamId] = useState("");
  const [cards, setCards] = useState<LibraryCard[]>([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [confirm, confirmDialog] = useConfirm();
  useEffect(() => { if (!streamId && streams[0]) setStreamId(streams[0].id); }, [streams, streamId]);
  const load = useCallback(() => {
    if (streamId) api<LibraryCard[]>(`/library/cards?stream_id=${streamId}`).then(setCards).catch(() => setCards([]));
  }, [streamId]);
  useEffect(load, [load]);
  async function issue() {
    try {
      const out = await api<{ issued: number }>("/library/cards", { body: { stream_id: streamId } });
      setNotice(`${t("cardsIssued")}: ${out.issued}`);
      setError(null);
      load();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  async function revoke(card: LibraryCard) {
    if (await confirm(`${card.card_no} · ${card.full_name}`, t("revokeCard"))) {
      await api(`/library/cards/${card.id}/revoke`, { method: "POST" });
      load();
    }
  }
  return (
    <Card title={t("libraryCards")}>
      {confirmDialog}
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <Field label={t("classStream")}>
          <Select value={streamId} onChange={(e) => setStreamId(e.target.value)}>{streams.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</Select>
        </Field>
        <Button onClick={issue} disabled={!streamId}>{t("issueCards")}</Button>
        {cards.length > 0 && (
          <Button kind="plain" onClick={() => download(`/library/cards.pdf?stream_id=${streamId}`, "library-cards.pdf").catch((e) => setError(e))}>{t("printCards")}</Button>)}
        {notice && <span role="status" className="text-sm text-brand-700">✓ {notice}</span>}
      </div>
      <ErrorBox error={error} />
      <ul className="divide-y text-sm" data-testid="library-cards">
        {cards.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
            <span><span className="font-mono text-xs">{c.card_no}</span> · {c.full_name} <span className="text-slate-500">{c.admission_no}</span></span>
            <Button kind="plain" onClick={() => revoke(c)}>{t("revokeCard")}</Button>
          </li>))}
        {cards.length === 0 && <li className="py-2 text-slate-500">{t("noResults")}</li>}
      </ul>
    </Card>
  );
}

export default function Library() {
  const auth = useAuth();
  const [, t] = useLang();
  const [q, setQ] = useState("");
  const [books, setBooks] = useState<Book[]>([]);
  const [loans, setLoans] = useState<Loan[]>([]);
  const [categories, setCategories] = useState<Named[]>([]);
  const [publishers, setPublishers] = useState<Named[]>([]);
  const [lendTo, setLendTo] = useState<Record<string, string>>({});
  const [form, setForm] = useState({ title: "", author: "", isbn: "", copies: "1", category_id: "", publisher_id: "" });
  const [newName, setNewName] = useState({ category: "", publisher: "" });
  const [sent, setSent] = useState<number | null>(null);
  const [fineNote, setFineNote] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const load = useCallback(() => {
    api<Book[]>(`/library/books${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`).then(setBooks).catch(() => undefined);
    api<Loan[]>("/library/loans?open=true").then(setLoans).catch(() => undefined);
    api<Named[]>("/library/categories").then(setCategories).catch(() => undefined);
    api<Named[]>("/library/publishers").then(setPublishers).catch(() => undefined);
  }, [q]);
  useEffect(() => { const timer = setTimeout(load, 250); return () => clearTimeout(timer); }, [load]);

  async function run(action: () => Promise<unknown>) {
    try {
      await action();
      setError(null);
      load();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  function add(e: FormEvent) {
    e.preventDefault();
    run(async () => {
      await api("/library/books", { body: { title: form.title, author: form.author || null, isbn: form.isbn || null, copies: Number(form.copies),
        category_id: form.category_id || null, publisher_id: form.publisher_id || null } });
      setForm({ title: "", author: "", isbn: "", copies: "1", category_id: "", publisher_id: "" });
    });
  }
  function addNamed(e: FormEvent, key: "category" | "publisher") {
    e.preventDefault();
    run(async () => {
      await api(key === "category" ? "/library/categories" : "/library/publishers", { body: { name: newName[key] } });
      setNewName({ ...newName, [key]: "" });
    });
  }
  async function giveBack(l: Loan) {
    const out = await api<Loan>(`/library/loans/${l.id}/return`, { method: "POST" });
    setFineNote(out.fine_tzs ? `${l.borrower_name}: ${t("libraryFineCharged")} TZS ${money(out.fine_tzs)}` : "");
  }
  return (
    <div className="space-y-4">
      <Card title={t("library")}>
        <ErrorBox error={error} />
        <Input placeholder={t("search")} aria-label={t("search")} value={q} onChange={(e) => setQ(e.target.value)} className="mb-2" />
        <p className="mb-2 text-xs text-slate-500">{t("lendHint")}</p>
        <ul className="divide-y text-sm" data-testid="books">
          {books.map((b) => (
            <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span><b>{b.title}</b> {b.author && <span className="text-slate-500">· {b.author}</span>}</span>
              <span className="flex items-center gap-2">
                <Badge>{t("available")}: {b.available}/{b.copies}</Badge>
                <Input aria-label={`${t("admissionNo")} ${b.title}`} placeholder={t("admissionNo")} className="w-36"
                  value={lendTo[b.id] ?? ""} onChange={(e) => setLendTo({ ...lendTo, [b.id]: e.target.value })} />
                <Button kind="plain" disabled={!lendTo[b.id] || b.available === 0}
                  onClick={() => run(async () => { await api("/library/loans", { body: { book_id: b.id, ...borrower(lendTo[b.id]) } }); setLendTo({ ...lendTo, [b.id]: "" }); })}>
                  {t("lend")}</Button>
              </span>
            </li>))}
        </ul>
      </Card>
      <Card title={t("loans")} actions={<span className="flex items-center gap-2">
        <Button kind="plain" onClick={() => run(async () => setSent((await api<{ queued: number }>("/library/reminders/run", { method: "POST" })).queued))}>{t("sendReminders")}</Button>
        {sent !== null && <Badge>{t("remindersQueued")}: {sent}</Badge>}</span>}>
        {fineNote && <p role="status" className="mb-2 text-sm text-accent-700">{fineNote}</p>}
        <ul className="divide-y text-sm" data-testid="loans">
          {loans.map((l) => (
            <li key={l.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
              <span>{l.title} · {l.borrower_name}</span>
              <span className="flex items-center gap-2"><span className={l.overdue ? "font-semibold text-red-700" : "text-slate-500"}>{l.due_date}</span>
                <Button kind="plain" onClick={() => run(() => giveBack(l))}>{t("returned")}</Button></span>
            </li>))}
          {loans.length === 0 && <li className="py-2 text-slate-500">{t("noResults")}</li>}
        </ul>
      </Card>
      <Card title={t("addBook")}>
        <form className="grid gap-2 sm:grid-cols-3 sm:items-end lg:grid-cols-7" onSubmit={add}>
          <Field label={t("title")}><Input required minLength={2} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
          <Field label={t("author")}><Input value={form.author} onChange={(e) => setForm({ ...form, author: e.target.value })} /></Field>
          <Field label="ISBN"><Input pattern="[0-9X-]{10,17}" value={form.isbn} onChange={(e) => setForm({ ...form, isbn: e.target.value })} /></Field>
          <Field label={t("copies")}><Input type="number" min={0} value={form.copies} onChange={(e) => setForm({ ...form, copies: e.target.value })} /></Field>
          <Field label={t("category")}>
            <Select value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })}><option value="">—</option>{categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
          </Field>
          <Field label={t("publisher")}>
            <Select value={form.publisher_id} onChange={(e) => setForm({ ...form, publisher_id: e.target.value })}><option value="">—</option>{publishers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
          </Field>
          <Button type="submit">{t("add")}</Button>
        </form>
        <div className="mt-4 grid gap-3 border-t border-slate-100 pt-4 sm:grid-cols-2">
          <form className="flex items-end gap-2" onSubmit={(e) => addNamed(e, "category")}>
            <Field label={t("newCategory")}><Input required minLength={2} maxLength={80} value={newName.category} onChange={(e) => setNewName({ ...newName, category: e.target.value })} /></Field>
            <Button type="submit" kind="plain">{t("add")}</Button>
          </form>
          <form className="flex items-end gap-2" onSubmit={(e) => addNamed(e, "publisher")}>
            <Field label={t("newPublisher")}><Input required minLength={2} maxLength={80} value={newName.publisher} onChange={(e) => setNewName({ ...newName, publisher: e.target.value })} /></Field>
            <Button type="submit" kind="plain">{t("add")}</Button>
          </form>
        </div>
      </Card>
      {auth.can("library.manage", "cards.print") && <Cards />}
    </div>
  );
}
