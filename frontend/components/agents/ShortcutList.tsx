"use client";
import { useCallback, useEffect, useState } from "react";
import { companionKbApi, type KbShortcut } from "@/lib/api";
import { BTN_ROW_DANGER, ErrorNote, LoadingRows } from "./ui";
import { sourceText } from "./knowledgeRows";
import { usedText } from "./collectionRows";
import { BTN_ROW, ConfirmDialog, EmptyNote, errorText, useListHeading } from "./collectionUi";

/**
 * The Learned shortcuts tab. Example: "How long does a refund take?",
 * goes straight to "Returns policy, p. 8", used 14 times, read by Maya.
 */
export function ShortcutList({ collectionId }: { collectionId: string }) {
  const [rows, setRows] = useState<KbShortcut[] | null>(null);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<KbShortcut | null>(null);
  const [status, setStatus] = useState("");
  const { heading, focusHeading } = useListHeading("Learned shortcuts");

  const load = useCallback(() => {
    setError("");
    companionKbApi
      .listShortcuts(collectionId)
      .then(setRows)
      .catch((e) => setError(errorText(e, "Could not load the shortcuts.")));
  }, [collectionId]);
  useEffect(load, [load]);

  if (error) {
    return (
      <div className="p-4">
        <ErrorNote message={error} onRetry={load} />
      </div>
    );
  }
  if (rows === null) {
    return (
      <div className="p-4">
        <LoadingRows />
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <>
        {heading}
        <EmptyNote
          action={
            <button type="button" className={BTN_ROW} onClick={() => { setRows(null); load(); }}>
              Refresh
            </button>
          }
        >
          No shortcuts yet. One appears when 3 similar questions are answered by the same page.
        </EmptyNote>
      </>
    );
  }

  return (
    <div>
      {heading}
      <p className="sr-only" role="status">
        {status}
      </p>
      <ul className="divide-y divide-border-subtle">
        {rows.map((s) => (
          <li key={s.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 space-y-1">
              <p className="break-words font-medium text-ink">{s.topic}</p>
              <p className="break-words text-sm text-ink-secondary">Goes straight to {sourceText(s)}</p>
              <p className="text-sm text-ink-secondary">
                {usedText(s.uses)} · {s.companion_name}
              </p>
            </div>
            <div className="sm:justify-end">
              <button type="button" className={BTN_ROW_DANGER} onClick={() => setDeleting(s)} aria-label={`Delete shortcut: ${s.topic}`}>
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>

      {deleting && (
        <ConfirmDialog
          title="Delete this shortcut?"
          confirmLabel="Delete shortcut"
          onClose={() => setDeleting(null)}
          onConfirm={async () => {
            await companionKbApi.deleteShortcut(deleting.id);
            setRows((prev) => (prev ? prev.filter((r) => r.id !== deleting.id) : prev));
            setStatus("Shortcut deleted.");
            setDeleting(null);
            focusHeading();
          }}
        >
          <p className="font-medium text-ink">{deleting.topic}</p>
          <p>
            Characters go back to searching all the files for this question. The topic will not be learned again, even if people keep
            asking it.
          </p>
          <p className="font-medium text-ink">This cannot be undone.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
