"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { ChevronDown, Loader2, Phone, Pin, Search, StickyNote, Users, X } from "lucide-react";
import { api, type Caller, type CallLog, type ReviewLead, type ReviewRange } from "@/lib/api";
import { cn, formatPhone, timeAgo } from "@/lib/utils";
import { useCallers, useNotes } from "@/hooks/useApi";
import { SegmentBadge } from "@/components/segment-badge";
import { CallAiDetail, anyProcessing, scoreColor } from "@/components/CallAi";
import { CallReport } from "@/components/CallReport";
import { hasReportContent } from "@/lib/call-report";
import { TONE_CHIP, callResultKey, callResultLabel, callResultTone } from "@/lib/call-wrapup";
import { saveNote } from "@/app/dashboard/telecalling/lib/notes-api";

type Preset = "today" | "7" | "30" | "custom";
type Tab = "all" | "called" | "notes" | "uncalled" | "review";

const PRESETS: { id: Preset; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "7", label: "Last 7 days" },
  { id: "30", label: "Last 30 days" },
  { id: "custom", label: "Custom" },
];
type ScoreBand = "high" | "mid" | "low" | "none";
// A lead's band comes from its average over scored calls; "none" = no scored call in range.
const SCORE_BANDS: { id: ScoreBand; label: string; test: (avg: number | null) => boolean }[] = [
  { id: "high", label: "80 and above", test: (a) => a != null && a >= 80 },
  { id: "mid", label: "60 to 79", test: (a) => a != null && a >= 60 && a < 80 },
  { id: "low", label: "Under 60", test: (a) => a != null && a < 60 },
  { id: "none", label: "Not scored", test: (a) => a == null },
];
const SEGMENTS: { id: "A" | "B" | "C" | "D"; label: string }[] = [
  { id: "A", label: "Hot" },
  { id: "B", label: "Warm" },
  { id: "C", label: "Cold" },
  { id: "D", label: "Not interested" },
];
const PROCESSING_POLL_MS = 10_000;
const CARD = "bg-white border border-[#e2e8f0] rounded-2xl";
const EYEBROW = "font-label text-[9px] uppercase tracking-widest font-extrabold text-[#94a3b8]";

/** Local-midnight ISO with the browser's offset, so "today" means the admin's today. */
function localIso(d: Date): string {
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  const pad = (n: number) => String(Math.floor(Math.abs(n))).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T00:00:00${sign}${pad(off / 60)}:${pad(off % 60)}`;
}
function dayInput(d: Date): string {
  return localIso(d).slice(0, 10);
}
function addDays(d: Date, n: number): Date {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  x.setDate(x.getDate() + n);
  return x;
}
function rangeFor(preset: Preset, from: string, to: string): { start: string; end: string; label: string } {
  const today = addDays(new Date(), 0);
  if (preset === "custom" && from && to) {
    const [fy, fm, fd] = from.split("-").map(Number);
    const [ty, tm, td] = to.split("-").map(Number);
    const s = new Date(fy, fm - 1, fd);
    const e = addDays(new Date(ty, tm - 1, td), 1);
    const fmt = (d: Date) => d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
    return { start: localIso(s), end: localIso(e), label: `${fmt(s)} – ${fmt(new Date(ty, tm - 1, td))}` };
  }
  const days = preset === "today" ? 1 : preset === "30" ? 30 : 7;
  return {
    start: localIso(addDays(today, 1 - days)),
    end: localIso(addDays(today, 1)),
    label: PRESETS.find((p) => p.id === preset)?.label ?? "",
  };
}
function formatTalk(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h) return `${h}h ${m}m`;
  return `${m}m ${seconds % 60}s`;
}
function formatDuration(seconds: number | null): string {
  if (!seconds) return "—";
  const m = Math.floor(seconds / 60);
  return m ? `${m}m ${seconds % 60}s` : `${seconds % 60}s`;
}
function callWhen(iso: string): string {
  const d = new Date(iso);
  const dateStr = d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  const timeStr = d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true }).toLowerCase();
  return `${dateStr}, ${timeStr}`;
}
/** "25 Sep 26, 14:30" — date plus 24-hour time. */
function noteWhen(iso: string): string {
  const d = new Date(iso);
  const date = d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "2-digit" });
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
  return `${date}, ${time}`;
}
function initial(name: string | null | undefined): string {
  return (name || "?").trim().charAt(0).toUpperCase() || "?";
}

function StatusPill({ call }: { call: Pick<CallLog, "score" | "score_status" | "call_group" | "provider"> | null }) {
  if (!call || call.provider !== "telecmi") return null;
  const base = "shrink-0 px-2 py-0.5 rounded-full border font-label text-[9px] font-bold";
  if ((call.score_status === "scored" || call.score_status === "provisional") && call.score != null) {
    return <span className={cn(base, "font-mono", scoreColor(call.score))}>{call.score.toFixed(1)}</span>;
  }
  const muted = cn(base, "bg-[#f8fafc] text-[#94a3b8] border-[#e2e8f0]");
  if (call.score_status === "early_exit") return <span className={muted}>Early exit</span>;
  if (call.score_status === "not_connected") return <span className={muted}>Not connected</span>;
  if (call.score_status === "very_short") return <span className={muted}>Under 30s</span>;
  return null;
}

/** A dropdown styled as a pill; the first choice ("any") means no filter. */
function FilterSelect({
  id,
  label,
  value,
  onChange,
  anyLabel,
  options,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  anyLabel: string;
  options: { id: string; label: string }[];
}) {
  const active = value !== "";
  return (
    <label
      htmlFor={id}
      className={cn(
        "relative flex items-center h-9 pl-3 pr-7 rounded-xl border bg-white transition-colors",
        active ? "border-[var(--primary-200)] bg-[var(--primary-50)]" : "border-[#e2e8f0]",
      )}
    >
      <span className="sr-only">{label}</span>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "appearance-none bg-transparent font-body text-xs font-bold focus:outline-none cursor-pointer",
          active ? "text-primary" : "text-[#13284A]",
        )}
      >
        <option value="">{anyLabel}</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown size={13} className="absolute right-2.5 text-[#94a3b8] pointer-events-none" />
    </label>
  );
}

export default function CallReview() {
  const { data: callersData } = useCallers();
  const callers = useMemo<Caller[]>(() => {
    const team = callersData?.data ?? [];
    const admin = callersData?.admin_caller;
    return admin ? [{ ...admin, name: `${admin.name || "Admin"} (me)` }, ...team] : team;
  }, [callersData]);
  const callerName = useCallback(
    (id: string | null | undefined) => (id ? callers.find((c) => c.id === id)?.name ?? "Former telecaller" : "Admin"),
    [callers],
  );

  const [preset, setPreset] = useState<Preset>("7");
  const [from, setFrom] = useState(() => dayInput(addDays(new Date(), -29)));
  const [to, setTo] = useState(() => dayInput(new Date()));
  const [callerId, setCallerId] = useState<string>("");
  const [search, setSearch] = useState("");
  const [scoreBand, setScoreBand] = useState<ScoreBand | "">("");
  const [segment, setSegment] = useState<"A" | "B" | "C" | "D" | "">("");
  const [tab, setTab] = useState<Tab>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const window_ = useMemo(() => rangeFor(preset, from, to), [preset, from, to]);
  const range: ReviewRange = useMemo(
    () => ({ start: window_.start, end: window_.end, callerId: callerId || null }),
    [window_.start, window_.end, callerId],
  );

  const [rows, setRows] = useState<ReviewLead[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.callReview
      .leads(range)
      .then((res) => {
        if (cancelled) return;
        setRows(res.data || []);
        setTruncated(!!res.truncated);
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Couldn't load calls"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [range]);

  const filtersActive = !!(search.trim() || scoreBand || segment);
  const searched = useMemo(() => {
    const q = search.trim().toLowerCase();
    const digits = q.replace(/\D/g, "");
    const band = SCORE_BANDS.find((b) => b.id === scoreBand);
    return rows.filter(
      (r) =>
        (!q || (r.name ?? "").toLowerCase().includes(q) || (!!digits && (r.phone ?? "").replace(/\D/g, "").includes(digits))) &&
        (!band || band.test(r.scored > 0 ? r.avg_score : null)) &&
        (!segment || r.segment === segment),
    );
  }, [rows, search, scoreBand, segment]);

  const inTab = useCallback((r: ReviewLead, t: Tab) => {
    if (t === "called") return r.calls > 0;
    if (t === "notes") return r.notes > 0;
    if (t === "uncalled") return r.assigned && r.calls === 0;
    if (t === "review") return r.needs_review;
    return true;
  }, []);
  const tabs: { id: Tab; label: string }[] = [
    { id: "all", label: "All" },
    { id: "called", label: "Called" },
    { id: "notes", label: "Notes saved" },
    ...(callerId ? [{ id: "uncalled" as Tab, label: "Assigned, not called" }] : []),
    { id: "review", label: "Needs review" },
  ];
  const activeTab = tabs.some((t) => t.id === tab) ? tab : "all";
  const visible = searched.filter((r) => inTab(r, activeTab));
  const selected = visible.find((r) => r.id === selectedId) ?? null;

  // Totals follow the filter bar exactly (telecaller, dates, search); the tabs only narrow the list.
  const kpi = useMemo(() => {
    const sum = (k: keyof ReviewLead) => searched.reduce((a, r) => a + (Number(r[k]) || 0), 0);
    const calls = sum("calls");
    const connected = sum("connected");
    const scored = sum("scored");
    return {
      calls,
      leadsCalled: searched.filter((r) => r.calls > 0).length,
      connected,
      connectRate: calls ? Math.round((connected / calls) * 100) : null,
      talk: sum("talk_seconds"),
      avg: scored ? (sum("score_sum") / scored).toFixed(1) : "—",
      scored,
      earlyExits: sum("early_exits"),
      notes: sum("notes"),
      uncalled: searched.filter((r) => r.assigned && r.calls === 0).length,
    };
  }, [searched]);

  const selectedCaller = callers.find((c) => c.id === callerId);

  return (
    <div className="flex flex-col gap-3 pb-6 min-h-full lg:h-[calc(100vh-4rem)] lg:min-h-0">
      {/* Locked header: Filter bar + KPI Cards. On desktop the page is one fixed-height frame, so only the panes below scroll. */}
      <div className="sticky top-14 md:top-16 lg:static lg:shrink-0 z-20 space-y-2 pb-2 pt-2 bg-[#f8fafc]/95 backdrop-blur-md border-b border-[#f1f5f9]/60 px-2 sm:px-3 md:px-4">
        {/* Filter bar */}
        <div className={cn(CARD, "p-2.5 shadow-sm flex flex-wrap items-center gap-2 bg-white/90 backdrop-blur-sm")}>
          <div className="flex p-0.5 gap-0.5 rounded-xl bg-[#f8fafc] border border-[#f1f5f9]" role="group" aria-label="Date range">
            {PRESETS.map((p) => (
              <button
                key={p.id}
                onClick={() => setPreset(p.id)}
                aria-pressed={preset === p.id}
                className={cn(
                  "px-3 py-1.5 rounded-lg font-label text-xs font-bold transition-all",
                  preset === p.id ? "bg-white text-primary shadow-sm" : "text-[#475569] hover:text-[#13284A]",
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
          {preset === "custom" && (
            <div className="flex items-center gap-1.5">
              <input
                id="review-from"
                type="date"
                value={from}
                max={to}
                onChange={(e) => setFrom(e.target.value)}
                aria-label="From date"
                className="h-9 px-2 rounded-xl border border-[#e2e8f0] bg-white font-body text-xs"
              />
              <span className="font-label text-xs text-[#94a3b8]">to</span>
              <input
                id="review-to"
                type="date"
                value={to}
                min={from}
                onChange={(e) => setTo(e.target.value)}
                aria-label="To date"
                className="h-9 px-2 rounded-xl border border-[#e2e8f0] bg-white font-body text-xs"
              />
            </div>
          )}
          <label htmlFor="review-caller" className="relative flex items-center h-9 pl-2 pr-7 gap-2 rounded-xl border border-[#e2e8f0] bg-white">
            <span className="w-6 h-6 rounded-full bg-primary text-white grid place-items-center font-label text-[10px] font-extrabold shrink-0">
              {selectedCaller ? initial(selectedCaller.name) : <Users size={12} />}
            </span>
            <select
              id="review-caller"
              value={callerId}
              onChange={(e) => {
                setCallerId(e.target.value);
                setSelectedId(null);
              }}
              className="appearance-none bg-transparent font-body text-xs font-bold text-[#13284A] focus:outline-none cursor-pointer max-w-[180px] truncate"
            >
              <option value="">All telecallers</option>
              {callers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <ChevronDown size={13} className="absolute right-2.5 text-[#94a3b8] pointer-events-none" />
          </label>
          <label htmlFor="review-search" className="flex-1 min-w-[200px] flex items-center h-9 px-3 gap-2 rounded-xl border border-[#e2e8f0] bg-white">
            <Search size={14} className="text-[#94a3b8] shrink-0" />
            <input
              id="review-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search lead name or phone"
              className="w-full bg-transparent font-body text-xs focus:outline-none"
            />
          </label>
          <FilterSelect
            id="review-score"
            label="Score"
            value={scoreBand}
            onChange={(v) => {
              setScoreBand(v as ScoreBand | "");
              setSelectedId(null);
            }}
            anyLabel="Any score"
            options={SCORE_BANDS}
          />
          <FilterSelect
            id="review-segment"
            label="Segment"
            value={segment}
            onChange={(v) => {
              setSegment(v as "A" | "B" | "C" | "D" | "");
              setSelectedId(null);
            }}
            anyLabel="Any segment"
            options={SEGMENTS}
          />
          {filtersActive && (
            <button
              onClick={() => {
                setSearch("");
                setScoreBand("");
                setSegment("");
                setSelectedId(null);
              }}
              className="inline-flex items-center gap-1 h-9 px-3 rounded-xl font-label text-xs font-bold text-primary hover:bg-[var(--primary-50)] transition-colors"
            >
              <X size={13} /> Clear
            </button>
          )}
        </div>

        {/* KPI Cards (Locked with Filter bar) */}
        <div className={cn(CARD, "grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 overflow-hidden shadow-sm bg-white")}>
          {[
            { label: "Calls", value: kpi.calls, sub: `${kpi.leadsCalled} lead${kpi.leadsCalled === 1 ? "" : "s"}` },
            { label: "Connected", value: kpi.connected, sub: kpi.connectRate == null ? "—" : `${kpi.connectRate}% of calls` },
            { label: "Talk time", value: formatTalk(kpi.talk), sub: "connected calls" },
            { label: "Avg score", value: kpi.avg, sub: `${kpi.scored} scored call${kpi.scored === 1 ? "" : "s"}` },
            { label: "Early exits", value: kpi.earlyExits, sub: "not scored" },
            {
              label: "Notes saved",
              value: kpi.notes,
              sub: callerId ? `${kpi.uncalled} assigned lead${kpi.uncalled === 1 ? "" : "s"} not called` : "in this range",
            },
          ].map((k) => (
            <div key={k.label} className="px-3.5 py-2.5 border-[#f1f5f9] border-l border-t -ml-px -mt-px min-w-0">
              <p className={EYEBROW}>{k.label}</p>
              <p className="font-heading text-xl sm:text-2xl font-extrabold text-[#13284A] tabular-nums mt-0.5 truncate">
                {loading ? <span className="inline-block w-10 h-6 rounded bg-[#f1f5f9] animate-pulse align-middle" /> : k.value}
              </p>
              <p className="font-label text-[11px] text-[#475569] truncate">{k.sub}</p>
            </div>
          ))}
        </div>
        {truncated && <div className="text-amber-700 font-bold text-xs px-1">· Too many calls to total exactly, so narrow the dates</div>}
      </div>

      {/* Panes */}
      <div className="grid grid-cols-1 lg:grid-cols-[340px_minmax(0,1fr)] gap-4 items-start lg:items-stretch lg:flex-1 lg:min-h-0 lg:grid-rows-1 pt-1 px-2 sm:px-3 md:px-4">
        <aside className={cn(CARD, "flex flex-col lg:h-full lg:min-h-0 min-w-0")}>
          <div className="flex flex-wrap gap-1 p-3 border-b border-[#f1f5f9]">
            {tabs.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                aria-pressed={activeTab === t.id}
                className={cn(
                  "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border font-label text-[11px] font-bold transition-colors",
                  activeTab === t.id
                    ? "bg-[var(--primary-50)] border-[var(--primary-200)] text-primary"
                    : "bg-white border-[#e2e8f0] text-[#475569] hover:text-[#13284A]",
                )}
              >
                {t.label}
                <span className="font-mono text-[10px] opacity-70">{searched.filter((r) => inTab(r, t.id)).length}</span>
              </button>
            ))}
          </div>
          <div className="overflow-y-auto p-1.5 max-h-[420px] lg:max-h-none lg:flex-1 lg:min-h-0">
            {loading ? (
              <div className="py-12 flex justify-center">
                <Loader2 size={18} className="animate-spin text-primary" />
              </div>
            ) : error ? (
              <p className="py-10 px-4 text-center font-body text-xs text-rose-700">{error}. Refresh the page to try again.</p>
            ) : visible.length === 0 ? (
              <div className="py-10 px-4 text-center">
                <p className="font-body text-sm font-semibold text-[#475569]">No leads match these filters</p>
                <p className="font-label text-xs text-[#94a3b8] mt-1">Try a wider date range, another telecaller or another tab.</p>
              </div>
            ) : (
              visible.map((r) => (
                <button
                  key={r.id}
                  onClick={() => setSelectedId(r.id)}
                  aria-current={selected?.id === r.id}
                  className={cn(
                    "w-full grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2.5 p-2.5 rounded-xl border text-left transition-colors",
                    selected?.id === r.id
                      ? "bg-[var(--primary-50)] border-[var(--primary-200)]"
                      : "border-transparent hover:bg-[#f8fafc]",
                  )}
                >
                  <span className="w-9 h-9 rounded-full bg-primary text-white grid place-items-center font-label text-sm font-extrabold">
                    {initial(r.name || r.phone)}
                  </span>
                  <span className="min-w-0">
                    <span className="block font-body text-[13px] font-bold text-[#13284A] truncate">
                      {r.name || formatPhone(r.phone) || "Unknown lead"}
                    </span>
                    {r.name && <span className="block font-label text-[11px] text-[#475569] truncate">{formatPhone(r.phone)}</span>}
                    <span className="block font-label text-[11px] text-[#94a3b8] truncate">
                      {r.last_call_at ? `Called ${timeAgo(r.last_call_at)}` : "Not called yet"}
                      {r.calls > 0 && ` · ${r.calls} call${r.calls === 1 ? "" : "s"}`}
                      {r.notes > 0 && ` · ${r.notes} note${r.notes === 1 ? "" : "s"}`}
                    </span>
                  </span>
                  <span className="flex flex-col items-end gap-1">
                    {r.segment && <SegmentBadge segment={r.segment} />}
                    <StatusPill call={r.last_call} />
                  </span>
                </button>
              ))
            )}
          </div>
        </aside>

        <section className={cn(CARD, "min-w-0 lg:h-full lg:min-h-0 lg:flex lg:flex-col lg:overflow-hidden")}>
          {selected ? (
            <LeadWorkspace key={`${selected.id}-${range.start}-${range.end}-${callerId}`} lead={selected} range={range} callerName={callerName} />
          ) : (
            <div className="py-24 px-6 flex flex-col items-center text-center">
              <div className="w-14 h-14 rounded-2xl bg-[var(--primary-50)] text-primary grid place-items-center mb-3">
                <Phone size={22} />
              </div>
              <h3 className="font-heading text-lg font-extrabold text-[#13284A]">Pick a lead</h3>
              <p className="font-body text-sm text-[#475569] mt-1 max-w-sm">
                Choose a lead on the left to see each call&apos;s recording, score, summary and transcript, with the notes saved for it.
              </p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function LeadWorkspace({
  lead,
  range,
  callerName,
}: {
  lead: ReviewLead;
  range: ReviewRange;
  callerName: (id: string | null | undefined) => string;
}) {
  const [calls, setCalls] = useState<CallLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true);
      try {
        setCalls(await api.callReview.leadCalls(lead.id, range));
      } catch {
        if (!quiet) setCalls([]);
      } finally {
        if (!quiet) setLoading(false);
      }
    },
    [lead.id, range],
  );
  useEffect(() => {
    void load();
  }, [load]);

  const processing = anyProcessing(calls);
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(() => void load(true), PROCESSING_POLL_MS);
    return () => clearInterval(timer);
  }, [processing, load]);

  const call = calls.find((c) => c.id === activeId) ?? calls[0] ?? null;

  return (
    <>
      <header className="flex flex-wrap items-center gap-4 px-5 py-4 border-b border-[#f1f5f9] lg:shrink-0">
        <span className="w-12 h-12 rounded-full bg-primary text-white grid place-items-center font-heading text-lg font-extrabold">
          {initial(lead.name || lead.phone)}
        </span>
        <div className="flex-1 min-w-[200px]">
          <h2 className="font-heading text-xl font-extrabold text-[#13284A] flex flex-wrap items-center gap-2">
            {lead.name || formatPhone(lead.phone) || "Unknown lead"}
            {lead.segment && <SegmentBadge segment={lead.segment} />}
          </h2>
          <p className="font-label text-xs text-[#475569] mt-0.5">
            {formatPhone(lead.phone)} · Assigned to <b className="text-[#13284A]">{lead.assigned_to ? callerName(lead.assigned_to) : "nobody"}</b>
          </p>
        </div>
        <dl className="flex gap-5">
          {[
            ["Calls", lead.calls],
            ["Avg score", lead.avg_score?.toFixed(1) ?? "—"],
            ["Notes", lead.notes],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className={EYEBROW}>{k}</dt>
              <dd className="font-heading text-base font-extrabold text-[#13284A] tabular-nums">{v}</dd>
            </div>
          ))}
        </dl>
        <Link
          href={`/dashboard/telecalling?lead_id=${lead.id}`}
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-primary text-white font-label text-xs font-bold hover:opacity-90 transition-opacity"
        >
          <Phone size={13} /> Open in dialer
        </Link>
      </header>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_300px] lg:flex-1 lg:min-h-0 lg:overflow-y-auto">
        <div className="p-4 flex flex-col gap-3 min-w-0 xl:border-r border-[#f1f5f9]">
          <p className={EYEBROW}>Calls in this range</p>
          {loading ? (
            <div className="py-10 flex justify-center">
              <Loader2 size={18} className="animate-spin text-primary" />
            </div>
          ) : calls.length === 0 ? (
            <p className="rounded-2xl border border-[#e2e8f0] bg-[#f8fafc] p-4 font-body text-xs text-[#475569]">
              No calls in the selected dates.{lead.assigned ? " This lead is assigned to the telecaller and still waiting for a call." : ""}
            </p>
          ) : (
            <>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {calls.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => setActiveId(c.id)}
                    aria-pressed={call?.id === c.id}
                    className={cn(
                      "shrink-0 min-w-[175px] text-left rounded-xl border px-3 py-2 transition-all",
                      call?.id === c.id ? "border-primary ring-2 ring-[var(--primary-100)]" : "border-[#e2e8f0] hover:bg-[#f8fafc]",
                    )}
                  >
                    <span className="block font-body text-[11px] font-bold text-[#13284A] whitespace-nowrap">{callWhen(c.created_at)}</span>
                    <span className="block font-label text-[10px] text-[#94a3b8] mt-0.5 mb-1.5 truncate">
                      {formatDuration(c.duration_seconds)} · {callerName(c.caller_id)}
                    </span>
                    <StatusPill call={c} />
                  </button>
                ))}
              </div>
              {call && <CallDetail call={call} callerName={callerName} onChanged={() => void load(true)} />}
            </>
          )}
        </div>
        <NotesRail leadId={lead.id} callerName={callerName} />
      </div>
    </>
  );
}

function CallDetail({
  call,
  callerName,
  onChanged,
}: {
  call: CallLog;
  callerName: (id: string | null | undefined) => string;
  onChanged: () => void;
}) {
  const resultKey = callResultKey(call);
  const audioRef = useRef<HTMLAudioElement>(null);
  const isTelecmi = call.provider === "telecmi";
  // CallReport's verdict row already shows the next step when the report renders.
  const reportShowsNextStep =
    isTelecmi && hasReportContent(call.evaluation?.report) && Boolean(call.ai_summary?.next_action?.trim());

  function seek(seconds: number) {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = seconds;
    audio.play().catch(() => {
      // Autoplay can be blocked; the playhead has still moved, so the user can press play.
    });
  }

  return (
    <div className="flex flex-col gap-2.5">
      <div className="rounded-2xl border border-[#e2e8f0] p-3.5 flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="font-body text-sm font-bold text-[#13284A]">
              {callWhen(call.created_at)} · {formatDuration(call.duration_seconds)}
            </p>
            <p className="font-label text-[11px] text-[#475569]">by {callerName(call.caller_id)}</p>
          </div>
          {resultKey && (
            <span className={cn("px-2 py-0.5 rounded-full border font-label text-[10px] font-bold", TONE_CHIP[callResultTone(resultKey)])}>
              {callResultLabel(resultKey) ?? resultKey}
            </span>
          )}
        </div>
        {call.recording_url ? (
          <audio ref={audioRef} key={call.id} src={call.recording_url} controls className="w-full h-9" />
        ) : (
          <p className="font-label text-[11px] italic text-[#94a3b8]">No recording for this call.</p>
        )}
      </div>
      {isTelecmi && <CallReport log={call} onSeek={call.recording_url ? seek : undefined} />}
      {isTelecmi ? (
        <CallAiDetail log={call} onChanged={onChanged} />
      ) : (
        call.ai_summary?.brief && (
          <p className="rounded-xl border border-[#f1f5f9] bg-white px-3 py-2.5 font-body text-[11px] leading-relaxed text-[#1e293b]">{call.ai_summary.brief}</p>
        )
      )}
      {call.ai_summary?.next_action && !reportShowsNextStep && (
        <div className="rounded-xl border border-[#f1f5f9] bg-white px-3 py-2.5">
          <p className="font-label text-[9px] uppercase tracking-widest font-extrabold text-primary mb-1">Next step</p>
          <p className="font-body text-[11px] leading-relaxed text-[#1e293b]">{call.ai_summary.next_action}</p>
        </div>
      )}
    </div>
  );
}

function NotesRail({ leadId, callerName }: { leadId: string; callerName: (id: string | null | undefined) => string }) {
  const { data, mutate, isLoading } = useNotes(leadId);
  // Only notes a person typed: Aira's "AI Summary:" notes show as each call's Next step instead.
  const notes = [...(data?.pinned ?? []), ...(data?.notes ?? [])].filter(
    (n) => n.content?.trim() && !n.content.startsWith("AI Summary:"),
  );
  // Notes saved before authors were recorded have no caller_id.
  const author = (n: (typeof notes)[number]) => (n.caller_id ? callerName(n.caller_id) : "Author not recorded");
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  async function add() {
    const text = draft.trim();
    if (!text) return;
    setSaving(true);
    try {
      await saveNote(leadId, text, false);
      setDraft("");
      await mutate();
      toast.success("Note added");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't add the note");
    } finally {
      setSaving(false);
    }
  }

  return (
    <aside className="p-4 flex flex-col gap-2.5 bg-[#f8fafc] rounded-b-2xl xl:rounded-bl-none xl:rounded-r-2xl min-w-0">
      <p className={cn(EYEBROW, "flex items-center gap-1.5")}>
        <StickyNote size={11} /> All notes on this lead · {notes.length}
      </p>
      {isLoading ? (
        <div className="py-6 flex justify-center">
          <Loader2 size={16} className="animate-spin text-primary" />
        </div>
      ) : notes.length === 0 ? (
        <p className="font-body text-xs text-[#94a3b8]">No notes yet.</p>
      ) : (
        notes.map((n) => (
          <div key={n.id} className={cn("rounded-xl border bg-white p-2.5 flex flex-col gap-1", n.is_pinned ? "border-amber-200" : "border-[#e2e8f0]")}>
            <div className="flex items-center gap-1.5 font-label text-[11px] text-[#475569]">
              <span className="w-[18px] h-[18px] rounded-full bg-primary text-white grid place-items-center text-[9px] font-extrabold">
                {initial(author(n))}
              </span>
              <b className="text-[#13284A] truncate">{author(n)}</b>
              <span className="shrink-0">{n.created_at ? noteWhen(n.created_at) : ""}</span>
              {n.is_pinned && <Pin size={11} className="ml-auto text-amber-600 shrink-0" aria-label="Pinned" />}
            </div>
            <p className="font-body text-xs text-[#334155] whitespace-pre-wrap break-words">{n.content}</p>
            {!!n.tags?.length && (
              <div className="flex flex-wrap gap-1">
                {n.tags.map((t) => (
                  <span key={t} className="px-1.5 py-0.5 rounded-full border border-[#e2e8f0] bg-[#f8fafc] font-label text-[9px] font-bold text-[#475569]">
                    {t}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))
      )}
      <div className="rounded-xl border border-[#e2e8f0] bg-white p-2 flex flex-col gap-1.5 mt-1">
        <textarea
          id={`review-note-${leadId}`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Add a coaching note or follow-up"
          aria-label="Add a note"
          rows={3}
          className="w-full resize-y bg-transparent font-body text-xs focus:outline-none"
        />
        <button
          onClick={add}
          disabled={saving || !draft.trim()}
          className="self-end inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-white font-label text-xs font-bold disabled:opacity-50"
        >
          {saving && <Loader2 size={12} className="animate-spin" />} Add note
        </button>
      </div>
    </aside>
  );
}
