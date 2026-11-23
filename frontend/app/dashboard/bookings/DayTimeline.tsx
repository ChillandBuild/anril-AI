"use client";
import { useRef, useState } from "react";
import { cn } from "@/lib/utils";
import type { Booking, BookingResource, FreeRanges } from "@/lib/bookingsApi";
import { HELD_HATCH_STYLE, PX_PER_MIN, STATUS_CLASS, bookingFlags, clickMinutes, customerLabel, dropMinutes, freeBands, gridRange, isLive, placeBooking } from "./bookingsLogic";
import { clock, toIso } from "./bookingsTime";

export interface MoveRequest {
  booking: Booking;
  resource: BookingResource;
  startAt: string;
}

/**
 * Desktop day view: one column per staff / chair on a 15-minute grid. Free gaps are clickable (new booking),
 * booked blocks open the sheet, and a block can be dragged to another time or column.
 * Dragging is a mouse shortcut; every block is also a button, and the sheet has a Move button.
 */
export function DayTimeline({
  date,
  resources,
  bookings,
  free,
  canManage,
  onOpen,
  onNewAt,
  onMove,
}: {
  date: string;
  resources: BookingResource[];
  bookings: Booking[];
  free: FreeRanges;
  canManage: boolean;
  onOpen: (b: Booking) => void;
  onNewAt: (resource: BookingResource, startAt: string) => void;
  onMove: (req: MoveRequest) => void;
}) {
  const live = bookings.filter((b) => b.status !== "cancelled");
  const range = gridRange(date, resources, live);
  const heightPx = (range.endMin - range.startMin) * PX_PER_MIN;
  const hours: number[] = [];
  for (let m = range.startMin; m < range.endMin; m += 60) hours.push(m);
  const drag = useRef<{ id: string; grabMin: number } | null>(null);
  const [over, setOver] = useState<string | null>(null);

  return (
    <div className="overflow-x-auto rounded-2xl border border-[#e8edf2] bg-white shadow-sm">
      <div className="flex min-w-max">
        <div className="sticky left-0 z-10 w-14 shrink-0 border-r border-[#eef2f6] bg-white">
          <div className="h-10 border-b border-[#eef2f6]" />
          <div className="relative" style={{ height: heightPx }} aria-hidden>
            {hours.map((m) => (
              <span key={m} className="absolute right-1.5 -translate-y-1/2 text-xs text-ink-muted" style={{ top: (m - range.startMin) * PX_PER_MIN }}>
                {m === range.startMin ? "" : clock(m)}
              </span>
            ))}
          </div>
        </div>

        {resources.map((r) => {
          const mine = live.filter((b) => b.resource_id === r.id);
          const bands = freeBands(free[r.id], date, range.startMin);
          return (
            <div key={r.id} className="w-56 shrink-0 border-r border-[#eef2f6] last:border-r-0">
              <div className="flex h-10 items-center border-b border-[#eef2f6] px-3">
                <span className="truncate font-label text-sm font-bold text-ink">{r.name}</span>
              </div>
              <div
                className={cn("relative bg-[repeating-linear-gradient(0deg,#f8fafc,#f8fafc_6px,#f1f5f9_6px,#f1f5f9_7px)]", over === r.id && "ring-2 ring-inset ring-primary/40")}
                style={{ height: heightPx }}
                onDragOver={(e) => {
                  if (!drag.current || !canManage) return;
                  e.preventDefault();
                  setOver(r.id);
                }}
                onDragLeave={() => setOver((cur) => (cur === r.id ? null : cur))}
                onDrop={(e) => {
                  setOver(null);
                  const d = drag.current;
                  drag.current = null;
                  if (!d || !canManage) return;
                  e.preventDefault();
                  const booking = live.find((b) => b.id === d.id);
                  if (!booking) return;
                  const rect = e.currentTarget.getBoundingClientRect();
                  const p = placeBooking(booking, date, range.startMin);
                  const startMin = dropMinutes({
                    offsetY: e.clientY - rect.top,
                    grabOffsetMin: d.grabMin,
                    gridStartMin: range.startMin,
                    gridEndMin: range.endMin,
                    blockMin: (p?.height ?? 30) + (p?.gap ?? 0),
                  });
                  onMove({ booking, resource: r, startAt: toIso(date, startMin) });
                }}
              >
                {/* Hour lines */}
                {hours.map((m) => (
                  <div key={m} aria-hidden className="absolute inset-x-0 border-t border-[#e2e8f0]" style={{ top: (m - range.startMin) * PX_PER_MIN }} />
                ))}

                {/* Free gaps: click to book */}
                {canManage &&
                  bands.map((band, i) => (
                    <button
                      key={i}
                      type="button"
                      aria-label={`Free ${clock(band.startMin)} to ${clock(band.endMin)} with ${r.name}. Add a booking`}
                      className="absolute inset-x-0 border-y border-dashed border-emerald-200 bg-white/80 text-left text-xs text-emerald-800 opacity-90 hover:bg-emerald-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                      style={{ top: band.top * PX_PER_MIN, height: band.height * PX_PER_MIN }}
                      onClick={(e) => {
                        const rect = e.currentTarget.getBoundingClientRect();
                        const min = clickMinutes(e.clientY - rect.top + band.top * PX_PER_MIN, band, range.startMin);
                        onNewAt(r, toIso(date, min));
                      }}
                    >
                      <span className="px-2 pt-0.5">＋ Free</span>
                    </button>
                  ))}

                {/* Bookings */}
                {mine.map((b) => {
                  const p = placeBooking(b, date, range.startMin);
                  if (!p) return null;
                  const flags = bookingFlags(b);
                  const draggable = canManage && (b.status === "booked" || b.status === "held");
                  return (
                    <div key={b.id} className="absolute inset-x-1" style={{ top: p.top * PX_PER_MIN, height: (p.height + p.gap) * PX_PER_MIN }}>
                      <button
                        type="button"
                        draggable={draggable}
                        onDragStart={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          drag.current = { id: b.id, grabMin: (e.clientY - rect.top) / PX_PER_MIN };
                          e.dataTransfer.effectAllowed = "move";
                          e.dataTransfer.setData("text/plain", b.id);
                        }}
                        onDragEnd={() => {
                          drag.current = null;
                          setOver(null);
                        }}
                        onClick={() => onOpen(b)}
                        className={cn(
                          "block w-full overflow-hidden rounded-lg border px-2 py-1 text-left text-xs leading-snug shadow-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary",
                          STATUS_CLASS[b.status],
                          draggable && "cursor-grab active:cursor-grabbing",
                          b.status === "held" && "opacity-80",
                        )}
                        style={{ height: Math.max(p.height * PX_PER_MIN, 24), ...(b.status === "held" ? HELD_HATCH_STYLE : {}) }}
                      >
                        <span className="block truncate font-bold">{customerLabel(b)}</span>
                        <span className="block truncate">
                          {clock(p.top + range.startMin)} · {b.service_name}
                        </span>
                        {p.height * PX_PER_MIN >= 64 && flags.length > 0 && <span className="block truncate font-semibold">{flags.map((f) => f.label).join(" · ")}</span>}
                      </button>
                      {p.gap > 0 && isLive(b.status) && (
                        <div
                          aria-hidden
                          className="mt-0.5 rounded-b-md bg-[repeating-linear-gradient(45deg,#cbd5e1,#cbd5e1_3px,#f1f5f9_3px,#f1f5f9_6px)] opacity-80"
                          style={{ height: p.gap * PX_PER_MIN - 2 }}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
