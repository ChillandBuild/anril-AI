"use client";
import { cn } from "@/lib/utils";
import type { CompanionStatus } from "@/lib/api";

/** Shared bits for the Anril Agents pages: cards, buttons, fields, status pill. */

export const CARD = "rounded-2xl border border-border-subtle bg-white p-5";
export const BTN_PRIMARY =
  "inline-flex min-h-9 items-center justify-center gap-1.5 rounded-xl bg-primary px-4 text-sm font-semibold text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-50";
export const BTN_SECONDARY =
  "inline-flex min-h-9 items-center justify-center gap-1.5 rounded-xl border border-border bg-white px-4 text-sm font-medium text-ink transition-colors hover:bg-surface-mid disabled:cursor-not-allowed disabled:opacity-50";
export const BTN_DANGER =
  "inline-flex min-h-9 items-center justify-center gap-1.5 rounded-xl bg-danger px-4 text-sm font-semibold text-white transition-colors hover:bg-danger/90 disabled:cursor-not-allowed disabled:opacity-50";
export const BTN_ROW_DANGER =
  "inline-flex min-h-8 items-center justify-center gap-1.5 rounded-xl border border-danger/40 bg-white px-3 text-[13px] font-medium text-danger transition-colors hover:bg-danger/5 disabled:cursor-not-allowed disabled:opacity-50";
export const INPUT =
  "w-full rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/15";

const STATUS_STYLE: Record<CompanionStatus, string> = {
  live: "bg-success/10 text-success",
  draft: "bg-surface-mid text-ink-secondary",
  paused: "bg-amber-50 text-amber-700",
};

export function StatusPill({ status }: { status: CompanionStatus }) {
  return (
    <span className={cn("inline-flex rounded-full px-2 py-0.5 text-xs font-medium capitalize", STATUS_STYLE[status] ?? STATUS_STYLE.draft)}>
      {status}
    </span>
  );
}

export function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-ink">
        {label}
      </label>
      {children}
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-ink-secondary">{hint}</p>
      ) : null}
    </div>
  );
}

export function LoadingRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-11 animate-pulse rounded-xl bg-surface-mid" />
      ))}
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-danger/20 bg-danger/5 px-4 py-3 text-sm text-danger">
      <span>{message}</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="font-medium underline underline-offset-2">
          Try again
        </button>
      )}
    </div>
  );
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
