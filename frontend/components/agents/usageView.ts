import type { AgentUsage } from "@/lib/api";

/** The meter: share of the included replies used, capped at 100 for the bar.
 * 3,420 of 10,000 → { pct: 34, bar: 34, tone: "ok" }; 8,500 → "near"; 10,420 → { pct: 104, bar: 100, tone: "over" }.
 * No plan (included 0) → null. */
export function meter(used: number, included: number): { pct: number; bar: number; tone: "ok" | "near" | "over" } | null {
  if (included <= 0) return null;
  const pct = Math.round((used / included) * 100);
  return { pct, bar: Math.min(100, pct), tone: used > included ? "over" : used >= included * 0.8 ? "near" : "ok" };
}

/** One bar per UTC day from the cycle start to today (or the cycle end, if sooner), missing days as 0. */
export function cycleBars(usage: Pick<AgentUsage, "daily" | "period_start" | "period_end">, today = new Date()) {
  const byDate = new Map(usage.daily.map((d) => [d.date, d.count]));
  const start = new Date(`${usage.period_start}T00:00:00Z`);
  const todayUtc = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
  const endDay = usage.period_end ? new Date(Date.parse(`${usage.period_end}T00:00:00Z`) - 86_400_000) : todayUtc;
  const last = endDay < todayUtc ? endDay : todayUtc;
  const out: { date: string; count: number }[] = [];
  for (let d = start; d <= last && out.length < 62; d = new Date(d.getTime() + 86_400_000)) {
    const key = d.toISOString().slice(0, 10);
    out.push({ date: key, count: byDate.get(key) ?? 0 });
  }
  return out;
}

/** Replies per character over the cycle, most first. "unknown" (a deleted character) is labelled as such. */
export function byCharacter(usage: Pick<AgentUsage, "daily" | "companions">): { name: string; count: number }[] {
  const totals = new Map<string, number>();
  for (const day of usage.daily) {
    for (const [id, n] of Object.entries(day.by_companion)) totals.set(id, (totals.get(id) ?? 0) + n);
  }
  return Array.from(totals.entries())
    .map(([id, count]) => ({ name: usage.companions[id] ?? "Deleted character", count }))
    .sort((a, b) => b.count - a.count);
}

/** "₹3,000" from 3000; "₹2,999.5" from 2999.5. */
export function rupees(amount: number): string {
  return `₹${amount.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

/** "5 Nov" from "2026-11-05". */
export function shortDate(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });
}
