import { useEffect, useState } from "react";

import { api, Page } from "./api";
import { useLang } from "./i18n";
import { Input } from "./ui";

export interface PickedStudent { id: string; admission_no: string; full_name: string; class_code?: string | null }

/** Search by name or admission number; calls onPick with the chosen student. */
export default function StudentPicker({ onPick, label }: { onPick: (s: PickedStudent) => void; label?: string }) {
  const [, t] = useLang();
  const [q, setQ] = useState("");
  const [matches, setMatches] = useState<PickedStudent[]>([]);
  useEffect(() => {
    if (q.trim().length < 2) { setMatches([]); return; }
    const timer = setTimeout(() => api<Page<PickedStudent>>(`/students?q=${encodeURIComponent(q.trim())}&limit=10`)
      .then((p) => setMatches(p.items)).catch(() => undefined), 250);
    return () => clearTimeout(timer);
  }, [q]);
  return (
    <div>
      <Input placeholder={t("search")} aria-label={label ?? t("search")} value={q} onChange={(e) => setQ(e.target.value)} />
      {matches.length > 0 && (
        <ul className="mt-1 divide-y rounded-md border text-sm">
          {matches.map((m) => (
            <li key={m.id}><button type="button" className="w-full px-2 py-1.5 text-left hover:bg-slate-50"
              onClick={() => { onPick(m); setQ(""); setMatches([]); }}>{m.admission_no} · {m.full_name} {m.class_code ?? ""}</button></li>))}
        </ul>
      )}
    </div>
  );
}
