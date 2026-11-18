"use client";
import { toast } from "sonner";
import { useEffect, useRef, useState } from "react";
import { api, Lead, LeadFilters, Caller, CustomerGroup, BroadcastHistoryItem, WabaTemplate, getAuthHeaders, API_URL } from "@/lib/api";
import { ArrowUp, Download, Pencil, X, RefreshCw, MessageSquare, UserPlus, ArrowLeftRight, Search, Info, FolderPlus, BellOff, Star } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { timeAgo, formatPhone } from "@/lib/utils";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { AssignButton } from "./AssignButton";
import ReengagementBuilder from "./ReengagementBuilder";
import { useLeadsPage, useLeadsSummary } from "@/hooks/useApi";
import { useSearchParams, useRouter } from "next/navigation";
import { MobileRecordCard, MobileRecordField, MobileRecordGrid, MobileRecordHeader } from "@/components/MobileRecord";
import { FilterMenu, FilterMenuOption } from "./FilterMenu";
import { Select } from "@/components/ui/Select";
import { CheckTick } from "@/components/ui/controls";
import { SendMessageModal } from "./SendMessageModal";
import { SendTemplateModal } from "./SendTemplateModal";
import { GroupsPanel } from "./GroupsPanel";

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
/** Status filter: All, one interest level (A-D), or buyers. */
type StatusFilter = "ALL" | (typeof SEGMENTS)[number] | "BUYERS";
/** Which header tab of Customers is showing. */
type HeaderView = "people" | "groups" | "said-stop" | "feedback";

const SEGMENT_LABELS: Record<string, string> = {
  A: "Hot",
  B: "Warm",
  C: "Cold",
  D: "Not interested",
};

/** Interest-word colours, the same tokens the segment badge uses. */
const SEGMENT_TEXT: Record<string, string> = {
  A: "text-segment-a-text",
  B: "text-segment-b-text",
  C: "text-segment-c-text",
  D: "text-segment-d-text",
};

const STATUS_OPTIONS: FilterMenuOption[] = [
  { value: "all", label: "All" },
  { value: "A", label: "Hot" },
  { value: "B", label: "Warm" },
  { value: "C", label: "Cold" },
  { value: "buyers", label: "Buyers" },
];

const STATUS_BY_OPTION: Record<string, StatusFilter> = { A: "A", B: "B", C: "C", D: "D", buyers: "BUYERS" };

const SOURCE_FILTERS: FilterMenuOption[] = [
  { value: "ALL", label: "All" },
  { value: "INBOUND", label: "Inbound" },
  { value: "ORGANIC", label: "Organic" },
  { value: "META_ADS", label: "Meta Ads" },
  { value: "BROADCAST", label: "Broadcast" },
];

const SOURCE_NAMES: Record<string, string> = {
  whatsapp: "WhatsApp", instagram: "Instagram", facebook: "Facebook", telegram: "Telegram", meta_form: "Instant form",
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

/** Buyer or Lead, the interest word, and the broadcast they came from (the name is the only part that cuts short). */
function StatusCell({ lead }: { lead: Lead }) {
  const segment = lead.broadcast_score?.segment ?? lead.segment;
  const broadcastName = lead.broadcast_score?.broadcast_name ?? null;
  return (
    <div className="flex min-w-0 max-w-full items-center gap-1.5 whitespace-nowrap text-xs">
      <span
        className={cn(
          "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold",
          lead.is_buyer ? "bg-primary/10 text-primary" : "bg-slate-100 text-slate-700"
        )}
      >
        {lead.is_buyer ? "Buyer" : "Lead"}
      </span>
      <span className={cn("shrink-0 font-bold", SEGMENT_TEXT[segment])}>{SEGMENT_LABELS[segment] ?? segment}</span>
      {broadcastName && (
        <span className="min-w-0 truncate text-[#64748b]" title={broadcastName}>
          · {broadcastName}
        </span>
      )}
    </div>
  );
}

function GroupsCell({ lead }: { lead: Lead }) {
  const groups = lead.groups ?? [];
  if (groups.length === 0) return <span className="text-xs text-[#64748b]">—</span>;
  return (
    <div className="flex items-center gap-1.5 whitespace-nowrap" title={groups.map((g) => g.name).join(", ")}>
      <span className="max-w-[120px] truncate rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-700">
        {groups[0].name}
      </span>
      {groups.length > 1 && <span className="text-[11px] font-semibold text-[#64748b]">+{groups.length - 1}</span>}
    </div>
  );
}

const STAT_TONES = {
  default: "text-[#0A1528]",
  warn: "text-[#b45309]",
  stop: "text-[#dc2626]",
} as const;

function LeadStatCard({ emoji, label, value, hint, tone = "default", onClick, active, title }: {
  emoji: string; label: string; value: string; hint: string; tone?: keyof typeof STAT_TONES;
  onClick?: () => void;
  /** A filter card that is on: the list below shows only these people. */
  active?: boolean;
  title?: string;
}) {
  const className = cn(
    "flex min-w-0 flex-col items-start gap-1 rounded-2xl border bg-white px-5 py-4 text-left",
    active ? "border-primary bg-primary/5 ring-2 ring-primary/15" : "border-[#e2e8f0]",
  );
  const body = (
    <>
      <div className="flex min-w-0 items-center gap-1.5 text-sm font-semibold text-[#334155]">
        <span aria-hidden className="text-base leading-none">{emoji}</span>
        <span className="truncate">{label}</span>
      </div>
      <div className={cn("font-display text-2xl font-bold sm:text-3xl", STAT_TONES[tone])}>{value}</div>
      <div className="text-xs text-[#64748b]">{hint}</div>
    </>
  );
  if (!onClick) return <div className={className}>{body}</div>;
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      className={cn(className, "transition-all", !active && "hover:border-slate-300")}
    >
      {body}
    </button>
  );
}

function ComingSoonCard({ icon: Icon, title, text }: { icon: LucideIcon; title: string; text: string }) {
  return (
    <div className="rounded-2xl border border-[#e2e8f0] bg-white px-6 py-12 text-center shadow-sm">
      <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Icon size={20} />
      </div>
      <h2 className="mt-4 font-display text-lg font-bold text-[#0A1528]">{title}</h2>
      <p className="mx-auto mt-1 max-w-md text-sm text-[#64748b]">{text}</p>
    </div>
  );
}

const fmtCount = (n: number | undefined) => (n === undefined ? "—" : n.toLocaleString("en-IN"));

export function LeadsClient() {
  const { role, permissions } = useAuthRole();
  const canManageLeads = role === "owner" || permissions.includes("leads.manage");
  // Sending a chat message needs the same right as replying in Conversations.
  const canReply = role === "owner" || permissions.includes("conversations.reply");
  const [refreshing, setRefreshing] = useState(false);
  const [callers, setCallers] = useState<Caller[]>([]);
  const [groups, setGroups] = useState<CustomerGroup[]>([]);

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
  const [sort, setSort] = useState<"urgent" | undefined>();
  const [now, setNow] = useState(new Date());
  const [tipsDismissed, setTipsDismissed] = useState(false);

  // Modal states
  const [sendMessageLeads, setSendMessageLeads] = useState<Lead[]>([]);
  const [sendMessageModalOpen, setSendMessageModalOpen] = useState(false);
  const [sendTemplateLeadId, setSendTemplateLeadId] = useState<string | null>(null);

  // Assign popover state
  const [assignPopoverOpen, setAssignPopoverOpen] = useState(false);
  const assignPopoverRef = useRef<HTMLDivElement>(null);

  // Add to group popover state
  const [groupPopoverOpen, setGroupPopoverOpen] = useState(false);
  const groupPopoverRef = useRef<HTMLDivElement>(null);
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");

  // Change segment popover state
  const [changeSegmentPopoverOpen, setChangeSegmentPopoverOpen] = useState(false);
  const changeSegmentPopoverRef = useRef<HTMLDivElement>(null);

  // Re-engagement states
  const [wabaTemplates, setWabaTemplates] = useState<WabaTemplate[]>([]);
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawTab = searchParams.get("tab");
  const headerView: HeaderView =
    rawTab === "groups" || rawTab === "said-stop" || rawTab === "feedback" ? rawTab : "people";
  // Follow-ups is a header tab (old links say tab=reengagement).
  const pageView: "leads" | "reengagement" = rawTab === "follow-ups" || rawTab === "reengagement" ? "reengagement" : "leads";
  const listEnabled = headerView === "people" && pageView === "leads";
  const dateFrom = searchParams.get("date_from") ?? undefined;
  const dateTo = searchParams.get("date_to") ?? undefined;
  const groupId = searchParams.get("group_id") || undefined;
  // Repeat buyers / Not back in 90 days cards, as a filter (?bought=repeat|quiet).
  const rawBought = searchParams.get("bought");
  const bought = rawBought === "repeat" || rawBought === "quiet" ? rawBought : undefined;
  const toggleBought = (value: "repeat" | "quiet") =>
    replaceLeadsUrl((params) => {
      if (bought === value) params.delete("bought");
      else params.set("bought", value);
    });
  // The status lives in the URL (?segment=A-D, or ?buyer=1), so links like the dashboard's Hot card still land on it.
  const requestedSegment = searchParams.get("segment");
  const status: StatusFilter = (SEGMENTS as readonly string[]).includes(requestedSegment ?? "")
    ? (requestedSegment as (typeof SEGMENTS)[number])
    : searchParams.get("buyer") === "1"
      ? "BUYERS"
      : "ALL";
  const segmentFilter = status === "ALL" || status === "BUYERS" ? undefined : status;
  const [reengageTrigger, setReengageTrigger] = useState<"broadcast" | "inbound">("inbound");

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

  /** One URL update for any mix of params (two back-to-back replaces would drop the first). */
  function replaceLeadsUrl(mutate: (params: URLSearchParams) => void) {
    const params = new URLSearchParams(searchParams.toString());
    mutate(params);
    router.replace(`/dashboard/leads?${params.toString()}`, { scroll: false });
  }

  // Both dates in ONE url update: two back-to-back router.replace calls each start
  // from the same old url, so the second would silently drop the first date.
  const setDates = (from: string, to: string) => {
    replaceLeadsUrl((params) => {
      if (from) params.set("date_from", from);
      else params.delete("date_from");
      if (to) params.set("date_to", to);
      else params.delete("date_to");
    });
  };

  function setStatus(next: StatusFilter) {
    replaceLeadsUrl((params) => {
      params.delete("segment");
      params.delete("buyer");
      if (next === "BUYERS") params.set("buyer", "1");
      else if (next !== "ALL") params.set("segment", next);
    });
  }

  // Filters shared by the list, the summary cards and the export, so the numbers always match the table.
  const listFilters: LeadFilters = {
    segment: segmentFilter,
    buyer: status === "BUYERS" ? true : undefined,
    group_id: groupId,
    bought,
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
      ...listFilters,
      page,
      limit: PAGE_SIZE,
      sort,
    },
    listEnabled
  );
  const { data: summary, mutate: mutateSummary } = useLeadsSummary(listFilters, listEnabled);

  const leads = pageData?.data ?? [];
  const totalLeads = pageData?.total ?? 0;
  const hasFilters = !!(
    search || sourceFilter !== "ALL" || dateFrom || dateTo || assigned || replyWindow || status !== "ALL" || groupId || bought
  );
  const groupName = groups.find((g) => g.id === groupId)?.name ?? "Group";
  const statusValue = status === "ALL" ? "all" : status === "BUYERS" ? "buyers" : status;
  const statusOptions: FilterMenuOption[] =
    status === "D" ? [...STATUS_OPTIONS, { value: "D", label: "Not interested" }] : STATUS_OPTIONS;
  // What the table is showing, in words: "hot leads", "buyers", "all people".
  const listName = status === "ALL" ? "people" : status === "BUYERS" ? "buyers" : `${SEGMENT_LABELS[status].toLowerCase()} leads`;

  async function refreshLeads() {
    setRefreshing(true);
    try {
      await Promise.all([mutateList(), mutateSummary()]);
    } finally {
      setRefreshing(false);
    }
  }

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
    setSelectedIds(new Set());
  }, [search, sourceFilter, selectedCampaignId, selectedBroadcastId, dateFrom, dateTo, assigned, replyWindow, sort, status, groupId, bought]);

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
    api.customerGroups.list().then(setGroups).catch(() => {});

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

  // Close the add-to-group popover on an outside click.
  useEffect(() => {
    if (!groupPopoverOpen) return;
    function handleClickOutside(event: MouseEvent) {
      if (groupPopoverRef.current && !groupPopoverRef.current.contains(event.target as Node)) {
        setGroupPopoverOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [groupPopoverOpen]);

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

  function finishGroupAdd(groupLabel: string, count: number) {
    toast.success(`Added ${count} to ${groupLabel}`);
    setSelectedIds(new Set());
    setGroupPopoverOpen(false);
    setCreatingGroup(false);
    setNewGroupName("");
    mutateList();
    api.customerGroups.list().then(setGroups).catch(() => {});
  }

  async function addSelectedToGroup(group: CustomerGroup) {
    const ids = Array.from(selectedIds);
    try {
      await api.customerGroups.addMembers(group.id, ids);
      finishGroupAdd(group.name, ids.length);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add to group");
    }
  }

  async function createGroupAndAdd() {
    const name = newGroupName.trim();
    if (!name) return;
    const ids = Array.from(selectedIds);
    try {
      const group = await api.customerGroups.create(name);
      await api.customerGroups.addMembers(group.id, ids);
      finishGroupAdd(group.name, ids.length);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create group");
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
      await Promise.all([mutateList(), mutateSummary()]);
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
        <div className="h-1 rounded-full bg-[#e2e8f0] w-24" style={{ overflow: "hidden" }}>
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
      whatsapp: "var(--primary)", // brand teal; WhatsApp green is banned (lib/brand-guard.test.ts)
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

  function clearFilters() {
    setSearchInput("");
    setSourceFilter("ALL");
    setSelectedCampaignId("");
    setSelectedBroadcastId("");
    setAssigned(undefined);
    setReplyWindow(undefined);
    replaceLeadsUrl((params) => {
      for (const key of ["date_from", "date_to", "segment", "buyer", "group_id", "bought"]) params.delete(key);
    });
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

  return (
    <div className="min-w-0">
      {sendMessageModalOpen && (
        <SendMessageModal
          selectedLeads={sendMessageLeads}
          batchLabel={listName}
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

      {headerView === "groups" && <GroupsPanel />}

      {headerView === "said-stop" && (
        <ComingSoonCard
          icon={BellOff}
          title="Said stop"
          text="People who asked you to stop messaging them will be listed here. This list is being built next."
        />
      )}

      {headerView === "feedback" && (
        <ComingSoonCard
          icon={Star}
          title="Feedback"
          text="Star ratings customers give after a purchase or visit will show here. This list is being built next."
        />
      )}

      {headerView === "people" && pageView === "reengagement" && (
        <div className="space-y-6">
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
              <Select
                value={selectedBroadcastId}
                onChange={setSelectedBroadcastId}
                placeholder="Select a broadcast…"
                className="mt-1 max-w-md"
                options={broadcastHistory
                  .flatMap((b) => (b.broadcast_id ? [{ ...b, broadcast_id: b.broadcast_id }] : []))
                  .map((b) => ({
                    value: b.broadcast_id,
                    label: `${b.template_name} · ${new Date(b.timestamp).toLocaleString()}`,
                  }))}
              />
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

      {headerView === "people" && pageView === "leads" && (
        <div className="space-y-4">
          {/* Customer summary cards: they follow the same filters as the table below. */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <LeadStatCard
              emoji="👥"
              label="People"
              value={fmtCount(summary?.people)}
              hint={summary ? `${fmtCount(summary.leads)} leads · ${fmtCount(summary.buyers)} buyers` : ""}
            />
            <LeadStatCard
              emoji="🔁"
              label="Repeat buyers"
              active={bought === "repeat"}
              onClick={() => toggleBought("repeat")}
              title={bought === "repeat" ? "Showing repeat buyers. Click to show everyone" : "Show only repeat buyers"}
              value={fmtCount(summary?.repeat_buyers)}
              hint="bought 2+ times"
            />
            <LeadStatCard
              emoji="💰"
              label="Spent with you"
              value={summary ? `₹${(summary.spent_paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "—"}
              hint="all time"
            />
            <LeadStatCard
              emoji="😴"
              label="Not back in 90 days"
              active={bought === "quiet"}
              onClick={() => toggleBought("quiet")}
              title={bought === "quiet" ? "Showing buyers not back in 90 days. Click to show everyone" : "Show only buyers not back in 90 days"}
              tone="warn"
              value={fmtCount(summary?.not_back_90)}
              hint="bought before, quiet since"
            />
            <LeadStatCard
              emoji="⛔"
              label="Said stop"
              tone="stop"
              value={fmtCount(summary?.said_stop)}
              hint="no offers go to them"
              onClick={() => router.push("/dashboard/leads?tab=said-stop")}
            />
          </div>

          {/* Main card with filters and table */}
          <div className="rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
            {/* Filter bar: one line. It wraps (never overlaps) only when the card is too narrow for
                every control, e.g. a small screen with the sidebar open and long filter values. */}
            <div className="flex flex-wrap items-center gap-1.5 p-4 border-b border-[#e2e8f0]">
              {/* Search input */}
              <div className="relative min-w-[120px] flex-1">
                <Search size={14} className="absolute left-3 top-2.5 text-[#64748b]" />
                <input
                  type="text"
                  placeholder="Search name, number, broadcast or ad"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  className="pl-10 pr-3 py-2 w-full text-xs border border-[#e2e8f0] rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
              </div>

              {/* Filter dropdowns */}
              <FilterMenu
                label="Status"
                options={statusOptions}
                value={statusValue}
                onChange={(val) => setStatus(STATUS_BY_OPTION[val ?? ""] ?? "ALL")}
                showValue={true}
              />

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

              {/* Which campaign / broadcast, in the same row as the Source it narrows. It starts at 124px when
                  the row decides line breaks, then grows only up to its text, so a long name truncates
                  instead of pushing Refresh / Download to a second line. */}
              {showsSourcePicker && sourceFilter === "META_ADS" && (
                <Select
                  size="sm"
                  value={selectedCampaignId}
                  onChange={setSelectedCampaignId}
                  aria-label="Campaign"
                  className="w-auto min-w-0 max-w-fit basis-[124px] grow gap-1.5 pl-2.5 pr-2 text-xs font-bold text-[#0A1528]"
                  options={[
                    { value: "", label: "All campaigns" },
                    ...campaigns.map((c) => ({ value: c.id, label: campaignLabel(c) })),
                  ]}
                />
              )}

              {showsSourcePicker && sourceFilter === "BROADCAST" && (
                <Select
                  size="sm"
                  value={selectedBroadcastId}
                  onChange={setSelectedBroadcastId}
                  aria-label="Broadcast"
                  className="w-auto min-w-0 max-w-fit basis-[124px] grow gap-1.5 pl-2.5 pr-2 text-xs font-bold text-[#0A1528]"
                  options={[
                    { value: "", label: "All broadcasts" },
                    ...broadcastHistory.flatMap((h) =>
                      h.broadcast_id
                        ? [{ value: h.broadcast_id, label: `${h.template_name} · ${new Date(h.timestamp).toLocaleDateString()}` }]
                        : [],
                    ),
                  ]}
                />
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
                  label="Handled by"
                  options={[
                    { value: "all", label: "All" },
                    { value: "unassigned", label: "Unassigned" },
                    { value: "ai_agent", label: "AI agent" },
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

              {groupId && (
                <span className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg bg-primary/10 py-1 pl-3 pr-1.5 text-xs font-bold text-primary">
                  Group: {groupName}
                  <button
                    type="button"
                    onClick={() => replaceLeadsUrl((params) => params.delete("group_id"))}
                    aria-label="Remove group filter"
                    className="rounded p-0.5 hover:bg-primary/10"
                  >
                    <X size={12} />
                  </button>
                </span>
              )}

              {hasFilters && (
                <button
                  type="button"
                  onClick={clearFilters}
                  className="shrink-0 whitespace-nowrap px-1 text-xs font-semibold text-primary hover:opacity-70"
                >
                  Clear
                </button>
              )}

              {/* Right side buttons */}
              <div className="ml-auto flex shrink-0 gap-1.5">
                <button
                  onClick={refreshLeads}
                  title="Refresh"
                  aria-label="Refresh"
                  disabled={refreshing}
                  className="flex h-9 w-9 items-center justify-center rounded-xl border border-[#e2e8f0] bg-white text-[#0A1528] hover:bg-[#f8fafc] transition-colors disabled:opacity-40"
                >
                  <RefreshCw size={14} className={cn(refreshing && "animate-spin")} />
                </button>
                {role === "owner" && (
                  <button
                    onClick={async () => {
                      try {
                        await api.leads.exportLeads(listFilters);
                        toast.success("Export downloaded");
                      } catch (err) {
                        toast.error(err instanceof Error ? err.message : "Export failed");
                      }
                    }}
                    title="Export"
                    aria-label="Export"
                    className="flex h-9 w-9 items-center justify-center rounded-xl border border-[#e2e8f0] bg-white text-[#0A1528] hover:bg-[#f8fafc] transition-colors"
                  >
                    <Download size={14} />
                  </button>
                )}
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
                {canManageLeads && (
                  <div ref={groupPopoverRef} className="relative">
                    <button
                      onClick={() => setGroupPopoverOpen(!groupPopoverOpen)}
                      className="rounded-lg bg-white/10 px-3 py-1.5 text-xs font-bold hover:bg-white/20 transition-colors flex items-center gap-1.5"
                    >
                      <FolderPlus size={12} />
                      Add to group
                    </button>
                    {groupPopoverOpen && (
                      <div className="absolute top-full left-0 mt-1 z-30 min-w-[220px] rounded-xl border border-[#e2e8f0] bg-white shadow-lg">
                        {groups.filter((g) => g.kind === "picked").length === 0 && (
                          <div className="px-4 py-2.5 text-xs text-[#64748b]">No groups yet</div>
                        )}
                        {groups
                          .filter((g) => g.kind === "picked")
                          .map((group) => (
                            <button
                              key={group.id}
                              onClick={() => addSelectedToGroup(group)}
                              className="flex w-full items-center justify-between gap-3 border-t border-[#f1f5f9] px-4 py-2.5 text-left text-xs font-semibold text-[#334155] transition-colors first:border-t-0 hover:bg-slate-50"
                            >
                              <span className="truncate">{group.name}</span>
                              <span className="shrink-0 text-[#64748b]">{group.member_count}</span>
                            </button>
                          ))}
                        {creatingGroup ? (
                          <form
                            onSubmit={(e) => {
                              e.preventDefault();
                              createGroupAndAdd();
                            }}
                            className="flex items-center gap-2 border-t border-[#f1f5f9] p-2.5"
                          >
                            <input
                              autoFocus
                              value={newGroupName}
                              onChange={(e) => setNewGroupName(e.target.value)}
                              placeholder="Group name"
                              className="min-w-0 flex-1 rounded-lg border border-[#e2e8f0] px-2.5 py-1.5 text-xs text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary/20"
                            />
                            <button
                              type="submit"
                              disabled={!newGroupName.trim()}
                              className="shrink-0 rounded-lg bg-primary px-2.5 py-1.5 text-xs font-bold text-white disabled:opacity-40"
                            >
                              {"Create & add"}
                            </button>
                          </form>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setCreatingGroup(true)}
                            className="w-full border-t border-[#f1f5f9] px-4 py-2.5 text-left text-xs font-bold text-primary hover:bg-slate-50"
                          >
                            + New group
                          </button>
                        )}
                      </div>
                    )}
                  </div>
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
                        clearFilters();
                        setSort(undefined);
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
                        Name
                      </th>
                      <th className="w-[220px] max-w-[220px] px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
                        Status
                      </th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
                        Spent
                      </th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
                        Last
                      </th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
                        Came from
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
                          title={sort === "urgent" ? "Most urgent first. Click to undo" : "Show the most urgent first"}
                          aria-pressed={sort === "urgent"}
                          className="flex items-center gap-1 whitespace-nowrap uppercase tracking-wider text-primary hover:opacity-70"
                        >
                          Reply window
                          {/* The arrow turns over when "most urgent first" is on. */}
                          <ArrowUp
                            size={12}
                            strokeWidth={2.5}
                            aria-hidden
                            className={cn("transition-transform duration-300", sort === "urgent" && "rotate-180")}
                          />
                        </button>
                      </th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
                        Assigned to
                      </th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b]">
                        Groups
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
                                <div className="whitespace-nowrap font-bold text-sm text-[#0A1528]">
                                  {getPrimaryLine(lead)}
                                </div>
                                {getSecondaryLine(lead) && (
                                  <div className="whitespace-nowrap text-xs text-[#64748b]">{getSecondaryLine(lead)}</div>
                                )}
                              </div>
                            </div>
                          </td>
                          <td className="w-[220px] max-w-[220px] px-4 py-3">
                            <StatusCell lead={lead} />
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-sm text-[#334155]">
                            {lead.spent_paise ? `₹${(lead.spent_paise / 100).toLocaleString("en-IN")}` : "—"}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-xs text-[#64748b]">
                            {lead.last_activity_at ? timeAgo(lead.last_activity_at) : "—"}
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
                          <td className="px-4 py-3">
                            <GroupsCell lead={lead} />
                          </td>
                          <td className="px-4 py-3 text-right">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                setSendTemplateLeadId(lead.id);
                              }}
                              className="whitespace-nowrap rounded-lg border border-primary px-3 py-1.5 text-xs font-bold text-primary hover:bg-primary/5"
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
                    />
                    <MobileRecordGrid>
                      <MobileRecordField label="Status" value={<StatusCell lead={lead} />} className="col-span-2" />
                      <MobileRecordField
                        label="Spent"
                        value={lead.spent_paise ? `₹${(lead.spent_paise / 100).toLocaleString("en-IN")}` : "—"}
                      />
                      <MobileRecordField label="Came from" value={sourceLabel(lead.source)} />
                      <MobileRecordField label="Last" value={lead.last_activity_at ? timeAgo(lead.last_activity_at) : "—"} />
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
                      <MobileRecordField label="Assigned" value={lead.assigned_to ? callers.find((c) => c.id === lead.assigned_to)?.name || "Caller" : "Unassigned"} />
                      <MobileRecordField label="Groups" value={<GroupsCell lead={lead} />} className="col-span-2" />
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
                          className="whitespace-nowrap rounded-lg border border-primary px-3 py-1.5 text-xs font-bold text-primary hover:bg-primary/5"
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
                  Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, totalLeads)} of {totalLeads} {listName}
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
