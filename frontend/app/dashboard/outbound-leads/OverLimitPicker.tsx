"use client";
import { useMemo, useState } from "react";
import { AlertTriangle, ChevronDown, Search } from "lucide-react";
import { TickMark } from "@/components/ui/controls";
import { cn, formatPhone } from "@/lib/utils";
import { matchPeople, toggleAll, weekRangeLabel, type OverLimitPerson } from "./overLimit";

const MAX_ROWS = 200;

type Props = {
  people: OverLimitPerson[];
  limit: number;
  weekStart: string;
  weekEnd: string;
  picked: Set<string>;
  onChange: (next: Set<string>) => void;
};

// People who already got this week's broadcasts. Skipped unless picked here.
export function OverLimitPicker({ people, limit, weekStart, weekEnd, picked, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const shown = useMemo(() => matchPeople(people, query), [people, query]);
  const drawn = shown.length > MAX_ROWS ? shown.slice(0, MAX_ROWS) : shown;
  const pickedInShown = useMemo(() => shown.reduce((n, p) => n + (picked.has(p.phone) ? 1 : 0), 0), [shown, picked]);
  const allPicked = shown.length > 0 && pickedInShown === shown.length;
  const somePicked = pickedInShown > 0 && !allPicked;

  if (people.length === 0) return null;
  const n = people.length;

  function toggleOne(phone: string) {
    const next = new Set(picked);
    if (next.has(phone)) next.delete(phone);
    else next.add(phone);
    onChange(next);
  }

  return (
    <div className="rounded-xl border border-orange-200 bg-orange-50/70 p-3 space-y-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2 text-orange-900 font-body text-sm">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span>
            {n.toLocaleString()} {n === 1 ? "person" : "people"} already got {limit} {limit === 1 ? "broadcast" : "broadcasts"} this week
            {" "}({weekRangeLabel(weekStart, weekEnd)}). They&apos;ll be skipped unless you pick them.
          </span>
        </div>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="flex shrink-0 items-center gap-1 rounded-lg border border-orange-200 bg-white/80 px-2.5 py-1 font-label text-xs font-semibold text-orange-900 hover:bg-white"
        >
          {open ? "Hide" : `Show ${n.toLocaleString()} ${n === 1 ? "person" : "people"}`}
          <ChevronDown size={12} className={cn("transition-transform", open && "rotate-180")} />
        </button>
      </div>

      {open && (
        <div className="space-y-2">
          <div className="relative">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-orange-700/70" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name or number"
              aria-label="Search people over the weekly limit"
              className="h-10 w-full rounded-lg border border-orange-200 bg-white pl-9 pr-3 font-body text-sm text-on-surface placeholder:text-on-surface-muted focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
          </div>

          <button
            type="button"
            role="checkbox"
            aria-checked={allPicked ? true : somePicked ? "mixed" : false}
            disabled={shown.length === 0}
            onClick={() => onChange(toggleAll(picked, shown, !allPicked))}
            className="flex select-none items-center gap-2.5 text-left disabled:opacity-50"
          >
            <TickMark checked={allPicked} indeterminate={somePicked} size="sm" />
            <span className="font-body text-sm text-orange-900">
              Select all · {pickedInShown.toLocaleString()} of {shown.length.toLocaleString()} picked
            </span>
          </button>

          <div role="group" aria-label="People over this week's limit" className="max-h-64 overflow-y-auto rounded-lg border border-orange-200 bg-white/80 divide-y divide-orange-100">
            {drawn.length === 0 ? (
              <p className="p-3 font-body text-sm text-on-surface-muted">No one matches that search.</p>
            ) : (
              drawn.map((p) => (
                <button
                  key={p.phone}
                  type="button"
                  role="checkbox"
                  aria-checked={picked.has(p.phone)}
                  onClick={() => toggleOne(p.phone)}
                  className="flex w-full select-none items-center gap-2.5 px-3 py-2 text-left hover:bg-orange-50"
                >
                  <TickMark checked={picked.has(p.phone)} size="sm" />
                  <span className="min-w-0 flex-1 truncate font-body text-sm text-on-surface">{p.name || "—"}</span>
                  <span className="shrink-0 font-body text-xs tabular-nums text-on-surface-muted">{formatPhone(`+${p.phone}`)}</span>
                  <span className="shrink-0 font-label text-xs text-orange-900">{p.this_week} this week</span>
                </button>
              ))
            )}
          </div>

          {shown.length > MAX_ROWS && (
            <p className="font-body text-xs text-orange-900/80">
              Showing {MAX_ROWS} of {shown.length.toLocaleString()} — search to find others
            </p>
          )}
        </div>
      )}
    </div>
  );
}
