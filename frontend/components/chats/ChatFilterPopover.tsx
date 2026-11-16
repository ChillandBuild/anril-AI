"use client";
import { useEffect, useRef, useState } from "react";
import { Check, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Select } from "@/components/ui/Select";
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

function Chip({
  selected,
  onClick,
  children,
  dot,
}: {
  selected: boolean;
  onClick: () => void;
  children: React.ReactNode;
  dot?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12.5px] font-semibold transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30",
        selected
          ? "border-primary/40 bg-primary-light text-primary"
          : "border-[#e2e8f0] bg-white text-[#334155] hover:border-slate-300 hover:bg-[#f8fafc]"
      )}
    >
      {selected ? <Check size={13} strokeWidth={2.75} /> : dot ? <span className={cn("h-2 w-2 rounded-full", dot)} /> : null}
      {children}
    </button>
  );
}

function Group({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <fieldset className={cn("min-w-0", className)}>
      <legend className="mb-2 font-label text-[10.5px] font-bold uppercase tracking-[0.08em] text-[#64748b]">{title}</legend>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </fieldset>
  );
}

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/**
 * The Chats page's Filter panel. Changes stay a draft until "Show N chats"; N is the server's
 * exact count for the draft, so the button always tells the truth about what you'll get.
 */
export function ChatFilterPopover({
  open,
  value,
  onApply,
  onClose,
  countFor,
  team,
  tags,
}: {
  open: boolean;
  value: InboxFilters;
  onApply: (next: InboxFilters) => void;
  onClose: () => void;
  countFor: (draft: InboxFilters) => Promise<number>;
  team: Option[];
  tags: Option[];
}) {
  const [draft, setDraft] = useState<InboxFilters>(value);
  const [count, setCount] = useState<number | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) setDraft(value);
  }, [open, value]);

  // Live count for the draft, debounced so ticking three chips is one request.
  useEffect(() => {
    if (!open) return;
    let live = true;
    setCount(null);
    const handle = setTimeout(() => {
      countFor(draft).then((n) => live && setCount(n)).catch(() => live && setCount(-1));
    }, 250);
    return () => {
      live = false;
      clearTimeout(handle);
    };
  }, [open, draft, countFor]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    function onDown(e: MouseEvent) {
      const target = e.target as HTMLElement;
      // Radix Select menus render in a portal outside the panel; clicks there are not "outside".
      if (target.closest?.("[data-radix-popper-content-wrapper]")) return;
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

  const set = (patch: Partial<InboxFilters>) => setDraft((d) => ({ ...d, ...patch }));
  const on = activeFilterCount(draft);

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-label="Filter chats"
      className={cn(
        "z-dialog md:z-40 flex flex-col overflow-hidden bg-white shadow-[0_24px_60px_-12px_rgba(10,21,40,0.28)] ring-1 ring-[#e2e8f0]",
        // Phones: a sheet over the list. Larger screens: a panel under the button, wider than the list.
        "fixed inset-x-3 bottom-3 top-24 rounded-2xl",
        "md:absolute md:inset-auto md:left-4 md:top-[calc(100%+6px)] md:max-h-[min(640px,calc(100dvh-180px))] md:w-[600px]"
      )}
    >
      <div className="flex items-center justify-between border-b border-[#eef1f5] px-5 py-3.5">
        <div>
          <h3 className="font-display text-[15px] font-bold text-[#0A1528]">Filter chats</h3>
          <p className="text-[11.5px] text-[#64748b]">Pick more than one in a group to see any of them.</p>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setDraft(EMPTY_FILTERS)}
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

      <div className="grid flex-1 grid-cols-1 gap-x-8 gap-y-5 overflow-y-auto px-5 py-4 md:grid-cols-2">
        <Group title="Interest">
          {INTEREST_OPTIONS.map((o) => (
            <Chip key={o.value} dot={INTEREST_DOT[o.value]} selected={draft.segments.includes(o.value)}
              onClick={() => set({ segments: toggle(draft.segments, o.value) })}>
              {o.label}
            </Chip>
          ))}
        </Group>

        <Group title="Result">
          {RESULT_OPTIONS.map((o) => (
            <Chip key={o.value} selected={draft.results.includes(o.value)}
              onClick={() => set({ results: toggle(draft.results, o.value) })}>
              {o.label}
            </Chip>
          ))}
        </Group>

        <Group title="Waiting">
          {WAITING_OPTIONS.map((o) => (
            <Chip key={o.value} selected={draft.waiting.includes(o.value)}
              onClick={() => set({ waiting: toggle(draft.waiting, o.value) })}>
              {o.label}
            </Chip>
          ))}
        </Group>

        <Group title="Handled by">
          {[{ value: "ai", label: "AI agent" }, ...team, { value: "nobody", label: "Nobody yet" }].map((o) => (
            <Chip key={o.value} selected={draft.handledBy.includes(o.value)}
              onClick={() => set({ handledBy: toggle(draft.handledBy, o.value) })}>
              {o.label}
            </Chip>
          ))}
        </Group>

        <Group title="Came from" className="md:col-span-2">
          {CAME_FROM_OPTIONS.map((o) => (
            <Chip key={o.value} selected={draft.cameFrom.includes(o.value)}
              onClick={() => set({ cameFrom: toggle(draft.cameFrom, o.value) })}>
              {o.label}
            </Chip>
          ))}
        </Group>

        <Group title="Last message">
          {DATE_OPTIONS.map((o) => (
            <Chip key={o.value} selected={draft.date === o.value} onClick={() => set({ date: o.value })}>
              {o.label}
            </Chip>
          ))}
          {draft.date === "custom" && (
            <input
              type="date"
              aria-label="From date"
              value={draft.customFrom}
              max={new Date().toISOString().slice(0, 10)}
              onChange={(e) => set({ customFrom: e.target.value })}
              className="h-8 rounded-lg border border-[#e2e8f0] px-2.5 text-[12.5px] text-[#0A1528] focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          )}
        </Group>

        <fieldset className="min-w-0">
          <legend className="mb-2 font-label text-[10.5px] font-bold uppercase tracking-[0.08em] text-[#64748b]">Tag</legend>
          <Select
            size="sm"
            value={draft.tagId}
            onChange={(v) => set({ tagId: v })}
            aria-label="Tag"
            options={[{ value: "", label: "Any tag" }, ...tags]}
          />
        </fieldset>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-[#eef1f5] bg-[#fbfcfd] px-5 py-3">
        <span className="text-[12px] text-[#64748b]">
          {on === 0 ? "No filters on" : `${on} filter${on === 1 ? "" : "s"} on`}
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onClose}
            className="h-9 rounded-xl border border-[#e2e8f0] bg-white px-4 text-[13px] font-semibold text-[#334155] hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onApply(draft)}
            className="inline-flex h-9 min-w-[132px] items-center justify-center gap-2 rounded-xl bg-primary px-4 text-[13px] font-bold text-white shadow-sm hover:bg-primary/90"
          >
            {count === null ? (
              <>
                <Loader2 size={14} className="animate-spin" /> Counting…
              </>
            ) : count < 0 ? (
              "Show chats"
            ) : (
              `Show ${count.toLocaleString("en-IN")} chat${count === 1 ? "" : "s"}`
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
