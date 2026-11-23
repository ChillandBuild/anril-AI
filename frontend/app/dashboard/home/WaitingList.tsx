"use client";
import Link from "next/link";
import { cn } from "@/lib/utils";
import type { HomeWaitingItem } from "@/lib/api";
import { waitingFor } from "./todayLayout";

const SEGMENT_BADGE: Record<string, { label: string; cls: string }> = {
  A: { label: "Hot", cls: "bg-rose-50 text-rose-700" },
  B: { label: "Warm", cls: "bg-amber-50 text-amber-800" },
  C: { label: "Cold", cls: "bg-slate-100 text-slate-700" },
};

/** Rows shown on Home; the full list is one tap away under "See all". */
export const WAITING_ROWS = 6;

/** The chats that have waited longest for a person to reply. */
export function WaitingList({ total, items }: { total: number; items: HomeWaitingItem[] }) {
  return (
    <section className="min-w-0 rounded-2xl border border-border bg-white px-5 py-4 shadow-sm" aria-label="Waiting for your reply">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-display text-base font-extrabold text-ink">
          Waiting for your reply <span className="text-ink-muted">· {total}</span>
        </h3>
        <Link href="/dashboard/conversations" className="shrink-0 font-label text-xs font-bold text-primary-700 hover:text-primary-900">
          See all ›
        </Link>
      </div>
      {items.length === 0 ? (
        <p className="mt-3 font-body text-sm text-ink-muted">Nobody is waiting. You are all caught up.</p>
      ) : (
        <ul className="mt-2 divide-y divide-border-subtle">
          {items.slice(0, WAITING_ROWS).map((it) => {
            const badge = it.segment ? SEGMENT_BADGE[it.segment] : undefined;
            return (
              <li key={it.lead_id} className="flex items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-body text-sm font-bold text-ink">{it.name || "Unknown"}</span>
                    {badge && (
                      <span className={cn("shrink-0 rounded-full px-2 py-0.5 font-label text-[11px] font-bold", badge.cls)}>{badge.label}</span>
                    )}
                    <span className="shrink-0 font-label text-xs font-medium text-ink-muted">· {waitingFor(it.waiting_since)}</span>
                  </div>
                  {it.last_message ? <p className="truncate font-body text-[13px] text-ink-secondary">“{it.last_message}”</p> : null}
                </div>
                <Link
                  href={`/dashboard/conversations?lead=${encodeURIComponent(it.lead_id)}`}
                  className="shrink-0 rounded-xl border border-border-subtle bg-white px-3.5 py-2 font-label text-xs font-bold text-ink shadow-sm hover:border-slate-300"
                >
                  Reply
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
