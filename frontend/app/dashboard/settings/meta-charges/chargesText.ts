import type { AiReplies, MetaCharges } from "@/lib/connectionsApi";

export const NOT_AVAILABLE_HELP =
  "This usually means WhatsApp isn't connected yet, or Meta is slow to answer. We never guess your charges. Check again in a little while.";

/** 2140 -> "₹2,140", 2140.5 -> "₹2,140.50" (Indian grouping). Other currencies show their code. */
export function formatMoney(value: number, currency: string, wholeRupees = false): string {
  const whole = wholeRupees || Number.isInteger(value);
  const digits = whole ? 0 : 2;
  const amount = (wholeRupees ? Math.round(value) : value).toLocaleString("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return currency === "INR" ? `₹${amount}` : `${currency} ${amount}`;
}

export function formatCount(n: number): string {
  return n.toLocaleString("en-IN");
}

/** The width of the AI replies bar: 0 to 100, never more, never negative. */
export function barWidth(pct: number | null): number {
  if (pct == null || Number.isNaN(pct)) return 0;
  return Math.min(100, Math.max(0, pct));
}

export type BarTone = "ok" | "warn" | "full";

export function barTone(pct: number | null): BarTone {
  if (pct != null && pct >= 100) return "full";
  if (pct != null && pct >= 80) return "warn";
  return "ok";
}

/** "Meta charged ₹2,140 this month. You have used 76% of your AI replies." */
export function inShort(charges: MetaCharges, ai: AiReplies): string {
  const first = charges.available
    ? `Meta charged ${formatMoney(charges.total.cost, charges.currency, true)} this month.`
    : "Meta hasn't shared this month's charges yet.";
  const second =
    ai.pct != null
      ? `You have used ${ai.pct}% of your AI replies.`
      : `You have used ${formatCount(ai.used)} AI ${ai.used === 1 ? "reply" : "replies"} this month.`;
  return `${first} ${second}`;
}

/** Why the weekly limit can't be saved, or null when it's fine. */
export function reachLimitProblem(text: string, min: number, max: number): string | null {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return `Enter a whole number from ${min} to ${max}.`;
  const n = Number(t);
  return n < min || n > max ? `Enter a whole number from ${min} to ${max}.` : null;
}
