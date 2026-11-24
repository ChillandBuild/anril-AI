/* ------------------------------------------------------------------ *
 * Shared paging rules for every list in the dashboard. Lists show 25
 * rows a page, the same as Customers. The bar itself lives in
 * components/ui/Pagination.tsx.
 * ------------------------------------------------------------------ */

export const PAGE_SIZE = 25;

export function totalPages(total: number, pageSize = PAGE_SIZE): number {
  return Math.max(1, Math.ceil(total / pageSize));
}

/** Keep a page number inside 1..totalPages. */
export function clampPage(page: number, total: number, pageSize = PAGE_SIZE): number {
  return Math.min(Math.max(1, page), totalPages(total, pageSize));
}

/** The rows of one page, for lists that are loaded whole in the browser. */
export function slicePage<T>(items: readonly T[], page: number, pageSize = PAGE_SIZE): T[] {
  const p = clampPage(page, items.length, pageSize);
  return items.slice((p - 1) * pageSize, p * pageSize);
}

/**
 * The page buttons to draw: always page 1 and the last page, the pages
 * within `range` of the current one, and "..." where a run is skipped.
 * e.g. page 1 of 15 → [1, 2, 3, 4, "...", 15]. Phones use range 1 so the bar fits.
 */
export function pageButtons(page: number, pages: number, range = 3): (number | "...")[] {
  const nums: number[] = [1];
  for (let i = Math.max(2, page - range); i <= Math.min(pages - 1, page + range); i++) nums.push(i);
  if (pages > 1) nums.push(pages);
  const out: (number | "...")[] = [];
  nums.forEach((n, i) => {
    if (i > 0 && n - nums[i - 1] > 1) out.push("...");
    out.push(n);
  });
  return out;
}

/** "1–25 of 366" parts for the left-hand count. */
export function showingRange(page: number, total: number, pageSize = PAGE_SIZE): { from: number; to: number } {
  if (total === 0) return { from: 0, to: 0 };
  const p = clampPage(page, total, pageSize);
  return { from: (p - 1) * pageSize + 1, to: Math.min(p * pageSize, total) };
}
