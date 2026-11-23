"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import {
  KIND_LABEL,
  parseMoneyInput,
  parseWholeNumber,
  priceRangeText,
  type Property,
  type PropertyBody,
  type PropertyKind,
} from "@/lib/propertiesApi";
import { cn } from "@/lib/utils";

/* One form for adding and editing a property. Money is typed the way owners say it ("45 lakh", "1.2 cr")
 * and sent as paise. People without orders access get no price boxes (the backend leaves prices out). */

const field = "mt-1 w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-ink focus:border-primary focus:outline-none";
const label = "block text-xs font-semibold text-ink";

function moneyText(paise: number | null | undefined) {
  return paise == null ? "" : String(paise / 100);
}

export function PropertyForm({
  initial,
  canSeeMoney,
  saving,
  submitLabel,
  onSubmit,
}: {
  initial?: Property;
  canSeeMoney: boolean;
  saving: boolean;
  submitLabel: string;
  onSubmit: (body: PropertyBody) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [project, setProject] = useState(initial?.project ?? "");
  const [kind, setKind] = useState<PropertyKind>(initial?.kind ?? "flat");
  const [bhk, setBhk] = useState(initial?.bhk != null ? String(initial.bhk) : "");
  const [low, setLow] = useState(moneyText(initial?.price_min_paise));
  const [high, setHigh] = useState(moneyText(initial?.price_max_paise));
  const [size, setSize] = useState(initial?.size_text ?? "");
  const [total, setTotal] = useState(initial?.units_total != null ? String(initial.units_total) : "");
  const [left, setLeft] = useState(initial?.units_left != null ? String(initial.units_left) : "");
  const [mapUrl, setMapUrl] = useState(initial?.map_url ?? "");
  const [rera, setRera] = useState(initial?.rera_no ?? "");
  const [aiOn, setAiOn] = useState(initial?.ai_on ?? true);
  const [error, setError] = useState<string | null>(null);

  const lowPaise = parseMoneyInput(low);
  const highPaise = parseMoneyInput(high);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const bhkN = parseWholeNumber(bhk);
    const totalN = parseWholeNumber(total);
    const leftN = parseWholeNumber(left);
    if (!name.trim()) return setError("Give the property a name, like \"Green Valley 3BHK\"");
    if (bhkN === undefined || totalN === undefined || leftN === undefined) return setError("BHK and units: whole numbers only, please");
    if (canSeeMoney && (lowPaise === undefined || highPaise === undefined)) return setError("Prices: type a number, like 4500000 or 45 lakh");
    if (canSeeMoney && lowPaise != null && highPaise != null && highPaise < lowPaise) return setError("The highest price cannot be less than the lowest");
    if (totalN != null && leftN != null && leftN > totalN) return setError("Units left cannot be more than the total units");
    setError(null);
    const body: PropertyBody = {
      name: name.trim(), project: project.trim() || null, kind, bhk: bhkN, size_text: size.trim() || null,
      units_total: totalN, units_left: leftN, map_url: mapUrl.trim() || null, rera_no: rera.trim() || null, ai_on: aiOn,
    };
    if (canSeeMoney) {
      body.price_min_paise = lowPaise ?? null;
      body.price_max_paise = highPaise ?? null;
    }
    onSubmit(body);
  }

  const range = canSeeMoney && typeof lowPaise !== "undefined" && typeof highPaise !== "undefined" ? priceRangeText(lowPaise, highPaise) : "";

  return (
    <form onSubmit={submit} className="space-y-4 rounded-card border border-border bg-white p-4 shadow-sm">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className={label}>
          Name
          <input className={field} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} placeholder="Green Valley 3BHK" />
        </label>
        <label className={label}>
          Project
          <input className={field} value={project} maxLength={120} onChange={(e) => setProject(e.target.value)} placeholder="Green Valley" />
        </label>
        <label className={label}>
          Type
          <select className={field} value={kind} onChange={(e) => setKind(e.target.value as PropertyKind)}>
            {(Object.keys(KIND_LABEL) as PropertyKind[]).map((k) => (
              <option key={k} value={k}>{KIND_LABEL[k]}</option>
            ))}
          </select>
        </label>
        <label className={label}>
          BHK
          <input className={field} inputMode="numeric" value={bhk} onChange={(e) => setBhk(e.target.value)} placeholder="3" />
        </label>
        {canSeeMoney && (
          <>
            <label className={label}>
              Lowest price
              <input className={field} value={low} onChange={(e) => setLow(e.target.value)} placeholder="45 lakh" />
            </label>
            <label className={label}>
              Highest price
              <input className={field} value={high} onChange={(e) => setHigh(e.target.value)} placeholder="60 lakh" />
            </label>
          </>
        )}
        <label className={label}>
          Size
          <input className={field} value={size} maxLength={80} onChange={(e) => setSize(e.target.value)} placeholder="1450 sq ft" />
        </label>
        <label className={label}>
          RERA no.
          <input className={field} value={rera} maxLength={60} onChange={(e) => setRera(e.target.value)} />
        </label>
        <label className={label}>
          Total units
          <input className={field} inputMode="numeric" value={total} onChange={(e) => setTotal(e.target.value)} placeholder="20" />
        </label>
        <label className={label}>
          Units left
          <input className={field} inputMode="numeric" value={left} onChange={(e) => setLeft(e.target.value)} placeholder="same as total to start" />
        </label>
        <label className={cn(label, "sm:col-span-2")}>
          Map link
          <input className={field} value={mapUrl} maxLength={500} onChange={(e) => setMapUrl(e.target.value)} placeholder="https://maps.google.com/..." />
        </label>
      </div>
      {range && <p className="text-sm text-ink-muted">Customers will see: {range}</p>}
      <label className="flex items-start gap-2 text-sm text-ink">
        <input type="checkbox" className="mt-1 h-4 w-4" checked={aiOn} onChange={(e) => setAiOn(e.target.checked)} />
        <span>
          Let the AI agent talk about this property
          <span className="block text-xs text-ink-muted">Switch off to keep it out of chats while you finish the details.</span>
        </span>
      </label>
      {error && <p role="alert" className="text-sm font-semibold text-red-700">{error}</p>}
      <button
        type="submit"
        disabled={saving}
        className="inline-flex min-h-10 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-white disabled:opacity-60"
      >
        {saving && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
        {submitLabel}
      </button>
    </form>
  );
}
