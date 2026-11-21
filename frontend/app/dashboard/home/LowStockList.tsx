"use client";
import Link from "next/link";
import type { HomeLowStockItem } from "@/lib/api";

/** The 5 catalogue items closest to running out. */
export function LowStockList({ total, items }: { total: number; items: HomeLowStockItem[] }) {
  return (
    <section className="min-w-0 rounded-2xl border border-[#e8edf2] bg-white px-4 py-3.5 shadow-sm" aria-label="Stock running low">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-display text-base font-bold text-ink">
          Stock running low <span className="text-ink-muted">· {total}</span>
        </h3>
      </div>
      {items.length === 0 ? (
        <p className="mt-3 font-body text-sm text-ink-muted">Nothing is running low.</p>
      ) : (
        <ul className="mt-2 divide-y divide-[#eef2f6]">
          {items.map((it) => (
            <li key={it.item_id} className="flex items-center justify-between gap-3 py-2.5">
              <span className="min-w-0 truncate font-body text-sm font-bold text-ink">{it.name}</span>
              <span className={it.stock <= 0 ? "shrink-0 font-label text-xs font-bold text-rose-700" : "shrink-0 font-label text-xs font-bold text-amber-800"}>
                {it.stock <= 0 ? "out of stock" : `${it.stock} left`}
              </span>
            </li>
          ))}
        </ul>
      )}
      <Link href="/dashboard/catalog" className="mt-1 inline-block font-label text-xs font-bold text-primary-700 hover:text-primary-900">
        See all in Catalogue ›
      </Link>
    </section>
  );
}
