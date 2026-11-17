// Front desk: admission inquiries, follow-ups, and turning an inquiry into an application (FR-77).
import { FormEvent, useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Named, useCurrentTerm, useList } from "../academic";
import { api, ApiError, fieldErrors, Page } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";
import { Column, DataTable, Modal, PAGE_SIZE } from "../widgets";

interface Inquiry {
  id: string;
  full_name: string;
  phone: string | null;
  email: string | null;
  class_id: string | null;
  source: string;
  message: string | null;
  follow_up_on: string | null;
  notes: string | null;
  status: string;
  application_id: string | null;
  created_at: string;
}

const SOURCES = ["WALK_IN", "PHONE", "WEBSITE", "REFERRAL", "OTHER"];
const blank = { full_name: "", phone: "", email: "", class_id: "", source: "WALK_IN", message: "", follow_up_on: "" };

export default function Inquiries() {
  const auth = useAuth();
  const [, t] = useLang();
  const [classes] = useList<Named>("/classes");
  const className = new Map(classes.map((c) => [c.id, c.code]));
  const [form, setForm] = useState(blank);
  const [error, setError] = useState<ApiError | null>(null);
  const [filter, setFilter] = useState<"OPEN" | "due" | "CONVERTED" | "CLOSED" | "">("OPEN");
  const [version, setVersion] = useState(0);
  const [editing, setEditing] = useState<Inquiry | null>(null);
  const [converting, setConverting] = useState<Inquiry | null>(null);

  const load = useCallback((cursor: string | null) => {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
    if (filter === "due") params.set("due", "true");
    else if (filter) params.set("status", filter);
    if (cursor) params.set("cursor", cursor);
    return api<Page<Inquiry>>(`/inquiries?${params}`);
  }, [filter]);

  async function create(e: FormEvent) {
    e.preventDefault();
    const body = Object.fromEntries(Object.entries(form).filter(([, v]) => v !== ""));
    try {
      await api("/inquiries", { body });
      setForm(blank);
      setError(null);
      setVersion((v) => v + 1);
    } catch (err) {
      setError(err as ApiError);
    }
  }

  const today = new Date().toISOString().slice(0, 10);
  const columns: Column<Inquiry>[] = [
    { key: "name", header: t("name"), sort: (r) => r.full_name, render: (r) => (
      <span><b>{r.full_name}</b>{r.message && <span className="block text-xs text-slate-500">{r.message}</span>}</span>) },
    { key: "contact", header: t("contact"), render: (r) => <span className="text-xs">{r.phone ?? ""}{r.email ? ` ${r.email}` : ""}</span> },
    { key: "class", header: t("classWanted"), render: (r) => (r.class_id ? className.get(r.class_id) : "—") },
    { key: "follow", header: t("followUp"), sort: (r) => r.follow_up_on ?? "9999",
      render: (r) => r.follow_up_on && (
        <span className={r.status === "OPEN" && r.follow_up_on <= today ? "font-semibold text-red-700" : ""}>{r.follow_up_on}</span>) },
    { key: "status", header: t("status"), render: (r) => <Badge>{r.status}</Badge> },
    { key: "actions", header: "", render: (r) => r.status === "OPEN" && (
      <span className="flex flex-wrap gap-2">
        <Button kind="plain" onClick={() => setEditing(r)}>{t("followUp")}</Button>
        {auth.can("enrolment.manage") && <Button onClick={() => setConverting(r)}>{t("makeApplication")}</Button>}
      </span>) },
  ];

  return (
    <div className="space-y-4">
      <Card title={t("newInquiry")}>
        <form onSubmit={create} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label={t("name")} error={fieldErrors(error).full_name}>
            <Input required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          </Field>
          <Field label={t("phone")} error={fieldErrors(error).phone}>
            <Input type="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          </Field>
          <Field label={t("email")} error={fieldErrors(error).email}>
            <Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Field>
          <Field label={t("classWanted")}>
            <Select value={form.class_id} onChange={(e) => setForm({ ...form, class_id: e.target.value })}>
              <option value="">—</option>
              {classes.map((c) => <option key={c.id} value={c.id}>{c.code}</option>)}
            </Select>
          </Field>
          <Field label={t("source")}>
            <Select value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}>
              {SOURCES.map((s) => <option key={s}>{s}</option>)}
            </Select>
          </Field>
          <Field label={t("followUp")}>
            <Input type="date" value={form.follow_up_on} onChange={(e) => setForm({ ...form, follow_up_on: e.target.value })} />
          </Field>
          <div className="sm:col-span-2">
            <Field label={t("message")}>
              <Input value={form.message} maxLength={500} onChange={(e) => setForm({ ...form, message: e.target.value })} />
            </Field>
          </div>
          <div className="sm:col-span-2 lg:col-span-4">
            <ErrorBox error={error} />
            <Button type="submit" className="mt-2">{t("save")}</Button>
          </div>
        </form>
      </Card>

      <Card title={t("inquiries")}>
        <div className="mb-3 max-w-xs">
          <Select aria-label={t("status")} value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
            <option value="OPEN">{t("openInquiries")}</option>
            <option value="due">{t("followUpDue")}</option>
            <option value="CONVERTED">{t("converted")}</option>
            <option value="CLOSED">{t("closed")}</option>
            <option value="">{t("allStatuses")}</option>
          </Select>
        </div>
        <DataTable label={t("inquiries")} columns={columns} load={load} reloadKey={`${filter}|${version}`} rowKey={(r) => r.id} />
      </Card>

      {editing && <FollowUp inquiry={editing} onDone={() => { setEditing(null); setVersion((v) => v + 1); }} />}
      {converting && <Convert inquiry={converting} onClose={() => setConverting(null)} />}
    </div>
  );
}

function FollowUp({ inquiry, onDone }: { inquiry: Inquiry; onDone: () => void }) {
  const [, t] = useLang();
  const [notes, setNotes] = useState(inquiry.notes ?? "");
  const [next, setNext] = useState(inquiry.follow_up_on ?? "");
  const [error, setError] = useState<ApiError | null>(null);
  async function save(close: boolean) {
    try {
      await api(`/inquiries/${inquiry.id}`, { method: "PATCH", body: { notes, follow_up_on: next || null, ...(close ? { status: "CLOSED" } : {}) } });
      onDone();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  return (
    <Modal open title={`${t("followUp")}: ${inquiry.full_name}`} onClose={onDone}
      footer={<>
        <Button kind="plain" onClick={() => save(true)}>{t("closeInquiry")}</Button>
        <Button onClick={() => save(false)}>{t("save")}</Button>
      </>}>
      <div className="space-y-3">
        <Field label={t("notes")}><textarea className="control" rows={4} maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        <Field label={t("nextFollowUp")}><Input type="date" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
        <ErrorBox error={error} />
      </div>
    </Modal>
  );
}

/** The application is made from the inquiry: the desk adds what the inquiry did not have (birth date, guardian). */
function Convert({ inquiry, onClose }: { inquiry: Inquiry; onClose: () => void }) {
  const [, t] = useLang();
  const navigate = useNavigate();
  const { year } = useCurrentTerm();
  const [classes] = useList<Named>("/classes");
  const [first, ...rest] = inquiry.full_name.split(/\s+/);
  const [f, setF] = useState({
    first_name: first, last_name: rest.join(" "), gender: "F", date_of_birth: "", class_id: inquiry.class_id ?? "",
    guardian_first: "", guardian_last: rest[rest.length - 1] ?? "", guardian_gender: "F", relationship: "MOTHER", phone: inquiry.phone ?? "",
  });
  const [error, setError] = useState<ApiError | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api(`/inquiries/${inquiry.id}/convert`, { body: { application: {
        class_id: f.class_id, academic_year_id: year?.id, consent_data_processing: true,
        applicant: { first_name: f.first_name, last_name: f.last_name, gender: f.gender, date_of_birth: f.date_of_birth },
        guardians: [{ first_name: f.guardian_first, last_name: f.guardian_last, gender: f.guardian_gender, phone: f.phone,
          relationship: f.relationship, is_primary: true, sms_consent: true }],
      } } });
      navigate("/enrolment");
    } catch (err) {
      setError(err as ApiError);
    }
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal open title={`${t("makeApplication")}: ${inquiry.full_name}`} onClose={onClose}>
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        <Field label={t("firstName")}><Input required value={f.first_name} onChange={set("first_name")} /></Field>
        <Field label={t("lastName")}><Input required value={f.last_name} onChange={set("last_name")} /></Field>
        <Field label={t("gender")}><Select value={f.gender} onChange={set("gender")}><option value="F">{t("female")}</option><option value="M">{t("male")}</option></Select></Field>
        <Field label={t("dateOfBirth")}><Input type="date" required value={f.date_of_birth} onChange={set("date_of_birth")} /></Field>
        <Field label={t("classWanted")}>
          <Select required value={f.class_id} onChange={set("class_id")}><option value="">—</option>{classes.map((c) => <option key={c.id} value={c.id}>{c.code}</option>)}</Select>
        </Field>
        <Field label={t("phone")}><Input type="tel" required value={f.phone} onChange={set("phone")} /></Field>
        <Field label={`${t("guardian")}: ${t("firstName")}`}><Input required value={f.guardian_first} onChange={set("guardian_first")} /></Field>
        <Field label={`${t("guardian")}: ${t("lastName")}`}><Input required value={f.guardian_last} onChange={set("guardian_last")} /></Field>
        <Field label={t("relationship")}>
          <Select value={f.relationship} onChange={set("relationship")}>{["MOTHER", "FATHER", "GUARDIAN", "SPONSOR", "SIBLING", "OTHER"].map((r) => <option key={r}>{r}</option>)}</Select>
        </Field>
        <Field label={`${t("guardian")}: ${t("gender")}`}><Select value={f.guardian_gender} onChange={set("guardian_gender")}><option value="F">{t("female")}</option><option value="M">{t("male")}</option></Select></Field>
        <div className="sm:col-span-2">
          <ErrorBox error={error} />
          <div className="mt-3 flex justify-end gap-2">
            <Button type="button" kind="plain" onClick={onClose}>{t("cancel")}</Button>
            <Button type="submit">{t("makeApplication")}</Button>
          </div>
        </div>
      </form>
    </Modal>
  );
}
