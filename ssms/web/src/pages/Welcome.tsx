// The public front page for visitors who are not signed in: what the system does and who uses it, then the way in.
// Layout follows the reference product's front page (design/19): hero, stats bar, module tabs, role cards. No demo
// passwords are shown: this is a real school's system.
import { useState } from "react";
import { Link } from "react-router-dom";

import { setLang, useLang, Word } from "../i18n";
import { Icon } from "../icons";
import { NAV } from "../nav";
import { Tabs } from "../widgets";

type Module = "dashboard" | "students" | "attendance" | "fees" | "exams";

const MODULES: Record<Module, { tab: Word; icon: string; head: Word; desc: Word; points: Word[] }> = {
  dashboard: { tab: "wTabDashboard", icon: "reports", head: "wDashHead", desc: "wDashDesc", points: ["wDash1", "wDash2", "wDash3", "wDash4"] },
  students: { tab: "wTabStudents", icon: "students", head: "wStuHead", desc: "wStuDesc", points: ["wStu1", "wStu2", "wStu3", "wStu4"] },
  attendance: { tab: "wTabAttendance", icon: "attendance", head: "wAttHead", desc: "wAttDesc", points: ["wAtt1", "wAtt2", "wAtt3", "wAtt4"] },
  fees: { tab: "wTabFees", icon: "fees", head: "wFeeHead", desc: "wFeeDesc", points: ["wFee1", "wFee2", "wFee3", "wFee4"] },
  exams: { tab: "wTabExams", icon: "exams", head: "wExamHead", desc: "wExamDesc", points: ["wExam1", "wExam2", "wExam3", "wExam4"] },
};

const ROLES: Array<{ name: Word; desc: Word; tag: Word; icon: string; tile: string; tagLook: string; to: string }> = [
  { name: "wRoleSuper", desc: "wRoleSuperDesc", tag: "wTagPlatform", icon: "privacy", tile: "bg-slate-800", tagLook: "bg-slate-100 text-slate-700", to: "/console" },
  { name: "wRoleAdmin", desc: "wRoleAdminDesc", tag: "wTagStaff", icon: "key", tile: "bg-brand-500", tagLook: "bg-brand-50 text-brand-700", to: "/login?as=school_admin" },
  { name: "teacher", desc: "wRoleTeacherDesc", tag: "wTagStaff", icon: "marks", tile: "bg-emerald-600", tagLook: "bg-emerald-50 text-emerald-700", to: "/login?as=teacher" },
  { name: "wRoleBursar", desc: "wRoleBursarDesc", tag: "wTagStaff", icon: "money", tile: "bg-amber-600", tagLook: "bg-amber-50 text-amber-800", to: "/login?as=bursar" },
  { name: "wRoleReception", desc: "wRoleReceptionDesc", tag: "wTagStaff", icon: "inquiry", tile: "bg-sky-600", tagLook: "bg-sky-50 text-sky-700", to: "/login?as=receptionist" },
  { name: "wRoleLibrarian", desc: "wRoleLibrarianDesc", tag: "wTagStaff", icon: "library", tile: "bg-violet-600", tagLook: "bg-violet-50 text-violet-700", to: "/login?as=librarian" },
  { name: "wRoleStudent", desc: "wRoleStudentDesc", tag: "wTagPortal", icon: "students", tile: "bg-teal-600", tagLook: "bg-teal-50 text-teal-700", to: "/login?as=student" },
  { name: "wRoleParent", desc: "wRoleParentDesc", tag: "wTagPortal", icon: "people", tile: "bg-rose-600", tagLook: "bg-rose-50 text-rose-700", to: "/login?as=parent" },
];

const MODULE_COUNT = NAV.reduce((n, g) => n + g.links.length, 0);

/** A drawn preview of the app for each module: the real colours and shapes, not a screenshot. */
function Preview({ module }: { module: Module }) {
  const bars: Record<Module, number[]> = {
    dashboard: [62, 80, 71, 90, 84], students: [40, 55, 70, 64, 88], attendance: [92, 95, 89, 97, 94],
    fees: [30, 48, 61, 75, 82], exams: [58, 66, 73, 69, 81],
  };
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-[0_12px_28px_-6px_rgb(15_23_42/0.10)]" aria-hidden="true">
      <div className="flex items-center gap-1.5 border-b border-slate-100 bg-slate-50 px-3 py-2">
        <span className="h-2.5 w-2.5 rounded-full bg-rose-300" /><span className="h-2.5 w-2.5 rounded-full bg-amber-300" /><span className="h-2.5 w-2.5 rounded-full bg-emerald-300" />
      </div>
      <div className="flex">
        <div className="hidden w-14 shrink-0 flex-col items-center gap-3 bg-brand-900 py-4 text-brand-200 sm:flex">
          {["home", "students", "attendance", "fees", "exams"].map((i) => (
            <span key={i} className={`rounded-lg p-1.5 ${i === MODULES[module].icon ? "bg-brand-500 text-white" : ""}`}><Icon name={i} className="h-4 w-4" /></span>))}
        </div>
        <div className="flex-1 space-y-3 p-4">
          <div className="grid grid-cols-3 gap-2">
            {[["bg-brand-50", "bg-brand-500"], ["bg-emerald-50", "bg-emerald-500"], ["bg-amber-50", "bg-amber-500"]].map(([bg, fg]) => (
              <div key={bg} className={`rounded-lg ${bg} p-2`}><div className={`h-1.5 w-8 rounded ${fg}`} /><div className="mt-2 h-3 w-12 rounded bg-slate-300/70" /></div>))}
          </div>
          <div className="flex h-24 items-end gap-2 rounded-lg border border-slate-100 p-2">
            {bars[module].map((h, i) => <div key={i} className="flex-1 rounded-t bg-brand-400" style={{ height: `${h}%` }} />)}
          </div>
          {[0, 1, 2].map((r) => (
            <div key={r} className="flex items-center gap-2"><span className="h-5 w-5 rounded-full bg-slate-200" /><span className="h-2 flex-1 rounded bg-slate-100" />
              <span className={`h-4 w-12 rounded-full ${r === 1 ? "bg-amber-100" : "bg-emerald-100"}`} /></div>))}
        </div>
      </div>
    </div>
  );
}

export default function Welcome() {
  const [lang, t] = useLang();
  const [module, setModule] = useState<Module>("dashboard");
  const shown = MODULES[module];
  const stats: Array<[string, Word]> = [["8", "wStatRoles"], [`${MODULE_COUNT}+`, "wStatModules"], ["2", "wStatLanguages"], ["✓", "wStatOffline"]];
  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-600">
      <div className="bg-brand-900 px-4 py-2 text-center text-xs font-medium text-brand-100">{t("wTopbar")}</div>

      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <Link to="/" className="flex items-center gap-3">
            <img src="/icon.svg" alt="" className="h-9 w-9 rounded-lg" />
            <span className="leading-tight"><span className="block font-bold text-slate-900">SSMS</span>
              <span className="hidden text-xs text-slate-500 sm:block">{t("wTagline")}</span></span>
          </Link>
          <nav className="flex items-center gap-1 text-sm font-semibold sm:gap-2">
            <a href="#modules" className="hidden rounded-lg px-3 py-2 text-slate-600 hover:text-slate-900 md:block">{t("wModulesKicker")}</a>
            <a href="#roles" className="hidden rounded-lg px-3 py-2 text-slate-600 hover:text-slate-900 md:block">{t("wSeeRoles")}</a>
            <button type="button" onClick={() => setLang(lang === "sw" ? "en" : "sw")}
              className="rounded-lg px-3 py-2 text-slate-600 hover:text-slate-900">{lang === "sw" ? "English" : "Kiswahili"}</button>
            <Link to="/login" className="rounded-lg bg-brand-500 px-4 py-2 text-white shadow-sm hover:bg-brand-600">{t("signIn")}</Link>
          </nav>
        </div>
      </header>

      <main className="flex-1">
        <section className="relative overflow-hidden px-4 pb-12 pt-14 sm:pt-20">
          <div className="pointer-events-none absolute left-1/2 top-[-150px] h-[550px] w-[900px] max-w-[100vw] -translate-x-1/2"
            style={{ background: "radial-gradient(circle, rgb(99 102 241 / 0.14) 0%, rgb(168 85 247 / 0.08) 40%, transparent 70%)" }} />
          <div className="relative mx-auto max-w-3xl text-center">
            <span className="mb-5 inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3.5 py-1.5 text-xs font-semibold text-slate-700 shadow-sm">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />{t("wBadge")}
            </span>
            <h1 className="text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">{t("wTitle")}</h1>
            <p className="mx-auto mt-5 max-w-2xl text-base leading-relaxed text-slate-600 sm:text-lg">{t("wLead")}</p>
            <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
              <Link to="/login" className="inline-flex items-center justify-center gap-2 rounded-lg bg-brand-500 px-5 py-3 text-sm font-semibold text-white shadow-sm hover:bg-brand-600">
                <Icon name="key" className="h-4 w-4" />{t("signIn")}</Link>
              <a href="#modules" className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-5 py-3 text-sm font-semibold text-slate-800 hover:bg-slate-100">{t("wSeeModules")}</a>
              <a href="#roles" className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-700 hover:border-slate-400">{t("wSeeRoles")}</a>
            </div>
          </div>
          <div className="relative mx-auto mt-12 max-w-3xl">
            <Preview module="dashboard" />
            <span className="absolute -left-2 top-10 hidden items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-lg md:inline-flex">
              <Icon name="attendance" className="h-4 w-4 text-emerald-600" />{t("wFloatAttendance")}</span>
            <span className="absolute -right-2 bottom-10 hidden items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-lg md:inline-flex">
              <Icon name="privacy" className="h-4 w-4 text-brand-500" />{t("wFloatRoles")}</span>
          </div>
        </section>

        <section className="border-y border-slate-200 bg-white px-4 py-8">
          <dl className="mx-auto grid max-w-5xl grid-cols-2 gap-y-6 text-center sm:grid-cols-4">
            {stats.map(([value, label]) => (
              <div key={label} className="flex flex-col-reverse items-center">
                <dt className="text-sm font-semibold text-slate-600">{t(label)}</dt>
                <dd className="mb-1 text-3xl font-extrabold tracking-tight text-slate-900">{value}</dd>
              </div>))}
          </dl>
        </section>

        <section id="modules" className="scroll-mt-20 px-4 py-16">
          <div className="mx-auto max-w-6xl">
            <div className="mb-8 text-center">
              <p className="text-sm font-semibold uppercase tracking-wider text-brand-600">{t("wModulesKicker")}</p>
              <h2 className="mt-2 text-3xl font-bold tracking-tight text-slate-900">{t("wModulesTitle")}</h2>
            </div>
            <div className="flex justify-center">
              <Tabs label={t("wModulesKicker")} value={module} onChange={setModule}
                tabs={(Object.keys(MODULES) as Module[]).map((k) => [k, t(MODULES[k].tab)])} />
            </div>
            <div role="tabpanel" className="grid items-center gap-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-[0_10px_30px_-5px_rgb(15_23_42/0.05)] sm:p-10 lg:grid-cols-2">
              <div>
                <span className="mb-4 inline-flex rounded-xl bg-brand-50 p-2.5 text-brand-600"><Icon name={shown.icon} className="h-5 w-5" /></span>
                <h3 className="text-2xl font-bold tracking-tight text-slate-900">{t(shown.head)}</h3>
                <p className="mt-3 leading-relaxed text-slate-500">{t(shown.desc)}</p>
                <ul className="mt-6 space-y-3">
                  {shown.points.map((p) => (
                    <li key={p} className="flex items-start gap-2.5 text-sm font-medium text-slate-700">
                      <Icon name="check" className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />{t(p)}</li>))}
                </ul>
              </div>
              <Preview module={module} />
            </div>
          </div>
        </section>

        <section id="roles" className="scroll-mt-20 border-t border-slate-200 bg-white px-4 py-16">
          <div className="mx-auto max-w-6xl">
            <div className="mb-10 text-center">
              <p className="text-sm font-semibold uppercase tracking-wider text-brand-600">{t("wRolesKicker")}</p>
              <h2 className="mt-2 text-3xl font-bold tracking-tight text-slate-900">{t("wRolesTitle")}</h2>
              <p className="mx-auto mt-3 max-w-2xl text-slate-500">{t("wRolesLead")}</p>
            </div>
            <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {ROLES.map((r) => (
                <li key={r.name} className="flex flex-col justify-between rounded-xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-[0_12px_24px_-4px_rgb(15_23_42/0.08)]">
                  <div>
                    <div className="mb-4 flex items-center justify-between">
                      <span className={`flex h-10 w-10 items-center justify-center rounded-lg text-white ${r.tile}`}><Icon name={r.icon} className="h-5 w-5" /></span>
                      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${r.tagLook}`}>{t(r.tag)}</span>
                    </div>
                    <h3 className="text-lg font-bold text-slate-900">{t(r.name)}</h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-slate-500">{t(r.desc)}</p>
                  </div>
                  {r.to === "/console"
                    ? <a href={r.to} className="mt-5 flex items-center justify-center rounded-md bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-500">{t("wSignInAs")}</a>
                    : <Link to={r.to} className="mt-5 flex items-center justify-center rounded-md bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-500">{t("wSignInAs")}</Link>}
                </li>))}
            </ul>
          </div>
        </section>
      </main>

      <footer className="bg-brand-900 px-4 py-8 text-sm text-brand-200">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 sm:flex-row">
          <span className="flex items-center gap-2"><img src="/icon.svg" alt="" className="h-6 w-6 rounded" />SSMS · {t("wFooter")}</span>
          <span>© {new Date().getFullYear()}</span>
        </div>
      </footer>
    </div>
  );
}
