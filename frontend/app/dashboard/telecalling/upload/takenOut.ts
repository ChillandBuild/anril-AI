/** Upload history: the rows an upload left out, and why (counts come from the server). */
export const TAKEN_OUT_LABEL: Record<string, string> = {
  bad_number: "bad number",
  duplicate: "repeated in the file",
  said_stop: "said stop",
  already_customer: "already a customer",
  closed: "closed earlier",
  already_with_caller: "already with a telecaller",
};

export type TakenOutCounts = Record<string, number> | null | undefined;

/** Total rows taken out, or null for an upload made before this was recorded (the page shows a dash). */
export function takenOutTotal(counts: TakenOutCounts): number | null {
  if (!counts) return null;
  return Object.values(counts).reduce((a, b) => a + b, 0);
}

/** "2 bad number · 1 said stop", biggest first. */
export function takenOutReasons(counts: TakenOutCounts): string {
  if (!counts) return "";
  return Object.entries(counts)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([reason, n]) => `${n} ${TAKEN_OUT_LABEL[reason] ?? reason}`)
    .join(" · ");
}
