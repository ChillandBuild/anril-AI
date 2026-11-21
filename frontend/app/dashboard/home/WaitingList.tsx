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

/** The 3 chats that have waited longest for a person to reply. */
export function WaitingList({ total, items }: { total: number; items: HomeWaitingItem[] }) {
  return (
    <section className="min-w-0 rounded-2xl border border-[#e8edf2] bg-white px-4 py-3.5 shadow-sm" aria-label="Waiting for your reply">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-display text-base font-bold text-ink">
          Waiting for your reply <span className="text-ink-muted">· {total}</span>
        </h3>
        <Link href="/dashboard/conversations" className="shrink-0 font-label text-xs font-bold text-primary-700 hover:text-primary-900">
          See all ›
        </Link>
      </div>
      {items.length === 0 ? (
        <p className="mt-3 font-body text-sm text-ink-muted">Nobody is waiting. You are all caught up.</p>
      ) : (
        <ul className="mt-2 divide-y divide-[#eef2f6]">
          {items.map((it) => {
            const badge = it.segment ? SEGMENT_BADGE[it.segment] : undefined;
            return (
              <li key={it.lead_id} className="flex items-center justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-body text-sm font-bold text-ink">{it.name || "Unknown"}</span>
                    {badge && (
                      <span className={cn("shrink-0 rounded-full px-2 py-0.5 font-label text-xs font-bold", badge.cls)}>{badge.label}</span>
                    )}
                  </div>
                  <p className="truncate font-body text-xs text-ink-muted">
                    {it.last_message ? `“${it.last_message}” · ` : ""}waiting {waitingFor(it.waiting_since)}
                  </p>
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
