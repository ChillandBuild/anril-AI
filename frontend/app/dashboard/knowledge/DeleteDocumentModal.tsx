"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, Loader2, Trash2 } from "lucide-react";
import { api, type KnowledgeDeletePreview } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  doc: { id: string; name: string };
  isOwner: boolean;
  onClose: () => void;
  onDeleted: (descriptionChanged: boolean) => void;
}

type ApiError = Error & { status?: number };

export default function DeleteDocumentModal({ doc, isOwner, onClose, onDeleted }: Props) {
  const [preview, setPreview] = useState<KnowledgeDeletePreview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Edited lines the client chose to remove. Keep is the default (spec §6.3).
  const [removeEdited, setRemoveEdited] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(() => {
    setPreview(null);
    setLoadError(null);
    setRemoveEdited(new Set());
    api.knowledge
      .deletePreview(doc.id)
      .then(setPreview)
      .catch((e: ApiError) => setLoadError(e.message || "Could not check what this file affects."));
  }, [doc.id]);

  useEffect(() => {
    load();
  }, [load]);

  const changesDescription = preview !== null && (preview.remove_lines.length > 0 || removeEdited.size > 0);
  const ownerBlocked = changesDescription && !isOwner;

  function toggleEdited(line: string) {
    setRemoveEdited((prev) => {
      const next = new Set(prev);
      if (next.has(line)) next.delete(line);
      else next.add(line);
      return next;
    });
  }

  async function confirm() {
    if (!preview || ownerBlocked) return;
    setDeleting(true);
    try {
      const res = await api.knowledge.deleteDocument(doc.id, {
        base_version_id: preview.base_version_id,
        remove_edited: Array.from(removeEdited),
      });
      toast.success(
        res.description_changed
          ? `"${doc.name}" deleted, and its lines were taken out of your Description.`
          : `"${doc.name}" deleted.`,
      );
      onDeleted(res.description_changed);
    } catch (e) {
      const err = e as ApiError;
      toast.error(err.message || "Could not delete this file.");
      if (err.status === 409) load();
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Delete knowledge document"
        className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-surface-mid bg-surface shadow-2xl animate-in fade-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="space-y-4 overflow-y-auto p-6">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-red-50 text-red-600">
            <Trash2 size={24} />
          </div>
          <div>
            <h3 className="font-display text-lg font-bold text-on-surface">Delete this file?</h3>
            <p className="mt-1 break-words font-body text-xs leading-relaxed text-on-surface-muted">
              <strong className="font-semibold text-on-surface">{doc.name}</strong>
            </p>
          </div>

          {!preview && !loadError && (
            <div className="flex items-center gap-2 py-4 font-body text-xs text-on-surface-muted">
              <Loader2 size={14} className="animate-spin text-primary" /> Checking what this file affects…
            </div>
          )}
          {loadError && (
            <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-3 font-body text-xs text-red-800">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {loadError}
            </div>
          )}

          {preview && (
            <div className="space-y-3">
              <div className="rounded-xl border border-surface-mid bg-surface-low/60 p-3 font-body text-xs text-on-surface">
                {preview.has_facts
                  ? "Anril will stop looking up the facts from this file."
                  : "This file has nothing Anril looks up."}
              </div>

              {preview.remove_lines.length > 0 && (
                <div>
                  <p className="mb-1.5 font-label text-xs font-bold text-on-surface">
                    These lines leave your Description
                  </p>
                  <div className="space-y-0.5 rounded-xl border border-surface-mid bg-white p-2">
                    {preview.remove_lines.map((line, i) => (
                      <p key={i} className="rounded-md bg-red-50 px-2 py-0.5 font-mono text-[11px] text-red-800 line-through decoration-red-300">
                        {line}
                      </p>
                    ))}
                  </div>
                </div>
              )}

              {preview.edited_lines.length > 0 && (
                <div>
                  <p className="font-label text-xs font-bold text-on-surface">You changed these lines after this file added them</p>
                  <p className="mb-1.5 font-body text-[11px] text-on-surface-muted">They stay unless you choose Remove.</p>
                  <div className="space-y-1.5">
                    {preview.edited_lines.map((e) => {
                      const remove = removeEdited.has(e.current);
                      return (
                        <div key={e.current} className="flex items-center gap-2 rounded-xl border border-surface-mid bg-white p-2">
                          <p className="min-w-0 flex-1 break-words font-mono text-[11px] text-on-surface">{e.current}</p>
                          <div className="flex shrink-0 gap-0.5 rounded-lg bg-surface-low p-0.5">
                            {(["Keep", "Remove"] as const).map((label) => {
                              const active = (label === "Remove") === remove;
                              return (
                                <button
                                  key={label}
                                  onClick={() => (active ? undefined : toggleEdited(e.current))}
                                  className={cn(
                                    "rounded-md px-2 py-0.5 font-label text-[10px] font-bold transition-all",
                                    active
                                      ? label === "Remove"
                                        ? "bg-red-600 text-white"
                                        : "bg-white text-primary shadow-sm"
                                      : "text-on-surface-muted",
                                  )}
                                >
                                  {label}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="rounded-xl border border-amber-100 bg-amber-50 p-3 font-body text-xs leading-relaxed text-amber-900">
                Deleting a file can&apos;t be undone. Lines removed from your Description can be brought back from
                Description → History.
              </div>
              {ownerBlocked && (
                <p className="flex items-start gap-1.5 font-body text-xs text-amber-800">
                  <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                  This would change the Description, and only an account owner can do that.
                </p>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-surface-mid/60 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            disabled={deleting}
            className="rounded-xl border border-surface-mid bg-surface px-4 py-2 font-label text-xs font-semibold text-on-surface transition-colors hover:bg-surface-low"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={confirm}
            disabled={deleting || !preview || ownerBlocked}
            className="flex items-center gap-1.5 rounded-xl bg-red-600 px-4 py-2 font-label text-xs font-semibold text-white shadow-sm transition-colors hover:bg-red-700 disabled:opacity-50"
          >
            {deleting && <Loader2 size={13} className="animate-spin" />}
            {deleting ? "Deleting…" : "Delete file"}
          </button>
        </div>
      </div>
    </div>
  );
}
