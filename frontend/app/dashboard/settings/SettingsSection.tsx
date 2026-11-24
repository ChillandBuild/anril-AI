"use client";
import { CheckCircle2, Loader2, Save } from "lucide-react";
import { AiraLoader } from "@/components/AiraLoader";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

// The binary controls live in one shared place so the dashboard and the
// operator console cannot drift apart. Re-exported here because every
// settings panel already imports from this module.
export { SwitchPill, CheckTick, CheckField, TickMark } from "@/components/ui/controls";

/**
 * Settings sections are always open (2026-11-23): no chevron, nothing collapses.
 * The group wrapper only spaces the cards. `defaultOpenId` and `startClosed` are
 * still accepted so older callers compile, but they do nothing.
 */
export function SettingsAccordion({
  children,
}: {
  children: React.ReactNode;
  /** No effect: sections are always open. */
  defaultOpenId?: string | string[];
  /** No effect: sections are always open. */
  startClosed?: boolean;
}) {
  return <div className="space-y-2 sm:space-y-2.5">{children}</div>;
}

/* ------------------------------------------------------------------ */

export type SectionAccent = "violet" | "amber" | "sky" | "emerald";

const ACCENTS: Record<SectionAccent, { tile: string; icon: string; rail: string; glow: string }> = {
  violet: {
    tile: "bg-gradient-to-br from-[var(--primary-50)] to-[#e9e2ff] ring-[#ddd4fb]",
    icon: "text-primary",
    rail: "from-primary/70 via-primary-400/60 to-transparent",
    glow: "group-hover/section:shadow-[0_0_0_4px_rgba(var(--primary-800-rgb),0.06)]",
  },
  amber: {
    tile: "bg-gradient-to-br from-[#fffbeb] to-[#fdefc8] ring-[#f8e3ae]",
    icon: "text-amber-600",
    rail: "from-amber-500/70 via-amber-300/60 to-transparent",
    glow: "group-hover/section:shadow-[0_0_0_4px_rgba(217,119,6,0.06)]",
  },
  sky: {
    tile: "bg-gradient-to-br from-[#f0f9ff] to-[#dcedfd] ring-[#c3e0f8]",
    icon: "text-sky-600",
    rail: "from-sky-500/70 via-sky-300/60 to-transparent",
    glow: "group-hover/section:shadow-[0_0_0_4px_rgba(2,132,199,0.06)]",
  },
  emerald: {
    tile: "bg-gradient-to-br from-[#ecfdf5] to-[#d3f5e5] ring-[#b6ecd3]",
    icon: "text-emerald-600",
    rail: "from-emerald-500/70 via-emerald-300/60 to-transparent",
    glow: "group-hover/section:shadow-[0_0_0_4px_rgba(5,150,105,0.06)]",
  },
};

export type SectionStatus = {
  label: string;
  tone: "on" | "off" | "warn";
};

const STATUS_STYLES: Record<SectionStatus["tone"], string> = {
  on: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  off: "bg-[#f1f5f9] text-ink-secondary ring-border",
  warn: "bg-amber-50 text-amber-700 ring-amber-200",
};

export function SettingsSection({
  icon: Icon,
  title,
  description,
  accent = "violet",
  status,
  dirty = false,
  headerAction,
  children,
}: {
  /** Kept so callers still compile. */
  id: string;
  icon: LucideIcon;
  title: string;
  description: string;
  accent?: SectionAccent;
  status?: SectionStatus;
  /** Shows an "Unsaved" marker on the header. */
  dirty?: boolean;
  /** No effect: sections are always open. */
  defaultOpen?: boolean;
  /** No effect: sections are always open, so there is no collapsed summary. */
  summary?: React.ReactNode;
  /** A control on the right of the header (e.g. an on/off switch). It edits the draft; Save applies it. */
  headerAction?: React.ReactNode;
  children: React.ReactNode;
}) {
  const a = ACCENTS[accent];

  return (
    <section className="group/section relative overflow-hidden rounded-2xl border border-primary/20 bg-white shadow-[0_2px_4px_rgba(28,25,23,0.03),0_18px_40px_-24px_rgba(28,25,23,0.28)]">
      <span
        aria-hidden
        className={cn("pointer-events-none absolute inset-x-0 top-0 h-[3px] bg-gradient-to-r", a.rail)}
      />

      <div className="flex w-full items-start gap-3 bg-white px-4 py-3 sm:px-5 sm:py-3.5">
        <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ring-1", a.tile)}>
          <Icon size={15} className={a.icon} strokeWidth={2} />
        </span>

        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h2 className="font-display text-sm font-bold tracking-[-0.015em] text-ink">
              {title}
            </h2>
            {status && (
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-full px-1.5 py-px font-label text-[9.5px] font-bold uppercase tracking-wider ring-1 ring-inset",
                  STATUS_STYLES[status.tone]
                )}
              >
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    status.tone === "on"
                      ? "bg-emerald-500"
                      : status.tone === "warn"
                      ? "bg-amber-500"
                      : "bg-ink-muted"
                  )}
                />
                {status.label}
              </span>
            )}
            {dirty && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-1.5 py-px font-label text-[9.5px] font-bold uppercase tracking-wider text-amber-700 ring-1 ring-inset ring-amber-200">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
                Unsaved
              </span>
            )}
          </span>
          <span className="mt-0.5 block max-w-2xl font-body text-[12.5px] leading-snug text-ink-secondary">
            {description}
          </span>
        </span>

        {headerAction && <div className="mt-1.5 flex shrink-0 items-center">{headerAction}</div>}
      </div>

      <div className="border-t border-border-subtle px-4 py-4 sm:px-5 sm:py-5">{children}</div>
    </section>
  );
}

/**
 * Footer used inside a section body: status text on the left, save button
 * on the right, separated by a hairline. Keeps every panel's save row
 * identical instead of five near-copies.
 */
export function SectionFooter({
  children,
  status,
}: {
  children: React.ReactNode;
  status?: React.ReactNode;
}) {
  return (
    <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle pt-4">
      <div className="min-h-[20px] flex items-center">{status}</div>
      {children}
    </div>
  );
}

export type SaveState = "idle" | "dirty" | "saving" | "saved";

/** The one Save button every settings panel uses. */
export function SaveButton({
  state,
  dirty,
  disabled = false,
  onClick,
}: {
  state: SaveState;
  dirty: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  const active = !disabled && dirty && state !== "saving" && state !== "saved";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!active}
      className={cn(
        "inline-flex items-center gap-2 rounded-xl px-4 py-2 font-label text-sm font-semibold transition-all duration-200",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30",
        state === "saved"
          ? "cursor-default bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200"
          : active
          ? "bg-primary hover:bg-primary-dark text-white shadow-[0_6px_16px_-8px_rgba(var(--primary-800-rgb),0.7)] hover:shadow-[0_10px_22px_-8px_rgba(var(--primary-800-rgb),0.75)] hover:brightness-110 active:scale-[0.98]"
          : "cursor-default bg-surface-subtle text-ink-muted ring-1 ring-inset ring-border/70"
      )}
    >
      {state === "saving" ? (
        <>
          <Loader2 size={14} className="animate-spin" />
          Saving…
        </>
      ) : state === "saved" ? (
        <>
          <CheckCircle2 size={14} />
          Saved
        </>
      ) : (
        <>
          <Save size={14} />
          Save Changes
        </>
      )}
    </button>
  );
}

/** Left-hand status line in a SectionFooter: "Unsaved changes" / "Saved" / resting hint. */
export function SaveStatus({
  state,
  dirty,
  idleLabel,
}: {
  state: SaveState;
  dirty: boolean;
  idleLabel?: string;
}) {
  if (state === "saved") {
    return (
      <span className="inline-flex items-center gap-1.5 font-body text-sm font-medium text-emerald-600">
        <CheckCircle2 size={15} /> Saved successfully
      </span>
    );
  }
  if (dirty) {
    return (
      <span className="inline-flex items-center gap-1.5 font-body text-[11px] font-semibold text-amber-600">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
        Unsaved changes
      </span>
    );
  }
  return idleLabel ? <span className="font-body text-[11px] text-ink-muted">{idleLabel}</span> : null;
}

export type SectionLoadState = "loading" | "ready" | "error";

/**
 * Holds a section's form back until its saved values have loaded. Rendering the
 * form on built-in defaults lets an early Save overwrite the real config, so
 * the form (and its Save button) only appears once the load succeeds.
 */
export function SectionLoadGate({
  state,
  onRetry,
  children,
}: {
  state: SectionLoadState;
  onRetry: () => void;
  children: React.ReactNode;
}) {
  if (state === "loading") return <AiraLoader inline className="min-h-[160px]" />;
  if (state === "error") {
    return (
      <div className="flex min-h-[160px] flex-col items-center justify-center gap-3 text-center">
        <p className="font-body text-sm text-ink-muted">Couldn&apos;t load these settings.</p>
        <button type="button" onClick={onRetry} className="btn-primary text-sm px-5 py-2">
          Retry
        </button>
      </div>
    );
  }
  return <>{children}</>;
}

/* ------------------------------------------------------------------ *
 * Collapsed-card summary
 *
 * Pass these as a section's `summary` so a closed card says what is set
 * ("3 of 6 events", "After 5 min", the template name) without opening it.
 * They render inside the header <button>, so they are spans only: no block
 * elements, nothing interactive.
 * ------------------------------------------------------------------ */

export function Facts({ children }: { children: React.ReactNode }) {
  return <span className="flex flex-wrap items-center gap-1">{children}</span>;
}

export function Fact({
  icon: Icon,
  mono = false,
  children,
}: {
  icon?: LucideIcon;
  mono?: boolean;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-border-subtle bg-surface-subtle px-1.5 py-px text-[11px] text-ink-secondary",
        mono ? "font-mono font-medium" : "font-body font-semibold"
      )}
    >
      {Icon && <Icon size={11} className="shrink-0 text-ink-muted" />}
      {children}
    </span>
  );
}

export function SummaryHint({ tone = "muted", children }: { tone?: "muted" | "warn"; children: React.ReactNode }) {
  return (
    <span className={cn("block font-body text-[11.5px]", tone === "warn" ? "font-semibold text-amber-700" : "text-ink-muted")}>
      {children}
    </span>
  );
}

/** Divider label that groups cards on one page (e.g. by where an alert arrives). */
export function GroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 px-1 pt-2 first:pt-0">
      <span className="font-label text-[10.5px] font-bold uppercase tracking-wider text-ink-muted">{children}</span>
      <span aria-hidden className="h-px flex-1 bg-border-subtle" />
    </div>
  );
}
