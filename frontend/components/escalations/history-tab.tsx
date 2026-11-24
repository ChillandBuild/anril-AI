"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Info, MessageSquare, RotateCcw, Search } from "lucide-react";
import { toast } from "sonner";
import { formatDateTime, formatDuration } from "@/lib/utils";
import {
  EMPTY_HISTORY_STATS,
  fetchHistory,
  reopenHandover,
  severityForWait,
  type HistoryStats,
  type ResolvedHandover,
} from "@/lib/escalations";

import { ChannelCell, DurationCell, LeadCell, PersonCell, TableEmpty, TableSkeleton, TriggerChip } from "@/components/escalations/atoms";
import { CheckTick } from "@/components/ui/controls";
import { Pagination } from "@/components/ui/Pagination";
import { PAGE_SIZE } from "@/lib/pagination";

interface HistoryTabProps {
  onOpenChat: (leadId: string) => void;
  canReply: boolean;
  /** Reopening puts a handover back in the active pool, so the parent has to
   *  refresh its list and the rail badge. */
  onReopened: () => void;
  /** Search and filters live in the shared page header, so they arrive as
   *  props; the raw stats go back up because the header renders both the KPI
   *  cards and the resolver/reason dropdown options from them. */
  search: string;
  resolver: string;
  reason: string;
  onStatsChange: (stats: HistoryStats) => void;
  /** Owner-only: tick rows to export them. The parent keeps the selection and the Export button. */
  selectable?: boolean;
  selected?: Set<string>;
  onSelectedChange?: (next: Set<string>) => void;
  /** The loaded rows and the total for the current filters, for the parent's Export. */
  onRowsChange?: (rows: ResolvedHandover[], total: number) => void;
}

export function HistoryTab({
  onOpenChat, canReply, onReopened, search, resolver, reason, onStatsChange,
  selectable = false, selected, onSelectedChange, onRowsChange,
}: HistoryTabProps) {
  const [rows, setRows] = useState<ResolvedHandover[]>([]);
  const [stats, setStats] = useState<HistoryStats>(EMPTY_HISTORY_STATS);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  // Only the newest request may write to the list (a filter can change while one is in flight).
  const requestId = useRef(0);
  const [error, setError] = useState(false);
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(search.trim()), 300);
    return () => clearTimeout(handle);
  }, [search]);

  // Any filter change goes back to page 1.
  useEffect(() => {
    setPage(1);
  }, [debounced, resolver, reason]);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    try {
      const res = await fetchHistory({
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
        q: debounced || undefined,
        resolver: resolver || undefined,
        reason: reason || undefined,
      });
      if (id !== requestId.current) return;
      setRows(res.data);
      setTotal(res.total);
      setStats(res.stats);
      setError(false);
    } catch {
      if (id === requestId.current) setError(true);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [debounced, resolver, reason, page]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleReopen(row: ResolvedHandover) {
    if (!canReply) return;
    const prev = rows;
    setRows((rs) => rs.filter((r) => r.id !== row.id));
    setTotal((t) => Math.max(0, t - 1));
    try {
      await reopenHandover(row.id);
      toast.success("Reopened — it's back in the active queue");
      onReopened();
    } catch (err) {
      setRows(prev);
      setTotal((t) => t + 1);
      toast.error(err instanceof Error ? err.message : "Couldn't reopen");
    }
  }

  useEffect(() => {
    onStatsChange(stats);
  }, [stats, onStatsChange]);

  useEffect(() => {
    onRowsChange?.(rows, total);
  }, [rows, total, onRowsChange]);

  const picked = selected ?? new Set<string>();
  const allPicked = rows.length > 0 && rows.every((r) => picked.has(r.id));
  function togglePick(id: string) {
    const next = new Set(picked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onSelectedChange?.(next);
  }

  const filtered = Boolean(debounced || resolver || reason);
  const hasUnattributed = rows.some((r) => !r.resolved_by_name);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">

      {/* ── list (only this scrolls; filters stay in the header) ── */}
      <div className="flex flex-1 flex-col overflow-y-auto px-6 py-4">
      {error ? (
        <TableEmpty
          icon={<Info size={24} className="text-ink-muted" />}
          title="Couldn't load history"
          body="The request didn't come back. It'll retry when you switch tabs."
        />
      ) : !loading && rows.length === 0 ? (
        <TableEmpty
          icon={filtered ? <Search size={24} className="text-ink-muted" /> : <CheckCircle2 size={24} className="text-ink-muted" />}
          title={filtered ? "No matches" : "Nothing resolved yet"}
          body={
            filtered
              ? "No resolved escalation matches those filters."
              : "Once you resolve an escalation it lands here, with who closed it and how long it took."
          }
        />
      ) : (
        <>
          {/* shrink-0: in this scrolling column a shrinkable card clipped the last rows instead of scrolling. */}
          <div className="shrink-0 rounded-2xl border border-border/80 bg-surface shadow-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1040px] border-collapse">
                <thead>
                  <tr className="border-b border-border/70 bg-slate-50/70">
                    {selectable && (
                      <th className="w-10 py-3 pl-5">
                        <CheckTick
                          size="sm"
                          checked={allPicked}
                          indeterminate={!allPicked && rows.some((r) => picked.has(r.id))}
                          onChange={() => onSelectedChange?.(allPicked ? new Set() : new Set(rows.map((r) => r.id)))}
                          aria-label="Select all shown"
                        />
                      </th>
                    )}
                    <th className={`sticky top-0 z-10 whitespace-nowrap px-4 py-3 ${selectable ? "pl-3" : "pl-8"} text-left font-heading text-[10px] font-bold uppercase tracking-[0.09em] text-slate-500`}>
                      Lead
                    </th>
                    <th className="sticky top-0 z-10 whitespace-nowrap px-4 py-3 text-left font-heading text-[10px] font-bold uppercase tracking-[0.09em] text-slate-500">
                      Channel
                    </th>
                    <th className="sticky top-0 z-10 whitespace-nowrap px-4 py-3 text-left font-heading text-[10px] font-bold uppercase tracking-[0.09em] text-slate-500">
                      Why Escalated
                    </th>
                    <th className="sticky top-0 z-10 whitespace-nowrap px-4 py-3 text-left font-heading text-[10px] font-bold uppercase tracking-[0.09em] text-slate-500 w-[180px]">
                      Resolved By
                    </th>
                    <th className="sticky top-0 z-10 whitespace-nowrap px-4 py-3 text-center font-heading text-[10px] font-bold uppercase tracking-[0.09em] text-slate-500 w-[140px]">
                      Resolved
                    </th>
                    <th className="sticky top-0 z-10 whitespace-nowrap px-4 py-3 text-center font-heading text-[10px] font-bold uppercase tracking-[0.09em] text-slate-500 w-[140px]">
                      Time to Resolve
                    </th>
                    <th className="sticky top-0 z-10 whitespace-nowrap px-4 py-3 pr-8 text-right font-heading text-[10px] font-bold uppercase tracking-[0.09em] text-slate-500 w-[210px]">
                      Actions
                    </th>
                  </tr>
                </thead>
                {loading ? (
                  <TableSkeleton columns={selectable ? 8 : 7} />
                ) : (
                  <tbody>
                    {rows.map((row) => (
                      <tr
                        key={row.id}
                        className="group border-b border-border-subtle/80 bg-surface transition-colors hover:bg-primary-50/20 last:border-b-0"
                      >
                        {selectable && (
                          <td className="w-10 py-3 pl-5 align-middle">
                            <CheckTick size="sm" checked={picked.has(row.id)} onChange={() => togglePick(row.id)} aria-label="Select this lead" />
                          </td>
                        )}
                        <td className={`px-4 py-3 ${selectable ? "pl-3" : "pl-8"} text-left align-middle`}>
                          <LeadCell lead={row.leads} />
                        </td>
                        <td className="px-4 py-3 text-left align-middle">
                          <ChannelCell lead={row.leads} />
                        </td>
                        <td className="px-4 py-3 text-left align-middle">
                          <TriggerChip reason={row.reason} />
                        </td>
                        <td className="px-4 py-3 text-left align-middle">
                          <PersonCell name={row.resolved_by_name} empty="Not recorded" />
                        </td>
                        <td className="px-4 py-3 text-center align-middle">
                          <span className="font-mono text-xs text-slate-600 font-medium">
                            {row.resolved_at ? formatDateTime(row.resolved_at) : "—"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-center align-middle">
                          <DurationCell
                            text={formatDuration(row.duration_seconds)}
                            severity={severityForWait(row.duration_seconds)}
                          />
                        </td>
                        <td className="px-4 py-3 pr-8 text-right align-middle">
                          <div className="flex items-center justify-end gap-1.5">
                            <button
                              onClick={() => onOpenChat(row.lead_id)}
                              className="inline-flex h-7 w-[100px] items-center justify-center gap-1.5 rounded-lg border border-border bg-surface font-label text-[11px] font-bold text-ink transition-colors hover:border-ink-muted"
                            >
                              <MessageSquare size={13} /> Open chat
                            </button>
                            <button
                              onClick={() => handleReopen(row)}
                              disabled={!canReply}
                              title={canReply ? "Put this back in the active queue" : "You have read-only access to conversations"}
                              className="inline-flex h-7 w-[86px] items-center justify-center gap-1.5 rounded-lg border border-border bg-surface font-label text-[11px] font-bold text-ink-secondary transition-colors hover:border-ink-muted hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
                            >
                              <RotateCcw size={12} /> Reopen
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                )}
              </table>
            </div>
            <Pagination page={page} total={total} onPageChange={setPage} noun="chats" />
          </div>

          {hasUnattributed && (
            <div className="mx-6 mb-6 flex shrink-0 items-start gap-2 rounded-[9px] border border-amber-200 bg-amber-50 px-3.5 py-2.5">
              <Info size={14} className="mt-px flex-shrink-0 text-amber-700" />
              <p className="font-body text-[11.5px] leading-relaxed text-amber-800">
                Escalations resolved before resolver tracking shipped show as <em>Not recorded</em>. Everything
                resolved from now on is attributed.
              </p>
            </div>
          )}
        </>
      )}
      </div>
    </div>
  );
}
