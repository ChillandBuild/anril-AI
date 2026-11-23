"use client";

import { useState } from "react";
import { AlertTriangle, Loader2, X } from "lucide-react";
import { timeAgo } from "@/lib/utils";
import {
  BatchError,
  StaleReportError,
  dismissBatch,
  dismissIssue,
  fixBatch,
  fixIssue,
  restoreIssues,
} from "./consistency/consistencyApi";
import {
  bulkBlockedReason,
  bulkLabel,
  bulkTargets,
  manageBlockedReason,
  summarizeDismiss,
  summarizeFix,
  summarizeRestore,
  toggleId,
} from "./consistency/consistencyLogic";
import { ConsistencyBulkSheet } from "./consistency/ConsistencyBulkSheet";
import { ConsistencyDismissedList } from "./consistency/ConsistencyDismissedList";
import { ConsistencyIssueCard } from "./consistency/ConsistencyIssueCard";
import { useConsistencyReport } from "./consistency/useConsistencyReport";
import type { Access, BulkAction, DismissBatchResult, FixBatchResult } from "./consistency/types";

const MIN_ISSUES_FOR_BULK = 2;
const NO_CHECK_YET = "Run a check first";

interface ConsistencyPanelProps {
  /** knowledge.manage (or owner). Without it nothing is written and /consistency/check is never called. */
  canManage: boolean;
  /** Description fixes are owner-only on the server; this only explains the disabled button. */
  isOwner: boolean;
  /** Called after anything changed (fix, dismiss, restore). The hub announces it and reloads. */
  onChanged?: () => void;
  /** No outer card: the host already draws one. */
  embedded?: boolean;
  /** The host bumps this to make the panel re-read the report. */
  reloadSignal?: number;
}

interface Notice {
  tone: "ok" | "warn";
  text: string;
}

const RELOAD_TEXT = "Issues changed since Anril checked. Reload to see the current list.";

function partialSummary(partial: FixBatchResult | DismissBatchResult | null): string | null {
  if (!partial) return null;
  if ("applied" in partial) return partial.applied.length + partial.skipped.length + partial.failed.length > 0 ? summarizeFix(partial) : null;
  return partial.dismissed.length + partial.skipped.length > 0 ? summarizeDismiss(partial) : null;
}

function CheckButton({ isChecking, blockedReason, onCheck }: { isChecking: boolean; blockedReason: string | null; onCheck: () => void }) {
  return (
    <span className="inline-flex flex-col items-end">
      <button
        type="button"
        disabled={isChecking || blockedReason !== null}
        aria-describedby={blockedReason ? "conflicts-check-reason" : undefined}
        onClick={onCheck}
        className="inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-lg px-1 font-label text-xs font-semibold text-primary hover:text-primary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-50"
      >
        {isChecking && <Loader2 size={12} className="animate-spin" />}
        {isChecking ? "Checking…" : "Check again"}
      </button>
      {blockedReason && (
        <span id="conflicts-check-reason" className="font-body text-[11px] text-ink-muted">
          {blockedReason}
        </span>
      )}
    </span>
  );
}

export function ConsistencyPanel({ canManage, isOwner, onChanged, embedded = false, reloadSignal = 0 }: ConsistencyPanelProps) {
  const access: Access = { canManage, isOwner };
  const { report, isLoading, isChecking, error, load, runCheck } = useConsistencyReport({ canManage, reloadSignal });
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [sheet, setSheet] = useState<BulkAction | null>(null);
  const [isBulkBusy, setIsBulkBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [isStale, setIsStale] = useState(false);

  const issues = report?.issues ?? [];
  const dismissed = report?.dismissed_issues ?? [];
  const checkedAt = report?.checked_at ?? null;
  const manageReason = manageBlockedReason(access);
  const bulkReason = bulkBlockedReason(access) ?? (checkedAt ? null : NO_CHECK_YET);
  const showBulk = issues.length >= MIN_ISSUES_FOR_BULK;
  // Ticks that no longer match a listed conflict (after a reload) are ignored, not sent.
  const liveSelected = new Set(issues.filter((i) => selected.has(i.id)).map((i) => i.id));

  async function afterChange() {
    await load();
    onChanged?.();
  }

  async function handleFix(id: string, text?: string) {
    await fixIssue(id, text);
    await afterChange();
  }

  async function handleDismiss(id: string) {
    await dismissIssue(id);
    await afterChange();
  }

  async function handleRestore(id: string) {
    try {
      const result = await restoreIssues([id]);
      setNotice({ tone: result.restored.length > 0 ? "ok" : "warn", text: summarizeRestore(result) });
      await afterChange();
    } catch (e) {
      setNotice({ tone: "warn", text: e instanceof Error ? e.message : "Couldn't restore this. Please try again." });
    }
  }

  async function confirmBulk(action: BulkAction, ids: string[]) {
    if (!checkedAt) return;
    setIsBulkBusy(true);
    setNotice(null);
    let changed = false;
    try {
      if (action === "fix") {
        const result = await fixBatch(ids, checkedAt);
        changed = result.applied.length > 0;
        setNotice({ tone: result.skipped.length + result.failed.length > 0 ? "warn" : "ok", text: summarizeFix(result) });
      } else {
        const result = await dismissBatch(ids, checkedAt);
        changed = result.dismissed.length > 0;
        setNotice({ tone: result.skipped.length > 0 ? "warn" : "ok", text: summarizeDismiss(result) });
      }
      setSelected(new Set());
    } catch (e) {
      const partial = e instanceof BatchError ? partialSummary(e.partial) : null;
      changed = partial !== null;
      if (e instanceof StaleReportError) setIsStale(true);
      const message = e instanceof StaleReportError ? RELOAD_TEXT : e instanceof Error ? e.message : "Something went wrong. Please try again.";
      setNotice({ tone: "warn", text: partial ? `${partial} ${message}` : message });
    } finally {
      setIsBulkBusy(false);
      setSheet(null);
    }
    if (changed) await afterChange();
  }

  async function reload() {
    setIsStale(false);
    setNotice(null);
    setSelected(new Set());
    await load();
  }

  const chrome = embedded ? "space-y-3" : "space-y-3 rounded-2xl border border-amber-200 bg-amber-50/60 p-4 sm:p-5";
  const slimChrome = embedded
    ? "flex flex-wrap items-center justify-between gap-2"
    : "flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border-subtle bg-surface-low px-3.5 py-2.5";

  if (isLoading) return <div className="h-11 animate-pulse rounded-xl bg-border-subtle" aria-hidden />;

  const needsCheck = !checkedAt || report?.stale;
  const checkReason = manageReason;

  const feedback = (
    <>
      {isStale && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-300 bg-amber-100/70 px-3 py-2">
          <p className="min-w-0 break-words font-body text-xs text-ink">Issues changed since Anril checked. Reload to see the current list.</p>
          <button
            type="button"
            onClick={reload}
            className="inline-flex min-h-9 items-center rounded-lg bg-primary hover:bg-primary-dark px-3 font-label text-xs font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
          >
            Reload
          </button>
        </div>
      )}
      {notice && !(isStale && notice.text === RELOAD_TEXT) && (
        <div
          role={notice.tone === "warn" ? "alert" : "status"}
          className={`flex items-start justify-between gap-2 rounded-xl border px-3 py-2 ${notice.tone === "warn" ? "border-amber-300 bg-amber-100/70" : "border-emerald-200 bg-emerald-50"}`}
        >
          <p className="min-w-0 break-words font-body text-xs text-ink">{notice.text}</p>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="Dismiss this message"
            className="shrink-0 rounded p-1 text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
          >
            <X size={14} />
          </button>
        </div>
      )}
    </>
  );

  const dismissedList = (
    <ConsistencyDismissedList items={dismissed} blockedReason={manageReason} isLocked={isBulkBusy} onRestore={handleRestore} />
  );

  if (issues.length === 0) {
    return (
      <div aria-live="polite" className="space-y-2.5">
        {feedback}
        <div className={slimChrome}>
          <span className="min-w-0 break-words font-body text-xs text-ink-muted">
            {isChecking ? (
              "Anril is checking that your description and knowledge agree with your Services page…"
            ) : needsCheck ? (
              error ?? (checkedAt ? "Your setup changed since Anril last checked." : "Anril hasn't checked your setup yet.")
            ) : (
              <>Everything Anril knows agrees with your Services page{checkedAt ? ` · Checked ${timeAgo(checkedAt)}` : ""}</>
            )}
          </span>
          <CheckButton isChecking={isChecking} blockedReason={checkReason} onCheck={runCheck} />
        </div>
        {dismissedList}
      </div>
    );
  }

  const sheetIssues = sheet ? bulkTargets(issues, liveSelected) : [];

  return (
    <div aria-live="polite" className={chrome}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-700">
            <AlertTriangle size={14} />
          </span>
          <div className="min-w-0">
            <p className="font-display text-sm font-bold text-ink">
              Anril found {issues.length} thing{issues.length === 1 ? "" : "s"} that disagree{issues.length === 1 ? "s" : ""} with your Services page
            </p>
            <p className="mt-0.5 max-w-xl font-body text-xs leading-relaxed text-ink-secondary">
              Anril always follows your Services page when they disagree, but fixing these keeps every answer consistent.
              {checkedAt ? ` Last checked ${timeAgo(checkedAt)}.` : ""}
            </p>
          </div>
        </div>
        <CheckButton isChecking={isChecking} blockedReason={checkReason} onCheck={runCheck} />
      </div>

      {error && <p className="break-words font-body text-xs text-red-600">{error}</p>}
      {feedback}

      {showBulk && (
        <div className="flex flex-wrap items-center gap-2">
          {(["fix", "dismiss"] as const).map((action) => (
            <button
              key={action}
              type="button"
              disabled={isBulkBusy || bulkReason !== null}
              aria-describedby={bulkReason ? "conflicts-bulk-reason" : undefined}
              onClick={() => setSheet(action)}
              className={
                action === "fix"
                  ? "inline-flex min-h-9 items-center rounded-lg bg-primary px-3 font-label text-xs font-semibold text-white hover:bg-primary-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-50"
                  : "inline-flex min-h-9 items-center rounded-lg border border-border bg-white px-3 font-label text-xs font-semibold text-ink-secondary hover:border-primary/40 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-50"
              }
            >
              {bulkLabel(action, issues.length, liveSelected.size)}
            </button>
          ))}
          {liveSelected.size > 0 && (
            <button
              type="button"
              onClick={() => setSelected(new Set())}
              className="inline-flex min-h-9 items-center rounded-lg px-2 font-label text-xs font-semibold text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
            >
              Clear selection
            </button>
          )}
          {bulkReason && (
            <span id="conflicts-bulk-reason" className="font-body text-[11px] text-ink-muted">
              {bulkReason}
            </span>
          )}
        </div>
      )}

      <div className="space-y-2.5">
        {issues.map((issue) => (
          <ConsistencyIssueCard
            key={issue.id}
            issue={issue}
            access={access}
            selected={showBulk ? liveSelected.has(issue.id) : null}
            isLocked={isBulkBusy}
            onToggleSelected={(id) => setSelected((prev) => toggleId(prev, id))}
            onFix={handleFix}
            onDismiss={handleDismiss}
          />
        ))}
      </div>

      {dismissedList}

      {sheet && (
        <ConsistencyBulkSheet
          action={sheet}
          issues={sheetIssues}
          access={access}
          isBusy={isBulkBusy}
          onCancel={() => setSheet(null)}
          onConfirm={(ids) => confirmBulk(sheet, ids)}
        />
      )}
    </div>
  );
}
