// A module's front page: one card per screen in the group, each with a short note and an Open button.
import { Link, Navigate, useParams } from "react-router-dom";

import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { Icon } from "../icons";
import { allowed } from "../nav";

export default function ModuleHub() {
  const { key } = useParams();
  const { can } = useAuth();
  const [, t] = useLang();
  const group = allowed(can).find((g) => g.key === key);
  if (!group) return <Navigate to="/" replace />;
  return (
    <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {group.links.map((n) => (
        <li key={n.to} className="group flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-card transition hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-lift">
          <div className="flex items-start gap-3">
            <span className="rounded-xl bg-brand-50 p-2.5 text-brand-600 transition group-hover:bg-brand-500 group-hover:text-white">
              <Icon name={n.icon} className="h-6 w-6" />
            </span>
            <div className="min-w-0">
              <h2 className="text-lg font-semibold tracking-tight">{t(n.label)}</h2>
              <p className="mt-1 text-sm text-slate-600">{t(n.hint)}</p>
            </div>
          </div>
          <Link to={n.to} aria-label={`${t("open")}: ${t(n.label)}`}
            className="mt-5 inline-flex w-fit items-center gap-1.5 self-end rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-600">
            {t("open")}<span aria-hidden="true">→</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
