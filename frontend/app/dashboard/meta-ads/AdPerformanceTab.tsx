"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Archive,
  Ban,
  Check,
  ChevronDown,
  ChevronRight,
  Columns3,
  Copy,
  Download,
  KeyRound,
  LayoutGrid,
  Loader2,
  type LucideIcon,
  Megaphone,
  Pause,
  RefreshCw,
  RotateCcw,
  Search,
  SlidersHorizontal,
  X,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import { AiraLoader } from "@/components/AiraLoader";
import { api, AdPerformanceRow, AdTrackingCodeResponse, TrackedAd } from "@/lib/api";
import {
  useAdFilters,
  useAdPerformance,
  useAdTotalReach,
  useReachByLevel,
  useSyncStart,
  useTrackedAds,
} from "@/hooks/useApi";
import { cn } from "@/lib/utils";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { TickMark } from "@/components/ui/controls";
import { ChannelMarks, deliveryLabel } from "./metaFields";
import {
  DatesMenu,
  LevelSwitch,
  MoreMenu,
  SummaryCard,
  TOOLBAR_BUTTON,
  rangeLabel,
  type ReportLevel,
} from "./reportControls";
import { AdDetailPanel } from "./AdDetailPanel";
import { MESSAGING_TOTAL_RULES, TotalLabel } from "./TotalLabel";

type MetricKey =
  | "delivery_status"
  | "budget"
  | "impressions"
  | "reach"
  | "frequency"
  | "inline_link_clicks"
  | "clicks_all"
  | "messages"
  | "meta_conversations"
  | "meta_conversations_started"
  | "meta_new_contacts"
  | "meta_conversations_replied"
  | "meta_blocks"
  | "cost_per_meta_conversation"
  | "conversation_rate"
  | "meta_conversation_rate"
  | "attribution_gap"
  | "clicked_no_message"
  | "no_message_rate"
  | "spend"
  | "cpc"
  | "cost_per_message"
  | "ctr"
  | "cpm"
  | "hot"
  | "hot_rate"
  | "cost_per_hot";

const METRICS: { key: MetricKey; label: string; defaultVisible: boolean; help: string }[] = [
  { key: "delivery_status", label: "Delivery", defaultVisible: true, help: "The ad's own delivery status in Meta. Ads removed in Ads Manager show as Deleted." },
  { key: "budget", label: "Budget", defaultVisible: false, help: "Daily or lifetime budget from the campaign or ad set in Meta" },
  { key: "impressions", label: "Impressions", defaultVisible: true, help: "Times the ad was shown" },
  { key: "reach", label: "Reach", defaultVisible: true, help: "Unique people reached in Meta for the selected period" },
  { key: "frequency", label: "Frequency", defaultVisible: false, help: "Impressions divided by unique Meta reach" },
  { key: "inline_link_clicks", label: "Chat clicks", defaultVisible: true, help: "Clicks that opened a WhatsApp, Instagram or Messenger chat" },
  { key: "clicks_all", label: "Clicks (all)", defaultVisible: false, help: "All interactions Meta classifies as clicks" },
  { key: "messages", label: "Messages sent (Anril confirmed)", defaultVisible: true, help: "Unique people who messaged from this ad on WhatsApp, Instagram or Messenger; repeat messages from the same person and ad count once" },
  { key: "meta_conversations", label: "Meta messaging contacts", defaultVisible: false, help: "People who messaged your business after this ad, as counted by Meta. Compare it with Messages sent (Anril confirmed)" },
  { key: "meta_conversations_started", label: "Messaging conversations started", defaultVisible: false, help: "New chats Meta credits to this ad: someone messaging you for the first time, or again after 7 or more quiet days. This is the Results number in Ads Manager" },
  { key: "meta_new_contacts", label: "New messaging contacts", defaultVisible: false, help: "People who messaged your business for the first time, as counted by Meta" },
  { key: "meta_conversations_replied", label: "Messaging conversations replied", defaultVisible: false, help: "Meta's count of chats from this ad that your business replied to within 24 hours. Meta often leaves this empty for chats answered through Anril, the same as in Ads Manager. For Anril's own count, use Messages sent" },
  { key: "meta_blocks", label: "Messaging blocks", defaultVisible: false, help: "People who blocked your business after messaging from this ad. Lower is better" },
  { key: "conversation_rate", label: "Message rate", defaultVisible: true, help: "Anril-confirmed messages divided by chat clicks" },
  { key: "meta_conversation_rate", label: "Meta messaging contact rate", defaultVisible: false, help: "Meta messaging contacts divided by chat clicks" },
  { key: "attribution_gap", label: "Tracking difference", defaultVisible: false, help: "Anril-confirmed messages minus Meta messaging contacts" },
  { key: "clicked_no_message", label: "No message", defaultVisible: true, help: "Chat clicks not matched to a unique Anril lead for this ad" },
  { key: "no_message_rate", label: "No-message rate", defaultVisible: false, help: "No-message clicks divided by chat clicks" },
  { key: "spend", label: "Spend", defaultVisible: true, help: "Amount spent in the selected period" },
  { key: "cpc", label: "CPC", defaultVisible: true, help: "Spend divided by chat clicks" },
  { key: "cost_per_message", label: "Cost / sent message", defaultVisible: true, help: "Spend divided by Anril-confirmed messages" },
  { key: "cost_per_meta_conversation", label: "Cost per messaging conversation started", defaultVisible: false, help: "Spend divided by Messaging conversations started" },
  { key: "ctr", label: "CTR", defaultVisible: false, help: "Click-through rate: chat clicks divided by impressions" },
  { key: "cpm", label: "CPM", defaultVisible: false, help: "Cost per mille: spend per 1,000 impressions" },
  { key: "hot", label: "Hot", defaultVisible: false, help: "Anril leads currently in the Hot segment" },
  { key: "hot_rate", label: "Hot lead rate", defaultVisible: false, help: "Hot leads divided by Anril-confirmed messages" },
  { key: "cost_per_hot", label: "Cost / hot lead", defaultVisible: false, help: "Spend divided by Hot leads" },
];

/** Numbers Meta reports as-is. */
const META_DIRECT_METRICS = new Set<MetricKey>([
  "delivery_status", "budget", "impressions", "reach", "inline_link_clicks", "clicks_all", "meta_conversations", "spend",
  "meta_conversations_started", "meta_new_contacts", "meta_conversations_replied", "meta_blocks",
]);

/** Anril divides Meta's own numbers; no Anril lead data is involved. */
const META_CALCULATED_METRICS = new Set<MetricKey>([
  "frequency", "cpc", "ctr", "cpm", "meta_conversation_rate", "cost_per_meta_conversation",
]);

// Everything else is built on Anril's own attributed leads.
const METRIC_GROUPS = [
  { title: "From Meta", metrics: METRICS.filter((metric) => META_DIRECT_METRICS.has(metric.key)) },
  { title: "Calculated from Meta numbers", metrics: METRICS.filter((metric) => META_CALCULATED_METRICS.has(metric.key)) },
  {
    title: "From Anril leads",
    metrics: METRICS.filter((metric) => !META_DIRECT_METRICS.has(metric.key) && !META_CALCULATED_METRICS.has(metric.key)),
  },
];

const DEFAULT_METRICS = new Set(METRICS.filter((metric) => metric.defaultVisible).map((metric) => metric.key));

function isoLocal(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function localDate(daysBack = 0) {
  const date = new Date();
  date.setDate(date.getDate() - daysBack);
  return isoLocal(date);
}

/** "2026-08-24" -> "24 Aug 2026". */
function formatDay(iso: string) {
  return new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function money(value: number | null | undefined) {
  if (value == null) return "—";
  return "₹" + Math.round(value).toLocaleString("en-IN");
}

function count(value: number | null | undefined) {
  return Math.round(value ?? 0).toLocaleString("en-IN");
}

function percent(value: number | null | undefined) {
  return value == null ? "—" : `${value.toFixed(1)}%`;
}

function decimal(value: number | null | undefined) {
  return value == null ? "—" : value.toFixed(2);
}

function budgetLabel(row: AdPerformanceRow) {
  const suffix = row.budget_level === "ad_set"
    ? " · Ad set"
    : row.budget_level === "campaign"
      ? " · Campaign"
      : "";
  if (row.daily_budget != null) return `${money(row.daily_budget)}/day${suffix}`;
  if (row.lifetime_budget != null) return `${money(row.lifetime_budget)} lifetime${suffix}`;
  return "—";
}

function signedCount(value: number) {
  if (!value) return "0";
  return `${value > 0 ? "+" : ""}${Math.round(value).toLocaleString("en-IN")}`;
}

type ChannelCounts = { whatsapp: number; instagram: number; messenger: number };

const CHANNEL_SHORT: { key: keyof ChannelCounts; short: string }[] = [
  { key: "whatsapp", short: "WA" },
  { key: "instagram", short: "IG" },
  { key: "messenger", short: "Messenger" },
];

/** "240 WA · 20 IG · 8 Messenger". Only for ads/totals that reached two or more apps. */
function channelSplit(byChannel: ChannelCounts | undefined): string | null {
  if (!byChannel) return null;
  const parts = CHANNEL_SHORT.filter((channel) => (byChannel[channel.key] ?? 0) > 0)
    .map((channel) => `${count(byChannel[channel.key])} ${channel.short}`);
  return parts.length >= 2 ? parts.join(" · ") : null;
}

function statusLabel(status: string | null | undefined) {
  return deliveryLabel(status) || "Unknown";
}

/** Meta statuses meaning the ad no longer exists in Ads Manager, as opposed to
 * merely not delivering. Rows in these states are kept for their spend history
 * but rendered as struck-through and dimmed. */
const REMOVED_STATUSES = new Set(["DELETED", "ARCHIVED"]);

function isRemoved(status: string | null | undefined) {
  return REMOVED_STATUSES.has((status || "").toUpperCase());
}

/** The cards above the table. Keys mirror DELIVERY_GROUPS in
 * backend/app/services/ad_performance.py -- the CSV export filters server-side
 * with the same key, so the download matches what is on screen. "Needs
 * attention" only shows when an ad is in one of those states. */
const DELIVERY_CARDS: { key: string; label: string; statuses: Set<string> | null; icon: LucideIcon; tint: string; always: boolean }[] = [
  { key: "", label: "All ads", statuses: null, icon: LayoutGrid, tint: "bg-primary-50 text-primary-700", always: true },
  { key: "active", label: "Active", statuses: new Set(["ACTIVE"]), icon: Activity, tint: "bg-emerald-50 text-emerald-700", always: true },
  { key: "paused", label: "Switched off", statuses: new Set(["PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED"]), icon: Pause, tint: "bg-amber-50 text-amber-700", always: true },
  { key: "removed", label: "Archived & deleted", statuses: new Set(["ARCHIVED", "DELETED"]), icon: Archive, tint: "bg-slate-100 text-slate-600", always: true },
  { key: "issues", label: "Needs attention", statuses: new Set(["DISAPPROVED", "WITH_ISSUES", "PENDING_REVIEW", "PENDING_BILLING_INFO"]), icon: AlertTriangle, tint: "bg-red-50 text-red-700", always: false },
];

const ISSUE_STATUSES = DELIVERY_CARDS[4].statuses ?? new Set<string>();

function matchesDelivery(row: AdPerformanceRow, key: string) {
  const card = DELIVERY_CARDS.find((item) => item.key === key);
  return !card?.statuses || card.statuses.has((row.delivery_status || "").toUpperCase());
}

const LEVEL_HEADINGS: Record<ReportLevel, string> = { campaign: "Campaign", adset: "Ad set", ad: "Ad" };
const LEVEL_NOUNS: Record<ReportLevel, [string, string]> = { campaign: ["campaign", "campaigns"], adset: ["ad set", "ad sets"], ad: ["ad", "ads"] };

/** Columns that hold words rather than numbers, so they read left-aligned. */
const TEXT_METRICS = new Set<MetricKey>(["delivery_status", "budget"]);

/** "8 Nov, 11:45 am" in the viewer's own clock. */
function syncedAt(iso: string) {
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

function RateBar({ value }: { value: number | null }) {
  return (
    <span className="inline-flex w-[120px] items-center gap-2">
      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-[#eef2f6]">
        <span className="block h-full rounded-full bg-primary-500" style={{ width: `${Math.max(0, Math.min(100, value ?? 0))}%` }} />
      </span>
      <span className="w-11 text-right font-bold">{percent(value)}</span>
    </span>
  );
}

/** One status for a campaign or ad set row: live if any ad is, removed only if every ad is. */
function groupStatus(rows: AdPerformanceRow[]): string {
  const statuses = rows.map((row) => (row.delivery_status || "").toUpperCase());
  if (statuses.includes("ACTIVE")) return "ACTIVE";
  if (statuses.every((status) => REMOVED_STATUSES.has(status))) return statuses.includes("ARCHIVED") ? "ARCHIVED" : "DELETED";
  return statuses.find((status) => ISSUE_STATUSES.has(status)) ?? "PAUSED";
}

type TableRow = { key: string; level: ReportLevel; row: AdPerformanceRow; title: string; subtitle: string };

/**
 * The table's rows at the chosen level. Campaign and ad set rows add up their
 * ads (aggregateRows); reach comes from Meta per campaign / ad set, since adding
 * the ads' reach would count anyone who saw two of them twice.
 */
function groupRows(rows: AdPerformanceRow[], level: ReportLevel, reachById: Record<string, number> | null | undefined): TableRow[] {
  if (level === "ad") {
    return rows.map((row) => ({
      key: row.ad_creative_id,
      level,
      row,
      title: row.creative_label,
      subtitle: `${row.campaign_name} › ${row.adset_name ?? "—"}`,
    }));
  }
  const groups = new Map<string, AdPerformanceRow[]>();
  for (const row of rows) {
    const id = level === "campaign"
      ? row.meta_campaign_id || row.campaign_id || row.campaign_name
      : row.adset_id || row.adset_name || "—";
    const list = groups.get(id);
    if (list) list.push(row);
    else groups.set(id, [row]);
  }
  return Array.from(groups.entries()).map(([id, members]) => {
    const first = members[0];
    const summed = aggregateRows(members);
    const metaReach = reachById?.[id];
    const reach = metaReach ?? summed.reach;
    const budgetHere = first.budget_level === (level === "campaign" ? "campaign" : "ad_set");
    const adsets = new Set(members.map((member) => member.adset_id)).size;
    const title = level === "campaign" ? first.campaign_name : first.adset_name ?? "—";
    return {
      key: `${level}:${id}`,
      level,
      title,
      subtitle: level === "campaign"
        ? `${first.campaign_created_at ? `Created ${createdOn(first.campaign_created_at)} · ` : ""}${adsets} ${adsets === 1 ? "ad set" : "ad sets"} · ${members.length} ${members.length === 1 ? "ad" : "ads"}`
        : `${first.campaign_name} · ${members.length} ${members.length === 1 ? "ad" : "ads"}`,
      row: {
        ...summed,
        ad_creative_id: `${level}:${id}`,
        creative_label: title,
        campaign_id: first.campaign_id,
        meta_campaign_id: first.meta_campaign_id,
        campaign_name: first.campaign_name,
        adset_id: level === "adset" ? first.adset_id : null,
        adset_name: level === "adset" ? first.adset_name : null,
        delivery_status: groupStatus(members),
        daily_budget: budgetHere ? first.daily_budget : null,
        lifetime_budget: budgetHere ? first.lifetime_budget : null,
        budget_level: budgetHere ? first.budget_level : null,
        reach,
        // Not while Meta's figure is still loading (reachById undefined).
        reach_estimated: reachById !== undefined && metaReach == null && members.length > 1 && summed.reach > 0,
        frequency: reach ? summed.impressions / reach : null,
      },
    };
  });
}

/** Days between an ISO date and today in India. */
/** "14 Aug 2026" in IST: the day the campaign was created in Ads Manager. */
function createdOn(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Kolkata" });
}

function daysSinceIst(isoDate: string): number {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
  return Math.round((Date.parse(today) - Date.parse(isoDate.slice(0, 10))) / 86_400_000);
}

/**
 * Meta's ACTIVE only means the ad is switched on. When it hasn't actually been shown
 * for 2+ days (a day of slack for Meta's reporting delay), say so on the pill.
 */
function idleSince(status: string, lastDelivery: string | null | undefined): string | null {
  if (status !== "ACTIVE") return null;
  if (!lastDelivery) return "not delivered yet";
  if (daysSinceIst(lastDelivery) < 2) return null;
  const day = new Date(`${lastDelivery.slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  return `no delivery since ${day}`;
}

function StatusBadge({ status, lastDelivery }: { status: string | null | undefined; lastDelivery?: string | null }) {
  const normalized = (status || "").toUpperCase();
  const removed = isRemoved(normalized);
  const isError = normalized.includes("DISAPPROVED") || normalized.includes("ERROR");
  // lastDelivery is undefined on rows the backend didn't check (e.g. the Total row).
  const idle = lastDelivery === undefined ? null : idleSince(normalized, lastDelivery);
  return (
    <span
      title={
        removed
          ? "Removed in Meta Ads Manager. Kept here for its spend history."
          : idle
            ? "Switched on in Meta, but it hasn't been shown to anyone recently. Check its budget, schedule and payment method in Ads Manager."
            : undefined
      }
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 font-label text-[10px] font-bold",
        removed
          ? "bg-stone-200/60 text-stone-500 ring-1 ring-inset ring-stone-300/70"
          : idle
            ? "bg-amber-50 text-amber-700"
            : normalized === "ACTIVE"
              ? "bg-emerald-50 text-emerald-700"
              : normalized === "PAUSED"
                ? "bg-amber-50 text-amber-700"
                : isError
                  ? "bg-red-50 text-red-700"
                  : "bg-stone-100 text-stone-600",
      )}
    >
      {removed ? (
        <Ban className="h-2.5 w-2.5 shrink-0" strokeWidth={3} aria-hidden />
      ) : (
        <span className={cn(
          "h-1.5 w-1.5 rounded-full",
          idle
            ? "bg-amber-500"
            : normalized === "ACTIVE"
              ? "bg-emerald-500"
              : normalized === "PAUSED"
                ? "bg-amber-500"
                : isError
                  ? "bg-red-500"
                  : "bg-stone-400",
        )} />
      )}
      {statusLabel(status)}
      {idle && <span className="font-semibold">· {idle}</span>}
    </span>
  );
}

function aggregateRows(rows: AdPerformanceRow[]): AdPerformanceRow {
  const total = rows.reduce((acc, row) => {
    acc.impressions += row.impressions;
    acc.reach += row.reach;
    acc.inline_link_clicks += row.inline_link_clicks;
    acc.clicks_all += row.clicks_all;
    acc.messages += row.messages;
    acc.meta_conversations += row.meta_conversations;
    acc.meta_conversations_started += row.meta_conversations_started;
    acc.meta_new_contacts += row.meta_new_contacts;
    acc.meta_conversations_replied += row.meta_conversations_replied;
    acc.meta_blocks += row.meta_blocks;
    acc.clicked_no_message += row.clicked_no_message;
    acc.hot += row.hot;
    acc.spend += row.spend;
    acc.byChannel.whatsapp += row.messages_by_channel?.whatsapp ?? 0;
    acc.byChannel.instagram += row.messages_by_channel?.instagram ?? 0;
    acc.byChannel.messenger += row.messages_by_channel?.messenger ?? 0;
    return acc;
  }, {
    impressions: 0,
    reach: 0,
    inline_link_clicks: 0,
    clicks_all: 0,
    messages: 0,
    meta_conversations: 0,
    meta_conversations_started: 0,
    meta_new_contacts: 0,
    meta_conversations_replied: 0,
    meta_blocks: 0,
    clicked_no_message: 0,
    hot: 0,
    spend: 0,
    byChannel: { whatsapp: 0, instagram: 0, messenger: 0 } as ChannelCounts,
  });

  const { byChannel, ...sums } = total;
  return {
    ad_creative_id: "total",
    creative_label: "Total",
    meta_ad_id: "",
    meta_ad_account_id: "",
    adset_id: null,
    adset_name: null,
    campaign_id: null,
    campaign_name: "Total",
    delivery_status: null,
    daily_budget: null,
    lifetime_budget: null,
    budget_level: null,
    ...sums,
    messages_by_channel: byChannel,
    frequency: total.reach ? total.impressions / total.reach : null,
    conversation_rate: total.inline_link_clicks ? (total.messages / total.inline_link_clicks) * 100 : null,
    meta_conversation_rate: total.inline_link_clicks ? (total.meta_conversations / total.inline_link_clicks) * 100 : null,
    attribution_gap: total.messages - total.meta_conversations,
    no_message_rate: total.inline_link_clicks ? (total.clicked_no_message / total.inline_link_clicks) * 100 : null,
    hot_rate: total.messages ? (total.hot / total.messages) * 100 : null,
    ctr: total.impressions ? (total.inline_link_clicks / total.impressions) * 100 : null,
    cpm: total.impressions ? (total.spend / total.impressions) * 1000 : null,
    cpc: total.inline_link_clicks ? total.spend / total.inline_link_clicks : null,
    cost_per_message: total.messages ? total.spend / total.messages : null,
    cost_per_meta_conversation: total.meta_conversations_started ? total.spend / total.meta_conversations_started : null,
    cost_per_hot: total.hot ? total.spend / total.hot : null,
  };
}

function metricValue(metric: MetricKey, row: AdPerformanceRow) {
  switch (metric) {
    case "delivery_status":
      return <StatusBadge status={row.delivery_status} lastDelivery={row.last_delivery_date} />;
    case "budget":
      return budgetLabel(row);
    case "reach":
      return row.reach_estimated ? (
        <span title="Estimate: Meta's exact figure wasn't available, so this adds up reach and may count someone twice">≈ {count(row.reach)}</span>
      ) : count(row.reach);
    case "impressions":
    case "inline_link_clicks":
    case "clicks_all":
    case "messages":
    case "meta_conversations":
    case "meta_conversations_started":
    case "meta_new_contacts":
    case "meta_conversations_replied":
    case "meta_blocks":
    case "clicked_no_message":
    case "hot":
      return count(row[metric]);
    case "attribution_gap":
      return signedCount(row.attribution_gap);
    case "conversation_rate":
    case "meta_conversation_rate":
    case "no_message_rate":
    case "hot_rate":
    case "ctr":
      return percent(row[metric]);
    case "spend":
    case "cpc":
    case "cost_per_message":
    case "cost_per_meta_conversation":
    case "cpm":
    case "cost_per_hot":
      return money(row[metric]);
    case "frequency":
      return decimal(row.frequency);
  }
}

export function AdPerformanceTab() {
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("meta_ads.manage");
  const [campaignId, setCampaignId] = useState("");
  const [adsetId, setAdsetId] = useState("");
  const [creativeId, setCreativeId] = useState("");
  const [dateFrom, setDateFrom] = useState(() => localDate(29));
  const [dateTo, setDateTo] = useState(() => localDate());
  const [exporting, setExporting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [showColumns, setShowColumns] = useState(false);
  const [showTrackingModal, setShowTrackingModal] = useState(false);
  const [trackingCreativeId, setTrackingCreativeId] = useState("");
  const [trackingMessage, setTrackingMessage] = useState("Hi, I'm interested in this service.");
  const [trackingResult, setTrackingResult] = useState<AdTrackingCodeResponse | null>(null);
  const [generatingTrackingCode, setGeneratingTrackingCode] = useState(false);
  const [copiedTrackingMessage, setCopiedTrackingMessage] = useState(false);
  const [deliveryStatus, setDeliveryStatus] = useState("");
  const [level, setLevel] = useState<ReportLevel>("ad");
  const [search, setSearch] = useState("");
  const [visibleMetrics, setVisibleMetrics] = useState<Set<MetricKey>>(() => new Set(DEFAULT_METRICS));
  const [showManage, setShowManage] = useState(false);
  const [detailRow, setDetailRow] = useState<AdPerformanceRow | null>(null);
  const [manageQuery, setManageQuery] = useState("");

  useEffect(() => {
    if (!showManage) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setShowManage(false);
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [showManage]);


  const { data: filters, mutate: mutateFilters } = useAdFilters();
  const { data: syncStart } = useSyncStart();
  const { data: trackedData, mutate: mutateTracked } = useTrackedAds(showManage);
  const params = {
    campaign_id: campaignId || undefined,
    adset_id: adsetId || undefined,
    ad_creative_id: creativeId || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  };
  const { data, isLoading, isValidating, mutate } = useAdPerformance(params);
  const allRows = useMemo(() => data?.data ?? [], [data]);
  // Search narrows everything below it -- cards included -- so the cards'
  // numbers always add up to what the table can show.
  const searched = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return allRows;
    return allRows.filter((row) =>
      [row.creative_label, row.campaign_name, row.adset_name ?? ""].some((text) => text.toLowerCase().includes(needle)),
    );
  }, [allRows, search]);
  // The selected card is the delivery filter: the table, Total row and export
  // all describe the same set.
  const rows = useMemo(
    () => (deliveryStatus ? searched.filter((row) => matchesDelivery(row, deliveryStatus)) : searched),
    [searched, deliveryStatus],
  );
  const deliveryCards = useMemo(
    () => DELIVERY_CARDS.map((card) => {
      const members = card.key ? searched.filter((row) => matchesDelivery(row, card.key)) : searched;
      return { ...card, count: members.length, totals: aggregateRows(members) };
    }).filter((card) => card.always || card.count > 0),
    [searched],
  );
  // Adding the rows' reach counts anyone who saw two of these ads twice, so the
  // Total row asks Meta for the de-duplicated figure, like Ads Manager's total.
  const { data: totalReach, error: totalReachError } = useAdTotalReach(
    rows.map((row) => row.ad_creative_id),
    dateFrom || undefined,
    dateTo || undefined,
  );
  const totals = useMemo(() => {
    const summed = aggregateRows(rows);
    const reach = totalReach?.reach;
    if (reach != null) {
      return { ...summed, reach, reach_estimated: false, frequency: reach ? summed.impressions / reach : null };
    }
    const metaFailed = Boolean(totalReachError) || totalReach?.reach === null;
    return {
      ...summed,
      reach_estimated: rows.some((row) => row.reach_estimated) || (metaFailed && rows.length > 1 && summed.reach > 0),
    };
  }, [rows, totalReach, totalReachError]);
  const selectedMetrics = useMemo(
    () => METRICS.filter((metric) => visibleMetrics.has(metric.key)),
    [visibleMetrics],
  );
  const { data: levelReach } = useReachByLevel(
    level,
    dateFrom && dateTo ? { date_from: dateFrom, date_to: dateTo } : null,
    rows.map((row) => row.meta_ad_id).filter(Boolean),
  );
  const tableRows = useMemo(() => groupRows(rows, level, levelReach?.reach), [rows, level, levelReach]);
  const [singular, plural] = LEVEL_NOUNS[level];
  const showingLabel = isLoading
    ? "Loading…"
    : `Showing ${tableRows.length} ${tableRows.length === 1 ? singular : plural} · ${rangeLabel(dateFrom, dateTo)}`;

  const adsetOptions = useMemo(
    () => (filters?.adsets ?? []).filter((adset) => !campaignId || adset.campaign_id === campaignId),
    [filters, campaignId],
  );
  // Generate ID writes a code into the ad's pre-filled message, which only WhatsApp
  // ads have. Older rows without channels are WhatsApp-only creatives.
  const whatsappCreatives = useMemo(
    () => (filters?.creatives ?? []).filter(
      (creative) => !creative.messaging_channels?.length || creative.messaging_channels.includes("whatsapp"),
    ),
    [filters],
  );
  const creativeOptions = useMemo(
    () => (filters?.creatives ?? []).filter(
      (creative) => (!campaignId || creative.campaign_id === campaignId) && (!adsetId || creative.adset_id === adsetId),
    ),
    [filters, campaignId, adsetId],
  );
  const hasFilters = Boolean(campaignId || adsetId || creativeId || search.trim() || deliveryStatus);
  /** "Ads: New Sales ad, New Engagement ad" -- tells apart campaigns or ad sets that share a name. */
  function adsIn(key: "campaign_id" | "adset_id", id: string) {
    const names = (filters?.creatives ?? []).filter((creative) => creative[key] === id).map((creative) => creative.name);
    return names.length ? `Ads: ${names.join(", ")}` : undefined;
  }
  const showSyncNote = Boolean(syncStart?.start_date) && dateFrom < (syncStart?.start_date ?? "").slice(0, 10);

  const trackedGroups = useMemo(() => {
    const needle = manageQuery.trim().toLowerCase();
    const byCampaign = new Map<string, TrackedAd[]>();
    for (const ad of trackedData?.data ?? []) {
      if (needle && !ad.creative_label.toLowerCase().includes(needle) && !ad.campaign_name.toLowerCase().includes(needle)) continue;
      const list = byCampaign.get(ad.campaign_name) ?? [];
      list.push(ad);
      byCampaign.set(ad.campaign_name, list);
    }
    return Array.from(byCampaign.entries());
  }, [trackedData, manageQuery]);

  const campaignNames = useMemo(
    () => new Map((filters?.campaigns ?? []).map((campaign) => [campaign.id, campaign.name])),
    [filters],
  );
  const adsetNames = useMemo(
    () => new Map((filters?.adsets ?? []).map((adset) => [adset.id, adset.name])),
    [filters],
  );

  function toggleMetric(key: MetricKey) {
    setVisibleMetrics((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function clearFilters() {
    setCampaignId("");
    setAdsetId("");
    setCreativeId("");
    setDeliveryStatus("");
    setSearch("");
  }

  /** Like Ads Manager: a campaign row opens its ad sets, an ad set row its ads, an ad its detail panel. */
  function openRow(item: TableRow) {
    if (item.level === "ad") {
      setDetailRow(item.row);
    } else if (item.level === "campaign") {
      setCampaignId(item.row.campaign_id ?? "");
      setAdsetId("");
      setCreativeId("");
      setLevel("adset");
    } else {
      setAdsetId(item.row.adset_id ?? "");
      setCreativeId("");
      setLevel("ad");
    }
  }

  /** Optimistic on the tracked-ads list; SWR rolls it back if the save fails. */
  async function toggleTracked(ad: TrackedAd) {
    const next = !ad.tracked;
    const apply = (current: { data: TrackedAd[] } | undefined) => ({
      data: (current?.data ?? []).map((item) =>
        item.ad_creative_id === ad.ad_creative_id ? { ...item, tracked: next } : item,
      ),
    });
    try {
      await mutateTracked(
        async (current) => {
          await api.inboundLeads.setCreativeTracking(ad.ad_creative_id, next);
          return apply(current);
        },
        { optimisticData: apply, rollbackOnError: true, revalidate: false },
      );
      await Promise.all([mutate(), mutateFilters()]);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not update this ad");
    }
  }

  async function handleSyncNow() {
    setSyncing(true);
    try {
      const result = await api.inboundLeads.adSyncNow();
      if (!result.ok) {
        toast.error(result.error ?? "Sync failed — no details returned");
        return;
      }
      // Refresh first so the message below can say whether the table still has saved rows.
      const [fresh] = await Promise.all([mutate(), mutateFilters()]);
      const tableHasRows = (fresh?.data ?? []).length > 0;
      if (result.written > 0) {
        toast.success(`Synced ${result.written} messaging ad row${result.written === 1 ? "" : "s"}`);
      } else if (result.rows_fetched > 0) {
        toast.info("Meta returned ads for the last 30 days, but none were messaging ads.");
      } else {
        // Sync only asks Meta for the last 30 days; the table shows whatever dates are picked.
        toast.info(
          tableHasRows
            ? "No ad delivery in the last 30 days — the table shows saved numbers from earlier."
            : "No ad delivery in the last 30 days."
        );
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  async function handleExport() {
    setExporting(true);
    try {
      // The table filters delivery client-side for instant feedback; the CSV is
      // built server-side, so the choice has to travel with the request.
      await api.inboundLeads.adPerformanceExportCsv({
        ...params,
        delivery_status: deliveryStatus || undefined,
      });
      toast.success("Downloaded: ad_performance.csv");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }

  function openTrackingModal() {
    const selected = whatsappCreatives.some((creative) => creative.id === creativeId) ? creativeId : "";
    setTrackingCreativeId(selected || whatsappCreatives[0]?.id || "");
    setTrackingResult(null);
    setCopiedTrackingMessage(false);
    setShowTrackingModal(true);
  }

  async function handleGenerateTrackingCode() {
    if (!trackingCreativeId) {
      toast.error("Select a creative first");
      return;
    }
    setGeneratingTrackingCode(true);
    try {
      const result = await api.inboundLeads.generateAdTrackingCode({
        ad_creative_id: trackingCreativeId,
        message: trackingMessage,
      });
      setTrackingResult(result);
      await mutateFilters();
      toast.success("Tracking ID is ready");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not generate tracking ID");
    } finally {
      setGeneratingTrackingCode(false);
    }
  }

  async function handleCopyTrackingMessage() {
    if (!trackingResult) return;
    try {
      await navigator.clipboard.writeText(trackingResult.prefilled_message);
      setCopiedTrackingMessage(true);
      toast.success("Pre-filled message copied");
      window.setTimeout(() => setCopiedTrackingMessage(false), 2_000);
    } catch {
      toast.error("Could not copy the message");
    }
  }

  const selectClass =
    "h-9 w-full cursor-pointer appearance-none rounded-xl border border-surface-mid/80 bg-white px-3 pr-8 font-body text-xs font-semibold text-on-surface shadow-sm transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200 disabled:cursor-not-allowed disabled:opacity-40";

  return (
    <div className="space-y-[18px]">
      <div
        role="group"
        aria-label="Filter ads by delivery"
        className={cn("grid grid-cols-1 gap-3.5 sm:grid-cols-2", deliveryCards.length > 4 ? "xl:grid-cols-5" : "xl:grid-cols-4")}
      >
        {deliveryCards.map((card) => (
          <SummaryCard
            key={card.key || "all"}
            selected={deliveryStatus === card.key}
            onSelect={() => setDeliveryStatus(card.key)}
            icon={card.icon}
            tint={card.tint}
            label={card.label}
            badge={isLoading ? "—" : `${card.count} ${card.count === 1 ? "ad" : "ads"}`}
            value={isLoading ? "—" : count(card.totals.messages)}
            caption="messages sent"
            stats={[
              { label: "Clicks", value: isLoading ? "—" : count(card.totals.inline_link_clicks) },
              { label: "Rate", value: isLoading ? "—" : percent(card.totals.conversation_rate) },
              { label: "Spent", value: isLoading ? "—" : money(card.totals.spend) },
            ]}
          />
        ))}
      </div>

      <section aria-label="Messaging ads" className="rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
        <div className="flex flex-wrap items-center gap-2 border-b border-[#eef2f6] p-3.5 xl:flex-nowrap">
          <LevelSwitch
            level={level}
            onLevel={setLevel}
            filters={{
              campaign: {
                options: (filters?.campaigns ?? []).map((campaign) => ({ id: campaign.id, name: campaign.name, hint: adsIn("campaign_id", campaign.id) })),
                value: campaignId,
                onChange: (id) => { setCampaignId(id); setAdsetId(""); setCreativeId(""); },
              },
              adset: {
                options: adsetOptions.map((adset) => ({ id: adset.id, name: adset.name, hint: adsIn("adset_id", adset.id) })),
                value: adsetId,
                onChange: (id) => { setAdsetId(id); setCreativeId(""); },
              },
              ad: {
                options: creativeOptions.map((creative) => ({ id: creative.id, name: creative.name })),
                value: creativeId,
                onChange: setCreativeId,
              },
            }}
          />
          <label className="relative min-w-[160px] max-w-[260px] flex-1">
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
            historyNote="Messaging ads covers ads that were running when you connected, and new ones since, so months before those ads show nothing here. The same date applies to All ads."
          />
          {hasFilters && (
            <button type="button" onClick={clearFilters}
              className="shrink-0 px-1 font-label text-xs font-bold text-primary-700 hover:text-primary-900">
              Clear
            </button>
          )}

          <span className="hidden flex-1 xl:block" />

          <button type="button" onClick={() => mutate()} disabled={isValidating} aria-label="Refresh" title="Refresh"
            className={cn(TOOLBAR_BUTTON, "w-9 px-0")}>
            <RefreshCw size={14} className={isValidating ? "animate-spin" : ""} />
          </button>
          <button type="button" onClick={handleSyncNow} disabled={syncing || !canManage}
            title={canManage ? "Pull the latest messaging ad performance from Meta" : "Needs Meta Ads write access"}
            className="flex h-9 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-xl border border-amber-200 bg-amber-50 px-3 font-label text-xs font-bold text-amber-800 shadow-sm transition-colors hover:bg-amber-100 disabled:opacity-40">
            <Zap size={13} className={syncing ? "animate-pulse" : ""} /> {syncing ? "Syncing…" : "Sync now"}
          </button>
          <div className="relative shrink-0">
            <button type="button" onClick={() => setShowColumns((visible) => !visible)}
              aria-expanded={showColumns} aria-haspopup="dialog" className={TOOLBAR_BUTTON}>
              <Columns3 size={13} /> Columns
              <span className="rounded-full bg-[#f1f5f9] px-1.5 py-0.5 text-[10px] text-[#475569]">{selectedMetrics.length}</span>
            </button>
            {showColumns && (
              <div role="dialog" aria-label="Customize ad performance columns"
                className="absolute right-0 top-11 z-30 flex max-h-[26rem] w-[320px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-[#e2e8f0] bg-white p-3 shadow-xl">
                <div className="mb-2 flex items-center justify-between border-b border-[#eee9e1] px-1 pb-2">
                  <div className="flex items-center gap-2">
                    <SlidersHorizontal size={13} className="text-primary-600" />
                    <span className="font-label text-xs font-bold text-[#13284A]">Customize metrics</span>
                  </div>
                  <button type="button" onClick={() => setVisibleMetrics(new Set(DEFAULT_METRICS))}
                    className="flex items-center gap-1 font-label text-[10px] font-bold text-primary-600 hover:text-primary-800">
                    <RotateCcw size={10} /> Reset
                  </button>
                </div>
                <div className="min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain pr-1">
                  {METRIC_GROUPS.map((group) => (
                    <div key={group.title} className="space-y-1">
                      <p className="px-2 pt-2 font-label text-[10px] font-bold uppercase tracking-wide text-stone-400">{group.title}</p>
                      {group.metrics.map((metric) => (
                        <button
                          key={metric.key}
                          type="button"
                          role="checkbox"
                          aria-checked={visibleMetrics.has(metric.key)}
                          onClick={() => toggleMetric(metric.key)}
                          className="flex w-full items-start gap-2 rounded-xl px-2 py-2 text-left hover:bg-stone-50"
                        >
                          <TickMark checked={visibleMetrics.has(metric.key)} size="sm" className="mt-0.5" />
                          <span>
                            <span className="block font-label text-[11px] font-bold text-stone-700">{metric.label}</span>
                            <span className="block font-body text-[10px] leading-4 text-stone-400">{metric.help}</span>
                          </span>
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
          <MoreMenu
            items={[
              {
                label: "Generate ID",
                icon: KeyRound,
                onClick: openTrackingModal,
                disabled: !canManage || whatsappCreatives.length === 0,
                title: canManage ? "Generate a fallback ID for a Meta ad's pre-filled WhatsApp message" : "Needs Meta Ads write access",
              },
              {
                label: "Manage ads",
                icon: SlidersHorizontal,
                onClick: () => setShowManage(true),
                disabled: !canManage,
                title: canManage ? "Switch individual ads on or off in this report" : "Needs Meta Ads write access",
              },
            ]}
          />
          <button type="button" onClick={handleExport} disabled={exporting || rows.length === 0}
            className="flex h-9 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-xl bg-primary px-3.5 font-label text-xs font-bold text-white shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-40">
            <Download size={13} /> {exporting ? "Exporting…" : "Export"}
          </button>
        </div>

        <div role="status" className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-[#eef2f6] bg-[#fbfcfd] px-4 py-2.5 font-body text-[11px] text-[#64748b]">
          <span className="font-bold text-[#0A1528]">{showingLabel}</span>
          {showSyncNote && syncStart?.start_date && (
            <>
              <span aria-hidden="true">·</span>
              <span>Numbers start {formatDay(syncStart.start_date)}, the history date set for this account</span>
            </>
          )}
          {syncStart?.last_synced_at && (
            <>
              <span aria-hidden="true">·</span>
              <span>Last synced {syncedAt(syncStart.last_synced_at)}</span>
            </>
          )}
          {(totals.reach_estimated || tableRows.some((item) => item.row.reach_estimated)) && (
            <>
              <span aria-hidden="true">·</span>
              <span className="text-amber-800">Reach marked ≈ is an estimate: Meta&apos;s exact figure wasn&apos;t available, so it may count someone twice. Refresh to try again.</span>
            </>
          )}
        </div>

        <div className="overflow-hidden rounded-b-2xl">
          {isLoading ? (
            <AiraLoader inline className="min-h-[300px]" />
          ) : allRows.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-4 py-20 text-center">
              <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-50">
                <Megaphone size={24} className="text-primary-400" />
              </div>
              <h3 className="mb-1 text-base font-bold text-[#1e293b]">No messaging ad data for this account</h3>
              <p className="max-w-md text-sm leading-relaxed text-[#94a3b8]">
                Validate the Meta Ads card in Settings, then run Sync now. Ads from previously connected accounts stay hidden.
              </p>
            </div>
          ) : tableRows.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-4 py-16 text-center">
              <h3 className="mb-1 text-sm font-bold text-[#1e293b]">No ads match</h3>
              <p className="max-w-md text-xs leading-relaxed text-[#94a3b8]">Pick another card above, or clear the search and filters.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1080px]">
                <thead>
                  <tr className="border-b border-[#eef2f6]">
                    <th className="sticky left-0 z-10 min-w-[280px] bg-white px-4 py-3 text-left font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">
                      {LEVEL_HEADINGS[level]}
                    </th>
                    {selectedMetrics.map((metric) => (
                      <th key={metric.key} title={metric.help}
                        className={cn(
                          "whitespace-nowrap px-4 py-3 font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted",
                          TEXT_METRICS.has(metric.key) ? "text-left" : "text-right",
                        )}>
                        {metric.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#f1f5f9]">
                  {tableRows.map((item) => {
                    const { row } = item;
                    // Ads removed in Ads Manager stay in the table -- their spend is
                    // real and still counts toward the totals -- but recede visually.
                    const removed = item.level === "ad" && isRemoved(row.delivery_status);
                    return (
                      <tr
                        key={item.key}
                        onClick={() => openRow(item)}
                        title={item.level === "ad" ? "See where this ad works best" : `Show this ${item.level === "campaign" ? "campaign's ad sets" : "ad set's ads"}`}
                        className={cn(
                          "group cursor-pointer transition-colors hover:bg-[#f8fafc]",
                          removed && "opacity-55 hover:opacity-100",
                        )}
                      >
                        <td className="sticky left-0 z-10 bg-white px-4 py-3 group-hover:bg-[#f8fafc]">
                          <div className="flex items-center gap-2">
                            <span className={cn(
                              "min-w-0 truncate font-label text-[13px] font-bold text-[#0A1528] group-hover:text-primary-700",
                              removed && "line-through decoration-stone-400",
                            )} title={item.title}>
                              {item.title}
                            </span>
                            {item.level === "ad" && <ChannelMarks channels={row.messaging_channels} multiDestination={row.is_multi_destination} />}
                            {item.level !== "ad" && <ChevronRight size={14} className="shrink-0 text-[#cbd5e1] group-hover:text-primary-600" />}
                          </div>
                          <div className="mt-0.5 truncate font-body text-[11px] text-[#94a3b8]" title={item.subtitle}>{item.subtitle}</div>
                        </td>
                        {selectedMetrics.map((metric) => (
                          <td key={metric.key} className={cn(
                            "whitespace-nowrap px-4 py-3 text-xs tabular-nums",
                            TEXT_METRICS.has(metric.key) ? "text-left" : "text-right",
                            metric.key === "messages" && "font-bold text-on-surface",
                            metric.key === "inline_link_clicks" && "font-semibold text-primary-700",
                            metric.key === "hot" && "font-semibold text-rose-600",
                          )}>
                            {metric.key === "conversation_rate" ? (
                              <RateBar value={row.conversation_rate} />
                            ) : metric.key === "delivery_status" && item.level !== "ad" ? (
                              <StatusBadge status={row.delivery_status} />
                            ) : metricValue(metric.key, row)}
                            {metric.key === "messages" && channelSplit(row.messages_by_channel) && (
                              <span className="mt-0.5 block text-[10px] font-normal text-on-surface-muted">{channelSplit(row.messages_by_channel)}</span>
                            )}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 border-[#e2e8f0] bg-[#f8fafc] font-bold">
                    <td className="sticky left-0 z-10 bg-[#f8fafc] px-4 py-3 text-sm">
                      <TotalLabel rules={MESSAGING_TOTAL_RULES} /> <span className="ml-1.5 font-body text-[11px] font-medium text-[#64748b]">{rows.length} {rows.length === 1 ? "ad" : "ads"}</span>
                    </td>
                    {selectedMetrics.map((metric) => (
                      <td key={metric.key} className={cn(
                        "whitespace-nowrap px-4 py-3 text-xs tabular-nums",
                        TEXT_METRICS.has(metric.key) ? "text-left" : "text-right",
                      )}>
                        {metric.key === "delivery_status" || metric.key === "budget" ? "—" : metricValue(metric.key, totals)}
                        {metric.key === "messages" && channelSplit(totals.messages_by_channel) && (
                          <span className="mt-0.5 block text-[10px] font-normal text-on-surface-muted">{channelSplit(totals.messages_by_channel)}</span>
                        )}
                      </td>
                    ))}
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </div>
      </section>

      {showTrackingModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="tracking-id-title"
          className="fixed inset-0 z-dialog flex items-center justify-center bg-stone-950/40 p-4 backdrop-blur-[2px]"
          onClick={() => setShowTrackingModal(false)}
        >
          <div
            className="w-full max-w-lg rounded-3xl border border-white/60 bg-white p-5 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-4 flex items-start justify-between gap-4">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-primary-100 text-primary-700">
                  <KeyRound size={18} />
                </span>
                <div>
                  <h2 id="tracking-id-title" className="font-display text-lg font-bold text-on-surface">Generate tracking ID</h2>
                  <p className="mt-0.5 font-body text-xs leading-5 text-on-surface-muted">
                    Meta Ad ID is used first. This code is the fallback when Meta does not send it.
                  </p>
                </div>
              </div>
              <button type="button" onClick={() => setShowTrackingModal(false)}
                className="rounded-xl p-2 text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-700"
                aria-label="Close tracking ID dialog">
                <X size={16} />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label htmlFor="tracking-creative" className="mb-1.5 block font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">
                  Meta ad creative
                </label>
                <div className="relative">
                  <select
                    id="tracking-creative"
                    className={selectClass}
                    value={trackingCreativeId}
                    onChange={(event) => {
                      setTrackingCreativeId(event.target.value);
                      setTrackingResult(null);
                      setCopiedTrackingMessage(false);
                    }}
                  >
                    <option value="">Select a creative</option>
                    {whatsappCreatives.map((creative) => {
                      const campaign = creative.campaign_id ? campaignNames.get(creative.campaign_id) : null;
                      const adset = creative.adset_id ? adsetNames.get(creative.adset_id) : null;
                      const context = [campaign, adset].filter(Boolean).join(" · ");
                      return (
                        <option key={creative.id} value={creative.id}>
                          {creative.name}{context ? ` — ${context}` : ""}
                        </option>
                      );
                    })}
                  </select>
                  <ChevronDown size={13} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
                </div>
              </div>

              <div>
                <label htmlFor="tracking-message" className="mb-1.5 block font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">
                  WhatsApp pre-filled message
                </label>
                <textarea
                  id="tracking-message"
                  rows={3}
                  maxLength={500}
                  value={trackingMessage}
                  onChange={(event) => {
                    setTrackingMessage(event.target.value);
                    setTrackingResult(null);
                  }}
                  className="w-full resize-none rounded-2xl border border-surface-mid bg-white px-3 py-2.5 font-body text-sm text-on-surface outline-none transition focus:border-primary-300 focus:ring-2 focus:ring-primary-100"
                />
              </div>

              <button
                type="button"
                onClick={handleGenerateTrackingCode}
                disabled={!trackingCreativeId || !trackingMessage.trim() || generatingTrackingCode}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 font-label text-sm font-bold text-white transition hover:bg-primary/90 disabled:opacity-40"
              >
                {generatingTrackingCode ? <Loader2 size={14} className="animate-spin" /> : <KeyRound size={14} />}
                {generatingTrackingCode ? "Generating…" : "Generate ID"}
              </button>

              {trackingResult && (
                <div className="rounded-2xl border border-emerald-100 bg-emerald-50/60 p-4">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <div>
                      <p className="font-label text-[10px] font-bold uppercase tracking-wider text-emerald-700">Tracking ID</p>
                      <p className="mt-0.5 font-mono text-base font-bold text-emerald-950">[ANRIL:{trackingResult.code}]</p>
                    </div>
                    <button type="button" onClick={handleCopyTrackingMessage}
                      className="flex items-center gap-1.5 rounded-xl border border-emerald-200 bg-white px-3 py-2 font-label text-xs font-bold text-emerald-700 hover:bg-emerald-50">
                      {copiedTrackingMessage ? <Check size={13} /> : <Copy size={13} />}
                      {copiedTrackingMessage ? "Copied" : "Copy message"}
                    </button>
                  </div>
                  <pre className="whitespace-pre-wrap rounded-xl bg-white px-3 py-2.5 font-body text-xs leading-5 text-stone-700">
                    {trackingResult.prefilled_message}
                  </pre>
                  <p className="mt-2 font-body text-[10px] leading-4 text-emerald-800">
                    Paste this exact text into this ad’s WhatsApp pre-filled message in Meta Ads Manager.
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {detailRow && (
        <AdDetailPanel
          row={detailRow}
          dateFrom={dateFrom}
          dateTo={dateTo}
          onClose={() => setDetailRow(null)}
          stats={[
            { label: "Messages sent", value: count(detailRow.messages), sub: channelSplit(detailRow.messages_by_channel) },
            { label: "Hot leads", value: count(detailRow.hot), tone: "text-rose-600" },
            { label: "Cost / sent message", value: money(detailRow.cost_per_message) },
            { label: "Cost / hot lead", value: money(detailRow.cost_per_hot) },
          ]}
        />
      )}

      {showManage && canManage && (
        <div className="fixed inset-0 z-dialog">
          <div
            aria-hidden
            onClick={() => setShowManage(false)}
            className="absolute inset-0 bg-stone-950/40 backdrop-blur-[2px]"
          />
          <aside
            role="dialog"
            aria-modal="true"
            aria-labelledby="manage-ads-title"
            className="fixed inset-y-0 right-0 flex w-full max-w-md flex-col bg-white shadow-2xl"
          >
            <div className="flex items-start justify-between gap-4 border-b border-surface-mid/60 p-5">
              <div>
                <h2 id="manage-ads-title" className="font-display text-lg font-bold text-on-surface">Ads in your Anril report</h2>
                <p className="mt-1 font-body text-xs leading-5 text-on-surface-muted">
                  Switch an ad off to hide it from this report. Lead tracking keeps running, so switching it back on loses nothing.
                </p>
              </div>
              <button type="button" onClick={() => setShowManage(false)}
                className="rounded-xl p-2 text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-700"
                aria-label="Close ads panel">
                <X size={16} />
              </button>
            </div>

            <div className="px-5 pt-4">
              <div className="relative">
                <Search size={12} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
                <input
                  type="search"
                  value={manageQuery}
                  onChange={(event) => setManageQuery(event.target.value)}
                  placeholder="Search by ad or campaign"
                  aria-label="Search ads by ad or campaign name"
                  className="h-9 w-full rounded-xl border border-surface-mid bg-white pl-8 pr-3 font-body text-xs font-semibold text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200"
                />
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-6 pt-4">
              {!trackedData ? (
                <p className="py-10 text-center font-body text-xs text-stone-400">Loading ads…</p>
              ) : trackedGroups.length === 0 ? (
                <p className="py-10 text-center font-body text-xs text-stone-400">
                  {trackedData.data.length === 0 ? "No messaging ads yet. Run Sync now first." : "No ads match that search."}
                </p>
              ) : (
                trackedGroups.map(([campaign, ads]) => (
                  <section key={campaign} className="mb-5">
                    <p className="mb-2 font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">{campaign}</p>
                    <ul className="divide-y divide-surface-mid/50 overflow-hidden rounded-2xl border border-surface-mid/70">
                      {ads.map((ad) => (
                        <li key={ad.ad_creative_id} className={cn(
                          "flex items-center justify-between gap-3 px-3 py-3 transition-opacity",
                          !ad.tracked && "opacity-60",
                        )}>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="font-label text-xs font-semibold text-on-surface">{ad.creative_label}</span>
                              <ChannelMarks channels={ad.messaging_channels} multiDestination={ad.is_multi_destination} />
                            </div>
                            <p className="mt-0.5 truncate font-body text-[10px] text-on-surface-muted">
                              {ad.adset_name} · {statusLabel(ad.delivery_status)}
                            </p>
                          </div>
                          <button
                            type="button"
                            role="switch"
                            aria-checked={ad.tracked}
                            aria-label={`Show ${ad.creative_label} in the Anril report`}
                            onClick={() => toggleTracked(ad)}
                            className={cn(
                              "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary-200",
                              ad.tracked ? "bg-primary-600" : "bg-stone-300",
                            )}
                          >
                            <span className={cn(
                              "inline-block h-4 w-4 rounded-full bg-white shadow transition-transform",
                              ad.tracked ? "translate-x-[18px]" : "translate-x-0.5",
                            )} />
                          </button>
                        </li>
                      ))}
                    </ul>
                  </section>
                ))
              )}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
