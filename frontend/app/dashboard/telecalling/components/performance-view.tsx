"use client";

import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import {
  X, Check, Download, ChevronUp, ChevronDown, Loader2, ShieldAlert,
} from "lucide-react";
import { api, API_URL, getAuthHeaders, type Caller, type TelecallingAnalyticsExtended } from "@/lib/api";
import { istTodayIso } from "@/lib/utils";
import { showsEvaluation } from "@/lib/evaluation-visibility";
import { formatTalk } from "./sections/performance-format";
import TeamAttendanceGrid from "../../team/TeamAttendanceGrid";
import LiveAgentStatus from "./sections/LiveAgentStatus";
import FeedbackOversight from "./sections/FeedbackOversight";
import PerformanceHeadline from "./sections/PerformanceHeadline";
import PerformanceKpis from "./sections/PerformanceKpis";
import PerformanceInsights from "./sections/PerformanceInsights";
import OutcomeBreakdown from "./sections/OutcomeBreakdown";
import CallsPerHour from "./sections/CallsPerHour";
import ShiftTimeline from "./sections/ShiftTimeline";
import NeedsAttention from "./sections/NeedsAttention";
import QaReviewFeed from "./sections/QaReviewFeed";
import BulkAssignment from "./sections/BulkAssignment";
import LeadProfileModal from "./sections/LeadProfileModal";
import { useAuthRole } from "../../contexts/AuthRoleContext";

type SortField =
  | "name" | "calls_today" | "connect_rate" | "avg_talk_seconds" | "idle_minutes_today" | "overall_score";

interface PerformanceViewProps {
  callers: Caller[];
  adminCaller?: Caller | null;
  /** From team/list, prefetched server-side -- the trustworthy tri-state
   * source for evaluation gating. undefined = not loaded yet. */
  callingProvider?: "telecmi" | "sim_basic";
  /** Show only this team's telecallers (callers.team_id). null/undefined = everyone. */
  teamFilter?: string | null;
}

export default function PerformanceView({ callers, adminCaller, callingProvider, teamFilter }: PerformanceViewProps) {
  const { role, roleSlug, permissions } = useAuthRole();
  const canManageTeam = role === "owner" || permissions.includes("team.manage");
  // A Team leader has team.manage (to work their team) but cannot change client-wide shift settings.
  const canChangeShifts = canManageTeam && roleSlug !== "team_leader";
  const canDownload = role === "owner" || permissions.includes("leads.download");
  const [stats, setStats] = useState<TelecallingAnalyticsExtended | null>(null);
  const [loadingStats, setLoadingStats] = useState(true);
  const [callersList, setCallersList] = useState<Caller[]>(callers);
  const [selectedCallerId, setSelectedCallerId] = useState<string | null>(null);

  // Daily Target inline editing
  const [editingTarget, setEditingTarget] = useState<Record<string, number>>({});
  const [updatingTargetId, setUpdatingTargetId] = useState<string | null>(null);

  // Leaderboard sorting
  const [sortField, setSortField] = useState<SortField>("calls_today");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");

  // Overall stats date-range filter
  const [statsFrom, setStatsFrom] = useState<string>(istTodayIso());
  const [statsTo, setStatsTo] = useState<string>(istTodayIso());

  // CSV Export
  const [exportSince, setExportSince] = useState<string>(istTodayIso());
  const [exportUntil, setExportUntil] = useState<string>(istTodayIso());
  const [exporting, setExporting] = useState(false);

  // Shift config
  const [shiftConfig, setShiftConfig] = useState<{ shift_mode: "common" | "individual"; shift_start_hour: number; shift_end_hour: number }>({
    shift_mode: "common", shift_start_hour: 9, shift_end_hour: 19,
  });

  // Lead profile modal
  const [viewingLeadId, setViewingLeadId] = useState<string | null>(null);

  // Tools zone (collapsed by default — keeps the report clean)
  const [toolsOpen, setToolsOpen] = useState(false);

  const loadPerformanceStats = useCallback(async () => {
    setLoadingStats(true);
    try {
      const data = await api.analytics.telecallingExtended({ from: statsFrom, to: statsTo });
      setStats(data);
    } catch (err) {
      console.error("Failed to load telecalling extended stats:", err);
      toast.error("Failed to load performance metrics");
    } finally {
      setLoadingStats(false);
    }
  }, [statsFrom, statsTo]);

  const loadCallers = useCallback(async () => {
    try {
      const res = await api.callers.list();
      setCallersList(res.data);
    } catch (err) {
      console.error("Failed to load callers:", err);
    }
  }, []);

  useEffect(() => {
    loadPerformanceStats();
    loadCallers();
  }, [loadPerformanceStats, loadCallers]);

  // Fetch telecalling config for shift settings
  useEffect(() => {
    (async () => {
      try {
        const auth = await getAuthHeaders();
        const res = await fetch(`${API_URL}/api/v1/settings/telecalling-config`, { headers: auth });
        if (res.ok) {
          const data = await res.json();
          setShiftConfig({
            shift_mode: data.shift_mode || "common",
            shift_start_hour: data.shift_start_hour ?? 9,
            shift_end_hour: data.shift_end_hour ?? 19,
          });
        }
      } catch {}
    })();
  }, []);

  async function handleShiftConfigSave(config: typeof shiftConfig) {
    if (!canChangeShifts) return;
    const updated = await api.team.updateShiftConfig(config);
    setShiftConfig(updated);
    toast.success("Shift config saved");
  }

  const handleUpdateTarget = async (callerId: string) => {
    const targetVal = editingTarget[callerId];
    if (targetVal === undefined) return;
    setUpdatingTargetId(callerId);
    try {
      await api.callers.updateTarget(callerId, targetVal);
      toast.success("Daily target updated successfully");
      setCallersList((prev) => prev.map((c) => (c.id === callerId ? { ...c, target: targetVal } : c)));
      const nextEditing = { ...editingTarget };
      delete nextEditing[callerId];
      setEditingTarget(nextEditing);
    } catch (err) {
      console.error("Failed to update target:", err);
      toast.error("Failed to update target");
    } finally {
      setUpdatingTargetId(null);
    }
  };

  const handleExportCsv = async () => {
    setExporting(true);
    try {
      await api.analytics.exportTelecallingCsv(exportSince, exportUntil);
      toast.success("CSV download started");
    } catch (err) {
      console.error("Failed to export telecalling CSV:", err);
      toast.error("Failed to export CSV report");
    } finally {
      setExporting(false);
    }
  };

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDirection("desc");
    }
  };

  const getSortedPerformers = () => {
    if (!stats || !stats.per_caller) return [];
    const callerIds = new Set(callersList.filter((c) => !teamFilter || c.team_id === teamFilter).map((c) => c.id));
    return [...stats.per_caller].filter((p) => callerIds.has(p.caller_id)).sort((a, b) => {
      let valA: string | number = 0;
      let valB: string | number = 0;
      if (sortField === "name") {
        valA = a.name.toLowerCase();
        valB = b.name.toLowerCase();
      } else if (sortField === "calls_today") {
        valA = a.calls_today || 0;
        valB = b.calls_today || 0;
      } else if (sortField === "connect_rate") {
        valA = a.connect_rate || 0;
        valB = b.connect_rate || 0;
      } else if (sortField === "avg_talk_seconds") {
        valA = a.avg_talk_seconds || 0;
        valB = b.avg_talk_seconds || 0;
      } else if (sortField === "idle_minutes_today") {
        valA = a.idle_minutes_today || 0;
        valB = b.idle_minutes_today || 0;
      } else if (sortField === "overall_score") {
        valA = a.overall_score || 0;
        valB = b.overall_score || 0;
      }
      if (valA < valB) return sortDirection === "asc" ? -1 : 1;
      if (valA > valB) return sortDirection === "asc" ? 1 : -1;
      return 0;
    });
  };

  const selectedCaller = callersList.find((c) => c.id === selectedCallerId) ?? null;
  const selectedCallerName = selectedCaller?.name;
  const callerStats = stats?.per_caller?.find((p) => p.caller_id === selectedCallerId);
  const flaggedCount = (stats?.per_caller || []).filter((c) => c.bunking_flag).length;
  const today = istTodayIso();
  const isTodayView = statsFrom === today && statsTo === today;
  // SIM clients get no evaluation at all: no score column, no QA review feed.
  // Unknown (still loading) and SIM both hide -- nothing about evaluation can
  // flash in before the tenant's calling provider is confirmed.
  const evaluationVisible = showsEvaluation(callingProvider);
  const leaderboardColumnCount = evaluationVisible ? 8 : 7;
  const sortIcon = (field: SortField) =>
    sortField === field
      ? (sortDirection === "asc" ? <ChevronUp size={10} className="inline ml-1" /> : <ChevronDown size={10} className="inline ml-1" />)
      : null;

  return (
    <div className="space-y-8 pb-12">
      {/* 1. Daily headline */}
      <PerformanceHeadline stats={stats} loading={loadingStats} flaggedCount={flaggedCount} isTodayView={isTodayView} />

      {/* Call-scoring warnings (recorded TeleCMI calls only), admins only */}
      {evaluationVisible && canManageTeam && <NeedsAttention onViewLead={setViewingLeadId} />}

      {/* Live agent status strip */}
      <LiveAgentStatus
        callers={callersList}
        adminCaller={adminCaller ?? null}
        selectedCallerId={selectedCallerId}
        onSelectCaller={setSelectedCallerId}
        statsFrom={statsFrom}
        statsTo={statsTo}
        onStatsFromChange={setStatsFrom}
        onStatsToChange={setStatsTo}
        onCallersChange={setCallersList}
        shiftConfig={shiftConfig}
        onShiftConfigSave={handleShiftConfigSave}
        callingProvider={callingProvider ?? "telecmi"}
        canManageShifts={canChangeShifts}
      />

      {callingProvider === "sim_basic" && role === "owner" && <FeedbackOversight />}

      {/* Selection indicator */}
      <div className="flex items-center gap-2 text-xs">
        {selectedCallerId ? (
          <>
            <span className="font-body text-[#475569]">
              Showing: <span className="font-bold text-[#13284A]">{selectedCallerName}</span>
            </span>
            <button
              onClick={() => setSelectedCallerId(null)}
              className="flex items-center gap-1 px-2 py-0.5 rounded-full border border-[#e2e8f0] text-[#94a3b8] hover:text-[#1e293b] hover:bg-[#f8fafc] transition-colors text-[10px] font-bold"
            >
              <X size={10} /> Clear
            </button>
          </>
        ) : (
          <span className="font-body text-[#475569]">
            Showing: <span className="font-bold text-[#13284A]">Team Overview</span>
          </span>
        )}
      </div>

      {/* 2. KPI tiles with deltas */}
      <PerformanceKpis
        stats={stats}
        callerStats={callerStats}
        selectedCallerId={selectedCallerId}
        loading={loadingStats}
        showDeltas={isTodayView}
        callingProvider={callingProvider}
      />

      {/* 3. Results — team-level outcome distribution + hourly volume (team view only) */}
      {!selectedCallerId && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          <OutcomeBreakdown stats={stats} />
          <CallsPerHour stats={stats} />
        </div>
      )}

      {/* 4. Auto-insights row (team view only) */}
      {!selectedCallerId && <PerformanceInsights stats={stats} showComparison={isTodayView} />}

      {/* 4. Agent Leaderboard (unchanged sortable table) */}
      <div className="bg-surface rounded-card p-6 shadow-card ring-1 ring-[#c4c7c7]/15">
        <div className="flex items-center justify-between mb-5 flex-wrap gap-4">
          <div>
            <h2 className="font-display text-base font-bold text-primary">Agent Performance Leaderboard</h2>
            <p className="font-label text-xs text-on-surface-muted">
              {evaluationVisible
                ? "Sort by connect rate, idle time, or average call score to manage team output."
                : "Sort by connect rate or idle time to manage team output."}
            </p>
          </div>
          {canDownload && (
          <div className="flex items-center gap-1.5 bg-[#f8fafc] p-1.5 rounded-xl border border-[#e2e8f0]">
            <span className="font-label text-[10px] text-[#475569] font-bold uppercase pl-1">Export Performance:</span>
            <input
              type="date"
              value={exportSince}
              onChange={(e) => setExportSince(e.target.value)}
              className="px-1.5 py-0.5 rounded bg-white border border-[#e2e8f0] font-body text-xs text-[#13284A] focus:outline-none"
            />
            <span className="text-[#94a3b8] text-xs">to</span>
            <input
              type="date"
              value={exportUntil}
              onChange={(e) => setExportUntil(e.target.value)}
              className="px-1.5 py-0.5 rounded bg-white border border-[#e2e8f0] font-body text-xs text-[#13284A] focus:outline-none"
            />
            <button
              onClick={handleExportCsv}
              disabled={exporting}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white rounded-lg hover:bg-primary/95 disabled:opacity-50 font-label text-xs font-semibold transition-colors"
            >
              {exporting ? <Loader2 className="animate-spin" size={12} /> : <Download size={12} />}
              CSV
            </button>
          </div>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-[#f1f5f9] text-[#94a3b8] font-label uppercase text-[10px] font-bold">
                <th className="py-3 px-4 cursor-pointer hover:text-[#13284A]" onClick={() => handleSort("name")}>Agent Name {sortIcon("name")}</th>
                <th className="py-3 px-4 cursor-pointer hover:text-[#13284A]" onClick={() => handleSort("calls_today")}>Calls Today {sortIcon("calls_today")}</th>
                <th className="py-3 px-4 cursor-pointer hover:text-[#13284A]" onClick={() => handleSort("connect_rate")}>Connect Rate {sortIcon("connect_rate")}</th>
                <th className="py-3 px-4 cursor-pointer hover:text-[#13284A]" onClick={() => handleSort("avg_talk_seconds")}>Avg Talk Time {sortIcon("avg_talk_seconds")}</th>
                <th className="py-3 px-4 cursor-pointer hover:text-[#13284A]" onClick={() => handleSort("idle_minutes_today")}>Idle Minutes {sortIcon("idle_minutes_today")}</th>
                {evaluationVisible && (
                  <th className="py-3 px-4 cursor-pointer hover:text-[#13284A]" onClick={() => handleSort("overall_score")} title="Average of this period's scored calls">Avg Score {sortIcon("overall_score")}</th>
                )}
                <th className="py-3 px-4">Bunking Alert</th>
                <th className="py-3 px-4">Daily Target</th>
              </tr>
            </thead>
            <tbody>
              {loadingStats ? (
                <tr>
                  <td colSpan={leaderboardColumnCount} className="text-center py-8 text-[#94a3b8] font-medium">
                    <Loader2 className="animate-spin text-[#94a3b8] inline mr-2" size={16} /> Loading performance logs...
                  </td>
                </tr>
              ) : getSortedPerformers().length === 0 ? (
                <tr>
                  <td colSpan={leaderboardColumnCount} className="text-center py-8 text-[#94a3b8]">No performance records for today.</td>
                </tr>
              ) : (
                getSortedPerformers().map((row) => {
                  const dbCaller = callersList.find((c) => c.id === row.caller_id);
                  const currentTarget = editingTarget[row.caller_id] !== undefined
                    ? editingTarget[row.caller_id]
                    : (dbCaller?.target ?? 0);
                  const isUpdating = updatingTargetId === row.caller_id;
                  return (
                    <tr
                      key={row.caller_id}
                      className={`border-b border-[#f1f5f9] hover:bg-[#f8fafc]/50 transition-colors ${selectedCallerId === row.caller_id ? "bg-primary/5" : ""}`}
                    >
                      <td className="py-3.5 px-4 font-bold text-[#13284A]">
                        {row.name}
                        {dbCaller?.team_name && (
                          <span className="ml-2 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">{dbCaller.team_name}</span>
                        )}
                      </td>
                      <td className="py-3.5 px-4 text-[#334155] font-semibold">{row.calls_today}</td>
                      <td className="py-3.5 px-4 text-[#334155] font-semibold">
                        {row.connect_rate ? `${Math.round(row.connect_rate * 100)}%` : "0%"}
                      </td>
                      <td className="py-3.5 px-4 text-[#334155] font-medium">
                        {formatTalk(row.avg_talk_seconds)}
                      </td>
                      <td className="py-3.5 px-4 text-[#334155] font-medium">
                        {row.idle_minutes_today ? `${Math.round(row.idle_minutes_today)} min` : "0 min"}
                      </td>
                      {evaluationVisible && (
                        <td className="py-3.5 px-4 text-[#13284A] font-bold text-sm">
                          {row.overall_score != null ? (
                            <>
                              {row.overall_score.toFixed(1)}/100
                              <span className="block font-label text-[10px] font-semibold text-[#94a3b8]">
                                {row.scored_calls ?? 0} scored
                              </span>
                            </>
                          ) : (
                            "\u2014"
                          )}
                        </td>
                      )}
                      <td className="py-3.5 px-4">
                        {row.bunking_flag ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-red-50 text-red-600 font-bold text-[9px] uppercase border border-red-200">
                            <ShieldAlert size={10} /> Idle Gap Alert
                          </span>
                        ) : (
                          <span className="text-[#94a3b8] font-medium">—</span>
                        )}
                      </td>
                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-1.5">
                          <input
                            type="number"
                            min="0"
                            value={currentTarget}
                            onChange={(e) => setEditingTarget({ ...editingTarget, [row.caller_id]: parseInt(e.target.value) || 0 })}
                            className="w-14 px-1.5 py-1 rounded bg-white border border-[#e2e8f0] text-center font-bold font-body text-xs text-[#13284A] focus:outline-none focus:ring-1 focus:ring-primary"
                          />
                          {(editingTarget[row.caller_id] !== undefined) && (
                            <button
                              onClick={() => handleUpdateTarget(row.caller_id)}
                              disabled={isUpdating}
                              className="p-1 text-emerald-600 hover:bg-emerald-50 rounded border border-emerald-200"
                              title="Save Daily Target"
                            >
                              {isUpdating ? <Loader2 className="animate-spin" size={10} /> : <Check size={10} />}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 5. Team Attendance Grid — always visible */}
      <div className="mt-8">
        <TeamAttendanceGrid selectedCallerId={selectedCallerId} selectedCallerName={selectedCallerName} />
      </div>

      {/* 6. Per-caller drill-down — only when a caller is selected */}
      {selectedCallerId && (
        <div className="mt-8 space-y-8">
          {(() => {
            const selectedCaller = callersList.find((c) => c.id === selectedCallerId);
            const effectiveShiftStart = shiftConfig.shift_mode === "individual" && selectedCaller?.shift_start_hour != null
              ? selectedCaller.shift_start_hour
              : shiftConfig.shift_start_hour;
            const effectiveShiftEnd = shiftConfig.shift_mode === "individual" && selectedCaller?.shift_end_hour != null
              ? selectedCaller.shift_end_hour
              : shiftConfig.shift_end_hour;
            return (
              <ShiftTimeline
                callerId={selectedCallerId}
                statsFrom={statsFrom}
                statsTo={statsTo}
                shiftStartHour={effectiveShiftStart}
                shiftEndHour={effectiveShiftEnd}
              />
            );
          })()}
        </div>
      )}

      {/* 6. Tools — collapsed by default to keep the report clean */}
      <div className="bg-surface rounded-card shadow-card ring-1 ring-[#c4c7c7]/15 overflow-hidden">
        <button
          onClick={() => setToolsOpen((o) => !o)}
          className="w-full flex items-center justify-between px-6 py-4 hover:bg-[#f8fafc]/50 transition-colors"
        >
          <div className="text-left">
            <h2 className="font-display text-base font-bold text-primary">Tools</h2>
            <p className="font-label text-xs text-on-surface-muted">
              {evaluationVisible ? "QA call review & bulk lead assignment." : "Bulk lead assignment."}
            </p>
          </div>
          {toolsOpen ? <ChevronUp size={16} className="text-[#94a3b8]" /> : <ChevronDown size={16} className="text-[#94a3b8]" />}
        </button>
        {toolsOpen && (
          <div className={evaluationVisible ? "px-6 pb-6 grid grid-cols-1 lg:grid-cols-2 gap-8" : "px-6 pb-6"}>
            {evaluationVisible && (
              <QaReviewFeed
                from={statsFrom}
                to={statsTo}
                callerId={selectedCallerId}
                callerName={selectedCallerName}
                onViewLead={setViewingLeadId}
              />
            )}
            <BulkAssignment callers={callersList} />
          </div>
        )}
      </div>

      {/* Lead profile modal */}
      {viewingLeadId && (
        <LeadProfileModal leadId={viewingLeadId} onClose={() => setViewingLeadId(null)} />
      )}
    </div>
  );
}
