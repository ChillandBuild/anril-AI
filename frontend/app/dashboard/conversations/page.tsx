"use client";
import { useCallback, useEffect, useState, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { getAuthHeaders, API_URL, Lead, api } from "@/lib/api";
import { ConversationList } from "@/components/conversation-list";
import { ChatThread } from "@/components/chat-thread";
import { LeadDetailsPanel } from "@/components/lead-details-panel";
import { EscalationPanel } from "@/components/escalation-panel";
import { ChatsFolderPanel } from "@/components/chats/ChatsFolderPanel";
import { ReasonDialog, type ReasonKind } from "@/components/chats/ReasonDialog";
import { formatPhone } from "@/lib/utils";
import { GROUPS_PAGE, fromChatsBody, saveChatsAsGroup, savedGroupMessage } from "@/components/chats/saveAsGroup";
import { createClient } from "@/lib/supabase/client";
import { usePolling } from "@/hooks/usePolling";
import { toast } from "sonner";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import {
  EMPTY_COUNTS,
  EMPTY_FILTERS,
  filterParams,
  type InboxChannel,
  type InboxCounts,
  type InboxFilters,
  type InboxView,
  type ListView,
  type Option,
} from "@/components/chats/inboxFilters";

function getDetailsPanelDefault(): boolean {
  if (typeof window === "undefined") return true;
  const stored = localStorage.getItem("lead_details_open");
  if (stored !== null) return stored === "true";
  return window.innerWidth >= 1280;
}

const CONVERSATIONS_PAGE_SIZE = 50;

async function fetchConversations(
  qs: URLSearchParams,
  limit: number,
  offset: number,
): Promise<{ leads: Lead[]; total: number }> {
  const auth = await getAuthHeaders();
  const params = new URLSearchParams(qs);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  const res = await fetch(`${API_URL}/api/v1/conversations?${params}`, { headers: auth });
  if (!res.ok) throw new Error(`conversations fetch failed: ${res.status}`);
  const data = await res.json();
  return { leads: data.leads ?? [], total: data.total ?? 0 };
}

async function fetchCounts(qs: URLSearchParams): Promise<InboxCounts> {
  const auth = await getAuthHeaders();
  const res = await fetch(`${API_URL}/api/v1/conversations/counts?${qs}`, { headers: auth });
  if (!res.ok) throw new Error(`counts fetch failed: ${res.status}`);
  const data = await res.json();
  return { ...EMPTY_COUNTS, ...data, channels: data.channels ?? {} };
}

function togglePinInList(leads: Lead[], leadId: string): Lead[] {
  return leads.map((l) =>
    l.id === leadId ? { ...l, pinned_at: l.pinned_at ? null : new Date().toISOString() } : l
  );
}

function SharedInboxEmpty() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-8 text-center select-none">
      <div className="w-[280px] h-[200px] rounded-2xl bg-gradient-to-br from-primary/15 via-primary/5 to-transparent border border-primary/15 p-4 mb-8 shadow-sm">
        <div className="flex gap-1.5 mb-4">
          <span className="w-2 h-2 rounded-full bg-primary/40" />
          <span className="w-2 h-2 rounded-full bg-primary/40" />
          <span className="w-2 h-2 rounded-full bg-primary/40" />
        </div>
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <div className="h-7 w-32 rounded-lg bg-primary/20" />
            <div className="h-6 w-6 rounded-full bg-primary/30" />
          </div>
          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-full bg-primary/40" />
            <div className="h-7 flex-1 rounded-lg bg-primary/15" />
          </div>
          <div className="h-7 w-3/4 rounded-lg bg-primary/10" />
        </div>
      </div>
      <h2 className="font-display text-2xl font-bold text-primary mb-2">Pick a chat on the left.</h2>
    </div>
  );
}

export default function ConversationsPage() {
  const { callerId, role, permissions } = useAuthRole();
  const canReplyToConversations = role === "owner" || permissions.includes("conversations.reply");
  // Save as a group puts people into Customers > Groups, so it needs the same permission as making a group there.
  const canSaveAsGroup = role === "owner" || permissions.includes("leads.manage");
  const router = useRouter();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [selected, setSelected] = useState<Lead | null>(null);
  const [error, setError] = useState(false);
  const [view, setView] = useState<InboxView>("inbox");
  // The full-width pages (Needs you, Archived, Blocked) have no list of their own: the list behind them stays Inbox.
  const listView: ListView = view === "ai_handling" ? "ai_handling" : "inbox";
  const [escalationCount, setEscalationCount] = useState(0);
  const [channel, setChannel] = useState<InboxChannel>("all");
  const [filters, setFilters] = useState<InboxFilters>(EMPTY_FILTERS);
  const [counts, setCounts] = useState<InboxCounts>(EMPTY_COUNTS);
  const [team, setTeam] = useState<Option[]>([]);
  const [tags, setTags] = useState<Option[]>([]);
  const [detailsOpen, setDetailsOpen] = useState(getDetailsPanelDefault);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  // The query whose first answer has arrived. Differs from the current one on first load and
  // right after a tab or filter change, so the list shows a loader instead of stale rows.
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const leadsCountRef = useRef(0);

  useEffect(() => {
    const handle = setTimeout(() => setDebouncedSearch(searchQuery.trim()), 300);
    return () => clearTimeout(handle);
  }, [searchQuery]);

  // Teammates (Handled by) and campaign tags (Tag) for the Filter panel.
  useEffect(() => {
    api.callers.list()
      .then(({ data }) => setTeam(data.filter((c) => c.active !== false).map((c) => ({ value: c.id, label: c.name }))))
      .catch(() => {});
    api.knowledge.listCampaignTags()
      .then((rows) => setTags(rows.map((t) => ({ value: t.id, label: t.name }))))
      .catch(() => {});
  }, []);

  const searchParams = useSearchParams();
  // "lead_id" too: WhatsApp alerts already sent to owners (template_fields.chat_link) and push links use it.
  const deepLinkLeadId = searchParams.get("lead") ?? searchParams.get("lead_id");
  const deepLinked = useRef(false);

  const fetchEscalationCount = useCallback(async () => {
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/chat-handovers/count`, { headers: auth });
      if (res.ok) setEscalationCount((await res.json()).count ?? 0);
    } catch {}
  }, []);

  useEffect(() => {
    fetchEscalationCount();
    const supabase = createClient();
    const channel = supabase
      .channel("escalation-count-realtime")
      .on("postgres_changes", { event: "*", schema: "public", table: "chat_handovers" }, () => {
        fetchEscalationCount();
      })
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [fetchEscalationCount]);

  const baseQs = useCallback(
    (f: InboxFilters = filters, v: ListView = listView) => filterParams(f, { view: v, channel, search: debouncedSearch || undefined }),
    [filters, listView, channel, debouncedSearch],
  );
  const queryKey = baseQs().toString();

  // Refresh (first load, tab/filter switch, poll) always re-fetches from offset 0, sized to at
  // least what's loaded, so a poll tick doesn't drop pages pulled in with "Load more". Every
  // filter is applied by the server, so total and counts describe exactly what is shown.
  const load = useCallback(() => {
    const qs = baseQs();
    const key = qs.toString();
    const limit = Math.max(CONVERSATIONS_PAGE_SIZE, leadsCountRef.current);
    fetchConversations(qs, limit, 0)
      .then(({ leads: loaded, total: t }) => {
        setLeads(loaded);
        setTotal(t);
        setLoadedKey(key);
        setError(false);
      })
      .catch(() => setError(true));
    fetchCounts(qs).then(setCounts).catch(() => {});
  }, [baseQs]);

  useEffect(() => { leadsCountRef.current = leads.length; }, [leads]);
  useEffect(() => { load(); }, [load]);
  usePolling(load, 20000);

  const loadMore = useCallback(async () => {
    if (loadingMore || leads.length >= total) return;
    setLoadingMore(true);
    try {
      const { leads: more, total: t } = await fetchConversations(baseQs(), CONVERSATIONS_PAGE_SIZE, leads.length);
      setLeads((prev) => {
        const seen = new Set(prev.map((l) => l.id));
        return [...prev, ...more.filter((l) => !seen.has(l.id))];
      });
      setTotal(t);
    } catch {
      toast.error("Failed to load more conversations");
    } finally {
      setLoadingMore(false);
    }
  }, [baseQs, leads.length, loadingMore, total]);

  // The Filter panel's "Show N chats": the exact count for a draft, for the tab and channel in view.
  const countFor = useCallback(async (draft: InboxFilters) => {
    const c = await fetchCounts(baseQs(draft));
    if (listView === "ai_handling") return c.ai_handling;
    return channel === "all" ? c.channels.all ?? 0 : c.channels[channel] ?? 0;
  }, [baseQs, listView, channel]);

  // Shared unread: opening a chat marks it read for the whole team.
  const markSeen = useCallback((lead: Lead) => {
    if (!lead.unread_count) return;
    setLeads((prev) => prev.map((l) => (l.id === lead.id ? { ...l, unread_count: 0 } : l)));
    api.chats.seen(lead.id).catch(() => {});
  }, []);

  // Selects a lead by id directly (via API), independent of whatever page of
  // the conversation list happens to be loaded.
  const selectLeadById = useCallback(async (leadId: string) => {
    const existing = leads.find((l) => l.id === leadId);
    if (existing) {
      setSelected(existing);
      markSeen(existing);
      return;
    }
    try {
      const lead = await api.leads.get(leadId);
      setLeads((prev) => (prev.some((l) => l.id === lead.id) ? prev : [lead, ...prev]));
      setSelected(lead);
      api.chats.seen(lead.id).catch(() => {});
    } catch {
      toast.error("Couldn't open that conversation");
    }
  }, [leads, markSeen]);

  // Auto-select lead from ?lead= query param (e.g. from a notification's Reply button)
  useEffect(() => {
    if (!deepLinkLeadId || deepLinked.current) return;
    deepLinked.current = true;
    selectLeadById(deepLinkLeadId);
  }, [deepLinkLeadId, selectLeadById]);

  useEffect(() => {
    localStorage.setItem("lead_details_open", String(detailsOpen));
  }, [detailsOpen]);

  function resetPaging() {
    leadsCountRef.current = 0;
  }

  function handleViewChange(next: InboxView) {
    resetPaging();
    setView(next);
    setSelected(null);
  }

  function handleSelect(lead: Lead) {
    setSelected(lead);
    markSeen(lead);
  }

  function handlePin(id: string) {
    setLeads((prev) => {
      const current = prev.find((l) => l.id === id);
      if (!current) return prev;
      const toggled = togglePinInList(prev, id);
      api.leads.pin(id).catch(() => {
        setLeads((rollback) => togglePinInList(rollback, id));
        toast.error("Failed to pin/unpin contact");
      });
      return toggled;
    });
  }

  // Archiving/blocking changes which tab a lead belongs to, so it leaves the
  // current list. Optimistically remove; reload on failure.
  // Both ask "Why?" first (optional), then act.
  const [askWhy, setAskWhy] = useState<{ kind: ReasonKind; id: string; name: string } | null>(null);
  const whoIs = (id: string) => {
    const l = leads.find((x) => x.id === id);
    return l?.name || formatPhone(l?.phone ?? "") || "this person";
  };

  function handleArchive(id: string) {
    if (!canReplyToConversations) return;
    setAskWhy({ kind: "archive", id, name: whoIs(id) });
  }

  function handleBlock(id: string) {
    setAskWhy({ kind: "block", id, name: whoIs(id) });
  }

  function confirmWhy(reason: string) {
    if (!askWhy) return;
    const { kind, id } = askWhy;
    setAskWhy(null);
    setLeads((prev) => prev.filter((l) => l.id !== id));
    if (selected?.id === id) setSelected(null);
    const call = kind === "archive" ? api.leads.archive(id, reason) : api.leads.block(id, reason);
    call
      .then(() => toast.success(kind === "archive" ? "Chat archived" : "Contact blocked"))
      .catch(() => { toast.error(kind === "archive" ? "Failed to archive" : "Failed to block"); load(); });
  }

  const whyDialog = askWhy && (
    <ReasonDialog kind={askWhy.kind} name={askWhy.name} onCancel={() => setAskWhy(null)} onConfirm={confirmWhy} />
  );

  // Reply from the Needs you page: open that chat in the Inbox.
  function handleEscalationReply(leadId: string) {
    resetPaging();
    setView("inbox");
    selectLeadById(leadId);
  }

  // A lead changed in the thread or the side panel: keep the list row in step.
  function handleLeadUpdate(updated: Lead) {
    setSelected(updated);
    setLeads((prev) => prev.map((l) => (l.id === updated.id ? { ...l, ...updated } : l)));
  }

  // Filter panel > Save as a group: the server collects everyone this tab, search and filters match.
  async function handleSaveAsGroup(name: string) {
    const saved = await saveChatsAsGroup(fromChatsBody(name, filters, { view: listView, channel, search: debouncedSearch || undefined }));
    toast.success(savedGroupMessage(saved.added, saved.name), {
      action: { label: "Open Groups", onClick: () => router.push(GROUPS_PAGE) },
    });
  }

  const listProps = {
    view,
    onViewChange: handleViewChange,
    channel,
    onChannelChange: (c: InboxChannel) => { resetPaging(); setChannel(c); },
    counts,
    filters,
    onFiltersChange: (f: InboxFilters) => { resetPaging(); setFilters(f); },
    countFor,
    team,
    tags,
    searchQuery,
    onSearchChange: setSearchQuery,
    onRefresh: load,
    onPin: handlePin,
    onArchive: handleArchive,
    canArchive: canReplyToConversations,
    onBlock: handleBlock,
    escalationCount,
    onSaveAsGroup: canSaveAsGroup ? handleSaveAsGroup : undefined,
    matchTotal: total,
  };

  if (view === "needs_you" || view === "archived" || view === "blocked") {
    return (
      <div className="flex h-[calc(100dvh-var(--mobile-nav-h)-env(safe-area-inset-bottom))] overflow-hidden bg-background lg:h-screen lg:pl-[var(--shell-left)]">
        {whyDialog}
        {/* Needs you, Archived and Blocked take the whole page width, with the Conversations tabs above. */}
        <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
          <ConversationList
            {...listProps}
            leads={[]}
            selectedId={null}
            onSelect={() => {}}
            fullPageContent={
              view === "needs_you" ? (
                <EscalationPanel
                  onReply={handleEscalationReply}
                  onCountChange={setEscalationCount}
                  currentCallerId={callerId}
                  canReplyToConversations={canReplyToConversations}
                />
              ) : (
                <ChatsFolderPanel
                  key={view}
                  mode={view}
                  onOpenChat={handleEscalationReply}
                  canReply={canReplyToConversations}
                  canExport={role === "owner"}
                  onSeeBlocked={() => handleViewChange("blocked")}
                />
              )
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100dvh-var(--mobile-nav-h)-env(safe-area-inset-bottom))] overflow-hidden bg-background lg:h-screen lg:pl-[var(--shell-left)]">
      {whyDialog}
      {/* ── Conversation list ── */}
      <div className={`relative w-full flex-shrink-0 md:block md:w-[380px] md:max-w-[38vw] ${selected ? "hidden" : "block"}`}>
        <ConversationList
          {...listProps}
          leads={leads}
          selectedId={selected?.id ?? null}
          onSelect={handleSelect}
          hasMore={leads.length < total}
          loadingMore={loadingMore}
          loading={loadedKey !== queryKey}
          onLoadMore={loadMore}
          onDeleted={(deletedIds) => {
            setLeads((prev) => prev.filter((l) => !deletedIds.includes(l.id)));
            if (selected && deletedIds.includes(selected.id)) {
              setSelected(null);
            }
          }}
        />
      </div>

      {/* ── Center: Chat thread / Shared Inbox empty state ── */}
      {selected ? (
        <ChatThread
          lead={selected}
          team={team}
          onBack={() => setSelected(null)}
          onDeleted={(id) => {
            setLeads((prev) => prev.filter((l) => l.id !== id));
            setSelected(null);
          }}
          onLeadUpdate={handleLeadUpdate}
          detailsOpen={detailsOpen}
          onToggleDetails={() => setDetailsOpen((open) => !open)}
        />
      ) : (
        <div className="hidden flex-1 md:flex">
          <SharedInboxEmpty />
        </div>
      )}
      {error && !selected && (
        <p className="absolute bottom-4 left-1/2 -translate-x-1/2 font-body text-sm text-red-500">Failed to load conversations. Retrying…</p>
      )}

      {/* ── Right: customer panel ── */}
      {selected && detailsOpen && (
        <div className="hidden xl:block">
          <LeadDetailsPanel
            lead={selected}
            team={team}
            onCollapse={() => setDetailsOpen(false)}
            onLeadUpdate={handleLeadUpdate}
          />
        </div>
      )}
    </div>
  );
}
