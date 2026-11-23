"use client";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import useSWR from "swr";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { bookingsApi, type Booking, type BookingResource, type BookingSetup } from "@/lib/bookingsApi";
import { FLAG_CLASS, HELD_HATCH_STYLE, STATUS_CLASS, STATUS_LABEL, bookingFlags, customerLabel, isOpen, sortByStart, summariseDay } from "./bookingsLogic";
import { addDays, dayLabel, formatDay, formatTime, istOf, todayIst } from "./bookingsTime";
import { BookingSheet } from "./BookingSheet";
import { DayTimeline, type MoveRequest } from "./DayTimeline";
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
            <button type="button" aria-label="Previous day" className={cn(BTN_SECONDARY, "px-2.5")} onClick={() => onDate(addDays(date, -1))}>
              <ChevronLeft size={16} />
            </button>
            <button type="button" className={BTN_SECONDARY} onClick={() => onDate(today)} disabled={date === today}>
              Today
            </button>
            <button type="button" aria-label="Next day" className={cn(BTN_SECONDARY, "px-2.5")} onClick={() => onDate(addDays(date, 1))}>
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

      {view && (counts.came > 0 || counts.toCome > 0 || counts.noShow > 0) && (
        <p className="text-sm text-ink-secondary">
          <span className="font-bold tabular-nums text-ink">{counts.came}</span> came ·{" "}
          <span className="font-bold tabular-nums text-ink">{counts.toCome}</span> to come ·{" "}
          <span className="font-bold tabular-nums text-ink">{counts.noShow}</span> didn&apos;t come
        </p>
      )}

      {canManage && !hasServices && <Notice tone="amber">Add a service in the Services &amp; timings tab before taking bookings.</Notice>}
      {error && !view && <Notice tone="red">Could not load this day. Try again in a moment.</Notice>}

      {view && resources.length === 0 && <Notice>No staff or chairs are set up yet. Add one in the By staff / chair tab.</Notice>}

      {view && resources.length > 0 && (
        <>
          <div className="hidden md:block">
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
          <div className="md:hidden">
            <PhoneList
              bookings={bookings}
              resources={resources}
              canManage={canManage}
              onOpen={(b) => {
                setSheetMode("view");
                onOpenId(b.id);
              }}
              onMove={(b) => {
                setSheetMode("move");
                onOpenId(b.id);
              }}
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

function PhoneList({
  bookings,
  resources,
  canManage,
  onOpen,
  onMove,
}: {
  bookings: Booking[];
  resources: BookingResource[];
  canManage: boolean;
  onOpen: (b: Booking) => void;
  onMove: (b: Booking) => void;
}) {
  if (bookings.length === 0) return <Notice>No bookings this day.</Notice>;
  return (
    <ul className="space-y-2">
      {bookings.map((b) => {
        const flags = bookingFlags(b);
        const col = resources.find((r) => r.id === b.resource_id)?.name;
        return (
          <li
            key={b.id}
            className={cn("rounded-xl border bg-white p-3 shadow-sm", b.status === "cancelled" && "opacity-60", b.status === "held" && "opacity-80")}
            style={b.status === "held" ? HELD_HATCH_STYLE : undefined}
          >
            <button type="button" onClick={() => onOpen(b)} className="block w-full text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-bold text-ink">
                    {formatTime(b.start_at)} · {customerLabel(b)}
                  </p>
                  <p className="truncate text-sm text-ink-secondary">
                    {b.service_name}
                    {col ? ` · ${col}` : ""}
                  </p>
                </div>
                <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-xs font-bold", STATUS_CLASS[b.status])}>{STATUS_LABEL[b.status]}</span>
              </div>
              {flags.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {flags.map((f) => (
                    <span key={f.key} className={cn("rounded-full px-2 py-0.5 text-xs font-bold", FLAG_CLASS[f.tone])}>
                      {f.label}
                    </span>
                  ))}
                </div>
              )}
            </button>
            {canManage && isOpen(b.status) && (
              <div className="mt-2">
                <button type="button" className={cn(BTN_SECONDARY, "min-h-9 py-1.5")} onClick={() => onMove(b)}>
                  Move
                </button>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
