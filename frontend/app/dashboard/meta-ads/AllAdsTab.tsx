"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  ChevronRight,
  CircleAlert,
  Download,
  FileText,
  Globe,
  LayoutGrid,
  type LucideIcon,
  Megaphone,
  MessageCircle,
  MoreHorizontal,
  Phone,
  Search,
  Shuffle,
  Smartphone,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { useAllAdsTotalReach, useAllMetaAds, useMetaFieldCatalog, useReachByLevel } from "@/hooks/useApi";
import { api } from "@/lib/api";
import type { AllAdsParams, AllAdsRow, MetaField } from "@/lib/api";
import { cn } from "@/lib/utils";
import { buildAllAdsCsv, computeTotals, fieldsToFetch, totalExplanation } from "./allAdsReport";
import { HoverTip } from "./HoverTip";
import { fieldHelp } from "./metaFieldHelp";
import {
  AdTypeBadge,
  BreakdownSelect,
  MetaColumnPicker,
  deliveryLabel,
  formatMetaValue,
  usePersistedColumns,
} from "./metaFields";
import {
  DatesMenu,
  LevelSwitch,
  SummaryCard,
  rangeLabel,
  type ReportLevel,
} from "./reportControls";

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

const LEVEL_HEADINGS: Record<ReportLevel, string> = { campaign: "Campaign", adset: "Ad set", ad: "Ad" };
const LEVEL_NOUNS: Record<ReportLevel, [string, string]> = { campaign: ["campaign", "campaigns"], adset: ["ad set", "ad sets"], ad: ["ad", "ads"] };

/** A card's look per ad type (the backend's ad_type_label); anything unlisted gets the plain one. */
const TYPE_LOOKS: Record<string, { icon: LucideIcon; tint: string }> = {
  WhatsApp: { icon: MessageCircle, tint: "bg-emerald-50 text-emerald-700" },
  App: { icon: Smartphone, tint: "bg-indigo-50 text-indigo-700" },
  Website: { icon: Globe, tint: "bg-sky-50 text-sky-700" },
  "Instant form": { icon: FileText, tint: "bg-violet-50 text-violet-700" },
  "Multi-destination": { icon: Shuffle, tint: "bg-amber-50 text-amber-700" },
  Calls: { icon: Phone, tint: "bg-rose-50 text-rose-700" },
};
const PLAIN_LOOK = { icon: MoreHorizontal, tint: "bg-slate-100 text-slate-600" };

/** The few inputs a card needs, run through the same totals as the Total row. */
const CARD_FIELDS: MetaField[] = [
  { key: "spend", label: "Spend", group: "", format: "money", breakdown_ok: true },
  { key: "impressions", label: "Impressions", group: "", format: "number", breakdown_ok: true },
  { key: "inline_link_clicks", label: "Link clicks", group: "", format: "number", breakdown_ok: true },
  { key: "results", label: "Results", group: "", format: "number", breakdown_ok: true },
  { key: "result_type", label: "Result type", group: "", format: "text", breakdown_ok: true },
  { key: "cost_per_result", label: "Cost per result", group: "", format: "money", breakdown_ok: true },
];

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

function typeOf(row: AllAdsRow) {
  return (row.ad_type || "").trim() || "Other";
}

/** One cell: Delivery in Ads Manager's words, everything else by its format. */
function cellValue(value: unknown, field: MetaField) {
  if (field.key === "delivery") return deliveryLabel(value) || "—";
  return formatMetaValue(value, field.format);
}

function money(value: unknown) {
  return formatMetaValue(value, "money") as string;
}

function count(value: unknown) {
  return formatMetaValue(value, "number") as string;
}

/** One status for a campaign or ad set row: live if any ad is, removed only if every ad is. */
function groupDelivery(rows: AllAdsRow[]): string | null {
  const statuses = rows.map((row) => String(row.values?.delivery ?? "").toUpperCase()).filter(Boolean);
  if (!statuses.length) return null;
  if (statuses.includes("ACTIVE")) return "ACTIVE";
  if (statuses.every((status) => status === "ARCHIVED" || status === "DELETED")) return statuses.includes("ARCHIVED") ? "ARCHIVED" : "DELETED";
  return statuses.includes("PAUSED") ? "PAUSED" : statuses[0];
}

type TableRow = {
  key: string;
  /** Rows of one ad / ad set / campaign share it, so breakdown rows sit together. */
  groupKey: string;
  level: ReportLevel;
  id: string;
  title: string;
  subtitle: string;
  type: string | null;
  breakdown: string | null;
  values: Record<string, unknown>;
  reachEstimated: boolean;
};

/**
 * The table's rows at the chosen level. Campaign and ad set rows add up their
 * ads the way the Total row does; reach comes from Meta per campaign / ad set
 * (with a breakdown, the buckets' reach is added up and marked as an estimate).
 */
function groupRows(
  rows: AllAdsRow[],
  level: ReportLevel,
  fields: MetaField[],
  reachById: Record<string, number> | null | undefined,
): TableRow[] {
  if (level === "ad") {
    return rows.map((row) => ({
      key: `${row.meta_ad_id}:${row.breakdown ?? ""}`,
      groupKey: row.meta_ad_id,
      level,
      id: row.meta_ad_id,
      title: row.ad_name,
      subtitle: [row.campaign_name, row.adset_name].filter(Boolean).join(" › "),
      type: typeOf(row),
      breakdown: row.breakdown,
      values: row.values ?? {},
      reachEstimated: false,
    }));
  }
  const groups = new Map<string, AllAdsRow[]>();
  for (const row of rows) {
    const id = (level === "campaign" ? row.campaign_id : row.adset_id) || (level === "campaign" ? row.campaign_name : row.adset_name) || "—";
    const key = `${id}|${row.breakdown ?? ""}`;
    const list = groups.get(key);
    if (list) list.push(row);
    else groups.set(key, [row]);
  }
  return Array.from(groups.entries()).map(([key, members]) => {
    const first = members[0];
    const id = key.split("|")[0];
    const ads = new Set(members.map((member) => member.meta_ad_id)).size;
    const types = Array.from(new Set(members.map(typeOf)));
    // One ad: its own reach is exact. Several: Meta's per-group figure; undefined
    // while that loads (no ≈ yet), null once Meta has none (≈, added up).
    const ownReach = Number(first.values?.reach ?? 0);
    const groupReach = first.breakdown
      ? null
      : reachById === undefined ? undefined : reachById?.[id] ?? null;
    const { values, reachEstimated } = computeTotals(members, fields, ads > 1 ? groupReach : ownReach);
    const adsets = new Set(members.map((member) => member.adset_id)).size;
    return {
      key,
      groupKey: id,
      level,
      id,
      title: (level === "campaign" ? first.campaign_name : first.adset_name) || "—",
      subtitle: level === "campaign"
        ? `${adsets} ${adsets === 1 ? "ad set" : "ad sets"} · ${ads} ${ads === 1 ? "ad" : "ads"}`
        : `${first.campaign_name} · ${ads} ${ads === 1 ? "ad" : "ads"}`,
      type: types.length === 1 ? types[0] : null,
      breakdown: first.breakdown,
      values: { ...values, delivery: groupDelivery(members) },
      reachEstimated,
    };
  });
}

export function AllAdsTab() {
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("meta_ads.manage");
  const [syncing, setSyncing] = useState(false);
  const [dateFrom, setDateFrom] = useState(() => localDate(29));
  const [dateTo, setDateTo] = useState(() => localDate());
  const [breakdown, setBreakdown] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState("");
  const [level, setLevel] = useState<ReportLevel>("ad");
  const [search, setSearch] = useState("");
  const [campaignFilter, setCampaignFilter] = useState("");
  const [adsetFilter, setAdsetFilter] = useState("");
  const [adFilter, setAdFilter] = useState("");
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
        // Plus the inputs the Total row, cards and download need, even if hidden.
        fields: fieldsToFetch([...columnFields.map((field) => field.key), "results", "cost_per_result"]),
        breakdown: breakdown ?? undefined,
      }
    : null;
  const { data, error, mutate } = useAllMetaAds(request);
  const loadError = catalogError ?? error;
  const allRows = useMemo(() => data?.data ?? [], [data]);

  // Campaign / ad set / ad pick lists for the switch's ▾ menus, from the ads in range.
  const pickLists = useMemo(() => {
    const campaigns = new Map<string, string>();
    const adsets = new Map<string, string>();
    const ads = new Map<string, string>();
    // The ads inside each campaign / ad set: shown under names that repeat.
    const inside = new Map<string, Set<string>>();
    const note = (id: string, adName: string) => inside.set(id, (inside.get(id) ?? new Set()).add(adName));
    for (const row of allRows) {
      if (row.campaign_id) {
        campaigns.set(row.campaign_id, row.campaign_name);
        note(row.campaign_id, row.ad_name);
      }
      if (row.adset_id && (!campaignFilter || row.campaign_id === campaignFilter)) {
        adsets.set(row.adset_id, row.adset_name);
        note(row.adset_id, row.ad_name);
      }
      if ((!campaignFilter || row.campaign_id === campaignFilter) && (!adsetFilter || row.adset_id === adsetFilter)) ads.set(row.meta_ad_id, row.ad_name);
    }
    const list = (map: Map<string, string>) => Array.from(map, ([id, name]) => ({
      id,
      name: name || "—",
      hint: inside.has(id) ? `Ads: ${Array.from(inside.get(id)!).join(", ")}` : undefined,
    })).sort((a, b) => a.name.localeCompare(b.name));
    return { campaigns: list(campaigns), adsets: list(adsets), ads: list(ads) };
  }, [allRows, campaignFilter, adsetFilter]);

  // Everything except the type card: the cards count what each type would show.
  const narrowed = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return allRows.filter((row) =>
      (!campaignFilter || row.campaign_id === campaignFilter)
      && (!adsetFilter || row.adset_id === adsetFilter)
      && (!adFilter || row.meta_ad_id === adFilter)
      && (!needle || [row.ad_name, row.campaign_name, row.adset_name].some((text) => (text || "").toLowerCase().includes(needle))),
    );
  }, [allRows, search, campaignFilter, adsetFilter, adFilter]);
  const filteredRows = useMemo(
    () => (typeFilter ? narrowed.filter((row) => typeOf(row) === typeFilter) : narrowed),
    [narrowed, typeFilter],
  );

  const typeCards = useMemo(() => {
    const byType = new Map<string, AllAdsRow[]>();
    for (const row of narrowed) {
      const list = byType.get(typeOf(row));
      if (list) list.push(row);
      else byType.set(typeOf(row), [row]);
    }
    const card = (key: string, label: string, rows: AllAdsRow[], look: { icon: LucideIcon; tint: string }) => {
      const { values } = computeTotals(rows, CARD_FIELDS, undefined);
      return { key, label, look, ads: new Set(rows.map((row) => row.meta_ad_id)).size, values };
    };
    const types = Array.from(byType.entries())
      .map(([type, rows]) => card(type, type, rows, TYPE_LOOKS[type] ?? PLAIN_LOOK))
      .sort((a, b) => Number(b.values.spend ?? 0) - Number(a.values.spend ?? 0));
    return [card("", "All types", narrowed, { icon: LayoutGrid, tint: "bg-primary-50 text-primary-700" }), ...types];
  }, [narrowed]);

  const filtered = Boolean(typeFilter || search.trim() || campaignFilter || adsetFilter || adFilter);
  const filteredAdIds = useMemo(
    () => Array.from(new Set(filteredRows.map((row) => row.meta_ad_id))),
    [filteredRows],
  );
  const reachRange = data && filteredRows.length ? { date_from: data.date_from, date_to: data.date_to } : null;
  // Reach de-duplicated by Meta: the whole account when nothing is filtered (All
  // ads lists every ad that delivered), else just the ads in view.
  const { data: totalReachData, error: totalReachError, mutate: mutateTotalReach } = useAllAdsTotalReach(
    reachRange,
    filtered ? filteredAdIds : undefined,
  );
  const { data: levelReach } = useReachByLevel(level, reachRange, filtered ? filteredAdIds : undefined);
  const totalReach = totalReachData ? totalReachData.reach : totalReachError ? null : undefined;
  const totals = useMemo(
    () => computeTotals(filteredRows, columnFields, totalReach),
    [filteredRows, columnFields, totalReach],
  );
  const tableRows = useMemo(
    () => groupRows(filteredRows, level, columnFields, levelReach?.reach),
    [filteredRows, level, columnFields, levelReach],
  );
  const groupCount = new Set(tableRows.map((row) => row.groupKey)).size;
  const reachShown = columnFields.some((field) => field.key === "reach" || field.key === "frequency");
  const showReachNote = reachShown && (totals.reachEstimated || tableRows.some((row) => row.reachEstimated));
  const [singular, plural] = LEVEL_NOUNS[level];

  function clearFilters() {
    setTypeFilter("");
    setSearch("");
    setCampaignFilter("");
    setAdsetFilter("");
    setAdFilter("");
  }

  /** Like Ads Manager: a campaign row opens its ad sets, an ad set row its ads. */
  function openRow(row: TableRow) {
    if (row.level === "campaign") {
      setCampaignFilter(row.id);
      setAdsetFilter("");
      setAdFilter("");
      setLevel("adset");
    } else if (row.level === "adset") {
      setAdsetFilter(row.id);
      setAdFilter("");
      setLevel("ad");
    }
  }

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
  const columnCount = 1 + (breakdown ? 1 : 0) + columnFields.length;

  function renderHeader() {
    return (
      <thead>
        <tr className="border-b border-[#eef2f6]">
          <th className="sticky left-0 z-20 min-w-[300px] max-w-[340px] border-r border-[#eef2f6] bg-white px-4 py-3 text-left font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">
            {LEVEL_HEADINGS[level]}
          </th>
          {breakdown && (
            <th className="whitespace-nowrap px-4 py-3 text-left font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">Breakdown</th>
          )}
          {columnFields.map((field) => (
            <th
              key={field.key}
              className={cn(
                "whitespace-nowrap px-4 py-3 font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted",
                NUMERIC_FORMATS.has(field.format) ? "text-right" : "text-left",
              )}
            >
              <HoverTip text={fieldHelp(field)} side="bottom">{field.label}</HoverTip>
            </th>
          ))}
        </tr>
      </thead>
    );
  }

  function renderBody() {
    if (!data) {
      return (
        <tbody className="divide-y divide-[#f1f5f9]">
          {Array.from({ length: 6 }, (_, index) => (
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
    let previous = "";
    return (
      <tbody className="divide-y divide-[#f1f5f9]">
        {tableRows.map((row) => {
          // With a breakdown, one ad (or group) produces several rows; name it once.
          const isFirst = row.groupKey !== previous;
          previous = row.groupKey;
          const drills = row.level !== "ad";
          return (
            <tr
              key={row.key}
              onClick={drills ? () => openRow(row) : undefined}
              title={drills ? `Show this ${row.level === "campaign" ? "campaign's ad sets" : "ad set's ads"}` : undefined}
              className={cn("group transition-colors hover:bg-[#f8fafc]", drills && "cursor-pointer", !isFirst && "bg-stone-50/40")}
            >
              <td className="sticky left-0 z-10 min-w-[300px] max-w-[340px] border-r border-[#eef2f6] bg-white px-4 py-3 group-hover:bg-[#f8fafc]">
                {isFirst && (
                  <>
                    <div className="flex min-w-0 items-center gap-2">
                      <span className={cn("min-w-0 truncate font-label text-[13px] font-bold text-[#0A1528]", drills && "group-hover:text-primary-700")} title={row.title}>
                        {row.title}
                      </span>
                      {row.type && <AdTypeBadge type={row.type} />}
                      {drills && <ChevronRight size={14} className="shrink-0 text-[#cbd5e1] group-hover:text-primary-600" />}
                    </div>
                    {row.subtitle && <div className="mt-0.5 truncate font-body text-[11px] text-[#94a3b8]" title={row.subtitle}>{row.subtitle}</div>}
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
                    field.key === "spend" && "font-semibold text-on-surface",
                  )}
                >
                  {row.reachEstimated && (field.key === "reach" || field.key === "frequency") && row.values[field.key] != null ? "≈ " : ""}
                  {cellValue(row.values[field.key], field)}
                </td>
              ))}
            </tr>
          );
        })}
      </tbody>
    );
  }

  function renderTotal() {
    if (!data || filteredRows.length === 0) return null;
    return (
      <tfoot>
        <tr className="border-t-2 border-[#e2e8f0] bg-[#f8fafc] font-bold">
          <td className="sticky left-0 z-10 border-r border-[#eef2f6] bg-[#f8fafc] px-4 py-3 text-left">
            <span className="font-label text-sm font-bold text-on-surface">Total</span>
            <span className="ml-2 font-body text-[11px] font-normal text-on-surface-muted">
              {filteredAdIds.length} {filteredAdIds.length === 1 ? "ad" : "ads"}
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
                <HoverTip text={totalExplanation(field, totals.reachEstimated)}>
                  {estimated && value != null ? "≈ " : ""}
                  {cellValue(value, field)}
                </HoverTip>
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
          <h3 className="mb-1 text-sm font-bold text-[#1e293b]">No ads match</h3>
          <p className="max-w-md text-xs leading-relaxed text-[#94a3b8]">Pick another card above, or clear the search and filters.</p>
        </div>
      );
    }
    return null;
  }

  const emptyState = renderEmptyState();

  return (
    <div className="space-y-[18px]">
      <div role="group" aria-label="Filter ads by type" className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        {typeCards.slice(0, 8).map((card) => {
          const single = typeof card.values.result_type === "string" ? card.values.result_type : null;
          return (
            <SummaryCard
              key={card.key || "all"}
              selected={typeFilter === card.key}
              onSelect={() => setTypeFilter(card.key)}
              icon={card.look.icon}
              tint={card.look.tint}
              label={card.label}
              badge={data ? `${card.ads} ${card.ads === 1 ? "ad" : "ads"}` : "—"}
              value={data ? money(card.values.spend) : "—"}
              caption="spent"
              stats={single
                ? [
                    { label: single, value: data ? count(card.values.results) : "—" },
                    { label: "Per result", value: data ? money(card.values.cost_per_result) : "—" },
                    { label: "Link clicks", value: data ? count(card.values.inline_link_clicks) : "—" },
                  ]
                : [
                    { label: "Impressions", value: data ? count(card.values.impressions) : "—" },
                    { label: "Link clicks", value: data ? count(card.values.inline_link_clicks) : "—" },
                    { label: "Results", value: "—" },
                  ]}
            />
          );
        })}
      </div>

      <section aria-label="All ads" className="rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
        <div className="flex flex-wrap items-center gap-2 border-b border-[#eef2f6] p-3.5 xl:flex-nowrap">
          <LevelSwitch
            level={level}
            onLevel={setLevel}
            filters={{
              campaign: {
                options: pickLists.campaigns,
                value: campaignFilter,
                onChange: (id) => { setCampaignFilter(id); setAdsetFilter(""); setAdFilter(""); },
              },
              adset: {
                options: pickLists.adsets,
                value: adsetFilter,
                onChange: (id) => { setAdsetFilter(id); setAdFilter(""); },
              },
              ad: { options: pickLists.ads, value: adFilter, onChange: setAdFilter },
            }}
          />
          <label className="relative min-w-[160px] max-w-[240px] flex-1">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#64748b]" />
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search ads"
              aria-label="Search ad or campaign"
              className="h-9 w-full rounded-xl border border-[#e2e8f0] bg-[#f8fafc] pl-9 pr-3 font-body text-xs font-medium text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-200"
            />
          </label>
          <DatesMenu
            dateFrom={dateFrom}
            dateTo={dateTo}
            onChange={(from, to) => { setDateFrom(from); setDateTo(to); }}
            canManage={canManage}
            onHistorySaved={() => mutate()}
            historyNote="The earliest date Anril shows for this ad account, on both All ads and Messaging ads. All ads lists every ad that ran from then on, including ads that were already off when you connected."
          />
          <BreakdownSelect breakdowns={catalog?.breakdowns ?? []} value={breakdown} onChange={setBreakdown} />
          {filtered && (
            <button type="button" onClick={clearFilters}
              className="shrink-0 px-1 font-label text-xs font-bold text-primary-700 hover:text-primary-900">
              Clear
            </button>
          )}

          <span className="hidden flex-1 xl:block" />

          <button
            type="button"
            onClick={handleSyncNow}
            disabled={syncing || !canManage}
            title={canManage ? "Pull the latest numbers from Meta now" : "Needs Meta Ads write access"}
            className="flex h-9 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-xl border border-amber-200 bg-amber-50 px-3 font-label text-xs font-bold text-amber-800 shadow-sm transition-colors hover:bg-amber-100 disabled:opacity-40"
          >
            <Zap size={13} className={syncing ? "animate-pulse" : ""} /> {syncing ? "Syncing…" : "Sync now"}
          </button>
          <MetaColumnPicker fields={fields} selected={columns} onChange={setColumns} defaultKeys={DEFAULT_COLUMN_KEYS} />
          <button
            type="button"
            onClick={handleDownload}
            disabled={!data || filteredRows.length === 0}
            className="flex h-9 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-xl bg-primary px-3.5 font-label text-xs font-bold text-white shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-40"
          >
            <Download size={13} /> Export
          </button>
        </div>

        <div role="status" className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-[#eef2f6] bg-[#fbfcfd] px-4 py-2.5 font-body text-[11px] text-[#64748b]">
          <span className="font-bold text-[#0A1528]">
            {data ? `Showing ${groupCount} ${groupCount === 1 ? singular : plural} · ${rangeLabel(data.date_from, data.date_to)}` : "Loading…"}
          </span>
          <span aria-hidden="true">·</span>
          <span>Numbers live from Meta</span>
          {showStartNote && data?.start_date && (
            <>
              <span aria-hidden="true">·</span>
              <span>Numbers start {formatIsoDate(data.start_date)}, the history date set for this account</span>
            </>
          )}
          {showReachNote && (
            <>
              <span aria-hidden="true">·</span>
              <span className="text-amber-800">Reach marked ≈ is an estimate: Meta&apos;s exact figure wasn&apos;t available, so it may count someone twice. Refresh to try again.</span>
            </>
          )}
        </div>

        <div className="overflow-hidden rounded-b-2xl">
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
      </section>
    </div>
  );
}
