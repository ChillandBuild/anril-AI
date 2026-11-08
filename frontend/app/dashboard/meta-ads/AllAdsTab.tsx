"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { CircleAlert, Download, Info, Megaphone, Zap } from "lucide-react";
import { toast } from "sonner";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { useAllAdsTotalReach, useAllMetaAds, useMetaFieldCatalog } from "@/hooks/useApi";
import { api } from "@/lib/api";
import type { AllAdsParams, AllAdsRow, MetaField } from "@/lib/api";
import { cn } from "@/lib/utils";
import { buildAllAdsCsv, computeTotals, fieldsToFetch } from "./allAdsReport";
import { DataFromPicker } from "./DataFromPicker";
import {
  AdTypeBadge,
  BreakdownSelect,
  MetaColumnPicker,
  deliveryLabel,
  formatMetaValue,
  usePersistedColumns,
} from "./metaFields";

const COLUMNS_STORAGE_KEY = "anril.metaAds.allAds.columns";
const DEFAULT_COLUMN_KEYS = [
  "results",
  "result_type",
  "cost_per_result",
  "reach",
  "impressions",
  "spend",
  "cpm",
  "inline_link_clicks",
  "ctr",
  "delivery",
];

const NUMERIC_FORMATS = new Set(["number", "money", "percent", "decimal"]);

/** Ad types the Meta ad-type classifier emits. Anything else falls under "Other". */
const KNOWN_AD_TYPES = ["WhatsApp", "Multi-destination", "Instant form", "Website"];
const TYPE_FILTERS: { key: string; label: string }[] = [
  { key: "all", label: "All" },
  ...KNOWN_AD_TYPES.map((type) => ({ key: type, label: type })),
  { key: "Other", label: "Other" },
];

const SKELETON_ROWS = 6;

function localDate(daysBack = 0) {
  const date = new Date();
  date.setDate(date.getDate() - daysBack);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** "2026-08-24" -> "24 Aug 2026". */
function formatIsoDate(iso: string) {
  const parsed = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return Number.isNaN(parsed.getTime())
    ? iso
    : parsed.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** One cell: Delivery in Ads Manager's words, everything else by its format. */
function cellValue(value: unknown, field: MetaField) {
  if (field.key === "delivery") return deliveryLabel(value) || "—";
  return formatMetaValue(value, field.format);
}

function matchesType(row: AllAdsRow, filterKey: string) {
  if (filterKey === "all") return true;
  const type = (row.ad_type || "").trim().toLowerCase();
  if (filterKey === "Other") return !KNOWN_AD_TYPES.some((known) => known.toLowerCase() === type);
  return type === filterKey.toLowerCase();
}

export function AllAdsTab() {
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("meta_ads.manage");
  const [syncing, setSyncing] = useState(false);
  const [dateFrom, setDateFrom] = useState(() => localDate(29));
  const [dateTo, setDateTo] = useState(() => localDate());
  const [breakdown, setBreakdown] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState("all");
  const [columns, setColumns] = usePersistedColumns(COLUMNS_STORAGE_KEY, DEFAULT_COLUMN_KEYS);

  const { data: catalog, error: catalogError } = useMetaFieldCatalog();
  const fields = useMemo(() => catalog?.fields ?? [], [catalog]);
  // Chosen columns in catalogue order, so the table reads the same however they were picked.
  const columnFields = useMemo(
    () => fields.filter((field) => columns.includes(field.key)),
    [fields, columns],
  );

  const request: AllAdsParams | null = catalog && dateFrom && dateTo
    ? {
        date_from: dateFrom,
        date_to: dateTo,
        // Plus the inputs the Total row and download need, even if hidden.
        fields: fieldsToFetch(columnFields.map((field) => field.key)),
        breakdown: breakdown ?? undefined,
      }
    : null;
  const { data, error, mutate } = useAllMetaAds(request);
  const loadError = catalogError ?? error;

  const allRows = useMemo(() => data?.data ?? [], [data]);
  const filteredRows = useMemo(
    () => allRows.filter((row) => matchesType(row, typeFilter)),
    [allRows, typeFilter],
  );
  // Unique ads per type, so the chips count ads rather than breakdown buckets.
  const typeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const filter of TYPE_FILTERS) {
      counts.set(filter.key, new Set(allRows.filter((row) => matchesType(row, filter.key)).map((row) => row.meta_ad_id)).size);
    }
    return counts;
  }, [allRows]);

  // With a breakdown, one ad produces several rows; keep them together under the ad.
  const groups = useMemo(() => {
    const byAd = new Map<string, AllAdsRow[]>();
    for (const row of filteredRows) {
      const list = byAd.get(row.meta_ad_id);
      if (list) list.push(row);
      else byAd.set(row.meta_ad_id, [row]);
    }
    return Array.from(byAd.values());
  }, [filteredRows]);

  // Total row reach, de-duplicated by Meta: the whole account when every type is
  // shown (All ads lists every ad that delivered), else just the ads in view.
  const filteredAdIds = useMemo(
    () => Array.from(new Set(filteredRows.map((row) => row.meta_ad_id))),
    [filteredRows],
  );
  const reachRange = data && filteredRows.length ? { date_from: data.date_from, date_to: data.date_to } : null;
  const { data: totalReachData, error: totalReachError, mutate: mutateTotalReach } = useAllAdsTotalReach(
    reachRange,
    typeFilter === "all" ? undefined : filteredAdIds,
  );
  const totalReach = totalReachData ? totalReachData.reach : totalReachError ? null : undefined;
  const totals = useMemo(
    () => computeTotals(filteredRows, columnFields, totalReach),
    [filteredRows, columnFields, totalReach],
  );
  const showReachNote = totals.reachEstimated && columnFields.some((field) => field.key === "reach" || field.key === "frequency");

  /** The account sync (refreshes Anril's ad list and the Messaging ads copy),
   * then this table straight from Meta, skipping the few-minute cache. */
  async function handleSyncNow() {
    setSyncing(true);
    try {
      const result = await api.inboundLeads.adSyncNow();
      if (!result.ok) {
        toast.error(result.error ?? "Sync failed — no details returned");
        return;
      }
      if (request) {
        await mutate(api.inboundLeads.getAllMetaAds({ ...request, refresh: true }), { revalidate: false });
      }
      await mutateTotalReach();
      toast.success("Synced — numbers are fresh from Meta.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  function handleDownload() {
    if (!data) return;
    const csv = buildAllAdsCsv(filteredRows, columnFields, {
      date_from: data.date_from,
      date_to: data.date_to,
      breakdown,
    });
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `all_ads_${data.date_from}_to_${data.date_to}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  const showStartNote = Boolean(data?.start_date && data.date_from && data.start_date > data.date_from);
  const columnCount = 3 + (breakdown ? 1 : 0) + columnFields.length;
  const typeLabel = TYPE_FILTERS.find((filter) => filter.key === typeFilter)?.label ?? "";

  function renderHeader() {
    return (
      <thead>
        <tr className="border-b border-surface-mid bg-surface-low/60">
          <th className="sticky left-0 z-20 w-[180px] min-w-[180px] max-w-[180px] bg-surface-low px-4 py-3 text-left font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">Campaign</th>
          <th className="sticky left-[180px] z-20 w-[150px] min-w-[150px] max-w-[150px] bg-surface-low px-4 py-3 text-left font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">Ad set</th>
          <th className="sticky left-[330px] z-20 w-[260px] min-w-[260px] max-w-[260px] border-r border-surface-mid/60 bg-surface-low px-4 py-3 text-left font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">Ad</th>
          {breakdown && (
            <th className="whitespace-nowrap px-4 py-3 text-left font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">Breakdown</th>
          )}
          {columnFields.map((field) => (
            <th
              key={field.key}
              title={`${field.group}: ${field.label}`}
              className={cn(
                "whitespace-nowrap px-4 py-3 font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted",
                NUMERIC_FORMATS.has(field.format) ? "text-right" : "text-left",
              )}
            >
              {field.label}
            </th>
          ))}
        </tr>
      </thead>
    );
  }

  function renderBody() {
    if (!data) {
      return (
        <tbody className="divide-y divide-surface-mid/50">
          {Array.from({ length: SKELETON_ROWS }, (_, index) => (
            <tr key={index}>
              {Array.from({ length: columnCount }, (__, cell) => (
                <td key={cell} className="px-4 py-3">
                  <div className="h-3 w-full max-w-[120px] animate-pulse rounded bg-stone-200/70" />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      );
    }

    return (
      <tbody className="divide-y divide-surface-mid/50">
        {groups.flatMap((group) =>
          group.map((row, index) => {
            const isFirst = index === 0;
            return (
              <tr
                key={`${row.meta_ad_id}:${row.breakdown ?? ""}`}
                className={cn("group transition-colors hover:bg-surface-low/60", !isFirst && "bg-stone-50/40")}
              >
                <td className="sticky left-0 z-10 w-[180px] min-w-[180px] max-w-[180px] bg-white px-4 py-3 text-left font-label text-xs font-semibold text-on-surface group-hover:bg-stone-50">
                  {isFirst && (
                    <span className="block truncate" title={row.campaign_name}>{row.campaign_name}</span>
                  )}
                </td>
                <td className="sticky left-[180px] z-10 w-[150px] min-w-[150px] max-w-[150px] bg-white px-4 py-3 text-left font-body text-xs text-on-surface-muted group-hover:bg-stone-50">
                  {isFirst && (
                    <span className="block truncate" title={row.adset_name}>{row.adset_name || "—"}</span>
                  )}
                </td>
                <td className="sticky left-[330px] z-10 w-[260px] min-w-[260px] max-w-[260px] border-r border-surface-mid/60 bg-white px-4 py-3 text-left group-hover:bg-stone-50">
                  {isFirst && (
                    <>
                      <span className="block truncate font-label text-xs font-semibold text-on-surface" title={row.ad_name}>{row.ad_name}</span>
                      <span className="mt-1 inline-block">
                        <AdTypeBadge type={row.ad_type} />
                      </span>
                    </>
                  )}
                </td>
                {breakdown && (
                  <td className={cn(
                    "whitespace-nowrap px-4 py-3 text-left text-xs capitalize",
                    isFirst ? "font-label font-semibold text-on-surface" : "pl-8 font-body text-on-surface-muted",
                  )}>
                    {row.breakdown ?? "—"}
                  </td>
                )}
                {columnFields.map((field) => (
                  <td
                    key={field.key}
                    className={cn(
                      "whitespace-nowrap px-4 py-3 text-xs tabular-nums",
                      NUMERIC_FORMATS.has(field.format) ? "text-right" : "text-left",
                    )}
                  >
                    {cellValue(row.values?.[field.key], field)}
                  </td>
                ))}
              </tr>
            );
          }),
        )}
      </tbody>
    );
  }

  function renderTotal() {
    if (!data || filteredRows.length === 0) return null;
    const ads = filteredAdIds.length;
    return (
      <tfoot>
        <tr className="border-t-2 border-surface-mid bg-surface-low font-bold">
          <td colSpan={3} className="sticky left-0 z-10 border-r border-surface-mid/60 bg-surface-low px-4 py-3 text-left">
            <span className="font-label text-xs font-bold text-on-surface">Total</span>
            <span className="ml-2 font-body text-[11px] font-normal text-on-surface-muted">
              {ads} {ads === 1 ? "ad" : "ads"}
            </span>
          </td>
          {breakdown && <td className="px-4 py-3" />}
          {columnFields.map((field) => {
            const value = totals.values[field.key];
            const estimated = totals.reachEstimated && (field.key === "reach" || field.key === "frequency");
            return (
              <td
                key={field.key}
                className={cn(
                  "whitespace-nowrap px-4 py-3 text-xs tabular-nums",
                  NUMERIC_FORMATS.has(field.format) ? "text-right" : "text-left",
                )}
              >
                {estimated && value != null ? "≈ " : ""}
                {cellValue(value, field)}
              </td>
            );
          })}
        </tr>
      </tfoot>
    );
  }

  function renderEmptyState(): ReactNode {
    if (loadError) {
      return (
        <div className="flex flex-col items-center justify-center px-4 py-16 text-center">
          <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-red-50">
            <CircleAlert size={24} className="text-red-400" />
          </div>
          <h3 className="mb-1 text-base font-bold text-[#1e293b]">Could not load ads</h3>
          <p className="max-w-md text-sm leading-relaxed text-[#94a3b8]">
            {loadError instanceof Error ? loadError.message : "Something went wrong. Try again in a moment."}
          </p>
        </div>
      );
    }
    if (data && allRows.length === 0) {
      return (
        <div className="flex flex-col items-center justify-center px-4 py-20 text-center">
          <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-50">
            <Megaphone size={24} className="text-primary-400" />
          </div>
          <h3 className="mb-1 text-base font-bold text-[#1e293b]">No ads in this date range</h3>
          <p className="max-w-md text-sm leading-relaxed text-[#94a3b8]">Try a wider date range.</p>
        </div>
      );
    }
    if (data && filteredRows.length === 0) {
      return (
        <div className="flex flex-col items-center justify-center px-4 py-16 text-center">
          <h3 className="mb-1 text-base font-bold text-[#1e293b]">No {typeLabel} ads in this date range</h3>
          <p className="max-w-md text-sm leading-relaxed text-[#94a3b8]">Pick another ad type above to see the rest.</p>
        </div>
      );
    }
    return null;
  }

  const emptyState = renderEmptyState();

  return (
    <div>
      <div className="mb-5 flex flex-col gap-4">
        <div>
          <h2 className="font-display text-xl font-bold text-on-surface">All ads</h2>
          <p className="mt-0.5 font-body text-xs text-on-surface-muted">
            Every ad that ran in the dates you picked, of every type, with the numbers exactly as Meta reports them.
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">From date</span>
            <input
              type="date"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.target.value)}
              className="h-9 rounded-xl border border-surface-mid bg-white px-3 font-body text-xs font-semibold text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">To date</span>
            <input
              type="date"
              value={dateTo}
              onChange={(event) => setDateTo(event.target.value)}
              className="h-9 rounded-xl border border-surface-mid bg-white px-3 font-body text-xs font-semibold text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200"
            />
          </label>
          <BreakdownSelect
            breakdowns={catalog?.breakdowns ?? []}
            value={breakdown}
            onChange={setBreakdown}
          />
          <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              onClick={handleSyncNow}
              disabled={syncing || !canManage}
              title={canManage ? "Pull the latest numbers from Meta now" : "Needs Meta Ads write access"}
              className="flex h-9 items-center justify-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 font-label text-xs font-bold text-amber-700 shadow-sm transition-all hover:bg-amber-100 disabled:opacity-40"
            >
              <Zap size={12} className={syncing ? "animate-pulse" : ""} /> {syncing ? "Syncing…" : "Sync now"}
            </button>
            <DataFromPicker
              canManage={canManage}
              onSaved={() => mutate()}
              note="The earliest date Anril shows for this ad account, on both All ads and Messaging ads. All ads lists every ad that ran from then on, including ads that were already off when you connected."
            />
            <MetaColumnPicker
              fields={fields}
              selected={columns}
              onChange={setColumns}
              defaultKeys={DEFAULT_COLUMN_KEYS}
            />
            <button
              type="button"
              onClick={handleDownload}
              disabled={!data || filteredRows.length === 0}
              className="flex h-9 items-center justify-center gap-2 rounded-xl bg-primary px-3 py-2 font-label text-xs font-bold text-white shadow-sm transition-all hover:bg-primary/90 disabled:opacity-40"
            >
              <Download size={12} /> Download CSV
            </button>
          </div>
        </div>

        <div role="group" aria-label="Filter by ad type" className="flex flex-wrap gap-2">
          {TYPE_FILTERS.map((filter) => {
            const active = typeFilter === filter.key;
            return (
              <button
                key={filter.key}
                type="button"
                aria-pressed={active}
                onClick={() => setTypeFilter(filter.key)}
                className={cn(
                  "flex h-7 items-center gap-1.5 rounded-full border px-3 font-label text-[11px] font-bold shadow-sm transition-all",
                  active
                    ? "border-primary-200 bg-primary-50 text-primary-700"
                    : "border-surface-mid bg-white text-on-surface-muted hover:border-primary-200 hover:text-primary-700",
                )}
              >
                {filter.label}
                {data && (
                  <span className={cn(
                    "rounded-full px-1.5 py-0.5 text-[9px] tabular-nums",
                    active ? "bg-primary-100 text-primary-700" : "bg-stone-100 text-stone-500",
                  )}>
                    {typeCounts.get(filter.key) ?? 0}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {showStartNote && data?.start_date && (
        <div role="status" className="mb-4 flex items-center gap-2 rounded-2xl border border-[#e2e8f0] bg-white px-4 py-2.5 font-body text-xs text-[#64748b]">
          <Info size={13} className="shrink-0 text-[#94a3b8]" />
          Showing data from {formatIsoDate(data.start_date)} — the history date set for this account.
        </div>
      )}

      {showReachNote && (
        <p role="status" className="mb-3 font-body text-[11px] text-slate-500">
          Total reach marked ≈ is an estimate: Meta&apos;s exact figure wasn&apos;t available, so it adds up each ad&apos;s reach and may count the same person twice. Refresh to try again.
        </p>
      )}

      <div className="card overflow-hidden rounded-2xl">
        {emptyState ?? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[960px]">
              {renderHeader()}
              {renderBody()}
              {renderTotal()}
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
