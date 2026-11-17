import { createContext, ReactNode, useContext, useEffect, useState } from "react";

import { api, bindSession, refreshSession, Session, applySession } from "./api";
import { setLang } from "./i18n";

interface SchoolChoice {
  school_id: string;
  name: string;
}

export type OtpResult = { choose: SchoolChoice[]; selection_token: string } | Session;

interface Auth {
  session: Session | null;
  ready: boolean;
  can: (...permissions: string[]) => boolean;
  login: (school_code: string, username: string, password: string) => Promise<void>;
  requestOtp: (phone: string) => Promise<void>;
  verifyOtp: (phone: string, code: string) => Promise<OtpResult>;
  selectSchool: (selection_token: string, school_id: string) => Promise<void>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
}

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    bindSession(setSession);
    refreshSession().finally(() => setReady(true));       // restore the session from the refresh cookie
  }, []);

  function start(s: Session) {
    applySession(s);
    if (s.user.language === "en" || s.user.language === "sw") setLang(s.user.language);
  }

  const value: Auth = {
    session,
    ready,
    can: (...permissions) => !!session && permissions.some((p) => session.permissions.includes(p)),
    async login(school_code, username, password) {
      start(await api<Session>("/auth/login", { body: { school_code, username, password } }));
    },
    async requestOtp(phone) {
      await api("/auth/otp/request", { body: { phone } });
    },
    async verifyOtp(phone, code) {
      const result = await api<OtpResult>("/auth/otp/verify", { body: { phone, code } });
      if ("access_token" in result) start(result);
      return result;
    },
    async selectSchool(selection_token, school_id) {
      start(await api<Session>("/auth/select-school", { body: { selection_token, school_id } }));
    },
    async logout() {
      await api("/auth/logout", { method: "POST" }).catch(() => undefined);
      applySession(null);
    },
    async reload() {
      await refreshSession();
    },
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth outside AuthProvider");
  return auth;
}
