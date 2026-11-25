"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Clock, Coffee, Download, Grid3X3, History, Inbox, Phone, RefreshCw, Search, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api, type Lead } from "@/lib/api";
import { formatPhone, timeAgo } from "@/lib/utils";
import { AiraLoader } from "@/components/AiraLoader";
import { isClosedLeadStatus } from "@/lib/call-wrapup";
import PhoneLeadSheet from "./PhoneLeadSheet";
import LeadDetailPanel from "./components/LeadDetailPanel";
import ManualDialPanel from "./components/ManualDialPanel";
import RecentCallsTab from "./components/RecentCallsTab";
import type { CallingCockpit } from "./lib/useCallingCockpit";
import type { CallbackJob } from "./types";

type Status = "active" | "break" | "logged_out";
type Group = "queue" | "scheduled" | "done" | "dialer" | "recent";

interface Props {
  cockpit: CallingCockpit;
  callerId: string | null;
  readOnly: boolean;
  myStatus: Status;
  onStatusChange: (s: Status) => void;
  queueLoading: boolean;
  queueLeads: Lead[];
  scheduledLeads: Lead[];
  doneLeads: Lead[];
  allLeads: Lead[];
  lastCalledMap: Record<string, string>;
  searchQuery: string;
  onSearchChange: (v: string) => void;
  setHistoryLead: (lead: Lead | null) => void;
  onExportCsv: () => void;
  exporting: boolean;
}

const SOURCE_LABEL: Record<string, string> = {
  whatsapp: "WhatsApp",
  instagram: "Instagram",
  facebook: "Facebook",
  telegram: "Telegram",
  indiamart: "IndiaMART",
  justdial: "Justdial",
  meta_form: "Meta form",
  upload: "Uploaded list",
  csv: "Uploaded list",
};

function clockTime(iso: string) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}

function leadLine(lead: Lead, called: string | undefined, cb: CallbackJob | undefined) {
  if (lead.call_status === "callback") {
    return cb ? `Call back at ${clockTime(cb.scheduled_for)}` : "Asked to be called later";
  }
  if (called) return `Called ${timeAgo(called)}`;
  const src = lead.source ? SOURCE_LABEL[lead.source.toLowerCase()] ?? lead.source : "";
  return src ? `New from ${src}` : "Not called yet";
}

export default function PhoneCallerView({
  cockpit, callerId, readOnly, myStatus, onStatusChange, queueLoading,
  queueLeads, scheduledLeads, doneLeads, allLeads, lastCalledMap,
  searchQuery, onSearchChange, setHistoryLead, onExportCsv, exporting,
}: Props) {
  const [group, setGroup] = useState<Group>("queue");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [statusBusy, setStatusBusy] = useState(false);
  const [stats, setStats] = useState<{ calls?: number; booked?: number; target?: number }>({});
  const [now, setNow] = useState(() => Date.now());

  // Today's numbers. Only figures the API returns are shown.
  const loadStats = useCallback(async () => {
    const [today, perf] = await Promise.allSettled([api.calls.statsToday(), api.callers.myPerformance()]);
    setStats({
      calls: today.status === "fulfilled" ? today.value.calls_today : undefined,
      booked: today.status === "fulfilled" ? today.value.conversions_today : undefined,
      target: perf.status === "fulfilled" ? perf.value.target : undefined,
    });
  }, []);
  // The first load comes from the wrap-up effect below (it runs on mount too).
  useEffect(() => {
    const t = setInterval(loadStats, 60000);
    return () => clearInterval(t);
  }, [loadStats]);
  // A finished wrap-up changes the numbers: refresh when the sheet closes.
  const wrapupOpen = cockpit.showWrapupModal;
  useEffect(() => { if (!wrapupOpen) loadStats(); }, [wrapupOpen, loadStats]);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);

  const callbackByLead = useMemo(() => {
    const m: Record<string, CallbackJob> = {};
    for (const cb of cockpit.todayCallbacks) if (cb.status === "pending") m[cb.lead_id] = cb;
    return m;
  }, [cockpit.todayCallbacks]);

  const dueCallback = useMemo(() => {
    const limit = now + 15 * 60 * 1000;
    return cockpit.todayCallbacks
      .filter((cb) => cb.status === "pending" && Date.parse(cb.scheduled_for) <= limit)
      .filter((cb) => !callerId || !cb.lead?.assigned_to || cb.lead.assigned_to === callerId)
      .sort((a, b) => Date.parse(a.scheduled_for) - Date.parse(b.scheduled_for))[0];
  }, [cockpit.todayCallbacks, now, callerId]);
  const dueLead = dueCallback ? allLeads.find((l) => l.id === dueCallback.lead_id) : undefined;

  async function toggleStatus() {
    if (statusBusy) return;
    const next: Status = myStatus === "active" ? "break" : "active";
    setStatusBusy(true);
    try {
      await api.callers.setMyStatus(next);
      onStatusChange(next);
    } catch {
      toast.error("Couldn't change your status. Try again.");
    } finally {
      setStatusBusy(false);
    }
  }

  const closeSheet = useCallback(() => setSheetOpen(false), []);

  // A link with ?lead_id= (SIM hand-off from a computer, alerts, Call reviews): CallerView selects
  // the lead; here it also opens, once per link.
  const linkedLeadId = useSearchParams()?.get("lead_id") ?? null;
  const openedLink = useRef<string | null>(null);
  useEffect(() => {
    if (linkedLeadId && linkedLeadId !== openedLink.current && cockpit.selectedLeadId === linkedLeadId) {
      openedLink.current = linkedLeadId;
      setSheetOpen(true);
    }
  }, [linkedLeadId, cockpit.selectedLeadId]);

  function openLead(lead: Lead) {
    cockpit.setSelectedLeadId(lead.id);
    setSheetOpen(true);
  }

  const dial = (lead: Lead) => {
    cockpit.setSelectedLeadId(lead.id);
    cockpit.dialWithGuard(lead.id, lead);
  };

  const groupLeads = group === "queue" ? queueLeads : group === "scheduled" ? scheduledLeads : doneLeads;
  const count = (n: number) => (queueLoading ? "-" : String(n));
  const canCallNext = !readOnly && !cockpit.dialingNext && myStatus === "active";
  const disabledReason = readOnly
    ? "You can only view calls right now"
    : myStatus === "break"
      ? "You are on a break"
      : myStatus === "logged_out"
        ? "You are signed out"
        : null;
  const dialLine = cockpit.callingProvider === "sim_basic" ? "The call goes from your SIM" : "Cloud call";
  const hasTarget = (stats.target ?? 0) > 0 && stats.calls !== undefined;
  const pct = hasTarget ? Math.min(100, Math.round(((stats.calls ?? 0) / (stats.target ?? 1)) * 100)) : 0;

  const statusStyle =
    myStatus === "active"
      ? "bg-primary text-white"
      : "bg-amber-100 text-amber-900 border border-amber-300";
  const statusLabel = myStatus === "active" ? "Available" : myStatus === "break" ? "On a break" : "Signed out";

  return (
    <div className="flex min-w-0 flex-col gap-3 lg:hidden">
      {/* 1. Status */}
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={toggleStatus}
          disabled={statusBusy}
          aria-label={myStatus === "active" ? "You are available. Tap to take a break" : "Tap to become available"}
          className={`inline-flex min-h-[44px] items-center gap-2 rounded-full px-4 font-label text-sm font-bold shadow-sm transition active:scale-[0.98] disabled:opacity-60 ${statusStyle}`}
        >
          {myStatus === "active" ? <span className="h-2.5 w-2.5 rounded-full bg-white" /> : <Coffee size={16} />}
          {statusLabel}
        </button>
        <p className="min-w-0 truncate text-right font-body text-xs text-ink-muted">
          {myStatus === "active" ? "Tap to take a break" : "Tap to start calling"}
        </p>
      </div>

      {/* 2. Your day */}
      {(stats.calls !== undefined || stats.booked !== undefined) && (
        <div className="rounded-2xl border border-border bg-white p-4 shadow-sm">
          <p className="font-label text-xs font-bold uppercase tracking-wide text-ink-muted">Your day</p>
          <div className="mt-2 flex items-end gap-6">
            {stats.calls !== undefined && (
              <div className="min-w-0">
                <p className="font-display text-2xl font-extrabold text-ink">
                  {hasTarget ? `${stats.calls} / ${stats.target}` : stats.calls}
                </p>
                <p className="font-body text-xs text-ink-secondary">Calls today</p>
              </div>
            )}
            {stats.booked !== undefined && (
              <div className="min-w-0">
                <p className="font-display text-2xl font-extrabold text-ink">{stats.booked}</p>
                <p className="font-body text-xs text-ink-secondary">Booked today</p>
              </div>
            )}
          </div>
          {hasTarget && (
            <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-surface-mid" aria-hidden>
              <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
            </div>
          )}
        </div>
      )}

      {/* 3. Callback due */}
      {dueCallback && (
        <div className="flex items-center gap-3 rounded-2xl border border-amber-300 bg-amber-50 p-3">
          <div className="min-w-0 flex-1">
            <p className="font-label text-xs font-bold uppercase tracking-wide text-amber-800">Callback due</p>
            <p className="truncate font-body text-sm font-semibold text-ink">
              {clockTime(dueCallback.scheduled_for)} · {dueCallback.lead?.name || formatPhone(dueCallback.lead?.phone)}
            </p>
          </div>
          {dueLead && (
            <button
              type="button"
              onClick={() => dial(dueLead)}
              disabled={readOnly || cockpit.dialing === dueLead.id}
              className="inline-flex min-h-[44px] shrink-0 items-center gap-1.5 rounded-xl bg-amber-500 px-4 font-label text-sm font-bold text-white active:scale-[0.98] disabled:opacity-50"
            >
              <Phone size={15} className="fill-white" /> Call now
            </button>
          )}
        </div>
      )}

      {/* 4. Next up */}
      <div className="rounded-3xl border border-navy-700 bg-navy p-4 shadow-md">
        <div className="flex items-center justify-between gap-3">
          <p className="font-label text-xs font-bold uppercase tracking-wide text-navy-accent">Next up</p>
          <p className="min-w-0 truncate font-body text-xs text-white/70">
            {queueLoading ? "Loading..." : `${queueLeads.length} left in queue`}
          </p>
        </div>
        <button
          type="button"
          onClick={cockpit.handleCallNext}
          disabled={!canCallNext}
          className="mt-3 flex min-h-[52px] w-full items-center justify-center gap-2 rounded-2xl bg-primary px-4 font-display text-base font-extrabold text-white transition active:scale-[0.99] disabled:opacity-50"
        >
          {cockpit.dialingNext ? <RefreshCw size={18} className="animate-spin" /> : <Sparkles size={18} className="fill-white" />}
          Call next
        </button>
        <p className="mt-2 font-body text-xs text-white/70">{disabledReason ?? dialLine}</p>
      </div>

      {/* 5. Segmented control */}
      <div className="grid grid-cols-3 gap-1 rounded-2xl bg-surface-mid p-1" role="tablist" aria-label="Lead groups">
        {([
          ["queue", "Queue", queueLeads.length],
          ["scheduled", "Scheduled", scheduledLeads.length],
          ["done", "Done", doneLeads.length],
        ] as const).map(([id, label, n]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={group === id}
            onClick={() => setGroup(id)}
            className={`flex h-10 min-w-0 flex-col items-center justify-center rounded-xl px-1 font-label leading-tight transition ${
              group === id ? "bg-white text-primary-900 shadow-sm" : "text-ink-secondary"
            }`}
          >
            <span className="max-w-full truncate text-[12.5px] font-bold">{label}</span>
            <span className="text-[10.5px] font-semibold opacity-80">{count(n)}</span>
          </button>
        ))}
      </div>

      {/* Dial a number, recent calls and the CSV export: the old phone layout had all three. */}
      <div className="grid grid-cols-3 gap-2">
        {([
          ["dialer", "Dial", Grid3X3],
          ["recent", "Recent", History],
        ] as const).map(([id, label, Icon]) => (
          <button
            key={id}
            type="button"
            aria-pressed={group === id}
            aria-label={id === "dialer" ? "Dial a number" : "Recent calls"}
            onClick={() => setGroup(group === id ? "queue" : id)}
            className={`flex h-9 min-w-0 items-center justify-center gap-1.5 rounded-xl border px-2 font-label text-xs font-bold ${
              group === id ? "border-navy bg-navy text-white" : "border-border bg-white text-ink"
            }`}
          >
            <Icon size={15} className="shrink-0" aria-hidden />
            <span className="truncate">{label}</span>
          </button>
        ))}
        <button
          type="button"
          onClick={onExportCsv}
          disabled={exporting || allLeads.length === 0}
          aria-label="Export your leads as CSV"
          className="flex h-9 min-w-0 items-center justify-center gap-1.5 rounded-xl border border-border bg-white px-2 font-label text-xs font-bold text-ink disabled:opacity-50"
        >
          {exporting ? <RefreshCw size={15} className="shrink-0 animate-spin" aria-hidden /> : <Download size={15} className="shrink-0" aria-hidden />}
          <span className="truncate">Export</span>
        </button>
      </div>

      {group === "dialer" ? (
        <div className="min-w-0 rounded-2xl border border-border bg-white p-3">
          <ManualDialPanel cockpit={cockpit} readOnly={readOnly} />
        </div>
      ) : group === "recent" ? (
        <div className="min-w-0 rounded-2xl border border-border bg-white p-3">
          <RecentCallsTab callerId={callerId} onSelectLead={(id) => { cockpit.setSelectedLeadId(id); setSheetOpen(true); }} />
        </div>
      ) : (
      <>
      <div className="relative">
        <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-muted" />
        <input
          type="search"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search name or phone"
          className="h-10 w-full rounded-xl border border-border bg-white pl-10 pr-3 font-body text-base text-ink focus:outline-none focus:ring-2 focus:ring-primary"
        />
      </div>

      {/* 6. List */}
      {queueLoading ? (
        <AiraLoader inline className="min-h-[160px]" />
      ) : groupLeads.length === 0 ? (
        <div className="flex flex-col items-center rounded-2xl border border-border bg-white px-4 py-10 text-center">
          <Inbox size={22} className="text-ink-muted" />
          <p className="mt-2 font-body text-sm font-semibold text-ink-secondary">
            {allLeads.length === 0 ? "No leads assigned to you" : "Nothing here"}
          </p>
        </div>
      ) : (
        <ul className="flex flex-col gap-2">
          {groupLeads.map((lead) => (
            <li key={lead.id} className="min-w-0">
              <div
                role="button"
                tabIndex={0}
                onClick={() => openLead(lead)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openLead(lead); } }}
                className="flex min-h-[64px] items-center gap-3 rounded-2xl border border-border bg-white p-3 shadow-sm active:bg-surface-mid"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-center gap-2">
                    <p className="min-w-0 truncate font-body text-[15px] font-bold text-ink">
                      {lead.name || formatPhone(lead.phone)}
                    </p>
                    <PhoneSegmentChip segment={lead.segment} />
                  </div>
                  <p className="mt-0.5 flex min-w-0 items-center gap-1 font-body text-xs text-ink-muted">
                    <Clock size={11} className="shrink-0" />
                    <span className="truncate">{leadLine(lead, lastCalledMap[lead.id], callbackByLead[lead.id])}</span>
                  </p>
                </div>
                <button
                  type="button"
                  aria-label={`Call ${lead.name || formatPhone(lead.phone)}`}
                  onClick={(e) => { e.stopPropagation(); dial(lead); }}
                  disabled={readOnly || cockpit.dialing === lead.id}
                  className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-white shadow-sm active:scale-95 disabled:opacity-50 ${
                    isClosedLeadStatus(lead.call_status) ? "bg-slate-400" : "bg-primary"
                  }`}
                >
                  <Phone size={18} className="fill-white" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      </>
      )}

      {sheetOpen && cockpit.selectedLeadId && (
        <PhoneLeadSheet
          title={cockpit.selectedLead?.name || formatPhone(cockpit.selectedLead?.phone) || "Lead"}
          onClose={closeSheet}
        >
          <LeadDetailPanel {...cockpit.leadDetailProps} setHistoryLead={setHistoryLead} readOnly={readOnly} />
        </PhoneLeadSheet>
      )}
    </div>
  );
}

const PHONE_SEGMENT: Record<string, { label: string; cls: string }> = {
  A: { label: "Hot", cls: "bg-rose-100 text-rose-800" },
  B: { label: "Warm", cls: "bg-amber-100 text-amber-900" },
  C: { label: "Cold", cls: "bg-slate-200 text-slate-700" },
  D: { label: "Not interested", cls: "bg-slate-100 text-slate-600" },
};

/** Hot / Warm / Cold in the same rose / amber / slate as Home, Chats and Customers. */
function PhoneSegmentChip({ segment }: { segment: string | null | undefined }) {
  const seg = segment ? PHONE_SEGMENT[segment] : undefined;
  if (!seg) return null;
  return <span className={`shrink-0 rounded-full px-2 py-0.5 font-label text-[11px] font-extrabold ${seg.cls}`}>{seg.label}</span>;
}
