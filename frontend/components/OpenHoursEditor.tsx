"use client";

// v9.2 #59 / #92: the one place the shop's open hours are set. Used by setup step 3 and Settings › Open hours.
// The AI agent answers "are you open?" from it, customer booking times stay inside it, and the after-hours
// message follows it.
import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { SwitchPill } from "@/components/ui/controls";
import {
  WEEKDAYS,
  openDaysFrom,
  openDaysToHours,
  openHoursApi,
  openHoursProblem,
  type OpenDay,
  type OpenHours,
} from "@/lib/replySettingsApi";

const FIELD =
  "w-[7.4rem] rounded-xl border border-border-subtle bg-white px-2 py-2 sm:w-[7.5rem] sm:px-3 font-body text-sm text-ink focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-60";

export function OpenHoursEditor({
  canManage = true,
  saveLabel = "Save open hours",
  onSaved,
  footerNote,
}: {
  canManage?: boolean;
  saveLabel?: string;
  onSaved?: (saved: OpenHours) => void;
  footerNote?: string;
}) {
  const [saved, setSaved] = useState<OpenHours | null>(null);
  const [days, setDays] = useState<OpenDay[]>([]);
  const [holidays, setHolidays] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(false);
    try {
      const r = await openHoursApi.get();
      setSaved(r);
      setDays(openDaysFrom(r));
      setHolidays(r.national_holidays);
    } catch {
      setLoadError(true);
    }
  }, []);
  useEffect(() => void load(), [load]);

  function change(i: number, patch: Partial<OpenDay>) {
    setDays((all) => all.map((d, j) => (j === i ? { ...d, ...patch } : d)));
    setError(null);
  }

  async function save() {
    const problem = openHoursProblem(days);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await openHoursApi.save({ hours: openDaysToHours(days, saved?.hours), national_holidays: holidays });
      setSaved(r);
      setDays(openDaysFrom(r));
      toast.success("Open hours saved");
      onSaved?.(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (loadError) {
    return (
      <div role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-4 font-body text-sm text-red-800">
        Couldn&apos;t load your open hours.{" "}
        <button type="button" onClick={() => void load()} className="font-bold underline">Try again</button>
      </div>
    );
  }
  if (!saved) return <div className="h-72 animate-pulse rounded-2xl bg-border-subtle" aria-label="Loading open hours" />;

  return (
    <div className="space-y-4">
      <fieldset className="divide-y divide-border-subtle rounded-2xl border border-border-subtle" disabled={!canManage || busy}>
        <legend className="sr-only">Open hours for each day (India time)</legend>
        {days.map((d, i) => (
          <div key={WEEKDAYS[i]} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5">
            <span id={`oh-day-${i}`} className="w-10 font-label text-sm font-bold text-ink">{WEEKDAYS[i]}</span>
            <SwitchPill on={d.on} size="sm" disabled={!canManage || busy} aria-label={`${WEEKDAYS[i]} open`}
              onChange={(on) => change(i, { on })} />
            {d.on ? (
              // The two times stay together, so on a phone they drop under the day as one line.
              <span className="flex items-center gap-2">
                <input type="time" value={d.open} aria-label={`${WEEKDAYS[i]} opens at`} className={FIELD}
                  onChange={(e) => change(i, { open: e.target.value })} />
                <span className="font-body text-sm text-ink-muted">to</span>
                <input type="time" value={d.close} aria-label={`${WEEKDAYS[i]} closes at`} className={FIELD}
                  onChange={(e) => change(i, { close: e.target.value })} />
              </span>
            ) : (
              <span className="font-body text-sm text-ink-muted">Closed</span>
            )}
          </div>
        ))}
      </fieldset>
      <label className="flex items-center gap-2 font-body text-sm text-ink">
        <input type="checkbox" checked={holidays} disabled={!canManage || busy} onChange={(e) => setHolidays(e.target.checked)}
          className="h-4 w-4 rounded border-border accent-primary" />
        Closed on national holidays (26 Jan, 15 Aug, 2 Oct)
      </label>
      {saved.set && saved.status && (
        <p className="font-body text-xs text-ink-muted" aria-live="polite">Right now: {saved.status}. Times are India time.</p>
      )}
      {error && <p role="alert" className="font-body text-sm text-danger">{error}</p>}
      <div className="flex flex-wrap items-center justify-end gap-3">
        {footerNote && <span className="font-body text-xs text-ink-muted">{footerNote}</span>}
        {canManage && (
          <button type="button" onClick={() => void save()} disabled={busy} className="btn-primary inline-flex items-center gap-2">
            {busy && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            {saveLabel}
          </button>
        )}
      </div>
    </div>
  );
}
