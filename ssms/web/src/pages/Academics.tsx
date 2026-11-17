import { FormEvent, Fragment, useState } from "react";

import { Named, nameOf, StreamRow, useCurrentTerm, useList } from "../academic";
import { api, ApiError, fieldErrors } from "../api";
import { useAuth } from "../auth";
import { useLang } from "../i18n";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../ui";

type Tab = "subjects" | "rooms" | "streams" | "weights";
const ROOM_TYPES = ["CLASSROOM", "LABORATORY", "ICT_LAB", "WORKSHOP", "HALL"];

interface Subject extends Named {
  necta_code: string | null;
  room_type: string;
}

interface Room {
  id: string;
  code: string;
  name: string;
  room_type: string;
  capacity: number;
  equipment: Array<{ equipment_id: string; name: string; quantity: number }>;
}

interface EquipmentItem {
  id: string;
  name: string;
  rooms: number;
}

/** Edit what is in a room. Names already used in the school are offered, so one item keeps one spelling. */
function RoomEquipmentEditor({ room, items, onSaved }: { room: Room; items: EquipmentItem[]; onSaved: () => void }) {
  const [, t] = useLang();
  const [lines, setLines] = useState(room.equipment.map((e) => ({ name: e.name, quantity: String(e.quantity) })));
  const [error, setError] = useState<ApiError | null>(null);
  const change = (i: number, patch: Partial<{ name: string; quantity: string }>) =>
    setLines(lines.map((l, n) => (n === i ? { ...l, ...patch } : l)));
  async function save() {
    try {
      const equipment = lines.filter((l) => l.name.trim()).map((l) => ({ name: l.name, quantity: Number(l.quantity) }));
      await api(`/rooms/${room.id}`, { method: "PATCH", body: { equipment } });
      onSaved();
    } catch (e) { setError(e as ApiError); }
  }
  return (
    <div className="space-y-2 py-2" data-testid="room-equipment">
      <ErrorBox error={error} />
      <datalist id="equipment-names">{items.map((i) => <option key={i.id} value={i.name} />)}</datalist>
      {lines.map((l, i) => (
        <div key={i} className="flex gap-2">
          <Input aria-label={t("equipment")} list="equipment-names" value={l.name} onChange={(e) => change(i, { name: e.target.value })} />
          <Input aria-label={t("quantity")} type="number" min={1} className="w-24" value={l.quantity} onChange={(e) => change(i, { quantity: e.target.value })} />
          <Button kind="plain" onClick={() => setLines(lines.filter((_, n) => n !== i))}>✕</Button>
        </div>
      ))}
      <div className="flex gap-2">
        <Button kind="plain" onClick={() => setLines([...lines, { name: "", quantity: "1" }])}>{t("add")}</Button>
        <Button onClick={save}>{t("save")}</Button>
      </div>
    </div>
  );
}

interface WeightRow {
  education_level_id: string;
  subject_code: string | null;
  total_weight: string;
  components: number;
  ok: boolean;
}

function AddForm({ fields, onSave }: {
  fields: Array<{ name: string; label: string; type?: string; options?: string[] }>;
  onSave: (values: Record<string, string>) => Promise<void>;
}) {
  const [, t] = useLang();
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const errors = fieldErrors(error);
  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await onSave(values);
      setValues({});
      setError(null);
    } catch (err) {
      setError(err as ApiError);
    }
  }
  return (
    <form className="mb-4 grid gap-2 sm:grid-cols-5 sm:items-end" onSubmit={submit}>
      {fields.map((f) => (
        <Field key={f.name} label={f.label} error={errors[f.name]}>
          {f.options ? (
            <Select name={f.name} value={values[f.name] ?? f.options[0]} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}>
              {f.options.map((o) => <option key={o}>{o}</option>)}
            </Select>
          ) : (
            <Input name={f.name} type={f.type ?? "text"} required value={values[f.name] ?? ""}
              onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
          )}
        </Field>
      ))}
      <Button type="submit">{t("add")}</Button>
      <div className="sm:col-span-5"><ErrorBox error={error} /></div>
    </form>
  );
}

export default function Academics() {
  const auth = useAuth();
  const [lang, t] = useLang();
  const [tab, setTab] = useState<Tab>("subjects");
  const canEdit = auth.can("academics.configure");
  const [subjects, reloadSubjects] = useList<Subject>("/subjects");
  const [equipmentFilter, setEquipmentFilter] = useState("");
  const [rooms, reloadRooms] = useList<Room>(equipmentFilter ? `/rooms?equipment_id=${equipmentFilter}` : "/rooms");
  const [equipmentItems, reloadItems] = useList<EquipmentItem>(tab === "rooms" ? "/equipment-items" : null);
  const [editingRoom, setEditingRoom] = useState<string | null>(null);
  const [classes] = useList<Named>("/classes");
  const [streams, reloadStreams] = useList<StreamRow>("/streams");
  const { termId } = useCurrentTerm();
  const [weights] = useList<WeightRow>(canEdit && termId && tab === "weights" ? `/assessment-components/weight-check?term_id=${termId}` : null);
  const className = new Map(classes.map((c) => [c.id, c.code]));

  return (
    <Card title={t("academics")}>
      <div className="mb-4 flex flex-wrap gap-2" role="tablist">
        {(["subjects", "rooms", "streams", ...(canEdit ? ["weights"] : [])] as Tab[]).map((k) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`rounded-full px-3 py-1 text-sm ${tab === k ? "bg-brand-500 text-white" : "bg-slate-100"}`}>
            {k === "weights" ? "%" : t(k)}
          </button>
        ))}
      </div>

      {tab === "subjects" && (
        <>
          {canEdit && <AddForm fields={[{ name: "code", label: t("shortCode") }, { name: "name_sw", label: "Jina (sw)" },
            { name: "name_en", label: "Name (en)" }, { name: "room_type", label: t("roomType"), options: ROOM_TYPES }]}
            onSave={async (v) => { await api("/subjects", { body: { room_type: "CLASSROOM", ...v, code: v.code?.toUpperCase() } }); await reloadSubjects(); }} />}
          <table className="w-full text-left text-sm"><tbody>
            {subjects.map((s) => (
              <tr key={s.id} className="border-b last:border-0">
                <td className="py-1.5 pr-3 font-mono text-xs">{s.code}</td><td className="pr-3">{nameOf(s, lang)}</td>
                <td className="pr-3 text-slate-500">{s.necta_code ?? ""}</td><td><Badge>{s.room_type}</Badge></td>
              </tr>))}
          </tbody></table>
        </>
      )}

      {tab === "rooms" && (
        <>
          {canEdit && <AddForm fields={[{ name: "code", label: t("shortCode") }, { name: "name", label: t("name") },
            { name: "capacity", label: t("capacity"), type: "number" }, { name: "room_type", label: t("roomType"), options: ROOM_TYPES }]}
            onSave={async (v) => { await api("/rooms", { body: { room_type: "CLASSROOM", ...v, capacity: Number(v.capacity) } }); await reloadRooms(); }} />}
          <div className="mb-3 max-w-xs">
            <Field label={t("searchByEquipment")}>
              <Select value={equipmentFilter} onChange={(e) => setEquipmentFilter(e.target.value)}>
                <option value="">{t("allEquipment")}</option>
                {equipmentItems.filter((i) => i.rooms > 0).map((i) => <option key={i.id} value={i.id}>{i.name} ({i.rooms})</option>)}
              </Select>
            </Field>
          </div>
          <table className="w-full text-left text-sm"><tbody>
            {rooms.map((r) => (
              <Fragment key={r.id}>
                <tr className="border-b last:border-0">
                  <td className="py-1.5 pr-3 font-mono text-xs">{r.code}</td><td className="pr-3">{r.name}</td>
                  <td className="pr-3">{r.capacity}</td><td className="pr-3"><Badge>{r.room_type}</Badge></td>
                  <td className="pr-3" data-testid="room-equipment-list">{r.equipment.map((e) => (e.quantity > 1 ? `${e.name} ×${e.quantity}` : e.name)).join(", ")}</td>
                  <td>{canEdit && <Button kind="plain" onClick={() => setEditingRoom(editingRoom === r.id ? null : r.id)}>{t("equipment")}</Button>}</td>
                </tr>
                {editingRoom === r.id && (
                  <tr className="border-b"><td colSpan={6}>
                    <RoomEquipmentEditor room={r} items={equipmentItems}
                      onSaved={() => { setEditingRoom(null); reloadRooms(); reloadItems(); }} />
                  </td></tr>
                )}
              </Fragment>))}
          </tbody></table>
        </>
      )}

      {tab === "streams" && (
        <>
          {canEdit && <AddForm fields={[{ name: "class_id", label: t("classLabel"), options: classes.map((c) => c.code) },
            { name: "name", label: t("stream") }, { name: "capacity", label: t("capacity"), type: "number" }]}
            onSave={async (v) => {
              const cls = classes.find((c) => c.code === (v.class_id ?? classes[0]?.code));
              await api("/streams", { body: { class_id: cls?.id, name: v.name, capacity: Number(v.capacity) } });
              await reloadStreams();
            }} />}
          <table className="w-full text-left text-sm">
            <thead className="border-b text-xs uppercase text-slate-500">
              <tr><th className="py-2">{t("classLabel")}</th><th>{t("enrolled")}</th><th>{t("capacity")}</th></tr>
            </thead>
            <tbody>
              {streams.map((s) => (
                <tr key={s.id} className="border-b last:border-0">
                  <td className="py-1.5">{className.get(s.class_id)} {s.name}</td>
                  <td>{s.enrolled ?? 0}</td><td>{s.capacity}</td>
                </tr>))}
            </tbody>
          </table>
        </>
      )}

      {tab === "weights" && (
        <ul className="divide-y text-sm">
          {weights.map((w, i) => (
            <li key={i} className="flex justify-between py-2">
              <span>{w.subject_code ?? "—"} · {w.components}</span>
              <span className={w.ok ? "text-brand-700" : "font-semibold text-red-700"}>{w.total_weight}%</span>
            </li>))}
        </ul>
      )}
    </Card>
  );
}
