import { FormEvent, Fragment, useEffect, useState } from "react";

import { api, ApiError, download, fieldErrors, Page } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";

interface StaffRow {
  id: string;
  staff_no: string;
  full_name: string;
  department_id: string | null;
  employment_type: string;
  status: string;
}

interface Named {
  id: string;
  code: string;
  name_en: string;
  name_sw: string;
}

const emptyStaff = {
  first_name: "", last_name: "", gender: "F", phone: "", email: "", staff_no: "", department_id: "",
  designation_id: "", employment_type: "PERMANENT",
};

/** The subjects a teacher may be timetabled for; the timetable refuses anyone else. */
function SubjectsPanel({ staffId, subjects, canEdit }: { staffId: string; subjects: Named[]; canEdit: boolean }) {
  const [lang, t] = useLang();
  const [chosen, setChosen] = useState<Set<string> | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    api<Array<{ subject_id: string }>>(`/staff/${staffId}/subjects`)
      .then((r) => setChosen(new Set(r.map((x) => x.subject_id))))
      .catch(setError);
  }, [staffId]);

  function toggle(id: string) {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id); else next.add(id);
    setChosen(next);
    setSaved(false);
  }
  async function save() {
    setError(null);
    try {
      await api(`/staff/${staffId}/subjects`, { method: "PUT", body: { subject_ids: [...chosen!] } });
      setSaved(true);
    } catch (e) { setError(e as ApiError); }
  }

  return (
    <div className="space-y-2 py-2" data-testid="staff-subjects">
      <ErrorBox error={error} />
      {chosen && (
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {subjects.map((s) => (
            <label key={s.id} className="text-sm">
              <input type="checkbox" className="mr-1" disabled={!canEdit} checked={chosen.has(s.id)} onChange={() => toggle(s.id)} />
              {lang === "sw" ? s.name_sw : s.name_en}
            </label>
          ))}
        </div>
      )}
      {canEdit && chosen && <Button kind="plain" onClick={save}>{t("save")}</Button>}
      {saved && <span className="ml-2 text-sm text-green-700" role="status">✓</span>}
    </div>
  );
}

export default function Staff() {
  const auth = useAuth();
  const [lang, t] = useLang();
  const [rows, setRows] = useState<StaffRow[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [departments, setDepartments] = useState<Named[]>([]);
  const [designations, setDesignations] = useState<Named[]>([]);
  const [subjects, setSubjects] = useState<Named[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState(emptyStaff);
  const [created, setCreated] = useState<{ username: string; temporary_password: string } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const errors = fieldErrors(error);
  const name = (n: Named) => (lang === "sw" ? n.name_sw : n.name_en);

  async function showSubjects(id: string) {
    if (!subjects.length) setSubjects(await api<Named[]>("/subjects"));
    setOpenId(openId === id ? null : id);
  }

  async function load(next: string | null) {
    const params = new URLSearchParams({ limit: "50" });
    if (q.trim()) params.set("q", q.trim());
    if (next) params.set("cursor", next);
    const page = await api<Page<StaffRow>>(`/staff?${params}`);
    setRows((old) => (next ? [...old, ...page.items] : page.items));
    setCursor(page.next_cursor);
  }

  useEffect(() => {
    const timer = setTimeout(() => load(null).catch((e) => setError(e)), 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);
  useEffect(() => {
    api<Named[]>("/departments").then(setDepartments).catch(() => undefined);
    api<Named[]>("/designations").then(setDesignations).catch(() => undefined);
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const out = await api<{ username: string; temporary_password: string }>("/staff", {
        body: {
          person: { first_name: form.first_name, last_name: form.last_name, gender: form.gender, phone: form.phone,
            email: form.email || null },
          staff_no: form.staff_no, department_id: form.department_id || null,
          designation_id: form.designation_id || null, employment_type: form.employment_type,
        },
      });
      setCreated(out);
      setForm(emptyStaff);
      setAdding(false);
      await load(null);
    } catch (err) {
      setError(err as ApiError);
    }
  }

  const departmentName = new Map(departments.map((d) => [d.id, name(d)]));
  return (
    <div className="space-y-4">
      {created && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm" role="status">
          <p className="font-semibold">{t("tempPassword")}</p>
          <p className="font-mono" data-testid="temp-password">{created.username} / {created.temporary_password}</p>
          <p className="text-amber-800">{t("tempPasswordNote")}</p>
        </div>
      )}
      {adding && (
        <Card title={t("addStaff")}>
          <ErrorBox error={error} />
          <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={submit}>
            <Field label={t("firstName")} error={errors["person.first_name"]}>
              <Input name="first_name" required value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
            </Field>
            <Field label={t("lastName")} error={errors["person.last_name"]}>
              <Input name="last_name" required value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
            </Field>
            <Field label={t("gender")}>
              <Select name="gender" value={form.gender} onChange={(e) => setForm({ ...form, gender: e.target.value })}>
                <option value="F">{t("female")}</option><option value="M">{t("male")}</option>
              </Select>
            </Field>
            <Field label={t("phone")} error={errors["person.phone"]}>
              <Input name="phone" type="tel" required value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </Field>
            <Field label={t("staffNo")} error={errors.staff_no}>
              <Input name="staff_no" required value={form.staff_no} onChange={(e) => setForm({ ...form, staff_no: e.target.value })} />
            </Field>
            <Field label={t("employmentType")}>
              <Select name="employment_type" value={form.employment_type} onChange={(e) => setForm({ ...form, employment_type: e.target.value })}>
                {["PERMANENT", "CONTRACT", "VOLUNTEER", "INTERN"].map((x) => <option key={x}>{x}</option>)}
              </Select>
            </Field>
            <Field label={t("department")}>
              <Select name="department_id" value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })}>
                <option value="">{t("none")}</option>
                {departments.map((d) => <option key={d.id} value={d.id}>{name(d)}</option>)}
              </Select>
            </Field>
            <Field label={t("designation")}>
              <Select name="designation_id" value={form.designation_id} onChange={(e) => setForm({ ...form, designation_id: e.target.value })}>
                <option value="">{t("none")}</option>
                {designations.map((d) => <option key={d.id} value={d.id}>{name(d)}</option>)}
              </Select>
            </Field>
            <div className="flex gap-2 sm:col-span-2">
              <Button type="submit">{t("save")}</Button>
              <Button type="button" kind="plain" onClick={() => setAdding(false)}>{t("cancel")}</Button>
            </div>
          </form>
        </Card>
      )}
      <Card title={t("staff")} actions={<span className="flex flex-wrap gap-2">
        <Button kind="plain" onClick={() => download("/exports/staff.csv", "staff.csv")}>{t("exportCsv")}</Button>
        {auth.can("staff.manage") && !adding && (
          <Button onClick={() => { setAdding(true); setCreated(null); }}>{t("addStaff")}</Button>)}
      </span>}>
        <Input placeholder={t("search")} value={q} onChange={(e) => setQ(e.target.value)} className="mb-3" aria-label={t("search")} />
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b text-xs uppercase text-slate-500">
              <tr><th className="py-2 pr-3">{t("staffNo")}</th><th className="pr-3">{t("name")}</th>
                <th className="pr-3">{t("department")}</th><th className="pr-3">{t("status")}</th><th /></tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <Fragment key={s.id}>
                  <tr className="border-b last:border-0">
                    <td className="py-2 pr-3 font-mono text-xs">{s.staff_no}</td>
                    <td className="pr-3">{s.full_name}</td>
                    <td className="pr-3">{(s.department_id && departmentName.get(s.department_id)) || t("none")}</td>
                    <td className="pr-3"><Badge>{s.status}</Badge></td>
                    <td><Button kind="plain" onClick={() => showSubjects(s.id)}>{t("qualifiedSubjects")}</Button></td>
                  </tr>
                  {openId === s.id && (
                    <tr className="border-b"><td colSpan={5}>
                      <SubjectsPanel staffId={s.id} subjects={subjects} canEdit={auth.can("staff.manage", "timetable.manage")} />
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {cursor && <Button kind="plain" className="mt-3" onClick={() => load(cursor)}>{t("loadMore")}</Button>}
      </Card>
    </div>
  );
}
