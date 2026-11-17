import { lazy, Suspense, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { api } from "./api";
import { useAuth } from "./auth";
import { useLang } from "./i18n";
import { Icon } from "./icons";
import { allowed } from "./nav";
import ChangePassword from "./pages/ChangePassword";
import Import from "./pages/Import";
import { chosenRole, ROLE_NAMES } from "./chosenRole";
import Login from "./pages/Login";
import Welcome from "./pages/Welcome";
import Staff from "./pages/Staff";
import { StudentDetail, StudentForm, StudentList } from "./pages/Students";
import Shell from "./Shell";

const Academics = lazy(() => import("./pages/Academics"));
const Announcements = lazy(() => import("./pages/Announcements"));
const Attendance = lazy(() => import("./pages/Attendance"));
const Audit = lazy(() => import("./pages/Audit"));
const Bank = lazy(() => import("./pages/Bank"));
const Children = lazy(() => import("./pages/Children"));
const Clubs = lazy(() => import("./pages/Clubs"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Devices = lazy(() => import("./pages/Devices"));
const Discipline = lazy(() => import("./pages/Discipline"));
const Enrolment = lazy(() => import("./pages/Enrolment"));
const Exams = lazy(() => import("./pages/Exams"));
const Fees = lazy(() => import("./pages/Fees"));
const Health = lazy(() => import("./pages/Health"));
const Hostel = lazy(() => import("./pages/Hostel"));
const Inbox = lazy(() => import("./pages/Inbox"));
const Library = lazy(() => import("./pages/Library"));
const Documents = lazy(() => import("./pages/Documents"));
const Console = lazy(() => import("./pages/Console"));
const ModuleHub = lazy(() => import("./pages/ModuleHub"));
const Inquiries = lazy(() => import("./pages/Inquiries"));
const Calendar = lazy(() => import("./pages/Calendar"));
const StaffAttendance = lazy(() => import("./pages/StaffAttendance"));
const Leave = lazy(() => import("./pages/Leave"));
const Teaching = lazy(() => import("./pages/Teaching"));
const Lessons = lazy(() => import("./pages/Lessons"));
const Learning = lazy(() => import("./pages/Learning"));
const Accounts = lazy(() => import("./pages/Accounts"));
const Marks = lazy(() => import("./pages/Marks"));
const Privacy = lazy(() => import("./pages/Privacy"));
const Reports = lazy(() => import("./pages/Reports"));
const Results = lazy(() => import("./pages/Results"));
const Sms = lazy(() => import("./pages/Sms"));
const StudentHome = lazy(() => import("./pages/StudentHome"));
const Timetable = lazy(() => import("./pages/Timetable"));
const Transport = lazy(() => import("./pages/Transport"));
const Venues = lazy(() => import("./pages/Venues"));

interface EventRow { id: string; title_en: string; title_sw: string; starts_on: string; ends_on: string }

/** The next few school events for the signed-in audience (FR-99); nothing is shown when there are none. */
function UpcomingEvents() {
  const [lang, t] = useLang();
  const [events, setEvents] = useState<EventRow[]>([]);
  useEffect(() => { api<EventRow[]>("/events").then((e) => setEvents(e.slice(0, 5))).catch(() => setEvents([])); }, []);
  if (events.length === 0) return null;
  const fmt = new Intl.DateTimeFormat(lang === "sw" ? "sw-TZ" : "en-GB", { day: "numeric", month: "short" });
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-card sm:p-5" data-testid="upcoming-events">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-semibold">{t("upcomingEvents")}</h2>
        <Link to="/calendar" className="text-sm font-medium text-brand-700 hover:underline">{t("calendar")} →</Link>
      </div>
      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        {events.map((e) => (
          <li key={e.id} className="rounded-xl bg-slate-50 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-brand-600">
              {fmt.format(new Date(e.starts_on))}{e.ends_on !== e.starts_on ? ` – ${fmt.format(new Date(e.ends_on))}` : ""}
            </p>
            <p className="mt-1 text-sm font-medium">{lang === "sw" ? e.title_sw : e.title_en}</p>
          </li>))}
      </ul>
    </section>
  );
}

/** The account does not have the role picked on the front page: say so, instead of silently showing other pages. */
function ChosenRoleNotice() {
  const { session, logout } = useAuth();
  const [, t] = useLang();
  const chosen = chosenRole();
  if (!chosen || session!.roles.includes(chosen)) return null;
  const roles = session!.roles.map((r) => (r in ROLE_NAMES ? t(ROLE_NAMES[r]) : r)).join(", ");
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-accent-300 bg-accent-100 px-4 py-3 text-sm text-accent-700" data-testid="role-notice">
      <span>{t("notThatRole").replace("{role}", t(ROLE_NAMES[chosen])).replace("{roles}", roles)}</span>
      <button type="button" className="font-semibold underline"
        onClick={async () => { await logout(); window.location.assign(`/login?as=${chosen}`); }}>{t("signInOther")}</button>
    </div>
  );
}

function Home() {
  const { session, can } = useAuth();
  const [lang, t] = useLang();
  const parentOnly = session!.roles.length > 0 && session!.roles.every((r) => r === "parent");
  const modules = allowed(can);
  return (
    <div className="space-y-4">
      <header className="pattern-weave overflow-hidden rounded-2xl bg-brand-900 px-6 py-7 text-white shadow-card sm:px-8">
        <p className="text-sm font-medium text-accent-300">{new Intl.DateTimeFormat(lang === "sw" ? "sw-TZ" : "en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "Africa/Dar_es_Salaam" }).format(new Date())}</p>
        <h1 className="mt-1 text-3xl font-bold leading-tight tracking-tight sm:text-4xl">{t("welcome")}, {session!.user.full_name}</h1>
        <p className="mt-2 text-brand-100">{session!.school.name}</p>
        {parentOnly && <p className="mt-3 text-sm text-brand-50">{t("parentHome")}</p>}
      </header>
      <ChosenRoleNotice />
      {!parentOnly && modules.length > 1 && (
        <nav aria-label={t("overview")} className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {modules.map((g) => (
            <Link key={g.key} to={`/m/${g.key}`}
              className="group flex flex-col gap-2 rounded-2xl border border-slate-200 bg-white p-4 shadow-card transition hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-lift">
              <span className="w-fit rounded-xl bg-brand-50 p-2 text-brand-600 transition group-hover:bg-brand-500 group-hover:text-white">
                <Icon name={g.icon} className="h-5 w-5" />
              </span>
              <span className="font-semibold">{t(g.group)}</span>
              <span className="text-xs text-slate-500">{g.links.length} · {g.links.slice(0, 3).map((n) => t(n.label)).join(", ")}{g.links.length > 3 ? "…" : ""}</span>
            </Link>
          ))}
        </nav>
      )}
      <UpcomingEvents />
      {can("settings.update", "finance.read", "attendance.take", "library.manage", "enrolment.manage") && <Dashboard />}
      {can("portal.parent") && <Children />}
      {can("portal.student") && <StudentHome />}
    </div>
  );
}

export default function App() {
  const { session, ready, can } = useAuth();
  const { pathname } = useLocation();
  const [, t] = useLang();
  if (window.location.pathname.startsWith("/console")) {   // the platform operators' page has its own sign-in
    return <Suspense fallback={<p className="p-6 text-sm text-slate-500">{t("loading")}</p>}><Console /></Suspense>;
  }
  if (!ready) return <p className="p-6 text-sm text-slate-500">{t("loading")}</p>;
  if (!session) return pathname === "/" ? <Welcome /> : <Login />;   // the front page, or sign in to reach any page
  if (session.user.must_change_password) {
    return <main className="px-4 py-8"><ChangePassword /></main>;
  }
  return (
    <Shell>
      <Suspense fallback={<p className="text-sm text-slate-500">{t("loading")}</p>}>
      <Routes>
        <Route path="/" element={<Home />} />
        {can("students.read") && <Route path="/students" element={<StudentList />} />}
        {can("students.create") && <Route path="/students/new" element={<StudentForm />} />}
        {can("students.read") && <Route path="/students/:id" element={<StudentDetail />} />}
        {can("staff.read", "staff.manage") && <Route path="/staff" element={<Staff />} />}
        {can("students.import", "staff.manage") && <Route path="/import" element={<Import />} />}
        {can("academics.configure", "timetable.manage") && <Route path="/academics" element={<Academics />} />}
        {can("timetable.read", "timetable.manage") && <Route path="/timetable" element={<Timetable />} />}
        {can("exams.read", "exams.manage") && <Route path="/exams" element={<Exams />} />}
        {can("marks.enter") && <Route path="/marks" element={<Marks />} />}
        {can("results.publish", "results.read") && <Route path="/results" element={<Results />} />}
        {can("enrolment.manage", "enrolment.validate", "enrolment.decide") && <Route path="/enrolment" element={<Enrolment />} />}
        {can("finance.read", "payments.record", "reconciliation.run", "fees.configure") && <Route path="/fees" element={<Fees />} />}
        {can("payments.confirm_bank") && <Route path="/bank" element={<Bank />} />}
        {can("attendance.take", "attendance.read") && <Route path="/attendance" element={<Attendance />} />}
        {can("attendance.device", "settings.update") && <Route path="/devices" element={<Devices />} />}
        {can("sms.manage") && <Route path="/sms" element={<Sms />} />}
        {can("hostel.manage") && <Route path="/hostel" element={<Hostel />} />}
        {can("transport.manage") && <Route path="/transport" element={<Transport />} />}
        {can("venues.manage") && <Route path="/venues" element={<Venues />} />}
        {can("discipline.read", "discipline.manage") && <Route path="/discipline" element={<Discipline />} />}
        {can("activities.manage", "marks.enter") && <Route path="/clubs" element={<Clubs />} />}
        {can("library.manage") && <Route path="/library" element={<Library />} />}
        {can("certificates.issue", "cards.print") && <Route path="/documents" element={<Documents />} />}
        {can("health.read") && <Route path="/health" element={<Health />} />}
        {can("reports.read") && <Route path="/reports" element={<Reports />} />}
        {can("privacy.manage") && <Route path="/privacy" element={<Privacy />} />}
        {can("audit.read") && <Route path="/audit" element={<Audit />} />}
        <Route path="/m/:key" element={<ModuleHub />} />
        {can("inquiries.manage") && <Route path="/inquiries" element={<Inquiries />} />}
        {can("staff_attendance.read", "staff_attendance.take") && <Route path="/staff-attendance" element={<StaffAttendance />} />}
        {can("leave.request", "leave.decide") && <Route path="/leave" element={<Leave />} />}
        <Route path="/calendar" element={<Calendar />} />
        {can("homework.manage", "materials.publish", "academics.configure") && <Route path="/teaching" element={<Teaching />} />}
        {can("attendance.take") && <Route path="/lessons" element={<Lessons />} />}
        {can("portal.student", "portal.parent") && <Route path="/learning" element={<Learning />} />}
        {can("accounts.read", "accounts.record", "accounts.approve", "fines.configure") && <Route path="/accounts" element={<Accounts />} />}
        <Route path="/announcements" element={<Announcements />} />
        <Route path="/inbox" element={<Inbox />} />
        <Route path="/password" element={<ChangePassword />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </Suspense>
    </Shell>
  );
}
