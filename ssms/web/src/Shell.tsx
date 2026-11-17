import { ReactNode, useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { api } from "./api";
import { useAuth } from "./auth";
import { setLang, useLang } from "./i18n";
import { Icon } from "./icons";
import { allowed, locate } from "./nav";
import { setViewingYear, useViewingYear } from "./year";
import { PageTitle } from "./ui";

function useUnread(): number {
  const [unread, setUnread] = useState(0);
  useEffect(() => {
    const load = () => api<{ unread: number }>("/notifications").then((r) => setUnread(r.unread)).catch(() => undefined);
    load();
    const timer = setInterval(load, 60_000);
    return () => clearInterval(timer);
  }, []);
  return unread;
}

interface YearRow { id: string; name: string; is_current: boolean }

/** The school's years, the one on screen and the current one (undefined while loading or when unreadable). */
function useYears(): { years: YearRow[]; shown?: YearRow; current?: YearRow; loaded: boolean } {
  const [years, setYears] = useState<YearRow[] | null>(null);
  const chosen = useViewingYear();
  useEffect(() => {
    api<YearRow[]>("/academic-years").then(setYears).catch(() => setYears(null));
  }, []);
  const current = years?.find((y) => y.is_current);
  const picked = years?.find((y) => y.id === chosen);
  useEffect(() => {
    // a remembered year that no longer exists (or is now the current one) falls back to the current year
    if (years && chosen && (!picked || picked.is_current)) setViewingYear(null);
  }, [years, chosen, picked]);
  return { years: years ?? [], shown: picked ?? current, current, loaded: years !== null };
}

/** Menu groups the person folded away, remembered on this device. Everything starts open. */
function useFolded(): [Set<string>, (key: string) => void] {
  const KEY = "ssms.folded";
  const [folded, setFolded] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem(KEY) ?? "[]")); } catch { return new Set(); }
  });
  const toggle = (key: string) => setFolded((old) => {
    const next = new Set(old);
    if (!next.delete(key)) next.add(key);
    try { localStorage.setItem(KEY, JSON.stringify([...next])); } catch { /* private mode */ }
    return next;
  });
  return [folded, toggle];
}

const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("");

const linkLook = (isActive: boolean) => `relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
  isActive ? "bg-white/10 font-semibold text-white" : "text-brand-100 hover:bg-white/5 hover:text-white"}`;

export default function Shell({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const [lang, t] = useLang();
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const session = auth.session!;
  const unread = useUnread();
  const { years, shown, current, loaded } = useYears();
  const chosenYear = useViewingYear(); // pages reload when the person picks a year, not when the list arrives
  const past = !!shown && !shown.is_current;
  const year = shown?.name;
  const [folded, toggle] = useFolded();
  const close = () => setOpen(false);
  const groups = allowed(auth.can);
  const { group: section, link: here } = locate(pathname);
  const hub = pathname.startsWith("/m/");
  const isHome = pathname === "/";
  const pageName = here ? t(here.label) : hub && section ? t(section.group)
    : pathname === "/inbox" ? t("inbox") : pathname === "/password" ? t("changePassword") : t("home");
  const pageHint = here ? t(here.hint) : hub && section ? t(section.hint) : null;
  const pageIcon = here?.icon ?? (hub ? section?.icon : pathname === "/inbox" ? "bell" : "key") ?? "home";
  const today = new Intl.DateTimeFormat(lang === "sw" ? "sw-TZ" : "en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "Africa/Dar_es_Salaam" }).format(new Date());

  return (
    <div className="min-h-screen md:flex">
      {open && <div className="fixed inset-0 z-30 bg-slate-900/50 md:hidden print:hidden" onClick={close} aria-hidden="true" />}

      <nav className={`${open ? "flex" : "hidden"} fixed inset-y-0 left-0 z-40 w-72 flex-col bg-brand-900 text-brand-50 shadow-lift
        md:sticky md:top-0 md:flex md:h-screen md:w-64 md:flex-none md:shadow-none print:!hidden`}>
        <div className="pattern-weave flex items-center gap-3 border-b border-white/10 px-4 py-4">
          <img src="/icon.svg" alt="" className="h-10 w-10 rounded-xl" />
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent-300">SSMS</p>
            <p className="truncate text-sm font-semibold leading-tight text-white" title={session.school.name}>{session.school.name}</p>
          </div>
          <button aria-label={t("closeMenu")} className="rounded-lg p-1.5 hover:bg-white/10 md:hidden" onClick={close}>
            <Icon name="close" />
          </button>
        </div>

        <div className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
          <NavLink to="/" end onClick={close} className={({ isActive }) => linkLook(isActive)}>
            {({ isActive }) => (
              <>
                {isActive && <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-accent-500" />}
                <Icon name="home" className={`h-[18px] w-[18px] ${isActive ? "text-accent-300" : "text-brand-300"}`} />{t("home")}
              </>
            )}
          </NavLink>
          {groups.map((g) => {
            const shut = folded.has(g.key) && section?.key !== g.key;
            return (
              <div key={g.key} className="pt-2">
                <button onClick={() => toggle(g.key)} aria-expanded={!shut}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-brand-300 hover:text-white">
                  <span className="flex-1 text-left">{t(g.group)}</span>
                  <svg aria-hidden="true" viewBox="0 0 20 20" className={`h-3.5 w-3.5 transition ${shut ? "-rotate-90" : ""}`} fill="none" stroke="currentColor" strokeWidth="2"><path d="m6 8 4 4 4-4" /></svg>
                </button>
                {!shut && (
                  <ul className="mt-0.5 space-y-0.5">
                    {[{ to: `/m/${g.key}`, label: t("overview"), icon: g.icon }, ...g.links.map((n) => ({ to: n.to, label: t(n.label), icon: n.icon }))].map((n) => (
                      <li key={n.to}>
                        <NavLink to={n.to} onClick={close} className={({ isActive }) => linkLook(isActive)}>
                          {({ isActive }) => (
                            <>
                              {isActive && <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-accent-500" />}
                              <Icon name={n.icon} className={`h-[18px] w-[18px] ${isActive ? "text-accent-300" : "text-brand-300"}`} />
                              {n.label}
                            </>
                          )}
                        </NavLink>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>

        <div className="border-t border-white/10 p-3 text-sm">
          <div className="flex items-center gap-3 px-1 pb-2">
            <span aria-hidden="true" className="flex h-9 w-9 flex-none items-center justify-center rounded-full bg-accent-500 text-xs font-bold text-brand-950">
              {initials(session.user.full_name)}
            </span>
            <p className="min-w-0 truncate font-medium text-white">{session.user.full_name}</p>
          </div>
          <div className="space-y-0.5">
            <NavLink to="/password" onClick={close} className="flex items-center gap-3 rounded-lg px-3 py-1.5 text-brand-100 hover:bg-white/5 hover:text-white">
              <Icon name="key" className="h-4 w-4 text-brand-300" />{t("changePassword")}
            </NavLink>
            <button className="flex w-full items-center gap-3 rounded-lg px-3 py-1.5 text-left text-brand-100 hover:bg-white/5 hover:text-white" onClick={() => auth.logout()}>
              <Icon name="signout" className="h-4 w-4 text-brand-300" />{t("signOut")}
            </button>
          </div>
        </div>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center gap-2 border-b border-slate-200 bg-slate-50/90 px-4 py-3 backdrop-blur sm:gap-3 md:px-8 print:hidden">
          <button aria-label="Menu" className="rounded-lg border border-slate-300 bg-white p-1.5 text-slate-700 md:hidden" onClick={() => setOpen(!open)}>
            <Icon name="menu" />
          </button>
          <p className="min-w-0 flex-1 truncate text-sm text-slate-500">
            {section && !hub && <span>{t(section.group)} <span aria-hidden="true" className="px-1 text-slate-400">/</span> </span>}
            <span className="font-semibold text-slate-800">{pageName}</span>
          </p>
          {loaded && (years.length === 0 ? (
            <span className="hidden items-center gap-1.5 rounded-full bg-accent-100 px-3 py-1 text-xs font-semibold text-accent-700 ring-1 ring-inset ring-accent-300 sm:inline-flex">
              <Icon name="timetable" className="h-3.5 w-3.5" />{t("noYear")}
            </span>
          ) : (
            <label className={`flex items-center gap-1.5 rounded-full py-1 pl-3 pr-1 text-xs font-semibold ring-1 ring-inset ${
              past ? "bg-accent-100 text-accent-700 ring-accent-300" : "bg-brand-50 text-brand-700 ring-brand-200"}`}>
              <Icon name="timetable" className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">{t("academicYear")}</span>
              <select aria-label={t("academicYear")} value={shown?.id ?? ""} data-testid="year-select"
                onChange={(e) => setViewingYear(e.target.value === current?.id ? null : e.target.value)}
                className="cursor-pointer rounded-full border-0 bg-transparent py-0 pl-1 pr-6 text-xs font-semibold focus:ring-2 focus:ring-brand-300">
                {years.map((y) => <option key={y.id} value={y.id}>{y.name}{y.is_current ? ` (${t("currentYear")})` : ""}</option>)}
              </select>
            </label>
          ))}
          <button className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-100"
            onClick={() => setLang(lang === "sw" ? "en" : "sw")}>
            <Icon name="language" className="h-4 w-4" />{t("language")}
          </button>
          <NavLink to="/inbox" aria-label={t("inbox")} data-testid="inbox-bell" className="relative rounded-lg p-1.5 text-slate-600 hover:bg-slate-100">
            <Icon name="bell" />
            {unread > 0 && (
              <span className="absolute -right-0.5 -top-0.5 min-w-[1.1rem] rounded-full bg-red-700 px-1 text-center text-[11px] font-bold leading-[1.1rem] text-white">
                {unread}
              </span>
            )}
          </NavLink>
        </header>

        {past && shown && (
          <div role="status" className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-accent-300 bg-accent-100 px-4 py-2 text-sm text-accent-700 print:hidden">
            <span><b>{t("viewingYear")} {shown.name}.</b> {t("viewingYearNote")}</span>
            <button onClick={() => setViewingYear(null)} className="font-semibold underline underline-offset-2">
              {t("backToCurrent")}{current ? ` (${current.name})` : ""}
            </button>
          </div>
        )}
        <main key={`${pathname}|${chosenYear ?? "current"}`} className="page-enter mx-auto w-full max-w-7xl flex-1 px-4 py-5 md:px-8 md:py-7 print:max-w-none print:p-0">
          {/* Letterhead: only on paper, so every printed list carries the school's name, year and date. */}
          <div className="hidden print:mb-4 print:flex print:items-center print:gap-4 print:border-b-2 print:border-slate-800 print:pb-3">
            <img src="/icon.svg" alt="" className="h-14 w-14" />
            <div className="flex-1">
              <p className="text-xl font-bold">{session.school.name}</p>
              <p className="text-sm">{pageName}{year ? ` · ${t("academicYear")} ${year}` : ""}</p>
            </div>
            <p className="text-xs">{t("printedOn")}: {today}</p>
          </div>

          {!isHome && (
            <header className="pattern-weave mb-5 flex flex-wrap items-center gap-4 rounded-2xl bg-brand-900 px-5 py-4 text-white shadow-card sm:px-6 print:hidden">
              <span className="rounded-xl bg-white/10 p-2.5 text-accent-300"><Icon name={pageIcon} className="h-6 w-6" /></span>
              <div className="min-w-0 flex-1">
                {section && !hub && <p className="text-xs font-semibold uppercase tracking-wider text-accent-300">{t(section.group)}</p>}
                <h1 className="text-2xl font-bold leading-tight tracking-tight">{pageName}</h1>
                {pageHint && <p className="mt-0.5 text-sm text-brand-100">{pageHint}</p>}
              </div>
              {!hub && (
                <button onClick={() => window.print()}
                  className="flex items-center gap-2 rounded-lg bg-white/10 px-3 py-2 text-sm font-semibold text-white ring-1 ring-inset ring-white/20 transition hover:bg-white/20">
                  <Icon name="print" className="h-4 w-4" />{t("print")}
                </button>
              )}
            </header>
          )}
          <PageTitle.Provider value={isHome ? null : pageName}>{children}</PageTitle.Provider>
        </main>
      </div>
    </div>
  );
}
