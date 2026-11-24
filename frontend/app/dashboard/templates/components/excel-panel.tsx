"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Check, Download, FileSpreadsheet, Loader2, Upload, X } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import type { Template, TemplateUsage } from "../types";
import { rowForCheck, saveAllTemplates, type BulkResult, type BulkRow } from "../template-excel";
import { RowEditor, RowList, type RowFilter } from "./bulk-review";

type Props = {
  open: boolean;
  onClose: () => void;
  totalCount: number;
  canManage: boolean;
  /** Fresh list + usage for "Download all": the whole account, not just what the filters show. */
  loadAll: () => Promise<{ templates: Template[]; usage: TemplateUsage }>;
  /** After templates were sent to Meta, so the list shows them. */
  onSubmitted: () => void;
};

async function errorText(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join(" ");
  return `Something went wrong (${res.status}).`;
}

async function downloadSample() {
  const res = await fetch(`${API_URL}/api/v1/templates/bulk/sample`, { headers: await getAuthHeaders() });
  if (!res.ok) throw new Error(await errorText(res));
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = "sample_templates.xlsx";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const FILTERS: { key: RowFilter; label: string; cls: string }[] = [
  { key: "all", label: "All", cls: "bg-surface-subtle text-ink" },
  { key: "ready", label: "ready", cls: "bg-emerald-50 text-emerald-700" },
  { key: "need_fix", label: "need a fix", cls: "bg-red-50 text-red-700" },
  { key: "exists", label: "already exist", cls: "bg-amber-50 text-amber-800" },
  { key: "removed", label: "removed", cls: "bg-slate-100 text-slate-600" },
];

export default function ExcelPanel({ open, onClose, totalCount, canManage, loadAll, onSubmitted }: Props) {
  const [tab, setTab] = useState<"upload" | "download">("upload");
  const [busy, setBusy] = useState<"" | "checking" | "sending" | "download">("");
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState("");
  const [rows, setRows] = useState<BulkRow[] | null>(null);
  const [removed, setRemoved] = useState<Set<number>>(new Set());
  const [unticked, setUnticked] = useState<Set<number>>(new Set());
  const [results, setResults] = useState<Map<number, BulkResult>>(new Map());
  const [activeRow, setActiveRow] = useState<number | null>(null);
  const [mobileEditor, setMobileEditor] = useState(false);
  const [filter, setFilter] = useState<RowFilter>("all");
  const [rechecking, setRechecking] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const recheckTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const version = useRef(0);

  useEffect(() => () => { if (recheckTimer.current) clearTimeout(recheckTimer.current); }, []);

  const isSent = (r: number) => results.get(r)?.status === "sent";
  const live = useMemo(() => (rows ?? []).filter((r) => !removed.has(r.row)), [rows, removed]);
  const counts = useMemo(() => ({
    all: rows?.length ?? 0,
    ready: live.filter((r) => r.status === "ready").length,
    need_fix: live.filter((r) => r.status === "need_fix").length,
    exists: live.filter((r) => r.status === "exists").length,
    removed: removed.size,
  }), [rows, live, removed]);
  const toSend = live.filter((r) => r.status === "ready" && !unticked.has(r.row) && !isSent(r.row));
  const shown = (rows ?? []).filter((r) =>
    filter === "all" ? true : filter === "removed" ? removed.has(r.row) : !removed.has(r.row) && r.status === filter,
  );
  const active = rows?.find((r) => r.row === activeRow) ?? null;

  if (!open) return null;

  function reset() {
    setRows(null);
    setRemoved(new Set());
    setUnticked(new Set());
    setResults(new Map());
    setActiveRow(null);
    setFilter("all");
    setFileName("");
    setError(null);
    setMobileEditor(false);
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    reset();
    setFileName(file.name);
    setBusy("checking");
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${API_URL}/api/v1/templates/bulk/check`, { method: "POST", headers: await getAuthHeaders(), body: form });
      if (!res.ok) throw new Error(await errorText(res));
      const data = await res.json();
      const got = data.rows as BulkRow[];
      setRows(got);
      setActiveRow((got.find((r) => r.status === "need_fix") ?? got[0])?.row ?? null);
    } catch (e) {
      setFileName("");
      setError(e instanceof Error ? e.message : "Couldn't read the file.");
    } finally {
      setBusy("");
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  /** Check every row still in the upload again (a fix in one row can clear a duplicate in another). */
  function scheduleRecheck(nextRows: BulkRow[], nextRemoved: Set<number>) {
    if (recheckTimer.current) clearTimeout(recheckTimer.current);
    const mine = ++version.current;
    setRechecking(true);
    recheckTimer.current = setTimeout(async () => {
      try {
        const keep = nextRows.filter((r) => !nextRemoved.has(r.row) && results.get(r.row)?.status !== "sent");
        const res = await fetch(`${API_URL}/api/v1/templates/bulk/recheck`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(await getAuthHeaders()) },
          body: JSON.stringify({ rows: keep.map(rowForCheck) }),
        });
        if (!res.ok) throw new Error(await errorText(res));
        const checked = new Map((await res.json()).rows.map((r: BulkRow) => [r.row, r]));
        if (mine !== version.current) return; // a newer edit is on its way
        setRows((cur) => (cur ?? []).map((r) => (checked.get(r.row) as BulkRow | undefined) ?? r));
      } catch (e) {
        if (mine === version.current) setError(e instanceof Error ? e.message : "Couldn't check the changes.");
      } finally {
        if (mine === version.current) setRechecking(false);
      }
    }, 450);
  }

  function editRow(next: BulkRow) {
    const nextRows = (rows ?? []).map((r) => (r.row === next.row ? next : r));
    setRows(nextRows);
    if (results.get(next.row)?.status === "refused") {
      // a refused row that is fixed can be sent again
      setResults((m) => { const c = new Map(m); c.delete(next.row); return c; });
    }
    scheduleRecheck(nextRows, removed);
  }

  function removeRow(row: number, remove: boolean) {
    const next = new Set(removed);
    if (remove) next.add(row); else next.delete(row);
    setRemoved(next);
    scheduleRecheck(rows ?? [], next);
  }

  function tick(row: number, on: boolean) {
    setUnticked((s) => { const c = new Set(s); if (on) c.delete(row); else c.add(row); return c; });
  }

  async function send() {
    if (!toSend.length) return;
    setBusy("sending");
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/v1/templates/bulk/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await getAuthHeaders()) },
        body: JSON.stringify({ rows: toSend.map(rowForCheck) }),
      });
      if (!res.ok) throw new Error(await errorText(res));
      const got = (await res.json()).results as BulkResult[];
      setResults((m) => { const c = new Map(m); got.forEach((r) => c.set(r.row, r)); return c; });
      onSubmitted();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send the templates.");
    } finally {
      setBusy("");
    }
  }

  async function downloadAll() {
    setBusy("download");
    setError(null);
    try {
      const { templates, usage } = await loadAll();
      await saveAllTemplates(templates, usage);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't make the file.");
    } finally {
      setBusy("");
    }
  }

  const reviewing = tab === "upload" && !!rows;
  const sentCount = Array.from(results.values()).filter((r) => r.status === "sent").length;
  const tabCls = (on: boolean) =>
    `flex items-center gap-1.5 border-b-2 px-1 py-2.5 text-sm font-semibold transition-colors ${
      on ? "border-primary text-primary" : "border-transparent text-ink-muted hover:text-ink"
    }`;

  return (
    <div className="fixed inset-0 z-dialog flex justify-end bg-black/40" onClick={() => !busy && onClose()}>
      <aside
        role="dialog"
        aria-label="Excel"
        className={`flex h-full w-full flex-col bg-white shadow-2xl transition-[max-width] duration-300 ${reviewing ? "max-w-7xl" : "max-w-xl"}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border-subtle px-5 py-3.5">
          <div className="flex items-center gap-2">
            <FileSpreadsheet size={18} className="text-primary" aria-hidden="true" />
            <h2 className="font-display text-base font-bold text-ink">Excel</h2>
          </div>
          <button onClick={onClose} disabled={!!busy} aria-label="Close" className="rounded-lg p-2 text-ink-muted hover:bg-surface-subtle hover:text-ink">
            <X size={16} />
          </button>
        </div>

        <div className="flex gap-6 border-b border-border-subtle px-5" role="tablist">
          <button role="tab" aria-selected={tab === "upload"} className={tabCls(tab === "upload")} onClick={() => setTab("upload")}>
            <Upload size={14} aria-hidden="true" /> Upload many
          </button>
          <button role="tab" aria-selected={tab === "download"} className={tabCls(tab === "download")} onClick={() => setTab("download")}>
            <Download size={14} aria-hidden="true" /> Download all ({totalCount})
          </button>
        </div>

        {error && (
          <p role="alert" className="mx-5 mt-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
        )}

        {tab === "download" ? (
          <div className="space-y-4 p-5">
            <p className="text-sm text-ink-secondary">
              One sheet with every template on this account (not only what the filters show): name, type, language,
              status, message, footer, buttons, where it is used and why it was rejected or paused. Good for checking
              with your team or keeping a copy.
            </p>
            <button onClick={downloadAll} disabled={!!busy || totalCount === 0} className="btn-primary inline-flex items-center gap-2 text-sm disabled:opacity-50">
              <Download size={14} aria-hidden="true" />
              {busy === "download" ? "Preparing…" : `Download all ${totalCount} templates`}
            </button>
          </div>
        ) : !canManage ? (
          <p className="p-5 text-sm text-ink-secondary">You need permission to manage templates to upload them.</p>
        ) : !rows ? (
          /* ── step 1-3: get the file in ───────────────────────────── */
          <div className="space-y-5 overflow-y-auto p-5">
            <ol className="grid gap-2.5 sm:grid-cols-3">
              <li className="rounded-2xl border border-[#e7e2da] p-3.5">
                <p className="flex items-center gap-1.5 text-[13px] font-bold text-ink"><span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary-50 text-[11px] text-primary">1</span> Download the sample</p>
                <button
                  type="button"
                  onClick={async () => { try { await downloadSample(); } catch (e) { setError(e instanceof Error ? e.message : "Couldn't download it."); } }}
                  className="mt-1.5 inline-flex items-center gap-1 text-[13px] font-semibold text-primary hover:underline"
                >
                  sample_templates.xlsx <Download size={12} aria-hidden="true" />
                </button>
              </li>
              <li className="rounded-2xl border border-[#e7e2da] p-3.5">
                <p className="flex items-center gap-1.5 text-[13px] font-bold text-ink"><span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary-50 text-[11px] text-primary">2</span> One row per template</p>
                <p className="mt-1 text-[12.5px] leading-snug text-ink-muted">Keep the columns as they are. Name, type, language, body and each {"{{n}}"} example are a must.</p>
              </li>
              <li className="rounded-2xl border-2 border-primary-200 bg-primary-50/40 p-3.5">
                <p className="flex items-center gap-1.5 text-[13px] font-bold text-ink"><span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary text-[11px] text-white">3</span> Upload it here</p>
                <label className={`mt-2 inline-flex cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-3 py-1.5 text-[13px] font-semibold text-white shadow-sm hover:bg-primary/90 ${busy ? "opacity-60" : ""}`}>
                  {busy === "checking" ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} aria-hidden="true" />}
                  {busy === "checking" ? "Checking…" : "Choose file"}
                  <input ref={fileRef} type="file" accept=".xlsx" disabled={!!busy} className="sr-only" onChange={(e) => onFile(e.target.files?.[0])} />
                </label>
              </li>
            </ol>
            <div className="rounded-2xl bg-surface-subtle px-4 py-3 text-[13px] leading-relaxed text-ink-secondary">
              <p className="font-semibold text-ink">After you upload</p>
              <p>Every template opens with a WhatsApp preview and the reason if anything is wrong. Fix it right there, remove what you don&apos;t need, then send them to Meta together.</p>
              <p className="mt-1.5 text-ink-muted">Up to 50 templates per file. Text headers only: picture, video and document headers are made in the builder. Names that already exist are skipped, never changed.</p>
            </div>
          </div>
        ) : (
          /* ── review: list, editor, preview ───────────────────────── */
          <>
            <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle px-5 py-3">
              <span className="mr-1 inline-flex items-center gap-1.5 text-[13px] font-semibold text-ink">
                <FileSpreadsheet size={14} className="text-primary" aria-hidden="true" /> {fileName || "Your file"} · {counts.all} rows
              </span>
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show">
                {FILTERS.map((f) => {
                  const n = counts[f.key];
                  if (f.key !== "all" && !n) return null;
                  return (
                    <button
                      key={f.key}
                      type="button"
                      onClick={() => setFilter(f.key)}
                      aria-pressed={filter === f.key}
                      className={`rounded-full px-2.5 py-1 text-[12px] font-semibold transition ${f.cls} ${filter === f.key ? "ring-2 ring-primary-300" : "opacity-90 hover:opacity-100"}`}
                    >
                      {f.key === "all" ? `All ${n}` : f.key === "exists" && n === 1 ? "1 already exists" : `${n} ${f.label}`}
                    </button>
                  );
                })}
              </div>
              <span className="ml-auto inline-flex items-center gap-1.5 text-[12px] text-ink-muted" aria-live="polite">
                {rechecking ? <><Loader2 size={12} className="animate-spin" /> Checking your changes…</> : <><Check size={12} /> Checked</>}
              </span>
            </div>

            <div className="grid min-h-0 flex-1 md:grid-cols-[320px_minmax(0,1fr)]">
              <div className={`min-h-0 overflow-y-auto border-r border-border-subtle ${mobileEditor ? "hidden md:block" : ""}`}>
                <RowList
                  rows={shown}
                  removed={removed}
                  ticked={new Set(toSend.map((r) => r.row))}
                  results={results}
                  activeRow={activeRow}
                  onOpen={(r) => { setActiveRow(r); setMobileEditor(true); }}
                  onTick={tick}
                  onRemove={removeRow}
                />
              </div>
              <div className={`min-h-0 overflow-y-auto p-5 ${mobileEditor ? "" : "hidden md:block"}`}>
                <button type="button" onClick={() => setMobileEditor(false)} className="mb-3 inline-flex items-center gap-1 text-[13px] font-semibold text-primary md:hidden">
                  <ArrowLeft size={14} /> All rows
                </button>
                {active ? (
                  <>
                    <p className="mb-3 text-[12px] font-semibold uppercase tracking-wider text-ink-muted">Row {active.row}</p>
                    <RowEditor row={active} locked={isSent(active.row)} removed={removed.has(active.row)} onChange={editRow} />
                  </>
                ) : (
                  <p className="py-16 text-center text-sm text-ink-muted">Pick a row to see it.</p>
                )}
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle px-5 py-3.5">
              <p className="text-[12.5px] text-ink-muted">
                {sentCount ? `${sentCount} sent to Meta. Approvals usually come within minutes.` : "Fixed rows join automatically. Untick a row to leave it out."}
              </p>
              <div className="flex items-center gap-2">
                <label className={`btn-ghost cursor-pointer text-sm ${busy ? "pointer-events-none opacity-50" : ""}`}>
                  Upload again
                  <input ref={fileRef} type="file" accept=".xlsx" disabled={!!busy} className="sr-only" onChange={(e) => onFile(e.target.files?.[0])} />
                </label>
                <button
                  type="button"
                  onClick={send}
                  disabled={!!busy || rechecking || toSend.length === 0}
                  className="inline-flex h-10 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-white shadow-md transition hover:bg-primary/90 disabled:opacity-50"
                >
                  {busy === "sending" && <Loader2 size={14} className="animate-spin" />}
                  {busy === "sending" ? "Sending…" : `Send ${toSend.length} to Meta for approval`}
                </button>
              </div>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
