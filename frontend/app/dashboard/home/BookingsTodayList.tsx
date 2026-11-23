"use client";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { STATUS_CLASS, STATUS_LABEL } from "../bookings/bookingsLogic";
import { formatTime } from "../bookings/bookingsTime";
import type { BookingStatus } from "@/lib/bookingsApi";
import type { TodaysBookings } from "./todayLayout";

/** The next bookings of today: time, name, service, column, status. Each row opens that booking. */
export function BookingsTodayList({ data, date }: { data: TodaysBookings; date: string }) {
  return (
    <section className="min-w-0 rounded-2xl border border-[#e8edf2] bg-white px-4 py-3.5 shadow-sm" aria-label="Today's bookings">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-display text-base font-bold text-ink">
          Today&apos;s bookings <span className="text-ink-muted">· {data.total}</span>
        </h3>
        <Link href="/dashboard/bookings" className="shrink-0 font-label text-xs font-bold text-primary-700 hover:text-primary-900">
          See all ›
        </Link>
      </div>
      {data.items.length === 0 ? (
        <p className="mt-3 font-body text-sm text-ink-muted">No bookings left today.</p>
      ) : (
        <ul className="mt-2 divide-y divide-[#eef2f6]">
          {data.items.map((b) => {
            const status = (b.status in STATUS_LABEL ? b.status : "booked") as BookingStatus;
            return (
              <li key={b.id}>
                <Link
                  href={`/dashboard/bookings?date=${encodeURIComponent(date)}&booking=${encodeURIComponent(b.id)}`}
                  className="flex items-center justify-between gap-3 py-2.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                >
                  <div className="min-w-0">
                    <p className="truncate font-body text-sm font-bold text-ink">
                      {formatTime(b.start_at)} · {b.customer_name || "Customer"}
                    </p>
                    <p className="truncate font-body text-xs text-ink-muted">
                      {b.service_name}
                      {b.resource_name ? ` · ${b.resource_name}` : ""}
                    </p>
                  </div>
                  <span className={cn("shrink-0 rounded-full border px-2 py-0.5 font-label text-xs font-bold", STATUS_CLASS[status])}>{STATUS_LABEL[status]}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
