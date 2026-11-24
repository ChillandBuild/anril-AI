"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, CheckCircle2, Download, Loader2, MessageSquare, Search, UserCog, X } from "lucide-react";
import { toast } from "sonner";
import { cn, formatDuration, secondsSince } from "@/lib/utils";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { usePolling } from "@/hooks/usePolling";
import {
  assignHandover,
  channelOf,
  fetchCallers,
  fetchHandovers,
  fetchHistory,
  reopenHandover,
  resolveHandover,
  severityForWait,
  EMPTY_HISTORY_STATS,
  TRIGGERS,
  type Caller,
  type Handover,
  type HistoryStats,
  type ResolvedHandover,
  type Severity,
} from "@/lib/escalations";
import { CheckTick } from "@/components/ui/controls";
import { channelLabel, downloadCsv, istDateTime, segmentLabel, today, type CsvColumn } from "@/components/chats/exportCsv";
import { Select } from "@/components/ui/Select";
import { StatCards, type StatItem } from "@/components/escalations/stat-cards";
import { HistoryTab } from "@/components/escalations/history-tab";
import { ChannelCell, DurationCell, LeadCell, PersonCell, TableEmpty, TableSkeleton, TriggerChip } from "@/components/escalations/atoms";

type Tab = "active" | "history";

/** Sleek rounded SLA indicator pill colors on the lead cell */
const SLA_BAR: Record<Severity, string> = {
  bad: "bg-rose-500",
  warn: "bg-amber-400",
  ok: "bg-emerald-400",
};

const SLA_TITLE: Record<Severity, string> = {
  bad: "SLA breached: Over 24h wait",
  warn: "Warning: Over 4h wait",
  ok: "Within SLA (<4h)",
};

const DAY = 86_400;

interface EscalationPanelProps {
  onReply: (leadId: string) => void;
  onCountChange: (count: number) => void;
  currentCallerId?: string | null;
  currentCallerName?: string | null;
  canReplyToConversations?: boolean;
}

export function EscalationPanel({
  onReply,
  onCountChange,
  currentCallerId,
  currentCallerName,
  canReplyToConversations = false,
}: EscalationPanelProps) {
  const { role } = useAuthRole();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [tab, setTab] = useState<Tab>(() => (searchParams.get("tab") === "history" ? "history" : "active"));
  const [handovers, setHandovers] = useState<Handover[]>([]);
  const [callers, setCallers] = useState<Caller[]>([]);
  const [loading, setLoading] = useState(true);
  const [assigningId, setAssigningId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [quickFilter, setQuickFilter] = useState<"all" | "unassigned" | "mine" | "breaching">("all");
  const [historyStats, setHistoryStats] = useState<HistoryStats>(EMPTY_HISTORY_STATS);
  const [historyResolver, setHistoryResolver] = useState("");
  const [historyReason, setHistoryReason] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);
  // Export (owner only, like Segments): ticked rows, or everything the current filters show.
  const canExport = role === "owner";
  const [pickedActive, setPickedActive] = useState<Set<string>>(new Set());
  const [pickedHistory, setPickedHistory] = useState<Set<string>>(new Set());
  const [historyRows, setHistoryRows] = useState<ResolvedHandover[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [exporting, setExporting] = useState(false);
  const onHistoryRows = useCallback((rows: ResolvedHandover[], total: number) => {
    setHistoryRows(rows);
    setHistoryTotal(total);
  }, []);

  const visibleHandovers = useMemo(
    () =>
      role === "owner"
        ? handovers
        : handovers.filter((h) => !h.assigned_to || h.assigned_to === currentCallerId),
    [handovers, role, currentCallerId]
  );

  const filteredHandovers = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    return visibleHandovers.filter((h) => {
      if (quickFilter === "unassigned" && h.assigned_to) return false;
      if (quickFilter === "mine" && h.assigned_to !== currentCallerId) return false;
      if (quickFilter === "breaching" && (secondsSince(h.opened_at) ?? 0) < DAY) return false;
      if (!q) return true;
      const ch = channelOf(h.leads);
      return [
        h.leads?.name,
        h.leads?.phone,
        h.leads?.tg_username,
        h.leads?.ig_user_id,
        h.leads?.fb_user_id,
        h.reason,
        ch.label,
      ]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q));
    });
  }, [visibleHandovers, searchQuery, quickFilter, currentCallerId]);

  const load = useCallback(async () => {
    const [hs, cs] = await Promise.all([fetchHandovers(), fetchCallers()]);
    setHandovers(hs);
    setCallers(cs);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);
  usePolling(load, 15000);

  useEffect(() => {
    if (!loading) onCountChange(visibleHandovers.length);
  }, [visibleHandovers.length, loading, onCountChange]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) setAssigningId(null);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function switchTab(next: Tab) {
    setTab(next);
    setPickedActive(new Set());
    setPickedHistory(new Set());
    setSearchQuery("");
    setQuickFilter("all");
    setHistoryResolver("");
    setHistoryReason("");
    const params = new URLSearchParams(searchParams.toString());
    if (next === "history") params.set("tab", "history");
    else params.delete("tab");
    const qs = params.toString();
    router.replace(qs ? `?${qs}` : "?", { scroll: false });
  }

  // ── stats for the KPI row ──
  const stats = useMemo(() => {
    const waits = visibleHandovers
      .map((h) => secondsSince(h.opened_at))
      .filter((s): s is number => s !== null);
    return {
      open: visibleHandovers.length,
      unassigned: visibleHandovers.filter((h) => !h.assigned_to).length,
      mine: visibleHandovers.filter((h) => h.assigned_to === currentCallerId).length,
      breaching: waits.filter((s) => s >= DAY).length,
      longest: waits.length ? Math.max(...waits) : null,
    };
  }, [visibleHandovers, currentCallerId]);

  const activeStats: StatItem[] = useMemo(
    () => [
      {
        label: "Open now",
        value: String(stats.open),
        tone: stats.open === 0 ? "positive" : stats.breaching > 0 ? "critical" : "warning",
        detail: stats.open === 0 ? "Queue is clear" : `${stats.unassigned} waiting for an owner`,
      },
      {
        label: "Longest wait",
        value: formatDuration(stats.longest),
        tone: stats.longest !== null && stats.longest >= DAY ? "critical" : "positive",
        detail: stats.longest !== null && stats.longest >= DAY ? "Past the 24h line" : "Inside the 24h line",
      },
      {
        label: "Breaching 24h",
        value: String(stats.breaching),
        tone: stats.breaching > 0 ? "critical" : "positive",
        detail: stats.open ? `of ${stats.open} open` : "Nothing open",
      },
      {
        label: role === "owner" ? "Unassigned" : "Assigned to me",
        value: String(role === "owner" ? stats.unassigned : stats.mine),
        tone: role === "owner" && stats.unassigned > 0 ? "warning" : "neutral",
        detail: role === "owner" ? "Nobody has picked these up" : "Yours to handle",
      },
    ],
    [stats, role]
  );

  const historyCards: StatItem[] = useMemo(
    () => [
      {
        label: "Resolved all-time",
        value: String(historyStats.total),
        detail: historyStats.total ? "Every handover closed by a human" : "Nothing resolved yet",
      },
      {
        label: "Median to resolve",
        value: formatDuration(historyStats.median_seconds),
        tone: historyStats.median_seconds !== null && historyStats.median_seconds > DAY ? "warning" : "positive",
        detail: "From handover to resolution",
      },
      {
        label: "Top resolver",
        value: historyStats.top_resolver ?? "Not recorded",
        detail: historyStats.top_resolver
          ? `${historyStats.top_resolver_count} of ${historyStats.total} resolved`
          : "No attributed resolutions yet",
      },
      {
        label: "Most common trigger",
        value: historyStats.top_reason ? (TRIGGERS[historyStats.top_reason]?.label ?? historyStats.top_reason) : "—",
        detail: historyStats.top_reason ? "Why the AI hands over most often" : "No triggers recorded yet",
      },
    ],
    [historyStats]
  );

  const myName = callers.find((c) => c.id === currentCallerId)?.name ?? currentCallerName ?? "You";

  async function handleResolve(handover: Handover) {
    if (!canReplyToConversations) return;
    const prev = handovers;
    setHandovers((hs) => hs.filter((h) => h.id !== handover.id));
    try {
      await resolveHandover(handover.id);
      toast.success("Escalation resolved", {
        duration: 8000,
        action: {
          label: "Undo",
          onClick: async () => {
            try {
              await reopenHandover(handover.id);
              toast.success("Reopened — it's back in the queue");
              load();
            } catch {
              toast.error("Couldn't undo — reopen it from History");
            }
          },
        },
      });
    } catch (err) {
      setHandovers(prev);
      toast.error(err instanceof Error ? err.message : "Couldn't resolve");
    }
  }

  async function handleAssign(handoverId: string, callerId: string, callerName: string) {
    setAssigningId(null);
    const prev = handovers;
    setHandovers((hs) =>
      hs.map((h) => (h.id === handoverId ? { ...h, assigned_to: callerId, caller_name: callerName } : h))
    );
    try {
      await assignHandover(handoverId, callerId);
      toast.success(`Assigned to ${callerName}`);
    } catch {
      setHandovers(prev);
      toast.error("Couldn't assign");
    }
  }

  async function handleClaim(handover: Handover) {
    if (!canReplyToConversations) return;
    if (!currentCallerId) {
      toast.error("A telecaller profile is required to pick up an escalation");
      return;
    }
    const prev = handovers;
    setHandovers((hs) =>
      hs.map((h) => (h.id === handover.id ? { ...h, assigned_to: currentCallerId, caller_name: myName } : h))
    );
    try {
      await assignHandover(handover.id, currentCallerId);
      toast.success("Claimed — you're handling this lead");
    } catch {
      setHandovers(prev);
      toast.error("Couldn't claim");
    }
  }

  const ACTIVE_COLUMNS: CsvColumn<Handover>[] = [
    { header: "Name", value: (h) => h.leads?.name },
    { header: "Phone", value: (h) => h.leads?.phone },
    { header: "Channel", value: (h) => channelLabel(h.leads?.source) },
    { header: "Interest", value: (h) => segmentLabel(h.leads?.segment) },
    { header: "Why it needs you", value: (h) => h.reason },
    { header: "Waiting since", value: (h) => istDateTime(h.opened_at) },
    { header: "Assigned to", value: (h) => (h.assigned_to ? h.caller_name ?? "Assigned" : "Unassigned") },
  ];
  const HISTORY_COLUMNS: CsvColumn<ResolvedHandover>[] = [
    { header: "Name", value: (h) => h.leads?.name },
    { header: "Phone", value: (h) => h.leads?.phone },
    { header: "Channel", value: (h) => channelLabel(h.leads?.source) },
    { header: "Interest", value: (h) => segmentLabel(h.leads?.segment) },
    { header: "Why it needed you", value: (h) => h.reason },
    { header: "Resolved by", value: (h) => h.resolved_by_name ?? "Not recorded" },
    { header: "Resolved at", value: (h) => istDateTime(h.resolved_at) },
    { header: "Time to resolve", value: (h) => formatDuration(h.duration_seconds) },
  ];

  const exportCount = tab === "active"
    ? pickedActive.size || filteredHandovers.length
    : pickedHistory.size || historyTotal;
  const exportPicked = tab === "active" ? pickedActive.size > 0 : pickedHistory.size > 0;

  async function handleExport() {
    if (exporting) return;
    setExporting(true);
    try {
      if (tab === "active") {
        const rows = pickedActive.size ? filteredHandovers.filter((h) => pickedActive.has(h.id)) : filteredHandovers;
        downloadCsv(`needs-you-${today()}.csv`, rows, ACTIVE_COLUMNS);
      } else {
        let rows: ResolvedHandover[];
        if (pickedHistory.size) {
          rows = historyRows.filter((r) => pickedHistory.has(r.id));
        } else {
          // Everything the History filters match, not just the loaded page.
          rows = [];
          for (let offset = 0; offset < 5000; offset += 100) {
            const page = await fetchHistory({
              limit: 100, offset, q: searchQuery.trim() || undefined,
              resolver: historyResolver || undefined, reason: historyReason || undefined,
            });
            rows.push(...page.data);
            if (rows.length >= page.total || page.data.length === 0) break;
          }
        }
        downloadCsv(`needs-you-history-${today()}.csv`, rows, HISTORY_COLUMNS);
      }
      toast.success("Export downloaded");
    } catch {
      toast.error("Couldn't export. Try again.");
    } finally {
      setExporting(false);
    }
  }

  const allActivePicked = filteredHandovers.length > 0 && filteredHandovers.every((h) => pickedActive.has(h.id));
  function toggleActive(id: string) {
    setPickedActive((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const readOnlyTitle = canReplyToConversations ? undefined : "You have read-only access to conversations";
  const QUICK_FILTERS = [
    { key: "all", label: "All" },
    { key: "unassigned", label: "Unassigned" },
    { key: "mine", label: "Mine" },
    { key: "breaching", label: "Over 24h" },
  ] as const;

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-background">
      {/* ── header + tabs ── */}
      <div className="flex-shrink-0 px-6 pt-6">
        <div className="flex flex-wrap items-center justify-between gap-x-8 gap-y-4">
          <div className="min-w-0 flex-shrink-0">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-100 to-primary-100 border border-primary-200/60 shadow-xs">
                <AlertTriangle size={18} className="text-[var(--primary-800)]" />
              </div>
              <div>
                <h2 className="font-display text-xl font-bold tracking-tight text-gray-900">Needs you</h2>
                <p className="font-body text-xs font-medium text-gray-500 mt-0.5">
                  Conversations the AI handed to a human.
                </p>
              </div>
            </div>
          </div>
          {!loading && <StatCards items={tab === "active" ? activeStats : historyCards} />}
        </div>

        <div className="-mx-6 mt-5 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-border/80 px-6 pb-2.5">
          <div className="flex items-center p-1 rounded-xl bg-primary-50/60 border border-primary-100/80 gap-1" role="tablist" aria-label="Escalation views">
            {([
              { key: "active", label: "Active", count: visibleHandovers.length },
              { key: "history", label: "History", count: null },
            ] as const).map((t) => (
              <button
                key={t.key}
                role="tab"
                aria-selected={tab === t.key}
                onClick={() => switchTab(t.key)}
                className={cn(
                  "flex items-center gap-1.5 px-3.5 py-1 rounded-lg font-label text-xs font-bold transition-all",
                  tab === t.key
                    ? "bg-white text-[var(--primary-800)] shadow-xs"
                    : "text-gray-500 hover:text-gray-900"
                )}
              >
                <span>{t.label}</span>
                {t.count !== null && t.count > 0 && (
                  <span
                    className={cn(
                      "rounded-full px-1.5 py-0.5 font-mono text-[10px] font-bold leading-none tabular-nums",
                      tab === t.key ? "bg-rose-500 text-white shadow-2xs" : "bg-primary-100 text-[var(--primary-800)]"
                    )}
                  >
                    {t.count}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Search + filters */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative h-8 w-[220px]">
              <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={tab === "active" ? "Search name, phone, reason…" : "Search name or phone…"}
                aria-label="Search escalations"
                className="h-8 w-full rounded-xl border border-primary-100/80 bg-white pl-8 pr-7 font-body text-xs text-gray-800 outline-none transition-all placeholder:text-gray-400 focus:border-[var(--primary-600)] focus:ring-2 focus:ring-[var(--primary-600)]/20 shadow-xs"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery("")}
                  aria-label="Clear search"
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
                >
                  <X size={12} />
                </button>
              )}
            </div>

            {tab === "active" ? (
              QUICK_FILTERS.map((f) => (
                <button
                  key={f.key}
                  onClick={() => setQuickFilter(f.key)}
                  aria-pressed={quickFilter === f.key}
                  className={cn(
                    "inline-flex h-8 items-center rounded-xl border px-3 font-label text-xs font-semibold transition-all shadow-xs",
                    quickFilter === f.key
                      ? "bg-primary hover:bg-primary-dark text-white border-transparent"
                      : "border-primary-100/80 bg-white text-gray-600 hover:border-primary-200 hover:bg-primary-50/50"
                  )}
                >
                  {f.label}
                </button>
              ))
            ) : (
              <>
                <Select
                  size="sm"
                  aria-label="Filter by resolver"
                  className="w-auto"
                  value={historyResolver}
                  onChange={setHistoryResolver}
                  options={[{ value: "", label: "Anyone" }, ...historyStats.resolvers.map((r) => ({ value: r, label: r }))]}
                />
                <Select
                  size="sm"
                  aria-label="Filter by reason"
                  className="w-auto"
                  value={historyReason}
                  onChange={setHistoryReason}
                  options={[{ value: "", label: "Any reason" }, ...historyStats.reasons.map((r) => ({ value: r, label: TRIGGERS[r]?.label ?? r }))]}
                />
              </>
            )}

            {canExport && (
              <button
                type="button"
                onClick={() => void handleExport()}
                disabled={exporting || exportCount === 0}
                title={exportPicked ? "Download the ticked leads as a spreadsheet" : "Download every lead these filters show"}
                className="inline-flex h-8 items-center gap-1.5 rounded-xl border border-primary-100/80 bg-white px-3 font-label text-xs font-semibold text-gray-700 shadow-xs transition-all hover:border-primary-200 hover:bg-primary-50/50 disabled:cursor-not-allowed disabled:opacity-45"
              >
                {exporting ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                {exportPicked ? `Export ${exportCount} selected` : `Export ${exportCount}`}
              </button>
            )}
          </div>
        </div>
      </div>

      {tab === "history" ? (
        <HistoryTab
          onOpenChat={onReply}
          canReply={canReplyToConversations}
          onReopened={load}
          search={searchQuery}
          resolver={historyResolver}
          reason={historyReason}
          onStatsChange={setHistoryStats}
          selectable={canExport}
          selected={pickedHistory}
          onSelectedChange={setPickedHistory}
          onRowsChange={onHistoryRows}
        />
      ) : (
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* ── list ── */}
          <div className="flex-1 overflow-y-auto px-6 py-4">
          {!loading && visibleHandovers.length === 0 ? (
            <TableEmpty
              icon={<CheckCircle2 size={26} className="text-success" />}
              title="All caught up"
              body="No conversations need your attention right now."
            />
          ) : !loading && filteredHandovers.length === 0 ? (
            <TableEmpty
              icon={<Search size={24} className="text-ink-muted" />}
              title="No matches"
              body="No open escalation matches your search or filter."
            />
          ) : (
            <div className="rounded-2xl border border-border/80 bg-surface shadow-card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[920px] border-collapse">
                  <thead>
                    <tr className="border-b border-border/70 bg-slate-50/70">
                      {canExport && (
                        <th className="w-10 py-3 pl-5">
                          <CheckTick
                            size="sm"
                            checked={allActivePicked}
                            indeterminate={!allActivePicked && filteredHandovers.some((h) => pickedActive.has(h.id))}
                            onChange={() => setPickedActive(allActivePicked ? new Set() : new Set(filteredHandovers.map((h) => h.id)))}
                            aria-label="Select all shown"
                          />
                        </th>
                      )}
                      <th className={cn("sticky top-0 z-10 whitespace-nowrap px-4 py-3 text-left font-heading text-[10px] font-bold uppercase tracking-[0.09em] text-slate-500", canExport ? "pl-6" : "pl-8")}>
                        Lead
                      </th>
                      <th className="sticky top-0 z-10 whitespace-nowrap px-4 py-3 text-left font-heading text-[10px] font-bold uppercase tracking-[0.09em] text-slate-500">
                        Channel
                      </th>
                      <th className="sticky top-0 z-10 whitespace-nowrap px-4 py-3 text-left font-heading text-[10px] font-bold uppercase tracking-[0.09em] text-slate-500">
                        Why Escalated
                      </th>
                      <th className="sticky top-0 z-10 whitespace-nowrap px-4 py-3 text-center font-heading text-[10px] font-bold uppercase tracking-[0.09em] text-slate-500 w-[130px]">
                        Waiting
                      </th>
                      <th className="sticky top-0 z-10 whitespace-nowrap px-4 py-3 text-left font-heading text-[10px] font-bold uppercase tracking-[0.09em] text-slate-500 w-[180px]">
                        Assigned
                      </th>
                      <th className="sticky top-0 z-10 whitespace-nowrap px-4 py-3 pr-8 text-right font-heading text-[10px] font-bold uppercase tracking-[0.09em] text-slate-500 w-[240px]">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  {loading ? (
                    <TableSkeleton columns={canExport ? 7 : 6} />
                  ) : (
                    <tbody>
                      {filteredHandovers.map((h) => {
                        const waited = secondsSince(h.opened_at);
                        const severity = severityForWait(waited);
                        const isMine = h.assigned_to === currentCallerId;
                        return (
                          <tr
                            key={h.id}
                            className="group border-b border-border-subtle/80 bg-surface transition-colors hover:bg-primary-50/20 last:border-b-0"
                          >
                            {canExport && (
                              <td className="w-10 py-3 pl-5 align-middle">
                                <CheckTick size="sm" checked={pickedActive.has(h.id)} onChange={() => toggleActive(h.id)} aria-label="Select this lead" />
                              </td>
                            )}
                            <td className={cn("relative px-4 py-3 text-left align-middle", canExport ? "pl-6" : "pl-8")}>
                              <span
                                className={cn(
                                  "absolute top-1/2 -translate-y-1/2 w-1 h-8 rounded-full transition-all",
                                  canExport ? "left-1.5" : "left-3",
                                  SLA_BAR[severity]
                                )}
                                title={SLA_TITLE[severity]}
                              />
                              <LeadCell lead={h.leads} />
                            </td>
                            <td className="px-4 py-3 text-left align-middle">
                              <ChannelCell lead={h.leads} />
                            </td>
                            <td className="px-4 py-3 text-left align-middle">
                              <TriggerChip reason={h.reason} />
                            </td>
                            <td className="px-4 py-3 text-center align-middle">
                              <DurationCell
                                text={formatDuration(waited)}
                                severity={severity}
                                sub={new Date(h.opened_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}
                              />
                            </td>
                            <td className="px-4 py-3 text-left align-middle">
                              <PersonCell name={h.assigned_to ? h.caller_name ?? "Assigned" : null} empty="Unassigned" />
                            </td>
                            <td className="px-4 py-3 pr-8 text-right align-middle">
                              <div className="flex items-center justify-end gap-1.5">
                                {role === "owner" || isMine ? (
                                  <>
                                    <button
                                      onClick={() => canReplyToConversations && onReply(h.lead_id)}
                                      disabled={!canReplyToConversations}
                                      title={readOnlyTitle}
                                      className="inline-flex h-7 w-[82px] items-center justify-center gap-1.5 rounded-lg border border-primary bg-primary font-label text-[11px] font-bold text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-40"
                                    >
                                      <MessageSquare size={13} /> Reply
                                    </button>
                                    <button
                                      onClick={() => handleResolve(h)}
                                      disabled={!canReplyToConversations}
                                      title={readOnlyTitle}
                                      className="inline-flex h-7 w-[92px] items-center justify-center gap-1.5 rounded-lg border border-emerald-200 bg-surface font-label text-[11px] font-bold text-success transition-colors hover:border-success hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-40"
                                    >
                                      <CheckCircle2 size={13} /> Resolve
                                    </button>
                                  </>
                                ) : (
                                  <button
                                    onClick={() => handleClaim(h)}
                                    disabled={!canReplyToConversations || !currentCallerId}
                                    title={
                                      !canReplyToConversations
                                        ? readOnlyTitle
                                        : !currentCallerId
                                          ? "A telecaller profile is required to pick up an escalation"
                                          : undefined
                                    }
                                    className="inline-flex h-7 w-[182px] items-center justify-center gap-1.5 rounded-lg border border-primary bg-primary font-label text-[11px] font-bold text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-40"
                                  >
                                    <MessageSquare size={13} /> Pick up
                                  </button>
                                )}

                                {role === "owner" && (
                                  <div className="relative" ref={assigningId === h.id ? dropdownRef : null}>
                                    <button
                                      onClick={() => setAssigningId(assigningId === h.id ? null : h.id)}
                                      disabled={!canReplyToConversations}
                                      title={canReplyToConversations ? "Assign to a telecaller" : readOnlyTitle}
                                      aria-label="Assign to a telecaller"
                                      className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-border bg-surface text-ink transition-colors hover:border-ink-muted disabled:cursor-not-allowed disabled:opacity-40"
                                    >
                                      <UserCog size={13} />
                                    </button>
                                    {assigningId === h.id && (
                                      <div className="absolute right-0 top-full z-30 mt-1.5 min-w-[180px] rounded-xl border border-border bg-surface py-1 text-left shadow-card-hover">
                                        <p className="px-3 py-1 font-heading text-[10px] font-semibold uppercase tracking-[0.09em] text-ink-muted">
                                          Assign to
                                        </p>
                                        <div className="my-0.5 border-t border-border-subtle" />
                                        {callers.length === 0 ? (
                                          <p className="px-3 py-2 font-body text-xs text-ink-muted">No active callers</p>
                                        ) : (
                                          callers.map((c) => (
                                            <button
                                              key={c.id}
                                              onClick={() => handleAssign(h.id, c.id, c.name)}
                                              className="w-full px-3 py-2 text-left font-body text-xs text-ink transition-colors hover:bg-primary-light hover:text-primary"
                                            >
                                              {c.name}
                                            </button>
                                          ))
                                        )}
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  )}
                </table>
              </div>
            </div>
          )}
          </div>
        </div>
      )}
    </div>
  );
}
