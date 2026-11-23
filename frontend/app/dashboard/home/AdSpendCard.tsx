"use client";
import { useEffect, useState } from "react";
import { api, type AdPerformanceSummary } from "@/lib/api";
import { CARD, ChartCard } from "./ChartCard";
import { formatRupees } from "./todayLayout";

const CAMPAIGNS = 6;
const BAR_MAX_PX = 96;

/**
 * Ad spend as one bar per campaign. People without the rupee permission get no spend from the server, so
 * for them the same bars show leads per campaign instead and the card is titled to match.
 * Hidden when the client has no campaigns, as the old section was.
 */
export function AdSpendCard() {
  const [data, setData] = useState<AdPerformanceSummary | null>(null);

  useEffect(() => {
    let active = true;
    api.analytics
      .adPerformance()
      .then((res) => {
        if (active) setData(res);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  if (!data || data.campaigns.length === 0) return null;

  const hasSpend = data.campaigns.some((c) => typeof c.spend_inr === "number" && Number.isFinite(c.spend_inr));
  const rows = data.campaigns
    .map((c) => ({
      id: c.id,
      name: c.campaign_name || "Campaign",
      value: hasSpend ? Math.max(0, c.spend_inr ?? 0) : Math.max(0, c.total_leads ?? 0),
    }))
    .sort((a, b) => b.value - a.value)
    .slice(0, CAMPAIGNS);
  const max = Math.max(0, ...rows.map((r) => r.value));
  const show = (v: number) => (hasSpend ? formatRupees(Math.round(v * 100)) : `${v} leads`);
  const total = data.campaigns.reduce((a, c) => a + (hasSpend ? (c.spend_inr ?? 0) : (c.total_leads ?? 0)), 0);
  const note = `${show(total)} · ${data.campaigns.length} campaign${data.campaigns.length === 1 ? "" : "s"}`;
  const top = max > 0 ? rows.findIndex((r) => r.value === max) : -1;

  return (
    <ChartCard title={hasSpend ? "Ad spend" : "Ad leads"} note={note} className={CARD}>
      <ul className="flex h-[150px] items-end gap-1 border-b border-border-subtle" aria-label={hasSpend ? "Spend per campaign" : "Leads per campaign"}>
        {rows.map((r, i) => (
          <li key={r.id} className="flex min-w-0 flex-1 flex-col items-center gap-1.5" title={`${r.name}: ${show(r.value)}`}>
            <span className={`text-[11px] font-extrabold text-ink ${i === top ? "" : "invisible"}`}>{show(r.value)}</span>
            <div
              className={`w-3/5 rounded-t ${i === top ? "bg-primary-800" : "bg-primary-400"}`}
              style={{ height: `${Math.max(2, Math.round((max > 0 ? r.value / max : 0) * BAR_MAX_PX))}px` }}
            />
            <span className="w-full truncate text-center text-[11px] text-ink-muted">{r.name}</span>
          </li>
        ))}
      </ul>
    </ChartCard>
  );
}
