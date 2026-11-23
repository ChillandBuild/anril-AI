"use client";
import { PERIODS, type Period } from "@/lib/aiSetupApi";

export function PeriodPicker({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  return (
    <div role="group" aria-label="Period" className="flex flex-wrap gap-1.5">
      {PERIODS.map((p) => (
        <button
          key={p.value}
          type="button"
          aria-pressed={value === p.value}
          onClick={() => onChange(p.value)}
          className={`min-h-9 rounded-full border px-3 font-label text-xs font-bold ${
            value === p.value ? "border-primary bg-primary text-white" : "border-border-subtle bg-white text-ink hover:border-primary/40"
          }`}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}
