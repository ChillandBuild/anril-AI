"use client";
import { useCallback, useEffect, useState, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { getAuthHeaders, API_URL, Lead, api } from "@/lib/api";
import { ConversationList, type InboxFolder } from "@/components/conversation-list";
import { ChatThread } from "@/components/chat-thread";
import { LeadDetailsPanel } from "@/components/lead-details-panel";
import { EscalationPanel } from "@/components/escalation-panel";
import { usePolling } from "@/hooks/usePolling";
import { toast } from "sonner";
import { createClient } from "@/lib/supabase/client";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";

function getDetailsPanelDefault(): boolean {
  if (typeof window === "undefined") return true;
  const stored = localStorage.getItem("lead_details_open");
  if (stored !== null) return stored === "true";
  return window.innerWidth >= 1280;
}

const CONVERSATIONS_PAGE_SIZE = 50;

async function fetchConversations(
  folder: InboxFolder,
  limit: number,
  offset: number,
  q?: string,
): Promise<{ leads: Lead[]; total: number }> {
  const auth = await getAuthHeaders();
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset), folder });
  if (q) qs.set("q", q);
  const res = await fetch(`${API_URL}/api/v1/conversations?${qs}`, { headers: auth });
  if (!res.ok) throw new Error(`conversations fetch failed: ${res.status}`);
  const data = await res.json();
  return { leads: data.leads ?? [], total: data.total ?? 0 };
}

const SEARCH_RESULTS_LIMIT = 200;

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
      <h2 className="font-display text-2xl font-bold text-primary mb-2">Shared Inbox</h2>
      <p className="font-body text-sm font-semibold text-on-surface mb-1">Connect Multiple Platforms &ndash; all in one inbox!</p>
      <p className="font-body text-sm text-on-surface-muted">Easily manage messages from multiple platforms in a single inbox.</p>
    </div>
  );
}

export default function ConversationsPage() {
  const { callerId, role, permissions } = useAuthRole();
  const canReplyToConversations = role === "owner" || permissions.includes("conversations.reply");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [selected, setSelected] = useState<Lead | null>(null);
  const [error, setError] = useState(false);
  const [platform, setPlatform] = useState<string>("all");
  const [folder, setFolder] = useState<InboxFolder>("chats");
  const [detailsOpen, setDetailsOpen] = useState(getDetailsPanelDefault);
  const [escalationCount, setEscalationCount] = useState(0);
  const [total, setTotal] = useState(0);
  // The Inbox tab's badge: always the Inbox count, whichever tab is open.
  const [inboxTotal, setInboxTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  // The folder whose first answer has arrived. Differs from `folder` on first
  // load and right after a folder switch, so the list shows a loader instead of
  // an empty state (or the previous folder's rows). Search refreshes don't touch it.
  const [loadedFolder, setLoadedFolder] = useState<InboxFolder | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const leadsCountRef = useRef(0);

  useEffect(() => {
    const handle = setTimeout(() => setDebouncedSearch(searchQuery.trim()), 300);
    return () => clearTimeout(handle);
  }, [searchQuery]);

  const searchParams = useSearchParams();
  const deepLinkLeadId = searchParams.get("lead");
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

  // Refresh (initial load, folder switch, poll) always re-fetches from offset 0,
  // sized to at least whatever's currently loaded — so a poll tick doesn't
  // silently discard pages the user pulled in via "Load more". A search query
  // is resolved server-side (not just against whatever page is loaded) so it
  // can find conversations outside the default page.
  const load = useCallback(() => {
    if (folder === "escalations") return;
    const limit = debouncedSearch ? SEARCH_RESULTS_LIMIT : Math.max(CONVERSATIONS_PAGE_SIZE, leadsCountRef.current);
    fetchConversations(folder, limit, 0, debouncedSearch || undefined)
      .then(({ leads: loaded, total: t }) => {
        setLeads(loaded);
        setTotal(t);
        setLoadedFolder(folder);
        if (folder === "chats" && !debouncedSearch) setInboxTotal(t);
        setError(false);
      })
      .catch(() => setError(true));
  }, [folder, debouncedSearch]);

  // On the other tabs, read the Inbox count on its own (one row is enough).
  useEffect(() => {
    if (folder === "chats") return;
    fetchConversations("chats", 1, 0)
      .then(({ total: t }) => setInboxTotal(t))
      .catch(() => {});
  }, [folder]);

  useEffect(() => { leadsCountRef.current = leads.length; }, [leads]);
  useEffect(() => { load(); }, [load]);
  usePolling(load, 20000);

  const loadMore = useCallback(async () => {
    if (loadingMore || leads.length >= total) return;
    setLoadingMore(true);
    try {
      const { leads: more, total: t } = await fetchConversations(folder, CONVERSATIONS_PAGE_SIZE, leads.length);
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
  }, [folder, leads.length, loadingMore, total]);

  // Selects a lead by id directly (via API), independent of whatever page of
  // the conversation list happens to be loaded — a lead outside the currently
  // fetched page would otherwise never be found by a client-side .find().
  const selectLeadById = useCallback(async (leadId: string) => {
    const existing = leads.find((l) => l.id === leadId);
    if (existing) {
      setSelected(existing);
      return;
    }
    try {
      const lead = await api.leads.get(leadId);
      setLeads((prev) => (prev.some((l) => l.id === lead.id) ? prev : [lead, ...prev]));
      setSelected(lead);
    } catch {
      toast.error("Couldn't open that conversation");
    }
  }, [leads]);

  // Auto-select lead from ?lead= query param (e.g. from Inbox Reply button)
  useEffect(() => {
    if (!deepLinkLeadId || deepLinked.current) return;
    deepLinked.current = true;
    selectLeadById(deepLinkLeadId);
  }, [deepLinkLeadId, selectLeadById]);

  useEffect(() => {
    localStorage.setItem("lead_details_open", String(detailsOpen));
  }, [detailsOpen]);

  function handleFolderChange(next: InboxFolder) {
    leadsCountRef.current = 0;
    setFolder(next);
    setSelected(null);
    setSearchQuery("");
  }

  function handleSelect(lead: Lead) {
    setSelected(lead);
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

  function handlePinSelected(ids: string[]) {
    setLeads((prev) => {
      let next = prev;
      for (const id of ids) {
        next = togglePinInList(next, id);
      }
      return next;
    });
    for (const id of ids) {
      api.leads.pin(id).catch(() => {
        setLeads((rollback) => togglePinInList(rollback, id));
        toast.error("Failed to pin/unpin contact");
      });
    }
  }

  // Archiving/blocking changes which folder a lead belongs to, so it leaves the
  // current list. Optimistically remove; reload on failure.
  function handleArchive(id: string) {
    if (!canReplyToConversations) return;
    setLeads((prev) => prev.filter((l) => l.id !== id));
    if (selected?.id === id) setSelected(null);
    api.leads.archive(id)
      .then(() => toast.success(folder === "archived" ? "Chat unarchived" : "Chat archived"))
      .catch(() => { toast.error("Failed to archive"); load(); });
  }

  function handleBlock(id: string) {
    setLeads((prev) => prev.filter((l) => l.id !== id));
    if (selected?.id === id) setSelected(null);
    api.leads.block(id)
      .then(() => toast.success(folder === "blocked" ? "Contact unblocked" : "Contact blocked"))
      .catch(() => { toast.error("Failed to block"); load(); });
  }

  function handleEscalationReply(leadId: string) {
    setFolder("chats");
    selectLeadById(leadId);
  }

  if (folder === "escalations") {
    return (
      <div className="flex h-[calc(100dvh-5.25rem)] overflow-hidden bg-background lg:h-screen lg:pl-[var(--sidebar-width)]">
        {/* Escalations take the whole page width, with the Conversations tabs above. */}
        <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
          <ConversationList
            leads={[]}
            selectedId={null}
            onSelect={() => {}}
            platform={platform}
            onPlatformChange={setPlatform}
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            onRefresh={load}
            onPin={handlePin}
            onPinSelected={handlePinSelected}
            onArchive={handleArchive}
            canArchive={canReplyToConversations}
            onBlock={handleBlock}
            folder={folder}
            onFolderChange={handleFolderChange}
            escalationCount={escalationCount}
            total={inboxTotal}
            hasMore={false}
            loadingMore={false}
            loading={false}
            onLoadMore={() => {}}
            onDeleted={() => {}}
            escalationPanelContent={
              <EscalationPanel
                onReply={handleEscalationReply}
                onCountChange={setEscalationCount}
                currentCallerId={callerId}
                canReplyToConversations={canReplyToConversations}
              />
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100dvh-5.25rem)] overflow-hidden bg-background lg:h-screen lg:pl-[var(--sidebar-width)]">
      {/* ── Conversation list ── */}
      <div className={`relative w-full flex-shrink-0 md:block md:w-[380px] md:max-w-[38vw] ${selected ? "hidden" : "block"}`}>
        <ConversationList
          leads={leads}
          selectedId={selected?.id ?? null}
          onSelect={handleSelect}
          platform={platform}
          onPlatformChange={setPlatform}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          onRefresh={load}
          onPin={handlePin}
          onPinSelected={handlePinSelected}
          onArchive={handleArchive}
          canArchive={canReplyToConversations}
          onBlock={handleBlock}
          folder={folder}
          onFolderChange={handleFolderChange}
          escalationCount={escalationCount}
          total={inboxTotal}
          hasMore={leads.length < total}
          loadingMore={loadingMore}
          loading={loadedFolder !== folder}
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
          onBack={() => setSelected(null)}
          onDeleted={(id) => {
            setLeads((prev) => prev.filter((l) => l.id !== id));
            setSelected(null);
          }}
          onLeadUpdate={(updated) => setSelected(updated)}
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

      {/* ── Right: Lead details panel ── */}
      {/* Opened and closed from the chat header's "Lead info" button. */}
      {selected && detailsOpen && (
        <div className="hidden xl:block">
          <LeadDetailsPanel
            lead={selected}
            onCollapse={() => setDetailsOpen(false)}
            onLeadUpdate={(updated) => setSelected(updated)}
          />
        </div>
      )}
    </div>
  );
}
