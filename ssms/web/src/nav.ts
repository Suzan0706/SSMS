// The menu: one list drives the sidebar, the module overview pages and the page title bar.
import type { Word } from "./i18n";

export interface NavLink { to: string; label: Word; hint: Word; icon: string; permissions: string[] }
export interface NavGroup { key: string; group: Word; hint: Word; icon: string; links: NavLink[] }

export const HOME: NavLink = { to: "/", label: "home", hint: "home", icon: "home", permissions: [] };

export const NAV: NavGroup[] = [
  { key: "people", group: "navPeople", hint: "hubPeople", icon: "people", links: [
    { to: "/students", label: "students", hint: "hintStudents", icon: "students", permissions: ["students.read"] },
    { to: "/staff", label: "staff", hint: "hintStaff", icon: "staff", permissions: ["staff.read", "staff.manage"] },
    { to: "/enrolment", label: "enrolment", hint: "hintEnrolment", icon: "enrolment", permissions: ["enrolment.manage", "enrolment.validate", "enrolment.decide"] },
    { to: "/inquiries", label: "inquiries", hint: "hintInquiries", icon: "inquiry", permissions: ["inquiries.manage"] },
    { to: "/staff-attendance", label: "staffAttendance", hint: "hintStaffAttendance", icon: "attendance", permissions: ["staff_attendance.read", "staff_attendance.take"] },
    { to: "/leave", label: "leave", hint: "hintLeave", icon: "leave", permissions: ["leave.request", "leave.decide"] },
    { to: "/import", label: "imports", hint: "hintImports", icon: "imports", permissions: ["students.import", "staff.manage"] },
  ] },
  { key: "teaching", group: "navTeaching", hint: "hubTeaching", icon: "academics", links: [
    { to: "/academics", label: "academics", hint: "hintAcademics", icon: "academics", permissions: ["academics.configure", "timetable.manage"] },
    { to: "/timetable", label: "timetable", hint: "hintTimetable", icon: "timetable", permissions: ["timetable.read", "timetable.manage"] },
    { to: "/attendance", label: "attendance", hint: "hintAttendance", icon: "attendance", permissions: ["attendance.take", "attendance.read"] },
    { to: "/exams", label: "exams", hint: "hintExams", icon: "exams", permissions: ["exams.read", "exams.manage"] },
    { to: "/marks", label: "marks", hint: "hintMarks", icon: "marks", permissions: ["marks.enter"] },
    { to: "/teaching", label: "teachingResources", hint: "hintTeaching", icon: "homework", permissions: ["homework.manage", "materials.publish", "academics.configure"] },
    { to: "/lessons", label: "lessonRegister", hint: "hintLessons", icon: "attendance", permissions: ["attendance.take"] },
    { to: "/learning", label: "myLearning", hint: "hintLearning", icon: "homework", permissions: ["portal.student", "portal.parent"] },
    { to: "/results", label: "results", hint: "hintResults", icon: "results", permissions: ["results.publish", "results.read"] },
  ] },
  { key: "finance", group: "navMoney", hint: "hubMoney", icon: "money", links: [
    { to: "/fees", label: "fees", hint: "hintFees", icon: "fees", permissions: ["finance.read", "payments.record", "reconciliation.run", "fees.configure"] },
    { to: "/accounts", label: "accountsTitle", hint: "hintAccounts", icon: "money", permissions: ["accounts.read", "accounts.record", "accounts.approve", "fines.configure"] },
    { to: "/bank", label: "bank", hint: "hintBank", icon: "bank", permissions: ["payments.confirm_bank"] },
  ] },
  { key: "messages", group: "navMessages", hint: "hubMessages", icon: "announcements", links: [
    { to: "/announcements", label: "announcements", hint: "hintAnnouncements", icon: "announcements", permissions: [] },
    { to: "/calendar", label: "calendar", hint: "hintCalendar", icon: "calendar", permissions: [] },
    { to: "/sms", label: "sms", hint: "hintSms", icon: "sms", permissions: ["sms.manage"] },
  ] },
  { key: "school-life", group: "navSchoolLife", hint: "hubSchoolLife", icon: "clubs", links: [
    { to: "/hostel", label: "hostels", hint: "hintHostels", icon: "hostels", permissions: ["hostel.manage"] },
    { to: "/transport", label: "transport", hint: "hintTransport", icon: "transport", permissions: ["transport.manage"] },
    { to: "/venues", label: "venues", hint: "hintVenues", icon: "venues", permissions: ["venues.manage"] },
    { to: "/discipline", label: "discipline", hint: "hintDiscipline", icon: "discipline", permissions: ["discipline.read", "discipline.manage"] },
    { to: "/clubs", label: "clubs", hint: "hintClubs", icon: "clubs", permissions: ["activities.manage", "marks.enter"] },
    { to: "/library", label: "library", hint: "hintLibrary", icon: "library", permissions: ["library.manage"] },
    { to: "/health", label: "health", hint: "hintHealth", icon: "health", permissions: ["health.read"] },
  ] },
  { key: "admin", group: "navAdmin", hint: "hubAdmin", icon: "privacy", links: [
    { to: "/devices", label: "devices", hint: "hintDevices", icon: "devices", permissions: ["attendance.device", "settings.update"] },
    { to: "/documents", label: "documents", hint: "hintDocuments", icon: "print", permissions: ["certificates.issue", "cards.print"] },
    { to: "/reports", label: "reports", hint: "hintReports", icon: "reports", permissions: ["reports.read"] },
    { to: "/privacy", label: "privacy", hint: "hintPrivacy", icon: "privacy", permissions: ["privacy.manage"] },
    { to: "/audit", label: "audit", hint: "hintAudit", icon: "audit", permissions: ["audit.read"] },
  ] },
];

/** The groups and links this person may open; a group with nothing in it is left out. */
export function allowed(can: (...p: string[]) => boolean): NavGroup[] {
  return NAV
    .map((g) => ({ ...g, links: g.links.filter((n) => n.permissions.length === 0 || can(...n.permissions)) }))
    .filter((g) => g.links.length > 0);
}

/** Where a path sits in the menu: its group and its link, if it has one. */
export function locate(pathname: string): { group?: NavGroup; link?: NavLink } {
  const hub = pathname.match(/^\/m\/([\w-]+)/);
  if (hub) return { group: NAV.find((g) => g.key === hub[1]) };
  for (const group of NAV) {
    const link = group.links.find((n) => pathname === n.to || pathname.startsWith(n.to + "/"));
    if (link) return { group, link };
  }
  return {};
}
