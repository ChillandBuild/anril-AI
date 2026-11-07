"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Ban,
  Check,
  ChevronDown,
  Columns3,
  CalendarDays,
  Copy,
  Download,
  Filter,
  KeyRound,
  Loader2,
  type LucideIcon,
  Megaphone,
  MessageCircle,
  MessageSquareOff,
  MousePointerClick,
  Percent,
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
  useSyncStart,
  useTrackedAds,
} from "@/hooks/useApi";
import { cn } from "@/lib/utils";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { TickMark } from "@/components/ui/controls";
import { ChannelMarks } from "./metaFields";
import { AdDetailPanel } from "./AdDetailPanel";

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
  { key: "meta_conversations", label: "Meta messaging contacts", defaultVisible: false, help: "People who connected by message, as counted by Meta (same number as Messaging contacts in All ads). Not the same as Messaging conversations started in All ads, which counts new chats within 7 days. For tracking comparison only" },
  { key: "conversation_rate", label: "Message rate", defaultVisible: true, help: "Anril-confirmed messages divided by chat clicks" },
  { key: "meta_conversation_rate", label: "Meta messaging contact rate", defaultVisible: false, help: "Meta messaging contacts divided by chat clicks" },
  { key: "attribution_gap", label: "Tracking difference", defaultVisible: false, help: "Anril-confirmed messages minus Meta messaging contacts" },
  { key: "clicked_no_message", label: "No message", defaultVisible: true, help: "Chat clicks not matched to a unique Anril lead for this ad" },
  { key: "no_message_rate", label: "No-message rate", defaultVisible: false, help: "No-message clicks divided by chat clicks" },
  { key: "spend", label: "Spend", defaultVisible: true, help: "Amount spent in the selected period" },
  { key: "cpc", label: "CPC", defaultVisible: true, help: "Spend divided by chat clicks" },
  { key: "cost_per_message", label: "Cost / sent message", defaultVisible: true, help: "Spend divided by Anril-confirmed messages" },
  { key: "ctr", label: "CTR", defaultVisible: false, help: "Click-through rate: chat clicks divided by impressions" },
  { key: "cpm", label: "CPM", defaultVisible: false, help: "Cost per mille: spend per 1,000 impressions" },
  { key: "hot", label: "Hot", defaultVisible: false, help: "Anril leads currently in the Hot segment" },
  { key: "hot_rate", label: "Hot lead rate", defaultVisible: false, help: "Hot leads divided by Anril-confirmed messages" },
  { key: "cost_per_hot", label: "Cost / hot lead", defaultVisible: false, help: "Spend divided by Hot leads" },
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

/** Today minus N months, clamped to the end of the target month (31 Mar - 1 month = 28/29 Feb). */
function monthsBack(months: number) {
  const today = new Date();
  const target = new Date(today.getFullYear(), today.getMonth() - months, 1);
  const lastDay = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  target.setDate(Math.min(today.getDate(), lastDay));
  return isoLocal(target);
}

/** "2026-08-24" -> "24 Aug 2026". */
function formatDay(iso: string) {
  return new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

type SyncOption = { value: string; label: string; date?: string };

/**
 * Data-from presets. A preset may never reach before the earliest tracked ad:
 * any preset dated on or before it collapses into one "Since your first ad" option
 * dated to that ad, so no two options share a date.
 */
function buildSyncOptions(earliestAd: string): SyncOption[] {
  const presets = [1, 2, 3].map((months) => ({
    date: monthsBack(months),
    label: months === 1 ? "Last 1 month" : `Last ${months} months`,
  }));
  const asOption = (preset: { date: string; label: string }): SyncOption => ({ value: preset.date, label: preset.label, date: preset.date });
  const custom: SyncOption = { value: "custom", label: "Custom date" };
  if (!earliestAd || presets.every((preset) => preset.date > earliestAd)) return [...presets.map(asOption), custom];
  return [
    ...presets.filter((preset) => preset.date > earliestAd).map(asOption),
    { value: earliestAd, label: "Since your first ad", date: earliestAd },
    custom,
  ];
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

function PerformanceKpiCard({
  label,
  value,
  description,
  icon: Icon,
  gradient,
  tone = "border-t-primary-500",
}: {
  label: string;
  value: string;
  description: string;
  icon: LucideIcon;
  gradient: string;
  tone?: string;
}) {
  return (
    <div className={cn("group flex items-center gap-4 rounded-2xl border border-[#e2e8f0]/80 bg-white p-5 shadow-sm transition-all duration-200 hover:shadow-md border-t-4", tone)}>
      <span className={cn("flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-white transition-transform group-hover:scale-110", gradient)}>
        <Icon size={19} />
      </span>
      <span className="min-w-0">
        <span className="block font-display text-2xl font-bold leading-none tabular-nums text-[#0A1528]">{value}</span>
        <span className="mt-0.5 block font-label text-xs font-medium text-[#94a3b8]">{label}</span>
        <span className="mt-1 block truncate font-body text-[9px] leading-none text-stone-400" title={description}>
          {description}
        </span>
      </span>
    </div>
  );
}

function statusLabel(status: string | null | undefined) {
  return (status || "UNKNOWN").replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());
}

/** Meta statuses meaning the ad no longer exists in Ads Manager, as opposed to
 * merely not delivering. Rows in these states are kept for their spend history
 * but rendered as struck-through and dimmed. */
const REMOVED_STATUSES = new Set(["DELETED", "ARCHIVED"]);

function isRemoved(status: string | null | undefined) {
  return REMOVED_STATUSES.has((status || "").toUpperCase());
}

/** Mirrors DELIVERY_GROUPS in backend/app/services/ad_performance.py -- the CSV
 * export filters server-side with these same keys, so the download matches what
 * is on screen. Ordered as they appear in the dropdown. */
const DELIVERY_FILTERS: { key: string; label: string; statuses: Set<string> }[] = [
  { key: "active", label: "Active", statuses: new Set(["ACTIVE"]) },
  { key: "paused", label: "Paused", statuses: new Set(["PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED"]) },
  { key: "archived", label: "Archived", statuses: new Set(["ARCHIVED"]) },
  { key: "deleted", label: "Deleted", statuses: new Set(["DELETED"]) },
  { key: "issues", label: "Needs attention", statuses: new Set(["DISAPPROVED", "WITH_ISSUES", "PENDING_REVIEW", "PENDING_BILLING_INFO"]) },
];

function matchesDelivery(row: AdPerformanceRow, key: string) {
  const group = DELIVERY_FILTERS.find((filter) => filter.key === key);
  return group ? group.statuses.has((row.delivery_status || "").toUpperCase()) : true;
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
    cost_per_hot: total.hot ? total.spend / total.hot : null,
  };
}

function metricValue(metric: MetricKey, row: AdPerformanceRow) {
  switch (metric) {
    case "delivery_status":
      return <StatusBadge status={row.delivery_status} lastDelivery={row.last_delivery_date} />;
    case "budget":
      return budgetLabel(row);
    case "impressions":
    case "reach":
    case "inline_link_clicks":
    case "clicks_all":
    case "messages":
    case "meta_conversations":
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
  const [showFilters, setShowFilters] = useState(false);
  const [showColumns, setShowColumns] = useState(false);
  const [showTrackingModal, setShowTrackingModal] = useState(false);
  const [trackingCreativeId, setTrackingCreativeId] = useState("");
  const [trackingMessage, setTrackingMessage] = useState("Hi, I'm interested in this service.");
  const [trackingResult, setTrackingResult] = useState<AdTrackingCodeResponse | null>(null);
  const [generatingTrackingCode, setGeneratingTrackingCode] = useState(false);
  const [copiedTrackingMessage, setCopiedTrackingMessage] = useState(false);
  const [showReportingNotice, setShowReportingNotice] = useState(true);
  const [deliveryStatus, setDeliveryStatus] = useState("");
  const [visibleMetrics, setVisibleMetrics] = useState<Set<MetricKey>>(() => new Set(DEFAULT_METRICS));
  const [showManage, setShowManage] = useState(false);
  const [detailRow, setDetailRow] = useState<AdPerformanceRow | null>(null);
  const [manageQuery, setManageQuery] = useState("");
  const [showSyncStart, setShowSyncStart] = useState(false);
  const [syncChoice, setSyncChoice] = useState("custom");
  const [customSyncDate, setCustomSyncDate] = useState("");
  const [savingSyncStart, setSavingSyncStart] = useState(false);
  const syncRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => setShowReportingNotice(false), 10_000);
    return () => window.clearTimeout(timeoutId);
  }, []);

  useEffect(() => {
    if (!showManage) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setShowManage(false);
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [showManage]);

  useEffect(() => {
    if (!showSyncStart) return;
    function handlePointerDown(event: MouseEvent) {
      if (syncRef.current && !syncRef.current.contains(event.target as Node)) setShowSyncStart(false);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setShowSyncStart(false);
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [showSyncStart]);

  const { data: filters, mutate: mutateFilters } = useAdFilters();
  const { data: syncStart, mutate: mutateSyncStart } = useSyncStart();
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
  const rows = useMemo(
    () => (deliveryStatus ? allRows.filter((row) => matchesDelivery(row, deliveryStatus)) : allRows),
    [allRows, deliveryStatus],
  );
  // Cards, Total and rows all describe the same set: whatever the Delivery
  // filter currently selects. Cards that quietly excluded archived ads while the
  // filter read "All statuses" contradicted the control right next to them --
  // to see live-only numbers, pick Active in the Delivery filter.
  const totals = useMemo(() => aggregateRows(rows), [rows]);
  const selectedMetrics = useMemo(
    () => METRICS.filter((metric) => visibleMetrics.has(metric.key)),
    [visibleMetrics],
  );

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
  const activeDimensionFilters =
    Number(Boolean(campaignId)) + Number(Boolean(adsetId)) + Number(Boolean(creativeId)) + Number(Boolean(deliveryStatus));
  const dataFromLabel = syncStart?.start_date ? formatDay(syncStart.start_date) : null;
  const showSyncNote = Boolean(syncStart?.start_date) && dateFrom < (syncStart?.start_date ?? "").slice(0, 10);
  const today = localDate();
  const historyFloor = syncStart ? localDate(syncStart.max_history_days) : "";
  const earliestAd = (syncStart?.earliest_ad_start ?? "").slice(0, 10);
  // Custom date may go no earlier than the later of: the earliest ad's start, or the history limit.
  const customMin = earliestAd && earliestAd > historyFloor ? earliestAd : historyFloor;
  const syncOptions = buildSyncOptions(earliestAd);
  const chosenSyncDate = syncChoice === "custom" ? customSyncDate : syncChoice;

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
    setDateFrom(localDate(29));
    setDateTo(localDate());
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

  function openSyncStart() {
    const current = (syncStart?.start_date ?? "").slice(0, 10);
    const match = syncOptions.find((option) => option.date === current);
    setSyncChoice(match ? match.value : "custom");
    setCustomSyncDate(current || customMin || today);
    setShowSyncStart((visible) => !visible);
  }

  async function saveSyncStart() {
    if (!chosenSyncDate) return;
    setSavingSyncStart(true);
    try {
      await api.inboundLeads.setSyncStart(chosenSyncDate);
      toast.success(`Pulling ad data from ${formatDay(chosenSyncDate)} — this can take a few minutes.`);
      setShowSyncStart(false);
      await Promise.all([mutateSyncStart(), mutate()]);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save the history date");
    } finally {
      setSavingSyncStart(false);
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
    <div>
      <div className="mb-5 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
              <PerformanceKpiCard
                label="Chat Clicks"
                value={isLoading ? "—" : count(totals.inline_link_clicks)}
                description="Clicked the ad and opened a chat"
                icon={MousePointerClick}
                gradient="bg-gradient-to-br from-primary-500 to-primary"
                tone="border-t-primary-500"
              />
              <PerformanceKpiCard
                label="Messages Sent"
                value={isLoading ? "—" : count(totals.messages)}
                description="Clicked and sent a message"
                icon={MessageCircle}
                gradient="bg-gradient-to-br from-blue-500 to-cyan-600"
                tone="border-t-sky-400"
              />
              <PerformanceKpiCard
                label="No Message"
                value={isLoading ? "—" : count(totals.clicked_no_message)}
                description="Clicked but did not send the message"
                icon={MessageSquareOff}
                gradient="bg-gradient-to-br from-amber-500 to-orange-500"
                tone="border-t-amber-400"
              />
              <PerformanceKpiCard
                label="Message Rate"
                value={isLoading ? "—" : percent(totals.conversation_rate)}
                description="Messages sent out of chat clicks"
                icon={Percent}
                gradient="bg-gradient-to-br from-emerald-500 to-teal-600"
                tone="border-t-emerald-400"
              />
        </div>

        <div className="grid h-fit grid-cols-2 gap-2 self-start p-1">
          <button type="button" onClick={() => mutate()} disabled={isValidating}
            className="flex h-9 items-center justify-center gap-2 rounded-xl border border-surface-mid bg-white px-3 py-2 font-label text-xs font-bold text-on-surface shadow-sm transition-all hover:border-primary-300 hover:text-primary-700 disabled:opacity-40">
            <RefreshCw size={12} className={isValidating ? "animate-spin" : ""} /> Refresh
          </button>
          <button type="button" onClick={handleSyncNow} disabled={syncing || !canManage}
            title={canManage ? "Pull the latest messaging ad performance from Meta" : "Needs Meta Ads write access"}
            className="flex h-9 items-center justify-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 font-label text-xs font-bold text-amber-700 shadow-sm transition-all hover:bg-amber-100 disabled:opacity-40">
            <Zap size={12} className={syncing ? "animate-pulse" : ""} /> {syncing ? "Syncing…" : "Sync now"}
          </button>

          <button type="button" onClick={() => setShowFilters((visible) => !visible)}
            aria-expanded={showFilters} aria-controls="ad-performance-filters"
            className={cn(
              "flex h-9 items-center justify-center gap-2 rounded-xl border px-3 py-2 font-label text-xs font-bold shadow-sm transition-all",
              showFilters || activeDimensionFilters > 0
                ? "border-primary-200 bg-primary-50 text-primary-700"
                : "border-surface-mid bg-white text-on-surface hover:border-primary-300 hover:text-primary-700",
            )}>
            <Filter size={12} /> Filters
            {activeDimensionFilters > 0 && (
              <span className="flex h-4 w-4 items-center justify-center rounded-full bg-primary-600 text-[9px] text-white">
                {activeDimensionFilters}
              </span>
            )}
          </button>

          <div className="relative">
            <button type="button" onClick={() => setShowColumns((visible) => !visible)}
              aria-expanded={showColumns} aria-haspopup="dialog"
              className="flex h-9 w-full items-center justify-center gap-2 rounded-xl border border-primary-200 bg-white px-3 py-2 font-label text-xs font-bold text-primary-700 shadow-sm transition-all hover:bg-primary-50">
              <Columns3 size={13} /> Columns
              <span className="rounded-full bg-primary-100 px-1.5 py-0.5 text-[9px]">{selectedMetrics.length}</span>
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
                  {METRICS.map((metric) => (
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
              </div>
            )}
          </div>

          <button type="button" onClick={openTrackingModal} disabled={!canManage || whatsappCreatives.length === 0}
            title={canManage ? "Generate a fallback ID for a Meta ad's pre-filled WhatsApp message" : "Needs Meta Ads write access"}
            className="flex h-9 items-center justify-center gap-2 rounded-xl border border-primary-200 bg-primary-50 px-3 py-2 font-label text-xs font-bold text-primary-700 shadow-sm transition-all hover:bg-primary-100 disabled:opacity-40">
            <KeyRound size={12} /> Generate ID
          </button>

          <button type="button" onClick={() => setShowManage(true)} disabled={!canManage}
            title={canManage ? "Switch individual ads on or off in this report" : "Needs Meta Ads write access"}
            className="flex h-9 items-center justify-center gap-2 rounded-xl border border-surface-mid bg-white px-3 py-2 font-label text-xs font-bold text-on-surface shadow-sm transition-all hover:border-primary-300 hover:text-primary-700 disabled:opacity-40">
            <SlidersHorizontal size={12} /> Manage ads
          </button>

          <div ref={syncRef} className="relative col-span-2">
            {canManage ? (
              <button type="button" onClick={openSyncStart}
                aria-expanded={showSyncStart} aria-haspopup="dialog"
                title="Choose how far back Anril pulls ad data from Meta"
                className="flex h-9 w-full items-center justify-center gap-2 rounded-xl border border-surface-mid bg-white px-3 py-2 font-label text-xs font-bold text-on-surface shadow-sm transition-all hover:border-primary-300 hover:text-primary-700">
                <CalendarDays size={12} /> Data from: {dataFromLabel ?? "last 30 days"}
              </button>
            ) : (
              <div className="flex h-9 w-full items-center justify-center gap-2 rounded-xl border border-surface-mid bg-white px-3 py-2 font-label text-xs font-bold text-on-surface-muted shadow-sm">
                <CalendarDays size={12} /> Data from: {dataFromLabel ?? "last 30 days"}
              </div>
            )}
            {canManage && showSyncStart && (
              <div role="dialog" aria-label="How far back to pull ad data"
                className="absolute right-0 top-11 z-30 w-[300px] max-w-[calc(100vw-2rem)] rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-xl">
                <p className="font-label text-xs font-bold text-[#13284A]">How far back should Anril pull ad data?</p>
                <div role="radiogroup" aria-label="History range" className="mt-3 space-y-1">
                  {syncOptions.map((option) => {
                    const tooOld = option.date !== undefined && Boolean(historyFloor) && option.date < historyFloor;
                    return (
                      <label key={option.value}
                        className={cn(
                          "flex items-center gap-2 rounded-xl px-2 py-2 font-label text-[11px] font-bold text-stone-700 hover:bg-stone-50",
                          tooOld && "cursor-not-allowed opacity-40",
                        )}>
                        <input type="radio" name="sync-start-range" value={option.value}
                          checked={syncChoice === option.value} disabled={tooOld}
                          onChange={() => setSyncChoice(option.value)}
                          className="h-3.5 w-3.5 accent-primary-600" />
                        <span className="flex-1">{option.label}</span>
                        {option.date && <span className="font-body text-[10px] font-medium text-stone-400">from {formatDay(option.date)}</span>}
                      </label>
                    );
                  })}
                </div>
                {syncChoice === "custom" && (
                  <input type="date" aria-label="Custom start date" value={customSyncDate}
                    min={customMin || undefined} max={today}
                    onChange={(event) => setCustomSyncDate(event.target.value)}
                    className="mt-2 h-9 w-full rounded-xl border border-surface-mid bg-white px-3 font-body text-xs font-semibold text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200" />
                )}
                <p className="mt-3 font-body text-[10px] leading-4 text-stone-500">
                  Applies to ads that were running when you connected, and new ones since. Each ad starts no earlier than the day it began running.
                </p>
                {earliestAd && (
                  <p className="mt-1.5 font-body text-[10px] leading-4 text-stone-500">
                    Your earliest tracked ad started on {formatDay(earliestAd)}.
                  </p>
                )}
                <button type="button" onClick={saveSyncStart} disabled={savingSyncStart || !chosenSyncDate}
                  className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2 font-label text-xs font-bold text-white transition hover:bg-primary/90 disabled:opacity-40">
                  {savingSyncStart && <Loader2 size={13} className="animate-spin" />}
                  {savingSyncStart ? "Saving…" : "Save"}
                </button>
              </div>
            )}
          </div>

          <button type="button" onClick={handleExport} disabled={exporting || rows.length === 0}
            className="col-span-2 flex h-9 items-center justify-center gap-2 rounded-xl bg-primary px-3 py-2 font-label text-xs font-bold text-white shadow-sm transition-all hover:bg-primary/90 disabled:opacity-40">
            <Download size={12} /> {exporting ? "Downloading…" : "Download CSV"}
          </button>
        </div>
      </div>

      {showFilters && (
        <div id="ad-performance-filters" className="mb-5 overflow-hidden rounded-2xl border border-primary-100/80 bg-gradient-to-br from-primary-50/70 via-white to-primary-50/50 p-3 shadow-sm">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary-600 text-white shadow-sm shadow-primary-200">
                <Filter size={13} />
              </span>
              <div>
                <p className="font-label text-[13px] font-bold text-on-surface">Filter ad performance</p>
                <p className="font-body text-[10px] text-on-surface-muted">Set a date range, then narrow by campaign, ad set, creative, or delivery status.</p>
              </div>
            </div>
            <button type="button" onClick={clearFilters}
              className="flex h-7 items-center gap-1 rounded-full border border-primary-200 bg-white/90 px-2.5 font-label text-[11px] font-semibold text-primary-700 shadow-sm transition-colors hover:border-primary-300 hover:bg-primary-50 hover:text-primary-900">
              <X size={11} /> Clear filters
            </button>
          </div>
          <div className="grid gap-2.5 items-end grid-cols-1 sm:grid-cols-2 xl:grid-cols-6">
            <div>
              <label htmlFor="ad-performance-from" className="mb-1 block font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">From Date</label>
              <input id="ad-performance-from" type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)}
                className="h-9 w-full rounded-xl border border-surface-mid bg-white px-3 font-body text-xs font-semibold text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200" />
            </div>
            <div>
              <label htmlFor="ad-performance-to" className="mb-1 block font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">To Date</label>
              <input id="ad-performance-to" type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)}
                className="h-9 w-full rounded-xl border border-surface-mid bg-white px-3 font-body text-xs font-semibold text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200" />
            </div>
            <div>
              <label htmlFor="ad-performance-campaign" className="mb-1 block font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">Campaign</label>
              <div className="relative">
                <select id="ad-performance-campaign" className={selectClass} value={campaignId}
                  onChange={(event) => { setCampaignId(event.target.value); setAdsetId(""); setCreativeId(""); }}>
                  <option value="">All campaigns</option>
                  {(filters?.campaigns ?? []).map((campaign) => <option key={campaign.id} value={campaign.id}>{campaign.name}</option>)}
                </select>
                <ChevronDown size={13} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
              </div>
            </div>
            <div>
              <label htmlFor="ad-performance-adset" className="mb-1 block font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">Ad set</label>
              <div className="relative">
                <select id="ad-performance-adset" className={selectClass} value={adsetId}
                  onChange={(event) => { setAdsetId(event.target.value); setCreativeId(""); }}>
                  <option value="">All ad sets</option>
                  {adsetOptions.map((adset) => <option key={adset.id} value={adset.id}>{adset.name}</option>)}
                </select>
                <ChevronDown size={13} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
              </div>
            </div>
            <div>
              <label htmlFor="ad-performance-creative" className="mb-1 block font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">Creative</label>
              <div className="relative">
                <select id="ad-performance-creative" className={selectClass} value={creativeId} onChange={(event) => setCreativeId(event.target.value)}>
                  <option value="">All creatives</option>
                  {creativeOptions.map((creative) => <option key={creative.id} value={creative.id}>{creative.name}</option>)}
                </select>
                <ChevronDown size={13} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
              </div>
            </div>
            <div>
              <label htmlFor="ad-performance-delivery" className="mb-1 block font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">Delivery</label>
              <div className="relative">
                <select id="ad-performance-delivery" className={selectClass} value={deliveryStatus}
                  onChange={(event) => setDeliveryStatus(event.target.value)}>
                  <option value="">All statuses</option>
                  {/* Only statuses actually present, so the list never offers a
                      choice that would empty the table. */}
                  {DELIVERY_FILTERS.filter(
                    (filter) => allRows.some((row) => filter.statuses.has((row.delivery_status || "").toUpperCase())),
                  ).map((filter) => (
                    <option key={filter.key} value={filter.key}>{filter.label}</option>
                  ))}
                </select>
                <ChevronDown size={13} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
              </div>
            </div>
          </div>
        </div>
      )}

      {showReportingNotice && (
        <div role="status" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-primary-100 bg-primary-50/60 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary-100 text-primary-600">
              <Megaphone size={15} />
            </span>
            <div>
              <p className="font-label text-xs font-bold text-primary-950">Messaging ads reporting</p>
              <p className="font-body text-[11px] text-primary-700">
                Current account {filters?.account_id ?? "not connected"} · Ads that open WhatsApp, Instagram or Messenger chats. Messages sent counts chats on all three apps.
              </p>
              <p className="font-body text-[10px] text-primary-600">
                Website, form and app ads are on the All ads tab. The Leads tab still includes WhatsApp, Instagram, Facebook, and Telegram leads.
              </p>
            </div>
          </div>
          <span className="rounded-full border border-primary-200 bg-white px-3 py-1 font-label text-[10px] font-bold text-primary-700">
            {dateFrom} — {dateTo}
          </span>
        </div>
      )}

      {showSyncNote && syncStart?.start_date && (
        <p role="status" className="mb-3 font-body text-[11px] text-slate-500">
          Showing data from {formatDay(syncStart.start_date)} — the history date set for this account.
        </p>
      )}

      <div className="card overflow-hidden rounded-2xl">
        {isLoading ? (
          <AiraLoader inline className="min-h-[300px]" />
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center justify-center px-4 py-20 text-center">
            <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-50">
              <Megaphone size={24} className="text-primary-400" />
            </div>
            <h3 className="mb-1 text-base font-bold text-[#1e293b]">No messaging ad data for this account</h3>
            <p className="max-w-md text-sm leading-relaxed text-[#94a3b8]">
              Validate the Meta Ads card in Settings, then run Sync now. Ads from previously connected accounts stay hidden.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1180px]">
              <thead>
                <tr className="border-b border-surface-mid bg-surface-low/60">
                  {["Campaign", "Ad set", "Creative"].map((heading) => (
                    <th key={heading} className="whitespace-nowrap px-4 py-3 text-center font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">{heading}</th>
                  ))}
                  {selectedMetrics.map((metric) => (
                    <th key={metric.key} title={metric.help}
                      className="whitespace-nowrap px-4 py-3 text-center font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">
                      {metric.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-mid/50">
                {rows.map((row) => {
                  // Ads removed in Ads Manager stay in the table -- their spend is
                  // real and still counts toward the totals -- but recede visually.
                  // Hovering restores full opacity so the numbers stay readable.
                  const removed = isRemoved(row.delivery_status);
                  return (
                    <tr
                      key={row.ad_creative_id}
                      onClick={() => setDetailRow(row)}
                      className={cn(
                        "cursor-pointer transition-all hover:bg-surface-low/60",
                        removed && "bg-surface-low/25 opacity-55 hover:opacity-100",
                      )}
                    >
                      <td className="px-4 py-3 text-center font-label text-xs font-semibold text-on-surface">
                        {row.campaign_name}
                        {row.campaign_created_at && (
                          <span className="mt-0.5 block whitespace-nowrap text-[10px] font-normal text-on-surface-muted">
                            Created {createdOn(row.campaign_created_at)}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-center text-xs text-on-surface-muted">{row.adset_name ?? "—"}</td>
                      <td className="min-w-[264px] px-4 py-3 text-center font-label text-xs font-semibold text-on-surface">
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); setDetailRow(row); }}
                          title="See where this ad works best"
                          className={cn(
                            "block rounded text-center hover:text-primary-700 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-200",
                            removed && "line-through decoration-stone-400",
                          )}
                        >
                          {row.creative_label}
                        </button>
                        <div className="mt-1 flex justify-center">
                          <ChannelMarks channels={row.messaging_channels} multiDestination={row.is_multi_destination} />
                        </div>
                      </td>
                      {selectedMetrics.map((metric) => (
                        <td key={metric.key} className={cn(
                          "whitespace-nowrap px-4 py-3 text-center text-xs tabular-nums",
                          metric.key === "messages" && "font-bold text-on-surface",
                          metric.key === "inline_link_clicks" && "font-semibold text-primary-700",
                          metric.key === "hot" && "font-semibold text-rose-600",
                        )}>
                          {metricValue(metric.key, row)}
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
                <tr className="border-t-2 border-surface-mid bg-surface-low/50 font-bold">
                  <td className="px-4 py-3 text-center text-sm">Total</td>
                  <td className="text-center" />
                  <td className="text-center" />
                  {selectedMetrics.map((metric) => (
                    <td key={metric.key} className="whitespace-nowrap px-4 py-3 text-center text-xs tabular-nums">
                      {metric.key === "delivery_status" ? "—" : metricValue(metric.key, totals)}
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
