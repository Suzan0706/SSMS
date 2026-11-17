import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, ApiError, download, fieldErrors, objectUrl, Page } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";
import { Column, DataTable, FileUpload, PAGE_SIZE, Uploaded } from "../widgets";
import StudentResults from "./StudentResults";

interface StudentRow {
  id: string;
  admission_no: string;
  full_name: string;
  gender: string;
  status: string;
  class_code: string | null;
  stream_name: string | null;
}

interface Guardian {
  guardian_id: string;
  full_name: string;
  phone: string | null;
  relationship: string;
  is_primary: boolean;
  receives_sms: boolean;
}

interface Student extends StudentRow {
  first_name: string;
  last_name: string;
  date_of_birth: string | null;
  admission_date: string | null;
  enrolment: { class_code: string; stream_name: string; academic_year: string } | null;
  guardians: Guardian[];
}

interface Option {
  id: string;
  label: string;
}

const STATUSES = ["APPLICANT", "ACTIVE", "SUSPENDED", "TRANSFERRED", "GRADUATED", "DROPPED_OUT"];
const RELATIONSHIPS = ["FATHER", "MOTHER", "GUARDIAN", "SPONSOR", "SIBLING", "OTHER"];

export function useStreams(): Option[] {
  const [options, setOptions] = useState<Option[]>([]);
  useEffect(() => {
    Promise.all([
      api<Array<{ id: string; code: string }>>("/classes"),
      api<Array<{ id: string; class_id: string; name: string }>>("/streams"),
    ]).then(([classes, streams]) => {
      const code = new Map(classes.map((c) => [c.id, c.code]));
      const order = new Map(classes.map((c, i) => [c.id, i]));
      setOptions(streams
        .sort((a, b) => (order.get(a.class_id) ?? 0) - (order.get(b.class_id) ?? 0) || a.name.localeCompare(b.name))
        .map((s) => ({ id: s.id, label: `${code.get(s.class_id)} ${s.name}` })));
    }).catch(() => setOptions([]));
  }, []);
  return options;
}

export function StudentList() {
  const auth = useAuth();
  const [, t] = useLang();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setQuery(q.trim()), 250);   // debounce typing
    return () => clearTimeout(timer);
  }, [q]);

  const load = useCallback((cursor: string | null) => {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
    if (query) params.set("q", query);
    if (status) params.set("status", status);
    if (cursor) params.set("cursor", cursor);
    return api<Page<StudentRow>>(`/students?${params}`);
  }, [query, status]);

  const columns: Column<StudentRow>[] = [
    { key: "no", header: t("admissionNo"), className: "font-mono text-xs", render: (s) => s.admission_no, sort: (s) => s.admission_no },
    { key: "name", header: t("name"), sort: (s) => s.full_name,
      render: (s) => <Link className="text-brand-700 hover:underline" to={`/students/${s.id}`}>{s.full_name}</Link> },
    { key: "class", header: t("classStream"), sort: (s) => `${s.class_code ?? ""} ${s.stream_name ?? ""}`,
      render: (s) => (s.class_code ? `${s.class_code} ${s.stream_name}` : t("none")) },
    { key: "status", header: t("status"), render: (s) => <Badge>{s.status}</Badge>, sort: (s) => s.status },
  ];

  return (
    <Card title={t("students")} actions={<span className="flex flex-wrap gap-2">
      {auth.can("students.export") && (
        <Button kind="plain" onClick={() => download(`/exports/students.csv?${new URLSearchParams({ ...(query ? { q: query } : {}), ...(status ? { status } : {}) })}`, "students.csv")}>{t("exportCsv")}</Button>)}
      {auth.can("students.create") && (
        <Link to="/students/new" className="rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-600">{t("addStudent")}</Link>)}
    </span>}>
      <div className="mb-3 flex flex-col gap-2 sm:flex-row">
        <Input placeholder={t("search")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("search")} />
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="sm:w-48" aria-label={t("status")}>
          <option value="">{t("allStatuses")}</option>
          {STATUSES.map((s) => <option key={s}>{s}</option>)}
        </Select>
      </div>
      <DataTable label={t("students")} columns={columns} load={load} reloadKey={`${query}|${status}`} rowKey={(s) => s.id} />
    </Card>
  );
}

const emptyStudent = {
  first_name: "", middle_name: "", last_name: "", gender: "F", date_of_birth: "", birth_cert_no: "", stream_id: "",
  guardian: { first_name: "", last_name: "", gender: "F", phone: "", relationship: "MOTHER", sms_consent: true },
  consent_data_processing: false,
};

export function StudentForm() {
  const [, t] = useLang();
  const navigate = useNavigate();
  const streams = useStreams();
  const [form, setForm] = useState(emptyStudent);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const errors = fieldErrors(error);
  const g = form.guardian;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const student = await api<Student>("/students", {
        body: {
          first_name: form.first_name, middle_name: form.middle_name || null, last_name: form.last_name,
          gender: form.gender, date_of_birth: form.date_of_birth, birth_cert_no: form.birth_cert_no || null,
          stream_id: form.stream_id || null, consent_data_processing: form.consent_data_processing,
          guardians: [{ ...g, is_primary: true }],
        },
      });
      navigate(`/students/${student.id}`, { state: { created: student.admission_no } });
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={t("addStudent")}>
      <ErrorBox error={error} />
      <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={submit}>
        <Field label={t("firstName")} error={errors.first_name}>
          <Input name="first_name" required value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
        </Field>
        <Field label={t("middleName")} error={errors.middle_name}>
          <Input name="middle_name" value={form.middle_name} onChange={(e) => setForm({ ...form, middle_name: e.target.value })} />
        </Field>
        <Field label={t("lastName")} error={errors.last_name}>
          <Input name="last_name" required value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
        </Field>
        <Field label={t("gender")}>
          <Select name="gender" value={form.gender} onChange={(e) => setForm({ ...form, gender: e.target.value })}>
            <option value="F">{t("female")}</option><option value="M">{t("male")}</option>
          </Select>
        </Field>
        <Field label={t("dob")} error={errors.date_of_birth ?? (errors.body && error?.details.some((d) => d.code === "student_age") ? errors.body : undefined)}>
          <Input name="date_of_birth" type="date" required value={form.date_of_birth} onChange={(e) => setForm({ ...form, date_of_birth: e.target.value })} />
        </Field>
        <Field label={t("birthCert")} error={errors.birth_cert_no}>
          <Input name="birth_cert_no" value={form.birth_cert_no} onChange={(e) => setForm({ ...form, birth_cert_no: e.target.value })} />
        </Field>
        <Field label={t("classStream")}>
          <Select name="stream_id" value={form.stream_id} onChange={(e) => setForm({ ...form, stream_id: e.target.value })}>
            <option value="">{t("applicantOnly")}</option>
            {streams.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </Select>
        </Field>

        <h3 className="pt-2 font-semibold sm:col-span-2">{t("guardian")}</h3>
        <Field label={t("firstName")} error={errors["guardians.0.first_name"]}>
          <Input name="guardian_first_name" required value={g.first_name} onChange={(e) => setForm({ ...form, guardian: { ...g, first_name: e.target.value } })} />
        </Field>
        <Field label={t("lastName")} error={errors["guardians.0.last_name"]}>
          <Input name="guardian_last_name" required value={g.last_name} onChange={(e) => setForm({ ...form, guardian: { ...g, last_name: e.target.value } })} />
        </Field>
        <Field label={t("phone")} error={errors["guardians.0.phone"]}>
          <Input name="guardian_phone" type="tel" required placeholder="0754 123 456" value={g.phone} onChange={(e) => setForm({ ...form, guardian: { ...g, phone: e.target.value } })} />
        </Field>
        <Field label={t("relationship")}>
          <Select name="guardian_relationship" value={g.relationship} onChange={(e) => setForm({ ...form, guardian: { ...g, relationship: e.target.value, gender: e.target.value === "FATHER" ? "M" : e.target.value === "MOTHER" ? "F" : g.gender } })}>
            {RELATIONSHIPS.map((r) => <option key={r}>{r}</option>)}
          </Select>
        </Field>
        <label className="flex items-center gap-2 text-sm sm:col-span-2">
          <input type="checkbox" checked={g.sms_consent} onChange={(e) => setForm({ ...form, guardian: { ...g, sms_consent: e.target.checked } })} />
          {t("smsConsent")}
        </label>
        <label className="flex items-start gap-2 text-sm sm:col-span-2">
          <input type="checkbox" name="consent" className="mt-1" checked={form.consent_data_processing} onChange={(e) => setForm({ ...form, consent_data_processing: e.target.checked })} />
          {t("dataConsent")}
        </label>
        <div className="flex gap-2 sm:col-span-2">
          <Button type="submit" disabled={busy || !form.consent_data_processing}>{t("save")}</Button>
          <Button type="button" kind="plain" onClick={() => navigate("/students")}>{t("cancel")}</Button>
        </div>
      </form>
    </Card>
  );
}

/** The student's photograph (FR-78): shown to staff who may see students, changed by those who may edit them. */
function StudentPhoto({ studentId, name, canEdit }: { studentId: string; name: string; canEdit: boolean }) {
  const [, t] = useLang();
  const [src, setSrc] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    let url: string | null = null;
    objectUrl(`/students/${studentId}/photo`).then((u) => { url = u; setSrc(u); }).catch(() => setSrc(null));
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [studentId, version]);
  async function use(file: Uploaded) {
    try {
      await api(`/students/${studentId}/photo`, { method: "PUT", body: { file_id: file.id } });
      setError(null);
      setVersion((v) => v + 1);
    } catch (e) {
      setError(e as ApiError);
    }
  }
  async function remove() {
    await api(`/students/${studentId}/photo`, { method: "DELETE" });
    setVersion((v) => v + 1);
  }
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("");
  return (
    <div className="flex w-36 shrink-0 flex-col items-start gap-2" data-testid="student-photo">
      {src
        ? <img src={src} alt={`${t("photo")}: ${name}`} className="h-36 w-28 rounded-xl object-cover ring-1 ring-slate-200" />
        : <span aria-label={t("noPhoto")} className="flex h-36 w-28 items-center justify-center rounded-xl bg-brand-50 text-3xl font-bold text-brand-300">{initials}</span>}
      {canEdit && (
        <>
          <FileUpload purpose="PHOTO" accept="image/jpeg,image/png" label={src ? t("changePhoto") : t("addPhoto")} onUploaded={use} />
          {src && <button className="text-xs text-red-700 underline" onClick={remove}>{t("removePhoto")}</button>}
          <ErrorBox error={error} />
        </>)}
    </div>
  );
}

export function StudentDetail() {
  const { id } = useParams();
  const auth = useAuth();
  const [, t] = useLang();
  const [student, setStudent] = useState<Student | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [change, setChange] = useState({ new_status: "SUSPENDED", reason: "", effective_date: new Date().toISOString().slice(0, 10) });

  const load = () => api<Student>(`/students/${id}`).then(setStudent).catch((e) => setError(e as ApiError));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [id]);

  async function submitStatus(e: FormEvent) {
    e.preventDefault();
    try {
      await api(`/students/${id}/status`, { body: change });
      setError(null);
      await load();
    } catch (err) {
      setError(err as ApiError);
    }
  }

  if (!student) return <ErrorBox error={error} />;
  return (
    <div className="space-y-4">
      <Link to="/students" className="text-sm text-brand-700">← {t("back")}</Link>
      <Card title={student.full_name} actions={<Badge>{student.status}</Badge>}>
        <div className="flex flex-col gap-5 sm:flex-row">
        <StudentPhoto studentId={student.id} name={student.full_name} canEdit={auth.can("students.update")} />
        <dl className="grid flex-1 content-start gap-2 text-sm sm:grid-cols-3">
          <div><dt className="text-slate-500">{t("admissionNo")}</dt><dd className="font-mono" data-testid="admission-no">{student.admission_no}</dd></div>
          <div><dt className="text-slate-500">{t("classStream")}</dt><dd>{student.enrolment ? `${student.enrolment.class_code} ${student.enrolment.stream_name} (${student.enrolment.academic_year})` : t("none")}</dd></div>
          <div><dt className="text-slate-500">{t("dob")}</dt><dd>{student.date_of_birth ?? t("none")}</dd></div>
        </dl>
        </div>
      </Card>
      <Card title={t("guardians")}>
        <ul className="divide-y text-sm">
          {student.guardians.map((g) => (
            <li key={g.guardian_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>{g.full_name} · {g.relationship} {g.is_primary && <Badge>{t("primary")}</Badge>}</span>
              <span className="font-mono text-xs">{g.phone}</span>
            </li>
          ))}
        </ul>
      </Card>
      {(auth.can("results.read") || auth.can("portal.parent")) && <StudentResults studentId={id!} />}
      {auth.can("students.status") && (
        <Card title={t("changeStatus")}>
          <ErrorBox error={error} />
          <form className="mt-2 grid gap-3 sm:grid-cols-4" onSubmit={submitStatus}>
            <Select value={change.new_status} onChange={(e) => setChange({ ...change, new_status: e.target.value })} aria-label={t("status")}>
              {STATUSES.filter((s) => s !== student.status).map((s) => <option key={s}>{s}</option>)}
            </Select>
            <Input required minLength={3} placeholder={t("reason")} value={change.reason} onChange={(e) => setChange({ ...change, reason: e.target.value })} />
            <Input type="date" required value={change.effective_date} onChange={(e) => setChange({ ...change, effective_date: e.target.value })} aria-label={t("effectiveDate")} />
            <Button type="submit">{t("save")}</Button>
          </form>
        </Card>
      )}
    </div>
  );
}
