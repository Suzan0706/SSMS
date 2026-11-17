import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ROLE_NAMES, rememberChosenRole } from "../chosenRole";

import { ApiError, fieldErrors } from "../api";
import { useAuth } from "../auth";
import { setLang, useLang } from "../i18n";
import { Icon } from "../icons";
import { Button, ErrorBox, Field, Input } from "../ui";

type Mode = "staff" | "parent";

export default function Login() {
  const auth = useAuth();
  const [lang, t] = useLang();
  const [params] = useSearchParams();
  const chosen = params.get("as");
  const chosenName = chosen && chosen in ROLE_NAMES ? ROLE_NAMES[chosen] : null;
  const [mode, setMode] = useState<Mode>(chosen === "parent" ? "parent" : "staff");
  useEffect(() => { rememberChosenRole(chosen); }, [chosen]);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [staff, setStaff] = useState({ school_code: "", username: "", password: "" });
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [choice, setChoice] = useState<{ token: string; schools: { school_id: string; name: string }[] } | null>(null);
  const errors = fieldErrors(error);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  const submitStaff = (e: FormEvent) => {
    e.preventDefault();
    run(() => auth.login(staff.school_code.trim(), staff.username.trim(), staff.password));
  };
  const submitPhone = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await auth.requestOtp(phone);
      setCodeSent(true);
    });
  };
  const submitCode = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      const result = await auth.verifyOtp(phone, code);
      if ("choose" in result) setChoice({ token: result.selection_token, schools: result.choose });
    });
  };

  return (
    <main className="grid min-h-screen lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <aside className="pattern-weave relative hidden flex-col justify-between overflow-hidden bg-brand-900 p-12 text-white lg:flex">
        <div className="flex items-center gap-3">
          <img src="/icon.svg" alt="" className="h-11 w-11 rounded-xl" />
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-accent-300">SSMS</p>
        </div>
        <div className="max-w-lg">
          <p className="text-5xl font-bold leading-[1.05] tracking-tight">{t("loginHeadline")}</p>
          <p className="mt-5 text-lg leading-relaxed text-brand-100">{t("loginLead")}</p>
          <ul className="mt-8 space-y-3">
            {([["results", "loginPointMarks"], ["fees", "loginPointFees"], ["attendance", "loginPointAttendance"]] as const).map(([icon, word]) => (
              <li key={word} className="flex items-center gap-3 text-brand-50">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10 text-accent-300"><Icon name={icon} /></span>
                {t(word)}
              </li>
            ))}
          </ul>
        </div>
        <p className="text-sm text-brand-300">{t("appName")}</p>
      </aside>

      <div className="flex flex-col justify-center px-5 py-8 sm:px-10">
        <div className="mx-auto w-full max-w-md">
          <div className="mb-8 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <img src="/icon.svg" alt="" className="h-10 w-10 rounded-xl lg:hidden" />
              <h1 className="text-lg font-bold lg:hidden">SSMS</h1>
              <Link to="/" className="hidden text-sm font-medium text-slate-600 hover:text-slate-900 lg:block">← {t("wBackHome")}</Link>
            </div>
            <button className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-100" onClick={() => setLang(lang === "sw" ? "en" : "sw")}>
              <Icon name="language" className="h-4 w-4" />{t("language")}
            </button>
          </div>
          <p className="mb-6 text-3xl font-bold leading-tight tracking-tight lg:hidden">{t("loginHeadline")}</p>

        <div className="mb-5 grid grid-cols-2 rounded-xl bg-slate-200/70 p-1 text-sm" role="tablist">
          {(["staff", "parent"] as Mode[]).map((m) => (
            <button key={m} role="tab" aria-selected={mode === m}
              className={`rounded-lg px-3 py-2 font-medium transition ${mode === m ? "bg-white font-semibold text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"}`}
              onClick={() => { setMode(m); setError(null); }}>
              {t(m === "staff" ? "staffLogin" : "parentLogin")}
            </button>
          ))}
        </div>

        {chosenName && (
          <p className="mb-4 rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-800" data-testid="signing-in-as">
            {t("signingInAs")}: <span className="font-semibold">{t(chosenName)}</span>
          </p>
        )}
        <ErrorBox error={error} />

        {mode === "staff" && (
          <form className="mt-4 space-y-4" onSubmit={submitStaff}>
            <Field label={t("schoolCode")} error={errors.school_code}>
              <Input name="school_code" autoComplete="organization" required placeholder="mfano-sec"
                value={staff.school_code} onChange={(e) => setStaff({ ...staff, school_code: e.target.value })} />
            </Field>
            <Field label={t("username")} error={errors.username}>
              <Input name="username" autoComplete="username" required
                value={staff.username} onChange={(e) => setStaff({ ...staff, username: e.target.value })} />
            </Field>
            <Field label={t("password")} error={errors.password}>
              <Input name="password" type="password" autoComplete="current-password" required
                value={staff.password} onChange={(e) => setStaff({ ...staff, password: e.target.value })} />
            </Field>
            <Button type="submit" disabled={busy} className="w-full">{t("signIn")}</Button>
          </form>
        )}

        {mode === "parent" && !choice && (
          <form className="mt-4 space-y-4" onSubmit={codeSent ? submitCode : submitPhone}>
            <Field label={t("phone")} error={errors.phone}>
              <Input name="phone" type="tel" inputMode="tel" autoComplete="tel" required placeholder="0754 123 456"
                value={phone} disabled={codeSent} onChange={(e) => setPhone(e.target.value)} />
            </Field>
            {codeSent && (
              <Field label={t("code")} error={errors.code}>
                <Input name="code" inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" maxLength={6} required
                  value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
              </Field>
            )}
            <Button type="submit" disabled={busy} className="w-full">{t(codeSent ? "verify" : "sendCode")}</Button>
            <button type="button" className="w-full text-center text-sm text-brand-700 underline" onClick={() => { setMode("staff"); setError(null); }}>
              {t("useUsername")}
            </button>
          </form>
        )}

        {choice && (
          <div className="mt-3 space-y-2">
            <p className="text-sm font-medium">{t("chooseSchool")}</p>
            {choice.schools.map((s) => (
              <Button key={s.school_id} kind="plain" className="w-full text-left"
                onClick={() => run(() => auth.selectSchool(choice.token, s.school_id))}>
                {s.name}
              </Button>
            ))}
          </div>
        )}
        </div>
      </div>
    </main>
  );
}
