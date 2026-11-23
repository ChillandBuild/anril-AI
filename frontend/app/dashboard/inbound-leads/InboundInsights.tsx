"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { api, type InboundLeadFilters, type InboundMoneyToday } from "@/lib/api";
import { formatRupees } from "@/components/deals/money";
import { cn } from "@/lib/utils";

export type InboundTab = "all" | "wants" | "lost";

export const INBOUND_TABS: { value: InboundTab; label: string }[] = [
  { value: "all", label: "All leads" },
  { value: "wants", label: "What they want" },
  { value: "lost", label: "Why lost" },
];

/** All leads / What they want / Why lost, under the filters. */
export function InboundTabs({ tab, onChange }: { tab: InboundTab; onChange: (t: InboundTab) => void }) {
  return (
    <div role="tablist" aria-label="Inbound leads view" className="flex gap-1 border-b border-[#e2e8f0]">
      {INBOUND_TABS.map((t) => (
        <button
          key={t.value}
          type="button"
          role="tab"
          aria-selected={tab === t.value}
          onClick={() => onChange(t.value)}
          className={cn(
            "-mb-px border-b-2 px-4 py-2.5 text-sm font-semibold transition-colors",
            tab === t.value ? "border-primary text-primary" : "border-transparent text-[#475467] hover:text-[#0A1528]",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

/**
 * What they want (grouped, with how many are Hot) or Why lost (grouped reasons), for the leads the
 * filters on screen match. Tapping a row searches the list for it.
 */
export function InsightsList({ tab, filters, onPick }: { tab: "wants" | "lost"; filters: InboundLeadFilters; onPick: (text: string) => void }) {
  const key = JSON.stringify(filters);
  const { data, error } = useSWR(["inbound-insights", key], () => api.inboundLeads.insights(filters));
  const rows: { text: string; count: number; hot?: number }[] = tab === "wants" ? data?.wants ?? [] : data?.lost ?? [];
  const most = Math.max(1, ...rows.map((r) => r.count));
  return (
    <div className="overflow-hidden rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
      <div className="flex items-baseline justify-between gap-3 border-b border-[#f1f5f9] px-5 py-3">
        <h3 className="text-sm font-bold text-[#0A1528]">{tab === "wants" ? "What people asked for" : "Why people didn't buy"}</h3>
        {data && (
          <span className="text-xs text-[#64748b]">
            {tab === "wants"
              ? `${data.with_wants.toLocaleString("en-IN")} leads said what they want`
              : `${data.lost_total.toLocaleString("en-IN")} marked Lost`}
          </span>
        )}
      </div>
      {error ? (
        <p className="px-5 py-8 text-center text-sm text-[#64748b]">Couldn&apos;t load this. Try again in a moment.</p>
      ) : !data ? (
        <div className="space-y-2 p-5">{[0, 1, 2].map((i) => <div key={i} className="h-6 animate-pulse rounded bg-slate-100" />)}</div>
      ) : rows.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-[#64748b]">
          {tab === "wants"
            ? "Nothing yet. The AI agent saves what each person wants as they chat."
            : "Nobody marked Lost in this view."}
        </p>
      ) : (
        <ul className="divide-y divide-[#f1f5f9]">
          {rows.map((r) => (
            <li key={r.text}>
              <button
                type="button"
                onClick={() => onPick(r.text)}
                title={tab === "wants" ? `Show the leads who want ${r.text}` : undefined}
                disabled={tab === "lost"}
                className="grid w-full grid-cols-[minmax(0,14rem)_1fr_auto] items-center gap-4 px-5 py-2.5 text-left hover:bg-[#f8fafc] disabled:cursor-default disabled:hover:bg-transparent"
              >
                <span className="truncate text-sm font-semibold capitalize text-[#0A1528]">{r.text}</span>
                <span className="h-2 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
                  <span className={cn("block h-full rounded-full", tab === "wants" ? "bg-primary/70" : "bg-[#98a2b3]")}
                    style={{ width: `${(r.count / most) * 100}%` }} />
                </span>
                <span className="whitespace-nowrap text-right text-sm tabular-nums text-[#0A1528]">
                  <span className="font-bold">{r.count}</span>
                  {(r.hot ?? 0) > 0 && <span className="ml-1.5 text-xs font-semibold text-[#b42318]">🔥 {r.hot}</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Store orders today · Paid on WhatsApp link · Paid at the store · Money in today. Hidden without deals.view. */
export function MoneyTodayCards() {
  const [data, setData] = useState<InboundMoneyToday | null>(null);
  useEffect(() => {
    let live = true;
    api.inboundLeads.moneyToday().then((d) => live && setData(d)).catch(() => {});
    return () => { live = false; };
  }, []);
  if (!data) return null;
  const cards = [
    {
      label: "Store orders today",
      value: data.store_orders.toLocaleString("en-IN"),
      hint: data.store_orders ? `${data.store_matched} matched to a chat · ${data.store_new} new customers` : "none yet today",
      tone: "border-[#e2e8f0] bg-white text-[#0A1528]",
    },
    {
      label: "Paid on WhatsApp link",
      value: formatRupees(data.link_paid_paise),
      hint: `${data.link_payments} ${data.link_payments === 1 ? "payment" : "payments"} · marked by itself`,
      tone: "border-[#abefc6] bg-[#f6fef9] text-[#067647]",
    },
    {
      label: "Paid at the store",
      value: formatRupees(data.store_paid_paise),
      hint: "cash / UPI / card in Orders & payments",
      tone: "border-[#fedf89] bg-[#fffcf5] text-[#b54708]",
    },
    {
      label: "Money in today",
      value: formatRupees(data.money_in_paise),
      hint: "WhatsApp + store, less refunds",
      tone: "border-primary/20 bg-primary-light/40 text-primary",
    },
  ];
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((c) => (
        <div key={c.label} className={cn("rounded-2xl border px-5 py-4 shadow-sm", c.tone.split(" ").slice(0, 2).join(" "))}>
          <p className="text-xs font-semibold text-[#475467]">{c.label}</p>
          <p className={cn("mt-1 text-2xl font-bold tabular-nums", c.tone.split(" ")[2])}>{c.value}</p>
          <p className="mt-0.5 text-xs text-[#64748b]">{c.hint}</p>
        </div>
      ))}
    </div>
  );
}
