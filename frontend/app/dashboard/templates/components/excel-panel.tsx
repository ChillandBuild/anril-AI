"use client";

import { useRef, useState } from "react";
import { Download, FileSpreadsheet, Upload, X } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import type { Template, TemplateUsage } from "../types";
import { languageName } from "../types";
import {
  countsText,
  saveAllTemplates,
  saveSampleFile,
  type BulkCounts,
  type BulkResult,
  type BulkRow,
} from "../template-excel";

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

const STATUS_PILL: Record<BulkRow["status"], { text: string; cls: string }> = {
  ready: { text: "Ready", cls: "bg-emerald-50 text-emerald-700" },
  need_fix: { text: "Needs a fix", cls: "bg-amber-50 text-amber-800" },
  exists: { text: "Already exists", cls: "bg-slate-100 text-slate-700" },
};

const RESULT_PILL: Record<BulkResult["status"], { text: string; cls: string }> = {
  sent: { text: "Sent to Meta", cls: "bg-emerald-50 text-emerald-700" },
  refused: { text: "Meta refused", cls: "bg-red-50 text-red-700" },
  skipped: { text: "Not sent", cls: "bg-slate-100 text-slate-700" },
};

async function errorText(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join(" ");
  return `Something went wrong (${res.status}).`;
}

export default function ExcelPanel({ open, onClose, totalCount, canManage, loadAll, onSubmitted }: Props) {
  const [tab, setTab] = useState<"upload" | "download">("upload");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<BulkRow[] | null>(null);
  const [counts, setCounts] = useState<BulkCounts | null>(null);
  const [results, setResults] = useState<BulkResult[] | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  if (!open) return null;

  async function guard(job: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await job();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    setRows(null);
    setCounts(null);
    setResults(null);
    await guard(async () => {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${API_URL}/api/v1/templates/bulk/check`, {
        method: "POST",
        headers: await getAuthHeaders(),
        body: form,
      });
      if (!res.ok) throw new Error(await errorText(res));
      const data = await res.json();
      setRows(data.rows);
      setCounts(data.counts);
    });
    if (fileRef.current) fileRef.current.value = "";
  }

  async function sendReady() {
    const ready = (rows ?? []).filter((r) => r.status === "ready");
    if (!ready.length) return;
    await guard(async () => {
      const res = await fetch(`${API_URL}/api/v1/templates/bulk/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await getAuthHeaders()) },
        body: JSON.stringify({ rows: ready }),
      });
      if (!res.ok) throw new Error(await errorText(res));
      setResults((await res.json()).results);
      onSubmitted();
    });
  }

  async function downloadAll() {
    await guard(async () => {
      const { templates, usage } = await loadAll();
      await saveAllTemplates(templates, usage);
    });
  }

  const readyCount = counts?.ready ?? 0;
  const tabCls = (active: boolean) =>
    `flex-1 border-b-2 px-3 py-2.5 text-sm font-semibold transition-colors ${
      active ? "border-primary text-primary" : "border-transparent text-ink-muted hover:text-ink"
    }`;

  return (
    <div className="fixed inset-0 z-dialog flex justify-end bg-black/40" onClick={onClose}>
      <aside
        role="dialog"
        aria-label="Excel"
        className="flex h-full w-full max-w-xl flex-col bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border-subtle px-5 py-4">
          <div className="flex items-center gap-2">
            <FileSpreadsheet size={18} className="text-primary" aria-hidden="true" />
            <h2 className="font-display text-base font-bold text-ink">Excel</h2>
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-lg p-2 text-ink-muted hover:bg-surface-subtle hover:text-ink">
            <X size={16} />
          </button>
        </div>

        <div className="flex border-b border-border-subtle" role="tablist">
          <button role="tab" aria-selected={tab === "upload"} className={tabCls(tab === "upload")} onClick={() => setTab("upload")}>
            Upload many
          </button>
          <button role="tab" aria-selected={tab === "download"} className={tabCls(tab === "download")} onClick={() => setTab("download")}>
            Download all ({totalCount})
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {error && <p role="alert" className="mb-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

          {tab === "download" ? (
            <div className="space-y-4">
              <p className="text-sm text-ink-secondary">
                One sheet with every template on this account (not only what the filters show): name, type, language,
                status, message, footer, buttons, where it is used and why it was rejected or paused.
              </p>
              <button onClick={downloadAll} disabled={busy || totalCount === 0} className="btn-primary inline-flex items-center gap-2 text-sm disabled:opacity-50">
                <Download size={14} aria-hidden="true" />
                {busy ? "Preparing…" : `Download all ${totalCount} templates`}
              </button>
            </div>
          ) : !canManage ? (
            <p className="text-sm text-ink-secondary">You need permission to manage templates to upload them.</p>
          ) : (
            <div className="space-y-5">
              <p className="text-sm text-ink-secondary">
                Make many simple templates in one go: a message, an optional footer and one website button. For anything
                else (pictures, several buttons, OTP) use the builder.
              </p>
              <div className="flex flex-wrap gap-2">
                <button onClick={() => guard(saveSampleFile)} className="btn-ghost inline-flex items-center gap-2 text-sm">
                  <Download size={14} aria-hidden="true" /> Download the sample file
                </button>
                <label className={`btn-primary inline-flex cursor-pointer items-center gap-2 text-sm ${busy ? "opacity-50" : ""}`}>
                  <Upload size={14} aria-hidden="true" /> {busy && !rows ? "Checking…" : "Upload your file"}
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".xlsx"
                    disabled={busy}
                    className="sr-only"
                    onChange={(e) => onFile(e.target.files?.[0])}
                  />
                </label>
              </div>
              <p className="text-xs text-ink-muted">Up to 50 templates. Names that already exist are skipped, never changed.</p>

              {counts && rows && (
                <div className="space-y-3">
                  <p className="text-sm font-semibold text-ink" aria-live="polite">{countsText(counts)}</p>
                  <div className="overflow-hidden rounded-xl border border-border-subtle">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-surface-subtle text-ink-muted">
                        <tr>
                          <th className="px-3 py-2 font-semibold">Row</th>
                          <th className="px-3 py-2 font-semibold">Template</th>
                          <th className="px-3 py-2 font-semibold">Check</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border-subtle">
                        {rows.map((r, i) => {
                          const pill = STATUS_PILL[r.status];
                          const result = results?.find((x) => x.row === r.row);
                          return (
                            <tr key={`${r.row}-${i}`} className="align-top">
                              <td className="px-3 py-2 text-ink-muted">{r.row}</td>
                              <td className="px-3 py-2">
                                <p className="break-all font-mono font-semibold text-ink">{r.name || "(no name)"}</p>
                                <p className="text-ink-muted">{r.language ? languageName(r.language) : ""}</p>
                              </td>
                              <td className="px-3 py-2">
                                <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${pill.cls}`}>{pill.text}</span>
                                {r.problems.length > 0 && (
                                  <ul className="mt-1 space-y-0.5 text-ink-secondary">
                                    {r.problems.map((p) => <li key={p}>{p}</li>)}
                                  </ul>
                                )}
                                {result && (
                                  <p className="mt-1">
                                    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${RESULT_PILL[result.status].cls}`}>
                                      {RESULT_PILL[result.status].text}
                                    </span>
                                    {result.reason && <span className="mt-1 block text-ink-secondary">{result.reason}</span>}
                                  </p>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  {!results && (
                    <button onClick={sendReady} disabled={busy || readyCount === 0} className="btn-primary text-sm disabled:opacity-50">
                      {busy ? "Sending…" : `Send ${readyCount} to Meta for approval`}
                    </button>
                  )}
                  {results && (
                    <p className="text-sm text-ink-secondary">
                      Done. Meta usually answers within minutes; approved templates show up as Approved after a sync.
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
