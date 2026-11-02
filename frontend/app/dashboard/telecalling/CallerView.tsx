"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { Phone, RefreshCw, Download, Inbox, User, Sparkles, Search, Clock } from "lucide-react";
import { api, Caller, Lead } from "@/lib/api";
import { formatPhone, timeAgo } from "@/lib/utils";
import { toast } from "sonner";
import NotesHistoryModal from "./components/notes-history-modal";
import NumpadDialer from "./components/NumpadDialer";
import RecentCallsTab from "./components/RecentCallsTab";
import LeadDetailPanel from "./components/LeadDetailPanel";
import CockpitModals from "./components/CockpitModals";
import { useCallingCockpit } from "./lib/useCallingCockpit";
import { getLeadQueueSection, sortLeadsForCallQueue, type LeadQueueSection } from "./lib/queue-priority";
import { useSearchParams } from "next/navigation";
import { SegmentBadge } from "@/components/segment-badge";
import { isClosedLeadStatus, isWorkingLeadStatus } from "@/lib/call-wrapup";
import { AiraLoader } from "@/components/AiraLoader";

export default function CallerView({ callerId, readOnly = false }: { callerId: string | null; readOnly?: boolean }) {
  const searchParams = useSearchParams();
  // caller profile + my assigned queue
  const [myStatus, setMyStatus] = useState<"active" | "break" | "logged_out">("active");
  const [myLeads, setMyLeads] = useState<Lead[]>([]);
  // True until the first queue fetch settles, so we never show "0 leads" / the empty state early.
  const [queueLoading, setQueueLoading] = useState(true);
  const [lastCalledMap, setLastCalledMap] = useState<Record<string, string>>({});
  const [exporting, setExporting] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [queueSubTab, setQueueSubTab] = useState<"new" | "callback" | "working" | "closed" | "dialer" | "recent">("new");
  const [historyLead, setHistoryLead] = useState<Lead | null>(null);

  // Load my assigned leads (the cockpit owns callbacks/config/wrap-ups itself).
  const loadQueue = useCallback(async () => {
    try {
      const [rawCallers, rawLeads] = await Promise.all([
        api.callers.list(),
        api.leads.list({ assigned_to: callerId || undefined, limit: 1000 }),
      ]);
      const callers = Array.isArray(rawCallers) ? rawCallers : (rawCallers?.data ?? []);
      const leads = Array.isArray(rawLeads) ? rawLeads : [];
      const me = callers.find((c: Caller) => c.id === callerId) || null;
      if (me) setMyStatus((me.status as "active" | "break" | "logged_out") || "active");

      const dialable = leads.filter((l: Lead) => l != null && l.phone && l.phone.trim() !== "");
      const sorted = sortLeadsForCallQueue(dialable);
      setMyLeads(sorted);

      const ids = sorted.map((l: Lead) => l.id).filter(Boolean);
      if (ids.length) api.calls.recentByLeads(ids).then(setLastCalledMap).catch(() => {});
    } catch (err) {
      console.error("CallerView load error:", err);
      toast.error("Couldn't load your lead queue — check your connection or permissions and try refreshing.");
    } finally {
      setQueueLoading(false);
    }
  }, [callerId]);

  useEffect(() => { loadQueue(); }, [loadQueue]);

  const cockpit = useCallingCockpit({ callerId, blockingWrapups: true, refreshQueue: loadQueue });

  const lastProcessedLeadId = useRef<string | null>(null);

  useEffect(() => {
    const leadId = searchParams.get("lead_id");
    if (leadId && leadId !== lastProcessedLeadId.current) {
      cockpit.setSelectedLeadId(leadId);
      const lead = myLeads.find((l) => l.id === leadId);
      if (lead) {
        lastProcessedLeadId.current = leadId;
        if (!lead.call_status || lead.call_status === "new") {
          setQueueSubTab("new");
        } else if (lead.call_status === "callback") {
          setQueueSubTab("callback");
        } else if (isWorkingLeadStatus(lead.call_status)) {
          setQueueSubTab("working");
        } else if (isClosedLeadStatus(lead.call_status)) {
          setQueueSubTab("closed");
        }
      }
    }
  }, [searchParams, cockpit.setSelectedLeadId, myLeads]);

  async function handleDownloadCSV() {
    setExporting(true);
    try {
      await api.leads.exportAssigned();
      toast.success("CSV downloaded successfully");
    } catch (err) {
      toast.error("Failed to download CSV");
      console.error(err);
    } finally {
      setExporting(false);
    }
  }

  const filteredLeads = myLeads.filter((lead) => {
    if (!lead) return false;
    const query = searchQuery.toLowerCase().trim();
    if (!query) return true;
    const nameMatch = lead.name?.toLowerCase().includes(query) ?? false;
    const phoneMatch = lead.phone?.toLowerCase().includes(query) ?? false;
    return nameMatch || phoneMatch;
  });

  const newLeads = filteredLeads.filter((l) => !l.call_status || l.call_status === "new");
  const callbackLeads = filteredLeads.filter((l) => l.call_status === "callback");
  const workingLeads = filteredLeads.filter((l) => isWorkingLeadStatus(l.call_status));
  const closedLeads = filteredLeads.filter((l) => isClosedLeadStatus(l.call_status));

  const activeSubTabLeads =
    queueSubTab === "new" ? newLeads :
    queueSubTab === "callback" ? callbackLeads :
    queueSubTab === "working" ? workingLeads :
    queueSubTab === "dialer" ? [] :
    closedLeads;
  const messageQueueCount = activeSubTabLeads.filter((lead) => getLeadQueueSection(lead) === "messages").length;
  const uploadQueueCount = activeSubTabLeads.length - messageQueueCount;
  const queueRows = activeSubTabLeads.map((lead, index) => {
    const section = getLeadQueueSection(lead);
    const previous = index > 0 ? getLeadQueueSection(activeSubTabLeads[index - 1]) : null;
    return { lead, section, showHeader: section !== previous };
  });

  const queueSectionLabel: Record<LeadQueueSection, string> = {
    messages: "Inbound & outbound message leads",
    upload: "Telecalling upload leads",
  };
  const queueSectionDetail: Record<LeadQueueSection, string> = {
    messages: `${messageQueueCount} priority lead${messageQueueCount === 1 ? "" : "s"}`,
    upload: `${uploadQueueCount} CSV lead${uploadQueueCount === 1 ? "" : "s"}`,
  };

  return (
    <div className="flex min-h-[calc(100vh-8rem)] flex-col bg-transparent xl:-my-4 xl:h-[calc(100vh-5.5rem)] xl:min-h-0 xl:overflow-hidden">
      <div className="grid flex-1 grid-cols-1 gap-4 pb-4 xl:grid-cols-12 xl:min-h-0 xl:pb-0">
        {/* Left Side: Lead List (4/12) */}
        <div className="flex flex-col gap-5 pr-0 xl:col-span-4 xl:min-h-0 xl:pr-1">
          <div className="flex flex-1 flex-col rounded-3xl border border-[#e2e8f0] bg-[#f8fafc] p-4 shadow-sm xl:min-h-0 xl:p-5">
            <div className="flex items-center justify-between mb-4 shrink-0">
              <div>
                <h2 className="font-display text-xl font-extrabold text-[#0A1528] tracking-tight">Lead Queue</h2>
                <p className="font-body text-xs text-[#475569] mt-0.5">{queueLoading ? "—" : myLeads.length} leads assigned</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleDownloadCSV}
                  disabled={exporting || myLeads.length === 0}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-[#e2e8f0]/80 rounded-xl font-label text-xs font-bold hover:bg-[#f8fafc] transition-all text-[#1e293b] shadow-sm hover:border-primary hover:text-primary disabled:opacity-50 hover:scale-[1.01] active:scale-[0.99]"
                  title="Download CSV of all assigned leads"
                >
                  {exporting ? <RefreshCw size={12} className="animate-spin text-primary" /> : <Download size={12} />}
                  Export CSV
                </button>
                <button
                  onClick={cockpit.handleCallNext}
                  disabled={readOnly || cockpit.dialingNext || myStatus !== "active"}
                  className="flex items-center gap-1.5 px-4 py-2 bg-gradient-to-r from-primary to-primary-dark text-white rounded-2xl font-label text-xs font-bold transition-all shadow-sm hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
                  title="Call next hot lead in queue"
                >
                  {cockpit.dialingNext ? <RefreshCw size={12} className="animate-spin mr-1" /> : <Sparkles size={12} className="mr-1 fill-white text-white" />}
                  Call Next
                </button>
              </div>
            </div>

            {/* Search */}
            <div className="mb-4 shrink-0">
              <div className="relative">
                <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
                <input
                  type="text"
                  placeholder="Search by name or phone..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-10 pr-4 py-2.5 bg-[#f8fafc] border border-[#e2e8f0] rounded-xl text-xs font-body focus:outline-none focus:ring-2 focus:ring-primary focus:bg-white transition-all shadow-inner"
                />
              </div>
            </div>

            {/* Sub-tabs */}
            <div className="flex gap-0.5 p-0.5 bg-[#e2e8f0]/60 rounded-2xl shrink-0 mb-4">
              {[
                { id: "new", label: `To Call (${queueLoading ? "—" : newLeads.length})` },
                { id: "callback", label: `Callbacks (${queueLoading ? "—" : callbackLeads.length})` },
                { id: "working", label: `In Prog (${queueLoading ? "—" : workingLeads.length})` },
                { id: "closed", label: `Closed (${queueLoading ? "—" : closedLeads.length})` },
                { id: "dialer", label: "Manual Dial" },
                { id: "recent", label: "Recent" },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setQueueSubTab(tab.id as typeof queueSubTab)}
                  className={`flex-1 py-1.5 px-0 rounded-xl font-label text-[9.5px] font-extrabold text-center whitespace-nowrap transition-all ${
                    queueSubTab === tab.id ? "bg-white text-orange-600 shadow-sm" : "text-amber-700/70 hover:text-[#13284A]"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Lead cards or numpad */}
            {queueSubTab === "recent" ? (
              <RecentCallsTab callerId={callerId} onSelectLead={cockpit.setSelectedLeadId} />
            ) : queueSubTab === "dialer" ? (
              <div className="flex-1 overflow-y-auto flex flex-col items-center pt-4 pb-2">
                <NumpadDialer value={cockpit.manualPhone} onChange={cockpit.setManualPhone} onDial={cockpit.manualDialWithGuard} dialing={cockpit.manualDialing} disabled={readOnly} />
              </div>
            ) : queueLoading ? (
              <AiraLoader inline className="min-h-[200px] flex-1" />
            ) : myLeads.length === 0 ? (
              <div className="text-center py-12 flex-1 flex flex-col justify-center items-center">
                <div className="w-12 h-12 bg-[#f8fafc] rounded-full flex items-center justify-center text-[#94a3b8] border border-[#f1f5f9] mb-3">
                  <Inbox size={18} />
                </div>
                <p className="font-body text-sm font-semibold text-[#475569]">No leads assigned to you</p>
                <p className="font-label text-xs text-[#94a3b8] mt-1">Queue automations will route hot leads as they arrive.</p>
              </div>
            ) : activeSubTabLeads.length === 0 ? (
              <div className="text-center py-12 flex-1 flex flex-col justify-center items-center">
                <div className="w-12 h-12 bg-[#f8fafc] rounded-full flex items-center justify-center text-[#94a3b8] border border-[#f1f5f9] mb-3">
                  <Inbox size={18} />
                </div>
                <p className="font-body text-sm font-semibold text-[#475569]">No matching leads found</p>
                <p className="font-label text-xs text-[#94a3b8] mt-1">Try switching tabs or adjusting your search query.</p>
              </div>
            ) : (
              <div className="flex-1 overflow-y-auto space-y-2 pr-1">
                {queueRows.map(({ lead, section, showHeader }) => {
                  if (!lead) return null;
                  const isSelected = cockpit.selectedLeadId === lead.id;

                  let borderAccent = "border-l-primary";
                  let avatarBg = "bg-primary";
                  let callBtnBg = "bg-emerald-500 hover:bg-emerald-600";

                  if (lead.segment === "A") {
                    borderAccent = "border-l-red-500";
                    avatarBg = "bg-red-500";
                    callBtnBg = "bg-rose-500 hover:bg-rose-600 shadow-rose-500/10";
                  } else if (lead.call_status === "callback") {
                    borderAccent = "border-l-amber-500";
                    avatarBg = "bg-amber-500";
                    callBtnBg = "bg-amber-500 hover:bg-amber-600 shadow-amber-500/10";
                  } else if (isClosedLeadStatus(lead.call_status)) {
                    borderAccent = "border-l-[#d6cfc9]";
                    avatarBg = "bg-[#94a3b8]";
                    callBtnBg = "bg-[#94a3b8] hover:bg-[#475569] shadow-[#475569]/10";
                  }

                  return [
                    showHeader && (
                      <div key={`${section}-header`} className="flex items-center gap-2 py-1">
                        <div className="h-px flex-1 bg-[#e2e8f0]" />
                        <div className="flex max-w-[80%] items-center gap-2 rounded-full border border-[#e2e8f0] bg-white px-2.5 py-1 shadow-sm">
                          <span className="truncate font-label text-[9.5px] font-black uppercase tracking-wide text-[#334155]">{queueSectionLabel[section]}</span>
                          <span className="shrink-0 rounded-full bg-[#f8fafc] px-1.5 py-0.5 font-label text-[8px] font-bold text-[#475569]">{queueSectionDetail[section]}</span>
                        </div>
                        <div className="h-px flex-1 bg-[#e2e8f0]" />
                      </div>
                    ),
                    <div
                      key={lead.id}
                      onClick={() => cockpit.setSelectedLeadId(lead.id)}
                      className={`rounded-2xl border-y border-r border-l-[6px] transition-all duration-200 cursor-pointer p-3 flex items-center justify-between gap-3 ${borderAccent} ${
                        isSelected
                          ? "bg-gradient-to-r from-primary-light/70 to-primary-50/20 border-primary-muted shadow-[0_4px_15px_rgba(var(--primary-500-rgb),0.06)] ring-1 ring-primary/10 translate-x-1"
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
                            {lead.call_status === "callback" && (
                              <span className="px-1.5 py-0.5 bg-amber-100 text-amber-800 rounded font-label text-[8px] font-black uppercase">CALL LATER</span>
                            )}
                          </div>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            <p className="font-label text-xs text-[#475569]">{lead.name ? formatPhone(lead.phone) : ""}</p>
                          </div>
                          <div className="flex items-center gap-1 text-[10px] text-[#94a3b8] mt-0.5">
                            <Clock size={10} />
                            {lead.call_status === "callback" ? (
                              <span>Customer asked to call later</span>
                            ) : lastCalledMap[lead.id] ? (
                              <span>Called {timeAgo(lastCalledMap[lead.id])}</span>
                            ) : (
                              <span>Not called yet</span>
                            )}
                          </div>
                        </div>
                      </div>

                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          cockpit.dialWithGuard(lead.id, lead);
                        }}
                        disabled={readOnly || cockpit.dialing === lead.id}
                        className={`p-2.5 rounded-xl transition-all shadow-sm shrink-0 flex items-center justify-center text-white ${callBtnBg} hover:scale-105 active:scale-95`}
                      >
                        <Phone size={14} className="fill-white" />
                      </button>
                    </div>,
                  ];
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right Side: Lead Profile (8/12) */}
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
                  Choose a lead from your active queue on the left to review campaign source attribution details, previous calls history, and log feedback notes.
                </p>
                <div className="grid grid-cols-2 gap-4 mt-8 w-full max-w-xs">
                  <div className="p-4 bg-white border border-[#f1f5f9] border-t-4 border-t-sky-400 rounded-2xl shadow-sm text-left">
                    <span className="text-[10px] font-bold text-[#94a3b8] uppercase tracking-wider block">Total Queue</span>
                    <span className="text-xl font-bold text-[#13284A] mt-1 block">{queueLoading ? "—" : myLeads.length}</span>
                  </div>
                  <div className="p-4 bg-white border border-[#f1f5f9] border-t-4 border-t-amber-400 rounded-2xl shadow-sm text-left">
                    <span className="text-[10px] font-bold text-[#94a3b8] uppercase tracking-wider block">Today Callbacks</span>
                    <span className="text-xl font-bold text-[#13284A] mt-1 block">{cockpit.todayCallbacks.length}</span>
                  </div>
                </div>
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
