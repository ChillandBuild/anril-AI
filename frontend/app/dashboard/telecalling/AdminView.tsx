"use client";
import { useCallback, useState } from "react";
import { Phone, ChevronDown, Sparkles, User, Inbox, Clock, Search } from "lucide-react";
import type { Caller, Lead } from "@/lib/api";
import { LEAD_CALL_STATUSES, LEAD_STATUS_LABEL, isClosedLeadStatus } from "@/lib/call-wrapup";
import { useAdminDashboard, useLeads } from "@/hooks/useApi";
import type { AdminDashboardData } from "@/hooks/useApi";
import { formatPhone } from "@/lib/utils";
import NotesHistoryModal from "./components/notes-history-modal";
import LeadDetailPanel from "./components/LeadDetailPanel";
import CockpitModals from "./components/CockpitModals";
import NumpadDialer from "./components/NumpadDialer";
import RecentCallsTab from "./components/RecentCallsTab";
import { useCallingCockpit } from "./lib/useCallingCockpit";
import { useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { SegmentBadge } from "@/components/segment-badge";
import { AiraLoader } from "@/components/AiraLoader";

export default function AdminView({ fallbackData, readOnly = false }: { fallbackData?: AdminDashboardData; readOnly?: boolean }) {
  const searchParams = useSearchParams();
  const { data: dashboard, mutate: refreshDashboard } = useAdminDashboard(fallbackData);
  const callers: Caller[] = dashboard?.callers ?? [];

  // Who the call dials as (null = admin self).
  const [selectedCallerId, setSelectedCallerId] = useState<string | null>(null);


  // Left-panel: Queue vs Manual Dial
  const [leftTab, setLeftTab] = useState<"queue" | "dialer" | "recent">("queue");
  const [historyLead, setHistoryLead] = useState<Lead | null>(null);

  // Queue filters
  const [queueSegment, setQueueSegment] = useState<string>("all");
  const [queueStatus, setQueueStatus] = useState<string>("all");
  const [queueAssignedTo, setQueueAssignedTo] = useState<string>("all");

  // Searching hits the API (the queue only holds one page of leads, so a lead
  // outside it would be unreachable by filtering what is already on screen).
  // Debounced so typing a phone number is one request, not ten.
  const [searchInput, setSearchInput] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setSearchTerm(searchInput.trim()), 350);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const { data: queueLeadsData, isLoading: queueLoading, mutate: refreshQueueLeads } = useLeads({
    segment: queueSegment !== "all" ? queueSegment : undefined,
    assigned_to: (queueAssignedTo !== "all" && queueAssignedTo !== "unassigned") ? queueAssignedTo : undefined,
    search: searchTerm || undefined,
    limit: 50,
  });

  const refreshQueue = useCallback(() => {
    refreshQueueLeads();
    refreshDashboard();
  }, [refreshQueueLeads, refreshDashboard]);

  const cockpit = useCallingCockpit({ callerId: selectedCallerId, blockingWrapups: false, refreshQueue });

  useEffect(() => {
    const leadId = searchParams.get("lead_id");
    if (leadId) cockpit.setSelectedLeadId(leadId);
  }, [searchParams, cockpit.setSelectedLeadId]);

  const filteredQueueLeads = (queueLeadsData ?? []).filter((lead) => {
    if (queueStatus !== "all" && lead.call_status !== queueStatus) return false;
    if (queueAssignedTo === "unassigned" && lead.assigned_to) return false;
    return true;
  });



  const selectedCallerName = callers.find((c) => c.id === selectedCallerId)?.name ?? "Admin (me)";

  return (
    <div className="flex min-h-[calc(100vh-8rem)] flex-col bg-transparent xl:-my-4 xl:h-[calc(100vh-5.5rem)] xl:min-h-0 xl:overflow-hidden">
      <div className="grid flex-1 grid-cols-1 gap-4 pb-4 xl:grid-cols-12 xl:min-h-0 xl:pb-0">
        {/* Left Side: Admin Queue (4/12) */}
        <div className="flex flex-col gap-5 pr-0 xl:col-span-4 xl:min-h-0 xl:pr-1">
          <div className="flex flex-1 flex-col rounded-3xl border border-[#e2e8f0] bg-[#f8fafc] p-4 shadow-sm xl:min-h-0 xl:p-5">
            {/* Header: title + Calling as + Config */}
            <div className="flex items-start justify-between mb-4 shrink-0 gap-2">
              <div>
                <h2 className="font-display text-xl font-extrabold text-[#0A1528] tracking-tight">Lead Queue</h2>
                <p className="font-label text-xs text-[#475569] mt-0.5">
                  Calling as <span className="text-[var(--primary-800)] font-semibold">{selectedCallerName}</span>
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
              </div>
            </div>

            {/* Calling as selector */}
            <div className="mb-3 shrink-0">
              <label className="block font-label text-[9px] text-[#94a3b8] uppercase tracking-widest mb-1 font-extrabold">Calling as</label>
              <div className="relative">
                <select
                  value={selectedCallerId || ""}
                  onChange={(e) => setSelectedCallerId(e.target.value || null)}
                  className="w-full appearance-none pl-3 pr-8 py-2 rounded-xl bg-white border border-[#e2e8f0]/80 font-body text-xs font-semibold text-[#1e293b] focus:outline-none focus:ring-2 focus:ring-[var(--primary-800)] cursor-pointer"
                >
                  <option value="">Admin (me)</option>
                  {callers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
                <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94a3b8] pointer-events-none" />
              </div>
            </div>

            {/* Queue / Manual Dial tabs */}
            <div className="flex gap-0.5 p-0.5 bg-[#e2e8f0]/60 rounded-2xl shrink-0 mb-4">
              {[
                { id: "queue", label: "Queue" },
                { id: "dialer", label: "Manual Dial" },
                { id: "recent", label: "Recent" },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setLeftTab(tab.id as typeof leftTab)}
                  className={`flex-1 py-1.5 rounded-xl font-label text-[11px] font-extrabold text-center transition-all ${
                    leftTab === tab.id ? "bg-white text-orange-600 shadow-sm" : "text-amber-700/70 hover:text-[#13284A]"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {leftTab === "recent" ? (
              <RecentCallsTab callerId={selectedCallerId} onSelectLead={cockpit.setSelectedLeadId} />
            ) : leftTab === "dialer" ? (
              <div className="flex-1 overflow-y-auto flex flex-col items-center pt-4 pb-2">
                <NumpadDialer value={cockpit.manualPhone} onChange={cockpit.setManualPhone} onDial={cockpit.manualDialWithGuard} dialing={cockpit.manualDialing} disabled={readOnly} />
              </div>
            ) : (
              <>
                {/* Search */}
                <div className="mb-3 shrink-0">
                  <div className="relative">
                    <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
                    <input
                      type="text"
                      placeholder="Search by name or phone..."
                      value={searchInput}
                      onChange={(e) => setSearchInput(e.target.value)}
                      className="w-full pl-10 pr-4 py-2.5 bg-white border border-[#e2e8f0] rounded-xl text-xs font-body focus:outline-none focus:ring-2 focus:ring-primary transition-all shadow-inner"
                    />
                  </div>
                </div>

                {/* Filters */}
                <div className="grid grid-cols-3 gap-2 mb-4 shrink-0">
                  {[
                    { value: queueSegment, set: setQueueSegment, label: "Segment", opts: [["all", "All Seg"], ["A", "A"], ["B", "B"], ["C", "C"], ["D", "D"]] },
                    { value: queueStatus, set: setQueueStatus, label: "Status", opts: [["all", "All"], ...LEAD_CALL_STATUSES.map((s) => [s, LEAD_STATUS_LABEL[s]] as [string, string])] },
                    { value: queueAssignedTo, set: setQueueAssignedTo, label: "Assigned", opts: [["all", "All"], ["unassigned", "Unassigned"], ...callers.map((c) => [c.id, c.name] as [string, string])] },
                  ].map((f) => (
                    <div key={f.label}>
                      <label className="block font-label text-[8px] text-[#94a3b8] uppercase tracking-widest mb-1 font-extrabold">{f.label}</label>
                      <div className="relative">
                        <select
                          value={f.value}
                          onChange={(e) => f.set(e.target.value)}
                          className="w-full appearance-none pl-2 pr-6 py-1.5 rounded-lg bg-white border border-[#e2e8f0]/80 font-body text-[11px] font-semibold text-[#1e293b] focus:outline-none focus:ring-2 focus:ring-primary cursor-pointer"
                        >
                          {f.opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                        <ChevronDown size={11} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[#94a3b8] pointer-events-none" />
                      </div>
                    </div>
                  ))}
                </div>

                {/* Lead cards */}
                {queueLoading ? (
                  <AiraLoader inline className="min-h-[200px] flex-1" />
                ) : filteredQueueLeads.length === 0 ? (
                  <div className="text-center py-12 flex-1 flex flex-col justify-center items-center">
                    <div className="w-12 h-12 bg-[#f8fafc] rounded-full flex items-center justify-center text-[#94a3b8] border border-[#f1f5f9] mb-3">
                      <Inbox size={18} />
                    </div>
                    <p className="font-body text-sm font-semibold text-[#475569]">
                      {searchTerm ? `No leads found for "${searchTerm}"` : "No leads match the filters"}
                    </p>
                    <p className="font-label text-xs text-[#94a3b8] mt-1">
                      {searchTerm ? "Check the spelling, or clear the segment / status / assignment filters." : "Adjust segment, status, or assignment above."}
                    </p>
                  </div>
                ) : (
                  <div className="flex-1 overflow-y-auto space-y-2 pr-1">
                    {filteredQueueLeads.map((lead) => {
                      const assignedCaller = callers.find((c) => c.id === lead.assigned_to);
                      const isSelected = cockpit.selectedLeadId === lead.id;

                      let borderAccent = "border-l-violet-400";
                      let avatarBg = "bg-primary-500";
                      let callBtnBg = "bg-emerald-500 hover:bg-emerald-600";
                      if (lead.segment === "A") {
                        borderAccent = "border-l-red-500"; avatarBg = "bg-red-500"; callBtnBg = "bg-rose-500 hover:bg-rose-600";
                      } else if (lead.call_status === "callback") {
                        borderAccent = "border-l-amber-500"; avatarBg = "bg-amber-500"; callBtnBg = "bg-amber-500 hover:bg-amber-600";
                      } else if (isClosedLeadStatus(lead.call_status)) {
                        borderAccent = "border-l-[#d6cfc9]"; avatarBg = "bg-[#94a3b8]"; callBtnBg = "bg-[#94a3b8] hover:bg-[#475569]";
                      }

                      return (
                        <div
                          key={lead.id}
                          onClick={() => cockpit.setSelectedLeadId(lead.id)}
                          className={`rounded-2xl border-y border-r border-l-[6px] transition-all duration-200 cursor-pointer p-3 flex items-center justify-between gap-3 ${borderAccent} ${
                            isSelected
                              ? "bg-gradient-to-r from-primary-light/70 to-primary-50/20 border-primary-muted shadow-[0_4px_15px_rgba(var(--primary-800-rgb),0.06)] ring-1 ring-primary/10 translate-x-1"
                              : "bg-[#f8fafc]/30 border-[#f1f5f9] hover:bg-[#f8fafc] hover:shadow-sm"
                          }`}
                        >
                          <div className="flex items-center gap-3 min-w-0 flex-1">
                            <div className={`w-9 h-9 rounded-full flex items-center justify-center font-display text-xs font-bold text-white shrink-0 ${avatarBg}`}>
                              {lead.name ? lead.name.charAt(0).toUpperCase() : <User size={14} />}
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-1.5 flex-wrap">
                                <p className="font-body text-sm font-bold text-[#13284A] truncate">{lead.name || formatPhone(lead.phone)}</p>
                                <SegmentBadge segment={lead.segment} />
                              </div>
                              <div className="flex items-center gap-1.5 mt-0.5">
                                <p className="font-label text-xs text-[#475569]">{lead.name ? formatPhone(lead.phone) : ""}</p>
                              </div>
                              <div className="flex items-center gap-1 text-[10px] text-[#94a3b8] mt-0.5">
                                <Clock size={10} />
                                <span>{assignedCaller ? assignedCaller.name : <span className="text-amber-500">Unassigned</span>}</span>
                              </div>
                            </div>
                          </div>
                          <button
                            onClick={(e) => { e.stopPropagation(); cockpit.dialWithGuard(lead.id, lead); }}
                            disabled={readOnly || cockpit.dialing === lead.id}
                            className={`p-2.5 rounded-xl transition-all shadow-sm shrink-0 flex items-center justify-center text-white ${callBtnBg} hover:scale-105 active:scale-95`}
                          >
                            <Phone size={14} className="fill-white" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        {/* Right Side: Lead Profile (8/12) — identical to telecaller cockpit */}
        <div className="hidden min-h-[380px] flex-col overflow-hidden rounded-3xl border border-[#e2e8f0] bg-[#f8fafc] shadow-sm xl:col-span-8 xl:flex xl:min-h-0">
          <div className="flex-1 overflow-y-auto">
            {!cockpit.selectedLeadId ? (
              <div className="min-h-full flex flex-col items-center justify-center p-12 text-center bg-gradient-to-br from-[#f8fafc]/40 to-primary-light/10">
                <div className="relative mb-6">
                  <div className="absolute inset-0 bg-primary/5 blur-2xl rounded-full scale-150 animate-pulse" />
                  <div className="relative p-6 rounded-3xl bg-white border border-[#f1f5f9] shadow-md text-primary">
                    <Sparkles size={38} className="text-primary" />
                  </div>
                </div>
                <h3 className="font-display text-xl font-extrabold text-[#0A1528] tracking-tight">Lead Profile Workspace</h3>
                <p className="font-body text-sm text-[#475569] max-w-md mt-2 leading-relaxed">
                  Pick a lead from the queue on the left to review attribution, call history, and log feedback — then dial as {selectedCallerName}.
                </p>
              </div>
            ) : (
              <LeadDetailPanel {...cockpit.leadDetailProps} setHistoryLead={setHistoryLead} readOnly={readOnly} />
            )}
          </div>
        </div>
      </div>

      {historyLead && <NotesHistoryModal lead={historyLead} onClose={() => setHistoryLead(null)} />}



      <CockpitModals cockpit={cockpit} />
    </div>
  );
}
