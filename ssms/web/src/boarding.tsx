import { FormEvent, useCallback, useEffect, useState } from "react";

import { nameOf, useCurrentTerm } from "./academic";
import { api, ApiError } from "./api";
import { useLang } from "./i18n";
import { Badge, Button, ErrorBox, Field, Select } from "./ui";

interface Hostel { id: string; name: string; gender: string }
interface Request { id: string; student_id: string; term_id: string; status: string; room: string | null }

/** A student asks for a bed for themselves; a guardian passes the child's id. Shows the request's status. */
export default function BoardingRequest({ studentId }: { studentId?: string }) {
  const [lang, t] = useLang();
  const { terms, termId, setTermId } = useCurrentTerm();
  const [hostels, setHostels] = useState<Hostel[]>([]);
  const [hostelId, setHostelId] = useState("");
  const [mine, setMine] = useState<Request[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const load = useCallback(() => api<Request[]>("/accommodation-requests").then(setMine).catch(() => undefined), []);
  useEffect(() => {
    api<Hostel[]>("/hostels").then(setHostels).catch(() => undefined);
    load();
  }, [load]);
  const current = mine.find((r) => r.term_id === termId && (!studentId || r.student_id === studentId) && r.status !== "CANCELLED");
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api("/accommodation-requests", { body: { term_id: termId, student_id: studentId ?? null, preferred_hostel_id: hostelId || null } });
      setError(null);
      load();
    } catch (err) {
      setError(err as ApiError);
    }
  }
  async function cancel(id: string) {
    await api(`/accommodation-requests/${id}/cancel`, { method: "POST" });
    load();
  }
  const word: Record<string, string> = { PENDING: t("awaitingApproval"), APPROVED: t("approved"), REJECTED: t("reject") };
  return (
    <form className="space-y-2 text-sm" onSubmit={submit} data-testid="boarding">
      <ErrorBox error={error} />
      <div className="grid gap-2 sm:grid-cols-3 sm:items-end">
        <Field label={t("term")}>
          <Select value={termId} onChange={(e) => setTermId(e.target.value)}>
            {terms.map((x) => <option key={x.id} value={x.id}>{nameOf(x, lang)}</option>)}
          </Select>
        </Field>
        {!current && (
          <>
            <Field label={t("hostels")}>
              <Select value={hostelId} onChange={(e) => setHostelId(e.target.value)}>
                <option value="">—</option>{hostels.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
              </Select>
            </Field>
            <Button type="submit" disabled={!termId}>{t("requestBed")}</Button>
          </>
        )}
      </div>
      {current && (
        <p className="flex flex-wrap items-center gap-2">
          <Badge>{word[current.status] ?? current.status}</Badge>{current.room && <b>{current.room}</b>}
          {current.status === "PENDING" && <button type="button" className="text-red-700 underline" onClick={() => cancel(current.id)}>{t("cancel")}</button>}
        </p>
      )}
    </form>
  );
}
