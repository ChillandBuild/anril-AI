"use client";
import { createPortal } from "react-dom";
import useSWR from "swr";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { bookingsApi } from "@/lib/bookingsApi";
import { dayBlocks, summariseDay } from "./bookingsLogic";
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

      {view && (() => {
        const week = view.days.map((d) => summariseDay(d.bookings));
        const sum = (k: "total" | "came" | "toCome" | "noShow") => week.reduce((n, s) => n + s[k], 0);
        return (
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-ink-secondary">
            <span><b className="tabular-nums text-ink">{sum("total")}</b> booked this week</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-[#12b76a]" aria-hidden /><b className="tabular-nums text-ink">{sum("came")}</b> came</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-[#6172f3]" aria-hidden /><b className="tabular-nums text-ink">{sum("toCome")}</b> to come</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-[#98a2b3]" aria-hidden /><b className="tabular-nums text-ink">{sum("noShow")}</b> didn&apos;t come</span>
          </div>
        );
      })()}

      {view && (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
          {view.days.map((d) => {
            const s = summariseDay(d.bookings);
            const isToday = d.date === today;
            const closed = view.resources.length > 0 && view.resources.every((r) => dayBlocks(r.hours, d.date).length === 0);
            const parts = [
              { n: s.came, c: "#12b76a" },
              { n: s.toCome, c: "#6172f3" },
              { n: s.noShow, c: "#98a2b3" },
            ].filter((p) => p.n > 0);
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
                  {closed && s.total === 0 ? (
                    <span className="mt-2 rounded-lg bg-slate-100 px-2 py-1 text-xs font-semibold text-ink-muted">Closed: nobody works this day</span>
                  ) : (
                    <>
                      <span className="font-display text-2xl font-extrabold tabular-nums text-ink">{s.total}</span>
                      <span className="text-xs text-ink-muted">{s.total === 1 ? "booking" : "bookings"}</span>
                    </>
                  )}
                  {parts.length > 0 && (
                    <span className="flex h-1.5 gap-0.5 overflow-hidden rounded-full" aria-hidden>
                      {parts.map((p) => <span key={p.c} style={{ flex: p.n, background: p.c }} />)}
                    </span>
                  )}
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
