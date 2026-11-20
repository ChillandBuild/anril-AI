"use client";

import { useState } from "react";
import { Plus, X } from "lucide-react";

/** Sizes and colours chips for the item page (each size/colour keeps its own stock, migration 294). */
export const cellKey = (size: string | null, colour: string | null) => `${size ?? ""}|${colour ?? ""}`;

export const SIZE_PRESETS: { label: string; values: string[] }[] = [
  { label: "S M L XL", values: ["S", "M", "L", "XL"] },
  { label: "Free size", values: ["Free size"] },
  { label: "2-8 yrs", values: ["2-4 yrs", "4-6 yrs", "6-8 yrs"] },
];

export function ChipInput({ label, values, onChange, placeholder, presets }: {
  label: string; values: string[]; onChange: (v: string[]) => void; placeholder: string; presets?: { label: string; values: string[] }[];
}) {
  const [text, setText] = useState("");
  function add(raw: string) {
    const parts = raw.split(",").map((p) => p.trim()).filter(Boolean);
    const next = [...values];
    for (const p of parts) if (!next.some((v) => v.toLowerCase() === p.toLowerCase()) && next.length < 20) next.push(p.slice(0, 30));
    onChange(next);
    setText("");
  }
  return (
    <div>
      <p className="mb-1 text-[11px] font-semibold uppercase text-ink-muted">{label}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        {values.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 rounded-full border border-primary/40 bg-primary-50 px-2.5 py-1 text-xs font-bold text-primary-800">
            {v}
            <button type="button" onClick={() => onChange(values.filter((x) => x !== v))} aria-label={`Remove ${v}`} className="text-primary-600 hover:text-primary-900">
              <X size={11} />
            </button>
          </span>
        ))}
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} aria-label={`Add ${label.toLowerCase()}`}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(text); } }}
          onBlur={() => text.trim() && add(text)}
          className="h-7 w-28 rounded-full border border-dashed border-border bg-white px-3 text-xs outline-none focus:border-primary" />
        {presets && values.length === 0 && presets.map((p) => (
          <button key={p.label} type="button" onClick={() => onChange(p.values)}
            className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] font-semibold text-primary hover:bg-primary-50">
            <Plus size={11} /> {p.label}
          </button>
        ))}
      </div>
    </div>
  );
}
