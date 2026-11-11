"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { companionKbApi, type KbDocument } from "@/lib/api";
import { BTN_PRIMARY, BTN_ROW_DANGER, ErrorNote, LoadingRows } from "./ui";
import { anyReading, docState, docStateLabel, fileSizeText, pagesText } from "./knowledgeRows";
import { bookHref, importHref, needsRetry, problemText, sortBooks, tierToggle } from "./collectionRows";
import {
  BTN_ROW,
  ConfirmDialog,
  EmptyNote,
  MainResourceBadge,
  StatePill,
  errorText,
  useListHeading,
  usePolling,
} from "./collectionUi";

const BOOK_LIMIT = 200;

/**
 * The Files tab of one collection. Example: "Returns policy", 319 of 320 pages, "Could not read page 200",
 * Retry / Make main resource / Delete. Refreshes every 3 seconds while any file is being read.
 */
export function BookList({ collectionId }: { collectionId: string }) {
  const [docs, setDocs] = useState<KbDocument[] | null>(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState<KbDocument | null>(null);
  const [status, setStatus] = useState("");
  const seq = useRef(0);
  const { heading, focusHeading } = useListHeading("Files");

  // Only the newest answer is kept, so a slow older request cannot overwrite a newer list.
  const fetchDocs = useCallback(async () => {
    const mine = ++seq.current;
    const list = await companionKbApi.listDocuments({ collectionId, limit: BOOK_LIMIT });
    if (mine === seq.current) setDocs(list);
  }, [collectionId]);

  const load = useCallback(() => {
    setError("");
    fetchDocs().catch((e) => setError(errorText(e, "Could not load the files.")));
  }, [fetchDocs]);
  useEffect(load, [load]);

  usePolling(fetchDocs, docs !== null && anyReading(docs));

  const markBusy = (id: string, on: boolean) =>
    setBusyIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const run = async (doc: KbDocument, action: () => Promise<unknown>, done: string) => {
    markBusy(doc.id, true);
    setActionError("");
    setStatus("");
    try {
      try {
        await action();
      } catch (e) {
        setActionError(errorText(e, "That did not work. Please try again."));
        return;
      }
      // The action worked. If only the refresh fails, keep the old list; the next poll or a reload fixes it.
      await fetchDocs().catch(() => undefined);
      setStatus(done);
    } finally {
      markBusy(doc.id, false);
    }
  };

  if (error) {
    return (
      <div className="p-4">
        <ErrorNote message={error} onRetry={load} />
      </div>
    );
  }
  if (docs === null) {
    return (
      <div className="p-4">
        <LoadingRows />
      </div>
    );
  }
  if (docs.length === 0) {
    return (
      <>
        {heading}
        <EmptyNote
          action={
            <Link href={importHref(collectionId)} className={BTN_PRIMARY}>
              Import a file
            </Link>
          }
        >
          No files in this collection yet. Press Import to add one.
        </EmptyNote>
      </>
    );
  }

  return (
    <div>
      {heading}
      {actionError && (
        <div className="p-4 pb-0">
          <ErrorNote message={actionError} />
        </div>
      )}
      <p className="sr-only" role="status">
        {status}
      </p>
      <ul className="divide-y divide-border-subtle">
        {sortBooks(docs).map((doc) => {
          const state = docState(doc);
          const problem = problemText(doc);
          const toggle = tierToggle(doc.tier);
          const busy = busyIds.has(doc.id);
          return (
            <li key={doc.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Link href={bookHref(collectionId, doc.id)} className="break-words font-medium text-ink hover:text-primary hover:underline">
                    {doc.title}
                  </Link>
                  {doc.tier === 1 && <MainResourceBadge />}
                  <StatePill state={state} label={docStateLabel(state)} />
                </div>
                <p className="text-sm text-ink-secondary">
                  {pagesText(doc)} · {fileSizeText(doc.size_bytes)}
                </p>
                {problem && <p className="break-words text-sm text-danger">{problem}</p>}
              </div>
              <div className="flex flex-wrap gap-2 sm:justify-end">
                {needsRetry(doc) && (
                  <button
                    type="button"
                    className={BTN_ROW}
                    disabled={busy}
                    onClick={() => run(doc, () => companionKbApi.retryDocument(doc.id), `Retrying ${doc.title}.`)}
                    aria-label={`Retry ${doc.title}`}
                  >
                    Retry
                  </button>
                )}
                <button
                  type="button"
                  className={BTN_ROW}
                  disabled={busy}
                  onClick={() =>
                    run(doc, () => companionKbApi.updateDocument(doc.id, { tier: toggle.next }), `${doc.title} updated.`)
                  }
                  aria-label={`${toggle.label}: ${doc.title}`}
                >
                  {toggle.label}
                </button>
                <button
                  type="button"
                  className={BTN_ROW_DANGER}
                  disabled={busy}
                  onClick={() => setDeleting(doc)}
                  aria-label={`Delete ${doc.title}`}
                >
                  Delete
                </button>
              </div>
            </li>
          );
        })}
      </ul>
      {docs.length >= BOOK_LIMIT && <p className="px-5 py-3 text-sm text-ink-secondary">Showing the newest {BOOK_LIMIT} files.</p>}

      {deleting && (
        <ConfirmDialog
          title={`Delete "${deleting.title}"?`}
          confirmLabel="Delete file"
          onClose={() => setDeleting(null)}
          onConfirm={async () => {
            await companionKbApi.deleteDocument(deleting.id);
            setDeleting(null);
            setStatus(`${deleting.title} deleted.`);
            await fetchDocs().catch(() => undefined);
            focusHeading();
          }}
        >
          <p>
            {deleting.page_count > 0
              ? `${deleting.title} and its ${deleting.page_count} ${deleting.page_count === 1 ? "page" : "pages"} are removed`
              : `${deleting.title} is removed`}
            , along with the passages made from them. Characters stop answering from it.
          </p>
          <p className="font-medium text-ink">This cannot be undone.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
