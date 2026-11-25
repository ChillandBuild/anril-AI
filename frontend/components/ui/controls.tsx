"use client";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ *
 * The app's two binary controls. Every switch and every checkbox in the
 * dashboard and the operator console goes through one of these, so the
 * look only ever has to change in this file.
 *
 *   SwitchPill  — on/off for a setting that takes effect on save
 *   CheckTick   — selection: pick items, tick options
 *   CheckField  — CheckTick plus a label and description, as one row
 * ------------------------------------------------------------------ */

type Size = "sm" | "md";

/* ================================================================== *
 * SwitchPill — track switch with a check/cross riding in the knob
 * ================================================================== */

const SWITCH_SIZES: Record<Size, { track: string; knob: string; travel: string; icon: number }> = {
  sm: { track: "h-5 w-9", knob: "h-[14px] w-[14px]", travel: "translate-x-[16px]", icon: 8 },
  md: { track: "h-6 w-11", knob: "h-[18px] w-[18px]", travel: "translate-x-[20px]", icon: 10 },
};

export function SwitchPill({
  on,
  onChange,
  disabled = false,
  loading = false,
  size = "md",
  "aria-label": ariaLabel,
}: {
  on: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  loading?: boolean;
  size?: Size;
  "aria-label"?: string;
}) {
  const s = SWITCH_SIZES[size];
  const inert = disabled || loading;

  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={ariaLabel}
      disabled={inert}
      onClick={() => !inert && onChange(!on)}
      className={cn(
        "relative shrink-0 rounded-full border p-0 transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
        // Invisible finger-size tap area (about 56x40) around the small track.
        "before:absolute before:-inset-2.5 before:content-['']",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 focus-visible:ring-offset-2 focus-visible:ring-offset-white",
        s.track,
        on
          ? "border-primary bg-primary shadow-[inset_0_1px_3px_rgba(var(--primary-950-rgb),0.4)]"
          : "border-border bg-[#e4ded2] shadow-[inset_0_1px_3px_rgba(28,25,23,0.09)]",
        inert ? "cursor-not-allowed opacity-45" : "cursor-pointer"
      )}
    >
      <span
        className={cn(
          "absolute left-[2px] top-[2px] grid place-items-center rounded-full bg-white shadow-[0_1px_4px_rgba(28,25,23,0.3)]",
          "transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
          s.knob,
          on && s.travel
        )}
      >
        {loading ? (
          <Loader2 size={s.icon} className="animate-spin text-ink-muted" strokeWidth={3} />
        ) : on ? (
          <svg
            width={s.icon}
            height={s.icon}
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--primary-800)"
            strokeWidth={3.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M20 6L9 17l-5-5" />
          </svg>
        ) : (
          <svg
            width={s.icon}
            height={s.icon}
            viewBox="0 0 24 24"
            fill="none"
            stroke="#94a3b8"
            strokeWidth={3.5}
            strokeLinecap="round"
            aria-hidden
          >
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        )}
      </span>
    </button>
  );
}

/* ================================================================== *
 * CheckTick — ring that fills violet and draws its tick
 * ================================================================== */

const TICK_SIZES: Record<Size, { box: string; icon: number }> = {
  sm: { box: "h-4 w-4", icon: 10 },
  md: { box: "h-[18px] w-[18px]", icon: 11 },
};

/**
 * The tick itself, with no interactivity — use inside a control that is
 * already a button, so we never nest one button in another.
 */
export function TickMark({
  checked,
  indeterminate = false,
  disabled = false,
  size = "md",
  className,
}: {
  checked: boolean;
  indeterminate?: boolean;
  disabled?: boolean;
  size?: Size;
  className?: string;
}) {
  const s = TICK_SIZES[size];
  const filled = checked || indeterminate;

  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center rounded-full border-2 transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
        s.box,
        filled
          ? "border-primary bg-primary shadow-[0_0_0_3px_rgba(var(--primary-800-rgb),0.13)]"
          : "border-[#c9c2b6] bg-transparent",
        disabled && "opacity-45",
        className
      )}
    >
      {indeterminate ? (
        <span className="block h-[2px] w-[8px] rounded-full bg-white" />
      ) : (
        <svg
          width={s.icon}
          height={s.icon}
          viewBox="0 0 24 24"
          fill="none"
          stroke="#ffffff"
          strokeWidth={3.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path
            d="M20 6L9 17l-5-5"
            style={{
              strokeDasharray: 24,
              strokeDashoffset: checked ? 0 : 24,
              transition: "stroke-dashoffset 340ms cubic-bezier(0.16, 1, 0.3, 1)",
            }}
          />
        </svg>
      )}
    </span>
  );
}

/** Bare tick control — for table cells and inline lists. */
export function CheckTick({
  checked,
  indeterminate = false,
  onChange,
  disabled = false,
  size = "md",
  className,
  "aria-label": ariaLabel,
}: {
  checked: boolean;
  indeterminate?: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  size?: Size;
  className?: string;
  "aria-label"?: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={indeterminate ? "mixed" : checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        if (!disabled) onChange(!checked);
      }}
      className={cn(
        "relative inline-grid place-items-center rounded-full p-0 transition-transform duration-200",
        // Invisible tap area: the 16-18px tick is reachable with a finger (about 32px).
        "before:absolute before:-inset-2 before:content-['']",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 focus-visible:ring-offset-2 focus-visible:ring-offset-white",
        disabled ? "cursor-not-allowed" : "cursor-pointer hover:scale-105 active:scale-95",
        className
      )}
    >
      <TickMark checked={checked} indeterminate={indeterminate} disabled={disabled} size={size} />
    </button>
  );
}

/**
 * A whole selectable row: tick, label, optional description. One button,
 * so the entire row is the hit target and the tick never nests.
 */
export function CheckField({
  checked,
  onChange,
  label,
  description,
  disabled = false,
  locked = false,
  lockedNote,
  tone = "default",
  size = "md",
  className,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: React.ReactNode;
  description?: React.ReactNode;
  disabled?: boolean;
  /** Always-on option: shown ticked, explains itself, cannot be changed. */
  locked?: boolean;
  lockedNote?: React.ReactNode;
  tone?: "default" | "locked";
  size?: Size;
  className?: string;
}) {
  const inert = disabled || locked;
  const amber = tone === "locked" || locked;

  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-disabled={inert || undefined}
      disabled={inert}
      onClick={() => !inert && onChange(!checked)}
      className={cn(
        "flex w-full items-start gap-3 rounded-xl border p-3.5 text-left transition-all duration-200",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30",
        amber
          ? "border-amber-200 bg-amber-50/70"
          : checked
          ? "border-primary/25 bg-primary-light/50"
          : "border-border bg-surface-subtle",
        inert ? "cursor-default" : "cursor-pointer hover:border-primary/40",
        disabled && !locked && "opacity-55",
        className
      )}
    >
      <TickMark checked={checked} disabled={disabled} size={size} className="mt-[1px]" />
      <span className="min-w-0 flex-1">
        <span className="block font-label text-sm font-semibold text-ink">{label}</span>
        {description && <span className="mt-0.5 block font-body text-xs text-ink-secondary">{description}</span>}
        {locked && lockedNote && (
          <span className="mt-0.5 block font-label text-xs text-amber-600">{lockedNote}</span>
        )}
      </span>
    </button>
  );
}
