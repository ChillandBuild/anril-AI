"use client";

import { toast } from "sonner";
import { Check, CheckCheck, Clock3, Hourglass, PackageCheck, Store, Truck, X } from "lucide-react";
import { api, type OrderDeliveryState, type OrderMessageKind, type OrderMessageResult, type OrderPaymentState } from "@/lib/api";
import { cn } from "@/lib/utils";

/** ₹1,86,400 (Indian grouping); paise only when there are some. */
export function rupees(paise: number | null | undefined): string {
  if (paise == null) return "—";
  const whole = paise % 100 === 0;
  return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2 });
}

/** "Today, 1:10 PM" · "Yesterday" · "13 Nov" */
export function whenShort(iso: string | null | undefined): string {
  if (!iso) return "";
  const at = new Date(iso);
  const now = new Date();
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diff = Math.round((day(now) - day(at)) / 86400000);
  if (diff === 0) return `Today, ${at.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}`;
  if (diff === 1) return "Yesterday";
  return at.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

const PAYMENT: Record<OrderPaymentState, { label: string; tone: string; icon: typeof Check }> = {
  paid: { label: "Paid", tone: "bg-emerald-50 text-emerald-700 ring-emerald-200", icon: Check },
  advance: { label: "Advance paid", tone: "bg-sky-50 text-sky-700 ring-sky-200", icon: Clock3 },
  waiting: { label: "Waiting for payment", tone: "bg-amber-50 text-amber-800 ring-amber-200", icon: Hourglass },
  quote: { label: "Quote sent", tone: "bg-slate-100 text-slate-600 ring-slate-200", icon: Clock3 },
  cancelled: { label: "Cancelled", tone: "bg-rose-50 text-rose-700 ring-rose-200", icon: X },
};

export function PaymentBadge({ state, className }: { state: OrderPaymentState; className?: string }) {
  const p = PAYMENT[state];
  const Icon = p.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 font-label text-[11px] font-bold ring-1", p.tone, className)}>
      <Icon size={12} strokeWidth={2.5} /> {p.label}
    </span>
  );
}

export function deliveryText(state: OrderDeliveryState, handover: string | null, courier?: string | null): string | null {
  if (state === "taken") return "Taken in store";
  if (state === "delivered") return handover === "courier" ? "Delivered" : "Picked up";
  if (state === "shipped") return courier ? `Shipped · ${courier}` : "Shipped";
  if (state === "ready") return handover === "courier" ? "Packed" : "Ready for pickup";
  if (state === "working") return handover === "courier" ? "To pack" : "Working on it";
  return null;
}

export function DeliveryBadge({ state, handover, courier, needsPacking }: {
  state: OrderDeliveryState; handover: string | null; courier?: string | null; needsPacking?: boolean;
}) {
  const text = deliveryText(state, handover, courier) ?? (needsPacking ? "To pack" : null);
  if (!text) return <span className="text-on-surface-muted">—</span>;
  const Icon = state === "taken" ? Store : state === "shipped" ? Truck : state === "delivered" ? PackageCheck : PackageCheck;
  const tone = state === "taken" || state === "delivered"
    ? "bg-slate-100 text-slate-700"
    : state === "shipped" ? "bg-indigo-50 text-indigo-700" : state === "ready" ? "bg-emerald-50 text-emerald-700" : "bg-orange-50 text-orange-700";
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 font-label text-[11px] font-bold", tone)}>
      <Icon size={12} /> {text}
    </span>
  );
}

export function Ticks({ ticks }: { ticks: string }) {
  if (ticks === "shared") return <span className="text-[11px] font-semibold text-on-surface-muted">from your phone</span>;
  if (ticks === "read") return <span className="inline-flex items-center gap-0.5 text-[11px] font-bold text-sky-600"><CheckCheck size={13} /> read</span>;
  if (ticks === "delivered") return <span className="inline-flex items-center gap-0.5 text-[11px] font-semibold text-on-surface-muted"><CheckCheck size={13} /> got it</span>;
  if (ticks === "failed") return <span className="text-[11px] font-bold text-rose-600">not delivered</span>;
  return <span className="inline-flex items-center gap-0.5 text-[11px] font-semibold text-on-surface-muted"><Check size={13} /> sent</span>;
}

const WHY: Record<string, string> = {
  no_phone: "This order has no phone number, so nothing was sent.",
  opted_out: "They said stop on WhatsApp, so nothing was sent.",
  whatsapp_not_connected: "WhatsApp isn't connected yet.",
  outside_24h_no_template: "They haven't messaged in 24 hours and the order messages aren't approved yet.",
  send_failed: "WhatsApp didn't take it.",
};

/** After any send: a quiet success, or a way to send it from the staff member's own WhatsApp. */
export function reportSend(orderId: string, kind: OrderMessageKind, result: OrderMessageResult | null | undefined, onShared?: () => void) {
  if (!result) return;
  if (result.sent) {
    toast.success(result.via === "template" ? "Sent on WhatsApp (approved message)" : "Sent on WhatsApp");
    return;
  }
  const why = WHY[result.reason ?? ""] ?? "It wasn't sent.";
  if (!result.share_url) {
    if (result.reason !== "no_phone") toast.message(why);
    return;
  }
  toast.message(why, {
    duration: 12000,
    action: {
      label: "Share on WhatsApp",
      onClick: () => {
        window.open(result.share_url!, "_blank", "noopener");
        api.orders.shared(orderId, kind, result.text).then(() => onShared?.()).catch(() => {});
      },
    },
  });
}
