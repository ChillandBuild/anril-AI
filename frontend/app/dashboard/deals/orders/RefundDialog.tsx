"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Check, Loader2, Lock, Undo2, X, Zap } from "lucide-react";
import { api, type OrderDetail, type RefundMethod } from "@/lib/api";
import { cn } from "@/lib/utils";
import { reportSend, rupees } from "./orderUi";

const REASONS = ["Customer changed mind", "Wrong size / colour", "Damaged", "Late delivery", "Out of stock", "Other"];

/** Cancel or refund one order. Owner, or a role with "Refund orders". */
export function RefundDialog({ order, onClose, onDone }: { order: OrderDetail; onClose: () => void; onDone: () => void }) {
  const held = order.refundable_paise;
  const [mode, setMode] = useState<"cancel" | "full" | "part">(held > 0 ? "full" : "cancel");
  const [reason, setReason] = useState("");
  const [other, setOther] = useState("");
  const [method, setMethod] = useState<RefundMethod>(order.razorpay_refundable_paise > 0 ? "razorpay" : "cash");
  const [amountText, setAmountText] = useState(String(held / 100));
  const [busy, setBusy] = useState(false);
  // Part refund by items: deal_item_id -> pieces picked (they go back on the shelf).
  const [picked, setPicked] = useState<Record<string, number>>({});
  const returnable = order.items_full.filter((i) => (order.returnable?.[i.id] ?? 0) > 0);

  function pick(id: string, qty: number) {
    const next = { ...picked, [id]: qty };
    if (!qty) delete next[id];
    setPicked(next);
    // The amount follows what was picked (the line's price, after the order's discount share).
    const share = order.total_paise && order.items_full.length ? order.total_paise / order.items_full.reduce((a, i) => a + i.unit_price_paise * i.qty, 0) : 1;
    const sum = order.items_full.reduce((a, i) => a + Math.round((next[i.id] ?? 0) * i.unit_price_paise * share), 0);
    if (sum) setAmountText(String(Math.min(sum, held) / 100));
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const amount = mode === "full" ? held : mode === "part" ? Math.round((Number(amountText) || 0) * 100) : 0;
  const first = (order.customer_full.name || "").split(" ")[0] || "The customer";
  const stockBack = mode !== "part" && order.payment === "paid" && order.items_full.length > 0;
  const tooMuchForLink = method === "razorpay" && amount > order.razorpay_refundable_paise;
  const why = reason === "Other" ? other.trim() : reason;

  async function submit() {
    if (!why) return toast.error("Pick why");
    if (mode === "part" && (amount < 100 || amount > held)) return toast.error(`Type an amount up to ${rupees(held)}`);
    setBusy(true);
    try {
      const items = mode === "part" ? Object.entries(picked).map(([deal_item_id, qty]) => ({ deal_item_id, qty })) : undefined;
      const out = await api.orders.refund(order.id, {
        mode, reason: why, ...(mode === "cancel" ? {} : { method, amount_paise: mode === "part" ? amount : undefined, items }),
      });
      toast.success(mode === "cancel" ? "Order cancelled" : `${rupees(amount)} refunded${out.credit_note ? ` · credit note ${out.credit_note}` : ""}`);
      if (out.short_paise) toast.error(`Razorpay didn't take ${rupees(out.short_paise)} of it. Give that back by cash or UPI.`);
      if (mode !== "cancel") reportSend(order.id, "refund", out.message, onDone);
      onDone();
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "The refund didn't go through");
    } finally {
      setBusy(false);
    }
  }

  const modes = [
    { key: "cancel" as const, title: "Cancel order", sub: held > 0 ? "only when nothing was paid" : "nothing paid back", disabled: held > 0 },
    { key: "full" as const, title: "Full refund", sub: held > 0 ? `${rupees(held)} ${order.payment === "advance" ? "advance paid" : "paid"}` : "nothing paid", disabled: held <= 0 },
    { key: "part" as const, title: "Part refund", sub: "pick items or an amount", disabled: held <= 0 },
  ];
  const methods: { key: RefundMethod; label: string; icon?: typeof Zap; disabled?: boolean; title?: string }[] = [
    { key: "razorpay", label: "Razorpay (auto, 5-7 days)", icon: Zap, disabled: order.razorpay_refundable_paise <= 0,
      title: order.razorpay_refundable_paise <= 0 ? "Nothing on this order was paid by link" : undefined },
    { key: "cash", label: "Cash" },
    { key: "upi", label: "UPI" },
    { key: "bank_transfer", label: "Bank" },
  ];

  return (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-stone-950/40 p-4 backdrop-blur-[2px]" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="refund-title" onClick={(e) => e.stopPropagation()}
        className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-3xl bg-white p-5 shadow-2xl sm:p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 id="refund-title" className="inline-flex items-center gap-2 font-display text-lg font-bold text-[#0A1528]">
            <Undo2 size={18} /> Cancel or refund order {order.label}
          </h2>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-[#94a3b8] hover:bg-stone-100 hover:text-[#0A1528]"><X size={18} /></button>
        </div>

        <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="What to do">
          {modes.map((m) => (
            <button key={m.key} type="button" role="radio" aria-checked={mode === m.key} disabled={m.disabled}
              onClick={() => setMode(m.key)}
              className={cn("rounded-2xl border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-45",
                mode === m.key ? "border-primary bg-primary-50/70 ring-2 ring-primary/15" : "border-[#e2e8f0] hover:border-slate-300")}>
              <span className="flex items-center gap-2 font-label text-sm font-bold text-[#0A1528]">
                <span className={cn("flex h-4 w-4 items-center justify-center rounded-full border-2", mode === m.key ? "border-primary" : "border-[#cbd5e1]")}>
                  {mode === m.key && <span className="h-2 w-2 rounded-full bg-primary" />}
                </span>
                {m.title}
              </span>
              <span className="mt-0.5 block pl-6 text-xs text-on-surface-muted">{m.sub}</span>
            </button>
          ))}
        </div>

        <p className="mb-2 mt-5 font-label text-xs font-bold text-[#0A1528]">Why? <span className="font-normal text-on-surface-muted">(one tap, shows in Reports)</span></p>
        <div className="flex flex-wrap gap-1.5">
          {REASONS.map((r) => (
            <button key={r} type="button" onClick={() => setReason(r)} aria-pressed={reason === r}
              className={cn("rounded-full border px-3 py-1.5 font-label text-xs font-bold",
                reason === r ? "border-primary bg-primary-50 text-primary-800" : "border-[#e2e8f0] text-[#334155] hover:border-slate-300")}>
              {r}
            </button>
          ))}
        </div>
        {reason === "Other" && (
          <input value={other} onChange={(e) => setOther(e.target.value)} placeholder="What happened?" maxLength={200} autoFocus
            className="mt-2 h-9 w-full rounded-xl border border-[#e2e8f0] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary-200" />
        )}

        {mode !== "cancel" && (
          <div className="mt-5 grid gap-3 sm:grid-cols-[1fr_180px]">
            <div>
              <p className="mb-2 font-label text-xs font-bold text-[#0A1528]">Pay back by</p>
              <div className="flex flex-wrap gap-1.5">
                {methods.map((m) => {
                  const Icon = m.icon;
                  return (
                    <button key={m.key} type="button" disabled={m.disabled} title={m.title} onClick={() => setMethod(m.key)} aria-pressed={method === m.key}
                      className={cn("inline-flex items-center gap-1 rounded-xl border px-3 py-1.5 font-label text-xs font-bold disabled:cursor-not-allowed disabled:opacity-40",
                        method === m.key ? "border-primary bg-primary-50 text-primary-800" : "border-[#e2e8f0] text-[#334155]")}>
                      {Icon && <Icon size={12} />} {m.label}
                    </button>
                  );
                })}
              </div>
            </div>
            <label className="block">
              <span className="mb-2 block font-label text-xs font-bold text-[#0A1528]">Amount</span>
              <span className="relative block">
                <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-on-surface-muted">₹</span>
                <input value={mode === "full" ? String(held / 100) : amountText} disabled={mode === "full"} inputMode="decimal" aria-label="Refund amount"
                  onChange={(e) => setAmountText(e.target.value.replace(/[^\d.]/g, ""))}
                  className="h-10 w-full rounded-xl border border-[#e2e8f0] pl-7 pr-3 text-sm font-bold tabular-nums focus:outline-none focus:ring-2 focus:ring-primary-200 disabled:bg-[#f8fafc]" />
              </span>
            </label>
          </div>
        )}
        {mode === "part" && returnable.length > 0 && (
          <div className="mt-4">
            <p className="mb-2 font-label text-xs font-bold text-[#0A1528]">Items coming back <span className="font-normal text-on-surface-muted">(optional: they go back to stock)</span></p>
            <ul className="divide-y divide-[#f1f5f9] rounded-2xl border border-[#e2e8f0]">
              {returnable.map((i) => {
                const max = order.returnable[i.id];
                const n = picked[i.id] ?? 0;
                return (
                  <li key={i.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                    <input type="checkbox" checked={n > 0} onChange={(e) => pick(i.id, e.target.checked ? 1 : 0)} aria-label={`Return ${i.name}`}
                      className="h-4 w-4 accent-[var(--primary)]" />
                    <span className="min-w-0 flex-1 truncate">{i.name}{i.variant_label ? <span className="text-on-surface-muted"> · {i.variant_label}</span> : null}</span>
                    {max > 1 && n > 0 && (
                      <select value={n} onChange={(e) => pick(i.id, Number(e.target.value))} aria-label={`How many ${i.name}`}
                        className="h-8 rounded-lg border border-[#e2e8f0] px-2 text-xs">
                        {Array.from({ length: max }, (_, k) => k + 1).map((k) => <option key={k} value={k}>{k}</option>)}
                      </select>
                    )}
                    <span className="w-20 text-right text-xs text-on-surface-muted">{rupees(i.unit_price_paise)} each</span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        {tooMuchForLink && mode !== "cancel" && (
          <p className="mt-2 text-xs text-amber-800">Only {rupees(order.razorpay_refundable_paise)} was paid by link. Refund the rest by cash or UPI.</p>
        )}

        <ul className="mt-5 space-y-1.5 rounded-2xl bg-[#f8fafc] p-3 text-xs text-[#334155]">
          {mode === "cancel" ? (
            <li className="flex gap-1.5"><Check size={14} className="text-emerald-600" /> The order closes as Cancelled. Nothing was paid, so nothing goes back.</li>
          ) : (
            <>
              {mode === "part" && Object.keys(picked).length > 0 && order.payment === "paid" && (
                <li className="flex gap-1.5"><Check size={14} className="text-emerald-600" />
                  {order.items_full.filter((i) => picked[i.id]).map((i) => `${i.name} × ${picked[i.id]}`).join(", ")} {Object.keys(picked).length === 1 && Object.values(picked)[0] === 1 ? "goes" : "go"} <b>back to stock</b>
                </li>
              )}
              {stockBack && <li className="flex gap-1.5"><Check size={14} className="text-emerald-600" /> {order.items_full.map((i) => i.name).join(", ")} {order.items_full.length === 1 && order.items_full[0].qty === 1 ? "goes" : "go"} <b>back to stock</b></li>}
              {mode === "full" && <li className="flex gap-1.5"><Check size={14} className="text-emerald-600" /> The order closes as Cancelled · refunded</li>}
              {order.invoice_number && order.bill_type === "gst" && <li className="flex gap-1.5"><Check size={14} className="text-emerald-600" /> A <b>credit note</b> is made for GST</li>}
              {order.customer_full.phone && (
                <li className="flex gap-1.5"><Check size={14} className="text-emerald-600" />
                  {first} gets a WhatsApp: &ldquo;{method === "razorpay" ? `Refund ${rupees(amount)} started, 5-7 days` : `${rupees(amount)} given back`}&rdquo;
                </li>
              )}
              <li className="flex gap-1.5"><Check size={14} className="text-emerald-600" /> Money in, Reports and Meta Ads Earned go down by {rupees(amount)}</li>
            </>
          )}
        </ul>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
          <span className="inline-flex items-center gap-1 text-xs text-on-surface-muted"><Lock size={12} /> Only the owner and managers with Refund orders can do this</span>
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="rounded-xl border border-[#e2e8f0] px-4 py-2 font-label text-sm font-bold text-[#334155]">Keep order</button>
            <button type="button" onClick={submit} disabled={busy || (mode !== "cancel" && (amount <= 0 || tooMuchForLink))}
              className="inline-flex items-center gap-2 rounded-xl bg-rose-600 px-4 py-2 font-label text-sm font-bold text-white shadow-sm hover:bg-rose-700 disabled:opacity-50">
              {busy && <Loader2 size={14} className="animate-spin" />}
              {mode === "cancel" ? "Cancel order" : `Refund ${rupees(amount)}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
