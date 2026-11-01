import { useState, useRef, useEffect, useMemo } from "react";
import { api, Lead } from "@/lib/api";
import { ChannelAvatar, getChannel } from "./channel-avatar";
import { formatConvoTime, formatPhone, cn } from "@/lib/utils";
import { Trash2, MoreVertical, MoreHorizontal, Search, X, SearchX, Pin, RefreshCw, Archive, Ban, Flag, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { CheckTick } from "@/components/ui/controls";

type ConversationLead = Lead & { last_reply_at?: string };

/** The inbox tabs. */
export type InboxFolder = "chats" | "escalations" | "archived" | "blocked";

interface Props {
  leads: Lead[];
  selectedId: string | null;
  onSelect: (lead: Lead) => void;
  onDeleted?: (ids: string[]) => void;
  platform: string;
  onPlatformChange: (platform: string) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  onPin?: (id: string) => void;
  onPinSelected?: (ids: string[]) => void;
  onRefresh?: () => void;
  onArchive?: (id: string) => void;
  canArchive?: boolean;
  onBlock?: (id: string) => void;
  folder?: InboxFolder;
  onFolderChange?: (folder: InboxFolder) => void;
  escalationCount?: number;
  total?: number;
  hasMore?: boolean;
  loadingMore?: boolean;
  onLoadMore?: () => void;
  escalationPanelContent?: React.ReactNode;
}

export function ConversationList(props: Props) {
  const { leads, selectedId, onSelect, onDeleted, platform, onPlatformChange, searchQuery, onSearchChange, onPin, onRefresh, onArchive, canArchive = false, onBlock, folder = "chats", onFolderChange, escalationCount = 0, total = 0, hasMore = false, loadingMore = false, onLoadMore, escalationPanelContent } = props;
  const [filterMode, setFilterMode] = useState<"all" | "needs" | "A" | "B" | "C">("all");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selectionMode, setSelectionMode] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [channelDropdownOpen, setChannelDropdownOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [cardMenuId, setCardMenuId] = useState<string | null>(null);

  const menuRef = useRef<HTMLDivElement>(null);
  const channelDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
      if (channelDropdownRef.current && !channelDropdownRef.current.contains(event.target as Node)) {
        setChannelDropdownOpen(false);
      }
      if (!(event.target as HTMLElement).closest?.("[data-card-menu]")) {
        setCardMenuId(null);
      }
    }
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setChannelDropdownOpen(false);
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

  const getLeadPlatform = (lead: Lead) => getChannel(lead.source);

  const needsReplyCount = useMemo(() => {
    return leads.filter((l) => l.needs_human_intervention || l.needs_human_attention).length;
  }, [leads]);

  const visible = useMemo(() => {
    const q = searchQuery.toLowerCase();
    const base = platform === "all" ? leads : leads.filter((l) => getLeadPlatform(l) === platform);

    const filtered = base.filter((l) => {
      // Apply filter mode
      if (filterMode === "needs") {
        return l.needs_human_intervention || l.needs_human_attention;
      } else if (filterMode !== "all") {
        return l.segment === filterMode;
      }
      return true;
    }).filter((l) => {
      if (!q) return true;
      const name = l.name?.toLowerCase() || "";
      const phone = l.phone?.toLowerCase() || "";
      if (name.includes(q) || phone.includes(q)) return true;
      const qDigits = q.replace(/\D/g, "");
      return qDigits.length > 0 && phone.replace(/\D/g, "").includes(qDigits);
    });

    return filtered.sort((a, b) => {
      const aPinned = a.pinned_at ? 1 : 0;
      const bPinned = b.pinned_at ? 1 : 0;
      if (aPinned !== bPinned) return bPinned - aPinned;
      if (aPinned && bPinned) {
        return new Date(b.pinned_at!).getTime() - new Date(a.pinned_at!).getTime();
      }
      if (a.needs_human_intervention && !b.needs_human_intervention) return -1;
      if (!a.needs_human_intervention && b.needs_human_intervention) return 1;
      const aTime = (a as ConversationLead).last_reply_at || a.created_at;
      const bTime = (b as ConversationLead).last_reply_at || b.created_at;
      return new Date(bTime).getTime() - new Date(aTime).getTime();
    });
  }, [leads, platform, filterMode, searchQuery]);


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


  // If in escalations folder and escalationPanelContent provided, render with header above it
  if (folder === "escalations" && escalationPanelContent) {
    return (
      <div className="w-full flex-shrink-0 bg-white flex flex-col h-full z-10 relative">
        {/* ── Header ── */}
        <div className="pr-4 pl-16 pt-4 pb-2 lg:pl-4">
          <div className="flex items-center justify-between">
            <h2 className="font-display text-[19px] font-bold text-[#0A1528]">Conversations</h2>
          </div>
        </div>

        {/* ── Tabs row ── */}
        <div className="border-b border-[#e2e8f0] px-4 flex gap-4">
          {[
            { id: "chats", label: "Inbox", count: total },
            { id: "escalations", label: "Escalations", count: escalationCount, icon: Flag, red: true },
            { id: "archived", label: "Archived", count: 0 },
            { id: "blocked", label: "Blocked", count: 0 },
          ].map((tab) => {
            const Icon = tab.icon;
            const isActive = folder === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => onFolderChange?.(tab.id as InboxFolder)}
                className={cn(
                  "py-3 text-[12px] font-semibold flex items-center gap-1.5 whitespace-nowrap relative transition-colors",
                  isActive
                    ? "text-primary"
                    : "text-[#64748b] hover:text-[#0A1528]"
                )}
              >
                {Icon && <Icon size={11} className={tab.red ? "text-red-500" : ""} />}
                {tab.label}
                {tab.count > 0 && (
                  <span className={cn(
                    "rounded-full px-1.5 py-0.5 text-[9px] font-bold",
                    tab.red
                      ? "bg-red-50 text-red-600"
                      : "bg-primary-light text-primary"
                  )}>
                    {tab.count}
                  </span>
                )}
                {isActive && (
                  <div className="absolute bottom-0 inset-x-0 h-0.5 bg-primary" />
                )}
              </button>
            );
          })}
        </div>

        {/* ── Escalation panel content ── */}
        {/* A bounded flex column, so the panel's table area is what scrolls. */}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {escalationPanelContent}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full flex-shrink-0 bg-white flex flex-col h-full z-10 relative">
      {/* ── Header ── */}
      <div className="pr-4 pl-16 pt-4 pb-2 lg:pl-4">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-[19px] font-bold text-[#0A1528]">Conversations</h2>
          <div className="relative" ref={menuRef}>
            <button onClick={() => setMenuOpen(!menuOpen)} className="p-1.5 rounded-md hover:bg-slate-100 text-slate-500 hover:text-slate-700 transition-colors">
              <MoreVertical size={18} />
            </button>
            {menuOpen && (
              <div className="absolute right-0 top-full mt-1 w-36 bg-white border border-slate-200 rounded-xl shadow-xl overflow-hidden z-20 py-1.5">
                <button onClick={() => { setSelectionMode(true); setMenuOpen(false); }} className="w-full text-left px-4 py-2 text-[13px] font-medium text-slate-700 hover:bg-slate-50 transition-colors">
                  Select chats
                </button>
                <button onClick={() => { setSelectionMode(true); setSelectedIds(new Set(visible.map(l => l.id))); setMenuOpen(false); }} className="w-full text-left px-4 py-2 text-[13px] font-medium text-slate-700 hover:bg-slate-50 transition-colors">
                  Select all
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Tabs row ── */}
      <div className="border-b border-[#e2e8f0] px-4 flex gap-4">
        {[
          { id: "chats", label: "Inbox", count: total },
          { id: "escalations", label: "Escalations", count: escalationCount, icon: Flag, red: true },
          { id: "archived", label: "Archived", count: 0 },
          { id: "blocked", label: "Blocked", count: 0 },
        ].map((tab) => {
          const Icon = tab.icon;
          const isActive = folder === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => onFolderChange?.(tab.id as InboxFolder)}
              className={cn(
                "py-3 text-[12px] font-semibold flex items-center gap-1.5 whitespace-nowrap relative transition-colors",
                isActive
                  ? "text-primary"
                  : "text-[#64748b] hover:text-[#0A1528]"
              )}
            >
              {Icon && <Icon size={11} className={tab.red ? "text-red-500" : ""} />}
              {tab.label}
              {tab.count > 0 && (
                <span className={cn(
                  "rounded-full px-1.5 py-0.5 text-[9px] font-bold",
                  tab.red
                    ? "bg-red-50 text-red-600"
                    : "bg-primary-light text-primary"
                )}>
                  {tab.count}
                </span>
              )}
              {isActive && (
                <div className="absolute bottom-0 inset-x-0 h-0.5 bg-primary" />
              )}
            </button>
          );
        })}
      </div>

      {/* ── Search box ── */}
      <div className="mx-4 mt-3">
        <div className="relative flex-1 group">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-primary transition-colors" />
          <input
            type="text"
            placeholder="Search name, number or message"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full pl-9 pr-7 py-2 bg-white border border-[#e2e8f0] rounded-xl text-[12.5px] text-slate-700 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all h-9"
          />
          {searchQuery && (
            <button onClick={() => onSearchChange("")} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 p-0.5 rounded-full hover:bg-slate-100 transition-colors">
              <X size={14} />
            </button>
          )}
          <button
            onClick={handleRefresh}
            title="Refresh"
            disabled={isRefreshing}
            className="absolute right-1 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-600 transition-colors disabled:opacity-60"
          >
            <RefreshCw size={14} className={isRefreshing ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* ── Filter chips row ── */}
      <div className="mx-4 mt-2.5 flex flex-wrap gap-1">
        {[
          { id: "all" as const, label: "All" },
          { id: "needs" as const, label: `Needs reply · ${needsReplyCount}` },
          { id: "A" as const, label: "🔥 Hot", color: "orange" },
          { id: "B" as const, label: "Warm", color: "amber" },
          { id: "C" as const, label: "Cold", color: "blue" },
        ].map((chip) => (
          <button
            key={chip.id}
            onClick={() => setFilterMode(chip.id)}
            className={cn(
              "rounded-full border px-[7px] py-1 text-[10.5px] font-semibold whitespace-nowrap transition-all",
              filterMode === chip.id
                ? chip.id === "all"
                  ? "bg-[#0A1528] text-white border-[#0A1528]"
                  : "bg-primary-light text-primary border-primary/30"
                : "bg-white text-[#334155] border-[#e2e8f0] hover:border-slate-300"
            )}
          >
            {chip.label}
          </button>
        ))}

        {/* Channel dropdown */}
        <div className="relative" ref={channelDropdownRef}>
          <button
            onClick={() => setChannelDropdownOpen(!channelDropdownOpen)}
            className={cn(
              "rounded-full border px-[7px] py-1 text-[10.5px] font-semibold whitespace-nowrap flex items-center gap-0.5 transition-all",
              platform === "all"
                ? "bg-white text-[#334155] border-[#e2e8f0] hover:border-slate-300"
                : "bg-primary-light text-primary border-primary/30"
            )}
          >
            Channel <ChevronDown size={10} />
          </button>
          {channelDropdownOpen && (
            <div className="absolute left-0 top-[calc(100%+4px)] z-30 w-32 rounded-xl border border-[#e2e8f0] bg-white shadow-lg py-1">
              {[
                { value: "all", label: "All channels" },
                { value: "whatsapp", label: "WhatsApp" },
                { value: "instagram", label: "Instagram" },
                { value: "facebook", label: "Facebook" },
                { value: "telegram", label: "Telegram" },
              ].map((ch) => (
                <button
                  key={ch.value}
                  onClick={() => {
                    onPlatformChange(ch.value);
                    setChannelDropdownOpen(false);
                  }}
                  className={cn(
                    "w-full text-left px-4 py-2 text-[12px]",
                    platform === ch.value
                      ? "bg-primary-light text-primary font-semibold"
                      : "text-slate-700 hover:bg-slate-50"
                  )}
                >
                  {ch.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Conversation list ── */}
      <div className="flex-1 overflow-y-auto">
        {visible.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-6 py-10 text-slate-500 space-y-3 animate-in fade-in duration-300">
            <div className="w-14 h-14 rounded-2xl bg-slate-100 border border-slate-200 flex items-center justify-center shadow-sm">
              <SearchX size={24} className="text-slate-400 opacity-60" />
            </div>
            <div>
              <p className="font-display font-semibold text-[15px] text-slate-700">No conversations found</p>
              <p className="text-[13px] mt-1.5 leading-relaxed">Try adjusting your search query or switching filters to find what you&apos;re looking for.</p>
            </div>
            {(searchQuery || filterMode !== "all" || platform !== "all") && (
              <button
                onClick={() => {
                  onSearchChange("");
                  setFilterMode("all");
                  onPlatformChange("all");
                }}
                className="mt-3 text-[13px] font-semibold text-primary hover:underline"
              >
                Clear all filters
              </button>
            )}
          </div>
        ) : (
          visible.map((lead) => {
            const isBot = lead.last_message_direction === "outbound" && lead.last_message_is_ai === true;
            const preview = lead.last_message_content || (lead.phone ? formatPhone(lead.phone) : "No messages yet");
            const needsAction = lead.needs_human_intervention || lead.needs_human_attention;
            return (
              <div
                key={lead.id}
                onClick={() => onSelect(lead)}
                role="button"
                tabIndex={0}
                className={cn(
                  "w-full text-left px-4 py-3 border-b border-[#f1f5f9] transition-all duration-150 group flex items-start gap-3 relative cursor-pointer",
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

                {/* Lead initials avatar */}
                <ChannelAvatar source={lead.source} size={36} />

                {/* Content */}
                <div className="flex-1 min-w-0">
                  {/* Line 1: name + time */}
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <div className="flex items-center gap-1 min-w-0">
                      <span className="text-[13px] font-bold text-[#0A1528] truncate">
                        {lead.name || formatPhone(lead.phone) || "Unknown"}
                      </span>
                      {onPin ? (
                        <button
                          onClick={(e) => { e.stopPropagation(); onPin(lead.id); }}
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
                    <span className="text-[10.5px] text-[#94a3b8] whitespace-nowrap">
                      {formatConvoTime((lead as ConversationLead).last_reply_at || lead.created_at)}
                    </span>
                  </div>

                  {/* Line 2: preview */}
                  <p className={cn(
                    "text-[12px] truncate mb-1.5",
                    needsAction ? "font-semibold text-[#0A1528]" : "text-[#64748b]"
                  )}>
                    {isBot && !needsAction ? "AI: " : ""}{preview}
                  </p>

                  {/* Line 3: tags */}
                  <div className="flex gap-1.5 flex-wrap">
                    {needsAction && (
                      <span className="rounded-md px-1.5 py-0.5 text-[10px] font-bold bg-red-600 text-white">
                        Needs reply
                      </span>
                    )}

                    {lead.segment === "A" && (
                      <span className="rounded-md px-1.5 py-0.5 text-[10px] font-bold bg-orange-50 text-orange-600">
                        Hot
                      </span>
                    )}
                    {lead.segment === "B" && (
                      <span className="rounded-md px-1.5 py-0.5 text-[10px] font-bold bg-amber-50 text-amber-700">
                        Warm
                      </span>
                    )}
                    {lead.segment === "C" && (
                      <span className="rounded-md px-1.5 py-0.5 text-[10px] font-bold bg-blue-50 text-blue-600">
                        Cold
                      </span>
                    )}
                    {lead.segment === "D" && (
                      <span className="rounded-md px-1.5 py-0.5 text-[10px] font-bold bg-slate-100 text-slate-500">
                        Not interested
                      </span>
                    )}

                    {isBot && !needsAction && (
                      <span className="rounded-md px-1.5 py-0.5 text-[10px] font-bold bg-emerald-50 text-emerald-700">
                        ✓ AI replied
                      </span>
                    )}

                    {lead.opted_out && (
                      <span className="rounded-md px-1.5 py-0.5 text-[10px] font-bold bg-slate-100 text-slate-700">
                        STOP
                      </span>
                    )}

                    {lead.blocked_at && (
                      <span className="rounded-md px-1.5 py-0.5 text-[10px] font-bold bg-slate-100 text-slate-700">
                        BLOCKED
                      </span>
                    )}
                  </div>
                </div>

                {/* Per-item menu */}
                <div className="relative shrink-0" data-card-menu onClick={(e) => e.stopPropagation()}>
                  <button
                    onClick={() => setCardMenuId(cardMenuId === lead.id ? null : lead.id)}
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
                          {folder === "archived" ? "Unarchive" : "Archive"}
                        </button>
                      )}
                      {onBlock && (
                        <button onClick={() => { setCardMenuId(null); onBlock(lead.id); }} className="w-full flex items-center gap-2 px-3 py-2 text-left text-[12.5px] text-slate-700 hover:bg-slate-50 transition-colors">
                          <Ban size={14} className="text-slate-500" />
                          {folder === "blocked" ? "Unblock" : "Block"}
                        </button>
                      )}
                      <button onClick={() => handleDeleteOne(lead.id)} className="w-full flex items-center gap-2 px-3 py-2 text-left text-[12.5px] text-red-600 hover:bg-red-50 transition-colors">
                        <Trash2 size={14} /> Delete
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
        {!searchQuery && filterMode === "all" && hasMore && (
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
