"use client";
import { createPortal } from "react-dom";
import useSWR from "swr";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { bookingsApi } from "@/lib/bookingsApi";
import { summariseDay } from "./bookingsLogic";
import { addDays, formatDay, mondayOf, todayIst } from "./bookingsTime";
import { BTN_SECONDARY, DownloadListButton, Notice } from "./bookingsUi";

/** Seven days, each with how many live bookings every column has. Tap a day to open it on the Day tab. */
export function WeekTab({
  weekStart,
  onWeek,
  onPickDay,
  canDownload,
  toolbarSlot,
}: {
  weekStart: string;
  onWeek: (monday: string) => void;
  onPickDay: (date: string) => void;
  canDownload: boolean;
  toolbarSlot: HTMLElement | null;
}) {
  const monday = mondayOf(weekStart);
  const { data, error } = useSWR(["bookings/week", monday], () => bookingsApi.week(monday), { revalidateOnFocus: true, keepPreviousData: true });
  // keepPreviousData would show last week under this week's title. Only draw data for this Monday.
  const view = data && data.start === monday ? data : undefined;
  const today = todayIst();
  const thisMonday = mondayOf(today);

  return (
    <div className="space-y-4">
      {toolbarSlot &&
        createPortal(
          <>
            <button type="button" aria-label="Previous week" className={cn(BTN_SECONDARY, "px-2.5")} onClick={() => onWeek(addDays(monday, -7))}>
              <ChevronLeft size={16} />
            </button>
            <button type="button" className={BTN_SECONDARY} onClick={() => onWeek(thisMonday)} disabled={monday === thisMonday}>
              This week
            </button>
            <button type="button" aria-label="Next week" className={cn(BTN_SECONDARY, "px-2.5")} onClick={() => onWeek(addDays(monday, 7))}>
              <ChevronRight size={16} />
            </button>
            {canDownload && (
              <DownloadListButton start={monday} end={addDays(monday, 6)} disabled={!view || view.days.every((d) => d.bookings.length === 0)} />
            )}
          </>,
          toolbarSlot,
        )}
      <h2 className="font-display text-lg font-bold text-ink">
        {formatDay(monday)} – {formatDay(addDays(monday, 6))}
      </h2>

      {error && !view && <Notice tone="red">Could not load this week. Try again in a moment.</Notice>}
      {!view && !error && <div className="h-40 animate-pulse rounded-2xl bg-border-subtle" aria-hidden />}

      {view && (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
          {view.days.map((d) => {
            const s = summariseDay(d.bookings);
            const isToday = d.date === today;
            return (
              <li key={d.date} className="min-w-0">
                <button
                  type="button"
                  onClick={() => onPickDay(d.date)}
                  className={cn(
                    "flex h-full w-full flex-col gap-1 rounded-2xl border bg-white p-3 text-left shadow-sm hover:border-slate-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary",
                    isToday ? "border-primary/50" : "border-[#e8edf2]",
                  )}
                >
                  <span className="font-label text-sm font-bold text-ink">{formatDay(d.date)}</span>
                  <span className="font-display text-2xl font-extrabold tabular-nums text-ink">{s.total}</span>
                  <span className="text-xs text-ink-muted">{s.total === 1 ? "booking" : "bookings"}</span>
                  <ul className="mt-1 space-y-0.5">
                    {view.resources
                      .filter((r) => s.byResource[r.id])
                      .map((r) => (
                        <li key={r.id} className="flex items-center justify-between gap-2 text-xs text-ink-secondary">
                          <span className="truncate">{r.name}</span>
                          <span className="font-bold tabular-nums">{s.byResource[r.id]}</span>
                        </li>
                      ))}
                  </ul>
                  {(s.came > 0 || s.noShow > 0 || s.toCome > 0) && (
                    <span className="mt-auto pt-1 text-xs text-ink-muted">
                      {s.came} came · {s.toCome} to come · {s.noShow} didn&apos;t come
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
