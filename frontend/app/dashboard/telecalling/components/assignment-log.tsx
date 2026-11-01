"use client";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Download, RefreshCw, ArrowRight, ClipboardList } from "lucide-react";
import { api, Caller, AssignmentLogEntry, AssignmentLogSummary } from "@/lib/api";
import { formatPhone, timeAgo } from "@/lib/utils";

const SEGMENT_LABEL: Record<string, string> = { A: "Hot", B: "Warm", C: "Cold", D: "Not Interested" };
const SEGMENT_STYLE: Record<string, string> = {
  A: "bg-red-50 text-red-600 border-red-200",
  B: "bg-amber-50 text-amber-600 border-amber-200",
  C: "bg-sky-50 text-sky-600 border-sky-200",
  D: "bg-gray-100 text-gray-500 border-gray-200",
};
const REASON_LABEL: Record<string, string> = {
  created: "On entry", scored: "Scored up", manual: "Manual edit",
  sweep: "Sweep", bot_flow: "Bot flow", ai_agent: "AI agent",
  autopilot: "Autopilot", call_callback: "Call → callback", call_converted: "Call → won",
  caller_unavailable: "Caller away", backlog_claim: "Claimed on login",
  escalation: "Escalation", round_robin: "Round-robin",
};

const PAGE_SIZE = 50;

export default function AssignmentLog({ callers }: { callers: Caller[] }) {
  const [entries, setEntries] = useState<AssignmentLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [summary, setSummary] = useState<AssignmentLogSummary | null>(null);

  const [callerFilter, setCallerFilter] = useState("");
  const [segmentFilter, setSegmentFilter] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.assignmentLog.list({
        page,
        limit: PAGE_SIZE,
        caller_id: callerFilter || undefined,
        segment: segmentFilter || undefined,
      });
      setEntries(Array.isArray(res.data) ? res.data : []);
      setTotal(res.meta?.total || 0);
    } catch {
      toast.error("Failed to load assignment log");
    } finally {
      setLoading(false);
    }
  }, [page, callerFilter, segmentFilter]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.assignmentLog.summary().then(setSummary).catch(() => {}); }, []);

  async function handleExport() {
    setExporting(true);
    try {
      await api.assignmentLog.exportCsv({ caller_id: callerFilter || undefined, segment: segmentFilter || undefined });
    } catch {
      toast.error("Export failed");
    } finally {
      setExporting(false);
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const callerSummaryRows = summary
    ? Object.entries(summary.by_caller).map(([id, value]) => (
        typeof value === "number"
          ? { id, name: id, count: value }
          : { id, name: value.caller_name || id, count: value.count || 0 }
      ))
    : [];

  return (
    <div>
      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="bg-surface rounded-card p-5 shadow-card ring-1 ring-[#c4c7c7]/15">
          <div className="p-2 rounded-xl bg-primary/10 w-fit mb-2"><ClipboardList size={16} className="text-primary" /></div>
          <span className="font-display text-3xl font-bold text-on-surface">{summary?.assigned_today ?? "—"}</span>
          <span className="block font-label text-xs text-on-surface-muted mt-1">Assigned Today</span>
        </div>
        <div className="bg-surface rounded-card p-5 shadow-card ring-1 ring-[#c4c7c7]/15">
          <span className="block font-label text-[10px] uppercase tracking-widest text-on-surface-muted mb-2">By Caller (today)</span>
          <div className="space-y-1">
            {callerSummaryRows.length > 0
              ? callerSummaryRows.slice(0, 4).map((row) => (
                  <div key={row.id} className="flex justify-between gap-3 font-body text-sm">
                    <span className="truncate text-on-surface">{row.name}</span>
                    <span className="font-semibold text-on-surface">{row.count}</span>
                  </div>
                ))
              : <span className="font-body text-sm text-on-surface-muted">{summary ? "No assignments yet" : "—"}</span>}
          </div>
        </div>
        <div className="bg-surface rounded-card p-5 shadow-card ring-1 ring-[#c4c7c7]/15">
          <span className="block font-label text-[10px] uppercase tracking-widest text-on-surface-muted mb-2">By Segment (today)</span>
          <div className="flex flex-wrap gap-2">
            {summary && Object.keys(summary.by_segment).length > 0
              ? Object.entries(summary.by_segment).map(([seg, n]) => (
                  <span key={seg} className={`px-2 py-1 rounded-lg border font-label text-xs font-semibold ${SEGMENT_STYLE[seg] || SEGMENT_STYLE.C}`}>
                    {SEGMENT_LABEL[seg] || seg}: {n}
                  </span>
                ))
              : <span className="font-body text-sm text-on-surface-muted">{summary ? "No assignments yet" : "—"}</span>}
          </div>
        </div>
      </div>

      {/* Filters + export */}
      <div className="mb-3 flex flex-wrap items-end gap-2.5 rounded-2xl border border-surface-mid/80 bg-white/95 p-3 shadow-sm">
        <div className="w-full sm:w-[170px]">
          <label className="mb-1 block font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">Caller</label>
          <select value={callerFilter} onChange={(e) => { setPage(1); setCallerFilter(e.target.value); }}
            className="h-9 w-full cursor-pointer appearance-none rounded-xl border border-surface-mid bg-white px-3 pr-8 font-body text-xs font-semibold text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200">
            <option value="">All callers</option>
            {callers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div className="w-full sm:w-[160px]">
          <label className="mb-1 block font-label text-[9px] font-bold uppercase tracking-wider text-on-surface-muted">Segment</label>
          <select value={segmentFilter} onChange={(e) => { setPage(1); setSegmentFilter(e.target.value); }}
            className="h-9 w-full cursor-pointer appearance-none rounded-xl border border-surface-mid bg-white px-3 pr-8 font-body text-xs font-semibold text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200">
            <option value="">All segments</option>
            <option value="A">Hot</option>
            <option value="B">Warm</option>
            <option value="C">Cold</option>
          </select>
        </div>
        <div className="ml-auto flex w-full items-center justify-end gap-2 sm:w-auto">
          <button onClick={load} disabled={loading}
            className="flex h-9 items-center gap-1.5 rounded-full border border-surface-mid bg-white px-3 font-label text-xs font-bold text-on-surface shadow-sm transition-colors hover:border-primary-200 hover:bg-primary-50 hover:text-primary disabled:opacity-50">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
          <button onClick={handleExport} disabled={exporting}
            className="flex h-9 items-center gap-1.5 rounded-full border border-primary-200 bg-primary-50 px-3.5 font-label text-xs font-bold text-primary shadow-sm transition-colors hover:bg-primary-100 disabled:opacity-50">
            <Download size={13} /> {exporting ? "Exporting…" : "Export CSV"}
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-2xl bg-surface shadow-sm ring-1 ring-[#c4c7c7]/15">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-surface-mid bg-surface-low/60">
              {["Lead", "Segment", "Assigned to", "Reason", "When"].map((h) => (
                <th key={h} className="px-4 py-2.5 font-label text-[9px] font-bold uppercase tracking-widest text-on-surface-muted">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-on-surface-muted font-body text-sm">Loading…</td></tr>
            ) : entries.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-on-surface-muted font-body text-sm">No assignments recorded yet.</td></tr>
            ) : entries.map((e) => (
              <tr key={e.id} className="border-b border-surface-mid/50 hover:bg-surface-subtle/40">
                <td className="px-4 py-2.5">
                  <span className="block font-body text-sm font-medium text-on-surface">{e.lead_name || "—"}</span>
                  <span className="block font-body text-xs text-on-surface-muted">{e.lead_phone ? formatPhone(e.lead_phone) : ""}</span>
                </td>
                <td className="px-4 py-2.5">
                  <span className={`px-2 py-0.5 rounded-lg border font-label text-xs font-semibold ${SEGMENT_STYLE[e.segment || "C"] || SEGMENT_STYLE.C}`}>
                    {SEGMENT_LABEL[e.segment || "C"] || e.segment}
                  </span>
                </td>
                <td className="px-4 py-2.5 font-body text-sm text-on-surface">
                  {e.event_type === "reassigned" && e.prev_caller_name ? (
                    <span className="flex items-center gap-1.5">
                      <span className="text-on-surface-muted line-through">{e.prev_caller_name}</span>
                      <ArrowRight size={12} className="text-amber-500" />
                      <span className="font-medium">{e.caller_name || "—"}</span>
                    </span>
                  ) : (
                    <span className="font-medium">{e.caller_name || "—"}</span>
                  )}
                </td>
                <td className="px-4 py-2.5 font-body text-xs text-on-surface-muted">
                  {REASON_LABEL[e.reason || ""] || e.reason || "—"}
                  <span className="block text-[10px] opacity-70">{e.method}</span>
                </td>
                <td className="px-4 py-2.5 font-body text-xs text-on-surface-muted whitespace-nowrap">{timeAgo(e.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between mt-4">
          <span className="font-body text-xs text-on-surface-muted">{total} total · page {page}/{totalPages}</span>
          <div className="flex gap-2">
            <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}
              className="px-3 py-1.5 rounded-lg border border-surface-mid font-label text-sm disabled:opacity-40 hover:border-primary/40">Prev</button>
            <button disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}
              className="px-3 py-1.5 rounded-lg border border-surface-mid font-label text-sm disabled:opacity-40 hover:border-primary/40">Next</button>
          </div>
        </div>
      )}
    </div>
  );
}
