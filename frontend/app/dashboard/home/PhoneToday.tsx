"use client";
import Link from "next/link";
import { Pencil, Phone } from "lucide-react";
import { cn } from "@/lib/utils";
import type { HomeBox, HomeLayout, HomeToday } from "@/lib/api";
import { TargetRow } from "./HomeBoxes";
import { PhoneQuickActions } from "./PhoneQuickActions";
import { LowStockList } from "./LowStockList";
import { BookingsTodayList } from "./BookingsTodayList";
import { FeedbackTodayList } from "./FeedbackTodayList";
import { todayIst } from "../bookings/bookingsTime";
import {
  BOX_META,
  formatBoxValue,
  isLoss,
  listIsOn,
  resolveBoxes,
  waitingFor,
  type BoxKey,
  type TodaysBookings,
} from "./todayLayout";

const SEGMENT: Record<string, { label: string; cls: string }> = {
  A: { label: "Hot", cls: "bg-rose-100 text-rose-800" },
  B: { label: "Warm", cls: "bg-amber-100 text-amber-900" },
  C: { label: "Cold", cls: "bg-slate-200 text-slate-700" },
};

/** Chats shown in the "Needs you" card; the rest are one tap away. */
const NEEDS_YOU_ROWS = 3;

type NeedsRow = {
  lead_id: string;
  name: string | null;
  segment: string | null;
  last_message: string | null;
  waiting_since: string;
  phone: string | null;
};

const chatHref = (leadId: string) => `/dashboard/conversations?lead=${encodeURIComponent(leadId)}`;

/**
 * Home's top half on a phone (< lg): the "Needs you" card, the target ring, the Today boxes as a
 * two-column grid, then the same lists as desktop. Same data and the same Edit Today as TodayBody.
 */
export function PhoneToday({ today, layout, onEdit }: { today: HomeToday; layout: HomeLayout | undefined; onEdit: () => void }) {
  const keys = resolveBoxes(layout, today);
  const boxes = today.boxes as Partial<Record<BoxKey, HomeBox>>;
  const target = keys.includes("target_month") ? boxes.target_month : undefined;
  const tiles = keys.filter((k) => k !== "target_month" && boxes[k]);

  const showWaiting = today.waiting !== null && listIsOn(layout, "waiting");
  const showStock = today.low_stock !== null && listIsOn(layout, "low_stock");
  const showFeedback = !!today.todays_feedback && listIsOn(layout, "todays_feedback");
  const bookings = (today as HomeToday & { todays_bookings?: TodaysBookings | null }).todays_bookings ?? null;
  const showBookings = !!bookings && listIsOn(layout, "todays_bookings");

  // The red Hot bar's chat leads the card; the waiting list fills the rest without repeating it.
  const bar = today.hot_bar;
  const rows: NeedsRow[] = [];
  if (bar) rows.push({ ...bar, segment: "A" });
  for (const it of today.waiting?.items ?? []) {
    if (rows.length >= NEEDS_YOU_ROWS) break;
    if (it.lead_id !== bar?.lead_id) rows.push({ ...it, phone: null });
  }
  const waitingTotal = Math.max(today.waiting?.total ?? 0, rows.length);
  const showNeedsYou = showWaiting || !!bar;

  return (
    <div className="flex flex-col gap-3.5">
      <PhoneQuickActions />
      {showNeedsYou && (
        <section aria-labelledby="needs-you" className="flex flex-col gap-3 rounded-3xl bg-navy p-4 text-white">
          <div className="flex items-center justify-between gap-3">
            <p id="needs-you" className="font-label text-xs font-extrabold uppercase tracking-wider text-navy-accent">
              Needs you · {waitingTotal}
            </p>
            <Link href="/dashboard/conversations" className="flex min-h-10 items-center font-label text-sm font-extrabold text-navy-accent">
              See all
            </Link>
          </div>
          {rows.length === 0 ? (
            <p className="font-body text-[15px] text-slate-200">Nobody is waiting. You are all caught up.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {rows.map((row, i) => {
                const seg = row.segment ? SEGMENT[row.segment] : undefined;
                const waited = waitingFor(row.waiting_since);
                return (
                  <li key={row.lead_id} className="flex flex-col gap-2.5 rounded-2xl bg-navy-800 p-3">
                    <Link href={chatHref(row.lead_id)} className="flex min-w-0 flex-col gap-1">
                      <span className="flex min-w-0 items-center gap-2">
                        <span className="truncate font-display text-[15px] font-extrabold">{row.name || "Unknown"}</span>
                        {seg && <span className={cn("shrink-0 rounded-full px-2 py-0.5 font-label text-[11px] font-extrabold", seg.cls)}>{seg.label}</span>}
                        {waited && (
                          <span className={cn("ml-auto shrink-0 font-label text-xs font-bold", i === 0 ? "text-rose-300" : "text-slate-300")}>
                            {waited}
                          </span>
                        )}
                      </span>
                      {row.last_message && <span className="truncate font-body text-[13px] text-slate-300">&ldquo;{row.last_message}&rdquo;</span>}
                    </Link>
                    {i === 0 && (
                      <div className={cn("grid gap-2", row.phone ? "grid-cols-2" : "grid-cols-1")}>
                        <Link
                          href={chatHref(row.lead_id)}
                          className="flex min-h-11 items-center justify-center rounded-xl bg-primary font-label text-sm font-extrabold text-white"
                        >
                          Reply
                        </Link>
                        {row.phone && (
                          <a
                            href={`tel:${row.phone}`}
                            className="flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-navy-700 font-label text-sm font-extrabold text-white"
                          >
                            <Phone size={15} aria-hidden />
                            Call
                          </a>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}

      {target && (
        <div className="rounded-2xl border border-border bg-white px-4">
          <TargetRow box={target} />
        </div>
      )}

      <div className="flex items-center justify-between px-1 pt-1">
        <p className="font-label text-xs font-extrabold uppercase tracking-wider text-ink-secondary">Today</p>
        <button
          type="button"
          onClick={onEdit}
          className="-mr-2 flex min-h-10 items-center gap-1.5 rounded-lg px-2 font-label text-sm font-bold text-primary-900"
        >
          <Pencil size={14} aria-hidden />
          Edit
        </button>
      </div>
      {tiles.length > 0 ? (
        <ul className="grid grid-cols-2 gap-2.5" aria-label="Today in numbers">
          {tiles.map((key) => {
            const box = boxes[key] as HomeBox;
            return (
              <li key={key} className="min-w-0">
                <Link href={box.href} className="flex h-full min-w-0 flex-col gap-1 rounded-2xl border border-border bg-white p-2.5 text-ink active:bg-surface-mid">
                  <span className="font-label text-[13px] font-bold leading-tight text-ink-secondary">{BOX_META[key].label}</span>
                  <span
                    className={cn(
                      "truncate font-display text-xl font-extrabold leading-tight tabular-nums",
                      isLoss(key, box) ? "text-rose-700" : "text-ink",
                    )}
                  >
                    {formatBoxValue(box)}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="rounded-2xl border border-border bg-white px-4 py-3 font-body text-sm text-ink-muted">
          No numbers to show yet. Use Edit to pick some.
        </p>
      )}

      {showBookings && bookings && <BookingsTodayList data={bookings} date={todayIst()} />}
      {showStock && today.low_stock && <LowStockList total={today.low_stock.total} items={today.low_stock.items} />}
      {showFeedback && today.todays_feedback && (
        <FeedbackTodayList total={today.todays_feedback.total} items={today.todays_feedback.items} />
      )}
    </div>
  );
}
