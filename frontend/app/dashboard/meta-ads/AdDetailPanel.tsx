"use client";

import { useEffect, useState } from "react";
import { Sparkles, X } from "lucide-react";
import type { AdBreakdownKey, AdBreakdownValues, AdPerformanceRow } from "@/lib/api";
import { useAdBreakdown } from "@/hooks/useApi";
import { cn } from "@/lib/utils";
import { ChannelMarks } from "./metaFields";
import { AdJourney } from "./AdJourney";
import {
  BREAKDOWN_TABS,
  cheapestSentence,
  costPerClick,
  groupLabel,
  pickCheapest,
} from "@/lib/ad-breakdown";

type Stat = { label: string; value: string; sub?: string | null; tone?: string };

function countText(value: number | null) {
  return value == null ? "—" : Math.round(value).toLocaleString("en-IN");
}

function moneyText(value: number | null) {
  return value == null ? "—" : "₹" + Math.round(value).toLocaleString("en-IN");
}

/** Cost per chat click keeps paise when it is small, e.g. ₹7.42, and rounds above that. */
function costPerClickText(value: number | null) {
  if (value == null) return "—";
  if (value < 100) return "₹" + value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return "₹" + Math.round(value).toLocaleString("en-IN");
}

function percentText(value: number | null) {
  return value == null ? "—" : `${value.toFixed(2)}%`;
}

/** "17 Sep – 16 Oct 2026". Year only on the end date. */
function formatRange(from: string, to: string) {
  const start = new Date(`${from.slice(0, 10)}T00:00:00`);
  const end = new Date(`${to.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return `${from} – ${to}`;
  const startText = start.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  const endText = end.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  return `${startText} – ${endText}`;
}

/** "Running since 12 Oct 2026 · ₹500/day": when it started and what it may spend. */
function runningLine(row: AdPerformanceRow): string | null {
  const started = row.schedule_start || row.campaign_created_at;
  const day = started
    ? new Date(started).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
    : null;
  const running = (row.delivery_status ?? "").toUpperCase() === "ACTIVE";
  const budget = row.daily_budget != null
    ? `${moneyText(row.daily_budget)}/day`
    : row.lifetime_budget != null ? `${moneyText(row.lifetime_budget)} lifetime` : null;
  const parts = [day ? `${running ? "Running since" : "Started"} ${day}` : null, budget].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

function ValueCells({ values }: { values: AdBreakdownValues | null }) {
  return (
    <>
      <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{countText(values?.inline_link_clicks ?? null)}</td>
      <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{moneyText(values?.spend ?? null)}</td>
      <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{costPerClickText(values ? costPerClick(values) : null)}</td>
      <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{countText(values?.impressions ?? null)}</td>
      <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{percentText(values?.inline_link_click_ctr ?? null)}</td>
    </>
  );
}

export function AdDetailPanel({
  row,
  dateFrom,
  dateTo,
  stats,
  onClose,
}: {
  row: AdPerformanceRow;
  dateFrom: string;
  dateTo: string;
  stats: Stat[];
  onClose: () => void;
}) {
  const [breakdown, setBreakdown] = useState<AdBreakdownKey>("placement");
  const { data, error, mutate } = useAdBreakdown(row.ad_creative_id, {
    breakdown,
    date_from: dateFrom,
    date_to: dateTo,
  });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rows = data?.rows ?? [];
  const cheapestIndex = pickCheapest(rows);
  const overallCost = data?.overall ? costPerClick(data.overall) : null;
  const cheapestText =
    cheapestIndex != null
      ? cheapestSentence(
          groupLabel(rows[cheapestIndex].label, breakdown),
          costPerClick(rows[cheapestIndex].values) ?? 0,
          overallCost,
        )
      : null;
  const shownFrom = data?.date_from ?? dateFrom;
  const shownTo = data?.date_to ?? dateTo;
  const clippedToHistory = Boolean(data && data.date_from > dateFrom);
  const tabLabel = BREAKDOWN_TABS.find((tab) => tab.key === breakdown)?.label ?? "Placement";

  return (
    <div className="fixed inset-0 z-dialog">
      <div
        aria-hidden
        onClick={onClose}
        className="absolute inset-0 bg-stone-950/40 backdrop-blur-[2px]"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="ad-detail-title"
        className="fixed inset-y-0 right-0 flex w-full max-w-xl flex-col bg-white shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-surface-mid/60 p-5">
          <div className="min-w-0">
            <h2 id="ad-detail-title" className="font-display text-lg font-bold text-on-surface">{row.creative_label}</h2>
            <div className="mt-1.5">
              <ChannelMarks channels={row.messaging_channels} multiDestination={row.is_multi_destination} />
            </div>
            <p className="mt-1.5 font-body text-xs leading-5 text-on-surface-muted">
              {row.campaign_name} · {row.adset_name ?? "No ad set"}
            </p>
            {runningLine(row) && <p className="font-body text-xs leading-5 text-on-surface-muted">{runningLine(row)}</p>}
            <p className="font-body text-xs leading-5 text-on-surface-muted">
              {formatRange(shownFrom, shownTo)}
              {clippedToHistory && " · from your history start date"}
            </p>
          </div>
          <button type="button" onClick={onClose}
            className="shrink-0 rounded-xl p-2 text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-700"
            aria-label="Close ad details">
            <X size={16} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-6 pt-4">
          <p className="mb-2 font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">This ad in Anril</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {stats.map((stat) => (
              <div key={stat.label} className="rounded-2xl border border-surface-mid/70 p-3">
                <p className={cn("font-display text-lg font-bold tabular-nums text-on-surface", stat.tone)}>{stat.value}</p>
                <p className="mt-0.5 font-label text-[10px] text-on-surface-muted">{stat.label}</p>
                {stat.sub && <p className="mt-0.5 text-[10px] text-on-surface-muted">{stat.sub}</p>}
              </div>
            ))}
          </div>

          <p className="mb-2 mt-6 font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">Where this ad works best</p>
          <div role="tablist" aria-label="Breakdown" className="flex gap-1.5 overflow-x-auto pb-1">
            {BREAKDOWN_TABS.map((tab) => {
              const active = tab.key === breakdown;
              return (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setBreakdown(tab.key)}
                  className={cn(
                    "shrink-0 rounded-full px-3 py-1.5 font-label text-xs font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-200",
                    active ? "bg-primary-600 text-white" : "bg-surface-low text-on-surface-muted hover:text-on-surface",
                  )}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>

          <div className="mt-3">
            {cheapestText ? (
              <p className="flex items-start gap-2 rounded-2xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900">
                <Sparkles size={14} className="mt-0.5 shrink-0" />
                <span>{cheapestText}</span>
              </p>
            ) : rows.length > 0 && cheapestIndex == null ? (
              <p className="text-xs text-on-surface-muted">Not enough chat clicks yet to compare. Each group needs at least 5.</p>
            ) : null}
          </div>

          <div className="mt-3">
            {error ? (
              <div className="flex flex-col items-center gap-3 rounded-2xl border border-surface-mid/70 p-6 text-center">
                <p className="text-xs text-on-surface-muted">Meta didn&apos;t respond. Try again in a minute.</p>
                <button
                  type="button"
                  onClick={() => mutate()}
                  className="rounded-full bg-primary-600 px-3 py-1.5 font-label text-xs font-semibold text-white transition-colors hover:bg-primary-700"
                >
                  Try again
                </button>
              </div>
            ) : !data ? (
              <div className="overflow-x-auto rounded-2xl border border-surface-mid/70">
                <table className="w-full text-xs">
                  <thead className="bg-surface-low/60">
                    <tr className="font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">
                      <th className="px-3 py-2.5 text-left">{tabLabel}</th>
                      <th className="px-3 py-2.5 text-right">Chat clicks</th>
                      <th className="px-3 py-2.5 text-right">Spend</th>
                      <th className="px-3 py-2.5 text-right">Cost per chat click</th>
                      <th className="px-3 py-2.5 text-right">Impressions</th>
                      <th className="px-3 py-2.5 text-right">CTR (link)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-mid/50">
                    {[0, 1, 2, 3].map((index) => (
                      <tr key={index} className="animate-pulse">
                        {[0, 1, 2, 3, 4, 5].map((cell) => (
                          <td key={cell} className="px-3 py-3">
                            <div className="ml-auto h-3 w-full rounded bg-stone-200" />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : rows.length === 0 ? (
              <p className="rounded-2xl border border-surface-mid/70 p-6 text-center text-xs text-on-surface-muted">
                Meta has no split for these dates yet.
              </p>
            ) : (
              <div className="overflow-x-auto rounded-2xl border border-surface-mid/70">
                <table className="w-full text-xs">
                  <thead className="bg-surface-low/60">
                    <tr className="font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">
                      <th className="px-3 py-2.5 text-left">{tabLabel}</th>
                      <th className="px-3 py-2.5 text-right">Chat clicks</th>
                      <th className="px-3 py-2.5 text-right">Spend</th>
                      <th className="px-3 py-2.5 text-right">Cost per chat click</th>
                      <th className="px-3 py-2.5 text-right">Impressions</th>
                      <th className="px-3 py-2.5 text-right">CTR (link)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-mid/50">
                    {rows.map((item, index) => {
                      const cheapest = index === cheapestIndex;
                      return (
                        <tr key={`${item.label}-${index}`} className={cn(cheapest && "bg-emerald-50/50")}>
                          <td className="px-3 py-2.5 text-left font-label font-semibold text-on-surface">
                            <span className="inline-flex flex-wrap items-center gap-1.5">
                              {groupLabel(item.label, breakdown)}
                              {cheapest && (
                                <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[9px] font-bold text-emerald-700">Cheapest</span>
                              )}
                            </span>
                          </td>
                          <ValueCells values={item.values} />
                        </tr>
                      );
                    })}
                  </tbody>
                  <tfoot>
                    <tr className="border-t-2 border-surface-mid font-bold">
                      <td className="px-3 py-2.5 text-left font-label text-on-surface">Whole ad</td>
                      <ValueCells values={data.overall} />
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </div>

          <p className="mt-4 text-[10px] text-on-surface-muted">
            Meta splits its own numbers only. Messages and hot leads are for the whole ad, because Meta doesn&apos;t share who the people are.
          </p>

          <AdJourney row={row} dateFrom={dateFrom} dateTo={dateTo} />
        </div>
      </aside>
    </div>
  );
}
