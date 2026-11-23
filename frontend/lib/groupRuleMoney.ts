/** Small helpers for the group rule rows: rupees <-> paise, and the "Used by" line. */

const MAX_RUPEES = 100_000_000; // the server caps a spend filter at the same size

/** "1,500" or "1500.50" in rupees -> paise. Empty or not a number -> undefined. */
export function rupeesToPaise(text: string): number | undefined {
  const cleaned = text.replace(/[,\s₹]/g, "");
  if (!cleaned) return undefined;
  const rupees = Number(cleaned);
  if (!Number.isFinite(rupees) || rupees < 0) return undefined;
  return Math.round(Math.min(rupees, MAX_RUPEES) * 100);
}

/** Paise -> rupees as the box shows them. 0 or missing -> "". */
export function paiseToRupeesText(paise: number | undefined): string {
  if (!paise) return "";
  const rupees = paise / 100;
  return Number.isInteger(rupees) ? String(rupees) : rupees.toFixed(2);
}

/** "Used by Reach · Call IQ · Follow-ups", or "Not used yet" when nothing points at the group. */
export function usedByLabel(used: string[] | undefined): string {
  return used && used.length > 0 ? `Used by ${used.join(" · ")}` : "Not used yet";
}
