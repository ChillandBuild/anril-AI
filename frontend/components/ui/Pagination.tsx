"use client";
import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { PAGE_SIZE, clampPage, pageButtons, showingRange, slicePage, totalPages } from "@/lib/pagination";

/* ------------------------------------------------------------------ *
 * The one pagination bar every dashboard list uses — the Customers
 * look: "Showing 1–25 of 366 people" on the left, and
 * "‹ Prev · 1 · 2 · 3 · 4 · … · 15 · Next ›" on the right.
 *
 *   <Pagination>      the bar (server- or browser-paged lists)
 *   usePagedList()    page state + the visible rows for a list that is
 *                     loaded whole in the browser
 * ------------------------------------------------------------------ */

export function Pagination({
  page,
  total,
  onPageChange,
  noun = "items",
  pageSize = PAGE_SIZE,
  className,
}: {
  page: number;
  total: number;
  onPageChange: (page: number) => void;
  /** What the rows are, plural: "people", "templates", "orders". */
  noun?: string;
  pageSize?: number;
  className?: string;
}) {
  if (total <= 0) return null;
  const pages = totalPages(total, pageSize);
  const current = clampPage(page, total, pageSize);
  const { from, to } = showingRange(current, total, pageSize);
  const go = (p: number) => onPageChange(clampPage(p, total, pageSize));

  return (
    <nav
      aria-label="Pages"
      className={cn(
        "flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-[#f1f5f9] px-3 py-3 sm:px-4",
        className,
      )}
    >
      <div className="text-xs text-[#64748b]">
        Showing {from}–{to} of {total} {noun}
      </div>
      <div className="flex flex-wrap items-center gap-1 sm:gap-2">
        <button
          type="button"
          onClick={() => go(current - 1)}
          disabled={current === 1}
          className="whitespace-nowrap px-1.5 py-1.5 text-xs font-bold text-[#0A1528] hover:opacity-70 disabled:opacity-40 sm:px-2"
        >
          ‹ Prev
        </button>
        {/* Laptop: the Customers spread. Phone: one page either side, so the bar fits. */}
        <PageNumbers className="hidden sm:flex" items={pageButtons(current, pages)} current={current} onPick={go} />
        <PageNumbers className="flex sm:hidden" items={pageButtons(current, pages, 1)} current={current} onPick={go} />
        <button
          type="button"
          onClick={() => go(current + 1)}
          disabled={current === pages}
          className="whitespace-nowrap px-1.5 py-1.5 text-xs font-bold text-[#0A1528] hover:opacity-70 disabled:opacity-40 sm:px-2"
        >
          Next ›
        </button>
      </div>
    </nav>
  );
}

function PageNumbers({
  items,
  current,
  onPick,
  className,
}: {
  items: (number | "...")[];
  current: number;
  onPick: (page: number) => void;
  className: string;
}) {
  return (
    <div className={cn("gap-1", className)}>
      {items.map((p, idx) =>
        p === "..." ? (
          <span key={`dots-${idx}`} className="px-0.5 text-[#64748b] sm:px-1">
            ...
          </span>
        ) : (
          <button
            type="button"
            key={p}
            onClick={() => onPick(p)}
            aria-current={p === current ? "page" : undefined}
            className={cn(
              "h-8 min-w-7 rounded-lg border px-1 text-xs font-bold transition-colors sm:min-w-8",
              p === current
                ? "border-primary bg-primary text-white"
                : "border-[#e2e8f0] text-[#0A1528] hover:border-primary hover:text-primary",
            )}
          >
            {p}
          </button>
        ),
      )}
    </div>
  );
}

/**
 * Page a list that is already loaded whole in the browser.
 * Pass the filtered + sorted rows; `resetKey` should change whenever a
 * filter, search or sort changes so the list goes back to page 1.
 */
export function usePagedList<T>(items: readonly T[], resetKey?: unknown, pageSize = PAGE_SIZE) {
  const [page, setPage] = useState(1);

  useEffect(() => {
    setPage(1);
  }, [resetKey]);

  // A delete or a refetch can leave us past the last page — step back.
  const current = clampPage(page, items.length, pageSize);
  const pageItems = useMemo(() => slicePage(items, current, pageSize), [items, current, pageSize]);

  return { page: current, setPage, pageItems, total: items.length, pageSize };
}
