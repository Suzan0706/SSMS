// Certificates and ID cards (FR-94, FR-95), with staff photographs for staff cards (FR-78).
import { FormEvent, useCallback, useEffect, useState } from "react";

import { api, ApiError, download } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import StudentPicker, { PickedStudent } from "../StudentPicker";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";
import { FileUpload, Modal, Tabs, Uploaded, useConfirm } from "../widgets";
import { useStreams } from "./Students";

interface Template { id: string; kind: string; name: string; language: string; body: string }
interface CertificateRow { id: string; serial_no: string; kind: string; template: string; student: string; admission_no: string; issued_on: string; revoked: boolean; revoked_reason: string | null }
interface IdCard { id: string; user_id: string; card_no: string; valid_until: string; full_name: string; kind: string; number: string | null; role: string; has_photo: boolean }
interface StaffRow { id: string; user_id: string }

const KINDS = ["LEAVING", "TRANSFER", "CHARACTER", "ACHIEVEMENT"];
const PLACEHOLDERS = "{{name}} {{admission_no}} {{class}} {{date_of_birth}} {{school}} {{issued_on}} {{year}}";

function Certificates() {
  const [lang, t] = useLang();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [rows, setRows] = useState<CertificateRow[]>([]);
  const [tpl, setTpl] = useState({ kind: "LEAVING", name: "", language: "sw", body: "" });
  const [templateId, setTemplateId] = useState("");
  const [picked, setPicked] = useState<PickedStudent[]>([]);
  const [issuedOn, setIssuedOn] = useState(new Date().toISOString().slice(0, 10));
  const [revoking, setRevoking] = useState<CertificateRow | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const load = useCallback(() => {
    api<Template[]>("/certificate-templates").then((list) => { setTemplates(list); if (!templateId && list[0]) setTemplateId(list[0].id); }).catch(() => undefined);
    api<CertificateRow[]>("/certificates").then(setRows).catch(() => undefined);
  }, [templateId]);
  useEffect(load, [load]);

  async function act(action: () => Promise<unknown>) {
    try {
      await action();
      setError(null);
      load();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  function saveTemplate(e: FormEvent) {
    e.preventDefault();
    act(async () => { await api("/certificate-templates", { body: tpl }); setTpl({ ...tpl, name: "", body: "" }); });
  }
  function issue(e: FormEvent) {
    e.preventDefault();
    act(async () => { await api("/certificates", { body: { template_id: templateId, student_ids: picked.map((p) => p.id), issued_on: issuedOn } }); setPicked([]); });
  }
  return (
    <div className="space-y-6">
      <ErrorBox error={error} />
      <form onSubmit={issue} className="grid gap-3 rounded-xl bg-slate-50 p-4 sm:grid-cols-3">
        <Field label={t("template")}>
          <Select aria-label={t("template")} required value={templateId} onChange={(e) => setTemplateId(e.target.value)}>{templates.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</Select>
        </Field>
        <Field label={t("issuedOn")}><Input type="date" required value={issuedOn} onChange={(e) => setIssuedOn(e.target.value)} /></Field>
        <div className="sm:col-span-3">
          <StudentPicker onPick={(s) => setPicked((old) => (old.some((o) => o.id === s.id) ? old : [...old, s]))} />
          <p className="mt-2 flex flex-wrap gap-2 text-sm">
            {picked.map((p) => <button type="button" key={p.id} onClick={() => setPicked(picked.filter((x) => x.id !== p.id))}><Badge>{p.full_name} ✕</Badge></button>)}
          </p>
        </div>
        <div className="sm:col-span-3"><Button type="submit" disabled={!templateId || picked.length === 0}>{t("issueCertificates")}</Button></div>
      </form>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm" aria-label={t("certificates")}>
          <thead><tr><th className="py-2 pr-3">#</th><th className="pr-3">{t("name")}</th><th className="pr-3">{t("template")}</th><th className="pr-3">{t("issuedOn")}</th><th className="pr-3">{t("status")}</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-slate-100 last:border-0">
                <td className="py-2 pr-3 font-mono text-xs">{r.serial_no}</td><td className="pr-3">{r.student} <span className="text-xs text-slate-500">{r.admission_no}</span></td>
                <td className="pr-3">{r.template}</td><td className="pr-3">{r.issued_on}</td>
                <td className="pr-3">{r.revoked ? <Badge>REVOKED</Badge> : <Badge>ACTIVE</Badge>}</td>
                <td><span className="flex gap-2">
                  <Button kind="plain" onClick={() => download(`/certificates/${r.id}.pdf?lang=${lang}`, `${r.serial_no}.pdf`)}>PDF</Button>
                  {!r.revoked && <Button kind="plain" onClick={() => setRevoking(r)}>{t("revokeCard")}</Button>}
                </span></td>
              </tr>))}
          </tbody>
        </table>
      </div>

      <form onSubmit={saveTemplate} className="grid gap-3 border-t border-slate-100 pt-4 sm:grid-cols-3">
        <h3 className="text-sm font-semibold sm:col-span-3">{t("newTemplate")}</h3>
        <Field label={t("kindLabel")}><Select value={tpl.kind} onChange={(e) => setTpl({ ...tpl, kind: e.target.value })}>{KINDS.map((k) => <option key={k}>{k}</option>)}</Select></Field>
        <Field label={t("name")}><Input required minLength={2} maxLength={80} value={tpl.name} onChange={(e) => setTpl({ ...tpl, name: e.target.value })} /></Field>
        <Field label={t("language")}><Select value={tpl.language} onChange={(e) => setTpl({ ...tpl, language: e.target.value })}><option value="sw">Kiswahili</option><option value="en">English</option></Select></Field>
        <div className="sm:col-span-3">
          <Field label={t("templateText")}><textarea className="control" rows={4} required minLength={10} maxLength={4000} value={tpl.body} onChange={(e) => setTpl({ ...tpl, body: e.target.value })} /></Field>
          <p className="mt-1 text-xs text-slate-500">{t("placeholdersHint")}: <code>{PLACEHOLDERS}</code></p>
        </div>
        <div className="sm:col-span-3"><Button type="submit" kind="plain">{t("save")}</Button></div>
      </form>

      <Modal open={revoking !== null} title={`${t("revokeCard")}: ${revoking?.serial_no ?? ""}`} onClose={() => setRevoking(null)}
        footer={<><Button kind="plain" onClick={() => setRevoking(null)}>{t("cancel")}</Button>
          <Button disabled={reason.trim().length < 5} onClick={() => act(async () => { await api(`/certificates/${revoking!.id}/revoke`, { body: { reason } }); setRevoking(null); setReason(""); })}>{t("revokeCard")}</Button></>}>
        <Field label={t("reason")}><Input minLength={5} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </Modal>
    </div>
  );
}

function IdCards() {
  const auth = useAuth();
  const [lang, t] = useLang();
  const streams = useStreams();
  const [target, setTarget] = useState("");                  // a stream id, or "staff"
  const [cards, setCards] = useState<IdCard[]>([]);
  const [staffIds, setStaffIds] = useState<Map<string, string>>(new Map());   // user id -> staff id
  const [notice, setNotice] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [confirm, confirmDialog] = useConfirm();
  useEffect(() => { if (!target && streams[0]) setTarget(streams[0].id); }, [streams, target]);
  const query = target === "staff" ? "staff=true" : `stream_id=${target}`;
  const load = useCallback(() => {
    if (!target) return;
    api<IdCard[]>(`/identity-cards?${query}`).then(setCards).catch(() => setCards([]));
  }, [target, query]);
  useEffect(load, [load]);
  useEffect(() => {
    if (target === "staff") api<{ items: StaffRow[] }>("/staff?limit=50").then((p) => setStaffIds(new Map(p.items.map((s) => [s.user_id, s.id])))).catch(() => undefined);
  }, [target]);

  async function issue() {
    try {
      const out = await api<{ issued: number }>("/identity-cards", { body: target === "staff" ? { staff: true } : { stream_id: target } });
      setNotice(`${t("cardsIssued")}: ${out.issued}`);
      setError(null);
      load();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  async function setPhoto(card: IdCard, file: Uploaded) {
    const staffId = staffIds.get(card.user_id);
    if (!staffId) return;
    try {
      await api(`/staff/${staffId}/photo`, { method: "PUT", body: { file_id: file.id } });
      load();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  return (
    <div className="space-y-3">
      {confirmDialog}
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t("forWhom")}>
          <Select aria-label={t("forWhom")} value={target} onChange={(e) => setTarget(e.target.value)}>
            {streams.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            <option value="staff">{t("staff")}</option>
          </Select>
        </Field>
        <Button onClick={issue} disabled={!target}>{t("issueCards")}</Button>
        {cards.length > 0 && <Button kind="plain" onClick={() => download(`/identity-cards.pdf?${query}&lang=${lang}`, "id-cards.pdf").catch((e) => setError(e))}>{t("printCards")}</Button>}
        {notice && <span role="status" className="text-sm text-brand-700">✓ {notice}</span>}
      </div>
      <p className="text-xs text-slate-500">{t("idCardNote")}</p>
      <ErrorBox error={error} />
      <ul className="divide-y text-sm" data-testid="id-cards">
        {cards.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
            <span><span className="font-mono text-xs">{c.card_no}</span> · {c.full_name} <span className="text-slate-500">{c.number} {c.role}</span>
              {!c.has_photo && <span className="ml-2"><Badge>{t("noPhoto")}</Badge></span>}</span>
            <span className="flex items-center gap-2">
              {target === "staff" && auth.can("staff.manage") && staffIds.has(c.user_id) && (
                <FileUpload purpose="PHOTO" accept="image/jpeg,image/png" label={c.has_photo ? t("changePhoto") : t("addPhoto")} onUploaded={(f) => setPhoto(c, f)} />)}
              <Button kind="plain" onClick={async () => { if (await confirm(`${c.card_no} · ${c.full_name}`, t("revokeCard"))) { await api(`/identity-cards/${c.id}/revoke`, { method: "POST" }); load(); } }}>{t("revokeCard")}</Button>
            </span>
          </li>))}
        {cards.length === 0 && <li className="py-2 text-slate-500">{t("noResults")}</li>}
      </ul>
    </div>
  );
}

export default function Documents() {
  const auth = useAuth();
  const [, t] = useLang();
  type Tab = "certificates" | "cards";
  const tabs: Array<[Tab, string]> = [];
  if (auth.can("certificates.issue")) tabs.push(["certificates", t("certificates")]);
  if (auth.can("cards.print")) tabs.push(["cards", t("idCards")]);
  const [tab, setTab] = useState<Tab>(tabs[0]?.[0] ?? "cards");
  return (
    <Card title={t("documentsTitle")}>
      <Tabs label={t("documentsTitle")} tabs={tabs} value={tab} onChange={setTab} />
      {tab === "certificates" ? <Certificates /> : <IdCards />}
    </Card>
  );
}
