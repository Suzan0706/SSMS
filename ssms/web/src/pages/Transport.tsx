import { FormEvent, useCallback, useEffect, useState } from "react";

import { nameOf, useCurrentTerm, useList } from "../academic";
import { api, ApiError } from "../api";
import { money } from "../finance";
import { useLang } from "../i18n";
import StudentPicker, { PickedStudent } from "../StudentPicker";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";

interface Bus { id: string; bus_no: string; capacity: number; status: string; used: number; free: number; driver_name: string | null; driver_phone: string | null }
interface Stop { id: string; seq: number; name: string; pickup_time: string }
interface RouteRow { id: string; name: string; term_fee_tzs: string; stops: Stop[] }
interface Assignment { id: string; full_name: string; admission_no: string; route_name: string; bus_no: string; stop_name: string;
  pickup_time: string; invoice_no: string | null }

export default function Transport() {
  const [lang, t] = useLang();
  const { terms, termId, setTermId } = useCurrentTerm();
  const [buses, setBuses] = useState<Bus[]>([]);
  const [routes, reloadRoutes] = useList<RouteRow>("/routes");
  const [rows, setRows] = useState<Assignment[]>([]);
  const [routeFilter, setRouteFilter] = useState("");
  const [student, setStudent] = useState<PickedStudent | null>(null);
  const [pick, setPick] = useState({ route_id: "", stop_id: "", bus_id: "" });
  const [busForm, setBusForm] = useState({ bus_no: "", capacity: "30" });
  const [routeForm, setRouteForm] = useState({ name: "", fee: "", stops: "" });
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const load = useCallback(() => {
    if (!termId) return;
    api<Bus[]>(`/buses?term_id=${termId}`).then(setBuses).catch(() => undefined);
    api<Assignment[]>(`/transport-assignments?term_id=${termId}`).then(setRows).catch(() => undefined);
  }, [termId]);
  useEffect(() => { load(); }, [load]);
  const route = routes.find((r) => r.id === pick.route_id);

  async function run(action: () => Promise<unknown>, after?: () => void) {
    try {
      await action();
      setError(null);
      after?.();
      load();
    } catch (e) {
      setError(e as ApiError);
    }
  }
  function assign(e: FormEvent) {
    e.preventDefault();
    if (!student) return;
    run(async () => {
      const out = await api<Assignment>("/transport-assignments", { body: { stop_id: pick.stop_id, bus_id: pick.bus_id, student_id: student.id, term_id: termId } });
      setNotice(out.invoice_no ? `${t("addedToInvoice")} ${out.invoice_no}` : t("billedLater"));
    }, () => setStudent(null));
  }
  function addBus(e: FormEvent) {
    e.preventDefault();
    run(() => api("/buses", { body: { bus_no: busForm.bus_no.toUpperCase(), capacity: Number(busForm.capacity) } }), () => setBusForm({ bus_no: "", capacity: "30" }));
  }
  function addRoute(e: FormEvent) {
    e.preventDefault();
    // stops: one per line, "06:30 Kisasa sokoni"
    const stops = routeForm.stops.split("\n").map((l) => l.trim()).filter(Boolean)
      .map((l, i) => ({ seq: i + 1, pickup_time: l.slice(0, 5), name: l.slice(5).trim() }));
    run(() => api("/routes", { body: { name: routeForm.name, term_fee_tzs: routeForm.fee || "0", stops } }),
      () => { setRouteForm({ name: "", fee: "", stops: "" }); reloadRoutes(); });
  }

  return (
    <div className="space-y-4">
      <Card title={t("transport")} actions={
        <Select aria-label={t("term")} value={termId} onChange={(e) => setTermId(e.target.value)}>
          {terms.map((x) => <option key={x.id} value={x.id}>{nameOf(x, lang)}</option>)}
        </Select>}>
        <ErrorBox error={error} />
        <ul className="mb-3 flex flex-wrap gap-2 text-sm">
          {buses.map((b) => <li key={b.id}><Badge>{b.bus_no} · {b.used}/{b.capacity}{b.status !== "ACTIVE" ? ` · ${b.status}` : ""}{b.driver_name ? ` · ${t("driver")}: ${b.driver_name}${b.driver_phone ? ` ${b.driver_phone}` : ""}` : ""}</Badge></li>)}
        </ul>
        <form className="space-y-2" onSubmit={assign}>
          {student ? <p className="text-sm font-semibold">{student.full_name} · {student.admission_no}</p> : <StudentPicker onPick={setStudent} />}
          <div className="grid gap-2 sm:grid-cols-4 sm:items-end">
            <Field label={t("route")}>
              <Select required value={pick.route_id} onChange={(e) => setPick({ ...pick, route_id: e.target.value, stop_id: "" })}>
                <option value="">—</option>{routes.map((r) => <option key={r.id} value={r.id}>{r.name} · {money(r.term_fee_tzs)}</option>)}
              </Select>
            </Field>
            <Field label={t("stop")}>
              <Select required value={pick.stop_id} onChange={(e) => setPick({ ...pick, stop_id: e.target.value })}>
                <option value="">—</option>{route?.stops.map((s) => <option key={s.id} value={s.id}>{s.pickup_time.slice(0, 5)} {s.name}</option>)}
              </Select>
            </Field>
            <Field label={t("bus")}>
              <Select required value={pick.bus_id} onChange={(e) => setPick({ ...pick, bus_id: e.target.value })}>
                <option value="">—</option>{buses.filter((b) => b.status === "ACTIVE").map((b) => <option key={b.id} value={b.id}>{b.bus_no} ({b.free})</option>)}
              </Select>
            </Field>
            <Button type="submit" disabled={!student}>{t("assign")}</Button>
          </div>
          {notice && <p className="text-sm text-brand-700" data-testid="transport-notice">✓ {notice}</p>}
        </form>
      </Card>
      <Card title={t("manifest")} actions={
        <Select aria-label={t("route")} className="w-56 print:hidden" value={routeFilter} onChange={(e) => setRouteFilter(e.target.value)}>
          <option value="">{t("allRoutes")}</option>{routes.map((r) => <option key={r.id} value={r.name}>{r.name}</option>)}
        </Select>}>
        {routeFilter && <p className="mb-2 text-sm font-semibold">{routeFilter} · {rows.filter((a) => a.route_name === routeFilter).length} {t("riders")}</p>}
        <ul className="divide-y text-sm" data-testid="manifest">
          {[...rows].filter((a) => !routeFilter || a.route_name === routeFilter)
            .sort((a, b) => a.route_name.localeCompare(b.route_name) || a.pickup_time.localeCompare(b.pickup_time) || a.full_name.localeCompare(b.full_name))
            .map((a) => (
            <li key={a.id} className="flex flex-wrap justify-between gap-2 py-1.5">
              <span>{a.full_name} · {a.admission_no}</span>
              <span className="text-slate-500">{a.route_name} · {a.pickup_time.slice(0, 5)} {a.stop_name} · {a.bus_no}</span>
              <button className="text-xs text-red-700 underline" onClick={() => run(() => api(`/transport-assignments/${a.id}/end`, { method: "POST" }))}>{t("end")}</button>
            </li>))}
          {rows.length === 0 && <li className="py-2 text-slate-500">{t("noResults")}</li>}
        </ul>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t("bus")}>
          <form className="flex flex-wrap items-end gap-2" onSubmit={addBus}>
            <Field label={t("plate")}><Input required placeholder="T 123 ABC" value={busForm.bus_no} onChange={(e) => setBusForm({ ...busForm, bus_no: e.target.value })} /></Field>
            <Field label={t("capacity")}><Input type="number" min={1} max={100} value={busForm.capacity} onChange={(e) => setBusForm({ ...busForm, capacity: e.target.value })} /></Field>
            <Button type="submit" kind="plain">{t("add")}</Button>
          </form>
        </Card>
        <Card title={t("route")}>
          <form className="space-y-2" onSubmit={addRoute}>
            <Field label={t("name")}><Input required minLength={2} value={routeForm.name} onChange={(e) => setRouteForm({ ...routeForm, name: e.target.value })} /></Field>
            <Field label={t("termFee")}><Input inputMode="decimal" value={routeForm.fee} onChange={(e) => setRouteForm({ ...routeForm, fee: e.target.value.replace(/,/g, "") })} /></Field>
            <Field label={t("stopsHelp")}>
              <textarea rows={3} value={routeForm.stops} onChange={(e) => setRouteForm({ ...routeForm, stops: e.target.value })}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" placeholder={"06:30 Kisasa sokoni\n06:45 Nyumba 300"} />
            </Field>
            <Button type="submit" kind="plain">{t("add")}</Button>
          </form>
        </Card>
      </div>
    </div>
  );
}
