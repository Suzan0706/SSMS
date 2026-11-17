import { FormEvent, useEffect, useState } from "react";

import { useList } from "../academic";
import { api, ApiError, Page } from "../api";
import { clock } from "../dates";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";

interface Device { id: string; name: string; kind: string; location: string | null; status: string; last_seen_at: string | null }
interface CardRow { id: string; student_id: string; admission_no: string; full_name: string; kind: string; status: string; issued_at: string }

function KeyNotice({ shown }: { shown: { name: string; key: string } | null }) {
  const [, t] = useLang();
  if (!shown) return null;
  return (
    <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm" data-testid="device-key">
      <p className="font-semibold">{t("deviceKey")} — {shown.name}</p>
      <code className="mt-1 block break-all">{shown.key}</code>
    </div>
  );
}

function DevicesPanel() {
  const [, t] = useLang();
  const [devices, reload] = useList<Device>("/devices");
  const [form, setForm] = useState({ name: "", kind: "RFID_READER", location: "" });
  const [shown, setShown] = useState<{ name: string; key: string } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      const out = await api<Device & { api_key: string }>("/devices", { body: { ...form, location: form.location || null } });
      setShown({ name: out.name, key: out.api_key });
      setForm({ name: "", kind: "RFID_READER", location: "" });
      setError(null);
      await reload();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  async function act(device: Device, action: "disable" | "rotate") {
    try {
      if (action === "rotate") {
        const out = await api<Device & { api_key: string }>(`/devices/${device.id}/rotate-key`, { method: "POST" });
        setShown({ name: out.name, key: out.api_key });
      } else {
        await api(`/devices/${device.id}`, { method: "PATCH", body: { status: device.status === "ACTIVE" ? "DISABLED" : "ACTIVE" } });
      }
      await reload();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <section className="space-y-3">
      <ErrorBox error={error} />
      <KeyNotice shown={shown} />
      <form className="grid gap-2 sm:grid-cols-4 sm:items-end" onSubmit={create}>
        <Field label={t("name")}><Input required minLength={2} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label={t("kind")}>
          <Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            <option value="RFID_READER">RFID</option><option value="QR_SCANNER">QR</option><option value="TABLET">Tablet</option>
          </Select>
        </Field>
        <Field label={t("location")}><Input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></Field>
        <Button type="submit">{t("add")}</Button>
      </form>
      <ul className="divide-y text-sm">
        {devices.map((d) => (
          <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span>{d.name} · {d.kind} · {d.location ?? ""}</span>
            <span className="text-xs text-slate-500">{t("lastSeen")}: {d.last_seen_at ? `${d.last_seen_at.slice(0, 10)} ${clock(d.last_seen_at)}` : "—"}</span>
            <span className="flex items-center gap-2"><Badge>{d.status}</Badge>
              <Button kind="plain" onClick={() => act(d, "disable")}>{d.status === "ACTIVE" ? t("disable") : "✓"}</Button>
              <Button kind="plain" onClick={() => act(d, "rotate")}>{t("newKey")}</Button></span>
          </li>))}
      </ul>
    </section>
  );
}

function CardsPanel() {
  const [, t] = useLang();
  const [q, setQ] = useState("");
  const [matches, setMatches] = useState<Array<{ id: string; admission_no: string; full_name: string }>>([]);
  const [student, setStudent] = useState<{ id: string; full_name: string } | null>(null);
  const [form, setForm] = useState({ kind: "RFID", token: "" });
  const [cards, setCards] = useState<CardRow[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    if (q.trim().length < 2) { setMatches([]); return; }
    const timer = setTimeout(() => api<Page<{ id: string; admission_no: string; full_name: string }>>(
      `/students?q=${encodeURIComponent(q.trim())}&limit=10`).then((p) => setMatches(p.items)).catch(() => undefined), 250);
    return () => clearTimeout(timer);
  }, [q]);
  const load = async (id: string) => setCards(await api<CardRow[]>(`/rfid-cards?student_id=${id}`));
  async function issue(e: FormEvent) {
    e.preventDefault();
    if (!student) return;
    try {
      await api("/rfid-cards", { body: { student_id: student.id, ...form } });
      setForm({ ...form, token: "" });
      setError(null);
      await load(student.id);
    } catch (err) {
      setError(err as ApiError);
    }
  }
  async function lose(card: CardRow) {
    try {
      await api(`/rfid-cards/${card.id}`, { method: "PATCH", body: { status: "LOST" } });
      await load(card.student_id);
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <section className="space-y-3">
      <ErrorBox error={error} />
      <Input placeholder={t("search")} aria-label={t("search")} value={q} onChange={(e) => setQ(e.target.value)} />
      <ul className="divide-y text-sm">
        {matches.map((m) => (
          <li key={m.id}><button className="w-full py-1.5 text-left" onClick={() => { setStudent(m); load(m.id); setMatches([]); }}>
            {m.admission_no} · {m.full_name}</button></li>))}
      </ul>
      {student && (
        <>
          <form className="grid gap-2 sm:grid-cols-3 sm:items-end" onSubmit={issue}>
            <p className="text-sm font-semibold sm:col-span-3">{student.full_name}</p>
            <Field label={t("kind")}>
              <Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}><option>RFID</option><option>QR</option></Select>
            </Field>
            <Field label={t("cardToken")}><Input required minLength={4} value={form.token} onChange={(e) => setForm({ ...form, token: e.target.value })} /></Field>
            <Button type="submit">{t("issueCard")}</Button>
          </form>
          <ul className="divide-y text-sm">
            {cards.map((c) => (
              <li key={c.id} className="flex items-center justify-between py-1.5">
                <span>{c.kind} · {c.issued_at.slice(0, 10)}</span>
                <span className="flex items-center gap-2"><Badge>{c.status}</Badge>
                  {c.status === "ACTIVE" && <Button kind="plain" onClick={() => lose(c)}>{t("lost")}</Button>}</span>
              </li>))}
          </ul>
        </>
      )}
    </section>
  );
}

export default function Devices() {
  const [, t] = useLang();
  return (
    <div className="space-y-4">
      <Card title={t("devices")}><DevicesPanel /></Card>
      <Card title={t("cards")}><CardsPanel /></Card>
    </div>
  );
}
