"use client";

import { useState } from "react";
import { Plus, X } from "lucide-react";
import { cn } from "@/lib/utils";

/** Sizes x colours, each box its own stock (migration 294). Colours down, sizes across. */
export interface VariantsValue {
  sizes: string[];
  colours: string[];
  /** key `${size}|${colour}` (either part may be empty) -> stock as typed */
  stock: Record<string, string>;
}

export const cellKey = (size: string | null, colour: string | null) => `${size ?? ""}|${colour ?? ""}`;

export function variantCells(v: VariantsValue) {
  const sizes = v.sizes.length ? v.sizes : [null];
  const colours = v.colours.length ? v.colours : [null];
  return colours.flatMap((c) => sizes.map((s) => ({ size: s, colour: c, stock: Math.max(0, Math.round(Number(v.stock[cellKey(s, c)] || 0))) })))
    .filter((cell) => cell.size || cell.colour);
}

export function variantsTotal(v: VariantsValue) {
  return variantCells(v).reduce((a, c) => a + c.stock, 0);
}

const SIZE_PRESETS: { label: string; values: string[] }[] = [
  { label: "S M L XL", values: ["S", "M", "L", "XL"] },
  { label: "Free size", values: ["Free size"] },
  { label: "2-8 yrs", values: ["2-4 yrs", "4-6 yrs", "6-8 yrs"] },
];

function ChipInput({ label, values, onChange, placeholder, presets }: {
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

export function VariantsEditor({ value, onChange }: { value: VariantsValue; onChange: (v: VariantsValue) => void }) {
  const sizes = value.sizes.length ? value.sizes : [null];
  const colours = value.colours.length ? value.colours : [null];
  const hasAny = value.sizes.length > 0 || value.colours.length > 0;

  return (
    <div className="space-y-3 rounded-xl border border-border bg-surface-low/40 p-3">
      <ChipInput label="Sizes" values={value.sizes} onChange={(sizes) => onChange({ ...value, sizes })} placeholder="Add size" presets={SIZE_PRESETS} />
      <ChipInput label="Colours" values={value.colours} onChange={(colours) => onChange({ ...value, colours })} placeholder="Add colour" />
      {hasAny && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                <th className="py-1.5 pr-2 text-left">Stock</th>
                {sizes.map((s) => <th key={s ?? "_"} className="px-1 py-1.5 text-center">{s ?? "Pieces"}</th>)}
              </tr>
            </thead>
            <tbody>
              {colours.map((c) => (
                <tr key={c ?? "_"}>
                  <td className="py-1 pr-2 font-semibold text-ink">{c ?? "All"}</td>
                  {sizes.map((s) => {
                    const key = cellKey(s, c);
                    const n = Number(value.stock[key] || 0);
                    return (
                      <td key={key} className="px-1 py-1 text-center">
                        <input type="number" min="0" step="1" inputMode="numeric" value={value.stock[key] ?? ""}
                          onChange={(e) => onChange({ ...value, stock: { ...value.stock, [key]: e.target.value } })}
                          aria-label={`Stock ${[c, s].filter(Boolean).join(" ")}`} placeholder="0"
                          className={cn("h-8 w-14 rounded-lg border text-center text-xs tabular-nums outline-none focus:border-primary",
                            !value.stock[key] || n === 0 ? "border-rose-200 bg-rose-50/60" : n === 1 ? "border-amber-200 bg-amber-50" : "border-border bg-white")} />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1.5 text-[11px] text-ink-muted">
            {variantsTotal(value)} pieces in all. Red = none left, yellow = last piece. Each change is saved in the stock history.
          </p>
        </div>
      )}
    </div>
  );
}
