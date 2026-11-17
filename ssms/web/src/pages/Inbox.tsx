import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { useLang } from "../i18n";
import { Button, Card } from "../ui";

interface Item { id: string; kind: string; title: string; body: string; link: string | null; read_at: string | null; created_at: string }

export default function Inbox() {
  const [, t] = useLang();
  const [inbox, setInbox] = useState<{ unread: number; items: Item[] }>({ unread: 0, items: [] });
  const load = useCallback(() => api<typeof inbox>("/notifications").then(setInbox).catch(() => undefined), []);
  useEffect(() => { load(); }, [load]);
  async function read(id: string | null) {
    await api(id ? `/notifications/${id}/read` : "/notifications/read-all", { method: "POST" });
    await load();
  }
  return (
    <Card title={`${t("inbox")} (${inbox.unread})`} actions={inbox.unread > 0 && <Button kind="plain" onClick={() => read(null)}>{t("markAllRead")}</Button>}>
      <ul className="divide-y text-sm">
        {inbox.items.map((n) => (
          <li key={n.id} className={`py-2 ${n.read_at ? "text-slate-500" : ""}`}>
            <p className="flex justify-between gap-2"><span className={n.read_at ? "" : "font-semibold"}>{n.title}</span>
              <span className="text-xs">{n.created_at.slice(0, 10)}</span></p>
            <p>{n.body}</p>
            <p className="flex gap-3 text-xs">
              {n.link && <Link className="text-brand-700 underline" to={n.link}>→</Link>}
              {!n.read_at && <button className="text-brand-700 underline" onClick={() => read(n.id)}>✓</button>}
            </p>
          </li>))}
        {inbox.items.length === 0 && <li className="py-3 text-slate-500">{t("noResults")}</li>}
      </ul>
    </Card>
  );
}
