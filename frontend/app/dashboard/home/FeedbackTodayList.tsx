"use client";
import Link from "next/link";
import { cn } from "@/lib/utils";
import type { HomeFeedbackItem } from "@/lib/api";
import { starsText } from "./todayLayout";

/** The latest answers customers gave today (up to 5). Each row opens that customer. 3 stars or fewer is flagged. */
export function FeedbackTodayList({ total, items }: { total: number; items: HomeFeedbackItem[] }) {
  return (
    <section className="min-w-0 rounded-2xl border border-[#e8edf2] bg-white px-4 py-3.5 shadow-sm" aria-label="Today's feedback">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-display text-base font-bold text-ink">
          Today&apos;s feedback <span className="text-ink-muted">· {total}</span>
        </h3>
        <Link href="/dashboard/leads?tab=feedback" className="shrink-0 font-label text-xs font-bold text-primary-700 hover:text-primary-900">
          See all ›
        </Link>
      </div>
      {items.length === 0 ? (
        <p className="mt-3 font-body text-sm text-ink-muted">No feedback yet today.</p>
      ) : (
        <ul className="mt-2 divide-y divide-[#eef2f6]">
          {items.map((f) => (
            <li key={f.id}>
              <Link
                href={`/dashboard/leads/${encodeURIComponent(f.lead_id)}`}
                className="flex items-center justify-between gap-3 py-2.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
              >
                <div className="min-w-0">
                  <p className="truncate font-body text-sm font-bold text-ink">{f.name || "Customer"}</p>
                  {f.reason ? <p className="truncate font-body text-xs text-ink-muted">&ldquo;{f.reason}&rdquo;</p> : null}
                </div>
                <span
                  className={cn("shrink-0 font-label text-sm font-bold tracking-wide", f.stars <= 3 ? "text-rose-700" : "text-amber-800")}
                  role="img"
                  aria-label={`${f.stars} out of 5 stars`}
                >
                  {starsText(f.stars)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
