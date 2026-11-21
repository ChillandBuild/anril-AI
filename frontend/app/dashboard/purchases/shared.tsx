"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import type { PurchaseOptionItem, PurchaseOrderStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Select } from "@/components/ui/Select";

/* Shared bits of Purchases & suppliers (backend services/purchases.py). */

export const GST_RATES = [0, 0.25, 3, 5, 12, 18, 28, 40];

export function rupees(paise: number | null | undefined): string {
  const value = (paise ?? 0) / 100;
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: value % 1 ? 2 : 0 })}`;
}

/** "480" or "480.50" typed in rupees -> paise (NaN when it isn't a number). */
export function toPaise(text: string): number {
  const n = Number(String(text).replace(/[,₹\s]/g, ""));
  return Number.isFinite(n) ? Math.round(n * 100) : NaN;
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function todayIso(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
}

const PO_LOOK: Record<PurchaseOrderStatus, { text: string; cls: string }> = {
  draft: { text: "Draft", cls: "bg-surface-mid text-ink-secondary" },
  sent: { text: "Sent", cls: "bg-blue-50 text-blue-700" },
  confirmed: { text: "Confirmed by supplier", cls: "bg-blue-50 text-blue-700" },
  part_received: { text: "Part came", cls: "bg-amber-50 text-amber-800" },
  received: { text: "✓ All received", cls: "bg-emerald-50 text-emerald-700" },
  cancelled: { text: "Cancelled", cls: "bg-surface-mid text-ink-muted" },
};

export function PoStatusChip({ status, lateDays, ordered, received }: {
  status: PurchaseOrderStatus; lateDays?: number; ordered?: number; received?: number;
}) {
  const look = lateDays && status !== "received" && status !== "cancelled"
    ? { text: `${lateDays} ${lateDays === 1 ? "day" : "days"} late`, cls: "bg-rose-50 text-rose-700" }
    : status === "part_received" && ordered
      ? { text: `Part came · ${received} of ${ordered}`, cls: PO_LOOK.part_received.cls }
      : PO_LOOK[status];
  return <span className={cn("inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold", look.cls)}>{look.text}</span>;
}

export function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn("block space-y-1", className)}>
      <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">{label}</span>
      {children}
    </label>
  );
}

export const inputCls =
  "h-10 w-full rounded-lg border border-border bg-white px-3 text-sm text-ink focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/15 disabled:bg-surface-low";

/** Pick an item, then its size/colour when it has them. */
export function ItemPicker({ items, onPick, label = "Add item" }: {
  items: PurchaseOptionItem[];
  onPick: (item: PurchaseOptionItem, variantId: string | null) => void;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [itemId, setItemId] = useState("");
  const item = items.find((i) => i.id === itemId);

  function pick(variantId: string | null) {
    if (!item) return;
    onPick(item, variantId);
    setItemId("");
    setOpen(false);
  }

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline">
        <Plus size={15} /> {label}
      </button>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select size="md" aria-label="Item" value={itemId} className="w-64"
        onChange={(v) => {
          setItemId(v);
          const chosen = items.find((i) => i.id === v);
          if (chosen && chosen.variants.length === 0) {
            onPick(chosen, null);
            setItemId("");
            setOpen(false);
          }
        }}
        placeholder="Pick an item" options={items.map((i) => ({ value: i.id, label: i.name }))} />
      {item && item.variants.length > 0 && (
        <Select size="md" aria-label="Size or colour" value="" className="w-48" onChange={(v) => v && pick(v)}
          placeholder="Size / colour" options={item.variants.map((v) => ({ value: v.id, label: `${v.label} · ${v.stock} in stock` }))} />
      )}
      <button type="button" onClick={() => { setOpen(false); setItemId(""); }} className="text-xs font-semibold text-ink-muted hover:text-ink">Cancel</button>
    </div>
  );
}

export function variantLabel(item: PurchaseOptionItem | undefined, variantId: string | null): string {
  if (!item) return "";
  const v = variantId ? item.variants.find((x) => x.id === variantId) : null;
  return v ? `${item.name} · ${v.label}` : item.name;
}

export function lastCost(item: PurchaseOptionItem | undefined, variantId: string | null): number {
  if (!item) return 0;
  const v = variantId ? item.variants.find((x) => x.id === variantId) : null;
  return v?.cost_price_paise ?? item.cost_price_paise ?? 0;
}

/** Open a wa.me link in a new tab (the team sends it from their own phone). */
export function openShare(url: string | null | undefined) {
  if (url) window.open(url, "_blank", "noopener,noreferrer");
}
