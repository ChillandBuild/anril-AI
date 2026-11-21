"use client";
import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { Flame, Pencil, Phone } from "lucide-react";
import { api, type HomeLayout, type HomeToday } from "@/lib/api";
import { HomeBoxes } from "./HomeBoxes";
import { WaitingList } from "./WaitingList";
import { LowStockList } from "./LowStockList";
import { EditTodayModal } from "./EditTodayModal";
import { listIsOn, resolveBoxes, waitingMinutes } from "./todayLayout";

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
 * "Today": the red Hot bar, the number boxes, and the two lists. Sits above the
 * older Home sections. If it can't load it shows a small retry and nothing else breaks.
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
    <section className="space-y-3" aria-label="Today">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-display text-[18px] font-bold text-ink">Today</h2>
        {today && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 font-label text-xs font-bold text-primary-700 hover:bg-primary/10 hover:text-primary-900"
          >
            <Pencil size={13} aria-hidden />
            Edit Today
          </button>
        )}
      </div>

      {!today && isLoading && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6" aria-hidden>
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-[92px] animate-pulse rounded-2xl border border-[#e8edf2] bg-white" />
          ))}
        </div>
      )}

      {!today && todayError && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-[#e8edf2] bg-white px-4 py-3" role="status">
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

      {today && <TodayBody today={today} layout={layout} />}

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

function TodayBody({ today, layout }: { today: HomeToday; layout: HomeLayout | undefined }) {
  const keys = resolveBoxes(layout, today);
  const showWaiting = today.waiting !== null && listIsOn(layout, "waiting");
  const showStock = today.low_stock !== null && listIsOn(layout, "low_stock");
  const bar = today.hot_bar;

  return (
    <>
      {bar && (
        <div
          className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3"
        >
          <p className="flex min-w-0 items-center gap-2 font-body text-sm text-rose-900">
            <Flame size={16} className="shrink-0 text-rose-600" aria-hidden />
            <span className="min-w-0">
              <span className="font-bold">
                {bar.name || "A lead"} (Hot) waiting {waitingMinutes(bar.waiting_since)} min
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

      <HomeBoxes keys={keys} boxes={today.boxes} />

      {(showWaiting || showStock) && (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {showWaiting && today.waiting && <WaitingList total={today.waiting.total} items={today.waiting.items} />}
          {showStock && today.low_stock && <LowStockList total={today.low_stock.total} items={today.low_stock.items} />}
        </div>
      )}
    </>
  );
}
