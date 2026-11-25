import { useState, useRef, useEffect, Fragment } from "react";
import { api, Lead } from "@/lib/api";
import { ChannelAvatar, CHANNEL_LABEL, getChannel } from "./channel-avatar";
import { PhoneAvatar, SegmentChip } from "./chats/PhoneAvatar";
import { formatConvoTime, formatPhone, cn, stripMarkdown } from "@/lib/utils";
import { Trash2, MoreVertical, MoreHorizontal, Search, X, SearchX, Pin, RefreshCw, Archive, Ban, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { CheckTick } from "@/components/ui/controls";
import { AiraLoader } from "@/components/AiraLoader";
import { formatRupees } from "./deals/money";
import { ChatFilterPopover } from "./chats/ChatFilterPopover";
import { SaveGroupDialog } from "./chats/SaveGroupDialog";
import { NotificationBell } from "./NotificationBell";
import {
  activeFilterCount,
  filterPills,
  type InboxChannel,
  type InboxCounts,
  type InboxFilters,
  type InboxView,
  type Option,
} from "./chats/inboxFilters";

type ConversationLead = Lead & { last_reply_at?: string };

interface Props {
  leads: Lead[];
  selectedId: string | null;
  onSelect: (lead: Lead) => void;
  onDeleted?: (ids: string[]) => void;
  view: InboxView;
  onViewChange: (view: InboxView) => void;
  channel: InboxChannel;
  onChannelChange: (channel: InboxChannel) => void;
  counts: InboxCounts;
  filters: InboxFilters;
  onFiltersChange: (filters: InboxFilters) => void;
  /** Exact server count for a draft of the filters (the Filter panel's "Show N chats"). */
  countFor: (draft: InboxFilters) => Promise<number>;
  team: Option[];
  tags: Option[];
  searchQuery: string;
  onSearchChange: (query: string) => void;
  onPin?: (id: string) => void;
  onRefresh?: () => void;
  onArchive?: (id: string) => void;
  canArchive?: boolean;
  onBlock?: (id: string) => void;
  hasMore?: boolean;
  loadingMore?: boolean;
  /** True until the first answer for this tab arrives, so the empty state is not shown too early. */
  loading?: boolean;
  onLoadMore?: () => void;
  /** Open handovers, for the Needs you tab's badge. */
  escalationCount?: number;
  /** A full-width page shown under the tabs (Needs you, Archived, Blocked). */
  fullPageContent?: React.ReactNode;
  /** Saves everyone the current tab, search and filters match as a group. Absent = no button (no leads.manage). */
  onSaveAsGroup?: (name: string) => Promise<void>;
  /** How many chats the current tab, search and filters match (the list's total). */
  matchTotal?: number;
}

/** Tabs that fold into the header menu on a phone, so the tab row stays one short line. */
const PHONE_MENU_TABS: ReadonlySet<string> = new Set(["archived", "blocked"]);

const CHANNEL_CHIPS: { value: InboxChannel; label: string; dot?: string }[] = [
  { value: "all", label: "All" },
  { value: "whatsapp", label: "WA", dot: "bg-primary" },
  { value: "instagram", label: "IG", dot: "bg-[#E1306C]" },
  { value: "facebook", label: "FB", dot: "bg-[#1877F2]" },
  { value: "telegram", label: "TG", dot: "bg-[#229ED9]" },
];

const SECTION_TITLE: Record<number, string> = {
  0: "Needs you · oldest first",
  1: "AI agent is handling",
  2: "Your team is handling",
};

/** Hover text for a red time: "Waiting 5 minutes", "Waiting 3 hours", "Waiting 35 days". */
function waitingTitle(since: string): string {
  const mins = Math.max(0, Math.floor((Date.now() - new Date(since).getTime()) / 60000));
  const plural = (n: number, unit: string) => `Waiting ${n} ${unit}${n === 1 ? "" : "s"} for a reply`;
  if (mins < 60) return plural(Math.max(1, mins), "minute");
  const hours = Math.floor(mins / 60);
  if (hours < 24) return plural(hours, "hour");
  return plural(Math.floor(hours / 24), "day");
}

/** Tab badges stay one short pill so the tab row never has to scroll. */
function tabCount(n: number): string {
  return n > 999 ? "999+" : n.toLocaleString("en-IN");
}

export function ConversationList(props: Props) {
  const {
    leads, selectedId, onSelect, onDeleted, view, onViewChange, channel, onChannelChange, counts, filters,
    onFiltersChange, countFor, team, tags, searchQuery, onSearchChange, onPin, onRefresh, onArchive,
    canArchive = false, onBlock, hasMore = false, loadingMore = false, loading = false, onLoadMore,
    escalationCount = 0, fullPageContent, onSaveAsGroup, matchTotal,
  } = props;
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selectionMode, setSelectionMode] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);
  const [saveGroupOpen, setSaveGroupOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [cardMenuId, setCardMenuId] = useState<string | null>(null);

  const menuRef = useRef<HTMLDivElement>(null);
  const filterCount = activeFilterCount(filters);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
      if (!(event.target as HTMLElement).closest?.("[data-card-menu]")) {
        setCardMenuId(null);
      }
    }
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuOpen(false);
        setCardMenuId(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  async function handleDeleteOne(id: string) {
    setCardMenuId(null);
    try {
      await api.leads.delete(id);
      onDeleted?.([id]);
    } catch {
      toast.error("Failed to delete chat");
    }
  }

  function toggleSelect(id: string, e?: React.MouseEvent) {
    e?.stopPropagation();
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedIds(next);
  }

  function handleRefresh() {
    if (!onRefresh || isRefreshing) return;
    setIsRefreshing(true);
    onRefresh();
    setTimeout(() => setIsRefreshing(false), 900);
  }

  const tabs: { id: InboxView; label: string; count?: number; urgent?: boolean }[] = [
    // No number on Inbox: the "All" channel chip right under it already shows it.
    { id: "inbox", label: "Inbox" },
    { id: "ai_handling", label: "AI handling", count: counts.ai_handling },
    { id: "needs_you", label: "Needs you", count: escalationCount, urgent: true },
    { id: "archived", label: "Archived" },
    { id: "blocked", label: "Blocked" },
  ];
  const showSections = view === "inbox";
  const anyNarrowing = Boolean(searchQuery) || filterCount > 0 || channel !== "all";

  // The full-width Needs you page keeps its original header and left-aligned tabs; the narrow
  // chat list uses the 68px band (level with the chat header) and tabs locked to its width.
  const fullScreen = (view === "needs_you" || view === "archived" || view === "blocked") && Boolean(fullPageContent);

  const headerAndTabs = (
    <>
      {/* ── Header ── */}
      <div className={cn(
        "shrink-0 px-4",
        fullScreen ? "pt-4 pb-2" : "flex h-14 items-center border-b border-[#e2e8f0] md:h-[68px]"
      )}>
        <div className="flex w-full items-center justify-between">
          <h2 className="font-display text-[19px] font-bold text-[#0A1528]">
            <span className="md:hidden">Chats</span>
            <span className="hidden md:inline">Conversations</span>
          </h2>
          <div className="flex items-center gap-1">
            {/* Chats has no top bar, so search and alerts live here (the top bar has them on every other page). */}
            <NotificationBell />
            {!fullScreen && (
              <div className="relative" ref={menuRef}>
                <button onClick={() => setMenuOpen(!menuOpen)} aria-label="More" className="flex h-11 w-11 items-center justify-center rounded-md hover:bg-slate-100 text-slate-500 hover:text-slate-700 transition-colors md:h-auto md:w-auto md:p-1.5">
                  <MoreVertical size={18} />
                </button>
                {menuOpen && (
                  <div className="absolute right-0 top-full mt-1 w-40 md:w-36 bg-white border border-slate-200 rounded-xl shadow-xl overflow-hidden z-20 py-1.5">
                    <button onClick={() => { setSelectionMode(true); setMenuOpen(false); }} className="w-full text-left px-4 py-3 md:py-2 text-[13px] font-medium text-slate-700 hover:bg-slate-50 transition-colors">
                      Select chats
                    </button>
                    <button onClick={() => { setSelectionMode(true); setSelectedIds(new Set(leads.map(l => l.id))); setMenuOpen(false); }} className="w-full text-left px-4 py-3 md:py-2 text-[13px] font-medium text-slate-700 hover:bg-slate-50 transition-colors">
                      Select all
                    </button>
                    {/* Phone: Archived and Blocked live here instead of taking a second row of tabs. */}
                    {tabs.filter((t) => PHONE_MENU_TABS.has(t.id)).map((t) => (
                      <button
                        key={t.id}
                        onClick={() => { onViewChange(t.id); setMenuOpen(false); }}
                        className="w-full border-t border-slate-100 px-4 py-3 text-left text-[13px] font-medium text-slate-700 hover:bg-slate-50 md:hidden"
                      >
                        {t.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Tabs row ── */}
      <div
        className={cn(
          "flex shrink-0 items-center gap-1.5 overflow-x-auto border-b border-[#e2e8f0] px-4 py-2 [scrollbar-width:none] md:gap-2 md:py-0 [&::-webkit-scrollbar]:hidden",
          fullScreen ? "md:gap-4" : "md:justify-between md:gap-2 md:overflow-x-auto"
        )}
        role="tablist"
      >
        {tabs.map((tab) => {
          const isActive = view === tab.id;
          return (
            <button
              key={tab.id}
              role="tab"
              aria-selected={isActive}
              onClick={() => onViewChange(tab.id)}
              className={cn(
                "relative h-8 shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-3 text-[12.5px] font-semibold transition-colors md:flex md:h-auto md:gap-1.5 md:rounded-none md:px-0 md:py-3 md:text-[12px]",
                // On the Archived / Blocked pages the header menu is not shown, so both stay as tabs there.
                PHONE_MENU_TABS.has(tab.id) && !isActive && !fullScreen ? "hidden" : "flex",
                isActive
                  ? "bg-[#0A1528] text-white md:bg-transparent md:text-primary"
                  : "bg-slate-100 text-[#334155] md:bg-transparent md:text-[#64748b] md:hover:text-[#0A1528]"
              )}
            >
              {tab.label}
              {tab.count !== undefined && tab.count > 0 && (
                <span className={cn(
                  "rounded-full px-1.5 text-[10.5px] font-bold leading-4 md:py-0.5 md:text-[9px]",
                  tab.urgent
                    ? "bg-rose-800 text-white md:bg-red-50 md:text-red-600"
                    : isActive
                      ? "bg-white/20 text-white md:bg-primary-light md:text-primary"
                      : "bg-white text-primary md:bg-primary-light"
                )}>
                  {tabCount(tab.count)}
                </span>
              )}
              {isActive && <div className="absolute bottom-0 inset-x-0 hidden h-0.5 bg-primary md:block" />}
            </button>
          );
        })}
      </div>

    </>
  );

  // Needs you / Archived / Blocked: a full-width page under the same header and tabs.
  if (fullScreen) {
    return (
      <div className="w-full flex-shrink-0 bg-white flex flex-col h-full z-10 relative">
        {headerAndTabs}
        {/* A bounded flex column, so the panel's table area is what scrolls. */}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{fullPageContent}</div>
      </div>
    );
  }

  return (
    <div className="w-full flex-shrink-0 bg-white flex flex-col h-full z-10 relative">
      {headerAndTabs}
      {/* ── Channel chips: each shows its own count under the current tab and filters ── */}
      <div className="mx-4 mt-2 flex flex-wrap gap-1.5 md:mt-3 md:gap-1">
        {CHANNEL_CHIPS.filter((c) => c.value === "all" || c.value === channel || (counts.channels[c.value] ?? 0) > 0).map((chip) => {
          const active = channel === chip.value;
          const n = counts.channels[chip.value];
          return (
            <button
              key={chip.value}
              onClick={() => onChannelChange(chip.value)}
              aria-pressed={active}
              className={cn(
                "inline-flex h-7 items-center gap-1 rounded-full border px-2.5 text-[12px] font-semibold whitespace-nowrap transition-all md:h-auto md:px-2 md:py-1 md:text-[10.5px]",
                active
                  ? "bg-primary-light text-primary border-primary/30"
                  : "bg-white text-[#334155] border-[#e2e8f0] hover:border-slate-300"
              )}
            >
              {chip.dot && <span className={cn("h-1.5 w-1.5 rounded-full", chip.dot)} />}
              {chip.label}
              {n !== undefined && <span className={active ? "text-primary/80" : "text-[#94a3b8]"}>{n.toLocaleString("en-IN")}</span>}
            </button>
          );
        })}
      </div>

      {/* ── Search + Filter ── */}
      <div className="relative mx-4 mt-2 flex gap-1.5 md:mt-2.5 md:gap-2">
        <div className="relative flex-1 group">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-primary transition-colors" />
          <input
            type="text"
            placeholder="Search name or phone"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full pl-9 pr-16 md:pr-12 py-2 bg-white border border-[#e2e8f0] rounded-xl text-[16px] md:text-[12.5px] text-slate-700 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all h-10 md:h-9"
          />
          {searchQuery && (
            <button onClick={() => onSearchChange("")} aria-label="Clear search" className="absolute right-10 md:right-7 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 p-1.5 md:p-0.5 rounded-full hover:bg-slate-100 transition-colors">
              <X size={14} />
            </button>
          )}
          <button
            onClick={handleRefresh}
            title="Refresh"
            aria-label="Refresh"
            disabled={isRefreshing}
            className="absolute right-1 md:right-1.5 top-1/2 -translate-y-1/2 p-2.5 md:p-1 text-slate-400 hover:text-slate-600 transition-colors disabled:opacity-60"
          >
            <RefreshCw size={14} className={isRefreshing ? "animate-spin" : ""} />
          </button>
        </div>
        <button
          type="button"
          data-filter-trigger
          onClick={() => setFilterOpen((o) => !o)}
          aria-expanded={filterOpen}
          aria-label={filterCount > 0 ? `Filter, ${filterCount} on` : "Filter"}
          className={cn(
            "relative inline-flex h-10 w-10 shrink-0 items-center justify-center gap-1.5 rounded-xl border text-[12.5px] font-semibold transition-colors md:h-9 md:w-auto md:px-3",
            filterCount > 0 || filterOpen
              ? "border-primary/40 bg-primary-light text-primary"
              : "border-[#e2e8f0] bg-white text-[#334155] hover:border-slate-300"
          )}
        >
          <SlidersHorizontal size={14} aria-hidden />
          <span className="sr-only md:not-sr-only">Filter</span>
          {filterCount > 0 && (
            <span className="absolute -right-1 -top-1 rounded-full bg-primary px-1.5 py-px text-[10px] font-bold leading-4 text-white md:static">{filterCount}</span>
          )}
        </button>
        <ChatFilterPopover
          open={filterOpen}
          value={filters}
          onClose={() => setFilterOpen(false)}
          onChange={onFiltersChange}
          countFor={countFor}
          team={team}
          tags={tags}
          onSaveAsGroup={onSaveAsGroup ? () => { setFilterOpen(false); setSaveGroupOpen(true); } : undefined}
        />
        {onSaveAsGroup && (
          <SaveGroupDialog
            open={saveGroupOpen}
            matchCount={loading ? null : matchTotal ?? null}
            onClose={() => setSaveGroupOpen(false)}
            onSave={async (name) => { await onSaveAsGroup(name); setSaveGroupOpen(false); }}
          />
        )}
      </div>

      {/* ── Active filters: one click on × removes one, no need to open the panel ── */}
      {filterCount > 0 && (
        <div className="mx-4 mt-2 flex flex-wrap items-center gap-1.5">
          {filterPills(filters, team, tags).map((pill) => (
            <span key={pill.id} className="inline-flex h-6 items-center gap-0.5 rounded-full bg-primary-light pl-2.5 pr-1 text-[11.5px] font-semibold text-primary">
              {pill.label}
              <button
                type="button"
                onClick={() => onFiltersChange(pill.without)}
                aria-label={`Remove ${pill.label}`}
                className="flex h-5 w-5 items-center justify-center rounded-full hover:bg-primary/15"
              >
                <X size={12} strokeWidth={2.5} />
              </button>
            </span>
          ))}
          <button
            type="button"
            onClick={() => onFiltersChange({ segments: [], results: [], cameFrom: [], handledBy: [], waiting: [], date: "any", customFrom: "", tagId: "" })}
            className="h-6 rounded-full px-2 text-[11.5px] font-semibold text-[#64748b] hover:bg-slate-100 hover:text-[#0A1528]"
          >
            Clear
          </button>
        </div>
      )}

      {/* ── Conversation list ── */}
      <div className="mt-2.5 min-h-0 flex-1 overflow-y-auto border-t border-[#f1f5f9]">
        {loading ? (
          <AiraLoader inline className="min-h-[200px] h-full" />
        ) : leads.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-6 py-10 text-slate-500 space-y-3 animate-in fade-in duration-300">
            <div className="w-14 h-14 rounded-2xl bg-slate-100 border border-slate-200 flex items-center justify-center shadow-sm">
              <SearchX size={24} className="text-slate-400 opacity-60" />
            </div>
            <div>
              <p className="font-display font-semibold text-[15px] text-slate-700">
                {anyNarrowing ? "No chats match" : "No chats here"}
              </p>
              <p className="text-[13px] mt-1.5 leading-relaxed">
                {anyNarrowing ? "Try fewer filters or a different search." : "New chats show up here as they come in."}
              </p>
            </div>
            {anyNarrowing && (
              <button
                onClick={() => {
                  onSearchChange("");
                  onChannelChange("all");
                  onFiltersChange({ ...filters, segments: [], results: [], cameFrom: [], handledBy: [], waiting: [], date: "any", customFrom: "", tagId: "" });
                }}
                className="mt-3 text-[13px] font-semibold text-primary hover:underline"
              >
                Clear all filters
              </button>
            )}
          </div>
        ) : (
          leads.map((lead, i) => {
            const group = lead.inbox_group ?? 1;
            const prevGroup = i > 0 ? leads[i - 1].inbox_group ?? 1 : null;
            const isBot = lead.last_message_direction === "outbound" && lead.last_message_is_ai === true;
            const preview = stripMarkdown(lead.last_message_content) || (lead.phone ? formatPhone(lead.phone) : "No messages yet");
            const needsYou = group === 0;
            const aiHandling = group === 1;
            const customerWaiting = lead.last_message_direction === "inbound";
            const waitingSince = needsYou ? lead.waiting_since : null;
            const unread = lead.unread_count ?? 0;
            const wants = lead.wants && (lead.wants.items || lead.wants.total_paise)
              ? [lead.wants.items, lead.wants.total_paise ? formatRupees(lead.wants.total_paise) : ""].filter(Boolean).join(" · ")
              : "";
            const line2 = needsYou
              ? `🙋 ${lead.needs_reason || "Waiting for your reply"}`
              : aiHandling
                ? customerWaiting ? "🤖 AI agent is replying" : `🤖 ${preview}`
                : `${isBot ? "AI: " : ""}${preview}`;
            return (
              <Fragment key={lead.id}>
                {showSections && group !== prevGroup && (
                  <div className={cn(
                    "sticky top-0 z-[1] border-b border-[#f1f5f9] bg-white/95 px-4 py-1.5 font-label text-[10px] font-bold uppercase tracking-[0.08em] backdrop-blur",
                    needsYou ? "text-red-600" : "text-[#64748b]"
                  )}>
                    {SECTION_TITLE[group]}
                  </div>
                )}
                {/* Phone row: 46px avatar, name + time, one preview line, chips. Hidden from md up. */}
                <div
                  onClick={() => onSelect(lead)}
                  onKeyDown={(e) => { if (e.key === "Enter") onSelect(lead); }}
                  role="button"
                  tabIndex={0}
                  className={cn(
                    "relative flex min-h-[72px] w-full cursor-pointer items-start gap-3 border-b border-[#f1f5f9] px-4 py-3 text-left active:bg-slate-50 md:hidden",
                    selectedId === lead.id && "bg-primary-light/50"
                  )}
                >
                  {selectionMode && (
                    <div className="shrink-0 self-center" onClick={(e) => e.stopPropagation()}>
                      <CheckTick
                        checked={selectedIds.has(lead.id)}
                        onChange={() => toggleSelect(lead.id)}
                        size="sm"
                        aria-label="Select conversation"
                      />
                    </div>
                  )}
                  <PhoneAvatar name={lead.name} segment={lead.segment} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex min-w-0 items-center gap-1">
                        <span className="truncate font-display text-[15px] font-bold text-ink">
                          {lead.name || formatPhone(lead.phone) || "Unknown"}
                        </span>
                        {lead.pinned_at && <Pin size={11} className="shrink-0 fill-current text-amber-500" aria-label="Pinned" />}
                      </span>
                      <span className={cn("shrink-0 whitespace-nowrap text-[11.5px]", waitingSince || needsYou ? "font-bold text-rose-700" : "text-ink-muted")}>
                        {formatConvoTime((lead as ConversationLead).last_reply_at || lead.created_at)}
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-2">
                      <p className={cn("min-w-0 flex-1 truncate text-[13.5px]", unread > 0 ? "font-semibold text-ink" : "text-ink-secondary")}>
                        {lead.last_message_direction === "outbound" && (isBot ? "Anril: " : "You: ")}
                        {preview}
                      </p>
                      {unread > 0 && (
                        <span className="min-w-[20px] shrink-0 rounded-full bg-primary px-1.5 text-center text-[11px] font-bold leading-5 text-white" aria-label={`${unread} unread`}>
                          {unread > 98 ? "99+" : unread}
                        </span>
                      )}
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1">
                      <SegmentChip segment={lead.segment} />
                      {needsYou && (
                        <span className="inline-flex shrink-0 items-center rounded-full bg-rose-800 px-2 py-0.5 text-[10.5px] font-bold leading-4 text-white">Needs you</span>
                      )}
                      {aiHandling && (
                        <span className="inline-flex shrink-0 items-center rounded-full bg-primary-light px-2 py-0.5 text-[10.5px] font-bold leading-4 text-primary-900">Anril replying</span>
                      )}
                      <span className="inline-flex shrink-0 items-center rounded-full bg-slate-100 px-2 py-0.5 text-[10.5px] font-semibold leading-4 text-ink-secondary">
                        {CHANNEL_LABEL[getChannel(lead.source)]}
                      </span>
                    </div>
                  </div>
                  <div className="relative shrink-0" data-card-menu onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => setCardMenuId(cardMenuId === lead.id ? null : lead.id)}
                      aria-label="Chat options"
                      className="-mr-2 flex h-11 w-11 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100"
                    >
                      <MoreHorizontal size={18} />
                    </button>
                    {cardMenuId === lead.id && (
                      <div className="absolute right-0 top-full z-50 mt-1 w-44 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-xl">
                        {onPin && (
                          <button
                            onClick={() => { setCardMenuId(null); onPin(lead.id); }}
                            className="flex min-h-11 w-full items-center gap-2 px-3 text-left text-[13px] text-slate-700 hover:bg-slate-50"
                          >
                            <Pin size={14} className="text-slate-500" />
                            {lead.pinned_at ? "Unpin" : "Pin"}
                          </button>
                        )}
                        {onArchive && (
                          <button
                            onClick={() => { setCardMenuId(null); onArchive(lead.id); }}
                            disabled={!canArchive}
                            className="flex min-h-11 w-full items-center gap-2 px-3 text-left text-[13px] text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            <Archive size={14} className="text-slate-500" />
                            Archive
                          </button>
                        )}
                        {onBlock && (
                          <button onClick={() => { setCardMenuId(null); onBlock(lead.id); }} className="flex min-h-11 w-full items-center gap-2 px-3 text-left text-[13px] text-slate-700 hover:bg-slate-50">
                            <Ban size={14} className="text-slate-500" />
                            Block
                          </button>
                        )}
                        <button onClick={() => handleDeleteOne(lead.id)} className="flex min-h-11 w-full items-center gap-2 px-3 text-left text-[13px] text-red-600 hover:bg-red-50">
                          <Trash2 size={14} /> Delete
                        </button>
                      </div>
                    )}
                  </div>
                </div>
                <div
                  onClick={() => onSelect(lead)}
                  onKeyDown={(e) => { if (e.key === "Enter") onSelect(lead); }}
                  role="button"
                  tabIndex={0}
                  className={cn(
                    "hidden w-full text-left px-4 py-3 border-b border-[#f1f5f9] transition-all duration-150 group md:flex items-start gap-3 relative cursor-pointer",
                    selectedId === lead.id
                      ? "bg-primary-light/50 before:absolute before:left-0 before:top-0 before:bottom-0 before:w-[3px] before:bg-primary"
                      : "hover:bg-[#f8fafc]"
                  )}
                >
                  {selectionMode && (
                    <div className="pt-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
                      <CheckTick
                        checked={selectedIds.has(lead.id)}
                        onChange={() => toggleSelect(lead.id)}
                        size="sm"
                        aria-label="Select conversation"
                      />
                    </div>
                  )}

                  <ChannelAvatar source={lead.source} size={36} />

                  <div className="flex-1 min-w-0">
                    {/* Line 1: name, interest, wait / time */}
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span className="text-[13px] font-bold text-[#0A1528] truncate">
                          {lead.name || formatPhone(lead.phone) || "Unknown"}
                        </span>
                        {lead.segment === "A" && (
                          <span className="shrink-0 rounded-md px-1.5 py-[3px] text-[10px] font-bold leading-none bg-orange-50 text-orange-600">🔥 Hot</span>
                        )}
                        {lead.segment === "B" && (
                          <span className="shrink-0 rounded-md px-1.5 py-[3px] text-[10px] font-bold leading-none bg-amber-50 text-amber-700">Warm</span>
                        )}
                        {lead.segment === "C" && (
                          <span className="shrink-0 rounded-md px-1.5 py-[3px] text-[10px] font-bold leading-none bg-blue-50 text-blue-600">Cold</span>
                        )}
                        {onPin ? (
                          <button
                            onClick={(e) => { e.stopPropagation(); onPin(lead.id); }}
                            aria-label={lead.pinned_at ? "Unpin" : "Pin"}
                            className={cn(
                              "shrink-0 p-0.5 rounded transition-all",
                              lead.pinned_at
                                ? "text-amber-500 opacity-100 hover:text-amber-700"
                                : "opacity-0 group-hover:opacity-100 text-slate-400 hover:text-amber-500"
                            )}
                          >
                            <Pin size={10} className={lead.pinned_at ? "fill-current" : ""} />
                          </button>
                        ) : lead.pinned_at ? (
                          <Pin size={10} className="text-amber-500 fill-current shrink-0" />
                        ) : null}
                      </div>
                      {/* One format everywhere: when the last message came. Red = the customer is waiting. */}
                      <span
                        className={cn("text-[10.5px] whitespace-nowrap", waitingSince ? "font-bold text-red-600" : "text-[#94a3b8]")}
                        title={waitingSince ? waitingTitle(waitingSince) : undefined}
                      >
                        {formatConvoTime((lead as ConversationLead).last_reply_at || lead.created_at)}
                      </span>
                    </div>

                    {/* Line 2: why it needs you / who is handling + unread */}
                    <div className="flex items-center gap-2 mb-1.5">
                      <p className={cn(
                        "min-w-0 flex-1 text-[12px] truncate",
                        needsYou ? "font-semibold text-amber-800" : unread > 0 ? "font-semibold text-[#0A1528]" : "text-[#64748b]"
                      )}>
                        {line2}
                      </p>
                      {unread > 0 && (
                        <span className="shrink-0 rounded-full bg-primary px-1.5 text-[10px] font-bold leading-[16px] text-white min-w-[16px] text-center" aria-label={`${unread} unread`}>
                          {unread > 98 ? "99+" : unread}
                        </span>
                      )}
                    </div>

                    {/* Line 3: what they want and the result -- one line, never wraps */}
                    <div className="flex h-[19px] gap-1.5 overflow-hidden">
                      {wants && (
                        <span className="min-w-0 truncate rounded-md px-1.5 py-0.5 text-[10px] font-semibold bg-slate-50 text-[#475569]">
                          {wants}
                        </span>
                      )}
                      {lead.converted_at || lead.wants?.stage === "won" ? (
                        <span className="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold bg-emerald-50 text-emerald-700">Came / Paid</span>
                      ) : lead.lost_at ? (
                        <span className="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold bg-slate-100 text-slate-600">Not buying</span>
                      ) : lead.booked_at ? (
                        <span className="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold bg-sky-50 text-sky-700">Booked</span>
                      ) : null}
                      {lead.segment === "D" && (
                        <span className="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold bg-slate-100 text-slate-500">Not interested</span>
                      )}
                      {lead.opted_out && (
                        <span className="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold bg-slate-100 text-slate-700">STOP</span>
                      )}
                      {lead.blocked_at && (
                        <span className="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold bg-slate-100 text-slate-700">BLOCKED</span>
                      )}
                    </div>
                  </div>

                  {/* Per-item menu */}
                  <div className="relative shrink-0" data-card-menu onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => setCardMenuId(cardMenuId === lead.id ? null : lead.id)}
                      aria-label="Chat options"
                      className="rounded-md p-1 text-slate-400 transition-all hover:bg-slate-200 md:opacity-0 md:group-hover:opacity-100"
                    >
                      <MoreHorizontal size={16} />
                    </button>
                    {cardMenuId === lead.id && (
                      <div className="absolute right-0 top-full mt-1 w-40 bg-white border border-slate-200 rounded-xl shadow-xl overflow-hidden z-50 py-1">
                        {onArchive && (
                          <button
                            onClick={() => { setCardMenuId(null); onArchive(lead.id); }}
                            disabled={!canArchive}
                            title={canArchive ? undefined : "You have read-only access to conversations"}
                            className="w-full flex items-center gap-2 px-3 py-2 text-left text-[12.5px] text-slate-700 hover:bg-slate-50 transition-colors disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
                          >
                            <Archive size={14} className="text-slate-500" />
                            Archive
                          </button>
                        )}
                        {onBlock && (
                          <button onClick={() => { setCardMenuId(null); onBlock(lead.id); }} className="w-full flex items-center gap-2 px-3 py-2 text-left text-[12.5px] text-slate-700 hover:bg-slate-50 transition-colors">
                            <Ban size={14} className="text-slate-500" />
                            Block
                          </button>
                        )}
                        <button onClick={() => handleDeleteOne(lead.id)} className="w-full flex items-center gap-2 px-3 py-2 text-left text-[12.5px] text-red-600 hover:bg-red-50 transition-colors">
                          <Trash2 size={14} /> Delete
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </Fragment>
            );
          })
        )}
        {hasMore && !loading && (
          <div className="p-3">
            <button
              onClick={onLoadMore}
              disabled={loadingMore}
              className="w-full rounded-xl border border-[#e2e8f0] py-2.5 text-center text-[12px] font-bold text-primary hover:bg-[#f8fafc] transition-colors disabled:opacity-50"
            >
              {loadingMore ? "Loading…" : "Load more conversations"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
