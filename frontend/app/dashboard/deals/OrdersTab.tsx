"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { toast } from "sonner";
import { ChevronRight, Download, Hourglass, IndianRupee, Loader2, MessageCircle, Package, ReceiptText, Search } from "lucide-react";
import { api, type OrderChip, type OrderRow, type OrdersPage } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { cn } from "@/lib/utils";
import { DeliveryBadge, PaymentBadge, reportSend, rupees, whenShort } from "./orders/orderUi";

const CHIPS: { key: OrderChip; label: string }[] = [
  { key: "all", label: "All" },
  { key: "waiting", label: "Waiting for payment" },
  { key: "advance", label: "Advance paid" },
  { key: "paid", label: "Paid" },
  { key: "pack", label: "To pack or ship" },
  { key: "quote", label: "Quote sent" },
  { key: "cancelled", label: "Cancelled" },
];

const DAYS = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "365", label: "1 year" },
  { value: "0", label: "All time" },
];

const CHANNELS = [
  { value: "all", label: "Online + store" },
  { value: "online", label: "Online" },
  { value: "store", label: "Store" },
];

const ACTION_LABEL: Record<OrderRow["next_action"], string> = {
  remind: "Send reminder",
  collect: "Collect balance",
  tracking: "Add tracking",
  ready: "Mark ready",
  open: "Open",
};

function periodText(days: string): string {
  if (days === "0") return "all time";
  return days === "365" ? "this year" : `last ${days} days`;
}

function Card({ icon: Icon, tint, label, value, lines, onSee }: {
  icon: typeof IndianRupee; tint: string; label: string; value: string;
  lines: { text: string; tone?: string }[]; onSee?: () => void;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-2xl border border-[#e8edf2] bg-white px-4 py-3.5 shadow-sm sm:px-[18px]">
      <span className="flex items-center gap-2">
        <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-[9px]", tint)} aria-hidden>
          <Icon size={15} />
        </span>
        <span className="truncate font-label text-[13px] font-bold text-[#0A1528]">{label}</span>
      </span>
      <span className="mt-1 font-display text-2xl font-extrabold leading-none tracking-tight text-[#0A1528] tabular-nums">{value}</span>
      {lines.map((line) => (
        <span key={line.text} className={cn("truncate font-label text-xs font-semibold text-[#64748b]", line.tone)}>{line.text}</span>
      ))}
      {onSee && (
        <button type="button" onClick={onSee} className="mt-0.5 w-fit font-label text-xs font-bold text-primary-700 hover:text-primary-900">
          See them ›
        </button>
      )}
    </div>
  );
}

export function OrdersTab({ canManage }: { canManage: boolean }) {
  const router = useRouter();
  const [chip, setChip] = useState<OrderChip>("all");
  const [channel, setChannel] = useState<"all" | "online" | "store">("all");
  const [days, setDays] = useState("30");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const query = { chip, channel, days: Number(days), q: search.trim() || undefined };
  const { data, error, isLoading, mutate } = useSWR<OrdersPage>(
    ["orders", JSON.stringify(query)],
    () => api.orders.list(query),
    { keepPreviousData: true, revalidateOnFocus: true },
  );
  const { data: setup, mutate: mutateSetup } = useSWR("orders-whatsapp-setup", () => api.orders.whatsappSetup(), {
    revalidateOnFocus: false,
  });
  const [submitting, setSubmitting] = useState(false);

  const rows = data?.data ?? [];
  const counts = data?.counts;
  const cards = data?.cards;
  const period = periodText(days);
  const missing = useMemo(() => (setup?.templates ?? []).filter((t) => t.status === "MISSING" || t.status === "REJECTED"), [setup]);
  const pending = (setup?.templates ?? []).filter((t) => t.status === "PENDING");

  async function rowAction(row: OrderRow) {
    if (row.next_action === "remind") {
      setBusy(row.id);
      try {
        const out = await api.orders.remind(row.id);
        reportSend(row.id, "reminder", out, () => mutate());
        await mutate();
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Couldn't send the reminder");
      } finally {
        setBusy(null);
      }
      return;
    }
    if (row.next_action === "ready") {
      setBusy(row.id);
      try {
        const out = await api.orders.delivery(row.id, { action: "ready" });
        reportSend(row.id, "ready", out.message, () => mutate());
        await mutate();
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Couldn't mark it ready");
      } finally {
        setBusy(null);
      }
      return;
    }
    const focus = row.next_action === "collect" ? "?focus=payment" : row.next_action === "tracking" ? "?focus=tracking" : "";
    router.push(`/dashboard/deals/orders/${row.id}${focus}`);
  }

  async function submitTemplates() {
    setSubmitting(true);
    try {
      const out = await api.orders.submitTemplates();
      await mutateSetup(out, { revalidate: false });
      if (out.problems.length) toast.error(out.problems[0]);
      else toast.success("Sent to Meta for approval. It usually takes a few hours to 2 days.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't submit them");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card icon={IndianRupee} tint="bg-emerald-50 text-emerald-700" label="Money in"
          value={cards ? rupees(cards.money_in.paise) : "—"}
          lines={[
            { text: cards ? `${cards.money_in.orders} ${cards.money_in.orders === 1 ? "order" : "orders"} paid · ${period}` : period },
            ...(cards?.money_in.refunded_paise ? [{ text: `after ${rupees(cards.money_in.refunded_paise)} refunded`, tone: "text-rose-600" }] : []),
          ]} />
        <Card icon={Hourglass} tint="bg-amber-50 text-amber-700" label="Still to collect"
          value={cards ? rupees(cards.to_collect.paise) : "—"}
          lines={[{
            text: cards ? `${cards.to_collect.orders} ${cards.to_collect.orders === 1 ? "order" : "orders"}${cards.to_collect.reminders_on ? ` · reminders on for ${cards.to_collect.reminders_on}` : ""}` : "",
            tone: cards?.to_collect.orders ? "text-amber-800" : undefined,
          }]}
          onSee={cards?.to_collect.orders ? () => setChip("waiting") : undefined} />
        <Card icon={Package} tint="bg-orange-50 text-orange-700" label="To pack or ship"
          value={cards ? String(cards.to_pack.orders) : "—"}
          lines={[{
            text: cards ? (cards.to_pack.over_2_days ? `${cards.to_pack.over_2_days} waiting over 2 days` : "none waiting long") : "",
            tone: cards?.to_pack.over_2_days ? "text-rose-600" : undefined,
          }]}
          onSee={cards?.to_pack.orders ? () => setChip("pack") : undefined} />
        <Card icon={ReceiptText} tint="bg-violet-50 text-violet-700" label="GST collected"
          value={cards ? rupees(cards.gst.paise) : "—"}
          lines={[{ text: cards ? `on ${cards.gst.bills} GST ${cards.gst.bills === 1 ? "bill" : "bills"} · ${period}` : "" }]} />
      </div>

      {setup?.connected && missing.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-primary-100 bg-primary-50/50 px-4 py-3">
          <MessageCircle size={18} className="shrink-0 text-primary-700" />
          <p className="min-w-0 flex-1 font-body text-xs leading-5 text-[#0A1528]">
            <span className="font-bold">Send bills and reminders to anyone on WhatsApp.</span>{" "}
            WhatsApp needs 3 approved messages for customers who haven&apos;t messaged you in 24 hours. Until then you get a
            &ldquo;Share on WhatsApp&rdquo; button instead.
          </p>
          {canManage ? (
            <button type="button" onClick={submitTemplates} disabled={submitting}
              className="inline-flex items-center gap-1.5 rounded-xl bg-primary px-3.5 py-2 font-label text-xs font-bold text-white shadow-sm hover:bg-primary/90 disabled:opacity-50">
              {submitting && <Loader2 size={13} className="animate-spin" />} Submit them to Meta
            </button>
          ) : (
            <span className="font-label text-xs font-semibold text-on-surface-muted">Ask the owner to submit them</span>
          )}
        </div>
      )}
      {setup?.connected && !missing.length && pending.length > 0 && (
        <p className="rounded-2xl border border-[#e8edf2] bg-white px-4 py-2.5 font-body text-xs text-on-surface-muted">
          Order messages are waiting for Meta&apos;s approval. Until then, people who haven&apos;t messaged in 24 hours get them through &ldquo;Share on WhatsApp&rdquo;.
        </p>
      )}

      <section className="rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
        <div className="flex flex-wrap items-center gap-2 border-b border-[#eef2f6] p-3.5">
          <div className="flex min-w-0 flex-1 flex-wrap gap-1.5" role="group" aria-label="Show orders">
            {CHIPS.map((c) => (
              <button key={c.key} type="button" onClick={() => setChip(c.key)} aria-pressed={chip === c.key}
                className={cn(
                  "whitespace-nowrap rounded-full border px-3 py-1.5 font-label text-xs font-bold transition-colors",
                  chip === c.key ? "border-[#0A1528] bg-[#0A1528] text-white" : "border-[#e2e8f0] bg-white text-[#334155] hover:border-slate-300",
                )}>
                {c.label}{counts ? <span className={cn("ml-1.5 tabular-nums", chip === c.key ? "text-white/80" : "text-[#94a3b8]")}>{counts[c.key]}</span> : null}
              </button>
            ))}
          </div>
          <label className="relative w-full sm:w-52">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#64748b]" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name, phone, order or item"
              aria-label="Search orders" type="search"
              className="h-9 w-full rounded-xl border border-[#e2e8f0] bg-[#f8fafc] pl-9 pr-3 text-xs text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary-200" />
          </label>
          <Select size="sm" value={channel} onChange={(v) => setChannel(v as typeof channel)} options={CHANNELS} aria-label="Online or store"
            className="w-auto text-xs font-bold" />
          <Select size="sm" value={days} onChange={setDays} options={DAYS} aria-label="Period" className="w-auto text-xs font-bold" />
        </div>

        {isLoading && !data ? (
          <div className="flex min-h-[260px] items-center justify-center"><Loader2 className="animate-spin text-primary" /></div>
        ) : error ? (
          <div className="flex flex-col items-center gap-3 px-4 py-16 text-center">
            <p className="text-sm text-on-surface-muted">Couldn&apos;t load orders. Nothing is lost.</p>
            <button type="button" onClick={() => mutate()} className="rounded-xl bg-primary px-3 py-1.5 text-xs font-bold text-white">Try again</button>
          </div>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center px-4 py-16 text-center">
            <ReceiptText size={26} className="mb-2 text-primary-300" />
            <h3 className="text-sm font-bold text-[#1e293b]">{chip === "all" && !search ? `No orders ${period}` : "No orders match"}</h3>
            <p className="mt-1 max-w-sm text-xs leading-relaxed text-[#94a3b8]">
              {chip === "all" && !search ? "Sales from WhatsApp, forms, calls and the shop counter land here." : "Pick another chip or period, or clear the search."}
            </p>
            {canManage && chip === "all" && !search && (
              <Link href="/dashboard/deals/new-bill" className="mt-4 rounded-xl bg-primary px-3.5 py-2 text-xs font-bold text-white shadow-sm">＋ New bill</Link>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[960px]">
              <thead>
                <tr className="border-b border-[#eef2f6] text-left font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">
                  <th className="px-4 py-3">Order</th>
                  <th className="px-4 py-3">Customer</th>
                  <th className="px-4 py-3">Items</th>
                  <th className="px-4 py-3 text-right">Amount</th>
                  <th className="px-4 py-3">Payment</th>
                  <th className="px-4 py-3">Delivery</th>
                  <th className="px-4 py-3"><span className="sr-only">Next step</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#f1f5f9]">
                {rows.map((row) => (
                  <tr key={row.id} onClick={() => router.push(`/dashboard/deals/orders/${row.id}`)}
                    className={cn("group cursor-pointer transition-colors hover:bg-[#f8fafc]", row.payment === "waiting" && "bg-amber-50/40")}>
                    <td className="px-4 py-3">
                      <div className="font-label text-[13px] font-bold text-[#0A1528] group-hover:text-primary-700">{row.label}</div>
                      <div className="text-[11px] text-[#94a3b8]">{whenShort(row.created_at)}</div>
                    </td>
                    <td className="max-w-[190px] px-4 py-3">
                      <div className="truncate font-label text-[13px] font-bold text-[#0A1528]">{row.customer.name || row.customer.phone || "Walk-in"}</div>
                      <div className="truncate text-[11px] text-[#94a3b8]">{row.customer.came_from}</div>
                    </td>
                    <td className="max-w-[240px] px-4 py-3"><div className="truncate text-xs text-[#334155]" title={row.items}>{row.items || "—"}</div></td>
                    <td className="px-4 py-3 text-right font-label text-[13px] font-bold tabular-nums text-[#0A1528]">{rupees(row.total_paise)}</td>
                    <td className="px-4 py-3">
                      <PaymentBadge state={row.payment} />
                      <div className="mt-1 max-w-[200px] truncate text-[11px] text-[#64748b]">{row.payment_note}</div>
                    </td>
                    <td className="px-4 py-3">
                      <DeliveryBadge state={row.delivery} handover={row.handover} courier={row.courier} needsPacking={row.needs_packing} />
                    </td>
                    <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                      {canManage || row.next_action === "open" ? (
                        <button type="button" onClick={() => rowAction(row)} disabled={busy === row.id}
                          className="inline-flex items-center gap-1 whitespace-nowrap font-label text-xs font-bold text-primary-700 hover:text-primary-900 disabled:opacity-50">
                          {busy === row.id && <Loader2 size={12} className="animate-spin" />}
                          {ACTION_LABEL[row.next_action]}{row.next_action === "open" && <ChevronRight size={13} />}
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {rows.length > 0 && (
          <div className="flex items-center justify-between gap-2 border-t border-[#eef2f6] px-4 py-2.5 text-[11px] text-[#64748b]">
            <span>Showing {rows.length} {rows.length === 1 ? "order" : "orders"} · {period}</span>
            <Link href="/dashboard/deals?tab=insights" className="inline-flex items-center gap-1 font-bold text-primary-700 hover:text-primary-900">
              <Download size={12} /> Monthly file for your auditor: Insights
            </Link>
          </div>
        )}
      </section>
    </div>
  );
}
