"use client";

import { useState } from "react";
import { Check, Loader2, Pencil, X } from "lucide-react";
import { fixBlockedReason, manageBlockedReason, sourceLabel } from "./consistencyLogic";
import type { Access, Issue } from "./types";
import { CheckTick } from "@/components/ui/controls";

const BUTTON_FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40";

interface IssueCardProps {
  issue: Issue;
  access: Access;
  /** null hides the checkbox (a lone conflict has nothing to select). */
  selected: boolean | null;
  /** Disables every action while a bulk request is running. */
  isLocked: boolean;
  onToggleSelected: (id: string) => void;
  onFix: (id: string, text?: string) => Promise<void>;
  onDismiss: (id: string) => Promise<void>;
}

export function ConsistencyIssueCard({ issue, access, selected, isLocked, onToggleSelected, onFix, onDismiss }: IssueCardProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(issue.proposed ?? issue.quote);
  const [busy, setBusy] = useState<"fix" | "dismiss" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fixReason = fixBlockedReason(issue, access);
  const dismissReason = manageBlockedReason(access);
  const reasonText = fixReason ?? dismissReason;
  const reasonId = `conflict-reason-${issue.id}`;
  const isIdle = busy === null && !isLocked;

  async function run(action: "fix" | "dismiss", fn: () => Promise<void>) {
    setBusy(action);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="min-w-0 space-y-2.5 rounded-2xl border border-amber-200 bg-white p-4">
      <div className="flex items-start gap-2.5">
        {selected !== null && (
          <label className="-m-2 flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center">
            <CheckTick
              checked={selected}
              onChange={() => onToggleSelected(issue.id)}
              disabled={isLocked}
              aria-label={`Select: ${issue.topic}`}
              size="sm"
            />
          </label>
        )}
        <span className="min-w-0 flex-1 break-words font-label text-[10px] font-bold uppercase tracking-wider text-amber-700">
          {sourceLabel(issue)}
        </span>
      </div>

      <p className="break-words font-label text-sm font-semibold text-ink">{issue.topic}</p>

      <p className="break-words font-body text-xs italic text-ink-muted">&ldquo;{issue.quote}&rdquo;</p>

      {issue.proposed !== null ? (
        <p className="break-words font-body text-xs text-ink-secondary">
          <span className="font-semibold text-ink">Suggested: </span>
          {issue.proposed === "" ? "remove this line" : issue.proposed}
        </p>
      ) : issue.editable ? (
        <p className="font-body text-xs text-ink-muted">
          Anril hasn&rsquo;t written a fix for this one yet. It tries again each time you open this
          page, or press Check again. You can also edit it yourself.
        </p>
      ) : null}

      {editing && (
        <div className="space-y-2 pt-1">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={2}
            className="w-full rounded-lg border border-border bg-white px-3 py-2 font-body text-sm text-ink outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            aria-label={`Edit wording for ${issue.topic}`}
          />
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!isIdle || fixReason !== null}
              aria-describedby={fixReason ? reasonId : undefined}
              onClick={() => run("fix", () => onFix(issue.id, draft))}
              className={`inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-primary hover:bg-primary-dark px-3 py-1.5 font-label text-xs font-semibold text-white disabled:opacity-50 ${BUTTON_FOCUS}`}
            >
              {busy === "fix" ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
              Apply
            </button>
            <button
              type="button"
              disabled={!isIdle}
              onClick={() => setEditing(false)}
              className={`inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 font-label text-xs font-semibold text-ink-secondary disabled:opacity-50 ${BUTTON_FOCUS}`}
            >
              <X size={12} /> Cancel
            </button>
          </div>
        </div>
      )}

      {!editing && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          {issue.editable && issue.proposed !== null && (
            <button
              type="button"
              disabled={!isIdle || fixReason !== null}
              aria-describedby={fixReason ? reasonId : undefined}
              onClick={() => run("fix", () => onFix(issue.id, undefined))}
              className={`inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 font-label text-xs font-semibold text-white transition hover:bg-primary-dark disabled:opacity-50 ${BUTTON_FOCUS}`}
            >
              {busy === "fix" ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
              Use suggestion
            </button>
          )}
          {issue.editable && (
            <button
              type="button"
              disabled={!isIdle || fixReason !== null}
              aria-describedby={fixReason ? reasonId : undefined}
              onClick={() => { setDraft(issue.proposed ?? issue.quote); setEditing(true); }}
              className={`inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 font-label text-xs font-semibold text-ink-secondary transition hover:border-primary/40 hover:text-ink disabled:opacity-50 ${BUTTON_FOCUS}`}
            >
              <Pencil size={12} /> Edit & apply
            </button>
          )}
          <button
            type="button"
            disabled={!isIdle || dismissReason !== null}
            aria-describedby={dismissReason ? reasonId : undefined}
            onClick={() => run("dismiss", () => onDismiss(issue.id))}
            className={`inline-flex min-h-9 items-center gap-1.5 rounded-lg px-3 py-1.5 font-label text-xs font-semibold text-ink-muted transition hover:text-ink disabled:opacity-50 ${BUTTON_FOCUS}`}
          >
            {busy === "dismiss" ? <Loader2 size={12} className="animate-spin" /> : <X size={12} />}
            Keep as is
          </button>
        </div>
      )}

      {reasonText && (
        <p id={reasonId} className="font-body text-[11px] text-ink-muted">
          {reasonText}
        </p>
      )}

      {!issue.editable && (
        <p className="font-body text-[11px] text-ink-muted">
          This file was uploaded before auto-sort. Re-sort it on the Knowledge page to fix it here.
        </p>
      )}

      {error && <p className="break-words font-body text-xs text-red-600">{error}</p>}
    </div>
  );
}
