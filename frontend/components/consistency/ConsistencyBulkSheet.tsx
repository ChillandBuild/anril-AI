"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Loader2, X } from "lucide-react";
import { predictedSkip, sourceLabel, toggleId } from "./consistencyLogic";
import type { Access, BulkAction, Issue } from "./types";
import { CheckTick } from "@/components/ui/controls";

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), [href], textarea:not([disabled])';

interface BulkSheetProps {
  action: BulkAction;
  issues: readonly Issue[];
  access: Access;
  isBusy: boolean;
  onCancel: () => void;
  /** Called with the ids still ticked. */
  onConfirm: (ids: string[]) => void;
}

function BeforeAfter({ issue }: { issue: Issue }) {
  if (issue.proposed === null) {
    return <p className="font-body text-xs text-ink-muted">Anril has no suggested wording for this one.</p>;
  }
  return (
    <div className="space-y-1 font-body text-xs">
      <p className="break-words text-ink-muted">
        <span className="font-semibold text-ink">Before: </span>&ldquo;{issue.quote}&rdquo;
      </p>
      <p className="break-words text-ink-secondary">
        <span className="font-semibold text-ink">After: </span>
        {issue.proposed === "" ? "this line is removed" : `“${issue.proposed}”`}
      </p>
    </div>
  );
}

export function ConsistencyBulkSheet({ action, issues, access, isBusy, onCancel, onConfirm }: BulkSheetProps) {
  const [ticked, setTicked] = useState<Set<string>>(() => new Set(issues.map((i) => i.id)));
  const dialogRef = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);
  const isFix = action === "fix";
  const verb = isFix ? "Fix" : "Dismiss";
  const count = useMemo(() => issues.filter((i) => ticked.has(i.id)).length, [issues, ticked]);
  const emptyReasonId = "bulk-empty-reason";

  useEffect(() => {
    opener.current = document.activeElement;
    dialogRef.current?.focus();
    return () => {
      if (opener.current instanceof HTMLElement) opener.current.focus();
    };
  }, []);

  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Escape" && !isBusy) {
      e.stopPropagation();
      onCancel();
      return;
    }
    if (e.key !== "Tab") return;
    const nodes = dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
    if (!nodes || nodes.length === 0) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  return (
    <div
      className="fixed inset-0 z-dialog flex items-end justify-center bg-black/50 p-0 backdrop-blur-sm sm:items-center sm:p-4"
      onClick={isBusy ? undefined : onCancel}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="bulk-sheet-title"
        tabIndex={-1}
        onKeyDown={onKeyDown}
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-t-2xl border border-border bg-white shadow-2xl outline-none sm:rounded-2xl"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border-subtle px-4 py-3.5 sm:px-5">
          <div className="min-w-0">
            <h3 id="bulk-sheet-title" className="font-display text-base font-bold text-ink">
              {verb} {issues.length} {issues.length === 1 ? "conflict" : "conflicts"}?
            </h3>
            <p className="mt-0.5 font-body text-xs text-ink-secondary">
              {isFix
                ? "Every item is ticked. Untick anything you want to leave alone. Each fix uses Anril's suggested wording."
                : "Every item is ticked. Untick anything you want to keep listed. You can restore dismissed items later."}
            </p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            disabled={isBusy}
            aria-label="Close"
            className="shrink-0 rounded-lg p-1.5 text-ink-muted hover:bg-border-subtle hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-50"
          >
            <X size={18} />
          </button>
        </div>

        <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto px-4 py-3 sm:px-5">
          {issues.map((issue) => {
            const skipNote = predictedSkip(issue, action, access);
            return (
              <li key={issue.id} className="min-w-0 rounded-xl border border-border-subtle bg-surface-low/50 p-3">
                <div className="flex items-start gap-2.5">
                  <CheckTick
                    checked={ticked.has(issue.id)}
                    onChange={() => setTicked((prev) => toggleId(prev, issue.id))}
                    disabled={isBusy}
                    aria-label={`Select: ${sourceLabel(issue)}`}
                    size="sm"
                    className="mt-0.5 shrink-0"
                  />
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <p className="break-words font-label text-[11px] font-bold uppercase tracking-wider text-amber-700">
                      {sourceLabel(issue)}
                      <span className="ml-1.5 normal-case tracking-normal text-ink">{issue.topic}</span>
                    </p>
                    {isFix ? (
                      <BeforeAfter issue={issue} />
                    ) : (
                      <p className="break-words font-body text-xs italic text-ink-muted">&ldquo;{issue.quote}&rdquo;</p>
                    )}
                    {skipNote && <p className="font-body text-[11px] font-semibold text-amber-800">{skipNote}</p>}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border-subtle px-4 py-3 sm:px-5">
          {count === 0 && (
            <p id={emptyReasonId} className="mr-auto font-body text-xs text-ink-muted">
              Tick at least one item.
            </p>
          )}
          <button
            type="button"
            onClick={onCancel}
            disabled={isBusy}
            className="inline-flex min-h-10 items-center rounded-lg border border-border px-3.5 font-label text-xs font-semibold text-ink-secondary hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onConfirm(issues.filter((i) => ticked.has(i.id)).map((i) => i.id))}
            disabled={isBusy || count === 0}
            aria-describedby={count === 0 ? emptyReasonId : undefined}
            className="inline-flex min-h-10 items-center gap-1.5 rounded-lg bg-primary px-4 font-label text-xs font-semibold text-white hover:bg-primary-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-50"
          >
            {isBusy ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
            {verb} {count}
          </button>
        </div>
      </div>
    </div>
  );
}
