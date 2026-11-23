import type { FeedbackReport } from "@/lib/customersApi";

/** How long the "this is the one you tapped" highlight stays on a row. */
export const HIGHLIGHT_MS = 3000;

/** DOM id of the row in the "Unhappy and still open" list. */
export const unhappyRowId = (id: string) => `fb-${id}`;
/** DOM id of the row in the "Recent" list (a different id, so the same feedback never has two equal ids). */
export const recentRowId = (id: string) => `fb-recent-${id}`;

/**
 * The element id to scroll to for ?fb=<feedback id>. Looks in the unhappy list first, then in Recent.
 * Returns null when there is no fb, or the row is not in the report (already fixed, or out of range).
 */
export function feedbackRowTarget(
  report: Pick<FeedbackReport, "unhappy_open" | "recent">,
  fb: string | null | undefined,
): string | null {
  const id = (fb ?? "").trim();
  if (!id) return null;
  if (report.unhappy_open.some((r) => r.id === id)) return unhappyRowId(id);
  if (report.recent.some((r) => r.id === id)) return recentRowId(id);
  return null;
}
