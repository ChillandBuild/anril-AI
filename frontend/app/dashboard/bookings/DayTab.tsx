"use client";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import useSWR from "swr";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { bookingsApi, type BookingResource, type BookingSetup } from "@/lib/bookingsApi";
import { customerLabel, sortByStart, summariseDay } from "./bookingsLogic";
import { addDays, dayLabel, formatDay, formatTime, istOf, todayIst } from "./bookingsTime";
import { BookingSheet } from "./BookingSheet";
import { DayTimeline, type MoveRequest } from "./DayTimeline";
import { DayList, DayTiles, EmptyDay } from "./DayList";
import { NewBookingDialog, type NewBookingPrefill } from "./NewBookingDialog";
import { BTN_PRIMARY, BTN_SECONDARY, ConfirmSheet, DownloadListButton, Notice, errorText } from "./bookingsUi";

export function DayTab({
  setup,
  date,
  onDate,
  openId,
  onOpenId,
  canManage,
  canSeeMoney,
  canDownload,
  toolbarSlot,
}: {
  setup: BookingSetup;
  date: string;
  onDate: (d: string) => void;
  openId: string | null;
  onOpenId: (id: string | null) => void;
  canManage: boolean;
  canSeeMoney: boolean;
  canDownload: boolean;
  toolbarSlot: HTMLElement | null;
}) {
  const { data, error, mutate } = useSWR(["bookings/day", date], () => bookingsApi.day(date), {
    refreshInterval: 60_000,
    revalidateOnFocus: true,
    keepPreviousData: true,
  });
  const [creating, setCreating] = useState<NewBookingPrefill | null>(null);
  const [moving, setMoving] = useState<MoveRequest | null>(null);
  const [moveBusy, setMoveBusy] = useState(false);
  const [sheetMode, setSheetMode] = useState<"view" | "move">("view");
  const [layout, setLayout] = useState<"list" | "timeline">("list");
  const today = todayIst();

  // keepPreviousData shows yesterday's bookings while today's load. Only draw data that is for this date.
  const view = data && data.date === date ? data : undefined;
  const resources: BookingResource[] = view?.resources ?? [];
  const bookings = useMemo(() => sortByStart(view?.bookings ?? []), [view]);
  // A late booking from the night before can spill into this day's board; count only bookings that start today.
  const counts = useMemo(() => summariseDay(bookings.filter((b) => istOf(b.start_at)?.date === date)), [bookings, date]);
  const opened = openId ? bookings.find((b) => b.id === openId) ?? null : null;
  const hasServices = setup.services.some((s) => s.active);

  // A different day: forget a half-finished drag.
  useEffect(() => setMoving(null), [date]);

  async function confirmMove() {
    if (!moving) return;
    setMoveBusy(true);
    try {
      await bookingsApi.move(moving.booking.id, { start_at: moving.startAt, resource_id: moving.resource.id });
      toast.success("Booking moved");
      setMoving(null);
      await mutate();
    } catch (err) {
      toast.error(errorText(err, "That time was just taken, pick another"));
      setMoving(null);
      await mutate();
    } finally {
      setMoveBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {toolbarSlot &&
        createPortal(
          <>
            <button type="button" aria-label="Previous day" className={cn(BTN_SECONDARY, "px-2.5 max-md:h-8 max-md:min-h-8")} onClick={() => onDate(addDays(date, -1))}>
              <ChevronLeft size={16} />
            </button>
            <button type="button" className={cn(BTN_SECONDARY, "max-md:h-8 max-md:min-h-8 max-md:px-3 max-md:py-0")} onClick={() => onDate(today)} disabled={date === today}>
              Today
            </button>
            <button type="button" aria-label="Next day" className={cn(BTN_SECONDARY, "px-2.5 max-md:h-8 max-md:min-h-8")} onClick={() => onDate(addDays(date, 1))}>
              <ChevronRight size={16} />
            </button>
            {canDownload && <DownloadListButton start={date} disabled={!view || bookings.length === 0} />}
            {canManage && (
              <button type="button" className={BTN_PRIMARY} onClick={() => setCreating({})} disabled={!hasServices} title={hasServices ? undefined : "Add a service first"}>
                <Plus size={16} aria-hidden /> New booking
              </button>
            )}
          </>,
          toolbarSlot,
        )}

      <h2 className="font-display text-lg font-bold text-ink">
        {dayLabel(date, today)}
        {dayLabel(date, today) !== formatDay(date) && <span className="ml-2 text-sm font-semibold text-ink-muted">{formatDay(date)}</span>}
      </h2>

      {view && counts.total + counts.noShow > 0 && <DayTiles bookings={bookings.filter((b) => istOf(b.start_at)?.date === date)} />}

      {canManage && !hasServices && <Notice tone="amber">Add a service in the Services &amp; timings tab before taking bookings.</Notice>}
      {error && !view && <Notice tone="red">Could not load this day. Try again in a moment.</Notice>}

      {view && resources.length === 0 && <Notice>No staff or chairs are set up yet. Add one in the By staff / chair tab.</Notice>}

      {view && resources.length > 0 && bookings.length === 0 && (
        <EmptyDay onNextDay={() => onDate(addDays(date, 1))} canManage={canManage && hasServices} onNew={() => setCreating({})} />
      )}

      {view && resources.length > 0 && bookings.length > 0 && (
        <>
          <div className="flex justify-end">
            <div role="tablist" aria-label="Day view" className="hidden rounded-xl border border-border bg-white p-0.5 md:inline-flex">
              {(["list", "timeline"] as const).map((v) => (
                <button key={v} type="button" role="tab" aria-selected={layout === v} onClick={() => setLayout(v)}
                  className={cn("rounded-lg px-3 py-1 text-xs font-bold", layout === v ? "bg-ink text-white" : "text-ink-secondary hover:text-ink")}>
                  {v === "list" ? "List" : "By staff"}
                </button>
              ))}
            </div>
          </div>
          <div className={layout === "list" ? "" : "md:hidden"}>
            <DayList
              bookings={bookings}
              resources={resources}
              who={{ canManage, myResourceId: setup.my_resource_id }}
              isToday={date === today}
              canSeeMoney={canSeeMoney}
              onOpen={(b) => {
                setSheetMode("view");
                onOpenId(b.id);
              }}
              onChanged={() => void mutate()}
            />
          </div>
          <div className={layout === "timeline" ? "hidden md:block" : "hidden"}>
            <DayTimeline
              date={date}
              resources={resources}
              bookings={bookings}
              free={view.free}
              canManage={canManage}
              onOpen={(b) => {
                setSheetMode("view");
                onOpenId(b.id);
              }}
              onNewAt={(r, startAt) => setCreating({ resourceId: r.id, startAt })}
              onMove={setMoving}
            />
          </div>
        </>
      )}
      {!view && !error && <div className="h-48 animate-pulse rounded-2xl bg-border-subtle" aria-hidden />}

      {opened && (
        <BookingSheet
          key={`${opened.id}-${sheetMode}`}
          booking={opened}
          resources={resources}
          canManage={canManage}
          myResourceId={setup.my_resource_id}
          canSeeMoney={canSeeMoney}
          initialMode={sheetMode}
          onClose={() => onOpenId(null)}
          onChanged={() => void mutate()}
        />
      )}

      {creating && (
        <NewBookingDialog
          setup={setup}
          prefill={{ ...creating, source: creating.source ?? "phone" }}
          canSeeMoney={canSeeMoney}
          onClose={() => setCreating(null)}
          onCreated={() => {
            setCreating(null);
            void mutate();
          }}
        />
      )}

      {moving && (
        <ConfirmSheet
          title="Move this booking?"
          body={`${customerLabel(moving.booking).split(/\s+/)[0]} gets a WhatsApp about the new time: ${formatDay(date)}, ${formatTime(moving.startAt)} with ${moving.resource.name}.`}
          confirmLabel="Move it"
          busy={moveBusy}
          onClose={() => setMoving(null)}
          onConfirm={() => void confirmMove()}
        />
      )}
    </div>
  );
}

