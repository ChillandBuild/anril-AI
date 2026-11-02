"use client";
import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import {
  Phone,
  RefreshCw,
  Check,
  Calendar,
  Clock,
  AlertTriangle,
  ChevronRight,
  Inbox,
  User,
  Zap,
  Shield,
  MessageSquare,
  FileText,
  X,
  PhoneCall,
  Activity,
  Award,
  Sparkles
} from "lucide-react";
import { api, CallbackBoardItem, CallLog } from "@/lib/api";
import { TONE_CHIP, callResultKey, callResultLabel, callResultTone } from "@/lib/call-wrapup";
import { formatPhone, timeAgo } from "@/lib/utils";
import { fetchAllNotes, markCallbackDone } from "../lib/notes-api";
import { isMobileDialSurface, openNativeDialer } from "../lib/sim-dialer";
import type { Note } from "../types";
import { usePolling } from "@/hooks/usePolling";
import { useActiveCall } from "../../contexts/ActiveCallContext";
import { useAuthRole } from "../../contexts/AuthRoleContext";
import { AiraLoader } from "@/components/AiraLoader";

type GroupedCallbacks = {
  overdue: CallbackBoardItem[];
  today: CallbackBoardItem[];
  tomorrow: CallbackBoardItem[];
  upcoming: CallbackBoardItem[];
};

function groupCallbacks(cbs: CallbackBoardItem[]): GroupedCallbacks {
  const now = new Date();
  const todayStr = now.toDateString();
  const tomorrowDate = new Date(now);
  tomorrowDate.setDate(tomorrowDate.getDate() + 1);
  const tomorrowStr = tomorrowDate.toDateString();

  const groups: GroupedCallbacks = { overdue: [], today: [], tomorrow: [], upcoming: [] };
  for (const cb of cbs) {
    const d = new Date(cb.scheduled_for);
    if (d < now) {
      groups.overdue.push(cb);
    } else if (d.toDateString() === todayStr) {
      groups.today.push(cb);
    } else if (d.toDateString() === tomorrowStr) {
      groups.tomorrow.push(cb);
    } else {
      groups.upcoming.push(cb);
    }
  }
  return groups;
}

export default function ScheduledCallsPage() {
  const [callbacks, setCallbacks] = useState<CallbackBoardItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [markingDone, setMarkingDone] = useState<string | null>(null);
  const [callingProvider, setCallingProvider] = useState<"telecmi" | "sim_basic">("telecmi");
  const { setActiveCall: setActiveCallCtx } = useActiveCall();
  const { role, callerId } = useAuthRole();

  // Context Handoff Modal State
  const [handoffCallback, setHandoffCallback] = useState<CallbackBoardItem | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [callLogs, setCallLogs] = useState<CallLog[]>([]);
  const [loadingHandoff, setLoadingHandoff] = useState(false);
  const [takeoverLoading, setTakeoverLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      const [res, assignmentMode] = await Promise.all([
        api.followUps.callbacksBoard(),
        api.calls.assignmentMode().catch(() => null),
      ]);
      setCallbacks(Array.isArray(res?.data) ? res.data : []);
      setCallingProvider(assignmentMode?.calling_provider ?? "telecmi");
    } catch {
      toast.error("Failed to load scheduled calls");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Poll every 10 seconds to keep caller statuses and assignments in sync
  usePolling(load, 10_000);

  async function handleMarkDone(jobId: string) {
    setMarkingDone(jobId);
    try {
      await markCallbackDone(jobId);
      setCallbacks((prev) => prev.filter((c) => c.id !== jobId));
      toast.success("Callback marked as completed");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to mark done");
    } finally {
      setMarkingDone(null);
    }
  }

  async function handleCallLead(cb: CallbackBoardItem) {
    if (!callerId) {
      toast.error("No caller profile found");
      return;
    }
    const phone = cb.lead.phone ?? "";
    const openedNativeDialer = callingProvider === "sim_basic" && isMobileDialSurface()
      ? openNativeDialer(phone)
      : false;

    if (callingProvider === "sim_basic" && isMobileDialSurface() && !openedNativeDialer) {
      toast.error("This lead has no callable phone number.");
      return;
    }

    try {
      const res = await api.calls.initiate({ leadId: cb.lead_id, callbackJobId: cb.id }, callerId);
      setActiveCallCtx({
        leadId: res.lead_id ?? cb.lead_id,
        name: res.lead_name ?? cb.lead.name ?? null,
        phone,
        callLogId: res.call_log_id ?? null,
      });
      if (res.provider === "sim_basic") {
        if (!openedNativeDialer && !openNativeDialer(phone)) {
          toast.error("This lead has no callable phone number.");
          return;
        }
        toast.success(`Opening phone dialer for ${cb.lead.name || phone}...`);
      } else {
        toast.success(`Calling ${cb.lead.name || phone}...`);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Call failed");
    }
  }

  async function handleOpenTakeoverHandoff(cb: CallbackBoardItem) {
    setHandoffCallback(cb);
    setLoadingHandoff(true);
    setNotes([]);
    setCallLogs([]);
    try {
      const [fetchedNotes, fetchedLogs] = await Promise.all([
        fetchAllNotes(cb.lead_id).catch(() => []),
        api.leads.callLogs(cb.lead_id)
      ]);
      setNotes(Array.isArray(fetchedNotes) ? fetchedNotes : []);
      setCallLogs(Array.isArray(fetchedLogs) ? fetchedLogs : []);
    } catch (err) {
      toast.error("Failed to load lead context details");
      console.error(err);
    } finally {
      setLoadingHandoff(false);
    }
  }

  async function handleConfirmTakeover(cb: CallbackBoardItem) {
    if (!callerId) {
      toast.error("You must be logged in as a telecaller to take over leads");
      return;
    }
    setTakeoverLoading(true);
    try {
      await api.leads.takeover(cb.lead_id);
      toast.success("Callback claimed");

      // Close modal and refresh board
      setHandoffCallback(null);
      load();
    } catch (err) {
      if ((err as { status?: number })?.status === 409) {
        toast.error("Already claimed by another caller");
        setHandoffCallback(null);
        load();
        return;
      }
      toast.error(err instanceof Error ? err.message : "Claim failed");
    } finally {
      setTakeoverLoading(false);
    }
  }

  function checkTakeoverEligible(cb: CallbackBoardItem) {
    // Claimable purely on time: 15 minutes past the scheduled slot, regardless of
    // anyone's status. Anyone with a caller profile (incl. the admin) can claim.
    if (!callerId) return false;
    if (cb.lead.assigned_to === callerId) return false;
    const scheduledTime = new Date(cb.scheduled_for).getTime();
    const fifteenMinInMs = 15 * 60 * 1000;
    return Date.now() >= scheduledTime + fifteenMinInMs;
  }

  function renderCallerStatus(cb: CallbackBoardItem) {
    const caller = cb.assigned_caller;
    if (!caller) {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium bg-[#f1f5f9] text-[#334155] border border-[#e2e8f0]">
          <User size={11} />
          Unassigned
        </span>
      );
    }

    // One self-explanatory pill: colored dot + caller name + plain-language state.
    // active → free · break → stepped away · else → logged out.
    const variants =
      caller.status === "active"
        ? { state: "Active", wrap: "bg-emerald-50 text-emerald-700 border-emerald-200/60", dot: "bg-emerald-500" }
        : caller.status === "break"
          ? { state: "On break", wrap: "bg-amber-50 text-amber-700 border-amber-200/60", dot: "bg-amber-500" }
          : { state: "Logged out", wrap: "bg-[#f1f5f9] text-[#475569] border-[#e2e8f0]", dot: "bg-[#94a3b8]" };

    return (
      <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium border ${variants.wrap}`}>
        <span className={`w-1.5 h-1.5 rounded-full ${variants.dot}`} />
        <span className="font-semibold">{caller.name}</span>
        <span className="opacity-70">·</span>
        {variants.state}
      </span>
    );
  }

  const groups = groupCallbacks(callbacks);

  const sectionConfig = [
    { key: "overdue" as const, label: "Overdue", icon: AlertTriangle, iconColor: "text-rose-500", bgGradient: "from-rose-50/70 to-red-50/20", borderColor: "border-rose-200/60", badgeColor: "bg-rose-100 text-rose-700" },
    { key: "today" as const, label: "Today", icon: Clock, iconColor: "text-amber-500", bgGradient: "from-amber-50/70 to-orange-50/20", borderColor: "border-amber-200/60", badgeColor: "bg-amber-100 text-amber-700" },
    { key: "tomorrow" as const, label: "Tomorrow", icon: Calendar, iconColor: "text-primary", bgGradient: "from-primary-light/70 to-primary-50/20", borderColor: "border-primary-muted/60", badgeColor: "bg-primary-light text-primary" },
    { key: "upcoming" as const, label: "Upcoming", icon: ChevronRight, iconColor: "text-[#475569]", bgGradient: "from-[#f8fafc]/70 to-gray-50/20", borderColor: "border-[#e2e8f0]/60", badgeColor: "bg-[#f1f5f9] text-[#334155]" },
  ];

  return (
    <div className="max-w-4xl mx-auto px-4 pb-12">
      {/* Custom Keyframe Animations */}
      <style dangerouslySetInnerHTML={{__html: `
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes zoomIn {
          from { transform: scale(0.95); opacity: 0; }
          to { transform: scale(1); opacity: 1; }
        }
        .animate-fade-in {
          animation: fadeIn 0.2s ease-out forwards;
        }
        .animate-zoom-in {
          animation: zoomIn 0.25s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
        }
      `}} />


      {loading ? (
        <AiraLoader inline />
      ) : callbacks.length === 0 ? (
        <div className="text-center py-20 bg-white rounded-3xl border border-[#e2e8f0]/60 shadow-sm">
          <div className="w-14 h-14 bg-[#f8fafc] rounded-full flex items-center justify-center text-[#94a3b8] border border-[#f1f5f9] mx-auto mb-4">
            <Inbox size={22} />
          </div>
          <h3 className="font-display text-lg font-bold text-[#1e293b]">No scheduled callbacks</h3>
          <p className="font-body text-sm text-[#94a3b8] mt-1 max-w-sm mx-auto">
            Schedule callbacks from the Dialer workspace to view them on the shared board.
          </p>
        </div>
      ) : (
        <div className="space-y-8">
          {sectionConfig.map(({ key, label, icon: Icon, iconColor, bgGradient, borderColor, badgeColor }) => {
            const items = groups[key];
            if (items.length === 0) return null;
            return (
              <div key={key} className={`bg-gradient-to-br ${bgGradient} border ${borderColor} rounded-3xl p-6 shadow-sm`}>
                <h2 className="font-display text-xs font-black uppercase tracking-widest flex items-center gap-2 mb-4 text-[#13284A]">
                  <Icon size={14} className={iconColor} />
                  {label}
                  <span className={`px-2 py-0.5 rounded-full font-label text-[10px] font-bold ${badgeColor}`}>
                    {items.length}
                  </span>
                </h2>
                <div className="space-y-3">
                  {items.map((cb) => {
                    const isTakeoverEligible = checkTakeoverEligible(cb);
                    const isAssignedToMe = cb.lead.assigned_to === callerId;
                    const actsAsCaller = !!callerId; // owner-with-caller-profile behaves like a telecaller here
                    const scheduledByMe = !!callerId && cb.scheduled_by?.id === callerId;
                    // "Claimed" = the callback is owned by a telecaller who isn't the scheduler
                    // (covers auto-/pre-103 callbacks with no recorded scheduler too).
                    const isClaimed =
                      !!cb.lead.assigned_to &&
                      cb.lead.assigned_to !== cb.scheduled_by?.id;

                    return (
                      <div
                        key={cb.id}
                        className={`flex flex-col md:flex-row md:items-center justify-between bg-white rounded-2xl p-5 shadow-sm border gap-4 transition-all ${
                          isTakeoverEligible
                            ? "border-primary-muted hover:border-primary-muted hover:shadow-primary-light/50 bg-gradient-to-r from-white to-primary-light/10"
                            : isAssignedToMe
                              ? "border-emerald-200 bg-gradient-to-r from-white to-emerald-50/10"
                              : "border-[#f1f5f9] hover:border-[#e2e8f0]"
                        } hover:shadow-md hover:scale-[1.01]`}
                      >
                        {/* Left Info Column */}
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <p className="font-body text-sm font-bold text-[#13284A] truncate">
                              {cb.lead.name ?? "Unnamed"}
                            </p>
                            <span className="font-label text-[10px] text-[#475569] font-semibold">
                              {formatPhone(cb.lead.phone ?? "")}
                            </span>
                            {cb.lead.segment && (
                              <span className={`px-1.5 py-0.5 rounded font-label text-[9px] font-black uppercase ${
                                cb.lead.segment === "A" ? "bg-emerald-50 text-emerald-700 border border-emerald-200/50" :
                                cb.lead.segment === "B" ? "bg-blue-50 text-blue-700 border border-blue-200/50" :
                                "bg-amber-50 text-amber-700 border border-amber-200/50"
                              }`}>
                                SEG {cb.lead.segment}
                              </span>
                            )}
                            {isTakeoverEligible && (
                              <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full font-label text-[9px] font-bold uppercase tracking-wider bg-primary-light text-primary border border-primary-muted shadow-sm animate-pulse">
                                <Zap size={8} className="fill-primary text-primary" />
                                Claimable
                              </span>
                            )}
                          </div>

                          <div className="flex items-center gap-2 flex-wrap mt-2">
                            <span className="font-label text-[10px] text-[#94a3b8] flex items-center gap-1">
                              <Clock size={10} />
                              {new Date(cb.scheduled_for).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}
                            </span>
                            <span className={`font-label text-[10px] flex items-center gap-1 px-2 py-0.5 rounded-lg border ${
                              isAssignedToMe
                                ? "bg-emerald-50 text-emerald-700 border-emerald-200/60"
                                : isClaimed
                                  ? "bg-primary-light text-primary border-primary-muted/60"
                                  : "bg-[#f8fafc] text-[#475569] border-[#f1f5f9]"
                            }`}>
                              {isClaimed ? <Zap size={10} /> : <User size={10} />}
                              {isClaimed
                                ? (isAssignedToMe ? "Claimed by you" : `Claimed by ${cb.assigned_caller?.name ?? "telecaller"}`)
                                : scheduledByMe
                                  ? "Scheduled by you"
                                  : cb.scheduled_by?.name
                                    ? `Scheduled by ${cb.scheduled_by.name}`
                                    : "Auto-scheduled"}
                            </span>
                            {cb.message_preview && (
                              <span className="font-label text-[10px] text-[#475569] bg-[#f8fafc] border border-[#f1f5f9] px-2 py-0.5 rounded-lg truncate max-w-[240px]">
                                {cb.message_preview}
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Middle Status Column */}
                        <div className="flex items-center gap-2 shrink-0 md:justify-center">
                          {renderCallerStatus(cb)}
                        </div>

                        {/* Right Actions Column */}
                        <div className="flex items-center gap-2 shrink-0 justify-end">
                          {isAssignedToMe && (
                            <>
                              <button
                                onClick={() => handleCallLead(cb)}
                                className="flex items-center gap-1.5 px-4 py-2 bg-gradient-to-r from-emerald-500 to-teal-600 text-white rounded-xl font-label text-[10px] font-bold hover:from-emerald-600 hover:to-teal-700 transition-all shadow-sm hover:shadow-md hover:scale-[1.02] active:scale-[0.98]"
                              >
                                <Phone size={12} className="fill-white text-white" /> Call
                              </button>
                              <button
                                onClick={() => handleMarkDone(cb.id)}
                                disabled={markingDone === cb.id}
                                className="flex items-center gap-1.5 px-4 py-2 bg-[#f1f5f9] text-[#334155] rounded-xl font-label text-[10px] font-bold hover:bg-[#e2e8f0] transition-all disabled:opacity-50"
                              >
                                {markingDone === cb.id ? <RefreshCw size={12} className="animate-spin" /> : <Check size={12} />}
                                Done
                              </button>
                            </>
                          )}

                          {!isAssignedToMe && isTakeoverEligible && (
                            <button
                              onClick={() => handleOpenTakeoverHandoff(cb)}
                              className="flex items-center gap-1.5 px-4 py-2 bg-gradient-to-r from-primary to-primary-600 text-white rounded-xl font-label text-[10px] font-bold hover:from-primary-dark hover:to-primary-700 transition-all shadow-md hover:shadow-lg hover:scale-[1.02] active:scale-[0.98]"
                            >
                              <Zap size={12} className="fill-white text-white" /> Claim
                            </button>
                          )}

                          {actsAsCaller && !isAssignedToMe && !isTakeoverEligible && (
                            <div className="flex items-center gap-1 px-3 py-1.5 bg-[#f8fafc] text-[#94a3b8] rounded-xl font-label text-[10px] border border-[#f1f5f9]">
                              <Shield size={11} />
                              Locked
                            </div>
                          )}

                          {role === "owner" && !actsAsCaller && (
                            <button
                              onClick={() => handleMarkDone(cb.id)}
                              disabled={markingDone === cb.id}
                              className="flex items-center gap-1.5 px-4 py-2 bg-[#f1f5f9] text-[#334155] rounded-xl font-label text-[10px] font-bold hover:bg-[#e2e8f0] transition-all disabled:opacity-50"
                            >
                              {markingDone === cb.id ? <RefreshCw size={12} className="animate-spin" /> : <Check size={12} />}
                              Done (Admin)
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Context Handoff Modal */}
      {handoffCallback && (
        <div className="fixed inset-0 z-dialog flex items-center justify-center p-4 bg-[#0A1528]/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-white rounded-3xl p-6 shadow-2xl w-full max-w-4xl border border-[#f1f5f9] max-h-[90vh] flex flex-col animate-zoom-in">
            {/* Modal Header */}
            <div className="flex items-center justify-between pb-4 border-b border-[#f1f5f9] shrink-0">
              <div>
                <div className="flex items-center gap-2">
                  <span className="p-1.5 bg-primary-light rounded-lg text-primary">
                    <Zap size={18} />
                  </span>
                  <h2 className="font-display text-xl font-bold text-[#13284A]">
                    Claim Callback
                  </h2>
                </div>
                <p className="font-body text-xs text-[#475569] mt-1">
                  Claim this overdue callback. Once claimed, the lead is assigned to you.
                </p>
              </div>
              <button
                onClick={() => setHandoffCallback(null)}
                className="p-1.5 rounded-lg hover:bg-[#f8fafc] text-[#94a3b8] hover:text-[#334155] transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto py-6 grid grid-cols-1 lg:grid-cols-2 gap-6 min-h-[300px]">
              {/* Left Column: Lead Info & Notes History */}
              <div className="space-y-4 flex flex-col min-w-0">
                <div className="bg-[#f8fafc] rounded-2xl p-4 border border-[#f1f5f9] shrink-0">
                  <h3 className="font-display text-xs font-bold text-[#94a3b8] uppercase tracking-wider mb-3">
                    Lead Details
                  </h3>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <p className="text-[10px] text-[#94a3b8] font-medium uppercase">Name</p>
                      <p className="text-sm font-bold text-[#13284A] truncate">{handoffCallback.lead.name || "Unnamed"}</p>
                    </div>
                    <div>
                      <p className="text-[10px] text-[#94a3b8] font-medium uppercase">Phone</p>
                      <p className="text-sm font-bold text-[#13284A]">{formatPhone(handoffCallback.lead.phone ?? "")}</p>
                    </div>
                    <div>
                      <p className="text-[10px] text-[#94a3b8] font-medium uppercase">Segment</p>
                      <span className={`inline-block px-2 py-0.5 rounded font-label text-[9px] font-black uppercase mt-0.5 ${
                        handoffCallback.lead.segment === "A" ? "bg-emerald-50 text-emerald-700 border border-emerald-200" :
                        handoffCallback.lead.segment === "B" ? "bg-blue-50 text-blue-700 border border-blue-200" :
                        "bg-amber-50 text-amber-700 border border-amber-200"
                      }`}>SEG {handoffCallback.lead.segment || "D"}</span>
                    </div>
                    <div>
                      <p className="text-[10px] text-[#94a3b8] font-medium uppercase">Lead Score</p>
                      <div className="flex items-center gap-1 mt-0.5">
                        <Award size={12} className="text-primary" />
                        <span className="text-xs font-bold text-[#13284A]">{handoffCallback.lead.score ?? 0}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="flex-1 flex flex-col min-h-[200px]">
                  <h3 className="font-display text-xs font-bold text-[#94a3b8] uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <FileText size={12} />
                    Touch Notes History
                  </h3>
                  <div className="flex-1 overflow-y-auto border border-[#f1f5f9] rounded-2xl p-4 space-y-3 bg-white max-h-[300px]">
                    {loadingHandoff ? (
                      <div className="flex items-center justify-center h-full py-8">
                        <RefreshCw size={20} className="animate-spin text-[#94a3b8]" />
                      </div>
                    ) : notes.length === 0 ? (
                      <div className="flex flex-col items-center justify-center py-8 text-[#94a3b8]">
                        <MessageSquare size={24} className="stroke-[1.5] mb-1.5" />
                        <p className="text-xs font-medium">No touch notes found for this lead.</p>
                      </div>
                    ) : (
                      notes.map((note) => (
                        <div key={note.id} className="p-3 bg-[#f8fafc] border border-[#f1f5f9] rounded-xl relative hover:border-[#e2e8f0] transition-colors">
                          <div className="flex items-center justify-between gap-2 mb-1">
                            <span className="text-[9px] text-[#94a3b8] font-semibold">{timeAgo(note.created_at)}</span>
                            {note.is_pinned && (
                              <span className="text-[9px] font-bold text-primary bg-primary-light px-1 rounded">Pinned</span>
                            )}
                          </div>
                          <p className="text-xs text-[#1e293b] whitespace-pre-wrap">{note.content}</p>
                          {note.structured && Object.keys(note.structured).length > 0 && (
                            <div className="mt-2 pt-2 border-t border-[#e2e8f0]/50 flex flex-wrap gap-2">
                              {Object.entries(note.structured).map(([k, v]) => v && (
                                <span key={k} className="text-[8px] bg-[#e2e8f0]/60 text-[#334155] px-1.5 py-0.5 rounded capitalize font-medium">
                                  {k.replace("_", " ")}: {v}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>

              {/* Right Column: Previous Call Logs & AI Evaluation */}
              <div className="space-y-4 flex flex-col min-w-0">
                <div className="flex-1 flex flex-col min-h-[350px]">
                  <h3 className="font-display text-xs font-bold text-[#94a3b8] uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <Activity size={12} />
                    Recent Calls &amp; AI Summaries
                  </h3>
                  <div className="flex-1 overflow-y-auto border border-[#f1f5f9] rounded-2xl p-4 space-y-3 bg-white max-h-[420px]">
                    {loadingHandoff ? (
                      <div className="flex items-center justify-center h-full py-8">
                        <RefreshCw size={20} className="animate-spin text-[#94a3b8]" />
                      </div>
                    ) : callLogs.length === 0 ? (
                      <div className="flex flex-col items-center justify-center py-12 text-[#94a3b8]">
                        <Phone size={24} className="stroke-[1.5] mb-1.5" />
                        <p className="text-xs font-medium">No previous call records available.</p>
                      </div>
                    ) : (
                      callLogs.map((log) => (
                        <div key={log.id} className="p-3 bg-[#f8fafc] border border-[#f1f5f9] rounded-xl space-y-2 hover:border-[#e2e8f0] transition-colors">
                          <div className="flex items-center justify-between">
                            <span className={`px-2 py-0.5 rounded border text-[8px] font-bold uppercase ${TONE_CHIP[callResultTone(callResultKey(log))]}`}>
                              {callResultLabel(callResultKey(log)) ?? "Not wrapped up"}
                            </span>
                            <span className="text-[9px] text-[#94a3b8]">{timeAgo(log.created_at)}</span>
                          </div>

                          {log.duration_seconds && (
                            <p className="text-[10px] text-[#475569] font-medium">
                              Duration: {Math.floor(log.duration_seconds / 60)}m {log.duration_seconds % 60}s
                            </p>
                          )}

                          {log.ai_summary && (
                            <div className="mt-2 bg-white rounded-lg p-2.5 border border-[#e2e8f0]/50 space-y-1.5">
                              <div className="flex items-center gap-1 mb-1 pb-1 border-b border-[#f1f5f9]">
                                <span className="text-[9px] font-bold text-[#334155] flex items-center gap-1">
                                  <Sparkles size={10} className="text-primary" />
                                  AI Evaluation
                                </span>
                              </div>
                              {(log.ai_summary.course || log.ai_summary.product) && (
                                <p className="text-[10px] text-[#334155]"><span className="font-semibold text-[#1e293b]">Course Interest:</span> {log.ai_summary.course || log.ai_summary.product}</p>
                              )}
                              {log.ai_summary.brief && (
                                <p className="text-[10px] text-[#334155]"><span className="font-semibold text-[#1e293b]">Brief:</span> {log.ai_summary.brief}</p>
                              )}
                              {log.ai_summary.budget && (
                                <p className="text-[10px] text-[#334155]"><span className="font-semibold text-[#1e293b]">Budget:</span> {log.ai_summary.budget}</p>
                              )}
                              {log.ai_summary.timeline && (
                                <p className="text-[10px] text-[#334155]"><span className="font-semibold text-[#1e293b]">Timeline:</span> {log.ai_summary.timeline}</p>
                              )}
                              {log.ai_summary.sentiment && (
                                <p className="text-[10px] text-[#334155]"><span className="font-semibold text-[#1e293b]">Sentiment:</span> {log.ai_summary.sentiment}</p>
                              )}
                              {log.ai_summary.next_action && (
                                <p className="text-[10px] text-[#334155]"><span className="font-semibold text-[#1e293b]">Next Action:</span> {log.ai_summary.next_action}</p>
                              )}
                            </div>
                          )}

                          {log.transcript_preview && (
                            <div className="bg-[#f1f5f9]/50 rounded p-2 mt-1.5">
                              <p className="text-[9px] font-bold text-[#475569] mb-0.5">Transcript Snippet</p>
                              <p className="text-[10px] text-[#334155] line-clamp-2 italic">&ldquo;{log.transcript_preview.first}&rdquo;</p>
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="flex items-center justify-end gap-3 pt-4 border-t border-[#f1f5f9] shrink-0">
              <button
                onClick={() => setHandoffCallback(null)}
                className="px-4 py-2 bg-[#f1f5f9] text-[#334155] hover:bg-[#e2e8f0] rounded-xl font-label text-[11px] font-bold transition-all"
              >
                Cancel
              </button>
              <button
                onClick={() => handleConfirmTakeover(handoffCallback)}
                disabled={takeoverLoading}
                className="flex items-center gap-1.5 px-5 py-2 bg-gradient-to-r from-primary to-primary-600 text-white hover:from-primary-dark hover:to-primary-700 rounded-xl font-label text-[11px] font-bold transition-all shadow-md hover:shadow-lg disabled:opacity-50"
              >
                {takeoverLoading ? (
                  <RefreshCw size={12} className="animate-spin" />
                ) : (
                  <PhoneCall size={12} className="fill-white text-white" />
                )}
                Claim
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
