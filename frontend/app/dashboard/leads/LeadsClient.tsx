"use client";
import { toast } from "sonner";
import { useEffect, useRef, useState } from "react";
import { api, Lead, Caller, CustomerGroup, GroupRule, BroadcastHistoryItem, WabaTemplate, getAuthHeaders, API_URL } from "@/lib/api";
import { ArrowUp, Check, ChevronDown, Phone, Download, Pencil, X, RefreshCw, MessageSquare, UserPlus, ArrowLeftRight, Search, Info, FolderPlus, BellOff, Bookmark, Tag, PhoneForwarded, Megaphone, Users, Upload, QrCode, SlidersHorizontal, User } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { Pagination } from "@/components/ui/Pagination";
import { timeAgo, formatPhone } from "@/lib/utils";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { AssignButton } from "./AssignButton";
import ReengagementBuilder from "./ReengagementBuilder";
import {
  CAME_FROM_OPTIONS,
  ADD_CALLER_HREF,
  NO_CALLERS_TEXT,
  callingApi,
  campaignHrefForGroup,
  describeCallingResult,
  describeTagResult,
  downloadLeadsCsv,
  parseTagInput,
  savePickedPeopleAsGroup,
  tagsApi,
  useLeadsPageX,
  useLeadsSummaryX,
  type LeadFiltersX,
  type LeadRow,
  type TagCount,
} from "@/lib/customersApi";
import { useSearchParams, useRouter } from "next/navigation";
import { MobileRecordField, MobileRecordGrid } from "@/components/MobileRecord";
import { FilterMenu, FilterMenuOption } from "./FilterMenu";
import { Select } from "@/components/ui/Select";
import { CheckTick } from "@/components/ui/controls";
import { SendMessageModal } from "./SendMessageModal";
import { SendTemplateModal } from "./SendTemplateModal";
import { GroupsPanel, RuleChoices } from "./GroupsPanel";
import { SaidStopPanel } from "./SaidStopPanel";
import { FeedbackPanel } from "./FeedbackPanel";
import { ConfirmModal } from "@/components/ConfirmModal";

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

/** Phone list chips and avatar tints, one per interest level. */
const PHONE_SEGMENT: Record<string, string> = {
  A: "bg-rose-100 text-rose-800",
  B: "bg-amber-100 text-amber-900",
  C: "bg-slate-200 text-slate-700",
  D: "bg-slate-100 text-slate-500",
};

const PHONE_CHIPS: { key: StatusFilter; label: string }[] = [
  { key: "ALL", label: "All" },
  { key: "A", label: "Hot" },
  { key: "B", label: "Warm" },
  { key: "C", label: "Cold" },
  { key: "D", label: "Not interested" },
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
  whatsapp: "WhatsApp", instagram: "Instagram", facebook: "Facebook", telegram: "Telegram", meta_form: "Instant form", qr: "QR",
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

/** The tags on a row, as small chips; clicking one filters the list to that tag. Shows 3, then +N. */
function TagChips({ tags, onPick }: { tags?: string[]; onPick: (tag: string) => void }) {
  if (!tags || tags.length === 0) return null;
  const shown = tags.slice(0, 3);
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1" onClick={(e) => e.stopPropagation()}>
      {shown.map((t) => (
        <button
          key={t}
          type="button"
          onClick={() => onPick(t)}
          title={`Show everyone tagged ${t}`}
          className="max-w-[110px] truncate rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700 hover:bg-slate-200"
        >
          {t}
        </button>
      ))}
      {tags.length > shown.length && (
        <span className="text-xs font-semibold text-[#556274]" title={tags.slice(3).join(", ")}>+{tags.length - shown.length}</span>
      )}
    </div>
  );
}

/** ⛔ Said stop: they asked for no offers. Bills, order updates and replies still go. */
function SaidStopMark() {
  return (
    <span
      title="Said stop: no offers, follow-ups or calls. Bills, order updates and replies still go."
      className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-bold text-red-600"
    >
      ⛔ Said stop
    </span>
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
    "flex min-w-0 flex-col items-start gap-0.5 rounded-2xl border bg-white px-3 py-2.5 text-left sm:gap-1 sm:px-5 sm:py-4",
    active ? "border-primary bg-primary/5 ring-2 ring-primary/15" : "border-[#e2e8f0]",
  );
  const body = (
    <>
      <div className="flex min-w-0 max-w-full items-center gap-1.5 text-xs font-semibold text-[#334155] sm:text-sm">
        <span aria-hidden className="text-sm leading-none sm:text-base">{emoji}</span>
        <span className="truncate">{label}</span>
      </div>
      <div className={cn("max-w-full font-display text-lg font-bold max-sm:truncate sm:text-3xl", STAT_TONES[tone])}>{value}</div>
      <div className="max-w-full text-xs text-[#64748b] max-sm:hidden">{hint}</div>
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

// First day: no customers at all and nothing filtered. Says what shows here, why it is empty,
// and gives the ways to fill it. Buttons only appear for people who may use those pages.
function FirstDayEmpty({ canImport, canQr }: { canImport: boolean; canQr: boolean }) {
  return (
    <div className="flex flex-col items-center px-4 py-14 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Users size={28} />
      </div>
      <h3 className="mt-4 font-display text-lg font-bold text-ink">No customers yet</h3>
      <p className="mt-2 max-w-md font-body text-sm text-[#556274]">
        Everyone who messages you, books, calls or buys shows here by themselves, one line per phone number. You don&apos;t have to type anyone in.
      </p>
      {(canImport || canQr) && (
        <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
          {canImport && (
            <Link href="/dashboard/telecalling/upload" className="btn-primary">
              <Upload size={14} /> Bring my old customer list (Excel)
            </Link>
          )}
          {canQr && (
            <Link href="/dashboard/qr-links" className="btn-secondary">
              <QrCode size={14} /> Get my shop QR
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

const fmtCount = (n: number | undefined) => (n === undefined ? "—" : n.toLocaleString("en-IN"));

export function LeadsClient() {
  // Phone only: the full filter bar folds behind one "Filters" button so the list starts near the top.
  const [phoneFiltersOpen, setPhoneFiltersOpen] = useState(false);
  const { role, permissions } = useAuthRole();
  const canManageLeads = role === "owner" || permissions.includes("leads.manage");
  // Sending a chat message needs the same right as replying in Conversations.
  const canReply = role === "owner" || permissions.includes("conversations.reply");
  const canImportList = role === "owner" || permissions.includes("telecalling.upload");
  const canGetQr = role === "owner" || permissions.includes("numbers.manage");
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
  // Phone list: which row has its details open.
  const [expandedId, setExpandedId] = useState<string | null>(null);
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

  // Tags: every tag in use (for the Tag filter and the picker), and the bulk Tag popover
  const [tagCounts, setTagCounts] = useState<TagCount[]>([]);
  const [tagPopoverOpen, setTagPopoverOpen] = useState(false);
  const tagPopoverRef = useRef<HTMLDivElement>(null);
  const [tagInput, setTagInput] = useState("");
  const [tagBusy, setTagBusy] = useState(false);
  const [callingBusy, setCallingBusy] = useState(false);
  const [campaignBusy, setCampaignBusy] = useState(false);

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
  // Leads only / Came from / Tag live in the URL too, so Reports and other pages can link straight to them.
  const onlyLeads = searchParams.get("only") === "leads";
  const cameFrom = searchParams.get("came_from") || undefined;
  const tagFilter = searchParams.get("tag") || undefined;
  // Google Ads > Open: one campaign's people (cleared with the chip above the table).
  const urlCampaign = searchParams.get("ad_campaign_id") || undefined;
  const setUrlParam = (key: string, value: string | undefined) =>
    replaceLeadsUrl((params) => {
      if (value) params.set(key, value);
      else params.delete(key);
    });
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
  const listFilters: LeadFiltersX = {
    segment: segmentFilter,
    buyer: status === "BUYERS" ? true : undefined,
    group_id: groupId,
    bought,
    search: search || undefined,
    source_filter: sourceFilter !== "ALL" ? sourceFilter.toLowerCase() : undefined,
    ad_campaign_id: sourceFilter === "META_ADS" && selectedCampaignId ? selectedCampaignId : urlCampaign,
    broadcast_id: sourceFilter === "BROADCAST" && selectedBroadcastId ? selectedBroadcastId : undefined,
    date_from: dateFrom,
    date_to: dateTo,
    assigned_to: assigned,
    reply_window: replyWindow,
    only: onlyLeads ? "leads" : undefined,
    came_from: cameFrom,
    tag: tagFilter,
  };

  // SWR Hooks for page data
  const { data: pageData, mutate: mutateList, isLoading } = useLeadsPageX(
    {
      ...listFilters,
      page,
      limit: PAGE_SIZE,
      sort,
    },
    listEnabled
  );
  const { data: summary, mutate: mutateSummary } = useLeadsSummaryX(listFilters, listEnabled);

  const leads: LeadRow[] = pageData?.data ?? [];
  const totalLeads = pageData?.total ?? 0;
  const hasFilters = !!(
    search || sourceFilter !== "ALL" || dateFrom || dateTo || assigned || replyWindow || status !== "ALL" || groupId || bought ||
    onlyLeads || cameFrom || tagFilter
  );
  const firstDay = totalLeads === 0 && !hasFilters;
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
  }, [search, sourceFilter, selectedCampaignId, selectedBroadcastId, dateFrom, dateTo, assigned, replyWindow, sort, status, groupId, bought, onlyLeads, cameFrom, tagFilter]);

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
    tagsApi.list().then(setTagCounts).catch(() => {});

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

  // Close the Tag popover on an outside click.
  useEffect(() => {
    if (!tagPopoverOpen) return;
    function handleClickOutside(event: MouseEvent) {
      if (tagPopoverRef.current && !tagPopoverRef.current.contains(event.target as Node)) {
        setTagPopoverOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [tagPopoverOpen]);

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

  const ruleChoices: RuleChoices = {
    callers: callers.map((c) => ({ id: c.id, name: c.name })),
    campaigns: campaigns.map((c) => ({ id: c.id, label: campaignLabel(c) })),
    broadcasts: broadcastHistory.flatMap((h) =>
      h.broadcast_id ? [{ id: h.broadcast_id, label: `${h.template_name} · ${new Date(h.timestamp).toLocaleDateString()}` }] : [],
    ),
    tags: tagCounts.map((t) => t.tag),
  };

  // "Save as a group": the filters on screen become a group that fills itself. Rules use rolling
  // dates, so only the Added presets carry over; a typed search or a custom date range does not.
  const savedRule: GroupRule = {
    ...(segmentFilter ? { segment: segmentFilter } : {}),
    ...(status === "BUYERS" ? { buyer: true as const } : {}),
    ...(sourceFilter !== "ALL" ? { source_filter: sourceFilter.toLowerCase() as GroupRule["source_filter"] } : {}),
    ...(listFilters.broadcast_id ? { broadcast_id: listFilters.broadcast_id } : {}),
    ...(listFilters.ad_campaign_id ? { ad_campaign_id: listFilters.ad_campaign_id } : {}),
    ...({ today: { added_days: 1 }, "7d": { added_days: 7 }, "30d": { added_days: 30 } } as Record<string, GroupRule>)[getDatePreset()] ?? {},
    ...(assigned ? { assigned_to: assigned } : {}),
    ...(replyWindow ? { reply_window: replyWindow } : {}),
    ...(bought ? { bought } : {}),
    ...(tagFilter ? { tag: tagFilter } : {}),
  };
  const canSaveAsGroup = canManageLeads && Object.keys(savedRule).length > 0;
  const [savingGroupOpen, setSavingGroupOpen] = useState(false);
  const [savedGroupName, setSavedGroupName] = useState("");

  async function saveFiltersAsGroup() {
    const name = savedGroupName.trim();
    if (!name) return;
    try {
      const group = await api.customerGroups.create(name, savedRule);
      const left = [search && "the search", getDatePreset() === "custom" && "the custom dates", groupId && "the group filter", (onlyLeads || cameFrom) && "Leads only or Came from"].filter(Boolean);
      toast.success(
        `Saved "${group.name}": ${group.member_count} people today. It updates by itself.` +
          (left.length ? ` (${left.join(" and ")} isn't part of it.)` : ""),
      );
      setSavingGroupOpen(false);
      setSavedGroupName("");
      api.customerGroups.list().then(setGroups).catch(() => {});
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the group");
    }
  }

  const [confirmSaidStop, setConfirmSaidStop] = useState(false);
  const [saidStopBusy, setSaidStopBusy] = useState(false);

  async function addSelectedToSaidStop() {
    setSaidStopBusy(true);
    try {
      const { added } = await api.saidStop.add(Array.from(selectedIds));
      toast.success(`${added} added to Said stop. No offers or calls will go to them.`);
      setConfirmSaidStop(false);
      setSelectedIds(new Set());
      await Promise.all([mutateList(), mutateSummary()]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not add to Said stop");
    } finally {
      setSaidStopBusy(false);
    }
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

  /** Add or take off the typed tags for everyone ticked. */
  async function bulkTag(kind: "add" | "remove") {
    const tags = parseTagInput(tagInput);
    if (tags.length === 0) {
      toast.error("Type a tag first, or pick one below");
      return;
    }
    const ids = Array.from(selectedIds);
    setTagBusy(true);
    try {
      const result = kind === "add" ? await tagsApi.add(ids, tags) : await tagsApi.remove(ids, tags);
      toast.success(describeTagResult(kind, result));
      setTagInput("");
      setTagPopoverOpen(false);
      setSelectedIds(new Set());
      await mutateList();
      tagsApi.list().then(setTagCounts).catch(() => {});
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not change tags");
    } finally {
      setTagBusy(false);
    }
  }

  /** Put the ticked people on the calling list and say what happened to each kind. */
  async function bulkSendToCalling() {
    const ids = Array.from(selectedIds);
    setCallingBusy(true);
    try {
      const result = await callingApi.sendPeople(ids);
      if (result.no_callers) {
        toast.error(NO_CALLERS_TEXT, { action: { label: "Open Team", onClick: () => router.push(ADD_CALLER_HREF) }, duration: 10000 });
        return;
      }
      toast.success(describeCallingResult(result), { duration: 10000 });
      setSelectedIds(new Set());
      await mutateList();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not send to calling");
    } finally {
      setCallingBusy(false);
    }
  }

  /** The ticked people become a fixed "Picked" group, then Reach opens with that group chosen.
   *  Said-stop people in the group are left out by Reach itself. */
  async function bulkSendCampaign() {
    const ids = Array.from(selectedIds);
    if (ids.length === 0 || campaignBusy) return;
    setCampaignBusy(true);
    try {
      const group = await savePickedPeopleAsGroup(ids);
      toast.success(`Saved ${ids.length} ${ids.length === 1 ? "person" : "people"} as "${group.name}"`);
      router.push(campaignHrefForGroup(group.id));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the group");
      setCampaignBusy(false);
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

  /** text is null when there is no real name to take letters from: the row then shows a plain person icon. */
  function getAvatarInitials(lead: Lead): { text: string | null; bgColor: string } {
    if (lead.name && !/^[+\d]/.test(lead.name.trim())) {
      const parts = lead.name.trim().split(" ");
      const initials = parts.map(p => p[0]).join("").toUpperCase().slice(0, 2);
      return { text: initials, bgColor: getInitialColor(lead.id) };
    }
    if (lead.source === "instagram") return { text: "IG", bgColor: getInitialColor(lead.id) };
    if (lead.source === "telegram") return { text: "TG", bgColor: getInitialColor(lead.id) };
    if (lead.source === "facebook") return { text: "FB", bgColor: getInitialColor(lead.id) };
    return { text: null, bgColor: getInitialColor(lead.id) };
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
      for (const key of ["date_from", "date_to", "segment", "buyer", "group_id", "bought", "only", "came_from", "tag"]) params.delete(key);
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

      <ConfirmModal
        open={confirmSaidStop}
        onClose={() => setConfirmSaidStop(false)}
        onConfirm={addSelectedToSaidStop}
        title={`Add ${selectedIds.size} to Said stop?`}
        description="Offers, follow-ups, auto-messages and telecaller calls stop for them. The AI agent still answers if they message you, and payment messages still go. Only do this when they asked."
        tone="danger"
        confirmLabel="Add to said stop"
        loading={saidStopBusy}
        loadingLabel="Adding…"
      />

      {headerView === "groups" && <GroupsPanel choices={ruleChoices} />}

      {headerView === "said-stop" && <SaidStopPanel />}

      {headerView === "feedback" && <FeedbackPanel />}

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
            initialGroupId={searchParams.get("group") || undefined}
          />
        </div>
      )}

      {headerView === "people" && pageView === "leads" && (
        <div className="space-y-4">
          {/* Customer summary cards: they follow the same filters as the table below. */}
          <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-5">
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

          {urlCampaign && sourceFilter !== "META_ADS" && (
            <div className="flex items-center gap-2 rounded-xl border border-primary/20 bg-primary-light/40 px-3 py-2 text-sm text-ink">
              Showing one ad campaign&apos;s people
              <button type="button" onClick={() => setUrlParam("ad_campaign_id", undefined)} className="ml-auto text-xs font-bold text-primary hover:underline">
                Show everyone ✕
              </button>
            </div>
          )}

          {/* Main card with filters and table */}
          <div className="rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
            {/* Phone: a big search box and wrapping interest chips. The filter bar below stays for everything else. */}
            <div className="space-y-2 border-b border-[#e2e8f0] p-3 md:hidden">
              <label className="relative block">
                <span className="sr-only">Search customers</span>
                <Search size={16} aria-hidden="true" className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-muted" />
                <input
                  type="search"
                  inputMode="search"
                  placeholder="Name, phone or what they asked for"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  className="h-10 w-full rounded-xl border border-border bg-white pl-10 pr-3 font-body text-base text-ink placeholder:text-ink-muted focus:outline-none focus:ring-2 focus:ring-primary/25"
                />
              </label>
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Interest">
                {PHONE_CHIPS.map((chip) => {
                  const on = status === chip.key;
                  return (
                    <button
                      key={chip.key}
                      type="button"
                      aria-pressed={on}
                      onClick={() => setStatus(chip.key)}
                      className={cn(
                        "h-8 rounded-full px-3 font-label text-[12.5px] font-bold transition-colors",
                        on ? "bg-navy text-white" : "bg-surface-mid text-ink-secondary",
                      )}
                    >
                      {chip.label}
                    </button>
                  );
                })}
                <button
                  type="button"
                  aria-expanded={phoneFiltersOpen}
                  onClick={() => setPhoneFiltersOpen((open) => !open)}
                  className={cn(
                    "ml-auto flex h-8 items-center gap-1 rounded-full border px-3 font-label text-[12.5px] font-bold",
                    phoneFiltersOpen ? "border-navy bg-navy text-white" : "border-border bg-white text-ink",
                  )}
                >
                  <SlidersHorizontal size={14} aria-hidden="true" />
                  {phoneFiltersOpen ? "Hide filters" : "Filters"}
                </button>
              </div>
            </div>

            {/* Filter bar: one line. On a phone it opens from the Filters button above. It wraps (never overlaps) only when the card is too narrow for
                every control, e.g. a small screen with the sidebar open and long filter values. */}
            <div className={cn("flex-wrap items-center gap-1.5 p-4 border-b border-[#e2e8f0] md:flex", phoneFiltersOpen ? "flex" : "hidden")}>
              {/* Search input */}
              <div className="relative hidden min-w-[120px] flex-1 md:block">
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
                  className="w-auto min-w-0 max-w-fit basis-[124px] grow gap-1.5 [&>span>span]:min-w-0 [&>span>span]:overflow-hidden pl-2.5 pr-2 text-xs font-bold text-[#0A1528]"
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
                  className="w-auto min-w-0 max-w-fit basis-[124px] grow gap-1.5 [&>span>span]:min-w-0 [&>span>span]:overflow-hidden pl-2.5 pr-2 text-xs font-bold text-[#0A1528]"
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

              {/* Leads only: people who never bought. */}
              <button
                type="button"
                aria-pressed={onlyLeads}
                onClick={() => setUrlParam("only", onlyLeads ? undefined : "leads")}
                title={onlyLeads ? "Showing people who never bought. Click to show everyone" : "Show only people who never bought"}
                className={cn(
                  "shrink-0 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-xs font-bold transition-colors",
                  onlyLeads ? "bg-primary text-white" : "border border-[#e2e8f0] bg-white text-[#0A1528] hover:border-slate-300",
                )}
              >
                Leads only
              </button>

              <FilterMenu
                label="Came from"
                options={CAME_FROM_OPTIONS}
                value={cameFrom ?? "all"}
                onChange={(val) => setUrlParam("came_from", val && val !== "all" ? val : undefined)}
                showValue={true}
              />

              {(tagCounts.length > 0 || tagFilter) && (
                <FilterMenu
                  label="Tag"
                  options={[
                    { value: "all", label: "All" },
                    ...(tagFilter && !tagCounts.some((t) => t.tag.toLowerCase() === tagFilter.toLowerCase())
                      ? [{ value: tagFilter, label: tagFilter }]
                      : []),
                    ...tagCounts.map((t) => ({ value: t.tag, label: t.count > 0 ? `${t.tag} (${t.count})` : t.tag })),
                  ]}
                  value={tagFilter ?? "all"}
                  onChange={(val) => setUrlParam("tag", val && val !== "all" ? val : undefined)}
                  showValue={true}
                />
              )}

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
                {canSaveAsGroup && (
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setSavingGroupOpen(!savingGroupOpen)}
                      title="Save these filters as a group that fills itself"
                      aria-label="Save these filters as a group"
                      aria-expanded={savingGroupOpen}
                      className="flex h-9 w-9 items-center justify-center rounded-xl border border-[#e2e8f0] bg-white text-[#0A1528] hover:bg-[#f8fafc] transition-colors"
                    >
                      <Bookmark size={14} />
                    </button>
                    {savingGroupOpen && (
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          saveFiltersAsGroup();
                        }}
                        className="absolute right-0 top-full z-30 mt-1 w-[280px] rounded-xl border border-[#e2e8f0] bg-white p-3 shadow-lg"
                      >
                        <p className="text-xs font-bold text-[#0A1528]">Save as a group</p>
                        <p className="mt-0.5 text-xs text-[#64748b]">
                          Everyone who matches these filters, now and later. It updates by itself.
                        </p>
                        <input
                          autoFocus
                          value={savedGroupName}
                          onChange={(e) => setSavedGroupName(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Escape") setSavingGroupOpen(false);
                          }}
                          maxLength={80}
                          placeholder="Group name"
                          aria-label="Group name"
                          className="mt-2 w-full rounded-lg border border-[#e2e8f0] px-2.5 py-1.5 text-xs text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary/20"
                        />
                        <button
                          type="submit"
                          disabled={!savedGroupName.trim()}
                          className="mt-2 w-full rounded-lg bg-primary px-2.5 py-1.5 text-xs font-bold text-white disabled:opacity-40"
                        >
                          Save group
                        </button>
                      </form>
                    )}
                  </div>
                )}
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
                        await downloadLeadsCsv(listFilters);
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
                {canManageLeads && (
                  <div ref={tagPopoverRef} className="relative">
                    <button
                      onClick={() => setTagPopoverOpen(!tagPopoverOpen)}
                      aria-expanded={tagPopoverOpen}
                      className="rounded-lg bg-white/10 px-3 py-1.5 text-xs font-bold hover:bg-white/20 transition-colors flex items-center gap-1.5"
                    >
                      <Tag size={12} />
                      Tag
                    </button>
                    {tagPopoverOpen && (
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          bulkTag("add");
                        }}
                        className="absolute top-full left-0 mt-1 z-30 w-[280px] max-w-[calc(100vw-2rem)] rounded-xl border border-[#e2e8f0] bg-white p-3 text-[#0A1528] shadow-lg"
                      >
                        <p className="text-xs font-bold">Tag {selectedIds.size} {selectedIds.size === 1 ? "person" : "people"}</p>
                        <input
                          autoFocus
                          value={tagInput}
                          onChange={(e) => setTagInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Escape") setTagPopoverOpen(false);
                          }}
                          maxLength={120}
                          placeholder="Type a tag, e.g. VIP"
                          aria-label="Tag"
                          className="mt-2 w-full rounded-lg border border-[#e2e8f0] px-2.5 py-1.5 text-xs text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary/20"
                        />
                        <p className="mt-1 text-xs text-[#556274]">Up to 30 letters. Use a comma for more than one. 10 tags at most per person.</p>
                        {tagCounts.length > 0 && (
                          <div className="mt-2 flex max-h-28 flex-wrap gap-1.5 overflow-y-auto">
                            {tagCounts.map((t) => (
                              <button
                                key={t.tag}
                                type="button"
                                onClick={() => setTagInput((cur) => parseTagInput(`${cur},${t.tag}`).join(", "))}
                                className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-200"
                              >
                                {t.tag}
                              </button>
                            ))}
                          </div>
                        )}
                        <div className="mt-3 flex gap-2">
                          <button
                            type="submit"
                            disabled={tagBusy || !tagInput.trim()}
                            className="flex-1 rounded-lg bg-primary px-2.5 py-1.5 text-xs font-bold text-white disabled:opacity-40"
                          >
                            Add tag
                          </button>
                          <button
                            type="button"
                            onClick={() => bulkTag("remove")}
                            disabled={tagBusy || !tagInput.trim()}
                            className="flex-1 rounded-lg border border-[#e2e8f0] px-2.5 py-1.5 text-xs font-bold text-[#0A1528] hover:bg-slate-50 disabled:opacity-40"
                          >
                            Remove tag
                          </button>
                        </div>
                      </form>
                    )}
                  </div>
                )}
                {canManageLeads && (
                  <button
                    onClick={bulkSendCampaign}
                    disabled={campaignBusy}
                    title="Saves these people as a group and opens Reach with it picked"
                    className="rounded-lg bg-white/10 px-3 py-1.5 text-xs font-bold hover:bg-white/20 transition-colors flex items-center gap-1.5 disabled:opacity-50"
                  >
                    <Megaphone size={12} />
                    {campaignBusy ? "Saving…" : "Send campaign"}
                  </button>
                )}
                {canManageLeads && (
                  <button
                    onClick={bulkSendToCalling}
                    disabled={callingBusy}
                    className="rounded-lg bg-white/10 px-3 py-1.5 text-xs font-bold hover:bg-white/20 transition-colors flex items-center gap-1.5 disabled:opacity-50"
                  >
                    <PhoneForwarded size={12} />
                    {callingBusy ? "Sending…" : "Send to calling"}
                  </button>
                )}
                {canManageLeads && (
                  <button
                    onClick={() => setConfirmSaidStop(true)}
                    className="rounded-lg bg-white/10 px-3 py-1.5 text-xs font-bold hover:bg-white/20 transition-colors flex items-center gap-1.5"
                  >
                    <BellOff size={12} />
                    Add to said stop
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
              ) : leads.length === 0 && firstDay ? (
                <FirstDayEmpty canImport={canImportList} canQr={canGetQr} />
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
                          onClick={() => router.push(`/dashboard/leads/${lead.id}`)}
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
                                  {avatar.text ?? <User size={16} aria-hidden="true" />}
                                </div>
                                <div
                                  className="h-3 w-3 rounded-full ring-2 ring-white absolute bottom-0 right-0"
                                  style={{ backgroundColor: channelDot.color }}
                                  title={channelDot.title}
                                />
                              </div>
                              <div className="min-w-0">
                                <div className="flex items-center gap-1.5 whitespace-nowrap font-bold text-sm text-[#0A1528]">
                                  {getPrimaryLine(lead)}
                                  {lead.opted_out && <SaidStopMark />}
                                </div>
                                {getSecondaryLine(lead) && (
                                  <div className="whitespace-nowrap text-xs text-[#64748b]">{getSecondaryLine(lead)}</div>
                                )}
                                <TagChips tags={lead.tags} onPick={(t) => setUrlParam("tag", t)} />
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
                              disabled={lead.opted_out}
                              title={lead.opted_out ? "They said stop: no offers or campaign messages go to them" : undefined}
                              className="whitespace-nowrap rounded-lg border border-primary px-3 py-1.5 text-xs font-bold text-primary hover:bg-primary/5 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400 disabled:hover:bg-transparent"
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

            {/* Mobile view: one slim row per person; "Details" opens everything the table shows. */}
            <div className="block p-3 md:hidden">
              {isLoading && !leads.length ? (
                <div className="p-8 text-center text-xs text-[#64748b]">Loading...</div>
              ) : leads.length === 0 && firstDay ? (
                <FirstDayEmpty canImport={canImportList} canQr={canGetQr} />
              ) : leads.length === 0 ? (
                <div className="p-8 text-center text-xs text-[#64748b]">No leads match these filters</div>
              ) : (
                <>
                  <label className="mb-1 flex min-h-11 items-center gap-3 px-1 font-body text-sm font-semibold text-ink-secondary">
                    <CheckTick
                      checked={selectedIds.size === leads.length && leads.length > 0}
                      indeterminate={selectedIds.size > 0 && selectedIds.size < leads.length}
                      onChange={(next) => setSelectedIds(next ? new Set(leads.map((l) => l.id)) : new Set())}
                      aria-label="Select all leads on this page"
                    />
                    Select all on this page
                  </label>
                  <ul className="space-y-2">
                    {leads.map((lead) => {
                      const seg = lead.broadcast_score?.segment ?? lead.segment;
                      const tint = PHONE_SEGMENT[seg] ?? "bg-slate-100 text-slate-600";
                      const name = lead.name || getPrimaryLine(lead);
                      const isSelected = selectedIds.has(lead.id);
                      const isOpen = expandedId === lead.id;
                      const line = [
                        sourceLabel(lead.source),
                        lead.came_from || null,
                        lead.last_activity_at ? timeAgo(lead.last_activity_at) : null,
                      ]
                        .filter(Boolean)
                        .join(" · ");
                      return (
                        <li
                          key={lead.id}
                          className={cn(
                            "rounded-2xl border bg-white",
                            isSelected ? "border-primary bg-primary-light/40" : "border-border",
                          )}
                        >
                          <div className="flex items-center gap-3 p-3">
                            <button
                              type="button"
                              aria-label={`Select ${name}`}
                              aria-pressed={isSelected}
                              onClick={() => {
                                const next = new Set(selectedIds);
                                if (isSelected) next.delete(lead.id);
                                else next.add(lead.id);
                                setSelectedIds(next);
                              }}
                              className={cn(
                                "flex h-11 w-11 shrink-0 items-center justify-center rounded-full font-display text-sm font-bold",
                                isSelected ? "bg-primary text-white" : tint,
                              )}
                            >
                              {isSelected ? <Check size={18} aria-hidden="true" /> : (getAvatarInitials(lead).text ?? <User size={18} aria-hidden="true" />)}
                            </button>
                            <div className="min-w-0 flex-1">
                              <button
                                type="button"
                                onClick={() => router.push(`/dashboard/leads/${lead.id}`)}
                                className="block w-full min-w-0 text-left"
                              >
                                <span className="flex min-w-0 items-center gap-1.5">
                                  <span className="min-w-0 truncate font-body text-sm font-bold text-ink">{name}</span>
                                  <span className={cn("shrink-0 rounded-full px-2 py-0.5 font-label text-[10px] font-bold", tint)}>
                                    {SEGMENT_LABELS[seg] ?? seg}
                                  </span>
                                </span>
                                <span className="mt-0.5 block truncate font-body text-xs text-ink-muted">{line || "—"}</span>
                              </button>
                              <button
                                type="button"
                                aria-expanded={isOpen}
                                onClick={() => setExpandedId(isOpen ? null : lead.id)}
                                className="relative mt-1 inline-flex items-center gap-1 font-label text-xs font-bold text-primary before:absolute before:-inset-x-2 before:-inset-y-3.5 before:content-['']"
                              >
                                {isOpen ? "Hide details" : "Details"}
                                <ChevronDown size={14} aria-hidden="true" className={cn("transition-transform", isOpen && "rotate-180")} />
                              </button>
                            </div>
                            {lead.phone && (
                              <a
                                href={`tel:${lead.phone.replace(/[\s()-]/g, "")}`}
                                aria-label={`Call ${name}`}
                                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary text-white"
                              >
                                <Phone size={18} aria-hidden="true" />
                              </a>
                            )}
                          </div>
                          {isOpen && (
                            <div className="border-t border-border p-3">
                              {lead.opted_out && <div className="mb-2"><SaidStopMark /></div>}
                              <MobileRecordGrid className="mt-0">
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
                                {(lead.tags?.length ?? 0) > 0 && (
                                  <MobileRecordField label="Tags" value={<TagChips tags={lead.tags} onPick={(t) => setUrlParam("tag", t)} />} className="col-span-2" />
                                )}
                              </MobileRecordGrid>
                              <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
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
                                <button
                                  type="button"
                                  onClick={() => setSendTemplateLeadId(lead.id)}
                                  disabled={lead.opted_out}
                                  title={lead.opted_out ? "They said stop: no offers or campaign messages go to them" : undefined}
                                  className="min-h-11 whitespace-nowrap rounded-xl border border-primary px-4 text-xs font-bold text-primary hover:bg-primary/5 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
                                >
                                  Send template
                                </button>
                              </div>
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </>
              )}
            </div>

            {/* Pagination */}
            {!isLoading && leads.length > 0 && (
              <Pagination page={page} total={totalLeads} pageSize={PAGE_SIZE} onPageChange={setPage} noun={listName} className="max-md:[&_button]:min-h-11 max-md:[&_button]:min-w-11" />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
