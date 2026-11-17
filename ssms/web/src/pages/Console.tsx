// The platform operators' console (FR-75): its own sign-in, a token kept in memory only, and counts per school.
// It never shows a learner's name or any school's records, only totals.
import { FormEvent, useEffect, useState } from "react";

import { BASE } from "../api";
import { useLang } from "../i18n";
import { Badge, Button, Card, Field, Input } from "../ui";

interface SchoolCount { id: string; code: string; name: string; status: string; students: number; staff: number; sms_credit: number }
interface Board { schools: number; by_status: Record<string, number>; students: number; staff: number; per_school: SchoolCount[] }

async function call<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!res.ok) throw new Error(String(res.status));
  return res.json() as Promise<T>;
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-2xl font-semibold tabular-nums">{value.toLocaleString()}</p>
    </div>
  );
}

export default function Console() {
  const [, t] = useLang();
  const [token, setToken] = useState<string | null>(null);
  const [form, setForm] = useState({ email: "", password: "", totp: "" });
  const [board, setBoard] = useState<Board | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (token) call<Board>("/platform/dashboard", {}, token).then(setBoard).catch(() => setToken(null));
  }, [token]);

  async function signIn(e: FormEvent) {
    e.preventDefault();
    try {
      const out = await call<{ access_token: string }>("/platform/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: form.email, password: form.password, totp: form.totp || null }),
      });
      setForm({ ...form, password: "", totp: "" });
      setFailed(false);
      setToken(out.access_token);
    } catch {
      setFailed(true);
    }
  }

  if (!token) {
    return (
      <main className="mx-auto max-w-sm px-4 py-12">
        <Card title={t("platformConsole")}>
          <form className="space-y-3" onSubmit={signIn}>
            <Field label={t("email")}><Input type="email" required autoComplete="username" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
            <Field label={t("password")}><Input type="password" required autoComplete="current-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
            <Field label={t("totpCode")}><Input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" value={form.totp} onChange={(e) => setForm({ ...form, totp: e.target.value })} /></Field>
            {failed && <p role="alert" className="text-sm text-red-700">{t("invalid")}</p>}
            <Button type="submit">{t("signIn")}</Button>
          </form>
        </Card>
      </main>
    );
  }
  return (
    <main className="mx-auto max-w-5xl space-y-4 px-4 py-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t("platformConsole")}</h1>
        <Button kind="plain" onClick={() => { setToken(null); setBoard(null); }}>{t("signOut")}</Button>
      </div>
      {!board ? <p className="text-sm text-slate-500">{t("loading")}</p> : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label={t("schools")} value={board.schools} />
            <Stat label={t("students")} value={board.students} />
            <Stat label={t("staff")} value={board.staff} />
          </div>
          <Card title={t("schools")}>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm" aria-label={t("schools")}>
                <thead><tr className="text-slate-500"><th className="py-2 pr-3">{t("name")}</th><th className="pr-3">{t("status")}</th>
                  <th className="pr-3 text-right">{t("students")}</th><th className="pr-3 text-right">{t("staff")}</th><th className="text-right">SMS</th></tr></thead>
                <tbody>
                  {board.per_school.map((s) => (
                    <tr key={s.id} className="border-t border-slate-100">
                      <td className="py-2 pr-3">{s.name} <span className="font-mono text-xs text-slate-500">{s.code}</span></td>
                      <td className="pr-3"><Badge>{s.status}</Badge></td>
                      <td className="pr-3 text-right tabular-nums">{s.students}</td>
                      <td className="pr-3 text-right tabular-nums">{s.staff}</td>
                      <td className="text-right tabular-nums">{s.sms_credit}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </main>
  );
}
