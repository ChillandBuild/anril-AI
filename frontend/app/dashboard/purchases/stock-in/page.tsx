"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Camera, Check, Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { DamagedAction, StockInResult, SupplierPayMethod } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AiraLoader } from "@/components/AiraLoader";
import { Select } from "@/components/ui/Select";
import { usePurchaseOptions, usePurchaseOrder } from "@/hooks/useApi";
import { Field, GST_RATES, ItemPicker, inputCls, lastCost, rupees, toPaise, todayIso, variantLabel } from "../shared";

/* Stock in: what came from a supplier. Opened with ?po=<id> it is "Goods came" for that purchase
 * order: the lines are the order's, so staff only tick what arrived. */

interface Line {
  key: string;
  catalog_item_id: string;
  variant_id: string | null;
  po_line_id: string | null;
  label: string;
  ordered: number | null;
  still: number | null;
  good: string;
  damaged: string;
  action: DamagedAction | null;
  cost: string;
  gst_rate: number;
  /** Batches & expiry: only for items that track batches. */
  batch_no?: string;
  expiry?: string;
}

const DAMAGED: { value: DamagedAction; label: string }[] = [
  { value: "replace", label: "Supplier replaces" },
  { value: "less_on_bill", label: "Less on bill" },
  { value: "discount", label: "Keep, sell at discount" },
];

export default function StockInPage() {
  const router = useRouter();
  const poId = useSearchParams().get("po");
  const { data: opts, error } = usePurchaseOptions();
  const { data: po } = usePurchaseOrder(poId);
  const [supplierId, setSupplierId] = useState("");
  const [newSupplier, setNewSupplier] = useState("");
  const [billNo, setBillNo] = useState("");
  const [billDate, setBillDate] = useState(todayIso());
  const [gstin, setGstin] = useState("");
  const [placeId, setPlaceId] = useState("");
  const [receivedBy, setReceivedBy] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [pay, setPay] = useState<"paid" | "part" | "later">("later");
  const [paidText, setPaidText] = useState("");
  const [method, setMethod] = useState<SupplierPayMethod>("upi");
  const [dueDate, setDueDate] = useState("");
  const [reading, setReading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState<StockInResult | null>(null);
  const [requestId] = useState(() => crypto.randomUUID());
  const photo = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (opts && !placeId) setPlaceId(opts.places.find((p) => p.bills_from)?.id ?? opts.places[0]?.id ?? "");
  }, [opts, placeId]);

  useEffect(() => {
    if (!po) return;
    setSupplierId(po.supplier_id);
    if (po.place_id) setPlaceId(po.place_id);
    setLines(po.lines.map((li) => {
      const still = Math.max(0, li.qty_ordered - li.qty_received);
      return {
        key: li.id, catalog_item_id: li.catalog_item_id, variant_id: li.variant_id, po_line_id: li.id, label: li.label,
        ordered: li.qty_ordered, still, good: String(still), damaged: "0", action: null,
        cost: String(li.unit_cost_paise / 100), gst_rate: Number(li.gst_rate),
      };
    }));
  }, [po]);

  const totals = useMemo(() => {
    let items = 0;
    let gst = 0;
    let pieces = 0;
    for (const li of lines) {
      const kept = (Number(li.good) || 0) + (li.action === "discount" ? Number(li.damaged) || 0 : 0);
      const value = kept * (toPaise(li.cost) || 0);
      items += value;
      gst += Math.round((value * li.gst_rate) / 100);
      pieces += kept;
    }
    return { items, gst, total: items + gst, pieces };
  }, [lines]);

  if (error) return <p className="text-sm text-danger">Couldn&apos;t load your items. Reload the page.</p>;
  if (!opts || (poId && !po)) return <AiraLoader inline className="min-h-[50vh]" />;

  const update = (key: string, patch: Partial<Line>) => setLines((ls) => ls.map((li) => (li.key === key ? { ...li, ...patch } : li)));
  const needsAction = lines.some((li) => Number(li.damaged) > 0 && !li.action);
  const paidPaise = toPaise(paidText);
  const payBad = pay === "part" && !(paidPaise > 0 && paidPaise < totals.total);
  const ready = lines.some((li) => (Number(li.good) || 0) + (Number(li.damaged) || 0) > 0) && !needsAction && !payBad
    && (pay === "later" || Boolean(supplierId || newSupplier.trim()));
  const short = lines.reduce((n, li) => n + (li.still != null ? Math.max(0, li.still - (Number(li.good) || 0)) : 0), 0);
  const damagedAside = lines.reduce((n, li) => n + (li.action && li.action !== "discount" ? Number(li.damaged) || 0 : 0), 0);

  async function readBill(file: File | undefined) {
    if (!file) return;
    setReading(true);
    try {
      const read = await api.purchases.readBill(file);
      if (read.supplier_id) setSupplierId(read.supplier_id);
      else if (read.supplier_name && !supplierId) setNewSupplier(read.supplier_name);
      if (read.bill_no) setBillNo(read.bill_no);
      if (read.bill_date) setBillDate(read.bill_date);
      if (read.supplier_gstin) setGstin(read.supplier_gstin);
      const matched = read.lines.filter((li) => li.catalog_item_id);
      setLines((ls) => [...ls, ...matched.map((li, i) => ({
        key: `read-${Date.now()}-${i}`, catalog_item_id: li.catalog_item_id!, variant_id: li.variant_id, po_line_id: null,
        label: li.label!, ordered: null, still: null, good: String(li.qty_good), damaged: "0", action: null,
        cost: String(li.unit_cost_paise / 100), gst_rate: Number(li.gst_rate) || 0,
      }))]);
      const missed = read.lines.length - matched.length;
      if (missed) toast.message(`Read ${matched.length} lines. ${missed} didn't match an item (${read.lines.filter((l) => !l.catalog_item_id).map((l) => l.read_name).join(", ")}): add them with “Add item”.`);
      else toast.success(`Read ${matched.length} lines. Check them, then save.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't read the bill.");
    } finally {
      setReading(false);
      if (photo.current) photo.current.value = "";
    }
  }

  async function save() {
    setSaving(true);
    try {
      const out = await api.purchases.stockIn({
        request_id: requestId,
        supplier_id: supplierId || null, supplier_name: supplierId ? undefined : newSupplier.trim() || undefined,
        purchase_order_id: poId, bill_no: billNo, bill_date: billDate, supplier_gstin: gstin, place_id: placeId || null,
        received_by: receivedBy, pay_status: pay, paid_paise: pay === "part" ? paidPaise : undefined, pay_method: method,
        due_date: pay === "paid" ? null : dueDate || null,
        lines: lines.map((li) => ({
          catalog_item_id: li.catalog_item_id, variant_id: li.variant_id, purchase_order_line_id: li.po_line_id,
          qty_good: Number(li.good) || 0, qty_damaged: Number(li.damaged) || 0,
          damaged_action: Number(li.damaged) > 0 ? li.action : null, unit_cost_paise: toPaise(li.cost) || 0, gst_rate: li.gst_rate,
          batch_no: li.batch_no?.trim() || undefined, expiry_date: li.expiry || undefined,
        })),
      });
      setDone(out);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save. Try again.");
    } finally {
      setSaving(false);
    }
  }

  if (done) {
    const people = done.waiting.reduce((n, w) => n + w.people, 0);
    return (
      <div className="mx-auto max-w-xl space-y-4 py-10 text-center">
        <p className="text-4xl" aria-hidden>📥</p>
        <h1 className="font-display text-xl font-bold text-ink">Stock +{done.pieces_in} saved</h1>
        <p className="text-sm text-ink-muted">
          Bill {rupees(done.total_paise)}. Cost prices updated.{done.damaged_aside ? ` ${done.damaged_aside} damaged kept aside.` : ""}
        </p>
        {people > 0 && (
          <div className="rounded-card border border-primary/30 bg-primary-50/60 px-4 py-3 text-sm text-ink">
            🔔 {people} {people === 1 ? "person is" : "people are"} waiting for what just came.{" "}
            <Link href="/dashboard/catalog?tab=asked" className="font-semibold text-primary hover:underline">Tell them it&apos;s back ›</Link>
          </div>
        )}
        <div className="flex justify-center gap-2">
          <button type="button" onClick={() => router.push("/dashboard/purchases?tab=stock-in")} className="btn-primary h-9 !py-0">Done</button>
          <button type="button" onClick={() => window.location.assign("/dashboard/purchases/stock-in")}
            className="h-9 rounded-xl border border-border px-3 text-sm font-semibold text-ink hover:bg-surface-low">Another stock in</button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-7xl space-y-4 pb-24">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href={poId ? "/dashboard/purchases" : "/dashboard/purchases?tab=stock-in"} className="inline-flex items-center gap-1.5 text-xs font-semibold text-ink-secondary hover:text-ink">
          <ArrowLeft size={14} /> {poId ? "Purchase orders" : "Stock in"}
        </Link>
        <div className="flex items-center gap-2">
          {po && <span className="text-sm font-semibold text-ink">Goods came · {po.po_number} from {po.supplier.name}</span>}
          <input ref={photo} type="file" hidden accept="image/jpeg,image/png,application/pdf" onChange={(e) => readBill(e.target.files?.[0])} />
          <button type="button" onClick={() => photo.current?.click()} disabled={reading}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border bg-white px-3 text-sm font-semibold text-ink hover:bg-surface-low disabled:opacity-60">
            {reading ? <Loader2 size={14} className="animate-spin" /> : <Camera size={15} />} Photo of supplier bill
          </button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <Field label="Supplier">
              {poId ? <input className={inputCls} disabled value={po?.supplier.name ?? ""} /> : (
                <Select size="md" value={supplierId} onChange={(v) => { setSupplierId(v); setNewSupplier(""); }} aria-label="Supplier"
                  placeholder={newSupplier ? `New: ${newSupplier}` : "Pick a supplier"} options={opts.suppliers.map((s) => ({ value: s.id, label: s.name }))} />
              )}
            </Field>
            <Field label="Their bill no."><input className={inputCls} value={billNo} onChange={(e) => setBillNo(e.target.value)} placeholder="SMT/1182" /></Field>
            <Field label="Date"><input type="date" className={inputCls} value={billDate} onChange={(e) => setBillDate(e.target.value)} /></Field>
            <Field label="Their GSTIN"><input className={inputCls} value={gstin} onChange={(e) => setGstin(e.target.value.toUpperCase())} placeholder="Optional" /></Field>
            <Field label="Put in">
              <Select size="md" value={placeId} onChange={setPlaceId} aria-label="Put in" options={opts.places.map((p) => ({ value: p.id, label: p.name }))} />
            </Field>
            <Field label="Received by"><input className={inputCls} value={receivedBy} onChange={(e) => setReceivedBy(e.target.value)} placeholder="Meena" /></Field>
          </div>

          <div className="overflow-x-auto rounded-card border border-border bg-white shadow-sm">
            <table className="w-full min-w-[820px] text-sm">
              <thead>
                <tr className="border-b border-border bg-surface-low text-left font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                  <th className="px-4 py-3">Item</th>
                  {poId && <th className="px-3 py-3">Ordered</th>}
                  <th className="px-3 py-3">{poId ? "Good" : "Qty"}</th>
                  <th className="px-3 py-3">Damaged</th>
                  {poId && <th className="px-3 py-3">Still to come</th>}
                  <th className="px-3 py-3">Cost each</th>
                  <th className="px-3 py-3">GST</th>
                  <th className="px-3 py-3">Total</th>
                  <th className="px-2 py-3" />
                </tr>
              </thead>
              <tbody>
                {lines.length === 0 && (
                  <tr><td colSpan={9} className="px-4 py-8 text-center text-ink-muted">Add what came, or take a photo of the supplier&apos;s bill.</td></tr>
                )}
                {lines.map((li) => {
                  const damaged = Number(li.damaged) || 0;
                  const kept = (Number(li.good) || 0) + (li.action === "discount" ? damaged : 0);
                  const still = li.still != null ? Math.max(0, li.still - (Number(li.good) || 0)) : null;
                  return (
                    <tr key={li.key} className="border-b border-border-subtle align-top last:border-b-0">
                      <td className="px-4 py-2.5 font-semibold text-ink">
                        {li.label}
                        {opts.items.find((it) => it.id === li.catalog_item_id)?.tracks_batches && (
                          <div className="mt-1.5 flex flex-wrap gap-1.5 font-normal">
                            <input value={li.batch_no ?? ""} maxLength={40} placeholder="Batch no." aria-label={`Batch no. of ${li.label}`}
                              onChange={(e) => update(li.key, { batch_no: e.target.value })}
                              className="h-8 w-28 rounded-lg border border-border px-2 font-mono text-xs uppercase" />
                            <input type="date" value={li.expiry ?? ""} aria-label={`Expiry of ${li.label}`}
                              onChange={(e) => update(li.key, { expiry: e.target.value })}
                              className={cn("h-8 rounded-lg border px-2 text-xs", li.expiry ? "border-border" : "border-amber-300")} />
                            {!li.expiry && <span className="w-full text-[11px] text-amber-700">Add the expiry so Anril can warn you before it.</span>}
                          </div>
                        )}
                      </td>
                      {poId && <td className="px-3 py-2.5 tabular-nums text-ink">{li.ordered}</td>}
                      <td className="px-3 py-2.5">
                        <input value={li.good} inputMode="numeric" aria-label={`Good pieces of ${li.label}`}
                          onChange={(e) => update(li.key, { good: e.target.value.replace(/\D/g, "") })}
                          className="h-9 w-20 rounded-lg border border-border px-2 text-center font-bold tabular-nums text-emerald-700" />
                      </td>
                      <td className="px-3 py-2.5">
                        <input value={li.damaged} inputMode="numeric" aria-label={`Damaged pieces of ${li.label}`}
                          onChange={(e) => update(li.key, { damaged: e.target.value.replace(/\D/g, "") })}
                          className={cn("h-9 w-16 rounded-lg border px-2 text-center tabular-nums", damaged ? "border-rose-300 text-rose-700" : "border-border")} />
                        {damaged > 0 && (
                          <div className="mt-1.5 flex flex-col gap-1">
                            {DAMAGED.map((d) => (
                              <button key={d.value} type="button" onClick={() => update(li.key, { action: d.value })}
                                className={cn("rounded-lg border px-2 py-1 text-left text-xs font-semibold",
                                  li.action === d.value ? "border-primary bg-primary-50 text-primary-800" : "border-border text-ink-secondary hover:bg-surface-low")}>
                                {d.label}{d.value === "less_on_bill" ? ` (${rupees(damaged * (toPaise(li.cost) || 0))})` : ""}
                              </button>
                            ))}
                          </div>
                        )}
                      </td>
                      {poId && (
                        <td className="px-3 py-2.5">
                          {still ? <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-800">{still} pcs</span>
                            : <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700"><Check size={12} className="inline" /></span>}
                        </td>
                      )}
                      <td className="px-3 py-2.5">
                        <input value={li.cost} inputMode="decimal" aria-label={`Cost of ${li.label}`} onChange={(e) => update(li.key, { cost: e.target.value })}
                          className="h-9 w-24 rounded-lg border border-border px-2 tabular-nums" />
                      </td>
                      <td className="px-3 py-2.5">
                        <Select size="sm" value={String(li.gst_rate)} aria-label={`GST on ${li.label}`} className="w-20"
                          onChange={(v) => update(li.key, { gst_rate: Number(v) })} options={GST_RATES.map((r) => ({ value: String(r), label: `${r}%` }))} />
                      </td>
                      <td className="px-3 py-2.5 font-bold tabular-nums text-ink">{rupees(kept * (toPaise(li.cost) || 0))}</td>
                      <td className="px-2 py-2.5">
                        {!li.po_line_id && (
                          <button type="button" onClick={() => setLines((ls) => ls.filter((x) => x.key !== li.key))} aria-label={`Remove ${li.label}`}
                            className="rounded-lg p-1 text-ink-muted hover:bg-red-50 hover:text-red-600"><Trash2 size={14} /></button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="border-t border-border px-4 py-3">
              <ItemPicker items={opts.items} label="Add item" onPick={(item, variantId) => {
                setLines((ls) => [...ls, { key: `${item.id}:${variantId ?? ""}:${Date.now()}`, catalog_item_id: item.id, variant_id: variantId,
                  po_line_id: null, label: variantLabel(item, variantId), ordered: null, still: null, good: "1", damaged: "0", action: null,
                  cost: String(lastCost(item, variantId) / 100), gst_rate: item.gst_rate }]);
              }} />
            </div>
          </div>
          <p className="rounded-card border border-primary/20 bg-primary-50/60 px-4 py-3 text-sm text-ink">
            📷 Photo of the supplier bill: Anril reads the items and amounts, you check and save.
          </p>
        </div>

        <aside className="space-y-3">
          <div className="rounded-card border border-border bg-white p-4 shadow-sm">
            <p className="text-sm font-bold text-ink">Total</p>
            <p className="mt-2 text-sm text-ink">Items {rupees(totals.items)}</p>
            <p className="text-sm text-ink">GST paid {rupees(totals.gst)} <span className="text-ink-muted">(for your accountant)</span></p>
            <p className="mt-1 font-display text-2xl font-bold tabular-nums text-ink">{rupees(totals.total)}</p>
          </div>
          <div className="space-y-3 rounded-card border border-border bg-white p-4 shadow-sm">
            <p className="text-sm font-bold text-ink">Paid to supplier?</p>
            <div className="flex flex-wrap gap-2">
              {([["paid", "Paid in full"], ["part", "Part paid"], ["later", "Pay later"]] as const).map(([value, label]) => (
                <button key={value} type="button" onClick={() => setPay(value)} aria-pressed={pay === value}
                  className={cn("rounded-xl border px-3 py-1.5 text-sm font-semibold",
                    pay === value ? "border-primary bg-primary-50 text-primary-800" : "border-border text-ink hover:bg-surface-low")}>{label}</button>
              ))}
            </div>
            {pay !== "later" && (
              <div className="flex gap-2">
                {pay === "part" && (
                  <input value={paidText} onChange={(e) => setPaidText(e.target.value)} inputMode="decimal" placeholder="Paid ₹" aria-label="Amount paid"
                    className={cn(inputCls, payBad && paidText ? "border-rose-300" : "")} />
                )}
                <Select size="md" value={method} onChange={(v) => setMethod(v as SupplierPayMethod)} aria-label="Paid by" className="w-32"
                  options={[{ value: "upi", label: "UPI" }, { value: "cash", label: "Cash" }, { value: "bank", label: "Bank" }, { value: "cheque", label: "Cheque" }]} />
              </div>
            )}
            {pay !== "paid" && (
              <Field label={pay === "part" ? "Rest due" : "Due"}>
                <input type="date" className={inputCls} value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
              </Field>
            )}
            {pay !== "later" && !supplierId && !newSupplier.trim() && <p className="text-xs font-semibold text-amber-800">Pick the supplier you paid.</p>}
          </div>
          <ul className="space-y-1 rounded-card border border-border bg-surface-low/60 px-4 py-3 text-sm text-ink">
            <li>✓ Stock goes up by <b>{totals.pieces}</b> {totals.pieces === 1 ? "piece" : "pieces"}{damagedAside ? ` (${damagedAside} damaged kept aside)` : ""}</li>
            <li>✓ Cost price updated, so profit is real</li>
            {pay !== "paid" && totals.total > 0 && <li>✓ You owe the supplier {rupees(pay === "part" && paidPaise > 0 ? totals.total - paidPaise : totals.total)}</li>}
            {poId && short > 0 && <li>✓ {short} still to come is tracked on the order</li>}
          </ul>
          {needsAction && <p className="text-xs font-semibold text-amber-800">Pick what to do with the damaged pieces.</p>}
          <button type="button" onClick={save} disabled={!ready || saving} className="btn-primary flex h-11 w-full items-center justify-center gap-2 disabled:opacity-50">
            {saving && <Loader2 size={16} className="animate-spin" />} Save stock in
          </button>
        </aside>
      </div>
    </div>
  );
}
