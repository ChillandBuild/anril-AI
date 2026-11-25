"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, History, Loader2, RotateCcw, X } from "lucide-react";
import { api, type KnowledgeVersion, type KnowledgeVersionReason } from "@/lib/api";
import { cn } from "@/lib/utils";
import { lineDiff } from "./descriptionDiff";

interface Props {
  kind: "description" | "facts";
  documentId?: string;
  /** e.g. "Description" or the file name. */
  title: string;
  canRestore: boolean;
  onClose: () => void;
  onRestored: () => void;
}

type ApiError = Error & { status?: number };

const REASON_LABEL: Record<KnowledgeVersionReason, string> = {
  baseline: "Before history started",
  edit: "Edited by hand",
  upload: "From an uploaded file",
  delete_document: "A file was deleted",
  resort: "From re-sorting a file",
  restore: "Restored an older version",
};

function formatWhen(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function KnowledgeHistoryModal({ kind, documentId, title, canRestore, onClose, onRestored }: Props) {
  const [versions, setVersions] = useState<KnowledgeVersion[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<"changes" | "full">("changes");
  const [restoring, setRestoring] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.knowledge
      .listVersions(kind, documentId)
      .then((rows) => {
        if (cancelled) return;
        setVersions(rows);
        setSelectedId(rows[1]?.id ?? rows[0]?.id ?? null);
      })
      .catch((e: ApiError) => !cancelled && setLoadError(e.message || "Could not load the history."));
    return () => {
      cancelled = true;
    };
  }, [kind, documentId]);

  const current = versions?.[0] ?? null;
  const selected = versions?.find((v) => v.id === selectedId) ?? null;
  const isCurrent = selected !== null && selected.id === current?.id;
  // "Changes vs now": what restoring would do to the current text.
  const rows = useMemo(
    () => (selected && current ? lineDiff(current.content, selected.content) : []),
    [selected, current],
  );

  async function restore() {
    if (!selected) return;
    setRestoring(true);
    try {
      await api.knowledge.restoreVersion(selected.id);
      toast.success(kind === "description" ? "Description restored. You can undo this from History too." : "Restored what Anril looks up from this file.");
      onRestored();
    } catch (e) {
      toast.error((e as ApiError).message || "Could not restore this version.");
    } finally {
      setRestoring(false);
    }
  }

  return (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-black/50 p-2 backdrop-blur-sm sm:p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Version history"
        className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-surface-mid bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-surface-mid bg-surface-low/50 px-5 py-4 sm:px-6">
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 font-label text-[11px] font-bold uppercase tracking-wider text-primary">
              <History size={12} /> History
            </p>
            <h3 className="mt-0.5 truncate font-display text-lg font-bold text-on-surface">{title}</h3>
            <p className="mt-0.5 font-body text-xs text-on-surface-muted">
              Every change is kept. Restoring saves the old text as a new version, so it can be undone too.
            </p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-on-surface-muted transition-colors hover:bg-surface-mid hover:text-on-surface" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        {!versions && !loadError && (
          <div className="flex items-center justify-center gap-2 py-20 font-body text-sm text-on-surface-muted">
            <Loader2 size={18} className="animate-spin text-primary" /> Loading history…
          </div>
        )}
        {loadError && (
          <div className="m-5 flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-3 font-body text-xs text-red-800">
            <AlertTriangle size={14} /> {loadError}
          </div>
        )}

        {versions && versions.length === 0 && (
          <p className="py-16 text-center font-body text-sm text-on-surface-muted">No history yet.</p>
        )}

        {versions && versions.length > 0 && (
          <div className="flex min-h-0 flex-1 flex-col md:flex-row">
            {/* Version list */}
            <ol className="max-h-48 shrink-0 overflow-y-auto border-b border-surface-mid md:max-h-none md:w-64 md:border-b-0 md:border-r">
              {versions.map((v, i) => (
                <li key={v.id}>
                  <button
                    onClick={() => setSelectedId(v.id)}
                    className={cn(
                      "w-full border-l-2 px-4 py-2.5 text-left transition-colors",
                      v.id === selectedId ? "border-primary bg-primary/5" : "border-transparent hover:bg-surface-low",
                    )}
                  >
                    <span className="flex items-center gap-1.5 font-label text-xs font-semibold text-on-surface">
                      {REASON_LABEL[v.reason] ?? v.reason}
                      {i === 0 && (
                        <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-[9px] font-bold uppercase text-emerald-700">
                          Now
                        </span>
                      )}
                    </span>
                    <span className="font-body text-[11px] text-on-surface-muted">{formatWhen(v.created_at)}</span>
                  </button>
                </li>
              ))}
            </ol>

            {/* Selected version */}
            <div className="flex min-h-0 flex-1 flex-col">
              {selected && (
                <>
                  <div className="flex items-center justify-between gap-2 border-b border-surface-mid/70 px-4 py-2.5">
                    <div className="flex gap-1 rounded-xl bg-surface-low p-1">
                      {(["changes", "full"] as const).map((v) => (
                        <button
                          key={v}
                          onClick={() => setView(v)}
                          disabled={isCurrent && v === "changes"}
                          className={cn(
                            "rounded-lg px-2.5 py-1 font-label text-[11px] font-bold transition-all disabled:opacity-40",
                            view === v && !(isCurrent && v === "changes") ? "bg-white text-primary shadow-sm" : "text-on-surface-muted",
                          )}
                        >
                          {v === "changes" ? "Changes vs now" : "Full text"}
                        </button>
                      ))}
                    </div>
                    {canRestore && !isCurrent && (
                      <button
                        onClick={restore}
                        disabled={restoring}
                        className="flex items-center gap-1.5 rounded-xl bg-primary px-3.5 py-1.5 font-label text-xs font-semibold text-white shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-50"
                      >
                        {restoring ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />} Restore this version
                      </button>
                    )}
                  </div>

                  <div className="flex-1 overflow-y-auto bg-surface-low/30 p-4">
                    {isCurrent || view === "full" ? (
                      <pre className="whitespace-pre-wrap break-words rounded-xl border border-surface-mid/80 bg-white p-3.5 font-mono text-[11.5px] leading-relaxed text-on-surface">
                        {selected.content || "(empty)"}
                      </pre>
                    ) : rows.every((r) => r.type === "same") ? (
                      <p className="py-10 text-center font-body text-xs text-on-surface-muted">Same as now.</p>
                    ) : (
                      <div className="space-y-0.5 rounded-xl border border-surface-mid/80 bg-white p-2.5">
                        {rows.map((r, i) => (
                          <div
                            key={i}
                            className={cn(
                              "flex gap-2 rounded-md px-2 py-0.5 font-mono text-[11.5px] leading-relaxed",
                              r.type === "add" && "bg-emerald-50 text-emerald-900",
                              r.type === "remove" && "bg-red-50 text-red-800 line-through decoration-red-300",
                              r.type === "same" && "text-on-surface-muted",
                            )}
                          >
                            <span className="w-3 shrink-0 select-none font-bold opacity-60">
                              {r.type === "add" ? "+" : r.type === "remove" ? "−" : ""}
                            </span>
                            <span className="min-w-0 whitespace-pre-wrap break-words">{r.text || " "}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  {!isCurrent && view === "changes" && (
                    <p className="border-t border-surface-mid/70 px-4 py-2 font-body text-[11px] text-on-surface-muted">
                      <span className="font-semibold text-emerald-700">Green</span> comes back and{" "}
                      <span className="font-semibold text-red-700">red</span> goes away if you restore this version.
                    </p>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
