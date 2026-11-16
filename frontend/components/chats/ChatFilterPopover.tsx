"use client";
import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { TickMark } from "@/components/ui/controls";
import {
  CAME_FROM_OPTIONS,
  DATE_OPTIONS,
  EMPTY_FILTERS,
  INTEREST_OPTIONS,
  RESULT_OPTIONS,
  WAITING_OPTIONS,
  activeFilterCount,
  type InboxFilters,
  type Option,
} from "./inboxFilters";

const INTEREST_DOT: Record<string, string> = {
  A: "bg-orange-500",
  B: "bg-amber-400",
  C: "bg-sky-500",
  D: "bg-slate-400",
};

type GroupKey = "segments" | "results" | "waiting" | "handledBy" | "cameFrom" | "date" | "tag";

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/** One option row with the dashboard's round tick. `round` marks a pick-one group (radio). */
function TickRow({
  checked,
  onClick,
  label,
  round = false,
  dot,
}: {
  checked: boolean;
  onClick: () => void;
  label: string;
  round?: boolean;
  dot?: string;
}) {
  return (
    <button
      type="button"
      role={round ? "radio" : "checkbox"}
      aria-checked={checked}
      onClick={onClick}
      className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-left text-[13px] font-semibold text-[#0A1528] transition-colors hover:bg-[#f8fafc] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
    >
      <TickMark checked={checked} size="sm" />
      {dot && <span className={cn("h-2 w-2 shrink-0 rounded-full", dot)} />}
      <span className="min-w-0 truncate">{label}</span>
    </button>
  );
}

/**
 * The Chats page's Filter panel. Every group is in one list of ticks, so one click picks an option;
 * the left side only jumps to a group. A tick applies straight away (the list behind updates), so
 * there is no "apply" step, and the footer shows how many chats match.
 */
export function ChatFilterPopover({
  open,
  value,
  onChange,
  onClose,
  countFor,
  team,
  tags,
}: {
  open: boolean;
  value: InboxFilters;
  onChange: (next: InboxFilters) => void;
  onClose: () => void;
  countFor: (filters: InboxFilters) => Promise<number>;
  team: Option[];
  tags: Option[];
}) {
  const [count, setCount] = useState<number | null>(null);
  const [current, setCurrent] = useState<GroupKey>("segments");
  const panelRef = useRef<HTMLDivElement>(null);
  const paneRef = useRef<HTMLDivElement>(null);
  const sectionRefs = useRef<Partial<Record<GroupKey, HTMLElement | null>>>({});

  // How many chats match what's ticked, debounced so quick ticks are one request.
  useEffect(() => {
    if (!open) return;
    let live = true;
    setCount(null);
    const handle = setTimeout(() => {
      countFor(value).then((n) => live && setCount(n)).catch(() => live && setCount(-1));
    }, 250);
    return () => {
      live = false;
      clearTimeout(handle);
    };
  }, [open, value, countFor]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    function onDown(e: MouseEvent) {
      const target = e.target as HTMLElement;
      if (panelRef.current && !panelRef.current.contains(target) && !target.closest?.("[data-filter-trigger]")) onClose();
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open, onClose]);

  if (!open) return null;

  const set = (patch: Partial<InboxFilters>) => onChange({ ...value, ...patch });
  const on = activeFilterCount(value);
  const handledOptions: Option[] = [{ value: "ai", label: "AI agent" }, ...team, { value: "nobody", label: "Nobody yet" }];

  const groups: { key: GroupKey; label: string; picked: number }[] = [
    { key: "segments", label: "Interest", picked: value.segments.length },
    { key: "results", label: "Result", picked: value.results.length },
    { key: "waiting", label: "Waiting", picked: value.waiting.length },
    { key: "handledBy", label: "Handled by", picked: value.handledBy.length },
    { key: "cameFrom", label: "Came from", picked: value.cameFrom.length },
    { key: "date", label: "Last message", picked: value.date !== "any" ? 1 : 0 },
    { key: "tag", label: "Tag", picked: value.tagId ? 1 : 0 },
  ];

  function jumpTo(key: GroupKey) {
    setCurrent(key);
    const pane = paneRef.current;
    const el = sectionRefs.current[key];
    if (pane && el) pane.scrollTo({ top: el.offsetTop - 4, behavior: "smooth" });
  }

  // Keep the left side in step with whichever group is at the top of the list.
  function onPaneScroll() {
    const pane = paneRef.current;
    if (!pane) return;
    if (pane.scrollTop + pane.clientHeight >= pane.scrollHeight - 4) {
      setCurrent(groups[groups.length - 1].key);
      return;
    }
    let best: GroupKey = groups[0].key;
    for (const g of groups) {
      const el = sectionRefs.current[g.key];
      if (el && el.offsetTop - 24 <= pane.scrollTop) best = g.key;
    }
    setCurrent(best);
  }

  const section = (key: GroupKey, title: string, children: React.ReactNode) => (
    <section
      key={key}
      ref={(el) => { sectionRefs.current[key] = el; }}
      aria-label={title}
      className="pb-2"
    >
      <h4 className="px-2.5 pb-1 pt-2 font-label text-[10.5px] font-bold uppercase tracking-[0.08em] text-[#64748b]">{title}</h4>
      {children}
    </section>
  );

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-label="Filter chats"
      className={cn(
        "z-dialog flex flex-col overflow-hidden bg-white shadow-[0_24px_60px_-12px_rgba(10,21,40,0.28)] ring-1 ring-[#e2e8f0] md:z-40",
        // Phones: a sheet over the list. Larger screens: a panel under the button, wider than the list.
        "fixed inset-x-3 bottom-3 top-24 rounded-2xl",
        "md:absolute md:inset-auto md:left-4 md:top-[calc(100%+6px)] md:h-[440px] md:max-h-[calc(100dvh-180px)] md:w-[460px]"
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-[#eef1f5] px-4 py-3">
        <h3 className="font-display text-[15px] font-bold text-[#0A1528]">Filter chats</h3>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => onChange(EMPTY_FILTERS)}
            disabled={on === 0}
            className="whitespace-nowrap rounded-lg px-2.5 py-1.5 text-[12.5px] font-semibold text-primary hover:bg-primary-light disabled:cursor-default disabled:text-slate-300 disabled:hover:bg-transparent"
          >
            Clear all
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-[#64748b] hover:bg-slate-100 hover:text-[#0A1528]"
          >
            <X size={18} />
          </button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[132px_minmax(0,1fr)] sm:grid-cols-[148px_minmax(0,1fr)]">
        {/* Jump list: shows where you are and how many are ticked in each group. */}
        <nav aria-label="Filter groups" className="flex flex-col gap-0.5 overflow-y-auto border-r border-[#eef1f5] bg-[#fbfcfd] p-2">
          {groups.map((g) => (
            <button
              key={g.key}
              type="button"
              aria-current={current === g.key}
              onClick={() => jumpTo(g.key)}
              className={cn(
                "flex w-full items-center justify-between gap-1.5 rounded-lg px-2.5 py-2 text-left text-[12.5px] transition-colors",
                current === g.key ? "bg-primary-light font-bold text-primary" : "font-semibold text-[#334155] hover:bg-[#f1f5f9]"
              )}
            >
              <span className="truncate">{g.label}</span>
              {g.picked > 0 && (
                <span className="flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-primary px-1 text-[10.5px] font-bold text-white">
                  {g.picked}
                </span>
              )}
            </button>
          ))}
        </nav>

        {/* Every option, one tick away. */}
        <div ref={paneRef} onScroll={onPaneScroll} className="relative overflow-y-auto px-2 pb-3 pt-1">
          {section("segments", "Interest",
            INTEREST_OPTIONS.map((o) => (
              <TickRow key={o.value} label={o.label} dot={INTEREST_DOT[o.value]} checked={value.segments.includes(o.value)}
                onClick={() => set({ segments: toggle(value.segments, o.value) })} />
            )))}
          {section("results", "Result",
            RESULT_OPTIONS.map((o) => (
              <TickRow key={o.value} label={o.label} checked={value.results.includes(o.value)}
                onClick={() => set({ results: toggle(value.results, o.value) })} />
            )))}
          {section("waiting", "Waiting",
            WAITING_OPTIONS.map((o) => (
              <TickRow key={o.value} label={o.label} checked={value.waiting.includes(o.value)}
                onClick={() => set({ waiting: toggle(value.waiting, o.value) })} />
            )))}
          {section("handledBy", "Handled by",
            handledOptions.map((o) => (
              <TickRow key={o.value} label={o.label} checked={value.handledBy.includes(o.value)}
                onClick={() => set({ handledBy: toggle(value.handledBy, o.value) })} />
            )))}
          {section("cameFrom", "Came from",
            CAME_FROM_OPTIONS.map((o) => (
              <TickRow key={o.value} label={o.label} checked={value.cameFrom.includes(o.value)}
                onClick={() => set({ cameFrom: toggle(value.cameFrom, o.value) })} />
            )))}
          {section("date", "Last message",
            <>
              {DATE_OPTIONS.map((o) => (
                <TickRow key={o.value} round label={o.label} checked={value.date === o.value}
                  onClick={() => set({ date: o.value })} />
              ))}
              {value.date === "custom" && (
                <div className="px-2.5 pb-1 pt-1">
                  <input
                    type="date"
                    aria-label="From date"
                    value={value.customFrom}
                    max={new Date().toISOString().slice(0, 10)}
                    onChange={(e) => set({ customFrom: e.target.value })}
                    className="h-9 w-full rounded-lg border border-[#e2e8f0] px-2.5 text-[12.5px] text-[#0A1528] focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                  />
                </div>
              )}
            </>
          )}
          {section("tag", "Tag",
            tags.length === 0 ? (
              <p className="px-2.5 py-1 text-[12px] text-[#94a3b8]">No tags yet.</p>
            ) : (
              [{ value: "", label: "Any tag" }, ...tags].map((o) => (
                <TickRow key={o.value || "any"} round label={o.label} checked={value.tagId === o.value}
                  onClick={() => set({ tagId: o.value })} />
              ))
            )
          )}
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-[#eef1f5] bg-[#fbfcfd] px-4 py-2.5">
        <span className="text-[12.5px] text-[#64748b]" aria-live="polite">
          {count === null ? "Counting…" : count < 0 ? "Couldn't count" : (
            <><span className="font-bold text-[#0A1528]">{count.toLocaleString("en-IN")}</span> chat{count === 1 ? "" : "s"} match</>
          )}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="h-9 rounded-xl bg-primary px-5 text-[13px] font-bold text-white shadow-sm hover:bg-[var(--primary-900)]"
        >
          Done
        </button>
      </div>
    </div>
  );
}
