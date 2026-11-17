// Shared building blocks for list pages and dialogs (design/20 §20.6): DataTable, Modal, ConfirmDialog.
import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, ApiError, Page } from "./api";
import { useLang } from "./i18n";
import { Button, ErrorBox } from "./ui";

/** Rows per page; list endpoints return at most 50. */
export const PAGE_SIZE = 50;

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  /** Value to sort by; columns without it are not sortable. */
  sort?: (row: T) => string | number;
  className?: string;
}

type Sort = { key: string; dir: 1 | -1 } | null;

/**
 * A server-paged table. `load` fetches one page for a cursor (null = first page); when `reloadKey` changes the table
 * goes back to the first page. Sorting a column orders the rows of the page on screen; the server's order decides
 * which rows are on each page.
 */
export function DataTable<T>({ columns, load, reloadKey, rowKey, label }: {
  columns: Column<T>[];
  load: (cursor: string | null) => Promise<Page<T>>;
  reloadKey: string;
  rowKey: (row: T) => string;
  label: string;
}) {
  const [, t] = useLang();
  const [rows, setRows] = useState<T[]>([]);
  const [cursors, setCursors] = useState<Array<string | null>>([null]); // cursor of each page seen so far
  const [pageNo, setPageNo] = useState(0);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [sort, setSort] = useState<Sort>(null);
  const request = useRef(0);

  const show = useCallback(async (index: number, cursor: string | null) => {
    const mine = ++request.current;
    setLoading(true);
    try {
      const page = await load(cursor);
      if (mine !== request.current) return; // a newer request has started
      setRows(page.items);
      setNext(page.next_cursor);
      setPageNo(index);
      setError(null);
    } catch (e) {
      if (mine === request.current) setError(e as ApiError);
    } finally {
      if (mine === request.current) setLoading(false);
    }
  }, [load]);

  useEffect(() => {
    setCursors([null]);
    show(0, null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadKey]);

  const sorted = useMemo(() => {
    const column = sort && columns.find((c) => c.key === sort.key);
    if (!sort || !column?.sort) return rows;
    const value = column.sort;
    return [...rows].sort((a, b) => {
      const x = value(a), y = value(b);
      return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * sort.dir;
    });
  }, [rows, sort, columns]);

  function toggle(key: string) {
    setSort((s) => (s?.key !== key ? { key, dir: 1 } : s.dir === 1 ? { key, dir: -1 } : null));
  }

  function goNext() {
    if (!next) return;
    setCursors((c) => [...c.slice(0, pageNo + 1), next]);
    show(pageNo + 1, next);
  }

  const first = pageNo * PAGE_SIZE + 1;
  return (
    <div>
      <ErrorBox error={error} />
      <div className="overflow-x-auto" aria-busy={loading}>
        <table className="w-full text-left text-sm" aria-label={label}>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} className={`py-2 pr-3 ${c.className ?? ""}`}
                  aria-sort={sort?.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : undefined}>
                  {c.sort ? (
                    <button type="button" onClick={() => toggle(c.key)}
                      className="inline-flex items-center gap-1 uppercase tracking-wider hover:text-slate-800">
                      {c.header}
                      <span aria-hidden="true" className={sort?.key === c.key ? "text-brand-600" : "text-slate-300"}>
                        {sort?.key === c.key && sort.dir === -1 ? "▼" : "▲"}
                      </span>
                    </button>
                  ) : c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && rows.length === 0
              ? [0, 1, 2, 3, 4].map((i) => (
                <tr key={`skeleton-${i}`} aria-hidden="true">
                  {columns.map((c) => <td key={c.key} className="py-3 pr-3"><span className="block h-3 w-3/4 animate-pulse rounded bg-slate-200" /></td>)}
                </tr>))
              : sorted.map((row) => (
                <tr key={rowKey(row)} className="border-b border-slate-100 last:border-0">
                  {columns.map((c) => <td key={c.key} className={`py-2 pr-3 ${c.className ?? ""}`}>{c.render(row)}</td>)}
                </tr>))}
          </tbody>
        </table>
      </div>
      {(rows.length > 0 || pageNo > 0) && (
        <nav aria-label={t("pages")} className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm text-slate-600">
          <p>{t("rowsShown")} {first}–{first + rows.length - 1}{next ? "" : ` ${t("rowsOf")} ${first + rows.length - 1}`}</p>
          <div className="flex gap-2">
            <Button kind="plain" disabled={pageNo === 0 || loading} onClick={() => show(pageNo - 1, cursors[pageNo - 1])}>← {t("previous")}</Button>
            <Button kind="plain" disabled={!next || loading} onClick={goNext}>{t("next")} →</Button>
          </div>
        </nav>
      )}
    </div>
  );
}

/** A modal dialog on the native <dialog> element: focus stays inside, Escape closes it, the page behind is inert. */
export function Modal({ open, title, onClose, children, footer }: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="modal-title"
      className="w-[min(32rem,calc(100vw-2rem))] rounded-2xl border border-slate-200 bg-white p-0 text-slate-900 shadow-lift backdrop:bg-slate-900/50">
      {open && (
        <div className="p-5 sm:p-6">
          <h2 id="modal-title" className="text-lg font-semibold tracking-tight">{title}</h2>
          <div className="mt-3 text-sm text-slate-700">{children}</div>
          {footer && <div className="mt-6 flex flex-wrap justify-end gap-2">{footer}</div>}
        </div>
      )}
    </dialog>
  );
}

/** `confirm(text)` opens a dialog and resolves true only when the person presses the confirm button. */
export function useConfirm(): [(text: string, action: string) => Promise<boolean>, ReactNode] {
  const [, t] = useLang();
  const [ask, setAsk] = useState<{ text: string; action: string; resolve: (ok: boolean) => void } | null>(null);
  const confirm = useCallback((text: string, action: string) => new Promise<boolean>((resolve) => setAsk({ text, action, resolve })), []);
  const answer = (ok: boolean) => {
    ask?.resolve(ok);
    setAsk(null);
  };
  const dialog = (
    <Modal open={ask !== null} title={t("areYouSure")} onClose={() => answer(false)}
      footer={<>
        <Button kind="plain" onClick={() => answer(false)}>{t("cancel")}</Button>
        <Button className="!bg-red-700 hover:!bg-red-800" onClick={() => answer(true)}>{ask?.action}</Button>
      </>}>
      <p>{ask?.text}</p>
    </Modal>
  );
  return [confirm, dialog];
}

/** A row of tabs; only the tabs the person may use are passed in. */
export function Tabs<K extends string>({ tabs, value, onChange, label }: {
  tabs: Array<[K, string]>;
  value: K;
  onChange: (key: K) => void;
  label: string;
}) {
  if (tabs.length < 2) return null;
  return (
    <div className="mb-4 inline-flex max-w-full flex-wrap gap-1 rounded-xl border border-slate-200 bg-slate-100 p-1" role="tablist" aria-label={label}>
      {tabs.map(([key, text]) => (
        <button key={key} type="button" role="tab" aria-selected={value === key} onClick={() => onChange(key)}
          className={`rounded-lg px-3.5 py-1.5 text-sm font-semibold transition ${value === key ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-900"}`}>
          {text}
        </button>
      ))}
    </div>
  );
}

export interface Uploaded { id: string; original_name: string; content_type: string; size_bytes: number; url: string }

/** Shrinks a photograph in the browser (longest side 600 px, JPEG) so it fits the 300 KB photo limit. */
async function shrinkPhoto(file: File): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 600 / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("encode"))), "image/jpeg", 0.85));
}

/** Uploads one file to POST /files for a purpose; the server checks the real type and size. */
export function FileUpload({ purpose, accept, label, onUploaded }: {
  purpose: "PHOTO" | "STUDY_MATERIAL" | "HOMEWORK" | "SUBMISSION" | "RECEIPT" | "CERT_TEMPLATE";
  accept: string;
  label: string;
  onUploaded: (file: Uploaded) => void;
}) {
  const [, t] = useLang();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  async function pick(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const body = purpose === "PHOTO" ? await shrinkPhoto(file) : file;
      const form = new FormData();
      form.set("purpose", purpose);
      form.set("file", body, purpose === "PHOTO" ? file.name.replace(/\.[^.]+$/, "") + ".jpg" : file.name);
      onUploaded(await api<Uploaded>("/files", { form }));
    } catch (e) {
      setError((e as ApiError).error_code ? (e as ApiError) : { status: 0, error_code: "FILE_TYPE", message: t("fileUnreadable"), details: [] });
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-2">
      <label className={`inline-flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-brand-300 bg-brand-50 px-4 py-2 text-sm font-semibold text-brand-700 hover:bg-brand-100 ${busy ? "opacity-60" : ""}`}>
        <input type="file" accept={accept} className="sr-only" disabled={busy} onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
        {busy ? t("uploading") : label}
      </label>
      <ErrorBox error={error} />
    </div>
  );
}
