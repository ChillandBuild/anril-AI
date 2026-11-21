"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { toast } from "sonner";
import {
  ArrowLeft, Bot, Check, Loader2, Minus, PackageOpen, Pencil, Plus, Search, ShoppingBag, Store, Truck, X,
} from "lucide-react";
import { api, type NewBillItem, type NewBillResult, type NewBillVariant, type SellableBatch } from "@/lib/api";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { cn } from "@/lib/utils";
import { computeBill } from "../orders/billMath";
import { reportSend, rupees } from "../orders/orderUi";

type Line = {
  key: string; item: NewBillItem; variant: NewBillVariant | null; qty: number;
  /** Batches & expiry: sellable batches in the order bills take them; batchId = staff's pick (null = first). */
  batches?: SellableBatch[]; batchId?: string | null;
};
type Method = "cash" | "upi" | "card" | "link";

const METHODS: { value: Method; label: string }[] = [
  { value: "cash", label: "Cash" },
  { value: "upi", label: "UPI" },
  { value: "card", label: "Card" },
  { value: "link", label: "Link" },
];

function priceOf(item: NewBillItem, variant: NewBillVariant | null): number {
  return variant?.price_paise ?? item.price_paise ?? 0;
}

/** The line's batch: the one staff picked, else the first the bill would take (same as the backend). */
function batchOf(l: Line): SellableBatch | null {
  if (!l.batches?.length) return null;
  return l.batches.find((b) => b.id === l.batchId) ?? l.batches[0];
}

/** Price with the batch's small discount (backend stock_batches.sale_price). */
function linePrice(l: Line): number {
  const base = priceOf(l.item, l.variant);
  const pct = batchOf(l)?.discount_pct ?? 0;
  return pct ? Math.round((base * (100 - pct)) / 100) : base;
}

function stockOf(item: NewBillItem): number | null {
  if (item.variants.length) return item.variants.reduce((a, v) => a + v.stock, 0);
  return item.stock;
}

function optionsText(item: NewBillItem): string {
  if (item.kind === "service") return "service";
  const sizes = new Set(item.variants.map((v) => v.size).filter(Boolean));
  const colours = new Set(item.variants.map((v) => v.colour).filter(Boolean));
  const parts = [];
  if (sizes.size) parts.push(`${sizes.size} ${sizes.size === 1 ? "size" : "sizes"}`);
  if (colours.size) parts.push(`${colours.size} ${colours.size === 1 ? "colour" : "colours"}`);
  return parts.join(" · ");
}

function rupeesToPaise(text: string): number {
  const n = Number(text.replace(/[^\d.]/g, ""));
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}

export default function NewBillPage() {
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("deals.manage");
  const { data: options, error } = useSWR("new-bill-options", () => api.orders.billOptions(), { revalidateOnFocus: false });
  const { data: shopRule } = useSWR("orders-advance-rule", () => api.orders.advanceRule(), { revalidateOnFocus: false });

  const [mode, setMode] = useState<"now" | "later">("now");
  const [group, setGroup] = useState("all");
  const [query, setQuery] = useState("");
  const [picking, setPicking] = useState<NewBillItem | null>(null);
  const [colour, setColour] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [known, setKnown] = useState<{ name?: string | null; orders?: number } | null>(null);
  const [b2b, setB2b] = useState(false);
  const [gstin, setGstin] = useState("");
  const [business, setBusiness] = useState("");
  const [discountText, setDiscountText] = useState("");
  const [editDiscount, setEditDiscount] = useState(false);
  const [billType, setBillType] = useState<"gst" | "simple">("gst");
  const [soldBy, setSoldBy] = useState<string>("");
  const [method, setMethod] = useState<Method>("cash");
  const [advanceText, setAdvanceText] = useState("");
  const [handover, setHandover] = useState<"pickup" | "courier">("pickup");
  const [readyBy, setReadyBy] = useState("");
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState<NewBillResult | null>(null);
  const [waitFor, setWaitFor] = useState<NewBillVariant | null>(null);

  // Who is this number? (so a returning customer's name fills in)
  useEffect(() => {
    const digits = phone.replace(/\D/g, "");
    if (digits.length < 10) {
      setKnown(null);
      return;
    }
    const t = setTimeout(() => {
      api.orders.findCustomer(phone).then((r) => {
        setKnown(r.found ? { name: r.name, orders: r.orders } : null);
        if (r.found && r.name && !name) setName(r.name);
      }).catch(() => setKnown(null));
    }, 350);
    return () => clearTimeout(t);
    // name is only read to avoid overwriting what was typed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phone]);

  const items = useMemo(() => options?.items ?? [], [options]);
  const groups = useMemo(() => {
    const set = new Set<string>();
    items.forEach((i) => { if (i.group) set.add(i.group); });
    const out = Array.from(set).sort();
    if (items.some((i) => i.kind === "service")) out.push("Services");
    return out;
  }, [items]);
  const shown = items.filter((i) => {
    if (group === "Services" && i.kind !== "service") return false;
    if (group !== "all" && group !== "Services" && i.group !== group) return false;
    return !query.trim() || i.name.toLowerCase().includes(query.trim().toLowerCase());
  });

  const includeGst = options?.prices_include_gst ?? true;
  const totals = computeBill(
    lines.map((l) => ({ unit_price_paise: linePrice(l), qty: l.qty, gst_rate: l.item.gst_rate })),
    { discount_paise: rupeesToPaise(discountText), include_gst: includeGst, bill_type: billType },
  );
  // The shop rule's advance (same as backend order_quotes.advance_for); typing another amount is noted on the order.
  const ruleAdvance = (() => {
    if (!shopRule || shopRule.kind === "none" || !totals.total_paise) return 0;
    if (shopRule.min_total_paise && totals.total_paise < shopRule.min_total_paise) return 0;
    const a = shopRule.kind === "percent" ? Math.round((totals.total_paise * shopRule.value) / 100) : Math.round(shopRule.value * 100);
    return Math.min(a, totals.total_paise);
  })();
  const advance = mode === "later" ? Math.min(advanceText.trim() ? rupeesToPaise(advanceText) : ruleAdvance, totals.total_paise) : totals.total_paise;
  const hasPhone = phone.replace(/\D/g, "").length >= 10;
  const gstRate = (() => {
    const rates = new Set(lines.map((l) => l.item.gst_rate || 0).filter(Boolean));
    return rates.size === 1 ? Array.from(rates)[0] : null;
  })();

  function addLine(item: NewBillItem, variant: NewBillVariant | null) {
    const key = item.id + (variant?.id ?? "");
    setLines((cur) => {
      const found = cur.find((l) => l.key === key);
      if (found) return cur.map((l) => (l.key === key ? { ...l, qty: l.qty + 1 } : l));
      return [...cur, { key, item, variant, qty: 1 }];
    });
    if (item.tracks_batches) {
      api.catalog.itemBatches(item.id, variant?.id ?? null)
        .then((res) => setLines((cur) => cur.map((l) => (l.key === key ? { ...l, batches: res.data } : l))))
        .catch(() => { /* the bill still picks the first-expiring batch by itself */ });
    }
  }

  function tapItem(item: NewBillItem) {
    if (item.variants.length) {
      setPicking(item);
      setColour(item.variants.find((v) => v.colour)?.colour ?? null);
      setWaitFor(null);
      return;
    }
    if (item.price_paise == null) {
      toast.error(`${item.name} has no price yet. Add one in Catalogue.`);
      return;
    }
    addLine(item, null);
  }

  function changeQty(key: string, delta: number) {
    setLines((cur) => cur.flatMap((l) => (l.key !== key ? [l] : l.qty + delta <= 0 ? [] : [{ ...l, qty: l.qty + delta }])));
  }

  function reset() {
    setLines([]); setPhone(""); setName(""); setKnown(null); setB2b(false); setGstin(""); setBusiness("");
    setDiscountText(""); setEditDiscount(false); setBillType("gst"); setMethod("cash"); setAdvanceText("");
    setHandover("pickup"); setReadyBy(""); setDone(null); setPicking(null);
  }

  async function save() {
    if (!lines.length) {
      toast.error("Add at least one item");
      return;
    }
    if (method === "link" && !hasPhone) {
      toast.error("A payment link needs their phone number");
      return;
    }
    if (b2b && !/^[0-9]{2}[A-Z0-9]{13}$/.test(gstin.trim().toUpperCase())) {
      toast.error("Check the GSTIN: 15 letters and numbers");
      return;
    }
    setSaving(true);
    try {
      const out = await api.orders.createBill({
        mode,
        phone: hasPhone ? phone : undefined,
        name: name.trim() || undefined,
        items: lines.map((l) => ({ catalog_item_id: l.item.id, variant_id: l.variant?.id ?? null, qty: l.qty, batch_id: l.batchId ?? null })),
        discount_paise: totals.discount_paise,
        bill_type: billType,
        gstin: b2b ? gstin.trim().toUpperCase() : undefined,
        business: b2b ? business.trim() || undefined : undefined,
        sold_by: soldBy && soldBy !== "ai" ? soldBy : null,
        sold_by_ai: soldBy === "ai",
        method,
        advance_paise: mode === "later" ? advance : undefined,
        handover: mode === "later" ? handover : undefined,
        ready_by: mode === "later" && readyBy ? readyBy : undefined,
      });
      setDone(out);
      reportSend(out.order.id, method === "link" ? "pay_link" : "bill", out.message);
      if (out.stock_short.length) {
        toast.message(`Sold more than the shelf shows: ${out.stock_short.map((s) => `${s.name} (${s.available} left)`).join(", ")}. Check the stock.`);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't save the bill");
    } finally {
      setSaving(false);
    }
  }

  async function addToWaitlist(variant: NewBillVariant) {
    if (!picking) return;
    if (!hasPhone) {
      toast.error("Type their phone number on the right first");
      return;
    }
    try {
      await api.orders.waitlist({ catalog_item_id: picking.id, variant_id: variant.id, phone, name: name.trim() || undefined });
      toast.success(`Saved. ${name.trim() || "They"} will be on the list for ${picking.name} ${variant.label}.`);
      setWaitFor(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't save it");
    }
  }

  if (!canManage) {
    return <p className="py-20 text-center text-sm text-on-surface-muted">You need Deals manage access to make bills.</p>;
  }

  if (done) {
    const o = done.order;
    return (
      <div className="mx-auto max-w-lg py-10">
        <div className="rounded-3xl border border-[#e2e8f0] bg-white p-6 text-center shadow-sm">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-emerald-50 text-emerald-600"><Check size={24} strokeWidth={3} /></span>
          <h1 className="mt-3 font-display text-xl font-bold text-[#0A1528]">Bill saved · {rupees(o.total_paise)}</h1>
          <p className="mt-1 text-sm text-on-surface-muted">
            {o.invoice_number ? `Bill ${o.invoice_number}` : `Order ${o.label}`}
            {o.payment === "paid" ? " · paid" : o.payment === "advance" ? ` · ${rupees(o.balance_paise)} left to pay` : " · waiting for payment"}
          </p>
          {done.message?.sent && <p className="mt-3 text-xs font-bold text-emerald-700">Sent to {o.customer_full.name || "them"} on WhatsApp</p>}
          {done.message && !done.message.sent && done.message.share_url && (
            <a href={done.message.share_url} target="_blank" rel="noopener noreferrer"
              onClick={() => api.orders.shared(o.id, method === "link" ? "pay_link" : "bill", done.message!.text).catch(() => {})}
              className="mt-4 inline-flex items-center gap-2 rounded-xl bg-[#25D366] px-4 py-2.5 font-label text-sm font-bold text-white shadow-sm hover:opacity-90">
              Share on WhatsApp
            </a>
          )}
          <div className="mt-6 flex justify-center gap-2">
            <Link href={`/dashboard/deals/orders/${o.id}`} className="rounded-xl border border-[#e2e8f0] px-4 py-2 font-label text-sm font-bold text-[#334155]">Open order</Link>
            <button type="button" onClick={reset} className="rounded-xl bg-primary px-4 py-2 font-label text-sm font-bold text-white">＋ Next bill</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 md:-mt-3">
      <div className="flex flex-wrap items-center gap-2">
        <Link href="/dashboard/deals" className="inline-flex items-center gap-1.5 rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 font-label text-xs font-bold text-[#334155] shadow-sm hover:border-slate-300">
          <ArrowLeft size={14} /> Orders
        </Link>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_400px]">
        {/* ── left: items ─────────────────────────────────── */}
        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex rounded-xl border border-[#e2e8f0] bg-white p-1 shadow-sm" role="group" aria-label="Taking it now or later">
              {([["now", "Taking it now", ShoppingBag], ["later", "Deliver later", Truck]] as const).map(([value, label, Icon]) => (
                <button key={value} type="button" onClick={() => setMode(value)} aria-pressed={mode === value}
                  className={cn("inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-label text-xs font-bold transition-colors",
                    mode === value ? "bg-primary text-white" : "text-[#475569] hover:text-[#0A1528]")}>
                  <Icon size={13} /> {label}
                </button>
              ))}
            </div>
            <div className="flex min-w-0 flex-wrap gap-1.5">
              {["all", ...groups].map((g) => (
                <button key={g} type="button" onClick={() => setGroup(g)} aria-pressed={group === g}
                  className={cn("rounded-full border px-3 py-1.5 font-label text-xs font-bold",
                    group === g ? "border-primary bg-primary-50 text-primary-800" : "border-[#e2e8f0] bg-white text-[#334155]")}>
                  {g === "all" ? "All" : g}
                </button>
              ))}
            </div>
            <label className="relative ml-auto w-full sm:w-52">
              <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#64748b]" />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find an item" type="search" aria-label="Find an item"
                className="h-9 w-full rounded-xl border border-[#e2e8f0] bg-white pl-9 pr-3 text-xs focus:outline-none focus:ring-2 focus:ring-primary-200" />
            </label>
          </div>

          {error ? (
            <p className="rounded-2xl border border-[#e2e8f0] bg-white p-8 text-center text-sm text-on-surface-muted">Couldn&apos;t load your items. Refresh to try again.</p>
          ) : !options ? (
            <div className="flex min-h-[200px] items-center justify-center"><Loader2 className="animate-spin text-primary" /></div>
          ) : items.length === 0 ? (
            <div className="rounded-2xl border border-[#e2e8f0] bg-white p-10 text-center">
              <PackageOpen size={26} className="mx-auto text-primary-300" />
              <p className="mt-2 text-sm font-bold text-[#0A1528]">No items to sell yet</p>
              <p className="mt-1 text-xs text-on-surface-muted">Add what you sell in Catalogue (status Ready), then bill it here.</p>
              <Link href="/dashboard/catalog" className="mt-3 inline-block text-xs font-bold text-primary-700">Open Catalogue</Link>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
              {shown.map((item) => {
                const stock = stockOf(item);
                const inCart = lines.filter((l) => l.item.id === item.id).reduce((a, l) => a + l.qty, 0);
                return (
                  <button key={item.id} type="button" onClick={() => tapItem(item)}
                    className={cn("flex flex-col gap-1 rounded-2xl border bg-white p-3.5 text-left shadow-sm transition-all hover:-translate-y-px hover:shadow",
                      picking?.id === item.id ? "border-primary ring-2 ring-primary/15" : "border-[#e2e8f0]")}>
                    <span className="flex items-start justify-between gap-2">
                      <span className="font-label text-sm font-bold text-[#0A1528]">{item.name}</span>
                      {inCart > 0 && <span className="rounded-full bg-primary px-1.5 font-label text-[10px] font-bold text-white">{inCart}</span>}
                    </span>
                    {optionsText(item) && <span className="text-[11px] text-on-surface-muted">{optionsText(item)}</span>}
                    <span className="mt-1 flex items-end justify-between">
                      <span className="font-display text-base font-bold tabular-nums text-[#0A1528]">{item.price_paise != null ? rupees(item.price_paise) : "No price"}</span>
                      {stock != null && item.kind !== "service" && (
                        <span className={cn("text-[11px] font-semibold", stock === 0 ? "text-rose-600" : stock <= 2 ? "text-amber-700" : "text-on-surface-muted")}>
                          {stock === 0 ? "out of stock" : `${stock} in stock`}
                        </span>
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          {picking && (
            <div className="rounded-2xl border-2 border-primary bg-white p-4 shadow-lg">
              <div className="flex items-start justify-between">
                <h2 className="font-label text-sm font-bold text-[#0A1528]">{picking.name} · pick {picking.variants.some((v) => v.colour) ? "colour and size" : "size"}</h2>
                <button type="button" onClick={() => setPicking(null)} aria-label="Close" className="text-[#94a3b8] hover:text-[#0A1528]"><X size={16} /></button>
              </div>
              <div className="mt-3 flex flex-wrap gap-6">
                {picking.variants.some((v) => v.colour) && (
                  <div>
                    <p className="mb-1.5 font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">Colour</p>
                    <div className="flex flex-wrap gap-1.5">
                      {Array.from(new Set(picking.variants.map((v) => v.colour).filter(Boolean) as string[])).map((c) => (
                        <button key={c} type="button" onClick={() => { setColour(c); setWaitFor(null); }} aria-pressed={colour === c}
                          className={cn("rounded-full border px-3 py-1.5 font-label text-xs font-bold",
                            colour === c ? "border-primary bg-primary-50 text-primary-800" : "border-[#e2e8f0] text-[#334155]")}>
                          {c}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <div>
                  <p className="mb-1.5 font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">{picking.variants.some((v) => v.size) ? "Size (stock)" : "Stock"}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {picking.variants.filter((v) => !colour || v.colour === colour).map((v) => (
                      <button key={v.id} type="button"
                        onClick={() => (v.stock <= 0 ? setWaitFor(v) : (addLine(picking, v), toast.success(`${picking.name} ${v.label} added`)))}
                        className={cn("rounded-full border px-3 py-1.5 font-label text-xs font-bold tabular-nums",
                          v.stock <= 0 ? "border-dashed border-[#e2e8f0] text-[#94a3b8] line-through"
                            : v.stock === 1 ? "border-amber-300 bg-amber-50 text-amber-800" : "border-[#e2e8f0] text-[#334155] hover:border-primary")}>
                        {(v.size ?? v.colour ?? "").toString()} · {v.stock}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              {(() => {
                const list = picking.variants.filter((v) => !colour || v.colour === colour);
                const last = list.filter((v) => v.stock === 1).map((v) => v.label);
                const out = list.filter((v) => v.stock <= 0).map((v) => v.size ?? v.label);
                if (!last.length && !out.length) return null;
                return (
                  <p className="mt-3 text-xs text-amber-800">
                    {last.length ? `${last.join(", ")} is the last piece. ` : ""}
                    {out.length ? `${out.join(", ")} is out: tap it to put the customer on the "tell me when back" list.` : ""}
                  </p>
                );
              })()}
              {waitFor && (
                <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-[#f8fafc] p-3 text-xs">
                  <span className="text-[#334155]">Tell {name.trim() || "this customer"} when <b>{picking.name} {waitFor.label}</b> is back?</span>
                  <button type="button" onClick={() => addToWaitlist(waitFor)} className="rounded-lg bg-primary px-3 py-1.5 font-bold text-white">Yes, save</button>
                  <button type="button" onClick={() => setWaitFor(null)} className="font-bold text-on-surface-muted">No</button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── right: the bill ─────────────────────────────── */}
        <aside id="the-bill" className="h-fit scroll-mt-4 rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm lg:sticky lg:top-4">
          <label className="block">
            <span className="font-label text-xs font-bold text-[#0A1528]">Customer phone</span>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" placeholder="98400 12345 (leave empty for walk-in)"
              className="mt-1 h-10 w-full rounded-xl border border-[#e2e8f0] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary-200" />
          </label>
          {(hasPhone || name) && (
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" aria-label="Customer name"
              className="mt-2 h-9 w-full rounded-xl border border-[#e2e8f0] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary-200" />
          )}
          {known && <p className="mt-1 text-[11px] text-emerald-700">Returning customer{known.orders ? ` · ${known.orders} ${known.orders === 1 ? "order" : "orders"} before` : ""}</p>}

          <label className="mt-3 flex cursor-pointer items-center gap-2 text-xs">
            <input type="checkbox" checked={b2b} onChange={(e) => setB2b(e.target.checked)} className="h-4 w-4 accent-[var(--primary)]" />
            <span className="font-bold text-[#0A1528]">Business customer (B2B)</span>
            <span className="text-on-surface-muted">· their GSTIN, for input credit</span>
          </label>
          {b2b && (
            <div className="mt-2 grid grid-cols-2 gap-2">
              <input value={gstin} onChange={(e) => setGstin(e.target.value.toUpperCase())} maxLength={15} placeholder="GSTIN" aria-label="GSTIN"
                className="h-9 rounded-xl border border-[#e2e8f0] px-3 text-xs uppercase focus:outline-none focus:ring-2 focus:ring-primary-200" />
              <input value={business} onChange={(e) => setBusiness(e.target.value)} placeholder="Business name" aria-label="Business name"
                className="h-9 rounded-xl border border-[#e2e8f0] px-3 text-xs focus:outline-none focus:ring-2 focus:ring-primary-200" />
            </div>
          )}

          <div className="mt-4 border-t border-[#eef2f6] pt-3">
            {lines.length === 0 ? (
              <p className="py-4 text-center text-xs text-on-surface-muted">Tap an item to add it.</p>
            ) : (
              <ul className="space-y-2">
                {lines.map((l) => (
                  <li key={l.key} className="flex items-center gap-2">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-label text-[13px] font-bold text-[#0A1528]">
                        {l.item.name}{l.variant ? ` · ${l.variant.label}` : ""}
                      </span>
                      {l.item.tracks_batches && (l.batches?.length ? (
                        <select value={batchOf(l)?.id ?? ""} aria-label={`Batch of ${l.item.name}`}
                          onChange={(e) => setLines((cur) => cur.map((x) => (x.key === l.key ? { ...x, batchId: e.target.value } : x)))}
                          className="mt-0.5 max-w-full truncate rounded border border-[#e2e8f0] bg-white px-1 py-0.5 text-[11px] text-[#475569]">
                          {l.batches.map((b, i) => (
                            <option key={b.id} value={b.id}>
                              {b.label} · {b.quantity} left{b.discount_pct ? ` · ${b.discount_pct}% off` : ""}{i === 0 && !l.batchId ? " (first)" : ""}
                            </option>
                          ))}
                        </select>
                      ) : l.batches ? (
                        <span className="block text-[11px] text-rose-600">No batch that can be sold (expired or none left)</span>
                      ) : null)}
                    </span>
                    <span className="flex items-center rounded-lg border border-[#e2e8f0]">
                      <button type="button" onClick={() => changeQty(l.key, -1)} aria-label="One less" className="px-1.5 py-1 text-[#475569]"><Minus size={12} /></button>
                      <span className="w-6 text-center text-xs font-bold tabular-nums">{l.qty}</span>
                      <button type="button" onClick={() => changeQty(l.key, 1)} aria-label="One more" className="px-1.5 py-1 text-[#475569]"><Plus size={12} /></button>
                    </span>
                    <span className="w-20 text-right text-sm font-bold tabular-nums">{rupees(linePrice(l) * l.qty)}</span>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-3 space-y-1 text-xs text-on-surface-muted">
              <div className="flex items-center justify-between">
                <button type="button" onClick={() => setEditDiscount((v) => !v)} className="inline-flex items-center gap-1 hover:text-[#0A1528]">Discount <Pencil size={11} /></button>
                {editDiscount ? (
                  <input value={discountText} onChange={(e) => setDiscountText(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" autoFocus placeholder="₹0" aria-label="Discount"
                    className="h-7 w-24 rounded-lg border border-[#e2e8f0] px-2 text-right text-xs tabular-nums focus:outline-none focus:ring-2 focus:ring-primary-200" />
                ) : <span className="tabular-nums">{totals.discount_paise ? `− ${rupees(totals.discount_paise)}` : "₹0"}</span>}
              </div>
              {billType === "gst" && totals.gst_paise > 0 && (
                <div className="flex justify-between">
                  <span>{includeGst ? "GST inside price" : "GST"}{gstRate ? ` (CGST + SGST ${gstRate / 2}%)` : ""}</span>
                  <span className="tabular-nums">{rupees(totals.gst_paise)}</span>
                </div>
              )}
            </div>
            <div className="mt-2 flex items-baseline justify-between">
              <span className="font-display text-lg font-bold text-[#0A1528]">Total</span>
              <span className="font-display text-2xl font-extrabold tabular-nums text-[#0A1528]">{rupees(totals.total_paise)}</span>
            </div>
          </div>

          <div className="mt-3 grid grid-cols-2 gap-2" role="group" aria-label="Bill type">
            {(["gst", "simple"] as const).map((t) => (
              <button key={t} type="button" onClick={() => setBillType(t)} aria-pressed={billType === t}
                className={cn("rounded-xl border py-2 font-label text-xs font-bold",
                  billType === t ? "border-primary bg-primary-50 text-primary-800" : "border-[#e2e8f0] text-[#334155]")}>
                {t === "gst" ? "GST bill" : "Simple bill"}
              </button>
            ))}
          </div>
          {billType === "gst" && options && !options.gstin_set && (
            <p className="mt-1 text-[11px] text-amber-800">Your GSTIN isn&apos;t set, so the bill prints without it. Add it in Settings › Business details.</p>
          )}

          {options && (options.team.length > 0) && (
            <div className="mt-3">
              <p className="mb-1.5 font-label text-xs font-bold text-[#0A1528]">Handled by</p>
              <div className="flex flex-wrap gap-1.5">
                {[...options.team.map((t) => ({ id: t.id, label: t.name })), { id: "ai", label: "AI agent" }].map((t) => (
                  <button key={t.id} type="button" onClick={() => setSoldBy(soldBy === t.id ? "" : t.id)} aria-pressed={soldBy === t.id}
                    className={cn("inline-flex items-center gap-1 rounded-full border px-3 py-1 font-label text-xs font-bold",
                      soldBy === t.id ? "border-primary bg-primary-50 text-primary-800" : "border-[#e2e8f0] text-[#334155]")}>
                    {t.id === "ai" && <Bot size={12} />} {t.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {mode === "later" && (
            <div className="mt-3 space-y-2 rounded-xl bg-[#f8fafc] p-3">
              <div className="flex gap-1.5" role="group" aria-label="How it reaches them">
                {([["pickup", "Pickup from shop", Store], ["courier", "Courier", Truck]] as const).map(([value, label, Icon]) => (
                  <button key={value} type="button" onClick={() => setHandover(value)} aria-pressed={handover === value}
                    className={cn("inline-flex flex-1 items-center justify-center gap-1 rounded-lg border py-1.5 font-label text-xs font-bold",
                      handover === value ? "border-primary bg-white text-primary-800" : "border-[#e2e8f0] text-[#475569]")}>
                    <Icon size={12} /> {label}
                  </button>
                ))}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <label className="text-[11px] font-bold text-[#334155]">Advance now
                  <input value={advanceText} onChange={(e) => setAdvanceText(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal"
                    placeholder={ruleAdvance ? `₹${ruleAdvance / 100} (shop rule)` : "₹0"}
                    className="mt-1 h-9 w-full rounded-lg border border-[#e2e8f0] bg-white px-2 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-primary-200" />
                </label>
                <label className="text-[11px] font-bold text-[#334155]">Ready by
                  <input type="date" value={readyBy} onChange={(e) => setReadyBy(e.target.value)}
                    className="mt-1 h-9 w-full rounded-lg border border-[#e2e8f0] bg-white px-2 text-xs focus:outline-none focus:ring-2 focus:ring-primary-200" />
                </label>
              </div>
              {totals.total_paise > 0 && <p className="text-[11px] text-on-surface-muted">Advance {rupees(advance)}{!advanceText.trim() && ruleAdvance ? " (shop rule)" : advanceText.trim() && ruleAdvance && advance !== ruleAdvance ? ` · shop rule says ${rupees(ruleAdvance)}, the change is noted` : ""} · balance {rupees(totals.total_paise - advance)} when ready.</p>}
            </div>
          )}

          <div className="mt-3 grid grid-cols-4 gap-1.5" role="group" aria-label="How they pay">
            {METHODS.map((m) => (
              <button key={m.value} type="button" onClick={() => setMethod(m.value)} aria-pressed={method === m.value}
                disabled={m.value === "link" && !hasPhone} title={m.value === "link" && !hasPhone ? "Needs their phone number" : undefined}
                className={cn("rounded-xl border py-2 font-label text-xs font-bold disabled:opacity-40",
                  method === m.value ? "border-primary bg-primary-50 text-primary-800" : "border-[#e2e8f0] text-[#334155]")}>
                {m.label}
              </button>
            ))}
          </div>

          <button type="button" onClick={save} disabled={saving || !lines.length}
            className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-3 font-label text-sm font-bold text-white shadow-sm hover:bg-primary/90 disabled:opacity-50">
            {saving && <Loader2 size={15} className="animate-spin" />}
            {method === "link" ? `Send pay link · ${rupees(advance || totals.total_paise)}` : hasPhone ? "Save bill · send on WhatsApp" : "Save bill"}
          </button>
          <p className="mt-2 text-center text-[11px] text-on-surface-muted">
            {hasPhone ? "The bill goes to them on WhatsApp." : "No number? It saves as a walk-in sale. Money and stock still count."}
          </p>
        </aside>
      </div>
      {/* Phones: the bill is below the items, so keep the total in reach. */}
      {lines.length > 0 && (
        <a href="#the-bill"
          className="fixed inset-x-4 bottom-4 z-30 flex items-center justify-between rounded-2xl bg-[#0A1528] px-4 py-3 font-label text-sm font-bold text-white shadow-xl lg:hidden">
          <span>{lines.reduce((a, l) => a + l.qty, 0)} {lines.reduce((a, l) => a + l.qty, 0) === 1 ? "item" : "items"} · {rupees(totals.total_paise)}</span>
          <span>Go to bill ↓</span>
        </a>
      )}
    </div>
  );
}
