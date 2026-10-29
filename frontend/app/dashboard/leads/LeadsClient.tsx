"use client";
import { toast } from "sonner";
import { useEffect, useRef, useState } from "react";
import { api, Lead, Caller, SegmentTemplate, BroadcastHistoryItem, WabaTemplate, getAuthHeaders, API_URL } from "@/lib/api";
import { Download, Pencil, X, RefreshCw, MessageSquare, UserPlus, ArrowLeftRight, Search, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { timeAgo, formatPhone } from "@/lib/utils";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { AssignButton } from "./AssignButton";
import ReengagementBuilder from "./ReengagementBuilder";
import { useLeadsPage } from "@/hooks/useApi";
import { useSearchParams, useRouter } from "next/navigation";
import { MobileRecordCard, MobileRecordField, MobileRecordGrid, MobileRecordHeader } from "@/components/MobileRecord";
import { SegmentBadge } from "@/components/segment-badge";
import { FilterMenu, FilterMenuOption } from "./FilterMenu";
import { SegmentBroadcastModal } from "./SegmentBroadcastModal";
import { ComposeModal } from "./ComposeModal";
import { CheckTick } from "@/components/ui/controls";
import { SendMessageModal } from "./SendMessageModal";
import { SendTemplateModal } from "./SendTemplateModal";

function NameCell({ lead, onUpdate, compact }: { lead: Lead; onUpdate: (l: Lead) => void; compact?: boolean }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(lead.name || "");

  async function save() {
    setEditing(false);
    const trimmed = value.trim();
    if (!trimmed || trimmed === (lead.name || "")) return;
    try {
      const updated = await api.leads.update(lead.id, { name: trimmed });
      onUpdate(updated);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Rename failed");
      setValue(lead.name || "");
    }
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") save();
          if (e.key === "Escape") {
            setValue(lead.name || "");
            setEditing(false);
          }
        }}
        className="font-body text-sm text-on-surface bg-surface-low px-2 py-0.5 rounded border border-primary focus:outline-none focus:ring-1 focus:ring-primary w-40"
      />
    );
  }

  if (compact && !lead.name) {
    return (
      <button
        onClick={(e) => {
          e.stopPropagation();
          setValue("");
          setEditing(true);
        }}
        className="text-primary text-xs font-semibold hover:opacity-70"
      >
        + Add name
      </button>
    );
  }

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        setValue(lead.name || "");
        setEditing(true);
      }}
      className="group flex items-center gap-1.5 font-body text-sm text-on-surface"
      title="Click to rename"
    >
      <span className={lead.name ? "" : "text-on-surface-muted italic"}>
        {lead.name || "Add name"}
      </span>
      <Pencil size={11} className="opacity-0 group-hover:opacity-60 text-on-surface-muted" />
    </button>
  );
}

const SEGMENTS = ["A", "B", "C", "D"] as const;

const SEGMENT_LABELS: Record<string, string> = {
  A: "Hot",
  B: "Warm",
  C: "Cold",
  D: "Not interested",
};

const SEGMENT_EMOJIS: Record<string, string> = {
  A: "🔥",
  B: "",
  C: "",
  D: "",
};

const SEGMENT_COLORS: Record<string, { text: string; edge: string }> = {
  A: { text: "text-orange-600", edge: "bg-orange-500" },
  B: { text: "text-[#0A1528]", edge: "bg-amber-400" },
  C: { text: "text-[#0A1528]", edge: "bg-blue-600" },
  D: { text: "text-[#0A1528]", edge: "bg-slate-400" },
};

// Matches the FilterMenu buttons beside it. Fixed width fits "All campaigns"/"All broadcasts"; a long
// name is cut short here but shown in full in the list. No right padding: Chrome's arrow sits inside it.
const PICKER_CLASS =
  "h-[30px] w-[132px] shrink-0 truncate rounded-lg border border-[#e2e8f0] bg-white pl-2 pr-1 text-xs font-bold text-[#0A1528] hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-primary/20";

const SOURCE_FILTERS: FilterMenuOption[] = [
  { value: "ALL", label: "All" },
  { value: "INBOUND", label: "Inbound" },
  { value: "ORGANIC", label: "Organic" },
  { value: "META_ADS", label: "Meta Ads" },
  { value: "BROADCAST", label: "Broadcast" },
];

const SOURCE_NAMES: Record<string, string> = {
  whatsapp: "WhatsApp", instagram: "Instagram", facebook: "Facebook", telegram: "Telegram",
  indiamart: "IndiaMART", justdial: "Justdial",
};

function sourceLabel(source: string): string {
  return SOURCE_NAMES[source] ?? source.charAt(0).toUpperCase() + source.slice(1);
}

function getInitialColor(leadId: string): string {
  const colors = ["#e0457b", "#7c5cdb", "#e07a3f", "#2f9e6e", "#4a90d9", "#d4a23a"];
  let hash = 0;
  for (let i = 0; i < leadId.length; i++) {
    hash = ((hash << 5) - hash) + leadId.charCodeAt(i);
    hash = hash & hash;
  }
  return colors[Math.abs(hash) % colors.length];
}

export function LeadsClient({ initialTab = "A" }: { fallbackLeads?: Lead[] | null; initialTab?: typeof SEGMENTS[number] }) {
  const { role, permissions } = useAuthRole();
  const canManageLeads = role === "owner" || permissions.includes("leads.manage");
  // Sending a chat message needs the same right as replying in Conversations.
  const canReply = role === "owner" || permissions.includes("conversations.reply");
  const [tab, setTab] = useState<typeof SEGMENTS[number]>(initialTab);
  const [templates, setTemplates] = useState<Record<string, SegmentTemplate>>({});
  const [composing, setComposing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [callers, setCallers] = useState<Caller[]>([]);

  // Filtering states
  const [sourceFilter, setSourceFilter] = useState("ALL");
  const [selectedCampaignId, setSelectedCampaignId] = useState("");
  const [selectedBroadcastId, setSelectedBroadcastId] = useState("");
  const [campaigns, setCampaigns] = useState<{ id: string; campaign_name: string; platform: string; created_at?: string; meta_created_at?: string | null }[]>([]);
  const [broadcastHistory, setBroadcastHistory] = useState<BroadcastHistoryItem[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 25;
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [assigned, setAssigned] = useState<string | undefined>();
  const [replyWindow, setReplyWindow] = useState<"open" | "closed" | undefined>();
  const [sort, setSort] = useState<"newest" | "oldest" | "urgent" | undefined>();
  const [now, setNow] = useState(new Date());
  const [tipsDismissed, setTipsDismissed] = useState(false);
  const [broadcastModalOpen, setBroadcastModalOpen] = useState(false);

  // Modal states
  const [sendMessageLeads, setSendMessageLeads] = useState<Lead[]>([]);
  const [sendMessageModalOpen, setSendMessageModalOpen] = useState(false);
  const [sendTemplateLeadId, setSendTemplateLeadId] = useState<string | null>(null);

  // Assign popover state
  const [assignPopoverOpen, setAssignPopoverOpen] = useState(false);
  const assignPopoverRef = useRef<HTMLDivElement>(null);

  // Change segment popover state
  const [changeSegmentPopoverOpen, setChangeSegmentPopoverOpen] = useState(false);
  const changeSegmentPopoverRef = useRef<HTMLDivElement>(null);

  // Checkbox ref for indeterminate state

  // Re-engagement states
  const [wabaTemplates, setWabaTemplates] = useState<WabaTemplate[]>([]);
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawTab = searchParams.get("tab");
  const pageView: "leads" | "reengagement" = rawTab === "reengagement" ? "reengagement" : "leads";
  const dateFrom = searchParams.get("date_from") ?? undefined;
  const dateTo = searchParams.get("date_to") ?? undefined;
  const requestedSegment = searchParams.get("segment");
  const composeParam = searchParams.get("compose");
  const broadcastParam = searchParams.get("broadcast");
  const [reengageTrigger, setReengageTrigger] = useState<"broadcast" | "inbound">("inbound");

  useEffect(() => {
    if ((SEGMENTS as readonly string[]).includes(requestedSegment ?? "")) {
      setTab(requestedSegment as typeof SEGMENTS[number]);
    }
  }, [requestedSegment]);

  // Read tips dismiss state from localStorage
  useEffect(() => {
    try {
      const dismissed = localStorage.getItem("segments.replyTipDismissed");
      setTipsDismissed(dismissed === "1");
    } catch {
      // ignore
    }
  }, []);

  // Update current time every 60s for reply window countdown
  useEffect(() => {
    const interval = setInterval(() => {
      setNow(new Date());
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  const setPageView = (val: "leads" | "reengagement") => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", val);
    router.replace(`/dashboard/leads?${params.toString()}`, { scroll: false });
  };

  // Both dates in ONE url update: two back-to-back router.replace calls each start
  // from the same old url, so the second would silently drop the first date.
  const setDates = (from: string, to: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (from) params.set("date_from", from);
    else params.delete("date_from");
    if (to) params.set("date_to", to);
    else params.delete("date_to");
    router.replace(`/dashboard/leads?${params.toString()}`, { scroll: false });
  };

  const setSegment = (segment: typeof SEGMENTS[number]) => {
    setTab(segment);
    setPage(1);
    setSelectedIds(new Set());
    const params = new URLSearchParams(searchParams.toString());
    params.delete("tab");
    params.set("segment", segment);
    router.replace(`/dashboard/leads?${params.toString()}`, { scroll: false });
  };

  // Shared filters for counts and table (excludes segment, page, limit, sort)
  const sharedFilters = {
    search: search || undefined,
    source_filter: sourceFilter !== "ALL" ? sourceFilter.toLowerCase() : undefined,
    ad_campaign_id: sourceFilter === "META_ADS" && selectedCampaignId ? selectedCampaignId : undefined,
    broadcast_id: sourceFilter === "BROADCAST" && selectedBroadcastId ? selectedBroadcastId : undefined,
    date_from: dateFrom,
    date_to: dateTo,
    assigned_to: assigned,
    reply_window: replyWindow,
  };

  // SWR Hooks for page data
  const { data: pageData, mutate: mutateList, isLoading } = useLeadsPage(
    {
      segment: tab,
      page,
      limit: PAGE_SIZE,
      ...sharedFilters,
      sort,
    },
    pageView === "leads"
  );

  const leads = pageData?.data ?? [];
  const totalLeads = pageData?.total ?? 0;
  const hasFilters = !!(search || sourceFilter !== "ALL" || dateFrom || dateTo || assigned || replyWindow);

  // Hooks for segment counts - keep mutate functions to refresh them after bulk operations
  const { data: countA, mutate: mutateCountA } = useLeadsPage({ segment: "A", page: 1, limit: 1, ...sharedFilters }, pageView === "leads");
  const { data: countB, mutate: mutateCountB } = useLeadsPage({ segment: "B", page: 1, limit: 1, ...sharedFilters }, pageView === "leads");
  const { data: countC, mutate: mutateCountC } = useLeadsPage({ segment: "C", page: 1, limit: 1, ...sharedFilters }, pageView === "leads");
  const { data: countD, mutate: mutateCountD } = useLeadsPage({ segment: "D", page: 1, limit: 1, ...sharedFilters }, pageView === "leads");

  const segmentCounts = {
    A: countA?.total,
    B: countB?.total,
    C: countC?.total,
    D: countD?.total,
  };

  async function refreshLeads() {
    setRefreshing(true);
    try {
      await Promise.all([mutateList(), mutateCountA(), mutateCountB(), mutateCountC(), mutateCountD()]);
    } finally {
      setRefreshing(false);
    }
  }

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
    setSelectedIds(new Set());
  }, [search, sourceFilter, selectedCampaignId, selectedBroadcastId, dateFrom, dateTo, assigned, replyWindow, sort]);

  // Search debounce effect
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    api.callers.list().then((res) => setCallers((res.data || []).filter((c) => c.active))).catch(() => {});
    // Same scope as the Meta Ads table: only the ad account connected now.
    api.inboundLeads.campaigns({ currentAccount: true }).then(setCampaigns).catch(() => {});
    api.broadcasts.history().then(setBroadcastHistory).catch(() => {});

    // Fetch WABA templates
    getAuthHeaders().then(auth => {
      fetch(`${API_URL}/api/v1/templates`, { headers: auth })
        .then(r => r.json())
        .then((res: { data: WabaTemplate[] }) => {
          setWabaTemplates((res.data || []).filter((t: WabaTemplate) => t.status === "APPROVED"));
        })
        .catch(() => {});
    });
  }, []);

  useEffect(() => {
    api.segments.templates().then((rows) => {
      const map: Record<string, SegmentTemplate> = {};
      rows.forEach((r) => (map[r.segment] = r));
      setTemplates(map);
    });
  }, []);

  // Handle compose and broadcast URL params
  useEffect(() => {
    if (composeParam === "1") {
      setComposing(true);
    }
  }, [composeParam]);

  useEffect(() => {
    if (broadcastParam === "1") {
      setBroadcastModalOpen(true);
    }
  }, [broadcastParam]);

  function closeCompose() {
    setComposing(false);
    const params = new URLSearchParams(searchParams.toString());
    params.delete("compose");
    router.replace(`/dashboard/leads?${params.toString()}`, { scroll: false });
  }

  function closeBroadcast() {
    setBroadcastModalOpen(false);
    const params = new URLSearchParams(searchParams.toString());
    params.delete("broadcast");
    router.replace(`/dashboard/leads?${params.toString()}`, { scroll: false });
  }

  function openSendMessageModal() {
    const selectedLeads = leads.filter((l) => selectedIds.has(l.id));
    setSendMessageLeads(selectedLeads);
    setSendMessageModalOpen(true);
  }

  function closeSendMessageModal() {
    setSendMessageModalOpen(false);
  }

  async function bulkAssign(callerId: string | null) {
    const ids = Array.from(selectedIds);
    try {
      await api.leads.bulkAssign(ids, callerId);
      toast.success(`Assigned ${ids.length} leads`);
      setSelectedIds(new Set());
      setAssignPopoverOpen(false);
      await mutateList();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to assign");
    }
  }

  async function bulkChangeSegment(newSegment: typeof SEGMENTS[number]) {
    const ids = Array.from(selectedIds);
    try {
      await Promise.all(ids.map((id) => api.leads.update(id, { segment: newSegment })));
      const label = SEGMENT_LABELS[newSegment];
      toast.success(`Moved ${ids.length} leads to ${label}`);
      setSelectedIds(new Set());
      setChangeSegmentPopoverOpen(false);
      await mutateList();
      // Refresh all counts
      await Promise.all([mutateCountA(), mutateCountB(), mutateCountC(), mutateCountD()]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to change segment");
    }
  }

  function getReplyWindowStatus(lead: Lead): { hours: number; minutes: number; isOpen: boolean; isUrgent: boolean } {
    if (!lead.last_inbound_at) {
      return { hours: 0, minutes: 0, isOpen: false, isUrgent: false };
    }
    const lastInbound = new Date(lead.last_inbound_at).getTime();
    const diffMs = now.getTime() - lastInbound;
    const hoursLeft = 24 - diffMs / (1000 * 60 * 60);
    const h = Math.floor(hoursLeft);
    const m = Math.floor((hoursLeft - h) * 60);
    return {
      hours: h,
      minutes: m,
      isOpen: hoursLeft > 0,
      isUrgent: hoursLeft > 0 && hoursLeft < 1,
    };
  }

  function renderReplyWindowCell(lead: Lead): React.ReactNode {
    const status = getReplyWindowStatus(lead);
    const fillPercent = status.isOpen ? (status.hours + status.minutes / 60) / 24 * 100 : 0;

    return (
      <div className="space-y-1">
        <div className="h-1 rounded-full bg-[#e2e8f0] w-40" style={{ overflow: "hidden" }}>
          <div
            className={`h-full transition-all ${
              status.isOpen ? (status.isUrgent ? "bg-orange-500" : "bg-primary") : "bg-[#e2e8f0]"
            }`}
            style={{ width: `${Math.max(fillPercent, 0)}%` }}
          />
        </div>
        <div className="text-xs font-bold">
          {status.isOpen ? (
            status.isUrgent ? (
              <span className="text-orange-500">⚠ {status.minutes}m left – reply now</span>
            ) : (
              <span className="text-primary">{status.hours}h {status.minutes}m left</span>
            )
          ) : (
            <span className="text-[#64748b]">Closed</span>
          )}
        </div>
      </div>
    );
  }

  function getAvatarInitials(lead: Lead): { text: string; bgColor: string } {
    if (lead.name) {
      const parts = lead.name.trim().split(" ");
      const initials = parts.map(p => p[0]).join("").toUpperCase().slice(0, 2);
      return { text: initials, bgColor: getInitialColor(lead.id) };
    }
    if (lead.source === "instagram") return { text: "IG", bgColor: getInitialColor(lead.id) };
    if (lead.source === "telegram") return { text: "TG", bgColor: getInitialColor(lead.id) };
    if (lead.source === "facebook") return { text: "FB", bgColor: getInitialColor(lead.id) };
    if (lead.phone) {
      return { text: lead.phone.replace(/\s/g, "").slice(0, 3), bgColor: getInitialColor(lead.id) };
    }
    return { text: "??", bgColor: getInitialColor(lead.id) };
  }

  function getChannelDot(lead: Lead): { color: string; title: string } {
    const channelColors: Record<string, string> = {
      whatsapp: "#25D366",
      instagram: "#E1306C",
      telegram: "#229ED9",
      facebook: "#1877F2",
    };
    return {
      color: channelColors[lead.source] || "#cbd5e1",
      title: lead.source || "Unknown",
    };
  }

  function getPrimaryLine(lead: Lead): string {
    if (lead.phone) {
      return formatPhone(lead.phone);
    }
    if (lead.source === "instagram") return "Instagram user";
    if (lead.source === "telegram") return "Telegram user";
    if (lead.source === "facebook") return "Facebook user";
    return lead.name || "No contact";
  }

  function getSecondaryLine(lead: Lead): React.ReactNode {
    if (lead.phone) {
      return <NameCell lead={lead} onUpdate={() => mutateList()} compact />;
    }
    if (lead.source === "telegram" && lead.tg_username) return `@${lead.tg_username}`;
    if (lead.source === "instagram" && lead.ig_user_id) return `@${lead.ig_user_id}`;
    if (lead.source === "facebook" && lead.fb_user_id) return lead.fb_user_id;
    return null;
  }

  const showsSourcePicker =
    (sourceFilter === "META_ADS" && campaigns.length > 0) || (sourceFilter === "BROADCAST" && broadcastHistory.length > 0);

  // Meta allows two campaigns with the same name; add the month each was created in Meta so they can be told apart.
  // Until the next sync stores Meta's date, fall back to when Aira first saw the campaign.
  function campaignLabel(c: { id: string; campaign_name: string; created_at?: string; meta_created_at?: string | null }): string {
    const twins = campaigns.filter((x) => x.campaign_name === c.campaign_name);
    const created = c.meta_created_at ?? c.created_at;
    if (twins.length < 2 || !created) return c.campaign_name;
    const month = new Date(created).toLocaleDateString("en-IN", { month: "short", year: "numeric", timeZone: "Asia/Kolkata" });
    return `${c.campaign_name} · ${month}`;
  }

  // Helper to get campaign name
  function getSelectedCampaignName(): string | undefined {
    const selected = campaigns.find((c) => c.id === selectedCampaignId);
    return selected ? campaignLabel(selected) : undefined;
  }

  // Helper to compute date preset from URL dates (using local dates)
  // Shown in the broadcast window so it's clear which leads the message goes to.
  function activeFilterLabels(): string[] {
    const out: string[] = [];
    if (search) out.push(`Search: "${search}"`);
    if (sourceFilter !== "ALL") {
      const source = SOURCE_FILTERS.find((o) => o.value === sourceFilter)?.label ?? sourceFilter;
      const detail =
        sourceFilter === "META_ADS" ? getSelectedCampaignName()
        : sourceFilter === "BROADCAST" ? broadcastHistory.find((b) => b.broadcast_id === selectedBroadcastId)?.template_name
        : undefined;
      out.push(`Source: ${source}${detail ? ` · ${detail}` : ""}`);
    }
    const preset = getDatePreset();
    if (preset !== "any") {
      out.push(`Added: ${{ today: "Today", "7d": "Last 7 days", "30d": "Last 30 days" }[preset] ?? `${dateFrom} to ${dateTo}`}`);
    }
    if (assigned) {
      out.push(`Assigned: ${assigned === "unassigned" ? "Unassigned" : callers.find((c) => c.id === assigned)?.name ?? "Caller"}`);
    }
    if (replyWindow) out.push(`Reply window: ${replyWindow === "open" ? "Open" : "Closed"}`);
    return out;
  }

  function clearFilters() {
    setSearchInput("");
    setSourceFilter("ALL");
    setSelectedCampaignId("");
    setSelectedBroadcastId("");
    setAssigned(undefined);
    setReplyWindow(undefined);
    setDates("", "");
  }

  function getDatePreset(): string {
    if (!dateFrom || !dateTo) return "any";
    const today = new Date();
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
    const sevenDaysAgoStr = `${sevenDaysAgo.getFullYear()}-${String(sevenDaysAgo.getMonth() + 1).padStart(2, "0")}-${String(sevenDaysAgo.getDate()).padStart(2, "0")}`;
    const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);
    const thirtyDaysAgoStr = `${thirtyDaysAgo.getFullYear()}-${String(thirtyDaysAgo.getMonth() + 1).padStart(2, "0")}-${String(thirtyDaysAgo.getDate()).padStart(2, "0")}`;

    if (dateFrom === todayStr && dateTo === todayStr) return "today";
    if (dateFrom === sevenDaysAgoStr && dateTo === todayStr) return "7d";
    if (dateFrom === thirtyDaysAgoStr && dateTo === todayStr) return "30d";
    return "custom";
  }

  const viewToggle = (
    <div className="flex w-max shrink-0 gap-1 rounded-xl border border-[#e2e8f0] bg-[#f8fafc] p-1">
      {([["leads", "New leads"], ["reengagement", "Re-engagement"]] as const).map(([view, label]) => (
        <button
          key={view}
          type="button"
          onClick={() => setPageView(view)}
          className={cn(
            "rounded-lg px-3 py-1.5 text-xs font-bold transition-all",
            pageView === view ? "bg-white text-[#0A1528] shadow-sm" : "text-[#64748b] hover:text-[#0A1528]"
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );

  return (
    <div className="min-w-0">
      {composing && (
        <ComposeModal
          onClose={closeCompose}
          canManageLeads={canManageLeads}
          onSent={() => {
            mutateList();
            closeCompose();
          }}
        />
      )}

      {broadcastModalOpen && (
        <SegmentBroadcastModal
          segment={tab}
          filters={sharedFilters}
          filterLabels={activeFilterLabels()}
          templates={templates}
          canManageLeads={canManageLeads}
          onClose={closeBroadcast}
          onAfterBroadcast={() => {
            mutateList();
          }}
        />
      )}

      {sendMessageModalOpen && (
        <SendMessageModal
          selectedLeads={sendMessageLeads}
          onClose={closeSendMessageModal}
          onAfterSend={() => {
            mutateList();
          }}
        />
      )}

      {sendTemplateLeadId && (
        <SendTemplateModal
          leadId={sendTemplateLeadId}
          onClose={() => {
            setSendTemplateLeadId(null);
            mutateList();
          }}
        />
      )}

      {pageView === "reengagement" && (
        <div className="space-y-6">
          {viewToggle}
          <div className="flex gap-2">
            <button
              onClick={() => setReengageTrigger("inbound")}
              className={`rounded-xl px-4 py-2 text-sm ${reengageTrigger === "inbound" ? "bg-on-surface text-surface" : "bg-on-surface/10 text-on-surface"}`}
            >
              Lead Reply Follow-up
            </button>
            <button
              onClick={() => setReengageTrigger("broadcast")}
              className={`rounded-xl px-4 py-2 text-sm ${reengageTrigger === "broadcast" ? "bg-on-surface text-surface" : "bg-on-surface/10 text-on-surface"}`}
            >
              Campaign Follow-up
            </button>
          </div>

          {reengageTrigger === "broadcast" && (
            <label className="block">
              <span className="font-label text-xs uppercase tracking-widest text-on-surface-muted">Broadcast</span>
              <select
                value={selectedBroadcastId}
                onChange={(e) => setSelectedBroadcastId(e.target.value)}
                className="mt-1 w-full max-w-md rounded-xl border border-on-surface/20 px-3 py-2 text-sm"
              >
                <option value="">Select a broadcast…</option>
                {broadcastHistory.filter((b) => b.broadcast_id).map((b) => (
                  <option key={b.broadcast_id} value={b.broadcast_id}>
                    {b.template_name} · {new Date(b.timestamp).toLocaleString()}
                  </option>
                ))}
              </select>
            </label>
          )}

          <ReengagementBuilder
            key={`${reengageTrigger}:${selectedBroadcastId ?? ""}`}
            type={reengageTrigger}
            broadcastId={reengageTrigger === "broadcast" ? selectedBroadcastId : undefined}
            templates={wabaTemplates}
            canManage={canManageLeads}
          />
        </div>
      )}

      {pageView === "leads" && (
        <div className="space-y-4">
          {/* Segment stat cards */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {SEGMENTS.map((seg) => {
              const count = segmentCounts[seg];
              const colors = SEGMENT_COLORS[seg];
              const isSelected = tab === seg;
              return (
                <button
                  key={seg}
                  onClick={() => setSegment(seg)}
                  className={cn(
                    "relative flex flex-col items-start gap-1 overflow-hidden rounded-2xl border bg-white py-4 pl-5 pr-4 text-left transition-all sm:flex-row sm:items-center sm:gap-4",
                    isSelected
                      ? "border-2 border-primary ring-4 ring-primary/10"
                      : "border-[#e2e8f0] hover:border-slate-300"
                  )}
                >
                  <div className={cn("absolute left-0 top-3 bottom-3 w-1 rounded-r", colors.edge)} />
                  <div className="min-w-[3ch] font-display text-3xl font-bold text-[#0A1528]">
                    {count === undefined ? "—" : count}
                  </div>
                  <div className="min-w-0">
                    <div className={cn("font-bold text-sm", colors.text)}>
                      {SEGMENT_EMOJIS[seg] ? `${SEGMENT_EMOJIS[seg]} ` : ""}{SEGMENT_LABELS[seg]}
                    </div>
                    <div className="text-xs text-[#64748b] mt-0.5">
                      {seg === "A" && "Ready to buy · reply first"}
                      {seg === "B" && "Interested · follow up"}
                      {seg === "C" && "Just browsing · nurture"}
                      {seg === "D" && "No action needed"}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Main card with filters and table */}
          <div className="rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
            {/* Filter bar: Refresh and Export stay on the first line; the filters wrap beside them. */}
            <div className="flex flex-col gap-2 p-4 border-b border-[#e2e8f0] min-[1360px]:flex-row min-[1360px]:items-center">
              {/* One line on wide screens. The campaign/broadcast picker adds a control, so with it the row needs 1440px+. */}
              <div className={cn(
                "flex min-w-0 flex-1 flex-wrap items-center gap-2",
                showsSourcePicker ? "min-[1440px]:flex-nowrap" : "min-[1360px]:flex-nowrap",
              )}>
              {viewToggle}

              {/* Search input */}
              <div className={cn("relative min-w-[150px] flex-1 min-[1360px]:max-w-xs", showsSourcePicker && "min-[1440px]:min-w-[100px]")}>
                <Search size={14} className="absolute left-3 top-2.5 text-[#64748b]" />
                <input
                  type="text"
                  placeholder="Search name or number"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  className="pl-10 pr-3 py-2 w-full text-xs border border-[#e2e8f0] rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
              </div>

              {/* Filter dropdowns */}
              {/* With the picker beside it, "Meta Ads" / "Broadcast" alone says enough and saves room. */}
              <FilterMenu
                label={showsSourcePicker ? SOURCE_FILTERS.find((o) => o.value === sourceFilter)?.label ?? "Source" : "Source"}
                options={SOURCE_FILTERS}
                value={sourceFilter === "ALL" ? undefined : sourceFilter}
                onChange={(val) => {
                  setSourceFilter(val || "ALL");
                  setSelectedCampaignId("");
                  setSelectedBroadcastId("");
                }}
                showValue={!showsSourcePicker}
              />

              {/* Which campaign / broadcast, in the same row as the Source it narrows. */}
              {showsSourcePicker && sourceFilter === "META_ADS" && (
                <select
                  value={selectedCampaignId}
                  onChange={(e) => setSelectedCampaignId(e.target.value)}
                  aria-label="Campaign"
                  className={PICKER_CLASS}
                >
                  <option value="">All campaigns</option>
                  {campaigns.map((c) => (
                    <option key={c.id} value={c.id}>
                      {campaignLabel(c)}
                    </option>
                  ))}
                </select>
              )}

              {showsSourcePicker && sourceFilter === "BROADCAST" && (
                <select
                  value={selectedBroadcastId}
                  onChange={(e) => setSelectedBroadcastId(e.target.value)}
                  aria-label="Broadcast"
                  className={PICKER_CLASS}
                >
                  <option value="">All broadcasts</option>
                  {broadcastHistory.map((h) => (
                    <option key={h.broadcast_id} value={h.broadcast_id}>
                      {h.template_name} · {new Date(h.timestamp).toLocaleDateString()}
                    </option>
                  ))}
                </select>
              )}

              <FilterMenu
                label="Added"
                options={[
                  { value: "any", label: "Any time" },
                  { value: "today", label: "Today" },
                  { value: "7d", label: "Last 7 days" },
                  { value: "30d", label: "Last 30 days" },
                  ...(getDatePreset() === "custom" ? [{ value: "custom", label: "Custom" }] : []),
                ]}
                value={getDatePreset()}
                onChange={(val) => {
                  if (val === "any") {
                    setDates("", "");
                  } else if (val === "today") {
                    const today = new Date();
                    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
                    setDates(todayStr, todayStr);
                  } else if (val === "7d") {
                    const to = new Date();
                    const toStr = `${to.getFullYear()}-${String(to.getMonth() + 1).padStart(2, "0")}-${String(to.getDate()).padStart(2, "0")}`;
                    const from = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
                    const fromStr = `${from.getFullYear()}-${String(from.getMonth() + 1).padStart(2, "0")}-${String(from.getDate()).padStart(2, "0")}`;
                    setDates(fromStr, toStr);
                  } else if (val === "30d") {
                    const to = new Date();
                    const toStr = `${to.getFullYear()}-${String(to.getMonth() + 1).padStart(2, "0")}-${String(to.getDate()).padStart(2, "0")}`;
                    const from = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);
                    const fromStr = `${from.getFullYear()}-${String(from.getMonth() + 1).padStart(2, "0")}-${String(from.getDate()).padStart(2, "0")}`;
                    setDates(fromStr, toStr);
                  }
                }}
                showValue={true}
              />

              {role === "owner" && (
                <FilterMenu
                  label="Assigned"
                  options={[
                    { value: "all", label: "All" },
                    { value: "unassigned", label: "Unassigned" },
                    ...callers.map((c) => ({ value: c.id, label: c.name })),
                  ]}
                  value={assigned}
                  onChange={(val) => {
                    if (val === "all" || !val) {
                      setAssigned(undefined);
                    } else {
                      setAssigned(val);
                    }
                  }}
                  showValue={true}
                />
              )}

              <FilterMenu
                label="Reply window"
                options={[
                  { value: "all", label: "All" },
                  { value: "open", label: "Open" },
                  { value: "closed", label: "Closed" },
                ]}
                value={replyWindow}
                onChange={(val) => {
                  if (val === "all" || !val) {
                    setReplyWindow(undefined);
                  } else {
                    setReplyWindow(val as "open" | "closed");
                  }
                }}
                showValue={true}
              />

              {hasFilters && (
                <button
                  type="button"
                  onClick={clearFilters}
                  className="shrink-0 whitespace-nowrap px-1 text-xs font-semibold text-primary hover:opacity-70"
                >
                  Clear
                </button>
              )}
              </div>

              {/* Right side buttons */}
              <div className="flex shrink-0 gap-2 self-end min-[1360px]:self-auto">
                <button
                  onClick={refreshLeads}
                  title="Refresh"
                  aria-label="Refresh"
                  disabled={refreshing}
                  className="flex items-center gap-1.5 rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 text-xs font-bold text-[#0A1528] hover:bg-[#f8fafc] transition-colors disabled:opacity-40"
                >
                  <RefreshCw size={14} className={cn(refreshing && "animate-spin")} />
                  {/* With a filter set, "Clear" takes the label's room so nothing wraps. */}
                  <span className={cn("min-[1360px]:hidden", !hasFilters && "2xl:inline")}>Refresh</span>
                </button>
                <button
                  onClick={async () => {
                    try {
                      await api.leads.exportLeads(tab);
                      toast.success("Export downloaded");
                    } catch (err) {
                      toast.error(err instanceof Error ? err.message : "Export failed");
                    }
                  }}
                  title="Export"
                  aria-label="Export"
                  className="flex items-center gap-1.5 rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 text-xs font-bold text-[#0A1528] hover:bg-[#f8fafc] transition-colors"
                >
                  <Download size={14} />
                  <span className={cn("min-[1360px]:hidden", !hasFilters && "2xl:inline")}>Export</span>
                </button>
              </div>
            </div>

            {/* Info banner */}
            {!tipsDismissed && (
              <div className="mx-4 mt-3 flex items-start gap-3 rounded-xl border border-primary/20 bg-primary/5 px-4 py-2.5">
                <Info size={14} className="text-primary shrink-0 mt-0.5" />
                <p className="text-xs text-[#334155]">
                  <b className="text-primary">Reply window:</b> WhatsApp &amp; Instagram let you send any free message within 24 hours of the customer&apos;s last message. After that, send an approved template.
                </p>
                <button
                  onClick={() => {
                    setTipsDismissed(true);
                    try {
                      localStorage.setItem("segments.replyTipDismissed", "1");
                    } catch {
                      // ignore
                    }
                  }}
                  className="text-primary hover:text-primary/70 shrink-0"
                >
                  <X size={14} />
                </button>
              </div>
            )}

            {/* Selection bar */}
            {selectedIds.size > 0 && (
              <div className="mx-4 mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-[#0A1528] px-4 py-2.5 text-white">
                <span className="font-bold text-xs">{selectedIds.size} selected</span>
                {canReply && (
                  <button
                    onClick={openSendMessageModal}
                    className="rounded-lg bg-white/10 px-3 py-1.5 text-xs font-bold hover:bg-white/20 transition-colors flex items-center gap-1.5"
                  >
                    <MessageSquare size={12} />
                    Send message
                  </button>
                )}
                {role === "owner" && (
                  <div ref={assignPopoverRef} className="relative">
                    <button
                      onClick={() => setAssignPopoverOpen(!assignPopoverOpen)}
                      className="rounded-lg bg-white/10 px-3 py-1.5 text-xs font-bold hover:bg-white/20 transition-colors flex items-center gap-1.5"
                    >
                      <UserPlus size={12} />
                      Assign
                    </button>
                    {assignPopoverOpen && (
                      <div className="absolute top-full left-0 mt-1 z-30 rounded-xl border border-[#e2e8f0] bg-white shadow-lg min-w-[180px]">
                        <button
                          onClick={() => bulkAssign(null)}
                          className="w-full text-left px-4 py-2.5 text-xs font-semibold text-[#334155] hover:bg-slate-50 transition-colors"
                        >
                          Unassigned
                        </button>
                        {callers.map((caller) => (
                          <button
                            key={caller.id}
                            onClick={() => bulkAssign(caller.id)}
                            className="w-full text-left px-4 py-2.5 text-xs font-semibold text-[#334155] hover:bg-slate-50 transition-colors border-t border-[#f1f5f9]"
                          >
                            {caller.name}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {canManageLeads && (
                <div ref={changeSegmentPopoverRef} className="relative">
                  <button
                    onClick={() => setChangeSegmentPopoverOpen(!changeSegmentPopoverOpen)}
                    className="rounded-lg bg-white/10 px-3 py-1.5 text-xs font-bold hover:bg-white/20 transition-colors flex items-center gap-1.5"
                  >
                    <ArrowLeftRight size={12} />
                    Change segment
                  </button>
                  {changeSegmentPopoverOpen && (
                    <div className="absolute top-full left-0 mt-1 z-30 rounded-xl border border-[#e2e8f0] bg-white shadow-lg min-w-[180px]">
                      {SEGMENTS.map((seg, idx) => (
                        <button
                          key={seg}
                          onClick={() => bulkChangeSegment(seg)}
                          className={cn(
                            "w-full text-left px-4 py-2.5 text-xs font-semibold text-[#334155] transition-colors hover:bg-slate-50 hover:text-[#0A1528]",
                            idx > 0 && "border-t border-[#f1f5f9]"
                          )}
                        >
                          {SEGMENT_LABELS[seg]}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                )}
                <button
                  onClick={() => setSelectedIds(new Set())}
                  className="ml-auto text-white/60 hover:text-white text-xs font-bold"
                >
                  Clear
                </button>
              </div>
            )}

            {/* Table */}
            <div className="hidden md:block overflow-x-auto">
              {isLoading && !leads.length ? (
                <div className="p-8 text-center text-xs text-[#64748b]">Loading...</div>
              ) : leads.length === 0 ? (
                <div className="p-8 text-center text-xs text-[#64748b]">
                  <p>No leads match these filters</p>
                  {hasFilters && (
                    <button
                      onClick={() => {
                        setSearchInput("");
                        setSourceFilter("ALL");
                        setAssigned(undefined);
                        setReplyWindow(undefined);
                        setSort(undefined);
                        setDates("", "");
                      }}
                      className="text-primary text-xs font-semibold mt-2 hover:opacity-70"
                    >
                      Clear filters
                    </button>
                  )}
                </div>
              ) : (
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-[#f1f5f9]">
                      <th className="px-4 py-3 text-left">
                        <CheckTick
                          checked={selectedIds.size === leads.length && leads.length > 0}
                          indeterminate={selectedIds.size > 0 && selectedIds.size < leads.length}
                          onChange={(next) => setSelectedIds(next ? new Set(leads.map((l) => l.id)) : new Set())}
                          aria-label="Select all leads on this page"
                        />
                      </th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
                        Customer
                      </th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
                        Lead
                      </th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
                        Source
                      </th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
                        <button
                          onClick={() => {
                            if (sort === "urgent") {
                              setSort(undefined);
                              setReplyWindow(undefined);
                            } else {
                              setSort("urgent");
                              setReplyWindow("open");
                            }
                          }}
                          className="flex items-center gap-1.5 uppercase tracking-wider text-primary hover:opacity-70"
                        >
                          Reply window ↑
                          {sort === "urgent" && (
                            <span className="inline-block bg-primary/10 text-primary text-[9px] rounded px-1.5 py-0.5 font-semibold">
                              Most urgent first
                            </span>
                          )}
                        </button>
                      </th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
                        Assigned to
                      </th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
                        <button
                          onClick={() => {
                            if (sort === "newest") {
                              setSort("oldest");
                            } else if (sort === "oldest") {
                              setSort(undefined);
                            } else {
                              setSort("newest");
                            }
                          }}
                          className="uppercase tracking-wider hover:opacity-70"
                        >
                          Added ⇅
                        </button>
                      </th>
                      <th className="px-4 py-3 text-right text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
                        Action
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {leads.map((lead) => {
                      const avatar = getAvatarInitials(lead);
                      const channelDot = getChannelDot(lead);
                      return (
                        <tr
                          key={lead.id}
                          onClick={() => router.push(`/dashboard/conversations?lead=${lead.id}`)}
                          className={cn(
                            "border-t border-[#f1f5f9] hover:bg-[#f8fafc] transition-colors cursor-pointer",
                            selectedIds.has(lead.id) && "bg-primary-light/60"
                          )}
                        >
                          <td
                            className="px-4 py-3"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <CheckTick
                              checked={selectedIds.has(lead.id)}
                              onChange={(next) => {
                                const newIds = new Set(selectedIds);
                                if (next) newIds.add(lead.id);
                                else newIds.delete(lead.id);
                                setSelectedIds(newIds);
                              }}
                              aria-label="Select lead"
                            />
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2.5">
                              <div className="relative">
                                <div
                                  className="h-9 w-9 rounded-full flex items-center justify-center text-white font-bold text-[11px]"
                                  style={{ backgroundColor: avatar.bgColor }}
                                >
                                  {avatar.text}
                                </div>
                                <div
                                  className="h-3 w-3 rounded-full ring-2 ring-white absolute bottom-0 right-0"
                                  style={{ backgroundColor: channelDot.color }}
                                  title={channelDot.title}
                                />
                              </div>
                              <div className="min-w-0">
                                <div className="font-bold text-sm text-[#0A1528]">
                                  {getPrimaryLine(lead)}
                                </div>
                                {getSecondaryLine(lead) && (
                                  <div className="text-xs text-[#64748b]">{getSecondaryLine(lead)}</div>
                                )}
                              </div>
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <SegmentBadge segment={lead.segment} />
                          </td>
                          <td className="px-4 py-3 text-sm text-[#334155]">
                            {sourceLabel(lead.source)}
                          </td>
                          <td className="px-4 py-3">
                            {renderReplyWindowCell(lead)}
                          </td>
                          <td className="px-4 py-3">
                            {role === "owner" ? (
                              <div onClick={(e) => e.stopPropagation()}>
                                <AssignButton
                                  leadId={lead.id}
                                  currentAssignedTo={lead.assigned_to}
                                  callers={callers}
                                  onAssigned={() => {
                                    mutateList();
                                  }}
                                />
                              </div>
                            ) : lead.assigned_to ? (
                              <span className="text-xs font-semibold text-[#334155]">
                                {callers.find((c) => c.id === lead.assigned_to)?.name || "Caller"}
                              </span>
                            ) : (
                              <span className="text-xs text-[#64748b]">Unassigned</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-xs text-[#64748b]">
                            {timeAgo(lead.created_at)}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                setSendTemplateLeadId(lead.id);
                              }}
                              className="rounded-lg border border-primary px-3 py-1.5 text-xs font-bold text-primary hover:bg-primary/5"
                            >
                              Send template
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>

            {/* Mobile view */}
            <div className="block md:hidden space-y-3 p-3">
              {isLoading && !leads.length ? (
                <div className="p-8 text-center text-xs text-[#64748b]">Loading...</div>
              ) : leads.length === 0 ? (
                <div className="p-8 text-center text-xs text-[#64748b]">No leads match these filters</div>
              ) : (
                leads.map((lead) => (
                  <MobileRecordCard
                    key={lead.id}
                    onClick={() => router.push(`/dashboard/conversations?lead=${lead.id}`)}
                    className="cursor-pointer"
                  >
                    <MobileRecordHeader
                      title={getPrimaryLine(lead)}
                      subtitle={getSecondaryLine(lead) as string | undefined}
                      aside={<SegmentBadge segment={lead.segment} />}
                    />
                    <MobileRecordGrid>
                      <MobileRecordField
                        label="Source"
                        value={sourceLabel(lead.source)}
                      />
                      <MobileRecordField label="Assigned" value={lead.assigned_to ? callers.find((c) => c.id === lead.assigned_to)?.name || "Caller" : "Unassigned"} />
                      <MobileRecordField label="Added" value={timeAgo(lead.created_at)} />
                      <MobileRecordField
                        label="Reply window"
                        value={(() => {
                          const status = getReplyWindowStatus(lead);
                          if (status.isOpen) {
                            return status.isUrgent ? `⚠ ${status.minutes}m left` : `${status.hours}h ${status.minutes}m left`;
                          }
                          return "Closed";
                        })()}
                      />
                    </MobileRecordGrid>
                    <div className="mt-4 flex items-center justify-between" onClick={(e) => e.stopPropagation()}>
                      <div>
                        {role === "owner" && (
                          <AssignButton
                            leadId={lead.id}
                            currentAssignedTo={lead.assigned_to}
                            callers={callers}
                            onAssigned={() => mutateList()}
                          />
                        )}
                      </div>
                      <div>
                        <button
                          onClick={() => setSendTemplateLeadId(lead.id)}
                          className="rounded-lg border border-primary px-3 py-1.5 text-xs font-bold text-primary hover:bg-primary/5"
                        >
                          Send template
                        </button>
                      </div>
                    </div>
                  </MobileRecordCard>
                ))
              )}
            </div>

            {/* Pagination */}
            {!isLoading && leads.length > 0 && (
              <div className="flex items-center justify-between border-t border-[#f1f5f9] px-4 py-3">
                <div className="text-xs text-[#64748b]">
                  Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, totalLeads)} of {totalLeads} {SEGMENT_LABELS[tab]} leads
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setPage(Math.max(1, page - 1))}
                    disabled={page === 1}
                    className="px-2 py-1.5 text-xs font-bold text-[#0A1528] hover:opacity-70 disabled:opacity-40"
                  >
                    ‹ Prev
                  </button>
                  <div className="flex gap-1">
                    {(() => {
                      const totalPages = Math.ceil(totalLeads / PAGE_SIZE);
                      const maxPages = 5;
                      const pages: (number | string)[] = [];
                      const range = Math.ceil(maxPages / 2);

                      // Always include page 1
                      pages.push(1);

                      // Add pages around current page
                      for (let i = Math.max(2, page - range); i <= Math.min(totalPages - 1, page + range); i++) {
                        pages.push(i);
                      }

                      // Always include last page
                      if (totalPages > 1 && !pages.includes(totalPages)) {
                        pages.push(totalPages);
                      }

                      // Add ellipsis where needed
                      const renderedPages: (number | string)[] = [];
                      for (let i = 0; i < pages.length; i++) {
                        if (i > 0 && (pages[i] as number) - (pages[i - 1] as number) > 1) {
                          if (renderedPages[renderedPages.length - 1] !== "...") {
                            renderedPages.push("...");
                          }
                        }
                        renderedPages.push(pages[i]);
                      }

                      return renderedPages.map((pageNum, idx) => {
                        if (pageNum === "...") {
                          return (
                            <span key={`dots-${idx}`} className="px-1 text-[#64748b]">
                              ...
                            </span>
                          );
                        }
                        return (
                          <button
                            key={pageNum}
                            onClick={() => setPage(pageNum as number)}
                            className={cn(
                              "h-8 min-w-8 rounded-lg border text-xs font-bold transition-colors",
                              pageNum === page
                                ? "bg-primary text-white border-primary"
                                : "border-[#e2e8f0] text-[#0A1528] hover:border-primary hover:text-primary"
                            )}
                          >
                            {pageNum}
                          </button>
                        );
                      });
                    })()}
                  </div>
                  <button
                    onClick={() => setPage(Math.min(Math.ceil(totalLeads / PAGE_SIZE), page + 1))}
                    disabled={page === Math.ceil(totalLeads / PAGE_SIZE)}
                    className="px-2 py-1.5 text-xs font-bold text-[#0A1528] hover:opacity-70 disabled:opacity-40"
                  >
                    Next ›
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
