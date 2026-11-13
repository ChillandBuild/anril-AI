"use client";
import { useEffect, useState } from "react";
import { api, InboundLead } from "@/lib/api";
import { useInboundLeads, useInboundCampaigns } from "@/hooks/useApi";
import {
  Download, Megaphone, Filter, X,
  Info, RefreshCw, RadioTower,
  Link2, Copy, Check,
} from "lucide-react";
import { cn, formatPhone } from "@/lib/utils";
import { SegmentBadge } from "@/components/segment-badge";
import { toast } from "sonner";
import { Select } from "@/components/ui/Select";
import { AiraLoader } from "@/components/AiraLoader";
import { MobileRecordCard, MobileRecordField, MobileRecordGrid, MobileRecordHeader } from "@/components/MobileRecord";

// ─── Constants ───────────────────────────────────────────────────────────────

const CHANNEL_CONFIG: Record<string, { label: string; color: string; bg: string; dot: string }> = {
  whatsapp: {
    label: "WhatsApp",
    color: "text-emerald-700",
    bg: "bg-emerald-50 border-emerald-200",
    dot: "bg-emerald-500",
  },
  instagram: {
    label: "Instagram",
    color: "text-pink-700",
    bg: "bg-pink-50 border-pink-200",
    dot: "bg-pink-500",
  },
  facebook: {
    label: "Facebook",
    color: "text-blue-700",
    bg: "bg-blue-50 border-blue-200",
    dot: "bg-blue-500",
  },
  meta_form: {
    label: "Instant form",
    color: "text-violet-700",
    bg: "bg-violet-50 border-violet-200",
    dot: "bg-violet-500",
  },
  telegram: {
    label: "Telegram",
    color: "text-sky-700",
    bg: "bg-sky-50 border-sky-200",
    dot: "bg-sky-500",
  },
  indiamart: {
    label: "IndiaMART",
    color: "text-amber-800",
    bg: "bg-amber-50 border-amber-200",
    dot: "bg-amber-500",
  },
  justdial: {
    label: "JustDial",
    color: "text-orange-800",
    bg: "bg-orange-50 border-orange-200",
    dot: "bg-orange-500",
  },
};

const SOURCE_OPTIONS = [
  { value: "", label: "All Channels" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "instagram", label: "Instagram" },
  { value: "facebook", label: "Facebook" },
  { value: "meta_form", label: "Instant form" },
  { value: "telegram", label: "Telegram" },
  { value: "indiamart", label: "IndiaMART" },
  { value: "justdial", label: "JustDial" },
];

const ORIGIN_OPTIONS = [
  { value: "all", label: "All" },
  { value: "organic", label: "Organic" },
  { value: "ad", label: "Ad" },
] as const;

const SEGMENT_FILTER_OPTIONS = [
  { value: "", label: "All Segments" },
  { value: "A", label: "Hot" },
  { value: "B", label: "Warm" },
  { value: "C", label: "Cold" },
  { value: "D", label: "Not Interested" },
];

// ─── Sub-components ──────────────────────────────────────────────────────────

function ChannelBadge({ source }: { source: string }) {
  const cfg = CHANNEL_CONFIG[source] ?? {
    label: source,
    color: "text-[#334155]",
    bg: "bg-[#f1f5f9] border-[#e2e8f0]",
    dot: "bg-[#94a3b8]",
  };
  return (
    <span className={cn(
      "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border",
      cfg.bg, cfg.color
    )}>
      <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", cfg.dot)} />
      {cfg.label}
    </span>
  );
}


function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center px-4">
      <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary-100 to-primary-light flex items-center justify-center mb-4 shadow-sm">
        <RadioTower size={28} className="text-primary-400" />
      </div>
      <h3 className="font-bold text-[#1e293b] text-lg mb-1">No Inbound Leads Yet</h3>
      <p className="text-sm text-[#94a3b8] max-w-sm leading-relaxed">
        Leads will appear here when users message you via WhatsApp, Instagram DM,
        Facebook Messenger, or Telegram — whether from an ad or organically.
      </p>
      <div className="mt-5 flex items-center gap-2 flex-wrap justify-center">
        {["WhatsApp", "Instagram DM", "Facebook Messenger", "Telegram"].map((ch) => (
          <span key={ch} className="px-3 py-1.5 rounded-full bg-[#f1f5f9] text-[#475569] text-xs font-medium border border-[#e2e8f0]">
            {ch}
          </span>
        ))}
      </div>
    </div>
  );
}

// Generates a tracked wa.me link for a Google Ads campaign CTA. The link carries
// a [GADS:<slug>] tag so inbound WhatsApp leads get attributed to Google.
function GoogleAdsLinkModal({ onClose }: { onClose: () => void }) {
  const [campaign, setCampaign] = useState("");
  const [gclid, setGclid] = useState("");
  const [link, setLink] = useState("");
  const [slug, setSlug] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  async function handleGenerate() {
    const name = campaign.trim();
    if (!name) {
      toast.error("Enter a campaign name first.");
      return;
    }
    setLoading(true);
    try {
      const res = await api.inboundLeads.googleLink(name, gclid.trim() || undefined);
      setLink(res.link);
      setSlug(res.campaign_slug);
      setCopied(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not generate link");
    } finally {
      setLoading(false);
    }
  }

  async function handleCopy() {
    await navigator.clipboard.writeText(link);
    setCopied(true);
    toast.success("Link copied — paste it into your Google ad");
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div
      className="fixed inset-0 z-dialog flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="card w-full max-w-md rounded-3xl p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-primary-100 flex items-center justify-center">
              <Link2 size={16} className="text-primary-700" />
            </div>
            <div>
              <h3 className="font-display font-black text-on-surface text-base leading-tight">Google Ads Link</h3>
              <p className="text-[11px] text-on-surface-muted">Track WhatsApp leads from a Google campaign</p>
            </div>
          </div>
          <button onClick={onClose} className="text-[#94a3b8] hover:text-[#1e293b] transition-colors">
            <X size={18} />
          </button>
        </div>

        <label className="block font-label text-[10px] font-bold text-on-surface-muted uppercase tracking-wider mb-1.5">
          Campaign Name
        </label>
        <input
          value={campaign}
          onChange={(e) => setCampaign(e.target.value)}
          placeholder="e.g. Summer Sale 2026"
          className="w-full px-3 py-2 bg-surface-low border border-surface-mid rounded-xl font-body text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-300 mb-3"
        />

        <label className="block font-label text-[10px] font-bold text-on-surface-muted uppercase tracking-wider mb-1.5">
          Google Click ID <span className="normal-case font-normal text-[#94a3b8]">(optional — for spend sync later)</span>
        </label>
        <input
          value={gclid}
          onChange={(e) => setGclid(e.target.value)}
          placeholder="{gclid}"
          className="w-full px-3 py-2 bg-surface-low border border-surface-mid rounded-xl font-mono text-xs text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-300 mb-4"
        />

        <button
          onClick={handleGenerate}
          disabled={loading}
          className="w-full flex items-center justify-center gap-2 px-3 py-2.5 bg-primary text-white rounded-xl font-label text-xs font-bold hover:bg-primary/90 transition-all disabled:opacity-40 shadow-sm"
        >
          <Link2 size={13} />
          <span>{loading ? "Generating…" : link ? "Regenerate" : "Generate Link"}</span>
        </button>

        {link && (
          <div className="mt-4">
            <div className="flex items-center justify-between mb-1.5">
              <span className="font-label text-[10px] font-bold text-on-surface-muted uppercase tracking-wider">Tracked Link</span>
              <span className="font-mono text-[10px] text-primary-700 bg-primary-50 px-1.5 py-0.5 rounded">[GADS:{slug}]</span>
            </div>
            <div className="flex items-stretch gap-2">
              <code className="flex-1 px-3 py-2 bg-surface-mid rounded-xl font-mono text-[11px] text-on-surface break-all leading-relaxed select-all">
                {link}
              </code>
              <button
                onClick={handleCopy}
                className="shrink-0 flex items-center justify-center px-3 rounded-xl bg-primary-600 text-white hover:bg-primary-700 transition-colors"
                title="Copy link"
              >
                {copied ? <Check size={15} /> : <Copy size={15} />}
              </button>
            </div>
            <p className="mt-3 text-[11px] text-on-surface-muted leading-relaxed">
              Paste this as the destination URL of your Google ad. Every click opens a
              pre-filled WhatsApp chat, and the reply is auto-tagged to this campaign in your dashboard.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Client UI Component ───────────────────────────────────────────────────────

interface InboundLeadsClientProps {
  fallbackInboundLeads: { data: InboundLead[]; total: number; page: number; limit: number } | null;
  fallbackCampaigns: { id: string; campaign_name: string; platform: string }[] | null;
}

export function InboundLeadsClient({
  fallbackInboundLeads,
  fallbackCampaigns,
}: InboundLeadsClientProps) {
  const [exporting, setExporting] = useState(false);
  const [showGoogleModal, setShowGoogleModal] = useState(false);
  // Filters
  const [selectedCampaign, setSelectedCampaign] = useState("");
  const [selectedSource, setSelectedSource] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [origin, setOrigin] = useState<"all" | "organic" | "ad">("all");
  const [selectedSegment, setSelectedSegment] = useState("");

  // Hook integrations
  const {
    data: inboundLeadsData,
    error: leadsError,
    mutate: mutateLeads,
    isValidating: leadsValidating,
  } = useInboundLeads(
    {
      origin: origin === "all" ? undefined : origin,
      segment: selectedSegment || undefined,
      ad_campaign_id: origin === "organic" ? undefined : (selectedCampaign || undefined),
      source: selectedSource || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      limit: 200,
    },
    true,
    fallbackInboundLeads ?? undefined,
  );

  const { data: campaignsData } = useInboundCampaigns(
    true,
    fallbackCampaigns ?? undefined,
  );

  const leads = inboundLeadsData?.data ?? [];
  const total = inboundLeadsData?.total ?? 0;
  const campaigns = campaignsData ?? [];
  const loading = !inboundLeadsData && !leadsError;

  const hasFilters = !!(selectedCampaign || selectedSource || dateFrom || dateTo || origin !== "all" || selectedSegment);
  const activeFilterCount = [
    selectedCampaign,
    selectedSource,
    dateFrom,
    dateTo,
    origin !== "all" ? origin : "",
    selectedSegment,
  ].filter(Boolean).length;
  const uniqueKeywords = new Set(leads.filter((l) => l.keyword !== "—").map((l) => l.keyword.toLowerCase().trim())).size;
  const uniqueCampaigns = new Set(leads.filter((l) => l.ad_campaign_id).map((l) => l.ad_campaign_id)).size;

  useEffect(() => {
    if (leadsError) {
      toast.error(leadsError instanceof Error ? leadsError.message : "Failed to load inbound leads");
    }
  }, [leadsError]);

  async function handleExport() {
    setExporting(true);
    try {
      await api.inboundLeads.exportCsv({
        origin: origin === "all" ? undefined : origin,
        segment: selectedSegment || undefined,
        ad_campaign_id: origin === "organic" ? undefined : (selectedCampaign || undefined),
        source: selectedSource || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      toast.success("Downloaded: inbound_leads.csv");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }

  function formatDate(iso: string) {
    try {
      return new Date(iso).toLocaleString("en-IN", {
        day: "2-digit", month: "short", year: "numeric",
        hour: "2-digit", minute: "2-digit", hour12: true,
      });
    } catch { return iso; }
  }

  return (
    <div>
      <>

      {/* ── Filter Panel ───────────────────────────────────────── */}
      <div className={cn(
        "overflow-hidden transition-all duration-300 ease-in-out",
        showFilters ? "max-h-64 opacity-100 mb-4" : "max-h-0 opacity-0 mb-0"
      )}>
        <div className="rounded-2xl border border-surface-mid/80 bg-white/95 p-3 shadow-sm">
          <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary-50 text-primary-700 ring-1 ring-primary-100">
                <Filter size={13} />
              </span>
              <div>
                <span className="block font-label text-[13px] font-bold text-on-surface">Filter Results</span>
                <span className="block font-body text-[10px] text-on-surface-muted">
                  {activeFilterCount > 0 ? `${activeFilterCount} active` : "All inbound leads"}
                </span>
              </div>
            </div>
            {hasFilters && (
              <button
                onClick={() => {
                  setSelectedCampaign("");
                  setSelectedSource("");
                  setDateFrom("");
                  setDateTo("");
                  setOrigin("all");
                  setSelectedSegment("");
                }}
                className="flex h-7 items-center gap-1 rounded-full border border-transparent px-2.5 text-[11px] font-semibold text-[#475569] transition-colors hover:border-red-100 hover:bg-red-50 hover:text-red-600"
              >
                <X size={11} /> Clear all
              </button>
            )}
          </div>
          <div className="flex flex-wrap items-end gap-2.5">
            <div className="w-full sm:w-[165px]">
              <label className="mb-1 block font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">Segment</label>
              <Select
                size="sm"
                value={selectedSegment}
                onChange={setSelectedSegment}
                aria-label="Segment"
                options={SEGMENT_FILTER_OPTIONS.map((s) => ({ value: s.value, label: s.label }))}
              />
            </div>

            <div className="min-w-[230px] flex-1">
              <label className="mb-1 block font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">Ad Campaign</label>
              <Select
                size="sm"
                value={selectedCampaign}
                onChange={setSelectedCampaign}
                disabled={origin === "organic"}
                aria-label="Ad Campaign"
                options={[
                  { value: "", label: "All Campaigns" },
                  ...campaigns.map((c) => ({ value: c.id, label: c.campaign_name })),
                ]}
              />
            </div>

            <div className="w-full sm:w-[165px]">
              <label className="mb-1 block font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">Channel</label>
              <Select
                size="sm"
                value={selectedSource}
                onChange={setSelectedSource}
                aria-label="Channel"
                options={SOURCE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
              />
            </div>

            <div className="w-[145px]">
              <label className="mb-1 block font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">From Date</label>
              <input
                type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                className="h-9 w-full rounded-xl border border-surface-mid bg-white px-3 font-body text-xs font-semibold text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200"
              />
            </div>

            <div className="w-[145px]">
              <label className="mb-1 block font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">To Date</label>
              <input
                type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                className="h-9 w-full rounded-xl border border-surface-mid bg-white px-3 font-body text-xs font-semibold text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200"
              />
            </div>
          </div>
        </div>
      </div>

      {/* ── Toolbar & Stats ─────────────────────────────────────── */}
      <div className="mb-3 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="Origin" className="grid h-9 w-[240px] grid-cols-3 gap-1 rounded-full border border-[#e2e8f0] bg-[#f8f5ef] p-1">
            {ORIGIN_OPTIONS.map((o) => (
              <button
                key={o.value}
                onClick={() => setOrigin(o.value)}
                aria-pressed={origin === o.value}
                className={`rounded-full px-2 text-xs font-bold transition ${
                  origin === o.value
                    ? "bg-white text-primary shadow-sm ring-1 ring-primary-100"
                    : "text-[#475569] hover:bg-white/60 hover:text-[#1e293b]"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
            <button
              onClick={() => setShowFilters((p) => !p)}
              className={cn(
                "flex h-9 items-center justify-center gap-2 px-3 py-2 rounded-xl font-label text-xs font-bold border transition-all shadow-sm",
                showFilters || hasFilters
                  ? "bg-primary-50 border-primary-200 text-primary-700 hover:bg-primary-100"
                  : "bg-white border-surface-mid text-on-surface hover:border-primary-300 hover:text-primary-700"
              )}
            >
              <Filter size={12} />
              <span>Filters</span>
              {activeFilterCount > 0 && (
                <span className="w-4 h-4 rounded-full bg-primary-600 text-white text-[9px] font-bold flex items-center justify-center">
                  {activeFilterCount}
                </span>
              )}
            </button>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <button
              onClick={() => mutateLeads()}
              disabled={leadsValidating}
              className="flex h-9 items-center justify-center gap-2 px-3 py-2 rounded-xl bg-white border border-[#e2e8f0] hover:bg-[#f1f5f9] text-[#0A1528] font-label text-xs font-bold transition-all disabled:opacity-40 shadow-sm"
            >
              <RefreshCw size={12} className={leadsValidating ? "animate-spin" : ""} />
              <span>Refresh</span>
            </button>
          <button
            onClick={() => setShowGoogleModal(true)}
            className="flex h-9 items-center justify-center gap-2 px-3 py-2 rounded-xl bg-primary-50 border border-primary-200 text-primary-700 hover:bg-primary-100 font-label text-xs font-bold transition-all shadow-sm"
          >
            <Link2 size={12} />
            <span>Google Ads Link</span>
          </button>
          <button
            onClick={handleExport}
            disabled={exporting || leads.length === 0}
            className="flex h-9 items-center justify-center gap-2 px-3 py-2 bg-primary text-white rounded-xl font-label text-xs font-bold hover:bg-primary/90 transition-all disabled:opacity-40 shadow-sm"
          >
            <Download size={12} />
            <span>{exporting ? "Downloading…" : "Download CSV"}</span>
          </button>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-surface-mid bg-surface-mid lg:grid-cols-4">
          {[
            { label: "total inbound", value: total, hint: "Organic + Meta Ad" },
            { label: "showing", value: leads.length, hint: "Rows in the table, up to 200" },
            { label: "unique keywords", value: uniqueKeywords, hint: "Distinct first messages shown" },
            { label: uniqueCampaigns === 1 ? "ad campaign" : "ad campaigns", value: uniqueCampaigns, hint: "Ad campaigns in the rows shown" },
          ].map((stat) => (
            <div key={stat.hint} title={stat.hint} className="flex items-baseline gap-2 bg-white px-4 py-2.5">
              <span className="font-label text-lg font-bold tabular-nums text-on-surface">{loading ? "–" : stat.value}</span>
              <span className="font-body text-xs text-on-surface-muted">{stat.label}</span>
            </div>
          ))}
        </div>
      </div>

      {showGoogleModal && <GoogleAdsLinkModal onClose={() => setShowGoogleModal(false)} />}

      {/* ── Table ──────────────────────────────────────────────── */}
      <div className="card rounded-2xl overflow-hidden !p-0">
        {loading ? (
          <AiraLoader inline className="min-h-[300px]" />
        ) : leads.length === 0 ? (
          <EmptyState />
        ) : (
          <>
            <div className="space-y-3 p-3 md:hidden">
              {leads.map((lead) => (
                <MobileRecordCard key={lead.id}>
                  <MobileRecordHeader
                    title={lead.name !== "—" ? lead.name : formatPhone(lead.phone)}
                    subtitle={lead.phone !== "—" ? formatPhone(lead.phone) : "No phone"}
                    aside={<ChannelBadge source={lead.source} />}
                  />
                  <div className="mt-3 flex flex-wrap gap-2">
                    <span className={cn(
                      "inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold",
                      lead.origin === "ad"
                        ? "border-primary-200 bg-primary-50 text-primary-700"
                        : "border-[#e2e8f0] bg-[#f1f5f9] text-[#334155]"
                    )}>
                      {lead.origin.charAt(0).toUpperCase() + lead.origin.slice(1)}
                    </span>
                    <SegmentBadge segment={lead.segment as "A" | "B" | "C" | "D"} />
                  </div>
                  <MobileRecordGrid>
                    <MobileRecordField label="Joined" value={formatDate(lead.created_at)} />
                    <MobileRecordField
                      label="Keyword"
                      className="col-span-2"
                      value={lead.keyword !== "—" ? <span className="line-clamp-2 text-xs leading-snug">&ldquo;{lead.keyword}&rdquo;</span> : "No message yet"}
                    />
                    <MobileRecordField
                      label="Campaign"
                      className="col-span-2"
                      value={<span className="line-clamp-2 text-xs leading-snug">{lead.campaign_name}</span>}
                    />
                  </MobileRecordGrid>
                </MobileRecordCard>
              ))}
            </div>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-surface-mid bg-surface-low/60">
                    {["Contact", "Channel", "Origin", "Keyword (First Message)", "Ad Campaign", "Segment", "Date & Time Joined"].map((h) => (
                      <th key={h} className="px-4 py-3 text-left font-label text-[10px] font-bold text-on-surface-muted uppercase tracking-widest whitespace-nowrap">
                        {h}
                        {h === "Origin" && (
                          <span
                            title="Ad: the lead clicked a Meta ad, so it has a campaign. Organic: the lead messaged you directly."
                            aria-label="Ad: the lead clicked a Meta ad, so it has a campaign. Organic: the lead messaged you directly."
                            className="ml-1 inline-flex cursor-help align-middle"
                          >
                            <Info size={11} />
                          </span>
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-mid/50">
                  {leads.map((lead, i) => (
                    <tr
                      key={lead.id}
                      className={cn(
                        "hover:bg-surface-low/60 transition-colors",
                        i % 2 === 1 ? "bg-surface-low/20" : ""
                      )}
                    >
                      {/* Contact */}
                      <td className="px-4 py-2.5 whitespace-nowrap">
                        <span className="font-label text-sm font-semibold text-on-surface">
                          {lead.name !== "—" ? lead.name : (
                            <span className="text-on-surface-muted italic font-normal text-xs">No name</span>
                          )}
                        </span>
                        <span className="font-body text-xs text-on-surface-muted">
                          {" · "}{lead.phone !== "—" ? formatPhone(lead.phone) : "—"}
                        </span>
                      </td>

                      {/* Channel */}
                      <td className="px-4 py-2.5 whitespace-nowrap">
                        <ChannelBadge source={lead.source} />
                      </td>

                      {/* Origin */}
                      <td className="px-4 py-2.5 whitespace-nowrap">
                        <span className={cn(
                          "inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold border",
                          lead.origin === "ad"
                            ? "bg-primary-50 border-primary-200 text-primary-700"
                            : "bg-[#f1f5f9] border-[#e2e8f0] text-[#334155]"
                        )}>
                          {lead.origin.charAt(0).toUpperCase() + lead.origin.slice(1)}
                        </span>
                      </td>

                      {/* Keyword */}
                      <td className="px-4 py-2.5 max-w-[240px]">
                        {lead.keyword !== "—" ? (
                          <span
                            title={lead.keyword}
                            className="inline-block font-body text-xs text-amber-800 bg-amber-50 border border-amber-100 px-2 py-0.5 rounded-lg max-w-full truncate"
                          >
                            &ldquo;{lead.keyword}&rdquo;
                          </span>
                        ) : (
                          <span className="text-on-surface-muted text-xs italic">no message yet</span>
                        )}
                      </td>

                      {/* Campaign */}
                      <td className="px-4 py-2.5 whitespace-nowrap">
                        {lead.campaign_name === "—" ? (
                          <span className="text-xs text-on-surface-muted">—</span>
                        ) : (
                          <div className="flex items-center gap-1.5">
                            <Megaphone size={11} className="text-primary-400 flex-shrink-0" />
                            <span
                              className="font-label text-xs font-semibold text-on-surface truncate max-w-[160px]"
                              title={lead.campaign_name}
                            >
                              {lead.campaign_name}
                            </span>
                          </div>
                        )}
                      </td>

                      {/* Segment */}
                      <td className="px-4 py-2.5 whitespace-nowrap">
                        <SegmentBadge segment={lead.segment as "A" | "B" | "C" | "D"} />
                      </td>

                      {/* Date joined */}
                      <td className="px-4 py-2.5 whitespace-nowrap">
                        <p className="font-body text-xs text-on-surface-muted">{formatDate(lead.created_at)}</p>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Table footer */}
            <div className="flex items-center justify-between border-t border-surface-mid bg-surface-low/40 px-4 py-3 md:px-5">
              <p className="font-label text-xs text-on-surface-muted">
                Showing <strong className="text-on-surface">{leads.length}</strong> of{" "}
                <strong className="text-on-surface">{total}</strong> inbound leads
                {hasFilters && " (filtered)"}
              </p>
            </div>
          </>
        )}
      </div>
      </>
    </div>
  );
}
