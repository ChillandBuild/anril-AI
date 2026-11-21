"use client";
import { useEffect, useRef, useState } from "react";
import { Loader2, X } from "lucide-react";
import { MAX_GROUP_PEOPLE } from "./saveAsGroup";

/**
 * Chats > Filter > Save as a group: asks for a name, then the page saves everyone the current tab,
 * search and filters match as a fixed group in Customers > Groups.
 * `matchCount` is the number of chats the list matches right now (null while it is unknown).
 */
export function SaveGroupDialog({
  open,
  matchCount,
  onClose,
  onSave,
}: {
  open: boolean;
  matchCount: number | null;
  onClose: () => void;
  /** Resolves when saved; rejects with a plain-words message to show under the name. */
  onSave: (name: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setName("");
    setError(null);
    setBusy(false);
    inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busy) onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  const tooMany = matchCount !== null && matchCount > MAX_GROUP_PEOPLE;
  const none = matchCount === 0;
  const trimmed = name.trim();
  const canSave = Boolean(trimmed) && !tooMany && !none && !busy;

  async function submit() {
    if (!canSave) return;
    setBusy(true);
    setError(null);
    try {
      await onSave(trimmed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save the group. Try again.");
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
      <div role="dialog" aria-modal="true" aria-labelledby="save-group-title" className="w-full max-w-md rounded-card bg-white p-6 shadow-xl">
        <div className="mb-3 flex items-start justify-between gap-3">
          <h3 id="save-group-title" className="font-display text-lg font-bold text-ink">Save as a group</h3>
          <button type="button" onClick={onClose} disabled={busy} aria-label="Close" className="text-ink-muted hover:text-ink disabled:opacity-45">
            <X size={18} />
          </button>
        </div>

        <p className="mb-4 text-[13px] leading-relaxed text-ink-secondary">
          {tooMany ? (
            <>
              <span className="font-bold text-red-600">{matchCount.toLocaleString("en-IN")} chats match.</span>{" "}
              A group holds up to {MAX_GROUP_PEOPLE.toLocaleString("en-IN")} people. Close this, narrow the filters, and try again.
            </>
          ) : none ? (
            "No chats match right now, so there is nobody to save."
          ) : (
            <>
              Saves{" "}
              <span className="font-bold text-ink">{matchCount === null ? "everyone" : `all ${matchCount.toLocaleString("en-IN")} people`}</span>{" "}
              in the chats you are looking at (this tab, your search and filters), not just the ones on screen. The group is fixed:
              chats that come in later don&apos;t join it. Find it in Customers &rsaquo; Groups.
            </>
          )}
        </p>

        <label htmlFor="save-group-name" className="mb-1 block text-[13px] font-bold text-ink">Group name</label>
        <input
          id="save-group-name"
          ref={inputRef}
          value={name}
          maxLength={80}
          onChange={(e) => { setName(e.target.value); setError(null); }}
          onKeyDown={(e) => { if (e.key === "Enter") void submit(); }}
          placeholder="Example: Insta Hot – Nov"
          disabled={busy}
          className="h-10 w-full rounded-xl border border-[#e2e8f0] px-3 text-[14px] text-ink placeholder:text-slate-400 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-60"
        />
        {error && <p role="alert" className="mt-2 text-[13px] font-semibold text-red-600">{error}</p>}

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} disabled={busy} className="h-10 rounded-xl px-4 text-[13px] font-semibold text-ink-secondary hover:bg-slate-100 disabled:opacity-45">
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={!canSave}
            className="inline-flex h-10 items-center gap-2 rounded-xl bg-primary px-5 text-[13px] font-bold text-white shadow-sm hover:bg-[var(--primary-900)] disabled:cursor-not-allowed disabled:opacity-45"
          >
            {busy && <Loader2 size={14} className="animate-spin" />}
            {busy ? "Saving…" : "Save group"}
          </button>
        </div>
      </div>
    </div>
  );
}
