"use client";

import { useMemo, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { Check, Loader2, Plus, Tag, Trash2, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { BatchBucket, StockBatch } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Select } from "@/components/ui/Select";
import { Pagination, usePagedList } from "@/components/ui/Pagination";
import { useBatches } from "@/hooks/useApi";
import { StatCard } from "./ItemsTab";
import { formatPaise } from "./money";

/* Batches & expiry (backend services/stock_batches.py, migration 310). Each batch has its own stock
 * and expiry. Bills take Sell-first batches, then the earliest expiry, never an expired one. */

type Filter = "all" | BatchBucket | "returnable";

const CHIP: Record<BatchBucket, string> = {
  expired: "bg-rose-50 text-rose-700",
  soon: "bg-amber-50 text-amber-800",
  later: "bg-yellow-50 text-yellow-800",
  fine: "bg-emerald-50 text-emerald-700",
};

function expiry(iso: string | null) {
  if (!iso) return "No expiry";
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function BatchesTab({ canManage, toolbarSlot }: { canManage: boolean; toolbarSlot: HTMLElement | null }) {
  const { data, error, mutate, isLoading } = useBatches();
  const [filter, setFilter] = useState<Filter>("all");
  const [supplier, setSupplier] = useState("");

  const shown = useMemo(() => (data?.batches ?? []).filter((b) =>
    (filter === "all" || (filter === "returnable" ? b.returnable : b.bucket === filter))
    && (!supplier || b.supplier === supplier)), [data, filter, supplier]);
  const paged = usePagedList(shown, `${filter}|${supplier}`);

  const cards = data?.cards;
  // No Orders access: the API sends no cost or value, so the cards and the Value column are left out.
  const noMoney = !!(data as { costs_hidden?: boolean } | null)?.costs_hidden;
  const card = (key: Filter, icon: string, label: string, tone: "red" | "amber" | "plain", sub: (v: number | null) => string) => {
    const c = cards?.[key as keyof typeof cards];
    return (
      <StatCard icon={icon} label={label} tone={c?.batches ? tone : "plain"} active={filter === key}
        onClick={() => setFilter(filter === key ? "all" : key)}
        value={c ? `${c.batches} ${c.batches === 1 ? "batch" : "batches"}` : "…"} sub={c ? (noMoney ? sub(null) : sub(c.value_paise)) : ""} />
    );
  };

  return (
    <div className="space-y-4">
      {toolbarSlot && canManage && createPortal(
        <Link href="/dashboard/purchases/stock-in"
          className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-primary px-3.5 text-sm font-bold text-white shadow-sm hover:bg-primary-dark">
          <Plus size={14} /> Stock in with batch
        </Link>,
        toolbarSlot,
      )}

      {error && (
        <div className="rounded-card border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          Couldn&apos;t load batches. <button type="button" onClick={() => mutate()} className="font-semibold underline">Try again</button>
        </div>
      )}
      {isLoading && (
        <div className="flex items-center justify-center gap-2 rounded-card border border-border bg-white py-16 text-sm text-ink-muted">
          <Loader2 size={16} className="animate-spin" /> Loading…
        </div>
      )}

      {data && data.tracked_items === 0 && (
        <div className="rounded-card border border-border bg-white px-6 py-10 text-center shadow-sm">
          <p className="text-3xl" aria-hidden>⏳</p>
          <h3 className="mt-3 font-display text-lg font-bold text-ink">No item tracks batches yet</h3>
          <p className="mx-auto mt-1 max-w-md text-sm text-ink-muted">
            For medicines, food or cosmetics, open the item and switch on <b>Track batches &amp; expiry</b>. Its stock
            today becomes one &ldquo;Opening stock&rdquo; batch; new stock is added with its batch no. and expiry through
            Purchases → Stock in. Shops that don&apos;t need it never see these fields.
          </p>
        </div>
      )}

      {data && data.tracked_items > 0 && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            {card("expired", "🔴", "Expired", "red", (v) => v == null ? "remove from shelf" : `${formatPaise(v)} · remove from shelf`)}
            {card("soon", "🟠", "Expiring in 30 days", "amber", (v) => v == null ? "" : `${formatPaise(v)} at cost`)}
            {card("later", "🟡", "In 31–90 days", "plain", (v) => v == null ? "" : formatPaise(v))}
            {card("fine", "✅", "Fine", "plain", (v) => v == null ? "" : formatPaise(v))}
            {card("returnable", "↩️", "Can return to supplier", "plain", (v) => v == null ? "before expiry" : `${formatPaise(v)} before expiry`)}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {([["all", "All"], ["expired", "Expired"], ["soon", "30 days"], ["later", "90 days"]] as [Filter, string][]).map(([key, text]) => {
              const n = key === "all" ? data.batches.length : data.cards[key as BatchBucket].batches;
              return (
                <button key={key} type="button" onClick={() => setFilter(key)} aria-pressed={filter === key}
                  className={cn("h-9 rounded-xl border px-3.5 text-sm font-semibold transition-colors",
                    filter === key ? "border-primary bg-primary-50 text-primary-800" : "border-border bg-white text-ink hover:bg-surface-low")}>
                  {text}{key !== "all" ? ` ${n}` : ""}
                </button>
              );
            })}
            {data.suppliers.length > 0 && (
              <Select size="sm" value={supplier} onChange={setSupplier} aria-label="Supplier" className="w-48"
                options={[{ value: "", label: "All suppliers" }, ...data.suppliers.map((s) => ({ value: s, label: s }))]} />
            )}
          </div>

          <div className="overflow-x-auto rounded-card border border-border bg-white shadow-sm">
            <table className="w-full min-w-[920px] text-sm">
              <thead>
                <tr className="border-b border-border bg-surface-low text-left font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                  <th className="px-4 py-3">Item</th>
                  <th className="px-3 py-3">Batch</th>
                  <th className="px-3 py-3">Expiry</th>
                  <th className="px-3 py-3">Stock</th>
                  {!noMoney && <th className="px-3 py-3">Value</th>}
                  <th className="px-3 py-3">Supplier</th>
                  <th className="px-3 py-3">What to do</th>
                </tr>
              </thead>
              <tbody>
                {shown.length === 0 && (
                  <tr><td colSpan={7} className="px-4 py-10 text-center text-ink-muted">
                    {data.batches.length ? "No batch matches this filter." : "No batch has stock right now."}
                  </td></tr>
                )}
                {paged.pageItems.map((b) => <BatchRow key={b.id} batch={b} canManage={canManage} noMoney={noMoney} onChanged={() => mutate()} />)}
              </tbody>
            </table>
            <Pagination page={paged.page} total={paged.total} onPageChange={paged.setPage} noun="batches" />
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <p className="rounded-card border border-primary/20 bg-primary-50/60 px-4 py-3 text-sm leading-relaxed text-ink">
              <span aria-hidden>🧾</span> On a bill, the batch marked Sell first, else the one that expires first, is picked by
              itself and shown on the bill line; staff can change it. An expired batch can never be billed. Batch and expiry
              print on the bill.
            </p>
            <p className="rounded-card border border-primary/20 bg-primary-50/60 px-4 py-3 text-sm leading-relaxed text-ink">
              <span aria-hidden>🔔</span> Owners get one bell a day at 9:30 AM when something has expired or expires within
              30 days, and Close today&apos;s cash lists them. A small discount lowers the price on bills and in the AI agent&apos;s replies
              while that batch is the one being sold.
            </p>
          </div>
        </>
      )}
    </div>
  );
}

function BatchRow({ batch: b, canManage, noMoney, onChanged }: { batch: StockBatch; canManage: boolean; noMoney: boolean; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"return" | "remove" | null>(null);
  const [editingDiscount, setEditingDiscount] = useState(false);
  const [pct, setPct] = useState(String(b.discount_pct || 10));

  async function act(key: string, run: () => Promise<unknown>, done: string) {
    setBusy(key);
    try {
      await run();
      toast.success(done);
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save. Try again.");
    } finally {
      setBusy(null);
      setConfirm(null);
      setEditingDiscount(false);
    }
  }

  const expired = b.bucket === "expired";
  const btn = "inline-flex h-8 items-center gap-1 whitespace-nowrap rounded-lg border px-2.5 text-[13px] font-semibold disabled:opacity-50";

  return (
    <tr className="border-b border-border-subtle align-top last:border-b-0">
      <td className="px-4 py-3">
        <Link href={`/dashboard/catalog/items/${b.catalog_item_id}`} className="font-bold text-ink hover:underline">
          {b.name}{b.variant_label ? ` · ${b.variant_label}` : ""}
        </Link>
        <p className="text-xs text-ink-muted">{b.place}</p>
      </td>
      <td className="px-3 py-3 font-mono text-[13px] text-ink">{b.batch_no || <span className="font-sans text-ink-muted">No batch no.</span>}</td>
      <td className="px-3 py-3">
        <span className={cn("whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold", CHIP[b.bucket])}>{expiry(b.expiry_date)}</span>
        <div className="mt-1 flex flex-wrap gap-1">
          {b.sell_first && <span className="rounded-full bg-primary-50 px-2 py-0.5 text-[11px] font-semibold text-primary-800">Sell first</span>}
          {b.discount_pct > 0 && <span className="rounded-full bg-violet-50 px-2 py-0.5 text-[11px] font-semibold text-violet-700">{b.discount_pct}% off</span>}
        </div>
      </td>
      <td className="px-3 py-3 font-bold tabular-nums text-ink">{b.quantity}</td>
      {!noMoney && (
        <td className="px-3 py-3 tabular-nums text-ink" title={b.value_at === "cost" ? "At cost" : "At selling price (no cost on this batch)"}>
          {formatPaise(b.value_paise)}
        </td>
      )}
      <td className="px-3 py-3 text-ink">{b.supplier ?? <span className="text-ink-muted">—</span>}</td>
      <td className="px-3 py-3">
        {!canManage ? <span className="text-ink-muted">—</span> : confirm ? (
          <span className="inline-flex flex-wrap items-center gap-2">
            <span className="text-xs text-ink-muted">
              {confirm === "return" ? `Return all ${b.quantity} to ${b.supplier}? What you owe them goes down.` : `Remove all ${b.quantity} from stock?`}
            </span>
            <button type="button" disabled={busy !== null}
              onClick={() => confirm === "return"
                ? act("return", () => api.catalog.returnBatch(b.id), `Returned to ${b.supplier}. What you owe them went down.`)
                : act("remove", () => api.catalog.writeOffBatch(b.id), "Removed from stock. It's in the Activity log.")}
              className={cn(btn, confirm === "remove" ? "border-danger/40 text-danger hover:bg-danger/5" : "border-primary bg-primary text-white hover:bg-primary-dark")}>
              {busy ? <Loader2 size={12} className="animate-spin" /> : <Check size={13} />} Yes
            </button>
            <button type="button" onClick={() => setConfirm(null)} className="text-xs font-semibold text-ink-muted hover:text-ink">Cancel</button>
          </span>
        ) : editingDiscount ? (
          <span className="inline-flex items-center gap-2">
            <input value={pct} onChange={(e) => setPct(e.target.value.replace(/\D/g, "").slice(0, 2))} inputMode="numeric" aria-label="Discount %"
              className="h-8 w-14 rounded-lg border border-border px-2 text-right tabular-nums outline-none focus:border-primary" />
            <span className="text-sm text-ink-muted">% off</span>
            <button type="button" disabled={busy !== null || pct === ""}
              onClick={() => act("discount", () => api.catalog.updateBatch(b.id, { discount_pct: Number(pct) }),
                Number(pct) ? `${pct}% off while this batch is sold.` : "Discount removed.")}
              className={cn(btn, "border-primary bg-primary text-white hover:bg-primary-dark")}>Save</button>
            <button type="button" onClick={() => setEditingDiscount(false)} className="text-xs font-semibold text-ink-muted hover:text-ink">Cancel</button>
          </span>
        ) : (
          <span className="flex flex-wrap gap-1.5">
            {expired ? (
              <button type="button" onClick={() => setConfirm("remove")} className={cn(btn, "border-border bg-white text-ink hover:bg-surface-low")}>
                <Trash2 size={13} /> Remove · write off
              </button>
            ) : (
              <>
                {b.supplier && (b.bucket === "soon" || b.bucket === "later") && (
                  <button type="button" onClick={() => setConfirm("return")} className={cn(btn, "border-primary bg-primary text-white hover:bg-primary-dark")}>
                    <Undo2 size={13} /> Return to supplier
                  </button>
                )}
                <button type="button" onClick={() => setEditingDiscount(true)} className={cn(btn, "border-border bg-white text-ink hover:bg-surface-low")}>
                  <Tag size={13} /> {b.discount_pct ? `${b.discount_pct}% off` : "Small discount"}
                </button>
                <button type="button" disabled={busy !== null}
                  onClick={() => act("first", () => api.catalog.updateBatch(b.id, { sell_first: !b.sell_first }),
                    b.sell_first ? "Back to the usual order." : "Bills take this batch first now.")}
                  className={cn(btn, b.sell_first ? "border-primary bg-primary-50 text-primary-800" : "border-border bg-white text-ink hover:bg-surface-low")}>
                  {b.sell_first && <Check size={13} />} Sell first
                </button>
              </>
            )}
          </span>
        )}
      </td>
    </tr>
  );
}
