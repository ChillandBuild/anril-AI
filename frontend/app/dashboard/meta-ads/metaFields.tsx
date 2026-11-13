"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Columns3, RotateCcw, Search, SlidersHorizontal } from "lucide-react";
import type { MetaBreakdown, MetaField } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Select } from "@/components/ui/Select";
import { TickMark } from "@/components/ui/controls";
import { fieldHelp } from "./metaFieldHelp";
import { HoverTip } from "./HoverTip";

const MISSING = "—";

function toNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/** "ABOVE_AVERAGE" -> "Above average". Meta enums come back shouting and underscored.
 * Anything else (an ad's headline or primary text) is shown exactly as written. */
function humanize(raw: string): string {
  if (!/^[A-Z0-9_]+$/.test(raw.trim())) return raw;
  // Ad relevance rankings: BELOW_AVERAGE_35 means the bottom 35% of ads.
  const bottom = raw.trim().match(/^BELOW_AVERAGE_(\d+)$/);
  if (bottom) return `Below average (bottom ${bottom[1]}%)`;
  const text = raw.replaceAll("_", " ").trim().toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The words Ads Manager's Delivery column uses for Meta's effective_status.
 * Mirrors DELIVERY_LABELS in backend/app/services/ad_performance.py (the CSV export). */
const DELIVERY_LABELS: Record<string, string> = {
  ACTIVE: "Active",
  PAUSED: "Off",
  ADSET_PAUSED: "Ad set off",
  CAMPAIGN_PAUSED: "Campaign off",
  ARCHIVED: "Archived",
  DELETED: "Deleted",
  PENDING_REVIEW: "In review",
  DISAPPROVED: "Rejected",
  PREAPPROVED: "Approved",
  PENDING_BILLING_INFO: "Billing issue",
  WITH_ISSUES: "Has issues",
  IN_PROCESS: "Processing",
};

/** "ADSET_PAUSED" -> "Ad set off". An unknown status is tidied up, never hidden. */
export function deliveryLabel(status: unknown): string {
  if (typeof status !== "string" || !status.trim()) return "";
  const key = status.trim().toUpperCase();
  return DELIVERY_LABELS[key] ?? humanize(key);
}

/** Under ₹100 keep paise (the per-unit costs read better); above that, whole rupees. */
function formatRupees(amount: number): string {
  const digits = Math.abs(amount) < 100 ? 2 : 0;
  return "₹" + amount.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Budgets arrive as {amount, type, level}: "₹500/day · Ad set" or "₹20,000 lifetime · Campaign". */
function formatBudget(value: Record<string, unknown>): string | null {
  const amount = toNumber(value.amount);
  if (amount === null) return null;
  const type = typeof value.type === "string" ? value.type.toLowerCase() : "";
  const level = typeof value.level === "string" && value.level ? ` · ${humanize(value.level)}` : "";
  const base = type === "lifetime" ? `${formatRupees(amount)} lifetime` : `${formatRupees(amount)}/day`;
  return base + level;
}

/** Renders one Meta value for its catalogue format. Anything missing shows an em dash. */
export function formatMetaValue(value: unknown, format: MetaField["format"]): ReactNode {
  if (value === null || value === undefined || value === "") return MISSING;
  switch (format) {
    case "number": {
      const parsed = toNumber(value);
      return parsed === null ? MISSING : Math.round(parsed).toLocaleString("en-IN");
    }
    case "money": {
      if (typeof value === "object" && !Array.isArray(value)) {
        return formatBudget(value as Record<string, unknown>) ?? MISSING;
      }
      const parsed = toNumber(value);
      return parsed === null ? MISSING : formatRupees(parsed);
    }
    case "percent": {
      const parsed = toNumber(value);
      return parsed === null ? MISSING : `${parsed.toFixed(2)}%`;
    }
    case "decimal": {
      const parsed = toNumber(value);
      return parsed === null ? MISSING : parsed.toFixed(2);
    }
    case "date": {
      const parsed = new Date(`${String(value).slice(0, 10)}T00:00:00`);
      return Number.isNaN(parsed.getTime())
        ? String(value)
        : parsed.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
    }
    case "image":
      return (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={String(value)}
          alt=""
          width={40}
          height={40}
          className="h-10 w-10 rounded-lg object-cover ring-1 ring-stone-200"
        />
      );
    case "text":
    default:
      if (Array.isArray(value)) return value.map((item) => humanize(String(item))).join(", ");
      if (typeof value === "object") return MISSING;
      return humanize(String(value));
  }
}

/**
 * Column visibility persisted per browser under `storageKey`. Starts on the
 * defaults so the server render and first client render agree, then loads the
 * saved choice. Storage can be blocked (private mode), so every access is guarded.
 */
export function usePersistedColumns(storageKey: string, defaults: string[]): [string[], (keys: string[]) => void] {
  const [selected, setSelected] = useState<string[]>(defaults);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (!raw) return;
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.every((key) => typeof key === "string")) {
        setSelected(parsed as string[]);
      }
    } catch {
      // Unreadable or blocked storage: keep the defaults.
    }
  }, [storageKey]);

  const update = useCallback(
    (keys: string[]) => {
      setSelected(keys);
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(keys));
      } catch {
        // Storage unavailable: the choice still applies for this visit.
      }
    },
    [storageKey],
  );

  return [selected, update];
}

export function MetaColumnPicker({
  fields,
  selected,
  onChange,
  defaultKeys,
  extraSections,
}: {
  fields: MetaField[];
  selected: string[];
  onChange: (keys: string[]) => void;
  defaultKeys: string[];
  extraSections?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const catalogKeys = useMemo(() => new Set(fields.map((field) => field.key)), [fields]);
  const selectedCount = useMemo(() => selected.filter((key) => catalogKeys.has(key)).length, [selected, catalogKeys]);

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const byGroup = new Map<string, MetaField[]>();
    for (const field of fields) {
      if (needle && !field.label.toLowerCase().includes(needle) && !field.key.toLowerCase().includes(needle)) continue;
      const list = byGroup.get(field.group) ?? [];
      list.push(field);
      byGroup.set(field.group, list);
    }
    return Array.from(byGroup.entries());
  }, [fields, query]);

  function toggle(key: string) {
    onChange(selectedSet.has(key) ? selected.filter((item) => item !== key) : [...selected, key]);
  }

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={() => setOpen((visible) => !visible)}
        aria-expanded={open}
        aria-haspopup="dialog"
        className="flex h-9 items-center justify-center gap-2 rounded-xl border border-primary-200 bg-white px-3 py-2 font-label text-xs font-bold text-primary-700 shadow-sm transition-all hover:bg-primary-50"
      >
        <Columns3 size={13} /> Columns
        <span className="rounded-full bg-primary-100 px-1.5 py-0.5 text-[9px]">{selectedCount}</span>
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Customize columns"
          className="absolute right-0 top-11 z-30 flex max-h-[26rem] w-[340px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-[#e2e8f0] bg-white p-3 shadow-xl"
        >
          <div className="mb-2 flex items-center gap-2 border-b border-[#eee9e1] px-1 pb-2">
            <SlidersHorizontal size={13} className="text-primary-600" />
            <span className="font-label text-xs font-bold text-[#13284A]">Customize columns</span>
          </div>
          <div className="relative mb-2">
            <Search size={12} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search columns"
              aria-label="Search columns"
              className="h-8 w-full rounded-xl border border-surface-mid bg-white pl-8 pr-3 font-body text-xs font-semibold text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200"
            />
          </div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain pr-1">
            {extraSections}
            {groups.map(([group, list]) => (
              <div key={group}>
                <p className="px-2 pb-1 pt-2 font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">
                  {group.replaceAll("_", " ")}
                </p>
                {list.map((field) => (
                  <button
                    key={field.key}
                    type="button"
                    role="checkbox"
                    aria-checked={selectedSet.has(field.key)}
                    onClick={() => toggle(field.key)}
                    className="flex w-full items-center gap-2 rounded-xl px-2 py-2 text-left hover:bg-stone-50"
                  >
                    <TickMark checked={selectedSet.has(field.key)} size="sm" />
                    <HoverTip text={fieldHelp(field)} side="bottom" focusable={false}>
                      <span className="block font-label text-[11px] font-bold text-stone-700">{field.label}</span>
                    </HoverTip>
                  </button>
                ))}
              </div>
            ))}
            {groups.length === 0 && (
              <p className="px-2 py-6 text-center font-body text-[11px] text-stone-400">No columns match “{query.trim()}”.</p>
            )}
          </div>
          <div className="mt-2 flex justify-end border-t border-[#eee9e1] pt-2">
            <button
              type="button"
              onClick={() => onChange([...defaultKeys])}
              className="flex items-center gap-1 rounded-lg px-2 py-1 font-label text-[10px] font-bold text-primary-600 hover:bg-primary-50 hover:text-primary-800"
            >
              <RotateCcw size={10} /> Reset to default
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function BreakdownSelect({
  breakdowns,
  value,
  onChange,
}: {
  breakdowns: MetaBreakdown[];
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  return (
    <div className="flex shrink-0 items-center gap-2">
      <span className="font-label text-xs font-bold text-[#0A1528]">Breakdown</span>
      <Select
        size="sm"
        value={value ?? ""}
        onChange={(v) => onChange(v || null)}
        aria-label="Break down by"
        className="w-[9rem]"
        options={[
          { value: "", label: "None" },
          ...breakdowns.map((breakdown) => ({ value: breakdown.key, label: breakdown.label })),
        ]}
      />
    </div>
  );
}

export function AdTypeBadge({ type }: { type: string }) {
  const key = type.trim().toLowerCase();
  const isMulti = key === "multi-destination";
  const tone =
    key === "whatsapp"
      ? "bg-emerald-50 text-emerald-700"
      : isMulti
        ? "bg-amber-50 text-amber-700"
        : key === "instant form"
          ? "bg-violet-50 text-violet-700"
          : key === "website"
            ? "bg-sky-50 text-sky-700"
            : "bg-stone-100 text-stone-600";
  return (
    <span
      title={isMulti ? "Includes Messenger and Instagram — Meta's numbers cover every destination" : undefined}
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-1 font-label text-[10px] font-bold",
        tone,
      )}
    >
      {type}
    </span>
  );
}

const CHANNEL_CHIPS: Record<string, { label: string; tone: string }> = {
  whatsapp: { label: "WhatsApp", tone: "bg-emerald-50 text-emerald-700" },
  instagram: { label: "Instagram", tone: "bg-rose-50 text-rose-700" },
  messenger: { label: "Messenger", tone: "bg-sky-50 text-sky-700" },
};

/** One tiny pill per chat app an ad opens. Renders nothing for an empty list. */
export function ChannelChips({ channels }: { channels: string[] }) {
  const chips = channels.map((channel) => CHANNEL_CHIPS[channel]).filter(Boolean);
  if (chips.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {chips.map((chip) => (
        <span
          key={chip.label}
          className={cn(
            "inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 font-label text-[9px] font-bold",
            chip.tone,
          )}
        >
          {chip.label}
        </span>
      ))}
    </span>
  );
}

/** Chat-app chips for an ad; the old Multi-destination badge only when no channel list came back. */
export function ChannelMarks({ channels, multiDestination }: { channels?: string[]; multiDestination?: boolean }) {
  if (channels && channels.length > 0) return <ChannelChips channels={channels} />;
  return multiDestination ? <AdTypeBadge type="Multi-destination" /> : null;
}
