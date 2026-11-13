"use client";

import { Select } from "@/components/ui/Select";

export type Preset =
  | "today" | "yesterday"
  | "last_7d" | "last_14d" | "last_30d"
  | "custom";

export type RangeValue = { preset: Preset; start: string; end: string };

const PRESET_OPTIONS: { id: Preset; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "last_7d", label: "7 days" },
  { id: "last_14d", label: "14 days" },
  { id: "last_30d", label: "30 days" },
  { id: "custom", label: "Custom" },
];

export function RangePicker({
  value,
  onChange,
  idPrefix = "range",
}: {
  value: RangeValue;
  onChange: (v: RangeValue) => void;
  idPrefix?: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        size="sm"
        aria-label="Date range"
        className="h-9 w-[140px] shrink-0"
        value={value.preset}
        onChange={(v) => onChange({ ...value, preset: v as Preset })}
        options={PRESET_OPTIONS.map((option) => ({ value: option.id, label: option.label }))}
      />

      {value.preset === "custom" && (
        <>
          <input
            id={`${idPrefix}-from`}
            type="date"
            aria-label="From"
            value={value.start}
            max={value.end || undefined}
            onChange={(e) => onChange({ ...value, start: e.target.value })}
            className="h-9 w-[122px] shrink-0 rounded-xl border border-surface-mid bg-white px-2.5 font-body text-xs font-semibold text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-200"
          />
          <span className="font-label text-xs text-on-surface-muted">→</span>
          <input
            id={`${idPrefix}-to`}
            type="date"
            aria-label="To"
            value={value.end}
            min={value.start || undefined}
            onChange={(e) => onChange({ ...value, end: e.target.value })}
            className="h-9 w-[122px] shrink-0 rounded-xl border border-surface-mid bg-white px-2.5 font-body text-xs font-semibold text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-200"
          />
        </>
      )}
    </div>
  );
}
