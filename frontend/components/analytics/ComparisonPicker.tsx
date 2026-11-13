"use client";

import { Select } from "@/components/ui/Select";
import { ComparisonSelection } from "./periodSelection";

export function comparisonLabel(selection: ComparisonSelection): string {
  if (selection.mode === "off") return "No comparison";
  if (selection.mode === "previous") return "Previous period";
  if (selection.start && selection.end) return `${selection.start} → ${selection.end}`;
  return "Custom comparison";
}

export function ComparisonPicker({
  value,
  onChange,
}: {
  value: ComparisonSelection;
  onChange: (value: ComparisonSelection) => void;
}) {
  const selectMode = (mode: ComparisonSelection["mode"]) => {
    onChange({ ...value, mode });
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        size="sm"
        aria-label="Comparison"
        className="h-9 w-[150px] shrink-0"
        value={value.mode}
        onChange={(v) => selectMode(v as ComparisonSelection["mode"])}
        options={[
          { value: "off", label: "Off" },
          { value: "previous", label: "Previous period" },
          { value: "custom", label: "Custom" },
        ]}
      />

      {value.mode === "custom" && (
        <>
          <input
            id="comparison-range-from"
            type="date"
            aria-label="From"
            value={value.start}
            max={value.end || undefined}
            onChange={(e) => onChange({ mode: "custom", start: e.target.value, end: value.end })}
            className="h-9 w-[122px] shrink-0 rounded-xl border border-surface-mid bg-white px-2.5 font-body text-xs font-semibold text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-200"
          />
          <span className="font-label text-xs text-on-surface-muted">→</span>
          <input
            id="comparison-range-to"
            type="date"
            aria-label="To"
            value={value.end}
            min={value.start || undefined}
            onChange={(e) => onChange({ mode: "custom", start: value.start, end: e.target.value })}
            className="h-9 w-[122px] shrink-0 rounded-xl border border-surface-mid bg-white px-2.5 font-body text-xs font-semibold text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-200"
          />
        </>
      )}
    </div>
  );
}
