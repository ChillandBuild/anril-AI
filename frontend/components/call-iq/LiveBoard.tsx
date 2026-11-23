"use client";

import { useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { AiraLoader } from "@/components/AiraLoader";
import { cn } from "@/lib/utils";
import {
  LIVE_REFRESH_MS, countByState, getLive, minutesText, sinceText, sortLive, stateLabel,
  type LivePerson, type LiveResponse, type LiveState,
} from "@/lib/callIqApi";
import { Card, ErrorBox, Stat } from "./CallIqShell";
import { useCallIqData } from "./useCallIqData";

const STATE_STYLE: Record<LiveState, { chip: string; dot: string }> = {
  on_call: { chip: "bg-emerald-50 text-emerald-800 ring-emerald-200", dot: "bg-emerald-600" },
  idle: { chip: "bg-sky-50 text-sky-900 ring-sky-200", dot: "bg-sky-600" },
  on_break: { chip: "bg-amber-50 text-amber-900 ring-amber-200", dot: "bg-amber-600" },
  off: { chip: "bg-slate-100 text-slate-700 ring-slate-200", dot: "bg-slate-500" },
};

const SUMMARY: { state: LiveState; label: string }[] = [
  { state: "on_call", label: "On a call" },
  { state: "idle", label: "Free" },
  { state: "on_break", label: "On a break" },
  { state: "off", label: "Not logged in" },
];

function PersonCard({ person, now }: { person: LivePerson; now: Date }) {
  const style = STATE_STYLE[person.state] ?? STATE_STYLE.off;
  const since = sinceText(person, now);
  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <h2 className="min-w-0 truncate font-display text-base font-bold text-primary">{person.name}</h2>
        <span className={cn("inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 font-label text-xs font-bold ring-1", style.chip)}>
          <span aria-hidden className={cn("h-2 w-2 rounded-full", style.dot)} />
          {stateLabel(person.state)}
        </span>
      </div>
      {since ? <p className="mt-1 font-label text-xs text-ink-secondary">{since}</p> : null}
      <div className="mt-4 grid grid-cols-2 gap-3">
        <Stat label="Calls today" value={person.calls_today} />
        <Stat label="Break today" value={minutesText(person.break_minutes_today)} />
      </div>
    </Card>
  );
}

function clock(iso: string | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", second: "2-digit", hour12: true }).format(d).toUpperCase();
}

export function LiveBoard() {
  const { data, err, loading, reload } = useCallIqData<LiveResponse>(getLive, "live", true, LIVE_REFRESH_MS);
  // Re-render each minute is not needed: every refresh brings a new "now" with the data.
  const [now] = useState(() => new Date());
  const people = useMemo(() => sortLive(data?.callers ?? []), [data]);
  const counts = useMemo(() => countByState(people), [people]);
  const shownNow = data?.as_of ? new Date(data.as_of) : now;

  if (loading && !data) return <AiraLoader inline className="min-h-40" />;
  if (err && !data) return <ErrorBox message={err} onRetry={reload} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-2" aria-label="How many people are in each state">
          {SUMMARY.map((s) => (
            <span key={s.state} className={cn("inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 font-label text-sm font-bold ring-1", STATE_STYLE[s.state].chip)}>
              {counts[s.state]} {s.label.toLowerCase()}
            </span>
          ))}
        </div>
        <button type="button" onClick={reload} className="inline-flex min-h-10 items-center gap-2 rounded-lg px-3 font-label text-sm font-bold text-ink-secondary hover:bg-black/5">
          <RefreshCw size={14} aria-hidden /> Updated {clock(data?.as_of) || "just now"}
        </button>
      </div>
      {people.length === 0 ? (
        <Card><p className="font-label text-sm text-ink-secondary">No telecallers to show yet. Add them under Team.</p></Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {people.map((p) => <PersonCard key={p.caller_id} person={p} now={shownNow} />)}
        </div>
      )}
      <p className="font-label text-xs text-ink-secondary">This page refreshes by itself every 20 seconds.</p>
    </div>
  );
}
