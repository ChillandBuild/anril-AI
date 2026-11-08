"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { CalendarDays, Check, ChevronDown, MoreHorizontal, Search, type LucideIcon } from "lucide-react";
import { useSyncStart } from "@/hooks/useApi";
import { cn } from "@/lib/utils";
import { DataFromPicker } from "./DataFromPicker";

/** Shared look for the one-line toolbar on both Meta Ads tabs. */
export const TOOLBAR_BUTTON =
  "flex h-9 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-xl border border-[#e2e8f0] bg-white px-3 font-label text-xs font-bold text-[#0A1528] shadow-sm transition-colors hover:border-primary-200 hover:text-primary-700 disabled:cursor-not-allowed disabled:opacity-40";

/** Closes a popover on an outside click or Escape. */
function useDismiss(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    function onPointer(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) close();
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") close();
    }
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);
  return ref;
}

export type ReportLevel = "campaign" | "adset" | "ad";

export type LevelFilter = {
  /** `hint` (e.g. the ads inside) shows under a name that appears more than once. */
  options: { id: string; name: string; hint?: string }[];
  value: string;
  onChange: (id: string) => void;
};

const LEVELS: { key: ReportLevel; label: string; all: string; noun: string }[] = [
  { key: "campaign", label: "Campaigns", all: "All campaigns", noun: "campaigns" },
  { key: "adset", label: "Ad sets", all: "All ad sets", noun: "ad sets" },
  { key: "ad", label: "Ads", all: "All ads", noun: "ads" },
];

/**
 * Campaigns | Ad sets | Ads, as in Ads Manager: the highlight slides to the
 * level the table is showing, and each option's ▾ narrows the report to one
 * campaign, ad set or ad.
 */
export function LevelSwitch({
  level,
  onLevel,
  filters,
}: {
  level: ReportLevel;
  onLevel: (level: ReportLevel) => void;
  filters: Record<ReportLevel, LevelFilter>;
}) {
  const [openFor, setOpenFor] = useState<ReportLevel | null>(null);
  const [query, setQuery] = useState("");
  const ref = useDismiss(openFor !== null, () => setOpenFor(null));
  const index = LEVELS.findIndex((item) => item.key === level);
  const open = LEVELS.find((item) => item.key === openFor);
  const openFilter = openFor ? filters[openFor] : null;
  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (openFilter?.options ?? []).filter((option) => !needle || option.name.toLowerCase().includes(needle));
  }, [openFilter, query]);
  // Two campaigns can share a name; only then is the hint worth the space.
  const repeated = useMemo(() => {
    const seen = new Map<string, number>();
    for (const option of openFilter?.options ?? []) seen.set(option.name, (seen.get(option.name) ?? 0) + 1);
    return seen;
  }, [openFilter]);

  function toggleMenu(key: ReportLevel) {
    setQuery("");
    setOpenFor((current) => (current === key ? null : key));
  }

  function pick(id: string) {
    openFilter?.onChange(id);
    setOpenFor(null);
  }

  return (
    <div ref={ref} className="relative shrink-0">
      <div role="tablist" aria-label="Report level" className="relative grid h-9 w-[330px] grid-cols-3 rounded-xl bg-[#eef2f6] p-1">
        <span
          aria-hidden="true"
          className="absolute inset-y-1 left-1 w-[calc((100%-0.5rem)/3)] rounded-lg bg-white shadow-sm ring-1 ring-black/[0.03] transition-transform duration-300 ease-out"
          style={{ transform: `translateX(${index * 100}%)` }}
        />
        {LEVELS.map((item) => {
          const active = item.key === level;
          const filtered = Boolean(filters[item.key].value);
          return (
            <div key={item.key} className="relative z-10 flex min-w-0 items-center justify-center">
              <button
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => onLevel(item.key)}
                className={cn(
                  "flex h-7 min-w-0 items-center gap-1.5 rounded-lg pl-2 pr-1 font-label text-xs font-bold transition-colors",
                  active ? "text-primary-700" : "text-[#475569] hover:text-[#0A1528]",
                )}
              >
                <span className="truncate">{item.label}</span>
                {filtered && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary-600" aria-label="filtered" />}
              </button>
              <button
                type="button"
                aria-label={`Filter ${item.noun}`}
                aria-expanded={openFor === item.key}
                aria-haspopup="listbox"
                onClick={() => toggleMenu(item.key)}
                className={cn(
                  "flex h-5 w-5 shrink-0 items-center justify-center rounded-md transition-colors",
                  openFor === item.key ? "bg-primary-100 text-primary-700" : "text-[#94a3b8] hover:bg-black/5 hover:text-[#0A1528]",
                )}
              >
                <ChevronDown size={12} strokeWidth={2.5} className={cn("transition-transform", openFor === item.key && "rotate-180")} />
              </button>
            </div>
          );
        })}
      </div>

      {open && openFilter && (
        <div className="absolute left-0 top-11 z-30 w-[300px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-2xl border border-[#e2e8f0] bg-white p-2 shadow-xl">
          <div className="relative mb-1.5">
            <Search size={12} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
            <input
              type="search"
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={`Search ${open.noun}`}
              aria-label={`Search ${open.noun}`}
              className="h-8 w-full rounded-xl border border-[#e2e8f0] bg-[#f8fafc] pl-8 pr-3 font-body text-xs font-semibold text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-200"
            />
          </div>
          <div role="listbox" aria-label={open.label} className="max-h-64 overflow-y-auto overscroll-contain">
            {[{ id: "", name: open.all, hint: undefined } as LevelFilter["options"][number], ...matches].map((option) => {
              const selected = openFilter.value === option.id;
              const hint = option.hint && (repeated.get(option.name) ?? 0) > 1 ? option.hint : null;
              return (
                <button
                  key={option.id || "all"}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  onClick={() => pick(option.id)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left font-label text-xs font-bold",
                    selected ? "bg-primary-50 text-primary-800" : "text-[#334155] hover:bg-stone-50",
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate" title={option.name}>{option.name}</span>
                    {hint && <span className="mt-0.5 block truncate font-body text-[10px] font-medium text-[#94a3b8]" title={hint}>{hint}</span>}
                  </span>
                  {selected && <Check size={13} className="shrink-0 text-primary-600" />}
                </button>
              );
            })}
            {matches.length === 0 && (
              <p className="px-3 py-4 text-center font-body text-[11px] text-stone-400">No {open.noun} match.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function isoLocal(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function daysBack(days: number) {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return isoLocal(date);
}

/** "2026-08-01" -> "1 Aug 2026" (or "1 Aug" without the year). */
function shortDay(iso: string, withYear = true) {
  return new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    ...(withYear ? { year: "numeric" } : {}),
  });
}

export function rangeLabel(from: string, to: string) {
  if (!from || !to) return "Pick dates";
  const sameYear = from.slice(0, 4) === to.slice(0, 4);
  return `${shortDay(from, !sameYear)} – ${shortDay(to)}`;
}

/**
 * The dates pill and its menu: quick ranges, a custom range, and -- at the
 * bottom -- the account's history date ("Anril has ad data from …"), which used
 * to be its own button.
 */
export function DatesMenu({
  dateFrom,
  dateTo,
  onChange,
  canManage,
  onHistorySaved,
  historyNote,
}: {
  dateFrom: string;
  dateTo: string;
  onChange: (from: string, to: string) => void;
  canManage: boolean;
  onHistorySaved?: () => unknown;
  historyNote: ReactNode;
}) {
  const { data: syncStart } = useSyncStart();
  const [open, setOpen] = useState(false);
  const [customFrom, setCustomFrom] = useState(dateFrom);
  const [customTo, setCustomTo] = useState(dateTo);
  const ref = useDismiss(open, () => setOpen(false));
  const today = isoLocal(new Date());
  const firstDay = (syncStart?.start_date ?? syncStart?.earliest_ad_start ?? "").slice(0, 10);
  const now = new Date();
  const presets = [
    { label: "Last 7 days", from: daysBack(6), to: today },
    { label: "Last 30 days", from: daysBack(29), to: today },
    { label: "This month", from: isoLocal(new Date(now.getFullYear(), now.getMonth(), 1)), to: today },
    {
      label: "Last month",
      from: isoLocal(new Date(now.getFullYear(), now.getMonth() - 1, 1)),
      to: isoLocal(new Date(now.getFullYear(), now.getMonth(), 0)),
    },
    ...(firstDay ? [{ label: "Everything", from: firstDay, to: today, hint: `from ${shortDay(firstDay, false)}` }] : []),
  ];
  const current = presets.find((preset) => preset.from === dateFrom && preset.to === dateTo);

  function toggle() {
    setCustomFrom(dateFrom);
    setCustomTo(dateTo);
    setOpen((visible) => !visible);
  }

  function choose(from: string, to: string) {
    onChange(from, to);
    setOpen(false);
  }

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-haspopup="dialog"
        className="flex h-9 items-center gap-1.5 whitespace-nowrap rounded-xl border border-primary-200 bg-primary-50 px-3 font-label text-xs font-bold text-primary-800 shadow-sm transition-colors hover:bg-primary-100"
      >
        <CalendarDays size={13} />
        {rangeLabel(dateFrom, dateTo)}
        <ChevronDown size={12} strokeWidth={2.5} className={cn("transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div role="dialog" aria-label="Dates" className="absolute left-0 top-11 z-30 w-[320px] max-w-[calc(100vw-2rem)] rounded-2xl border border-[#e2e8f0] bg-white p-3 shadow-xl">
          <p className="mb-1.5 px-1 font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">Show numbers for</p>
          <div className="space-y-0.5">
            {presets.map((preset) => {
              const selected = current?.label === preset.label;
              return (
                <button
                  key={preset.label}
                  type="button"
                  onClick={() => choose(preset.from, preset.to)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left font-label text-xs font-bold",
                    selected ? "bg-primary-50 text-primary-800" : "text-[#334155] hover:bg-stone-50",
                  )}
                >
                  <span className="flex-1">{preset.label}</span>
                  {"hint" in preset && preset.hint && <span className="font-body text-[10px] font-semibold text-[#64748b]">{preset.hint}</span>}
                  {selected && <Check size={13} className="text-primary-600" />}
                </button>
              );
            })}
          </div>
          <div className="mt-2 border-t border-[#eef2f6] pt-2.5">
            <p className="mb-1.5 px-1 font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">Custom</p>
            <div className="grid grid-cols-2 gap-2">
              <label className="flex flex-col gap-1 font-label text-[10px] font-bold text-[#64748b]">
                From
                <input type="date" value={customFrom} max={customTo || today} onChange={(event) => setCustomFrom(event.target.value)}
                  className="h-8 rounded-lg border border-[#e2e8f0] px-2 font-body text-xs font-semibold text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-200" />
              </label>
              <label className="flex flex-col gap-1 font-label text-[10px] font-bold text-[#64748b]">
                To
                <input type="date" value={customTo} min={customFrom} max={today} onChange={(event) => setCustomTo(event.target.value)}
                  className="h-8 rounded-lg border border-[#e2e8f0] px-2 font-body text-xs font-semibold text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-200" />
              </label>
            </div>
            <button
              type="button"
              disabled={!customFrom || !customTo || customFrom > customTo}
              onClick={() => choose(customFrom, customTo)}
              className="mt-2 flex h-8 w-full items-center justify-center rounded-xl bg-primary font-label text-xs font-bold text-white transition hover:bg-primary/90 disabled:opacity-40"
            >
              Apply
            </button>
          </div>
          <DataFromPicker variant="inline" className="mt-2.5" canManage={canManage} onSaved={onHistorySaved} note={historyNote} />
        </div>
      )}
    </div>
  );
}

export type MoreItem = { label: string; icon: LucideIcon; onClick: () => void; disabled?: boolean; title?: string };

/** "⋯": the less-used actions, so the toolbar stays on one line. */
export function MoreMenu({ items }: { items: MoreItem[] }) {
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));
  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        aria-label="More actions"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((visible) => !visible)}
        className={cn(TOOLBAR_BUTTON, "w-9 px-0")}
      >
        <MoreHorizontal size={16} />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-11 z-30 w-56 rounded-2xl border border-[#e2e8f0] bg-white p-1.5 shadow-xl">
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              title={item.title}
              onClick={() => {
                setOpen(false);
                item.onClick();
              }}
              className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left font-label text-xs font-bold text-[#334155] hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <item.icon size={14} className="text-[#64748b]" />
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * A clickable summary card, Segments-style: selecting it filters the table.
 * Big number on top, three small figures underneath.
 */
export function SummaryCard({
  selected,
  onSelect,
  icon: Icon,
  tint,
  label,
  badge,
  value,
  caption,
  stats,
}: {
  selected: boolean;
  onSelect: () => void;
  icon: LucideIcon;
  tint: string;
  label: string;
  badge: string;
  value: string;
  caption: string;
  stats: { label: string; value: string }[];
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={cn(
        "flex min-w-0 flex-col gap-3.5 rounded-2xl border-2 p-4 text-left transition-all duration-200 sm:p-[18px]",
        selected
          ? "border-primary bg-[#fbfefe] ring-4 ring-primary/10"
          : "border-[#e8edf2] bg-white shadow-sm hover:-translate-y-px hover:border-slate-300 hover:shadow",
      )}
    >
      <span className="flex items-center gap-2.5">
        <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px]", tint)} aria-hidden="true">
          <Icon size={16} />
        </span>
        <span className="min-w-0 flex-1 truncate font-label text-[13px] font-bold text-[#0A1528]">{label}</span>
        <span className={cn(
          "shrink-0 rounded-full px-2 py-0.5 font-label text-[11px] font-bold tabular-nums transition-colors",
          selected ? "bg-primary text-white" : "bg-[#f1f5f9] text-[#475569]",
        )}>
          {badge}
        </span>
      </span>
      <span className="flex items-baseline gap-2">
        <span className="font-display text-[28px] font-extrabold leading-none tracking-tight text-[#0A1528] tabular-nums">{value}</span>
        <span className="font-label text-xs font-semibold text-[#64748b]">{caption}</span>
      </span>
      <span className="grid grid-cols-3 gap-2 border-t border-dashed border-[#e2e8f0] pt-3">
        {stats.map((stat) => (
          <span key={stat.label} className="min-w-0">
            <span className="block truncate font-label text-[10px] font-bold uppercase tracking-wider text-[#64748b]">{stat.label}</span>
            <span className="mt-0.5 block truncate font-label text-[13px] font-bold text-[#0A1528] tabular-nums">{stat.value}</span>
          </span>
        ))}
      </span>
    </button>
  );
}
