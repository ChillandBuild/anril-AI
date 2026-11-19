"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { toast } from "sonner";
import {
  ArrowLeft, Bot, Check, ExternalLink, FileText, Loader2, MessageCircle, Send, Store, Truck, User,
} from "lucide-react";
import { api, type OrderDetail } from "@/lib/api";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { cn } from "@/lib/utils";
import { DeliveryBadge, PaymentBadge, Ticks, dateTime, reportSend, rupees } from "../orderUi";

type Step = { key: string; label: string; at: string | null; done: boolean };

function stepsFor(o: OrderDetail): Step[] {
  const paidOrAdvance = o.payment === "paid" || o.payment === "advance";
  if (o.handover === "taken") {
    return [
      { key: "billed", label: "Billed", at: o.created_at, done: true },
      { key: "paid", label: o.payment === "paid" ? "Paid" : "Payment", at: o.won_at, done: o.payment === "paid" },
      { key: "taken", label: "Taken in store", at: o.delivered_at, done: true },
    ];
  }
  if (o.handover === "courier") {
    return [
      { key: "ordered", label: "Ordered", at: o.created_at, done: true },
      { key: "ready", label: "Packed", at: o.ready_at, done: ["ready", "shipped", "delivered"].includes(o.delivery) },
      { key: "shipped", label: "Shipped", at: o.shipped_at, done: ["shipped", "delivered"].includes(o.delivery) },
      { key: "delivered", label: "Delivered", at: o.delivered_at, done: o.delivery === "delivered" },
    ];
  }
  return [
    { key: "ordered", label: paidOrAdvance && o.payment === "advance" ? "Advance paid" : "Ordered", at: o.created_at, done: true },
    { key: "working", label: "Working on it", at: null, done: ["working", "ready", "delivered"].includes(o.delivery) },
    { key: "ready", label: "Ready", at: o.ready_at, done: ["ready", "delivered"].includes(o.delivery) },
    { key: "delivered", label: "Picked up", at: o.delivered_at, done: o.delivery === "delivered" },
  ];
}

const KIND_TITLE: Record<string, string> = {
  bill: "Bill", confirmed: "Order confirmed", ready: "Ready", shipped: "On the way", delivered: "Delivered",
  reminder: "Payment reminder", pay_link: "Payment link",
};

const METHODS = [
  { value: "cash", label: "Cash" },
  { value: "upi", label: "UPI" },
  { value: "card", label: "Card" },
  { value: "bank_transfer", label: "Bank" },
] as const;

function initials(name: string | null | undefined) {
  const parts = (name || "?").trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

function Panel({ title, right, children, className }: { title?: React.ReactNode; right?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm sm:p-5", className)}>
      {(title || right) && (
        <div className="mb-3 flex items-center justify-between gap-3">
          {title && <h2 className="font-label text-sm font-bold text-[#0A1528]">{title}</h2>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export default function OrderPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const search = useSearchParams();
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("deals.manage");
  const { data: order, error, mutate } = useSWR<OrderDetail>(["order", id], () => api.orders.get(id));
  const [busy, setBusy] = useState<string | null>(null);
  const [payOpen, setPayOpen] = useState(search.get("focus") === "payment");
  const [payAmount, setPayAmount] = useState("");
  const [payMethod, setPayMethod] = useState<(typeof METHODS)[number]["value"]>("cash");
  const [trackOpen, setTrackOpen] = useState(search.get("focus") === "tracking");
  const [courier, setCourier] = useState("");
  const [tracking, setTracking] = useState("");

  useEffect(() => {
    if (order && !payAmount) setPayAmount(String(order.balance_paise / 100));
  }, [order, payAmount]);

  if (error) {
    return (
      <div className="py-20 text-center">
        <p className="text-sm text-on-surface-muted">This order couldn&apos;t be loaded.</p>
        <Link href="/dashboard/deals" className="mt-3 inline-block text-xs font-bold text-primary-700">Back to orders</Link>
      </div>
    );
  }
  if (!order) return <div className="flex min-h-[320px] items-center justify-center"><Loader2 className="animate-spin text-primary" /></div>;

  const o = order;
  const who = o.customer_full.name || o.customer_full.phone || "Walk-in customer";
  const first = (o.customer_full.name || "").split(" ")[0] || "the customer";
  const open = o.stage !== "won" && o.stage !== "lost";
  const canDeliver = canManage && o.stage !== "lost" && o.handover !== "taken" && o.delivery !== "delivered";

  async function run<T>(key: string, fn: () => Promise<T>, after?: (out: T) => void) {
    setBusy(key);
    try {
      const out = await fn();
      after?.(out);
      await mutate();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "That didn't work. Try again.");
    } finally {
      setBusy(null);
    }
  }

  function recordPayment() {
    const paise = Math.round(Number(payAmount) * 100);
    if (!paise || paise < 100) {
      toast.error("Type the amount they paid");
      return;
    }
    run("pay", () => api.orders.addPayment(o.id, { amount_paise: paise, method: payMethod }), (out) => {
      toast.success(out.paid_in_full ? "Paid in full" : `${rupees(paise)} recorded`);
      setPayOpen(false);
      setPayAmount("");
      if (out.stock_warnings.length) toast.message(`Stock didn't go down for ${out.stock_warnings.map((w) => w.name).join(", ")}: not enough on the shelf.`);
    });
  }

  const steps = stepsFor(o);
  const nextStep = (() => {
    if (!canDeliver) return null;
    if (o.handover === "courier") {
      if (o.delivery === "shipped") return { label: "Mark delivered", action: "delivered" as const };
      if (o.delivery === "ready") return { label: "Add tracking · sends it", action: "track" as const };
      return { label: "Mark packed", action: "ready" as const };
    }
    if (o.delivery === "ready") return { label: "Mark picked up", action: "delivered" as const };
    return { label: `Mark ready · tells ${first}`, action: "ready" as const };
  })();

  return (
    <div className="mx-auto max-w-[1280px] space-y-4 md:-mt-3">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={() => router.push("/dashboard/deals")}
          className="inline-flex items-center gap-1.5 rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 font-label text-xs font-bold text-[#334155] shadow-sm hover:border-slate-300">
          <ArrowLeft size={14} /> Orders
        </button>
        <div className="min-w-0 flex-1">
          <h1 className="truncate font-display text-lg font-bold text-[#0A1528]">Order {o.label} · {who}</h1>
          <p className="truncate text-xs text-on-surface-muted">{o.items}</p>
        </div>
        <PaymentBadge state={o.payment} />
        {o.customer_full.lead_id && (
          <Link href={`/dashboard/conversations?lead=${o.customer_full.lead_id}`}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 font-label text-xs font-bold text-[#334155] shadow-sm hover:border-slate-300">
            <MessageCircle size={14} /> Open chat
          </Link>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          <Panel>
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary-50 font-label text-sm font-bold text-primary-700">{initials(who)}</span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-label text-[15px] font-bold text-[#0A1528]">{who}</span>
                  {o.customer_full.segment === "A" && <span className="rounded-full bg-rose-50 px-2 py-0.5 font-label text-[10px] font-bold text-rose-600">Hot</span>}
                  {o.channel === "store" && <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 font-label text-[10px] font-bold text-slate-600"><Store size={10} /> Store</span>}
                </div>
                <p className="truncate text-xs text-on-surface-muted">
                  {[o.customer_full.phone, o.customer_full.came_from, o.customer_full.order_count > 1 ? `${o.customer_full.order_count}${["th", "st", "nd", "rd"][o.customer_full.order_count % 10 > 3 || [11, 12, 13].includes(o.customer_full.order_count % 100) ? 0 : o.customer_full.order_count % 10]} order` : null].filter(Boolean).join(" · ")}
                </p>
              </div>
              <div className="text-right">
                <p className="text-[11px] text-on-surface-muted">Sold by</p>
                <p className="inline-flex items-center gap-1 font-label text-xs font-bold text-[#0A1528]">
                  {o.sold_by.ai ? <><Bot size={13} /> AI agent</> : o.sold_by.name ? <><User size={13} /> {o.sold_by.name}</> : "—"}
                </p>
              </div>
            </div>
          </Panel>

          <Panel title="Steps" right={
            o.handover !== "taken" && canDeliver && !["shipped", "delivered"].includes(o.delivery) ? (
              <div className="flex rounded-xl border border-[#e2e8f0] bg-[#f8fafc] p-0.5" role="group" aria-label="How it reaches them">
                {(["pickup", "courier"] as const).map((h) => (
                  <button key={h} type="button" disabled={!!busy}
                    onClick={() => run("handover", () => api.orders.setHandover(o.id, h))}
                    className={cn("inline-flex items-center gap-1 rounded-lg px-2.5 py-1 font-label text-[11px] font-bold",
                      (o.handover ?? "pickup") === h ? "bg-white text-[#0A1528] shadow-sm" : "text-[#64748b]")}>
                    {h === "pickup" ? <><Store size={12} /> Pickup</> : <><Truck size={12} /> Courier</>}
                  </button>
                ))}
              </div>
            ) : <DeliveryBadge state={o.delivery} handover={o.handover} courier={o.courier} needsPacking={o.needs_packing} />
          }>
            <ol className="flex items-start">
              {steps.map((s, i) => (
                <li key={s.key} className="flex flex-1 flex-col items-center text-center">
                  <div className="flex w-full items-center">
                    <span className={cn("h-0.5 flex-1", i === 0 ? "bg-transparent" : steps[i - 1].done && s.done ? "bg-primary" : "bg-[#e2e8f0]")} />
                    <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 font-label text-xs font-bold",
                      s.done ? "border-primary bg-primary text-white" : "border-[#e2e8f0] bg-white text-[#94a3b8]")}>
                      {s.done ? <Check size={14} strokeWidth={3} /> : i + 1}
                    </span>
                    <span className={cn("h-0.5 flex-1", i === steps.length - 1 ? "bg-transparent" : s.done && steps[i + 1].done ? "bg-primary" : "bg-[#e2e8f0]")} />
                  </div>
                  <span className={cn("mt-1.5 font-label text-xs font-bold", s.done ? "text-[#0A1528]" : "text-[#94a3b8]")}>{s.label}</span>
                  {s.at && s.done && <span className="text-[10px] text-on-surface-muted">{dateTime(s.at)}</span>}
                </li>
              ))}
            </ol>
            {o.ready_by && o.delivery !== "delivered" && (
              <p className="mt-3 text-xs text-on-surface-muted">Promised by {new Date(o.ready_by).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })}</p>
            )}
            {nextStep && !trackOpen && (
              <button type="button" disabled={!!busy}
                onClick={() => nextStep.action === "track" ? setTrackOpen(true)
                  : run("step", () => api.orders.delivery(o.id, { action: nextStep.action, handover: o.handover === "courier" ? "courier" : "pickup" }),
                    (out) => reportSend(o.id, nextStep.action === "ready" ? "ready" : "delivered", out.message, () => mutate()))}
                className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 font-label text-sm font-bold text-white shadow-sm hover:bg-primary/90 disabled:opacity-50">
                {busy === "step" && <Loader2 size={14} className="animate-spin" />} {nextStep.label}
              </button>
            )}
            {trackOpen && canDeliver && (
              <div className="mt-4 grid gap-2 rounded-xl border border-[#e2e8f0] bg-[#f8fafc] p-3 sm:grid-cols-[1fr_1fr_auto]">
                <input value={courier} onChange={(e) => setCourier(e.target.value)} placeholder="Courier (DTDC, Delhivery…)" aria-label="Courier"
                  className="h-9 rounded-lg border border-[#e2e8f0] bg-white px-3 text-xs focus:outline-none focus:ring-2 focus:ring-primary-200" />
                <input value={tracking} onChange={(e) => setTracking(e.target.value)} placeholder="Tracking ID" aria-label="Tracking ID"
                  className="h-9 rounded-lg border border-[#e2e8f0] bg-white px-3 text-xs focus:outline-none focus:ring-2 focus:ring-primary-200" />
                <button type="button" disabled={!!busy || !courier.trim()}
                  onClick={() => run("track", () => api.orders.delivery(o.id, { action: "shipped", courier, tracking_id: tracking }),
                    (out) => { setTrackOpen(false); reportSend(o.id, "shipped", out.message, () => mutate()); })}
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 font-label text-xs font-bold text-white disabled:opacity-50">
                  {busy === "track" && <Loader2 size={12} className="animate-spin" />} Shipped · tell {first}
                </button>
              </div>
            )}
            {o.tracking_id && <p className="mt-3 text-xs text-on-surface-muted">Tracking: <span className="font-bold text-[#0A1528]">{o.courier} · {o.tracking_id}</span></p>}
          </Panel>

          <Panel>
            <div className="overflow-hidden rounded-xl border border-[#eef2f6]">
              <table className="w-full text-sm">
                <thead className="bg-[#f8fafc] font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">
                  <tr><th className="px-3 py-2 text-left">Item</th><th className="px-3 py-2 text-right">Qty</th><th className="px-3 py-2 text-right">Price</th></tr>
                </thead>
                <tbody className="divide-y divide-[#f1f5f9]">
                  {o.items_full.map((it) => (
                    <tr key={it.id}>
                      <td className="px-3 py-2.5">
                        <span className="font-label text-[13px] font-bold text-[#0A1528]">{it.name}</span>
                        {it.variant_label && <span className="ml-1.5 text-xs text-on-surface-muted">{it.variant_label}</span>}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{it.qty}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{rupees(it.unit_price_paise * it.qty)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <dl className="mt-3 space-y-1 text-xs text-on-surface-muted">
              {o.bill_type === "gst" && o.gst_paise > 0 && (
                <div className="flex justify-between"><dt>{o.prices_include_gst ? "Includes GST" : "GST"}</dt><dd className="tabular-nums">{rupees(o.gst_paise)}</dd></div>
              )}
              {o.discount_paise > 0 && <div className="flex justify-between"><dt>Discount</dt><dd className="tabular-nums">− {rupees(o.discount_paise)}</dd></div>}
              <div className="flex justify-between pt-1 font-display text-base font-bold text-[#0A1528]"><dt>Total</dt><dd className="tabular-nums">{rupees(o.total_paise)}</dd></div>
            </dl>
          </Panel>

          <Panel title="Payments">
            {o.payments.length === 0 ? (
              <p className="text-xs text-on-surface-muted">Nothing paid yet.</p>
            ) : (
              <ul className="divide-y divide-[#f1f5f9]">
                {o.payments.map((p) => (
                  <li key={p.id} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 py-2 text-xs">
                    <Check size={14} className="text-emerald-600" />
                    <span className="font-label font-bold capitalize text-[#0A1528]">{p.kind === "payment" ? "Payment" : p.kind}</span>
                    <span className="font-bold tabular-nums text-emerald-700">{rupees(p.amount_paise)}</span>
                    <span className="text-on-surface-muted">{p.method_label} · {dateTime(p.paid_at)}</span>
                    {p.received_by_name && <span className="ml-auto text-on-surface-muted">by {p.received_by_name}</span>}
                  </li>
                ))}
              </ul>
            )}
            {open && o.balance_paise > 0 && (
              <div className="mt-3 rounded-xl bg-amber-50/70 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-label text-sm font-bold text-[#0A1528]">{o.paid_paise ? "Balance" : "To pay"} {rupees(o.balance_paise)}</span>
                  {o.ready_by && <span className="text-xs text-on-surface-muted">· due when ready</span>}
                  {canManage && (
                    <span className="ml-auto flex gap-2">
                      <button type="button" disabled={!!busy || !o.customer_full.phone}
                        title={o.customer_full.phone ? undefined : "This order has no phone number"}
                        onClick={() => run("link", () => api.orders.payLink(o.id), (out) => reportSend(o.id, "pay_link", out, () => mutate()))}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-[#e2e8f0] bg-white px-3 py-1.5 font-label text-xs font-bold text-[#334155] disabled:opacity-50">
                        {busy === "link" ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />} Send pay link
                      </button>
                      <button type="button" onClick={() => setPayOpen((v) => !v)}
                        className="rounded-lg bg-primary px-3 py-1.5 font-label text-xs font-bold text-white">Record payment</button>
                    </span>
                  )}
                </div>
                {payOpen && canManage && (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <label className="relative">
                      <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-xs text-on-surface-muted">₹</span>
                      <input value={payAmount} onChange={(e) => setPayAmount(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" aria-label="Amount paid"
                        className="h-9 w-32 rounded-lg border border-[#e2e8f0] bg-white pl-6 pr-2 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-primary-200" />
                    </label>
                    <div className="flex gap-1" role="group" aria-label="How they paid">
                      {METHODS.map((m) => (
                        <button key={m.value} type="button" onClick={() => setPayMethod(m.value)} aria-pressed={payMethod === m.value}
                          className={cn("rounded-lg border px-2.5 py-1.5 font-label text-xs font-bold",
                            payMethod === m.value ? "border-primary bg-primary-50 text-primary-800" : "border-[#e2e8f0] bg-white text-[#334155]")}>
                          {m.label}
                        </button>
                      ))}
                    </div>
                    <button type="button" onClick={recordPayment} disabled={!!busy}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-[#0A1528] px-3 py-1.5 font-label text-xs font-bold text-white disabled:opacity-50">
                      {busy === "pay" && <Loader2 size={12} className="animate-spin" />} Save
                    </button>
                  </div>
                )}
                {o.reminders.from && o.reminders.sent < 3 && (
                  <p className="mt-2 text-[11px] text-on-surface-muted">Reminders go by themselves on day 1, 3 and 7 until it&apos;s paid ({o.reminders.sent} sent).</p>
                )}
              </div>
            )}
            {o.payment === "paid" && <p className="mt-2 inline-flex items-center gap-1 text-xs font-bold text-emerald-700"><Check size={13} /> Paid in full</p>}
          </Panel>

          {canManage && open && o.paid_paise === 0 && (
            <div className="flex items-center justify-between rounded-2xl border border-[#e2e8f0] bg-white px-4 py-3 text-xs">
              <span className="text-on-surface-muted">Customer changed their mind?</span>
              <button type="button" disabled={!!busy}
                onClick={() => {
                  if (!window.confirm(`Cancel order ${o.label}? Nothing has been paid.`)) return;
                  run("cancel", () => api.deals.updateStage(o.id, { stage: "lost", lost_reason: "Cancelled" }), () => toast.success("Order cancelled"));
                }}
                className="font-label font-bold text-rose-600 hover:text-rose-700">Cancel order</button>
            </div>
          )}
          {o.paid_paise > 0 && o.stage !== "lost" && (
            <p className="px-1 text-[11px] text-on-surface-muted">Refunds and cancelling a paid order come in the next update.</p>
          )}
        </div>

        <div className="space-y-4">
          <Panel title={`Updates sent to ${first}`} right={<span className="text-[11px] text-on-surface-muted">on WhatsApp</span>}>
            {o.messages.length === 0 ? (
              <p className="text-xs text-on-surface-muted">{o.customer_full.phone ? "Nothing sent yet." : "No phone number on this order, so nothing goes out."}</p>
            ) : (
              <ul className="space-y-3">
                {o.messages.map((m) => (
                  <li key={m.id} className="flex gap-3">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700"><MessageCircle size={14} /></span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-label text-[13px] font-bold text-[#0A1528]">{KIND_TITLE[m.kind] ?? m.kind}</span>
                        <Ticks ticks={m.ticks} />
                      </div>
                      {m.body && <p className="line-clamp-3 whitespace-pre-line text-xs text-[#475569]">{m.body}</p>}
                      <p className="text-[10px] text-on-surface-muted">{dateTime(m.created_at)}{m.sent_via === "template" ? " · approved message" : ""}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {o.upcoming.length > 0 && (
              <div className="mt-4 border-t border-dashed border-[#e2e8f0] pt-3">
                <p className="mb-2 font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">Goes out next, by itself</p>
                {o.upcoming.map((u) => (
                  <div key={u.kind + u.at} className="flex justify-between text-xs">
                    <span className="font-label font-bold text-[#0A1528]">Payment reminder</span>
                    <span className="text-on-surface-muted">{dateTime(u.at)}, {u.note}</span>
                  </div>
                ))}
              </div>
            )}
            {canManage && o.customer_full.phone && o.bill_url && (
              <button type="button" disabled={!!busy}
                onClick={() => run("bill", () => api.orders.send(o.id, "bill"), (out) => reportSend(o.id, "bill", out, () => mutate()))}
                className="mt-4 inline-flex items-center gap-1.5 font-label text-xs font-bold text-primary-700 hover:text-primary-900 disabled:opacity-50">
                {busy === "bill" ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />} Send the bill {o.messages.some((m) => m.kind === "bill") ? "again" : ""}
              </button>
            )}
          </Panel>

          <Panel title={<span className="inline-flex items-center gap-1.5"><FileText size={15} /> {o.bill_type === "gst" ? "GST invoice" : "Bill"}</span>}>
            {o.bill_url ? (
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-label text-sm font-bold text-[#0A1528]">{o.invoice_number ?? o.label}</p>
                  <p className="text-xs text-on-surface-muted">
                    {o.invoice_number ? `Numbered ${dateTime(o.invoice_issued_at)} · same numbering as shop bills` : "Gets its bill number with the first payment"}
                  </p>
                </div>
                <a href={o.bill_url} target="_blank" rel="noopener noreferrer"
                  className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-[#e2e8f0] px-3 py-1.5 font-label text-xs font-bold text-[#334155] hover:border-slate-300">
                  Open · PDF <ExternalLink size={12} />
                </a>
              </div>
            ) : (
              <p className="text-xs text-on-surface-muted">The bill appears here with the first payment.</p>
            )}
            {o.buyer_gstin && <p className="mt-2 text-xs text-on-surface-muted">Business customer: {o.buyer_business ? `${o.buyer_business} · ` : ""}GSTIN {o.buyer_gstin}</p>}
          </Panel>
          {o.notes && <Panel title="Note"><p className="whitespace-pre-line text-xs text-[#475569]">{o.notes}</p></Panel>}
        </div>
      </div>
    </div>
  );
}
