"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { COMPARE_COLORS, MAX_COMPARE, monthKey, monthsText, parseMonth, SHORT_MONTHS } from "./shared";

/**
 * A popover with a caller-drawn trigger. Portalled to <body> for the same reason as
 * FilterPopover: the dashboard content wrapper clips anything that overflows it.
 */
export function Popover({
  trigger,
  children,
  align = "left",
}: {
  trigger: (open: boolean, toggle: () => void) => React.ReactNode;
  children: (close: () => void) => React.ReactNode;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      const rect = ref.current?.getBoundingClientRect();
      if (!rect) return;
      const width = panelRef.current?.offsetWidth ?? 260;
      const wanted = align === "right" ? rect.right - width : rect.left;
      setPos({ top: rect.bottom + 6, left: Math.max(8, Math.min(wanted, window.innerWidth - width - 8)) });
    }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, align]);

  useEffect(() => {
    if (!open) return;
    function outside(e: MouseEvent) {
      const target = e.target as Node;
      if (ref.current?.contains(target) || panelRef.current?.contains(target)) return;
      setOpen(false);
    }
    function escape(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative shrink-0">
      {trigger(open, () => setOpen((o) => !o))}
      {open &&
        createPortal(
          <div
            ref={panelRef}
            style={{ top: pos?.top ?? 0, left: pos?.left ?? 0, visibility: pos ? "visible" : "hidden" }}
            className="fixed z-50 rounded-2xl border border-[#e2e8f0] bg-white p-2 shadow-lg"
          >
            {children(() => setOpen(false))}
          </div>,
          document.body
        )}
    </div>
  );
}

const MIN_YEAR = 2000;

/**
 * Year header for the month grids. ‹ › step one year; clicking the year opens a grid of
 * 12 years (‹ › then jump 12 at a time), so going back to e.g. 2004 takes two clicks.
 */
function YearPanel({
  year,
  onYear,
  maxYear,
  activeYears,
  badge,
  children,
}: {
  year: number;
  onYear: (y: number) => void;
  maxYear: number;
  activeYears: Set<number>;
  /** Small count shown on a year, e.g. how many of its months are ticked. */
  badge?: (y: number) => number;
  children: React.ReactNode;
}) {
  const [picking, setPicking] = useState(false);
  const [pageEnd, setPageEnd] = useState(maxYear);
  const pageYears = Array.from({ length: 12 }, (_, i) => pageEnd - 11 + i).filter((y) => y >= MIN_YEAR);
  const arrow = "grid h-7 w-7 place-items-center rounded-lg text-[#334155] hover:bg-slate-50 disabled:text-slate-300 disabled:hover:bg-transparent";

  function openYears() {
    setPageEnd(maxYear - Math.floor((maxYear - year) / 12) * 12);
    setPicking(true);
  }

  if (picking) {
    return (
      <div>
        <div className="flex items-center justify-between px-1 pb-1.5">
          <button type="button" onClick={() => setPageEnd((e) => e - 12)} disabled={pageEnd - 12 < MIN_YEAR} aria-label="Earlier years" className={arrow}>
            <ChevronLeft size={15} />
          </button>
          <button type="button" onClick={() => setPicking(false)} className="rounded-lg px-2 py-1 text-sm font-extrabold tabular-nums text-[#0A1528] hover:bg-slate-50">
            {pageYears[0]}–{pageYears[pageYears.length - 1]}
          </button>
          <button type="button" onClick={() => setPageEnd((e) => e + 12)} disabled={pageEnd >= maxYear} aria-label="Later years" className={arrow}>
            <ChevronRight size={15} />
          </button>
        </div>
        <div className="grid grid-cols-3 gap-1">
          {pageYears.map((y) => {
            const count = badge?.(y) ?? 0;
            return (
              <button
                key={y}
                type="button"
                onClick={() => {
                  onYear(y);
                  setPicking(false);
                }}
                className={cn(
                  "relative rounded-lg py-2 text-xs font-bold tabular-nums transition-colors",
                  y === year ? "bg-primary text-white" : "text-[#0A1528] hover:bg-slate-50"
                )}
              >
                {y}
                {count > 0 && (
                  <span className="absolute right-1 top-0.5 grid h-3.5 min-w-3.5 place-items-center rounded-full bg-primary px-0.5 text-[9px] text-white">
                    {count}
                  </span>
                )}
                {activeYears.has(y) && count === 0 && (
                  <span className={cn("absolute bottom-1 left-1/2 h-1 w-1 -translate-x-1/2 rounded-full", y === year ? "bg-white" : "bg-primary")} />
                )}
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between px-1 pb-1.5">
        <button type="button" onClick={() => onYear(year - 1)} disabled={year <= MIN_YEAR} aria-label="Previous year" className={arrow}>
          <ChevronLeft size={15} />
        </button>
        <button
          type="button"
          onClick={openYears}
          title="Pick a year"
          className="flex items-center gap-1 rounded-lg px-2 py-1 text-sm font-extrabold tabular-nums text-[#0A1528] hover:bg-slate-50"
        >
          {year}
          <ChevronDown size={13} className="text-[#64748b]" />
        </button>
        <button type="button" onClick={() => onYear(year + 1)} disabled={year >= maxYear} aria-label="Next year" className={arrow}>
          <ChevronRight size={15} />
        </button>
      </div>
      {children}
    </div>
  );
}

const yearsOf = (months: Iterable<string>) => new Set(Array.from(months, (m) => parseMonth(m).year));

/** Year header and a 3×4 grid of months. Months after `max` can't be picked. */
export function MonthGrid({
  value,
  max,
  activeMonths,
  onPick,
}: {
  value: string | null;
  max: string;
  activeMonths: Set<string>;
  onPick: (month: string) => void;
}) {
  const [year, setYear] = useState(() => parseMonth(value ?? max).year);
  const maxYear = parseMonth(max).year;

  return (
    <div className="w-[248px]">
      <YearPanel year={year} onYear={setYear} maxYear={maxYear} activeYears={yearsOf(activeMonths)}>
        <div className="grid grid-cols-3 gap-1">
          {SHORT_MONTHS.map((name, i) => {
            const key = monthKey(year, i + 1);
            const blocked = key > max;
            const selected = key === value;
            return (
              <button
                key={key}
                type="button"
                disabled={blocked}
                onClick={() => onPick(key)}
                className={cn(
                  "relative rounded-lg py-2 text-xs font-bold transition-colors",
                  selected ? "bg-primary text-white" : "text-[#0A1528] hover:bg-slate-50",
                  blocked && "cursor-not-allowed text-slate-300 hover:bg-transparent"
                )}
              >
                {name}
                {activeMonths.has(key) && (
                  <span
                    className={cn(
                      "absolute bottom-1 left-1/2 h-1 w-1 -translate-x-1/2 rounded-full",
                      selected ? "bg-white" : "bg-primary"
                    )}
                  />
                )}
              </button>
            );
          })}
        </div>
      </YearPanel>
      <p className="mt-2 flex items-center gap-1.5 px-1 text-[11px] text-[#64748b]">
        <span className="h-1 w-1 rounded-full bg-primary" /> had sales
      </p>
    </div>
  );
}

/** Tick up to MAX_COMPARE months, across any years, to compare with; nothing applies until "Compare". */
export function CompareGrid({
  picked,
  max,
  exclude,
  activeMonths,
  onApply,
}: {
  picked: string[];
  max: string;
  exclude: string;
  activeMonths: Set<string>;
  onApply: (months: string[]) => void;
}) {
  const maxYear = parseMonth(max).year;
  const [draft, setDraft] = useState<string[]>(picked);
  const [year, setYear] = useState(() => parseMonth([...picked].sort().pop() ?? max).year);
  const full = draft.length >= MAX_COMPARE;
  const unchanged = draft.length === picked.length && draft.every((m) => picked.includes(m));

  function toggle(key: string) {
    setDraft((d) => (d.includes(key) ? d.filter((m) => m !== key) : d.length < MAX_COMPARE ? [...d, key] : d));
  }

  return (
    <div className="w-[264px]">
      <YearPanel
        year={year}
        onYear={setYear}
        maxYear={maxYear}
        activeYears={yearsOf(activeMonths)}
        badge={(y) => draft.filter((m) => parseMonth(m).year === y).length}
      >
        <div className="grid grid-cols-3 gap-1">
          {SHORT_MONTHS.map((name, i) => {
            const key = monthKey(year, i + 1);
            const index = draft.indexOf(key);
            const on = index >= 0;
            const blocked = key > max || key === exclude || (!on && full);
            return (
              <button
                key={key}
                type="button"
                disabled={blocked}
                onClick={() => toggle(key)}
                aria-pressed={on}
                title={key === exclude ? "This is the month you're viewing" : !on && full ? `You can compare up to ${MAX_COMPARE} months` : undefined}
                className={cn(
                  "relative flex items-center justify-center gap-1 rounded-lg border py-2 text-xs font-bold transition-colors",
                  on ? "border-primary bg-primary/10 text-primary" : "border-transparent text-[#0A1528] hover:bg-slate-50",
                  blocked && "cursor-not-allowed text-slate-300 hover:bg-transparent"
                )}
              >
                {on && <i className="h-2 w-2 rounded-full" style={{ background: COMPARE_COLORS[index] }} />}
                {name}
                {activeMonths.has(key) && !on && (
                  <span className={cn("absolute bottom-1 left-1/2 h-1 w-1 -translate-x-1/2 rounded-full", blocked ? "bg-slate-300" : "bg-primary")} />
                )}
              </button>
            );
          })}
        </div>
      </YearPanel>

      <div className="mt-2 flex items-center justify-between gap-2 px-1">
        <span className="min-w-0 truncate text-[11px] text-[#64748b]">
          {full ? `${MAX_COMPARE} of ${MAX_COMPARE} picked · untick one to swap` : draft.length ? monthsText(draft) : (
            <span className="flex items-center gap-1.5"><span className="h-1 w-1 rounded-full bg-primary" /> had sales · pick up to {MAX_COMPARE}</span>
          )}
        </span>
        {draft.length > 0 && (
          <button type="button" onClick={() => setDraft([])} className="shrink-0 text-[11px] font-bold text-[#64748b] hover:text-[#0A1528]">
            Clear
          </button>
        )}
      </div>
      <button
        type="button"
        disabled={draft.length === 0 || unchanged}
        onClick={() => onApply(draft)}
        className="mt-2 w-full rounded-xl bg-primary py-2 text-xs font-bold text-white transition-opacity hover:bg-primary/90 disabled:opacity-40"
      >
        {draft.length > 1 ? `Compare with these ${draft.length} months` : "Compare"}
      </button>
    </div>
  );
}
