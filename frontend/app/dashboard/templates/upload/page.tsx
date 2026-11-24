"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AlertCircle, ArrowLeft, Check, Download, FileSpreadsheet, Loader2, Upload } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { rowForCheck, type BulkResult, type BulkRow } from "../template-excel";
import { RowEditor, RowList, type RowFilter } from "../components/bulk-review";
import Section from "../components/builder-section";
import { useAuthRole } from "../../contexts/AuthRoleContext";

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

const COLUMNS: { name: string; must?: boolean }[] = [
  { name: "Template name", must: true },
  { name: "Type", must: true },
  { name: "Language", must: true },
  { name: "Header" },
  { name: "Header example" },
  { name: "Body", must: true },
  { name: "Example {{1}} … {{5}}", must: true },
  { name: "Footer" },
  { name: "Button 1–3: type, text, link or phone" },
];

/** Upload many templates from Excel: get the sample, fill it, upload, then fix, remove and send on one screen. */
export default function UploadTemplatesPage() {
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("templates.manage");
  const [busy, setBusy] = useState<"" | "checking" | "sending">("");
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
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
  const sentCount = Array.from(results.values()).filter((r) => r.status === "sent").length;

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
      const got = (await res.json()).rows as BulkRow[];
      setRows(got);
      setActiveRow((got.find((r) => r.status === "need_fix") ?? got[0])?.row ?? null);
      window.scrollTo({ top: 0 });
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
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send the templates.");
    } finally {
      setBusy("");
    }
  }

  const fileInput = (
    <input ref={fileRef} type="file" accept=".xlsx" disabled={!!busy} className="sr-only" onChange={(e) => onFile(e.target.files?.[0])} />
  );

  return (
    <div className="w-full pb-28">

      {error && (
        <div role="alert" className="mb-4 flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <p>{error}</p>
        </div>
      )}

      {!canManage ? (
        <p className="rounded-2xl border border-[#e7e2da] bg-white p-6 text-sm text-ink-secondary">You need permission to manage templates to upload them.</p>
      ) : !rows ? (
        /* ── Before the upload: three steps, like Create Template's sections ── */
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="min-w-0 space-y-4">
            <Section n={1} title="Get the sample file" hint="the columns Anril reads" done={false}>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={async () => { try { setError(null); await downloadSample(); } catch (e) { setError(e instanceof Error ? e.message : "Couldn't download it."); } }}
                  className="inline-flex h-10 items-center gap-2 rounded-xl border border-primary-200 bg-primary-50 px-4 text-sm font-semibold text-primary-800 transition hover:bg-primary-100"
                >
                  <Download size={15} aria-hidden="true" /> sample_templates.xlsx
                </button>
                <span className="text-[12.5px] text-ink-muted">Two filled example rows, dropdowns for Type, Language and Button type, and a How to fill sheet.</span>
              </div>
            </Section>

            <Section n={2} title="Fill one row per template" hint="keep the columns as they are" done={false}>
              <div className="flex flex-wrap gap-2">
                {COLUMNS.map((c) => (
                  <span
                    key={c.name}
                    className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[12.5px] font-semibold ${
                      c.must ? "bg-orange-50 text-orange-800 ring-1 ring-orange-100" : "bg-surface-subtle text-ink-secondary"
                    }`}
                  >
                    {c.name}
                    {c.must && <span aria-label="must fill">*</span>}
                  </span>
                ))}
              </div>
              <p className="mt-3 text-[12.5px] text-ink-muted">
                <span className="font-semibold text-orange-800">*</span> must be filled. Every {"{{n}}"} in the Body needs its example. Up to 50 rows.
              </p>
            </Section>

            <Section n={3} title="Upload it" hint=".xlsx, under 2 MB" done={false} active>
              <label
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => { e.preventDefault(); setDragging(false); onFile(e.dataTransfer.files?.[0]); }}
                className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition ${
                  dragging ? "border-primary bg-primary-50/60" : "border-[#d9d3c8] bg-[#fbfaf7] hover:border-primary-300 hover:bg-primary-50/40"
                } ${busy ? "pointer-events-none opacity-70" : ""}`}
              >
                {fileInput}
                <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary text-white shadow-md">
                  {busy === "checking" ? <Loader2 size={22} className="animate-spin" /> : <Upload size={22} aria-hidden="true" />}
                </span>
                <span className="text-[15px] font-bold text-ink">{busy === "checking" ? "Checking every row…" : "Drop your Excel file here, or click to choose"}</span>
                <span className="text-[12.5px] text-ink-muted">Nothing is sent to Meta until you review and press Send.</span>
              </label>
            </Section>
          </div>

          <aside className="min-w-0 space-y-4 xl:sticky xl:top-4">
            <section className="rounded-2xl border border-[#e7e2da] bg-white p-5">
              <h2 className="mb-3 text-sm font-bold text-ink">After you upload</h2>
              <ol className="space-y-3 text-[13px] text-ink-secondary">
                {[
                  "Every template opens with a WhatsApp preview and, if something is wrong, the reason on that field.",
                  "Fix it right there. It's checked again as you type, no new upload needed.",
                  "Remove the rows you don't need, untick the ones to leave out.",
                  "Send the ready ones to Meta together. Each row shows Sent or the reason Meta refused it.",
                ].map((t, n) => (
                  <li key={n} className="flex gap-2.5">
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary-50 text-[11px] font-bold text-primary">{n + 1}</span>
                    <span>{t}</span>
                  </li>
                ))}
              </ol>
            </section>
            <p className="text-[12.5px] leading-relaxed text-ink-muted">
              Text headers only: picture, video and document headers are made in Create Template. Names that already exist are skipped, never changed.
            </p>
          </aside>
        </div>
      ) : (
        /* ── Review: list on the left, the chosen template on the right ── */
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-[#e7e2da] bg-white px-4 py-3 shadow-sm">
            <span className="mr-1 inline-flex min-w-0 items-center gap-1.5 text-[13.5px] font-semibold text-ink">
              <FileSpreadsheet size={15} className="shrink-0 text-primary" aria-hidden="true" />
              <span className="truncate">{fileName || "Your file"}</span>
              <span className="shrink-0 text-ink-muted">· {counts.all} rows</span>
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

          <div className="grid items-start gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
            <div className={`overflow-hidden rounded-2xl border border-[#e7e2da] bg-white shadow-sm lg:sticky lg:top-4 ${mobileEditor ? "hidden lg:block" : ""}`}>
              <div className="max-h-[calc(100dvh-14rem)] overflow-y-auto">
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
            </div>
            <section className={`min-w-0 rounded-2xl border border-[#e7e2da] bg-white p-5 shadow-sm md:p-6 ${mobileEditor ? "" : "hidden lg:block"}`}>
              <button type="button" onClick={() => setMobileEditor(false)} className="mb-3 inline-flex items-center gap-1 text-[13px] font-semibold text-primary lg:hidden">
                <ArrowLeft size={14} /> All rows
              </button>
              {active ? (
                <>
                  <p className="mb-4 font-display text-base font-bold text-ink">
                    Row {active.row} <span className="font-mono text-[14px] font-semibold text-ink-secondary">· {active.name || "(no name)"}</span>
                  </p>
                  <RowEditor row={active} locked={isSent(active.row)} removed={removed.has(active.row)} onChange={editRow} />
                </>
              ) : (
                <p className="py-16 text-center text-sm text-ink-muted">Pick a row to see it.</p>
              )}
            </section>
          </div>
        </div>
      )}

      {canManage && (
        <div className="sticky bottom-0 z-20 -mx-4 mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-[#e7e2da] bg-white/95 px-4 py-3 backdrop-blur md:-mx-6 md:px-6">
          <p className="text-[13px] font-medium text-ink-secondary">
            {!rows
              ? "Choose your Excel file above. Nothing is sent to Meta until you press Send."
              : sentCount
              ? `${sentCount} sent to Meta. Approvals usually come within minutes.`
              : toSend.length
                ? `${toSend.length} ready to send. Fixed rows join automatically.`
                : "Fix a row or tick one to send."}
          </p>
          <div className="flex w-full items-center gap-2 sm:w-auto [&>button]:flex-1 sm:[&>button]:flex-none">
            <Link
              href="/dashboard/templates"
              className="inline-flex h-11 shrink-0 items-center justify-center gap-1.5 rounded-xl border border-[#ddd8cf] bg-white px-4 text-sm font-semibold text-ink transition hover:bg-surface-subtle"
            >
              <ArrowLeft size={15} aria-hidden="true" /> Back
            </Link>
            {rows && (
            <>
            <label className={`inline-flex h-11 cursor-pointer items-center justify-center rounded-xl border border-[#ddd8cf] bg-white px-4 text-sm font-semibold text-ink hover:bg-surface-subtle ${busy ? "pointer-events-none opacity-50" : ""}`}>
              Upload again
              {fileInput}
            </label>
            <button
              type="button"
              onClick={send}
              disabled={!!busy || rechecking || toSend.length === 0}
              className="inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-primary px-5 text-sm font-bold text-white shadow-md transition hover:bg-primary/90 disabled:opacity-50 sm:flex-none"
            >
              {busy === "sending" && <Loader2 size={14} className="animate-spin" />}
              {busy === "sending" ? "Sending…" : `Send ${toSend.length} to Meta for approval`}
            </button>
            </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
