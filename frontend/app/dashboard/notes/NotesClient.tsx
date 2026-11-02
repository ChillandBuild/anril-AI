"use client";

import { toast } from "sonner";
import { useEffect, useState, useMemo } from "react";
import {
  Search, StickyNote, Plus, X, Pin, User, CalendarClock, RefreshCw, Sparkles,
} from "lucide-react";

import { api, Lead, CallLog, NoteWithLead } from "@/lib/api";
import { formatPhone, timeAgo } from "@/lib/utils";
import type { Note } from "@/app/dashboard/telecalling/types";
import { saveNote, createCallback } from "@/app/dashboard/telecalling/lib/notes-api";
import NoteCard from "./components/NoteCard";
import {
  AiSummaryCard, SEGMENT_COLORS, SEGMENT_LABELS, SentimentTrend, TagChip, TagSelector,
  dotColorFor, outcomeDotColor, TimelineItem,
} from "./components/shared";
import { useLeadsWithActivity, useNotes, useAllNotes } from "@/hooks/useApi";
import { TickMark } from "@/components/ui/controls";
import { AiraLoader } from "@/components/AiraLoader";
import { SegmentBadge } from "@/components/segment-badge";

type PageMode = "by_lead" | "all_notes";
type ViewMode = "grid" | "list";

export function NotesClient({ fallbackLeads }: { fallbackLeads: { data: Lead[] } | null }) {
  const [pageMode, setPageMode] = useState<PageMode>("by_lead");
  const [viewMode, setViewMode] = useState<ViewMode>("grid");

  // Listen for changes from global header
  useEffect(() => {
    const handlePageMode = (e: Event) => {
      const customEvent = e as CustomEvent<PageMode>;
      setPageMode(customEvent.detail);
    };
    const handleViewMode = (e: Event) => {
      const customEvent = e as CustomEvent<ViewMode>;
      setViewMode(customEvent.detail);
    };
    window.addEventListener("change-notes-page-mode", handlePageMode);
    window.addEventListener("change-notes-view-mode", handleViewMode);
    
    // Dispatch initial state when notes page mounts
    window.dispatchEvent(new CustomEvent("notes-page-mode-state", { detail: pageMode }));
    window.dispatchEvent(new CustomEvent("notes-view-mode-state", { detail: viewMode }));

    return () => {
      window.removeEventListener("change-notes-page-mode", handlePageMode);
      window.removeEventListener("change-notes-view-mode", handleViewMode);
    };
  }, []);

  // Update header state when pageMode changes
  useEffect(() => {
    window.dispatchEvent(new CustomEvent("notes-page-mode-state", { detail: pageMode }));
  }, [pageMode]);

  // Update header state when viewMode changes
  useEffect(() => {
    window.dispatchEvent(new CustomEvent("notes-view-mode-state", { detail: viewMode }));
  }, [viewMode]);

  // by-lead state
  const { data: leadsData, isLoading: leadsLoading, mutate: mutateLeads } = useLeadsWithActivity(true, fallbackLeads || undefined);
  const leads = useMemo(() => (leadsData?.data || []) as Lead[], [leadsData?.data]);
  const [search, setSearch] = useState("");
  const [lastCalledMap, setLastCalledMap] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Lead | null>(null);
  const [callLogs, setCallLogs] = useState<CallLog[]>([]);
  const [filterTag, setFilterTag] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<"notes" | "summary">("notes");

  // use SWR hooks for fetching notes
  const { data: notes, isLoading: notesLoading, mutate: mutateNotes } = useNotes(
    selected?.id ?? null,
    pageMode === "by_lead" && !!selected
  );

  const { data: allNotesData, isLoading: allNotesLoading, mutate: mutateAllNotes } = useAllNotes(
    pageMode === "all_notes"
  );
  const allNotes = allNotesData?.data || [];

  // add note state
  const [addTitle, setAddTitle] = useState("");
  const [addContent, setAddContent] = useState("");
  const [addPinned, setAddPinned] = useState(false);
  const [addTags, setAddTags] = useState<string[]>([]);
  const [adding, setAdding] = useState(false);
  const [showCallbackPicker, setShowCallbackPicker] = useState(false);
  const [callbackDate, setCallbackDate] = useState("");
  const [callbackTime, setCallbackTime] = useState("");

  // edit note state (shared between By Lead notes & All Notes board)
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [editPinned, setEditPinned] = useState(false);
  const [editTags, setEditTags] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  // all-notes board state
  const [boardSearch, setBoardSearch] = useState("");
  const [boardTag, setBoardTag] = useState<string | null>(null);
  const [boardSegment, setBoardSegment] = useState<string | null>(null);
  const [boardPinnedOnly, setBoardPinnedOnly] = useState(false);

  useEffect(() => {
    if (leads.length) {
      api.calls.recentByLeads(leads.map((l) => l.id))
        .then(setLastCalledMap)
        .catch(() => {});
    }
  }, [leads]);

  useEffect(() => {
    setDetailTab("notes");
    if (!selected) { setCallLogs([]); return; }
    api.leads.callLogs(selected.id)
      .then(setCallLogs)
      .catch(() => setCallLogs([]));
  }, [selected]);

  const filtered = leads.filter((l) => {
    const q = search.toLowerCase();
    return !q || (l.name ?? "").toLowerCase().includes(q) || (l.phone ?? "").includes(q);
  });

  const sortedLeads = [...filtered].sort((a, b) => {
    const ta = lastCalledMap[a.id] ?? a.created_at ?? "";
    const tb = lastCalledMap[b.id] ?? b.created_at ?? "";
    return tb.localeCompare(ta);
  });

  function goToLead(leadId: string) {
    const lead = leads.find((l) => l.id === leadId);
    setPageMode("by_lead");
    if (lead) {
      setSelected(lead);
    } else {
      api.leads.get(leadId).then(setSelected).catch(() => {});
    }
  }

  function composeAddContent() {
    const title = addTitle.trim();
    const body = addContent.trim();
    return title ? `${title}\n\n${body}` : body;
  }

  async function addNote() {
    if (!selected) return;
    const hasNote = addContent.trim().length > 0 || addTitle.trim().length > 0 || addTags.length > 0;
    const hasCallback = showCallbackPicker && !!callbackDate && !!callbackTime;
    if (!hasNote && !hasCallback) return;
    setAdding(true);
    try {
      if (hasNote) {
        await saveNote(selected.id, composeAddContent(), addPinned, addTags);
      }
      if (hasCallback) {
        await createCallback(selected.id, new Date(`${callbackDate}T${callbackTime}`).toISOString(), composeAddContent());
      }
      setAddTitle(""); setAddContent(""); setAddPinned(false); setAddTags([]);
      setShowCallbackPicker(false); setCallbackDate(""); setCallbackTime("");
      toast.success(hasCallback ? "Callback scheduled" : "Note added");
      await mutateNotes();
      await mutateLeads();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add note");
    } finally { setAdding(false); }
  }

  function startEdit(note: Note | NoteWithLead) {
    setEditingId(note.id);
    setEditContent(note.content);
    setEditPinned(note.is_pinned);
    setEditTags(note.tags ?? []);
  }

  function cancelEdit() {
    setEditingId(null);
  }

  async function saveEdit(noteId: string) {
    setSaving(true);
    try {
      await api.notes.update(noteId, { content: editContent.trim(), is_pinned: editPinned, tags: editTags });
      setEditingId(null);
      await mutateNotes();
      if (pageMode === "all_notes") {
        await mutateAllNotes();
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Update failed");
    } finally { setSaving(false); }
  }

  async function deleteNote(noteId: string) {
    if (!confirm("Delete this note?")) return;
    try {
      await api.notes.delete(noteId);
      await mutateNotes();
      if (pageMode === "all_notes") {
        await mutateAllNotes();
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed");
    }
  }

  const leadNoteItems = notes ? [...notes.pinned, ...notes.notes].filter((n) => !n.call_log_id) : [];
  const filteredLeadNotes = filterTag
    ? leadNoteItems.filter((n: Note) => (n.tags ?? []).includes(filterTag))
    : leadNoteItems;
  const aiLogs = callLogs.filter((l) => l.ai_summary || l.recording_url || l.ai_status);
  const leadTags = Array.from(new Set(leadNoteItems.flatMap((n: Note) => n.tags ?? [])));

  const boardTags = Array.from(new Set(allNotes.flatMap((n) => n.tags ?? [])));
  const filteredAllNotes = allNotes.filter((n) => {
    if (boardPinnedOnly && !n.is_pinned) return false;
    if (boardTag && !(n.tags ?? []).includes(boardTag)) return false;
    if (boardSegment && n.leads?.segment !== boardSegment) return false;
    if (boardSearch) {
      const q = boardSearch.toLowerCase();
      const matchContent = n.content.toLowerCase().includes(q);
      const matchLead = (n.leads?.name ?? "").toLowerCase().includes(q) || (n.leads?.phone ?? "").includes(q);
      if (!matchContent && !matchLead) return false;
    }
    return true;
  });

  const editProps = (note: Note | NoteWithLead) => ({
    isEditing: editingId === note.id,
    editContent, editPinned, editTags, saving,
    onStartEdit: () => startEdit(note),
    onContentChange: setEditContent,
    onPinnedChange: setEditPinned,
    onTagsChange: setEditTags,
    onSave: () => saveEdit(note.id),
    onCancel: cancelEdit,
    onDelete: () => deleteNote(note.id),
  });

  return (
    <div>
      {pageMode === "all_notes" ? (
        <div className="space-y-4">
          {/* Filters bar */}
          <div className="bg-[#f8fafc] rounded-2xl border border-[#e2e8f0] p-4 space-y-3">
            <div className="relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
              <input
                type="text" placeholder="Search notes, lead name or phone…" value={boardSearch}
                onChange={(e) => setBoardSearch(e.target.value)}
                className="w-full pl-9 pr-3 py-2.5 rounded-xl bg-white border border-[#e2e8f0] font-body text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
            <div className="flex items-center gap-1.5 flex-wrap">
              {(["A", "B", "C", "D"] as const).map((seg) => (
                <button
                  key={seg}
                  onClick={() => setBoardSegment(boardSegment === seg ? null : seg)}
                  className={`px-2.5 py-1 rounded-full border font-label text-[10px] font-black uppercase transition-all ${
                    boardSegment === seg ? `${SEGMENT_COLORS[seg]} border-transparent` : "bg-white border-[#e2e8f0] text-[#94a3b8] hover:border-[#d6cfc9]"
                  }`}
                >
                  {SEGMENT_LABELS[seg]}
                </button>
              ))}
              <button
                onClick={() => setBoardPinnedOnly((v) => !v)}
                className={`flex items-center gap-1 px-2.5 py-1 rounded-full border font-label text-[10px] font-bold uppercase transition-all ${
                  boardPinnedOnly ? "bg-amber-100 text-amber-700 border-transparent" : "bg-white border-[#e2e8f0] text-[#94a3b8] hover:border-[#d6cfc9]"
                }`}
              >
                <Pin size={10} /> Pinned
              </button>
              {boardTags.length > 0 && <span className="w-px h-4 bg-[#e2e8f0] mx-1" />}
              {boardTags.map((t) => (
                <button
                  key={t}
                  onClick={() => setBoardTag(boardTag === t ? null : t)}
                  className={`px-2 py-0.5 rounded-full border font-label text-[10px] font-semibold transition-all ${
                    boardTag === t ? "ring-2 ring-current ring-offset-1" : "opacity-60 hover:opacity-100"
                  } bg-primary-light text-primary border-primary-muted`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          {allNotesLoading ? (
            <p className="font-body text-sm text-[#94a3b8] px-2">Loading…</p>
          ) : filteredAllNotes.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-[#94a3b8]">
              <StickyNote size={40} className="mb-3 opacity-30" />
              <p className="font-body text-sm">No notes match your filters.</p>
            </div>
          ) : viewMode === "grid" ? (
            <div className="columns-1 sm:columns-2 lg:columns-3 gap-4">
              {filteredAllNotes.map((note) => (
                <NoteCard key={note.id} note={note} view="grid" showLead {...editProps(note)} onLeadClick={() => goToLead(note.lead_id)} />
              ))}
            </div>
          ) : (
            <div className="space-y-2">
              {filteredAllNotes.map((note) => (
                <NoteCard key={note.id} note={note} view="list" showLead {...editProps(note)} onLeadClick={() => goToLead(note.lead_id)} />
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-12 gap-4">
          {/* Left: lead list */}
          <div className="col-span-4 bg-[#f8fafc] rounded-3xl p-5 shadow-sm border border-[#e2e8f0] flex flex-col" style={{ maxHeight: "calc(100vh - 160px)" }}>
            <div className="relative mb-4 shrink-0">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
              <input
                type="text" placeholder="Search by name or phone…" value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-9 pr-3 py-2.5 rounded-xl bg-white border border-[#e2e8f0] font-body text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
            <div className="flex-1 overflow-y-auto space-y-2 pr-1">
              {leadsLoading && <AiraLoader inline className="min-h-[200px]" />}
              {!leadsLoading && sortedLeads.length === 0 && (
                <p className="font-body text-sm text-[#94a3b8] px-2">No leads found.</p>
              )}
              {sortedLeads.map((lead) => (
                <button
                  key={lead.id}
                  onClick={() => setSelected(lead)}
                  className={`w-full text-left rounded-2xl border p-3 flex items-center gap-3 transition-all ${
                    selected?.id === lead.id
                      ? "bg-white border-primary-muted shadow-sm ring-1 ring-primary/10"
                      : "bg-white/60 border-[#f1f5f9] hover:bg-white hover:shadow-sm"
                  }`}
                >
                  <div className="w-9 h-9 rounded-full bg-primary text-white flex items-center justify-center font-display text-xs font-bold shrink-0">
                    {lead.name ? lead.name.charAt(0).toUpperCase() : <User size={14} />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <p className="font-body text-sm font-bold text-[#13284A] truncate max-w-[110px]">
                        {lead.name || formatPhone(lead.phone)}
                      </p>
                      <span className={`px-1.5 py-0.5 rounded font-label text-[8px] font-black uppercase shrink-0 ${SEGMENT_COLORS[lead.segment]}`}>
                        {SEGMENT_LABELS[lead.segment]}
                      </span>
                    </div>
                    <p className="font-label text-xs text-[#475569] mt-0.5">
                      {lead.name ? formatPhone(lead.phone) : ""}
                    </p>
                    {lastCalledMap[lead.id] && (
                      <p className="font-label text-[10px] text-[#94a3b8] mt-0.5">Called {timeAgo(lastCalledMap[lead.id])}</p>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Right: lead notes */}
          <div className="col-span-8 space-y-4 overflow-y-auto" style={{ maxHeight: "calc(100vh - 160px)" }}>
            {!selected ? (
              <div className="flex flex-col items-center justify-center h-64 text-[#94a3b8] bg-[#f8fafc] rounded-3xl border border-[#e2e8f0]">
                <StickyNote size={40} className="mb-3 opacity-30" />
                <p className="font-body text-sm">Select a lead to view notes</p>
              </div>
            ) : (
              <>
                {/* Lead header */}
                <div className="bg-gradient-to-r from-primary-light via-white to-white rounded-2xl border border-[#e2e8f0] p-5 shadow-sm flex items-center justify-between">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-primary to-primary-500 text-white flex items-center justify-center font-display text-base font-bold shrink-0 shadow-sm">
                      {selected.name ? selected.name.charAt(0).toUpperCase() : <User size={18} />}
                    </div>
                    <div className="min-w-0">
                      <h2 className="font-display text-lg font-extrabold text-[#0A1528] truncate">
                        {selected.name || formatPhone(selected.phone)}
                      </h2>
                      <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                        {selected.name && (
                          <span className="font-label text-xs text-[#475569]">{formatPhone(selected.phone)}</span>
                        )}
                        <SegmentBadge segment={selected.segment} />
                      </div>
                    </div>
                  </div>
                  <button onClick={() => setSelected(null)} className="p-2 rounded-lg hover:bg-white transition-colors text-[#94a3b8] shrink-0">
                    <X size={16} />
                  </button>
                </div>

                {notesLoading ? (
                  <p className="font-body text-sm text-[#94a3b8] px-2">Loading…</p>
                ) : (
                  <>
                    {/* Section tabs (Call Notes / Call Summaries) */}
                    <div className="flex border-b border-[#e2e8f0] bg-white rounded-t-2xl">
                      {[
                        { id: "notes" as const, label: "Call Notes", count: leadNoteItems.length },
                        { id: "summary" as const, label: "Call Summaries", count: aiLogs.length },
                      ].map((t) => (
                        <button
                          key={t.id}
                          onClick={() => setDetailTab(t.id)}
                          className={`px-6 py-3 font-display text-xs font-black tracking-wider uppercase border-b-2 text-center transition-all flex items-center gap-1.5 ${
                            detailTab === t.id
                              ? "border-primary text-primary"
                              : "border-transparent text-[#94a3b8] hover:text-[#334155]"
                          }`}
                        >
                          {t.label}
                          {t.count > 0 && (
                            <span className={`px-1.5 py-0.5 rounded-full font-label text-[10px] normal-case font-bold tracking-normal ${
                              detailTab === t.id ? "bg-primary-light text-primary" : "bg-[#f1f5f9] text-[#94a3b8]"
                            }`}>
                              {t.count}
                            </span>
                          )}
                        </button>
                      ))}
                    </div>

                    {/* Notes section */}
                    {detailTab === "notes" && (
                    <div className="bg-[#f8fafc] rounded-2xl border border-[#e2e8f0] p-4">
                      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                        <h3 className="font-display text-sm font-extrabold text-[#0A1528] flex items-center gap-2">
                          <span className="w-6 h-6 rounded-lg bg-primary-light flex items-center justify-center">
                            <StickyNote size={13} className="text-primary" />
                          </span>
                          Notes
                          {leadNoteItems.length > 0 && (
                            <span className="px-1.5 py-0.5 rounded-full bg-primary-light font-label text-[10px] text-primary">
                              {leadNoteItems.length}
                            </span>
                          )}
                        </h3>
                        {leadTags.length > 0 && (
                          <div className="flex items-center gap-1.5 flex-wrap">
                            {filterTag && (
                              <button onClick={() => setFilterTag(null)}
                                className="flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-primary-light font-label text-[10px] text-primary hover:bg-primary-light">
                                <X size={8} /> Clear
                              </button>
                            )}
                            {leadTags.map((t) => (
                              <button key={t} onClick={() => setFilterTag(filterTag === t ? null : t)}
                                className={`px-2 py-0.5 rounded-full border font-label text-[10px] font-semibold transition-all ${filterTag === t ? "ring-2 ring-current ring-offset-1" : "opacity-60 hover:opacity-100"} bg-primary-light text-primary border-primary-muted`}>
                                {t}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>

                      {filteredLeadNotes.length === 0 ? (
                        <p className="font-body text-sm text-[#94a3b8]">
                          {filterTag ? `No notes tagged "${filterTag}".` : "No notes yet for this lead."}
                        </p>
                      ) : (
                        <div>
                          {filteredLeadNotes.map((note, i) => (
                            <TimelineItem key={note.id} color={dotColorFor(note)} isLast={i === filteredLeadNotes.length - 1}>
                              <NoteCard note={note} view="list" {...editProps(note)} />
                            </TimelineItem>
                          ))}
                        </div>
                      )}
                    </div>
                    )}

                    {/* Summary (AI call summaries) */}
                    {detailTab === "summary" && (
                    <div className="bg-[#f8fafc] rounded-2xl border border-[#e2e8f0] p-4">
                      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                        <h3 className="font-display text-sm font-extrabold text-[#0A1528] flex items-center gap-2">
                          <span className="w-6 h-6 rounded-lg bg-primary-50 flex items-center justify-center">
                            <Sparkles size={13} className="text-primary-500" />
                          </span>
                          Summary
                          {aiLogs.length > 0 && (
                            <span className="px-1.5 py-0.5 rounded-full bg-primary-50 font-label text-[10px] text-primary-600">
                              {aiLogs.length}
                            </span>
                          )}
                        </h3>
                        <SentimentTrend logs={aiLogs} />
                      </div>
                      {aiLogs.length === 0 ? (
                        <p className="font-body text-sm text-[#94a3b8]">No AI summaries yet. They appear after calls are processed.</p>
                      ) : (
                        <div>
                          {aiLogs.map((log, i) => (
                            <TimelineItem key={log.id} color={outcomeDotColor(log)} isLast={i === aiLogs.length - 1}>
                              <AiSummaryCard
                                log={log}
                                prevSummary={aiLogs[i + 1]?.ai_summary ?? undefined}
                                onGenerated={(updated) =>
                                  setCallLogs((logs) => logs.map((l) => (l.id === updated.id ? { ...l, ...updated } : l)))
                                }
                              />
                            </TimelineItem>
                          ))}
                        </div>
                      )}
                    </div>
                    )}

                    {/* Add note composer (compact) */}
                    {detailTab === "notes" && (
                    <div className="bg-white rounded-2xl border border-[#e2e8f0] p-3 space-y-2 shadow-sm">
                      <div className="flex items-center gap-2">
                        <Plus size={12} className="text-primary shrink-0" />
                        <input
                          type="text" value={addTitle} onChange={(e) => setAddTitle(e.target.value)}
                          placeholder="Title (optional)"
                          className="flex-1 px-2.5 py-1.5 rounded-lg bg-[#f8fafc] border border-[#e2e8f0] font-body text-xs font-bold focus:outline-none focus:ring-2 focus:ring-primary focus:bg-white transition-all"
                        />
                      </div>
                      <textarea
                        value={addContent} onChange={(e) => setAddContent(e.target.value)}
                        placeholder="Add a new note…" rows={2}
                        className="w-full px-2.5 py-1.5 rounded-lg bg-[#f8fafc] border border-[#e2e8f0] font-body text-xs focus:outline-none focus:ring-2 focus:ring-primary resize-none"
                      />
                      <div className="flex items-center gap-2 flex-wrap">
                        <button
                          type="button"
                          role="checkbox"
                          aria-checked={addPinned}
                          onClick={() => setAddPinned(!addPinned)}
                          className="flex select-none items-center gap-1.5"
                        >
                          <TickMark checked={addPinned} size="sm" />
                          <span className="font-label text-xs text-[#475569]">Pin note</span>
                        </button>
                        <TagSelector selected={addTags} onChange={setAddTags} />
                        <button
                          type="button"
                          onClick={() => setShowCallbackPicker((v) => !v)}
                          className={`flex items-center gap-1.5 px-2 py-1 rounded-lg font-label text-[11px] font-semibold border transition-all ${
                            showCallbackPicker
                              ? "bg-amber-500 border-amber-500 text-white"
                              : "bg-white border-amber-200 text-amber-700 hover:border-amber-400"
                          }`}
                        >
                          <CalendarClock size={11} /> Schedule Call
                        </button>
                        <div className="flex-1" />
                        <button
                          onClick={addNote}
                          disabled={
                            adding ||
                            (!addContent.trim() && !addTitle.trim() && addTags.length === 0 &&
                              !(showCallbackPicker && callbackDate && callbackTime))
                          }
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white rounded-lg font-label text-xs font-semibold hover:bg-primary-dark disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                          {adding ? <RefreshCw size={12} className="animate-spin" /> : <Plus size={12} />}
                          {adding ? "Saving…" : showCallbackPicker ? "Schedule Callback" : "Add Note"}
                        </button>
                      </div>
                      {addTags.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {addTags.map((t) => <TagChip key={t} label={t} onRemove={() => setAddTags(addTags.filter((x) => x !== t))} />)}
                        </div>
                      )}
                      {showCallbackPicker && (
                        <div className="flex flex-col gap-2 p-2.5 rounded-xl bg-amber-50 border border-amber-200">
                          <h4 className="font-display text-[10px] font-black text-amber-700 tracking-widest uppercase flex items-center gap-1.5">
                            <CalendarClock size={11} /> Schedule Call
                          </h4>
                          <div className="flex gap-2">
                            <input
                              type="date" value={callbackDate} onChange={(e) => setCallbackDate(e.target.value)}
                              className="flex-1 px-2 py-1.5 rounded-lg border border-amber-200 bg-white font-body text-xs focus:outline-none focus:ring-2 focus:ring-amber-300"
                            />
                            <input
                              type="time" value={callbackTime} onChange={(e) => setCallbackTime(e.target.value)}
                              className="flex-1 px-2 py-1.5 rounded-lg border border-amber-200 bg-white font-body text-xs focus:outline-none focus:ring-2 focus:ring-amber-300"
                            />
                          </div>
                        </div>
                      )}
                    </div>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
