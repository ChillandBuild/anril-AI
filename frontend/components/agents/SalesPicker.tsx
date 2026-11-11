"use client";
import { useCallback, useEffect, useState } from "react";
import { companionKbApi, type KbSalesDocument } from "@/lib/api";
import { KbDialog } from "@/components/agents/KbDialog";
import { BTN_PRIMARY, BTN_SECONDARY, ErrorNote, LoadingRows, formatDate } from "@/components/agents/ui";
import { toggleId } from "@/components/agents/uploadQueue";

/**
 * "Add from Anril Sales": tick files already uploaded to Anril Sales and copy them into the
 * chosen collection. The Sales copy is not changed. Example: tick "Porutham guide.pdf",
 * press Add, and it appears under Processing in "Astrology books".
 */
export function SalesPicker({
  open,
  onClose,
  collectionId,
  collectionName,
  tier,
  onAdded,
}: {
  open: boolean;
  onClose: () => void;
  collectionId: string;
  collectionName: string;
  tier: 1 | 2;
  /** Called after at least one file was added, so the page can refresh its lists. */
  onAdded: () => void;
}) {
  const [docs, setDocs] = useState<KbSalesDocument[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [adding, setAdding] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);

  const load = useCallback(() => {
    setLoadError("");
    setDocs(null);
    companionKbApi
      .listSalesDocuments()
      .then(setDocs)
      .catch((e: Error) => setLoadError(e.message || "Could not load your Anril Sales files."));
  }, []);

  useEffect(() => {
    if (!open) return;
    setPicked([]);
    setProblems([]);
    load();
  }, [open, load]);

  const add = async () => {
    if (adding || picked.length === 0 || !docs) return;
    setAdding(true);
    setProblems([]);
    const failed: string[] = [];
    const added: string[] = [];
    for (const id of picked) {
      const doc = docs.find((d) => d.id === id);
      try {
        await companionKbApi.addFromSales({ sales_document_id: id, collection_id: collectionId, tier });
        added.push(id);
      } catch (e) {
        failed.push(`${doc?.name ?? "A file"}: ${(e as Error).message || "could not be added."}`);
      }
    }
    setAdding(false);
    if (added.length) onAdded();
    if (failed.length === 0) {
      onClose();
      return;
    }
    // Keep the dialog open so the failed ones can be tried again; the added ones leave the list.
    setPicked((p) => p.filter((id) => !added.includes(id)));
    setDocs((d) => (d ? d.filter((x) => !added.includes(x.id)) : d));
    setProblems(failed);
  };

  const footer = (
    <>
      <button type="button" onClick={onClose} disabled={adding} className={BTN_SECONDARY}>
        Cancel
      </button>
      <button type="button" onClick={add} disabled={adding || picked.length === 0} className={BTN_PRIMARY}>
        {adding ? "Adding…" : picked.length > 1 ? `Add ${picked.length} files` : "Add"}
      </button>
    </>
  );

  return (
    <KbDialog open={open} title="Add from Anril Sales" onClose={adding ? () => undefined : onClose} footer={footer}>
      <p className="mb-3 text-ink-secondary">
        Copies a file you already uploaded to Anril Sales into &ldquo;{collectionName}&rdquo; as {tier === 1 ? "the main resource" : "a book"}. The Sales
        copy is not changed.
      </p>

      {loadError ? (
        <ErrorNote message={loadError} onRetry={load} />
      ) : docs === null ? (
        <LoadingRows rows={3} />
      ) : docs.length === 0 ? (
        <p className="rounded-xl bg-surface-mid px-3 py-3 text-ink-secondary">
          No Anril Sales files can be copied yet. Upload one in Anril Sales Knowledge, or close this and drop a file on the Upload page.
        </p>
      ) : (
        <fieldset disabled={adding}>
          <legend className="sr-only">Anril Sales files</legend>
          <ul className="space-y-1">
            {docs.map((d) => {
              const unreadable = d.file_type === "";   // an old file type the books reader cannot open
              return (
              <li key={d.id}>
                <label className={`flex min-h-10 items-center gap-3 rounded-lg px-2 py-1.5 ${unreadable ? "opacity-60" : "cursor-pointer hover:bg-surface-mid"}`}>
                  <input
                    type="checkbox"
                    disabled={unreadable}
                    aria-disabled={unreadable}
                    checked={picked.includes(d.id)}
                    onChange={() => setPicked((p) => toggleId(p, d.id))}
                    className="h-4 w-4 shrink-0 accent-primary"
                    data-autofocus={d === docs[0] ? "" : undefined}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-ink">{d.name}</span>
                    <span className="block text-xs text-ink-secondary">
                      {unreadable ? "This file type can't be read" : d.file_type.toUpperCase()}, added {formatDate(d.created_at)}
                    </span>
                  </span>
                </label>
              </li>
              );
            })}
          </ul>
        </fieldset>
      )}

      {problems.length > 0 && (
        <ul role="alert" className="mt-3 space-y-1 text-sm text-danger">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
    </KbDialog>
  );
}
