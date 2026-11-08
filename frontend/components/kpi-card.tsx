"use client";
import type { ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

interface KpiCardProps {
  label: string;
  value: ReactNode;
  /** Short grey line under the label, e.g. "Clicked the ad and opened a chat". */
  hint?: ReactNode;
  /** Tailwind bg class for the coloured bar on the left, e.g. "bg-primary". */
  edge?: string;
  /** Shows a pulse in place of the number. */
  loading?: boolean;
  /** Small muted text right after the number, e.g. "/ 12 used". */
  suffix?: ReactNode;
  /** A pill or icon at the right end of the card, e.g. "3 slots free". */
  badge?: ReactNode;
  /** Full-width extra row under the card body: a progress bar, a delta, a link. */
  children?: ReactNode;
  /**
   * Number above the label instead of beside it. For long values (money,
   * "7h 5m", a name) that would squeeze the label in a narrow column.
   */
  stacked?: boolean;
  /** Extra classes for the number, e.g. a tone colour. */
  valueClassName?: string;
  /** Native tooltip for the whole card. */
  title?: string;
  /** Renders the card as a link. */
  href?: string;
  /** Renders the card as a button. */
  onClick?: () => void;
  /** Highlighted as the active filter (with href or onClick). */
  selected?: boolean;
  className?: string;
}

// Old cards were coloured by a border-t-* tone class; callers that still pass
// one get the matching left-bar colour.
const EDGE_FROM_TONE: Record<string, string> = {
  "border-t-primary-500": "bg-primary",
  "border-t-sky-400": "bg-blue-600",
  "border-t-amber-400": "bg-amber-400",
  "border-t-emerald-400": "bg-emerald-500",
  "border-t-rose-400": "bg-rose-500",
  "border-t-purple-400": "bg-purple-500",
  "border-t-teal-400": "bg-teal-500",
};

export function edgeFromTone(tone: string): string {
  return EDGE_FROM_TONE[tone] ?? "bg-primary";
}

/**
 * Stat card in the Deals / Segments style: a coloured bar on the left, the
 * number, then the label and a hint. The one KPI card for dashboard pages.
 */
export function KpiCard({
  label,
  value,
  hint,
  edge = "bg-primary",
  loading,
  suffix,
  badge,
  children,
  stacked,
  valueClassName,
  title,
  href,
  onClick,
  selected,
  className,
}: KpiCardProps) {
  const interactive = Boolean(href || onClick);
  const shell = cn(
    "relative flex flex-col overflow-hidden rounded-2xl border bg-white py-4 pl-5 pr-4 text-left transition-all",
    selected ? "border-2 border-primary ring-4 ring-primary/10" : "border-[#e2e8f0]",
    interactive && !selected && "hover:border-slate-300",
    className
  );

  const number = (
    <div
      className={cn(
        "shrink-0 font-display text-3xl font-bold leading-none tabular-nums text-[#0A1528]",
        !stacked && "min-w-[2ch]",
        valueClassName
      )}
    >
      {loading ? (
        <span className="inline-block h-8 w-8 animate-pulse rounded bg-[#f1f5f9] align-middle" />
      ) : (
        <>
          {value}
          {suffix && <span className="ml-1 text-sm font-semibold text-[#64748b]">{suffix}</span>}
        </>
      )}
    </div>
  );

  const text = (
    <div className="min-w-0">
      <div className="truncate text-sm font-bold text-[#0A1528]">{label}</div>
      {hint && (
        <div className="truncate text-xs text-[#64748b]" title={typeof hint === "string" ? hint : undefined}>
          {hint}
        </div>
      )}
    </div>
  );

  const body = (
    <>
      <div className={cn("absolute bottom-3 left-0 top-3 w-1 rounded-r", edge)} />
      <div className={cn("flex gap-3", stacked ? "flex-col gap-1.5" : "items-center")}>
        {stacked ? (
          <div className="flex items-start justify-between gap-2">
            {number}
            {badge && <div className="shrink-0">{badge}</div>}
          </div>
        ) : (
          number
        )}
        {text}
        {!stacked && badge && <div className="ml-auto shrink-0 self-start">{badge}</div>}
      </div>
      {children && <div className="mt-3">{children}</div>}
    </>
  );

  if (href) {
    return (
      <Link href={href} title={title} className={shell}>
        {body}
      </Link>
    );
  }
  if (onClick) {
    return (
      <button type="button" onClick={onClick} title={title} aria-pressed={selected} className={shell}>
        {body}
      </button>
    );
  }
  return (
    <div title={title} className={shell}>
      {body}
    </div>
  );
}
