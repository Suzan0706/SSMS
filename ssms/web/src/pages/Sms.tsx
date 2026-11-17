import { useEffect, useState } from "react";

import { useList } from "../academic";
import { api, ApiError } from "../api";
import { clock } from "../dates";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Select } from "../ui";

interface Template { key: string; language: string; body: string; is_active: boolean; customised: boolean; placeholders: string[] }
interface SmsRow { id: string; to: string; template_key: string | null; body: string; segments: number; status: string; queued_at: string; error: string | null }
interface Credit { credits_left: number; low: boolean; history: Array<{ kind: string; credits: number; note: string | null; created_at: string }> }

function TemplateEditor({ template, onSaved }: { template: Template; onSaved: () => void }) {
  const [, t] = useLang();
  const [body, setBody] = useState(template.body);
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState(false);
  useEffect(() => setBody(template.body), [template.body]);
  async function save() {
    try {
      await api(`/message-templates/${template.key}/${template.language}`, { method: "PUT", body: { body, is_active: true } });
      setError(null);
      setDone(true);
      onSaved();
    } catch (e) {
      setError(e as ApiError);
      setDone(false);
    }
  }
  return (
    <li className="space-y-1 py-3">
      <p className="flex flex-wrap items-center gap-2 text-sm font-semibold">{template.key} · {template.language}
        {template.customised && <Badge>✎</Badge>}
        <span className="text-xs font-normal text-slate-500">{template.placeholders.map((p) => `{${p}}`).join(" ")}</span></p>
      <ErrorBox error={error} />
      <textarea rows={2} maxLength={480} value={body} onChange={(e) => { setBody(e.target.value); setDone(false); }}
        aria-label={`${template.key} ${template.language}`} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
      <div className="flex items-center gap-2"><Button kind="plain" onClick={save} disabled={body === template.body}>{t("save")}</Button>
        {done && <span className="text-sm text-brand-700">✓ {t("saved")}</span>}</div>
    </li>
  );
}

export default function Sms() {
  const [, t] = useLang();
  const [templates, reload] = useList<Template>("/message-templates");
  const [status, setStatus] = useState("");
  const [log, setLog] = useState<SmsRow[]>([]);
  const [credit, setCredit] = useState<Credit | null>(null);
  useEffect(() => { api<Credit>("/sms/credit").then(setCredit).catch(() => undefined); }, []);
  useEffect(() => { api<SmsRow[]>(`/sms${status ? `?status=${status}` : ""}`).then(setLog).catch(() => undefined); }, [status]);
  return (
    <div className="space-y-4">
      <Card title={t("smsCredit")}>
        {credit && (
          <div className="space-y-2 text-sm" data-testid="sms-credit">
            <p className="text-2xl font-semibold">{credit.credits_left.toLocaleString("en-US")}</p>
            {credit.low && <p className="text-amber-800" role="alert">⚠ {t("lowCredit")}</p>}
            <ul className="divide-y">
              {credit.history.map((h, i) => <li key={i} className="flex justify-between py-1"><span>{h.created_at.slice(0, 10)} · {h.kind} · {h.note}</span><b>+{h.credits}</b></li>)}
            </ul>
          </div>
        )}
      </Card>
      <Card title={t("templates")}>
        <ul className="divide-y">{templates.map((x) => <TemplateEditor key={`${x.key}|${x.language}`} template={x} onSaved={reload} />)}</ul>
      </Card>
      <Card title={t("smsLog")}>
        <Select aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)} className="mb-2 max-w-xs">
          <option value="">{t("allStatuses")}</option>
          {["QUEUED", "SENT", "DELIVERED", "FAILED", "SKIPPED"].map((s) => <option key={s}>{s}</option>)}
        </Select>
        <ul className="divide-y text-sm">
          {log.map((m) => (
            <li key={m.id} className="py-1.5">
              <p className="flex flex-wrap justify-between gap-2"><span className="font-mono text-xs">{m.to} · {m.template_key ?? ""}</span>
                <span className="text-xs text-slate-500">{m.queued_at.slice(0, 10)} {clock(m.queued_at)} · {m.segments} SMS <Badge>{m.status}</Badge></span></p>
              <p className="text-slate-700">{m.body}</p>
              {m.error && <p className="text-xs text-red-700">{m.error}</p>}
            </li>))}
        </ul>
      </Card>
    </div>
  );
}
