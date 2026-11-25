"use client";
import React, { useState, useEffect } from "react";
import { Sparkles, Phone, StickyNote, Tag, Inbox, User, RefreshCw, MessageSquare, CalendarClock, FileText, ChevronRight, Mic } from "lucide-react";
import { Lead, Message, CallLog, API_URL, getAuthHeaders } from "@/lib/api";
import type { NotesResponse, ActiveCallCtx } from "../types";
import { formatPhone, timeAgo } from "@/lib/utils";
import LeadAttribution from "./LeadAttribution";
import { getMessageDisplayMeta } from "../lib/message-display";
import { TickMark } from "@/components/ui/controls";
import { SegmentBadge } from "@/components/segment-badge";
import SendDetailsCard from "./SendDetailsCard";
import { TONE_DOT, callResultKey, callResultLabel, callResultTone } from "@/lib/call-wrapup";

const QUICK_NOTE_TAGS = [
  "Meeting scheduled",
  "Not interested",
  "Discussed pricing",
  "Demo planned",
  "Needs more info",
  "Send proposal",
  "Hot lead",
];

const CALLBACK_TAGS = new Set(["Meeting scheduled"]);

type MessageBubbleContentMessage = Pick<Message, "content" | "direction" | "media_type">;

function MessageBubbleContent({ message }: { message: MessageBubbleContentMessage }) {
  const display = getMessageDisplayMeta(message);
  return (
    <>
      {display.label && (
        <div className="mb-1.5 flex items-center gap-1 text-[9px] font-bold uppercase tracking-wide text-teal-600">
          <Mic size={10} />
          <span>{display.label}</span>
        </div>
      )}
      <p>{message.content}</p>
    </>
  );
}

export interface LeadDetailPanelProps {
  selectedLead: Lead;
  selectedLeadNotes: NotesResponse | null;
  selectedLeadMessages: Message[];
  selectedLeadCallLogs: CallLog[];
  selectedLeadBrief: { brief: string; opener: string } | null;
  briefLoading: boolean;
  generatePreCallBrief: (leadId: string, force?: boolean) => void;
  selectedLeadLoading: boolean;
  activeProfileTab: "overview" | "notes" | "attribution" | "script";
  setActiveProfileTab: (tab: "overview" | "notes" | "attribution" | "script") => void;
  activeCallCtx: ActiveCallCtx | null;
  callStatus: "ringing" | "connected" | "ended" | null;
  callDuration: number;
  quickNoteTitle: string;
  setQuickNoteTitle: (val: string) => void;
  quickNoteContent: string;
  setQuickNoteContent: (val: string) => void;
  quickNoteSaving: boolean;
  saveQuickNote: (leadId: string) => void;
  quickNoteTags: string[];
  setQuickNoteTags: (tags: string[]) => void;
  quickNotePinned: boolean;
  setQuickNotePinned: (val: boolean) => void;
  showCallbackPicker: boolean;
  setShowCallbackPicker: (val: boolean) => void;
  callbackDate: string;
  setCallbackDate: (val: string) => void;
  callbackTime: string;
  setCallbackTime: (val: string) => void;
  confirmRelease: string | null;
  handleRelease: (leadId: string) => void;
  dialWithGuard: (leadId: string, lead: Lead) => void;
  dialing: string | null;
  telecallingConfig: { scripts?: Record<string, string> } | null;
  scriptExpanded: boolean;
  setScriptExpanded: (val: boolean) => void;
  setHistoryLead: (lead: Lead | null) => void;
  readOnly?: boolean;
}

export default function LeadDetailPanel({
  selectedLead,
  selectedLeadNotes,
  selectedLeadMessages,
  selectedLeadCallLogs,
  selectedLeadBrief,
  briefLoading,
  generatePreCallBrief,
  selectedLeadLoading,
  activeProfileTab,
  setActiveProfileTab,
  activeCallCtx,
  callStatus,
  callDuration,
  quickNoteTitle,
  setQuickNoteTitle,
  quickNoteContent,
  setQuickNoteContent,
  quickNoteSaving,
  saveQuickNote,
  quickNoteTags,
  setQuickNoteTags,
  quickNotePinned,
  setQuickNotePinned,
  showCallbackPicker,
  setShowCallbackPicker,
  callbackDate,
  setCallbackDate,
  callbackTime,
  setCallbackTime,
  confirmRelease,
  handleRelease,
  dialWithGuard,
  dialing,
  telecallingConfig,
  scriptExpanded,
  setScriptExpanded,
  setHistoryLead,
  readOnly = false,
}: LeadDetailPanelProps) {

  const [noteFilter, setNoteFilter] = useState<"all" | "notes" | "calls" | "whatsapp">("all");
  const [tagsExpanded, setTagsExpanded] = useState(false);

  const toggleQuickNoteTag = (tag: string) => {
    const isSelected = quickNoteTags.includes(tag);
    setQuickNoteTags(isSelected ? quickNoteTags.filter((t) => t !== tag) : [...quickNoteTags, tag]);
    // Only open the callback picker when SELECTING a callback tag, not deselecting
    if (CALLBACK_TAGS.has(tag) && !isSelected) {
      setShowCallbackPicker(true);
    }
  };

  if (selectedLeadLoading) {
    return (
      <div className="py-16 flex flex-col items-center justify-center bg-[#f8fafc] rounded-2xl mx-5 mt-5">
        <RefreshCw size={32} className="animate-spin text-orange-400 mb-2" />
        <p className="font-body text-sm text-amber-700/60 font-medium">Loading lead profile...</p>
      </div>
    );
  }

  if (!selectedLead) {
    return (
      <div className="py-16 flex flex-col items-center justify-center text-center bg-[#f8fafc] rounded-2xl mx-5 mt-5 px-6">
        <User size={32} className="text-[#d6cfc9] mb-2" />
        <p className="font-body text-sm text-[#334155] font-semibold">Couldn&apos;t load this lead</p>
        <p className="font-body text-xs text-[#94a3b8] mt-1">The request failed. Select the lead again or pick another from the queue.</p>
      </div>
    );
  }

  const isCallingThisLead =
    activeCallCtx?.leadId === selectedLead.id && (callStatus === "ringing" || callStatus === "connected");

  // Live engagement signal
  const lastInbound = selectedLead.last_inbound_at ? new Date(selectedLead.last_inbound_at) : null;
  const hoursSinceInbound = lastInbound ? (Date.now() - lastInbound.getTime()) / 36e5 : Infinity;
  const engagementSignal =
    hoursSinceInbound < 24
      ? { label: "Active today", sublabel: "Hot window — call now", color: "text-emerald-700", bg: "bg-emerald-50 border-emerald-200", dot: "bg-emerald-500 animate-pulse" }
      : hoursSinceInbound < 168
      ? { label: "Active this week", sublabel: "Replied recently", color: "text-amber-700", bg: "bg-amber-50 border-amber-200", dot: "bg-amber-400" }
      : { label: "Gone cold", sublabel: "No recent WhatsApp activity", color: "text-[#475569]", bg: "bg-[#f8fafc] border-[#e2e8f0]", dot: "bg-[#d6cfc9]" };

  const recentCallLogs = selectedLeadCallLogs.slice(0, 7);
  const recentMessages = selectedLeadMessages.slice(-4);

  // Pipeline & call stats
  const assignedAt = selectedLead.assigned_at ? new Date(selectedLead.assigned_at) : null;
  const daysInPipeline = assignedAt ? Math.floor((Date.now() - assignedAt.getTime()) / 864e5) : null;
  const lastCallLog = selectedLeadCallLogs.length > 0 ? selectedLeadCallLogs[0] : null;
  const daysSinceLastContact = lastCallLog
    ? Math.floor((Date.now() - new Date(lastCallLog.created_at).getTime()) / 864e5)
    : null;
  const totalCalls = selectedLeadCallLogs.length;
  const connectedCalls = selectedLeadCallLogs.filter(l => (l.duration_seconds ?? 0) > 0).length;
  const totalDuration = selectedLeadCallLogs.reduce((sum, l) => sum + (l.duration_seconds ?? 0), 0);
  const avgDurationSecs = totalCalls > 0 ? Math.round(totalDuration / totalCalls) : 0;

  const score = selectedLead.score ?? 0;
  const ringColor =
    score >= 8 ? "#f43f5e" :
    score >= 6 ? "#f97316" :
    score >= 4 ? "#6366f1" :
    "#94a3b8";
  const ringBgGradient =
    score >= 8 ? "from-rose-500 to-red-600" :
    score >= 6 ? "from-amber-500 to-orange-600" :
    score >= 4 ? "from-primary to-primary-600" :
    "from-[#94a3b8] to-[#475569]";
  const circumference = 2 * Math.PI * 28;
  const strokeDashoffset = circumference - (score / 10) * circumference;

  // Unified timeline for "all" filter — sorted newest-first
  const timelineItems = [
    ...(selectedLeadNotes?.notes ?? []).map(n => ({
      type: "note" as const, id: n.id, created_at: n.created_at,
      content: n.content, is_pinned: n.is_pinned,
    })),
    ...selectedLeadCallLogs.map(l => ({
      type: "call" as const, id: l.id, created_at: l.created_at,
      outcome: l.outcome, manual_status: l.manual_status, duration_seconds: l.duration_seconds,
    })),
    ...selectedLeadMessages.map(m => ({
      type: "message" as const, id: m.id, created_at: m.created_at,
      content: m.content, direction: m.direction, media_type: m.media_type,
    })),
  ].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  return (
    <div className="flex flex-col bg-[#f8fafc]">
      <div className="sticky top-0 z-20">
      {/* Header */}
      <div className="bg-gradient-to-br from-[#1a1c3d] via-[#12132e] to-[#0c0d1f] text-white p-3 md:p-6 relative overflow-hidden shadow-md">
        <div className="absolute right-0 bottom-0 top-0 w-1/3 bg-radial-gradient from-orange-500/10 to-transparent pointer-events-none" />
        <div className="flex justify-between items-center gap-3 md:gap-4 max-md:flex-wrap relative z-10">
          <div className="flex gap-3 md:gap-4 items-center min-w-0">
            <div className="relative w-10 h-10 md:w-[66px] md:h-[66px] flex-shrink-0">
              <svg viewBox="0 0 66 66" className="absolute top-0 left-0 w-full h-full">
                <circle cx="33" cy="33" r="28" fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="4" />
                <circle cx="33" cy="33" r="28" fill="none" stroke={ringColor} strokeWidth="4"
                  strokeDasharray={circumference} strokeDashoffset={strokeDashoffset}
                  strokeLinecap="round" transform="rotate(-90 33 33)" className="transition-all duration-500" />
              </svg>
              <div className={`absolute inset-[3px] md:inset-[5px] bg-gradient-to-br ${ringBgGradient} rounded-full flex items-center justify-center font-display text-base md:text-xl font-bold text-white shadow-inner`}>
                {selectedLead.name ? selectedLead.name.charAt(0).toUpperCase() : <User size={20} />}
              </div>
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2.5 flex-wrap">
                <h2 className="font-display text-lg md:text-2xl font-extrabold tracking-tight truncate">
                  {selectedLead.name || "Unnamed Lead"}
                </h2>
                <SegmentBadge segment={selectedLead.segment} />
              </div>
              {isCallingThisLead ? (
                <div className="flex flex-wrap items-center gap-3 mt-1.5">
                  <span className={`px-2 py-0.5 rounded-md font-label text-[9px] font-black uppercase tracking-wider flex items-center gap-1.5 ${
                    callStatus === "connected"
                      ? "bg-emerald-500/30 text-emerald-200 border border-emerald-400/30"
                      : "bg-primary-500/30 text-primary-200 border border-primary-400/30 animate-pulse"
                  }`}>
                    {callStatus === "connected" && (
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                    )}
                    {callStatus === "ringing" ? "Ringing..." : "Connected"}
                  </span>
                  {callStatus === "connected" && (
                    <span className="font-mono text-sm font-bold text-emerald-400 bg-[#13284A]/80 px-3 py-1 rounded-lg border border-[#1e293b]/50">
                      {Math.floor(callDuration / 60).toString().padStart(2, '0')}:
                      {(callDuration % 60).toString().padStart(2, '0')}
                    </span>
                  )}
                  <p className="text-[#d6cfc9] font-label text-xs italic">
                    To hang up, end the call on your phone
                  </p>
                </div>
              ) : (
                <p className="text-[#d6cfc9] font-label text-sm mt-1.5 tracking-wide flex flex-wrap items-center gap-1.5">
                  <span className="font-bold text-white">{formatPhone(selectedLead.phone)}</span>
                  <span className="text-[#475569]">•</span>
                  <span>Score: {selectedLead.score}/10</span>
                  <span className="text-[#475569]">•</span>
                  <span>{selectedLead.channel || selectedLead.source || "Direct"}</span>
                  <span className="text-[#475569]">•</span>
                  <span>{selectedLead.assigned_at ? `Assigned ${timeAgo(selectedLead.assigned_at)}` : "Unassigned"}</span>
                </p>
              )}
            </div>
          </div>
          {!isCallingThisLead && (
            <div className="flex items-center gap-2 shrink-0 max-md:w-full">
              <button
                onClick={() => handleRelease(selectedLead.id)}
                disabled={readOnly}
                className={`px-3 h-9 md:h-auto md:px-4 md:py-2.5 rounded-2xl border font-label text-xs font-bold transition-all text-[#d6cfc9] hover:text-white ${
                  confirmRelease === selectedLead.id
                    ? "bg-red-600 border-red-500 text-white animate-pulse"
                    : "border-[#1e293b]/60 bg-[#0A1528]/40 hover:bg-[#0A1528]"
                }`}
              >
                {confirmRelease === selectedLead.id ? "Release?" : "Release Lead"}
              </button>
              <button
                onClick={() => dialWithGuard(selectedLead.id, selectedLead)}
                disabled={readOnly || dialing === selectedLead.id}
                className="flex items-center justify-center max-md:flex-1 max-md:min-h-11 gap-2 px-4 md:px-6 py-2 md:py-3 bg-primary hover:bg-primary-dark text-white rounded-2xl font-label text-sm font-extrabold shadow-lg shadow-primary/30 hover:shadow-xl hover:shadow-primary/40 transition-all hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
              >
                <Phone size={14} className="fill-white" />
                {dialing === selectedLead.id ? "Dialing…" : "Call Lead"}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Sub-tabs */}
      <div className="flex border-b border-[#e2e8f0] bg-white">
        {[
          { id: "overview", label: "Overview" },
          { id: "notes", label: "Notes & Log" },
          { id: "script", label: "Script" },
        ].map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveProfileTab(t.id as "overview" | "notes" | "attribution" | "script")}
            className={`px-3 py-2.5 md:px-6 md:py-4 font-display text-xs font-black tracking-wider uppercase border-b-2 text-center transition-all ${
              activeProfileTab === t.id
                ? "border-orange-500 text-orange-700"
                : "border-transparent text-[#94a3b8] hover:text-[#334155]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      </div>{/* end sticky header+tabs */}

      {/* Body */}
      <div className="p-5 space-y-4">

        {(activeProfileTab === "overview" || activeProfileTab === "attribution") && (
          <>
            {/* ── Quick Note + Send details on WhatsApp ── */}
            <div className="flex flex-col gap-3 lg:flex-row lg:items-stretch">
              <div className="min-w-0 flex-1 bg-white border border-[#e2e8f0] rounded-2xl p-4 shadow-sm flex flex-col gap-3">
                <h3 className="font-display text-xs font-black text-[#13284A] tracking-widest uppercase flex items-center gap-1.5">
                  <StickyNote size={12} className="text-orange-400" /> Quick Note
                </h3>
                <input
                  type="text"
                  value={quickNoteTitle}
                  onChange={(e) => setQuickNoteTitle(e.target.value)}
                  placeholder="Title (optional)"
                  className="w-full px-3 py-2 rounded-xl bg-[#f8fafc]/40 border border-[#e2e8f0] font-body text-xs font-bold focus:outline-none focus:ring-2 focus:ring-orange-300 focus:bg-white transition-all"
                />
                <textarea
                  value={quickNoteContent}
                  onChange={(e) => setQuickNoteContent(e.target.value)}
                  placeholder="Outcome summary… e.g. Interested, wants demo tomorrow 5 PM"
                  rows={4}
                  className="w-full p-3 rounded-xl bg-[#f8fafc]/40 border border-[#e2e8f0] font-body text-xs focus:outline-none focus:ring-2 focus:ring-orange-300 focus:bg-white transition-all resize-none"
                />

                {/* ── Tags + Schedule Call toggles ── */}
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setTagsExpanded((v) => !v)}
                    className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-[10px] font-black uppercase tracking-widest border transition-all ${
                      tagsExpanded || quickNoteTags.length > 0
                        ? "bg-orange-50 border-orange-200 text-orange-700"
                        : "bg-white border-[#e2e8f0] text-[#334155] hover:border-orange-300 hover:text-orange-600"
                    }`}
                  >
                    <Tag size={11} /> Tags{quickNoteTags.length > 0 ? ` (${quickNoteTags.length})` : ""}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowCallbackPicker(!showCallbackPicker)}
                    className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-[10px] font-black uppercase tracking-widest border transition-all ${
                      showCallbackPicker
                        ? "bg-amber-500 border-amber-500 text-white"
                        : "bg-white border-amber-200 text-amber-700 hover:border-amber-400"
                    }`}
                  >
                    <CalendarClock size={11} /> Schedule Call
                  </button>
                </div>

                {/* ── Tags (collapsed by default) ── */}
                {tagsExpanded && (
                  <div className="flex flex-wrap gap-1.5">
                    {QUICK_NOTE_TAGS.map((tag) => {
                      const selected = quickNoteTags.includes(tag);
                      return (
                        <button
                          key={tag}
                          type="button"
                          onClick={() => toggleQuickNoteTag(tag)}
                          className={`px-2.5 py-1 rounded-full text-[10px] font-bold border transition-all ${
                            selected
                              ? "bg-orange-500 border-orange-500 text-white"
                              : "bg-white border-[#e2e8f0] text-[#334155] hover:border-orange-300 hover:text-orange-600"
                          }`}
                        >
                          {tag}
                        </button>
                      );
                    })}
                  </div>
                )}

                {/* ── Callback scheduler ── */}
                {showCallbackPicker && (
                  <div className="flex flex-col gap-2 p-3 rounded-xl bg-amber-50 border border-amber-200">
                    <h4 className="font-display text-[10px] font-black text-amber-700 tracking-widest uppercase flex items-center gap-1.5">
                      <CalendarClock size={11} /> Schedule Call
                    </h4>
                    <div className="flex gap-2">
                      <input
                        type="date"
                        value={callbackDate}
                        onChange={(e) => setCallbackDate(e.target.value)}
                        className="flex-1 px-2 py-1.5 rounded-lg border border-amber-200 bg-white font-body text-[11px] focus:outline-none focus:ring-2 focus:ring-amber-300"
                      />
                      <input
                        type="time"
                        value={callbackTime}
                        onChange={(e) => setCallbackTime(e.target.value)}
                        className="flex-1 px-2 py-1.5 rounded-lg border border-amber-200 bg-white font-body text-[11px] focus:outline-none focus:ring-2 focus:ring-amber-300"
                      />
                    </div>
                  </div>
                )}

                {/* ── Pin + Save ── */}
                <div className="flex items-center justify-between">
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={quickNotePinned}
                    onClick={() => setQuickNotePinned(!quickNotePinned)}
                    className="flex items-center gap-1.5 font-body text-[11px] text-[#334155]"
                  >
                    <TickMark checked={quickNotePinned} size="sm" />
                    Pin this note
                  </button>
                  <button
                    onClick={() => saveQuickNote(selectedLead.id)}
                    disabled={
                      readOnly ||
                      quickNoteSaving ||
                      (!quickNoteContent.trim() && !quickNoteTitle.trim() && quickNoteTags.length === 0 &&
                        !(showCallbackPicker && callbackDate && callbackTime))
                    }
                    className="px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white rounded-xl font-label text-xs font-bold disabled:opacity-50 transition-all shadow-sm flex items-center gap-1.5"
                  >
                    {quickNoteSaving
                      ? <RefreshCw size={11} className="animate-spin" />
                      : showCallbackPicker ? "Schedule Callback" : "Save Note"}
                  </button>
                </div>
              </div>

              <SendDetailsCard leadId={selectedLead.id} readOnly={readOnly} />
            </div>

            {/* ── AI Pre-Call Brief ── */}
            <div className="bg-white border border-[#e2e8f0] rounded-2xl p-4 shadow-sm">
              <div className="flex items-center justify-between mb-2">
                <p className="font-label text-[9px] uppercase tracking-widest font-extrabold text-orange-600/80 flex items-center gap-1.5">
                  <Sparkles size={11} className="text-orange-500" /> AI Pre-Call Brief
                </p>
                <button
                  onClick={() => generatePreCallBrief(selectedLead.id, true)}
                  disabled={readOnly || briefLoading}
                  className="px-3 py-1.5 bg-orange-500 hover:bg-orange-600 text-white rounded-xl font-label text-[10px] font-extrabold disabled:opacity-60 transition-all flex items-center gap-1.5 shadow-sm"
                >
                  {briefLoading ? <RefreshCw size={10} className="animate-spin" /> : <Sparkles size={10} />}
                  {briefLoading ? "Generating…" : selectedLeadBrief ? "Refresh" : "Generate Brief"}
                </button>
              </div>
              {selectedLeadBrief ? (
                <div className="space-y-2.5">
                  <p className="font-body text-xs text-[#1e293b] leading-relaxed">{selectedLeadBrief.brief}</p>
                  <div className="bg-[#f8fafc] border border-[#e2e8f0] rounded-xl px-3 py-2.5">
                    <p className="font-label text-[9px] text-orange-600 uppercase font-extrabold tracking-wider mb-1">💡 Suggested Opener</p>
                    <p className="font-body text-xs text-[#13284A] italic leading-relaxed">&quot;{selectedLeadBrief.opener}&quot;</p>
                  </div>
                </div>
              ) : (
                <p className="font-body text-xs text-orange-400/80 italic">
                  {briefLoading ? "Analysing lead context…" : "Click Generate Brief to get an AI summary before you dial."}
                </p>
              )}
            </div>

            {/* ── Lead Source ── */}
            <div className="bg-white border border-[#e2e8f0] rounded-2xl p-4 shadow-sm flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-[#f1f5f9] text-[#334155] rounded-xl shrink-0">
                  <Inbox size={16} />
                </div>
                <div>
                  <p className="font-label text-[9px] text-orange-500/80 uppercase tracking-wider font-extrabold">Lead Source</p>
                  <p className="font-body text-sm font-semibold text-[#13284A] mt-0.5">
                    {selectedLead.channel || selectedLead.source || "Organic Inbound"} — {selectedLead.ad_campaign_name || selectedLead.template_name || "Organic Traffic"}
                  </p>
                </div>
              </div>
              <span className="font-label text-xs text-[#94a3b8] font-medium whitespace-nowrap">
                {selectedLead.assigned_at ? timeAgo(selectedLead.assigned_at) : "recent"}
              </span>
            </div>

            {/* ── Pipeline Stats ── */}
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-white border border-[#e2e8f0] rounded-2xl p-4 shadow-sm">
                <p className="font-label text-[9px] uppercase tracking-widest font-extrabold text-[#94a3b8] mb-1.5">Days in Pipeline</p>
                <p className="font-display text-3xl font-extrabold text-[#13284A]">
                  {daysInPipeline !== null ? daysInPipeline : "—"}
                </p>
                <p className="font-label text-[10px] text-[#94a3b8] mt-1">
                  {assignedAt
                    ? `assigned ${assignedAt.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`
                    : "no assignment date"}
                </p>
              </div>
              <div className="bg-white border border-[#e2e8f0] rounded-2xl p-4 shadow-sm">
                <p className="font-label text-[9px] uppercase tracking-widest font-extrabold text-[#94a3b8] mb-1.5">Last Contact</p>
                <p className="font-display text-3xl font-extrabold text-[#13284A]">
                  {daysSinceLastContact !== null ? `${daysSinceLastContact}d` : "—"}
                </p>
                <p className="font-label text-[10px] text-[#94a3b8] mt-1">
                  {lastCallLog ? timeAgo(lastCallLog.created_at) : "No calls yet"}
                </p>
              </div>
            </div>

            {/* ── Campaign Attribution ── */}
            <LeadAttribution lead={selectedLead} variant="compact" />

            {/* ── Engagement Signal + Call Trail ── */}
            <div className="grid grid-cols-2 gap-3">
              <div className={`border rounded-2xl p-4 flex items-start gap-3 shadow-sm ${engagementSignal.bg}`}>
                <span className={`w-2.5 h-2.5 rounded-full shrink-0 mt-1 ${engagementSignal.dot}`} />
                <div>
                  <p className="font-label text-[9px] uppercase tracking-widest font-extrabold text-[#94a3b8]">WhatsApp Activity</p>
                  <p className={`font-body text-sm font-extrabold mt-0.5 ${engagementSignal.color}`}>{engagementSignal.label}</p>
                  <p className="font-label text-[9px] text-[#94a3b8] mt-0.5">{engagementSignal.sublabel}</p>
                  {lastInbound && (
                    <p className="font-label text-[9px] text-[#94a3b8] mt-0.5">{timeAgo(selectedLead.last_inbound_at!)}</p>
                  )}
                </div>
              </div>

              <div className="bg-white border border-[#e2e8f0] rounded-2xl p-4 shadow-sm">
                <p className="font-label text-[9px] uppercase tracking-widest font-extrabold text-[#94a3b8] mb-2.5">📞 Call History</p>
                {recentCallLogs.length === 0 ? (
                  <p className="font-body text-xs text-[#94a3b8]">No calls yet</p>
                ) : (
                  <div className="flex items-center gap-2 flex-wrap">
                    {recentCallLogs.map((log) => (
                      <div key={log.id} className="group relative">
                        <div className={`w-6 h-6 rounded-full ring-2 ring-offset-1 ring-[#f1f5f9] ${TONE_DOT[callResultTone(callResultKey(log))]} cursor-default shadow-sm`} />
                        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 hidden group-hover:block z-20 bg-[#13284A] text-white text-[9px] font-bold px-2.5 py-1.5 rounded-xl whitespace-nowrap shadow-xl">
                          {callResultLabel(callResultKey(log)) ?? "Not wrapped up"} · {timeAgo(log.created_at)}
                          <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-[#13284A]" />
                        </div>
                      </div>
                    ))}
                    {selectedLeadCallLogs.length > 7 && (
                      <span className="font-label text-[9px] text-[#94a3b8] font-bold">+{selectedLeadCallLogs.length - 7}</span>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* ── WhatsApp Context Strip ── */}
            {recentMessages.length > 0 && (
              <div className="bg-gradient-to-br from-primary-950/5 to-teal-50/30 border border-teal-200/40 rounded-2xl p-4 shadow-sm">
                <p className="font-label text-[9px] uppercase tracking-widest font-extrabold text-teal-700/70 mb-3 flex items-center gap-1.5">
                  <MessageSquare size={11} /> Last WhatsApp Conversation
                </p>
                <div className="space-y-2">
                  {recentMessages.map((msg) => (
                    <div key={msg.id} className={`flex ${msg.direction === "inbound" ? "justify-start" : "justify-end"}`}>
                      <div className={`max-w-[78%] px-3 py-2 rounded-2xl text-xs font-body leading-relaxed shadow-sm ${
                        msg.direction === "inbound"
                          ? "bg-white text-[#1e293b] rounded-tl-sm border border-[#f1f5f9]"
                          : "bg-primary-50 border border-primary-100 text-ink rounded-tr-sm"
                      }`}>
                        <MessageBubbleContent message={msg} />
                        <p className="text-[9px] text-[#94a3b8] mt-0.5 text-right">{timeAgo(msg.created_at)}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── Recent Interactions ── */}
            {selectedLeadNotes?.notes && selectedLeadNotes.notes.length > 0 && (
              <div className="bg-white border border-[#e2e8f0] rounded-2xl p-4 shadow-sm">
                <div className="flex justify-between items-center mb-3">
                  <h3 className="font-display text-xs font-black text-[#13284A] flex items-center gap-1.5 tracking-widest uppercase">
                    <MessageSquare size={12} className="text-orange-400" /> Recent Interactions
                  </h3>
                  <button onClick={() => setActiveProfileTab("notes")} className="text-xs text-orange-500 font-bold hover:underline">
                    View all →
                  </button>
                </div>
                <div className="relative border-l-2 border-[#e2e8f0] pl-4 ml-2 space-y-3">
                  {selectedLeadNotes.notes.slice(0, 3).map((n) => (
                    <div key={n.id} className="relative">
                      <span className="absolute -left-[21px] top-1.5 w-2.5 h-2.5 rounded-full bg-orange-400 border-2 border-white" />
                      <span className="block text-[9px] text-[#94a3b8] font-bold mb-1">{timeAgo(n.created_at)}</span>
                      <div className="font-body text-xs text-[#334155] bg-[#f8fafc]/40 border border-[#e2e8f0]/60 p-3 rounded-xl leading-relaxed">
                        {n.content}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── Pitch Script ── */}
            {telecallingConfig?.scripts?.[selectedLead.segment] && (
              <div className="bg-white border border-[#e2e8f0] rounded-2xl p-4 shadow-sm">
                <div className="flex items-center justify-between">
                  <h3 className="font-display text-xs font-black text-orange-900 tracking-widest uppercase flex items-center gap-1.5">
                    <Sparkles size={12} className="text-orange-500" /> Pitch Script (SEG {selectedLead.segment})
                  </h3>
                  <button onClick={() => setScriptExpanded(!scriptExpanded)}
                    className="text-xs font-bold text-orange-600 hover:text-orange-800">
                    {scriptExpanded ? "Hide" : "Show"}
                  </button>
                </div>
                {scriptExpanded && (
                  <div className="mt-2.5 bg-[#f8fafc] border border-[#e2e8f0] p-3 rounded-xl text-[#1e293b] font-body text-xs leading-relaxed whitespace-pre-wrap">
                    {telecallingConfig.scripts[selectedLead.segment]}
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {activeProfileTab === "notes" && (
          <div className="space-y-4">
            {/* ── Call Stats Strip ── */}
            <div className="bg-white border border-[#e2e8f0] rounded-2xl p-4 shadow-sm">
              <div className="grid grid-cols-4 divide-x divide-[#f1f5f9] text-center">
                <div className="px-3">
                  <p className="font-display text-2xl font-extrabold text-[#13284A]">{totalCalls}</p>
                  <p className="font-label text-[9px] text-[#94a3b8] uppercase tracking-wider font-bold mt-0.5">Total Calls</p>
                </div>
                <div className="px-3">
                  <p className="font-display text-2xl font-extrabold text-emerald-600">{connectedCalls}</p>
                  <p className="font-label text-[9px] text-[#94a3b8] uppercase tracking-wider font-bold mt-0.5">Connected</p>
                </div>
                <div className="px-3">
                  <p className="font-display text-xl font-extrabold text-[#13284A]">
                    {avgDurationSecs > 0
                      ? `${Math.floor(avgDurationSecs / 60)}m${avgDurationSecs % 60 > 0 ? ` ${avgDurationSecs % 60}s` : ""}`
                      : "—"}
                  </p>
                  <p className="font-label text-[9px] text-[#94a3b8] uppercase tracking-wider font-bold mt-0.5">Avg Duration</p>
                </div>
                <div className="px-3">
                  <p className="font-display text-xl font-extrabold text-[#13284A] leading-tight">
                    {lastCallLog ? timeAgo(lastCallLog.created_at) : "—"}
                  </p>
                  <p className="font-label text-[9px] text-[#94a3b8] uppercase tracking-wider font-bold mt-0.5">Last Contact</p>
                </div>
              </div>
            </div>

            {/* ── Filter Pills ── */}
            <div className="flex gap-2">
              {(["all", "notes", "calls", "whatsapp"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setNoteFilter(f)}
                  className={`px-3 py-1.5 rounded-lg font-label text-xs font-bold transition-colors ${
                    noteFilter === f
                      ? "bg-orange-500 text-white shadow-sm"
                      : "bg-white border border-[#e2e8f0] text-[#475569] hover:text-[#1e293b]"
                  }`}
                >
                  {f === "all" ? "All" : f === "notes" ? "Notes" : f === "calls" ? "Calls" : "WhatsApp"}
                </button>
              ))}
            </div>

            {/* ── Timeline ── */}
            <div className="bg-white border border-[#e2e8f0] rounded-2xl p-5 shadow-sm">
              <div className="flex justify-between items-center mb-4">
                <h3 className="font-display text-xs font-black text-[#13284A] flex items-center gap-1.5 tracking-widest uppercase">
                  <Inbox size={12} className="text-orange-400" /> Interaction Timeline
                </h3>
                <button onClick={() => setHistoryLead(selectedLead)} className="text-xs text-orange-500 font-bold hover:underline">
                  History Modal
                </button>
              </div>

              {noteFilter === "all" && timelineItems.length === 0 && (
                <div className="p-6 bg-[#f8fafc]/40 border border-[#e2e8f0] text-center rounded-xl text-xs text-[#94a3b8] font-medium">
                  No interactions logged for this lead.
                </div>
              )}

              {/* All — merged chronological */}
              {noteFilter === "all" && timelineItems.length > 0 && (
                <div className="relative border-l-2 border-[#e2e8f0] pl-4 ml-2 space-y-4">
                  {timelineItems.map((item) => (
                    <div key={`${item.type}-${item.id}`} className="relative">
                      <span className={`absolute -left-[21px] top-1.5 w-2.5 h-2.5 rounded-full border-2 border-white ${
                        item.type === "note" ? "bg-orange-400" : item.type === "call" ? "bg-primary-400" : "bg-teal-400"
                      }`} />
                      <div className="text-[9px] text-[#94a3b8] font-bold mb-1 flex items-center gap-1">
                        {item.type === "note" && <><StickyNote size={9} className="text-orange-400" /> Note · {timeAgo(item.created_at)}</>}
                        {item.type === "call" && <><Phone size={9} className="text-primary-400" /> Call · {timeAgo(item.created_at)}</>}
                        {item.type === "message" && <><MessageSquare size={9} className="text-teal-500" /> WhatsApp · {timeAgo(item.created_at)}</>}
                      </div>
                      {item.type === "note" && (
                        <div className="flex flex-col gap-1">
                          {item.is_pinned && (
                            <span className="self-start text-orange-600 bg-orange-50 px-1.5 py-0.5 rounded-full font-black text-[7px]">PINNED</span>
                          )}
                          <div className="font-body text-xs text-[#334155] bg-[#f8fafc]/40 border border-[#e2e8f0]/60 p-3.5 rounded-xl leading-relaxed">
                            {item.content}
                          </div>
                        </div>
                      )}
                      {item.type === "call" && (
                        <div className="bg-primary-light/40 border border-primary-muted p-3 rounded-xl flex items-center justify-between">
                          <span className="font-label text-xs font-bold text-[#1e293b]">
                            {callResultLabel(callResultKey(item)) ?? "Call logged"}
                          </span>
                          {(item.duration_seconds ?? 0) > 0 && (
                            <span className="font-mono text-[10px] text-[#94a3b8]">
                              {Math.floor((item.duration_seconds ?? 0) / 60)}m {(item.duration_seconds ?? 0) % 60}s
                            </span>
                          )}
                        </div>
                      )}
                      {item.type === "message" && (
                        <div className={`flex ${item.direction === "inbound" ? "justify-start" : "justify-end"}`}>
                          <div className={`max-w-[80%] px-3 py-2 rounded-2xl text-xs font-body leading-relaxed shadow-sm ${
                            item.direction === "inbound"
                              ? "bg-white border border-[#e2e8f0] text-[#1e293b] rounded-tl-sm"
                              : "bg-primary-50 border border-primary-100 text-ink rounded-tr-sm"
                          }`}>
                            <MessageBubbleContent
                              message={{
                                content: item.content,
                                direction: item.direction,
                                media_type: item.media_type,
                              }}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Notes only */}
              {noteFilter === "notes" && (
                selectedLeadNotes?.notes && selectedLeadNotes.notes.length > 0 ? (
                  <div className="relative border-l-2 border-orange-100 pl-4 ml-2 space-y-4">
                    {selectedLeadNotes.notes.map((n) => (
                      <div key={n.id} className="relative">
                        <span className="absolute -left-[21px] top-1.5 w-2.5 h-2.5 rounded-full bg-orange-400 border-2 border-white" />
                        <div className="flex justify-between items-center text-[9px] text-[#94a3b8] font-bold mb-1">
                          <span className="flex items-center gap-1"><StickyNote size={9} className="text-orange-400" /> {timeAgo(n.created_at)}</span>
                          {n.is_pinned && <span className="text-orange-600 bg-orange-50 px-1.5 py-0.5 rounded-full font-black text-[7px]">PINNED</span>}
                        </div>
                        <div className="font-body text-xs text-[#334155] bg-[#f8fafc]/40 border border-[#e2e8f0]/60 p-3.5 rounded-xl leading-relaxed">
                          {n.content}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="p-6 bg-[#f8fafc]/40 border border-[#e2e8f0] text-center rounded-xl text-xs text-[#94a3b8] font-medium">
                    No notes logged for this lead.
                  </div>
                )
              )}

              {/* Calls only */}
              {noteFilter === "calls" && (
                selectedLeadCallLogs.length > 0 ? (
                  <div className="relative border-l-2 border-primary-muted pl-4 ml-2 space-y-3">
                    {selectedLeadCallLogs.map((log) => (
                      <div key={log.id} className="relative">
                        <span className="absolute -left-[21px] top-1.5 w-2.5 h-2.5 rounded-full bg-primary-400 border-2 border-white" />
                        <div className="text-[9px] text-[#94a3b8] font-bold mb-1 flex items-center gap-1">
                          <Phone size={9} className="text-primary-400" /> {timeAgo(log.created_at)}
                        </div>
                        <div className="bg-primary-light/40 border border-primary-muted p-3 rounded-xl flex items-center justify-between">
                          <span className="font-label text-xs font-bold text-[#1e293b]">
                            {callResultLabel(callResultKey(log)) ?? "Call logged"}
                          </span>
                          {(log.duration_seconds ?? 0) > 0 && (
                            <span className="font-mono text-[10px] text-[#94a3b8]">
                              {Math.floor((log.duration_seconds ?? 0) / 60)}m {(log.duration_seconds ?? 0) % 60}s
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="p-6 bg-[#f8fafc]/40 border border-[#e2e8f0] text-center rounded-xl text-xs text-[#94a3b8] font-medium">
                    No call logs found for this lead.
                  </div>
                )
              )}

              {/* WhatsApp only */}
              {noteFilter === "whatsapp" && (
                selectedLeadMessages.length > 0 ? (
                  <div className="space-y-2">
                    {selectedLeadMessages.map((msg) => (
                      <div key={msg.id} className={`flex ${msg.direction === "inbound" ? "justify-start" : "justify-end"}`}>
                        <div className={`max-w-[80%] px-3 py-2 rounded-2xl text-xs font-body leading-relaxed shadow-sm ${
                          msg.direction === "inbound"
                            ? "bg-white border border-[#e2e8f0] text-[#1e293b] rounded-tl-sm"
                            : "bg-primary-50 border border-primary-100 text-ink rounded-tr-sm"
                        }`}>
                          <MessageBubbleContent message={msg} />
                          <p className="text-[9px] text-[#94a3b8] mt-0.5 text-right">{timeAgo(msg.created_at)}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="p-6 bg-[#f8fafc]/40 border border-[#e2e8f0] text-center rounded-xl text-xs text-[#94a3b8] font-medium">
                    No WhatsApp messages found.
                  </div>
                )
              )}
            </div>
          </div>
        )}

        {activeProfileTab === "script" && (
          <ScriptPanel />
        )}

      </div>
    </div>
  );
}

interface ScriptStep {
  order: number;
  text: string;
  note?: string;
  branches?: { label: string; goto: number }[];
}

interface CallScript {
  id: string;
  name: string;
  steps: ScriptStep[];
  active: boolean;
}

function ScriptPanel() {
  const [activeScripts, setActiveScripts] = useState<CallScript[]>([]);
  const [selectedScript, setSelectedScript] = useState<CallScript | null>(null);
  const [loading, setLoading] = useState(true);
  const [currentStep, setCurrentStep] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const auth = await getAuthHeaders();
        const res = await fetch(`${API_URL}/api/v1/call-scripts/resolve`, { headers: auth });
        if (res.ok) {
          const data = await res.json();
          if (!cancelled && Array.isArray(data)) {
            const activeOnly = data.filter((s) => s.active);
            setActiveScripts(activeOnly);
            setSelectedScript(null);
          }
        }
      } catch { /* non-critical */ }
      if (!cancelled) setLoading(false);
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="p-8 text-center">
        <div className="animate-spin w-5 h-5 border-2 border-primary border-t-transparent rounded-full mx-auto" />
        <p className="text-xs text-[#94a3b8] mt-2">Loading scripts...</p>
      </div>
    );
  }

  if (activeScripts.length === 0) {
    return (
      <div className="p-8 bg-[#f8fafc]/40 border border-[#e2e8f0] text-center rounded-xl">
        <FileText size={24} className="text-[#d6cfc9] mx-auto mb-2" />
        <p className="text-xs text-[#94a3b8] font-medium">No active scripts configured.</p>
        <p className="text-[10px] text-[#d6cfc9] mt-1">Create one in Telecalling &rarr; Scripts.</p>
      </div>
    );
  }

  if (!selectedScript) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between border-b border-[#e2e8f0] pb-2 mb-2">
          <h3 className="font-display text-xs font-black text-[#13284A] tracking-widest uppercase flex items-center gap-1.5">
            <FileText size={12} className="text-primary shrink-0" /> Select Script
          </h3>
          <span className="text-[10px] text-[#94a3b8] font-bold">
            {activeScripts.length} Active
          </span>
        </div>

        <div className="grid grid-cols-1 gap-2.5">
          {activeScripts.map((s) => (
            <button
              key={s.id}
              onClick={() => {
                setSelectedScript(s);
                setCurrentStep(0);
              }}
              className="w-full bg-white hover:bg-primary-light/40 border border-[#e2e8f0] hover:border-primary-muted rounded-xl p-3.5 text-left transition-all duration-200 group flex items-start gap-3 shadow-sm hover:shadow"
            >
              <div className="w-8 h-8 rounded-lg bg-primary-light border border-primary-muted flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
                <FileText size={16} className="text-primary" />
              </div>
              <div className="min-w-0 flex-1">
                <h4 className="font-display text-xs font-bold text-[#13284A] truncate group-hover:text-primary transition-colors">
                  {s.name}
                </h4>
                <p className="font-body text-[10px] text-[#94a3b8] mt-0.5">
                  {s.steps?.length || 0} conversational steps
                </p>
              </div>
              <ChevronRight size={14} className="text-[#94a3b8] self-center group-hover:translate-x-0.5 transition-transform shrink-0" />
            </button>
          ))}
        </div>
      </div>
    );
  }

  const steps = [...selectedScript.steps].sort((a, b) => a.order - b.order);
  const step = steps[currentStep] || steps[0] || { order: 1, text: "", note: "", branches: [] };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between border-b border-[#e2e8f0] pb-2 mb-2">
        <button
          onClick={() => setSelectedScript(null)}
          className="inline-flex items-center gap-1.5 text-[10px] font-bold text-primary hover:text-primary-dark transition-colors uppercase tracking-wider font-label"
        >
          &larr; Back to all scripts
        </button>
        <span className="text-[10px] text-[#94a3b8] font-bold">
          Step {currentStep + 1} of {steps.length}
        </span>
      </div>

      <div className="flex items-center justify-between">
        <h3 className="font-display text-xs font-black text-[#13284A] tracking-widest uppercase flex items-center gap-1.5 truncate max-w-[70%]">
          <FileText size={12} className="text-primary shrink-0" /> {selectedScript.name}
        </h3>
      </div>

      <div className="bg-white border-2 border-primary-muted rounded-2xl p-5 shadow-sm">
        <div className="flex items-start gap-3">
          <div className="w-7 h-7 bg-primary-light text-primary rounded-full flex items-center justify-center font-black text-xs shrink-0">
            {step.order}
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-body text-sm text-[#13284A] leading-relaxed whitespace-pre-wrap">{step.text}</p>
            {step.note && (
              <p className="font-body text-xs text-[#94a3b8] italic mt-2">{step.note}</p>
            )}
          </div>
        </div>

        {step.branches && step.branches.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {step.branches.map((b) => (
              <button
                key={b.label}
                onClick={() => {
                  const idx = steps.findIndex((s) => s.order === b.goto);
                  if (idx >= 0) setCurrentStep(idx);
                }}
                className="px-3 py-1.5 bg-primary-light hover:bg-primary-muted text-primary rounded-lg text-xs font-bold border border-primary-muted transition-all flex items-center gap-1"
              >
                {b.label} <ChevronRight size={10} />
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => setCurrentStep(Math.max(0, currentStep - 1))}
          disabled={currentStep === 0}
          className="flex-1 py-2 bg-[#f1f5f9] hover:bg-[#e2e8f0] text-[#1e293b] rounded-xl text-xs font-bold disabled:opacity-30 transition-all"
        >
          Previous
        </button>
        <button
          onClick={() => setCurrentStep(Math.min(steps.length - 1, currentStep + 1))}
          disabled={currentStep === steps.length - 1}
          className="flex-1 py-2 bg-primary hover:bg-primary-dark text-white rounded-xl text-xs font-bold disabled:opacity-30 transition-all"
        >
          Next Step
        </button>
      </div>

      {/* Step overview */}
      <div className="space-y-1 max-h-[150px] overflow-y-auto pr-1">
        {steps.map((s, i) => (
          <button
            key={s.order}
            onClick={() => setCurrentStep(i)}
            className={`w-full text-left px-3 py-2 rounded-lg text-xs font-body transition-all flex items-center gap-2 ${
              i === currentStep
                ? "bg-primary-light text-primary font-bold border border-primary-muted"
                : i < currentStep
                ? "text-[#94a3b8] hover:bg-[#f8fafc]"
                : "text-[#334155] hover:bg-[#f8fafc]"
            }`}
          >
            <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-black shrink-0 ${
              i === currentStep ? "bg-primary text-white" : i < currentStep ? "bg-[#e2e8f0] text-[#475569]" : "bg-[#f1f5f9] text-[#94a3b8]"
            }`}>
              {s.order}
            </span>
            <span className="truncate">{s.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
