"use client";
import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { Flame, Pencil, Phone } from "lucide-react";
import { api, type HomeBox, type HomeLayout, type HomeToday } from "@/lib/api";
import { HomeBoxes } from "./HomeBoxes";
import { WaitingList } from "./WaitingList";
import { LowStockList } from "./LowStockList";
import { BookingsTodayList } from "./BookingsTodayList";
import { FeedbackTodayList } from "./FeedbackTodayList";
import { todayIst } from "../bookings/bookingsTime";
import { EditTodayModal } from "./EditTodayModal";
import { PhoneToday } from "./PhoneToday";
import { listIsOn, resolveBoxes, waitingFor, type BoxKey, type TodaysBookings } from "./todayLayout";

const swrOpts = {
  revalidateOnFocus: true,
  revalidateOnReconnect: true,
  dedupingInterval: 5_000,
  errorRetryCount: 2,
  shouldRetryOnError: (error: unknown) => {
    const status = (error as { status?: number } | undefined)?.status;
    return !status || ![401, 403, 404].includes(status);
  },
};

/**
 * Home's top half. Left two-thirds: the red Hot bar, "Waiting for your reply" and the other lists, one under
 * the other. Right third: the Today boxes as rows. If it can't load it shows a small retry and nothing else breaks.
 */
export function TodayBlock() {
  const { data: today, error: todayError, isLoading, mutate: reloadToday } = useSWR<HomeToday>(
    "home/today",
    () => api.home.today(),
    { ...swrOpts, refreshInterval: 120_000 },
  );
  // A missing or failing layout is not an error for the person: they just get the suggested set.
  const { data: layout, mutate: setLayout } = useSWR<HomeLayout>("home/layout", () => api.home.layout(), swrOpts);
  const [editing, setEditing] = useState(false);

  return (
    <section aria-label="Today">
      {!today && isLoading && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]" aria-hidden>
          <div className="h-[320px] animate-pulse rounded-2xl border border-border bg-white" />
          <div className="h-[320px] animate-pulse rounded-2xl border border-border bg-white" />
        </div>
      )}

      {!today && todayError && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-white px-4 py-3" role="status">
          <p className="font-body text-sm text-ink-muted">Today&apos;s numbers could not be loaded.</p>
          <button
            type="button"
            onClick={() => reloadToday()}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-label text-xs font-bold text-ink hover:border-slate-300"
          >
            Retry
          </button>
        </div>
      )}

      {today && (
        <>
          <div className="lg:hidden">
            <PhoneToday today={today} layout={layout} onEdit={() => setEditing(true)} />
          </div>
          <div className="hidden lg:block">
            <TodayBody today={today} layout={layout} onEdit={() => setEditing(true)} />
          </div>
        </>
      )}

      {editing && today && (
        <EditTodayModal
          today={today}
          layout={layout}
          onClose={() => setEditing(false)}
          onSaved={(saved) => {
            void setLayout(saved, { revalidate: false });
          }}
        />
      )}
    </section>
  );
}

function TodayBody({ today, layout, onEdit }: { today: HomeToday; layout: HomeLayout | undefined; onEdit: () => void }) {
  const keys = resolveBoxes(layout, today);
  const showWaiting = today.waiting !== null && listIsOn(layout, "waiting");
  const showStock = today.low_stock !== null && listIsOn(layout, "low_stock");
  const showFeedback = !!today.todays_feedback && listIsOn(layout, "todays_feedback");
  const bar = today.hot_bar;
  // The server sends the Today's bookings list only to people who may see Bookings.
  const bookings = (today as HomeToday & { todays_bookings?: TodaysBookings | null }).todays_bookings ?? null;
  const showBookings = !!bookings && listIsOn(layout, "todays_bookings");
  const hasLeft = !!bar || showWaiting || showStock || showBookings || showFeedback;
  const boxes = today.boxes as Partial<Record<BoxKey, HomeBox>>;
  const hasBoxes = keys.some((k) => boxes[k]);

  return (
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
      {hasLeft && (
        <div className="min-w-0 space-y-4">
          {bar && (
            <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-2.5">
              <p className="flex min-w-0 flex-[1_1_360px] items-center gap-2 font-body text-sm text-rose-900">
                <Flame size={16} className="shrink-0 text-rose-600" aria-hidden />
                <span className="min-w-0 truncate">
                  <span className="font-bold">
                    {bar.name || "A lead"} (Hot) waiting {waitingFor(bar.waiting_since) || "a while"}
                  </span>
                  {bar.last_message ? <span className="text-rose-800"> · {bar.last_message}</span> : null}
                </span>
              </p>
              <div className="flex shrink-0 items-center gap-2">
                <Link
                  href={`/dashboard/conversations?lead=${encodeURIComponent(bar.lead_id)}`}
                  className="btn-primary justify-center"
                >
                  Open chat
                </Link>
                {bar.phone && (
                  <a
                    href={`tel:${bar.phone}`}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 font-label text-xs font-bold text-ink shadow-sm hover:border-slate-300"
                  >
                    <Phone size={13} aria-hidden />
                    Call
                  </a>
                )}
              </div>
            </div>
          )}

          {showWaiting && today.waiting && <WaitingList total={today.waiting.total} items={today.waiting.items} />}
          {showStock && today.low_stock && <LowStockList total={today.low_stock.total} items={today.low_stock.items} />}
          {showBookings && bookings && <BookingsTodayList data={bookings} date={todayIst()} />}
          {showFeedback && today.todays_feedback && (
            <FeedbackTodayList total={today.todays_feedback.total} items={today.todays_feedback.items} />
          )}
        </div>
      )}

      {/* Stays in the right-hand column even when the left one is empty. */}
      <aside
        className="min-w-0 rounded-2xl border border-border bg-white px-5 py-4 shadow-sm lg:col-start-2 lg:row-start-1"
        aria-label="Today's numbers"
      >
        <div className="mb-2 flex items-center justify-between gap-3">
          <h3 className="font-display text-base font-extrabold text-ink">Today</h3>
          <button
            type="button"
            onClick={onEdit}
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 font-label text-xs font-bold text-primary-700 hover:bg-primary/10 hover:text-primary-900"
          >
            <Pencil size={13} aria-hidden />
            Edit Today
          </button>
        </div>
        {hasBoxes ? (
          <HomeBoxes keys={keys} boxes={boxes} />
        ) : (
          <p className="border-t border-border-subtle pt-3 font-body text-sm text-ink-muted">No numbers to show yet. Use Edit Today to pick some.</p>
        )}
      </aside>
    </div>
  );
}
