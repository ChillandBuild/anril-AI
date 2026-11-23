"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { bookingsApi } from "@/lib/bookingsApi";
import { sameInstant, timesByPart } from "./bookingsLogic";
import { addDays, dayLabel, formatDateTime, formatDay, todayIst } from "./bookingsTime";

export interface PickedSlot {
  start_at: string;
  resource_id: string;
  resource_name: string;
}

function timeText(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: "Asia/Kolkata" }).toUpperCase();
}

/**
 * Day chips (days that have a free time) and the free times of the picked day, for one service and one
 * column ("any" = anyone free). Used by New booking and by Move.
 */
export function SlotPicker({
  serviceId,
  resourceId,
  value,
  onChange,
  initialDate,
  wantedStart,
  excludeBookingId,
}: {
  serviceId: string;
  resourceId: string;
  value: PickedSlot | null;
  /** auto = true when the picker chose the time itself (the wantedStart one). */
  onChange: (slot: PickedSlot, auto?: boolean) => void;
  initialDate?: string;
  /** A time that was asked for (a clicked free gap). Picked for you once it shows up as free. */
  wantedStart?: string | null;
  /** When moving: this booking's own time counts as free. */
  excludeBookingId?: string;
}) {
  const [date, setDate] = useState<string>(initialDate ?? todayIst());
  const days = useSWR(serviceId ? ["bookings/free-days", serviceId, resourceId, excludeBookingId ?? ""] : null, () => bookingsApi.freeDays(serviceId, resourceId, excludeBookingId), { revalidateOnFocus: false });
  const times = useSWR(serviceId ? ["bookings/free", serviceId, resourceId, date, excludeBookingId ?? ""] : null, () => bookingsApi.free(serviceId, resourceId, date, excludeBookingId), { revalidateOnFocus: false });

  // With no day asked for, start on the first day that has a free time.
  const firstFree = days.data?.dates?.[0];
  const [auto, setAuto] = useState(!initialDate);
  useEffect(() => {
    if (auto && firstFree) {
      setDate(firstFree);
      setAuto(false);
    }
  }, [auto, firstFree]);

  // The clicked free gap: pick it once the free times for its day are in.
  const list = times.data?.times;
  useEffect(() => {
    if (!wantedStart || value || !list) return;
    const hit = list.find((t) => sameInstant(t.start_at, wantedStart));
    if (hit) onChange(hit, true);
  }, [wantedStart, value, list, onChange]);

  const dates = days.data?.dates ?? [];
  const parts = timesByPart(times.data?.times ?? []);
  const today = todayIst();

  return (
    <div className="space-y-3">
      <div>
        <p className="mb-1 font-label text-xs font-bold text-ink-muted">Day</p>
        <div className="flex gap-2 overflow-x-auto pb-1" role="group" aria-label="Pick a day">
          {days.isLoading && <Loader2 size={16} className="animate-spin text-ink-muted" aria-label="Loading days" />}
          {dates.slice(0, 21).map((d) => (
            <button
              key={d}
              type="button"
              aria-pressed={d === date}
              onClick={() => setDate(d)}
              className={cn(
                "shrink-0 rounded-lg border px-3 py-2 text-sm font-semibold",
                d === date ? "border-primary bg-primary text-white" : "border-[#e2e8f0] bg-white text-ink hover:bg-[#f8fafc]",
              )}
            >
              {dayLabel(d, today)}
            </button>
          ))}
          {!days.isLoading && dates.length === 0 && <p className="text-sm text-ink-muted">No free day in the next few weeks for this choice.</p>}
        </div>
        <div className="mt-2 flex items-center gap-2">
          <button type="button" aria-label="Previous day" className="h-9 w-9 rounded-lg border border-[#e2e8f0] text-ink hover:bg-slate-50 disabled:opacity-40" disabled={date <= today} onClick={() => setDate(addDays(date, -1))}>
            ‹
          </button>
          <span className="min-w-[7rem] text-center text-sm font-semibold text-ink">{formatDay(date)}</span>
          <button type="button" aria-label="Next day" className="h-9 w-9 rounded-lg border border-[#e2e8f0] text-ink hover:bg-slate-50" onClick={() => setDate(addDays(date, 1))}>
            ›
          </button>
        </div>
      </div>

      <div aria-live="polite">
        <p className="mb-1 font-label text-xs font-bold text-ink-muted">Free times</p>
        {times.isLoading && <Loader2 size={16} className="animate-spin text-ink-muted" aria-label="Loading times" />}
        {times.error && <p className="text-sm text-rose-700">Could not load the times. Try again.</p>}
        {!times.isLoading && !times.error && parts.length === 0 && <p className="text-sm text-ink-muted">Nothing free on {formatDay(date)}.</p>}
        {parts.map(({ part, times: list }) => (
          <div key={part} className="mb-2">
            <p className="mb-1 text-xs font-semibold text-ink-muted">{part}</p>
            <div className="flex flex-wrap gap-2">
              {list.map((t) => (
                <button
                  key={`${t.start_at}-${t.resource_id}`}
                  type="button"
                  aria-pressed={sameInstant(value?.start_at, t.start_at)}
                  onClick={() => onChange(t, false)}
                  className={cn(
                    "rounded-lg border px-3 py-2 text-sm font-semibold",
                    sameInstant(value?.start_at, t.start_at) ? "border-primary bg-primary text-white" : "border-[#e2e8f0] bg-white text-ink hover:bg-[#f8fafc]",
                  )}
                >
                  {timeText(t.start_at)}
                  {resourceId === "any" && <span className="ml-1 text-xs font-normal opacity-80">· {t.resource_name}</span>}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <p className="rounded-lg bg-[#f8fafc] px-3 py-2 text-sm text-ink" role="status">
        {value ? (
          <>
            <span className="text-ink-muted">Selected: </span>
            <span className="font-semibold">
              {formatDateTime(value.start_at)}
              {value.resource_name ? ` with ${value.resource_name}` : ""}
            </span>
          </>
        ) : (
          <span className="text-ink-muted">No time picked yet.</span>
        )}
      </p>
    </div>
  );
}
