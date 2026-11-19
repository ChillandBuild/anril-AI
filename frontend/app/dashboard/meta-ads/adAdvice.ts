/**
 * The Advice column on Messaging ads: one short tip per ad, from its numbers in the
 * chosen dates. The first rule that fits wins:
 *
 *   1. Too early to tell        spent under ₹500, or under 10 people messaged
 *   2. ★ Best · keep running    running, 1+ paid, the cheapest hot leads of those
 *   3. Chats, but no customers  20+ people messaged, nobody booked
 *   4. Costly · don't restart   stopped, cost per hot lead over 2× your average
 *   5. Costly · watch it        running, cost per hot lead over 2× your average
 *   6. Ended on schedule        stopped on or after the end date set in Meta
 *   7. Doing okay               anything else
 *
 * "Your average" and "cheapest" compare every ad in the dates, not only the card
 * picked above the table, so an ad's tip doesn't change with the card.
 * An ad with no hot leads counts as costly once it is past "too early".
 */
import type { AdPerformanceRow } from "@/lib/api";

export type AdviceKey = "too_early" | "best" | "no_customers" | "costly_stopped" | "costly_running" | "ended" | "ok";

export interface Advice {
  key: AdviceKey;
  label: string;
  /** One line, shown on hover. */
  reason: string;
}

export const ADVICE_MIN_SPEND = 500;
export const ADVICE_MIN_CHATS = 10;
export const ADVICE_NO_CUSTOMER_CHATS = 20;
const COSTLY_TIMES = 2;

type AdviceRow = Pick<
  AdPerformanceRow,
  "ad_creative_id" | "delivery_status" | "spend" | "messages" | "hot" | "booked" | "paid" | "schedule_end"
>;

function rupees(value: number) {
  return "₹" + Math.round(value).toLocaleString("en-IN");
}

function plural(n: number, one: string, many: string) {
  return `${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;
}

function isRunning(row: AdviceRow) {
  return (row.delivery_status ?? "").toUpperCase() === "ACTIVE";
}

function tooEarly(row: AdviceRow) {
  return row.spend < ADVICE_MIN_SPEND || row.messages < ADVICE_MIN_CHATS;
}

function costPerHot(row: AdviceRow): number | null {
  return row.hot ? row.spend / row.hot : null;
}

/** Tips for every ad, keyed by ad_creative_id. `today` is YYYY-MM-DD (the viewer's day). */
export function adviceFor(rows: AdviceRow[], today: string): Map<string, Advice> {
  const spend = rows.reduce((sum, row) => sum + row.spend, 0);
  const hot = rows.reduce((sum, row) => sum + row.hot, 0);
  const average = hot ? spend / hot : null;

  let best: AdviceRow | null = null;
  for (const row of rows) {
    const cost = costPerHot(row);
    if (!isRunning(row) || tooEarly(row) || row.paid < 1 || cost == null) continue;
    if (best == null || cost < (costPerHot(best) ?? Infinity)) best = row;
  }

  const out = new Map<string, Advice>();
  for (const row of rows) {
    out.set(row.ad_creative_id, adviceOne(row, { average, bestId: best?.ad_creative_id ?? null, today }));
  }
  return out;
}

function adviceOne(row: AdviceRow, ctx: { average: number | null; bestId: string | null; today: string }): Advice {
  if (tooEarly(row)) {
    return {
      key: "too_early",
      label: "Too early to tell",
      reason: row.spend < ADVICE_MIN_SPEND
        ? `Only ${rupees(row.spend)} spent so far. Wait for more chats before judging.`
        : `Only ${plural(row.messages, "person", "people")} messaged so far. Wait for more chats before judging.`,
    };
  }
  const cost = costPerHot(row);
  if (row.ad_creative_id === ctx.bestId && cost != null) {
    return {
      key: "best",
      label: "★ Best · keep running",
      reason: `Your cheapest hot leads (${rupees(cost)} each) and ${row.paid} paid.`,
    };
  }
  if (row.messages >= ADVICE_NO_CUSTOMER_CHATS && row.booked === 0) {
    return {
      key: "no_customers",
      label: "Chats, but no customers",
      reason: `${plural(row.messages, "chat", "chats")}, 0 bookings. Check the replies or the price.`,
    };
  }
  const costly = ctx.average != null && (cost == null || cost > ctx.average * COSTLY_TIMES);
  if (costly && ctx.average != null) {
    const why = cost == null
      ? `${rupees(row.spend)} spent and no hot leads yet.`
      : `${rupees(cost)} per hot lead, against your ${rupees(ctx.average)} average.`;
    return isRunning(row)
      ? { key: "costly_running", label: "Costly · watch it", reason: why }
      : { key: "costly_stopped", label: "Costly · don't restart", reason: why };
  }
  const end = row.schedule_end?.slice(0, 10);
  if (!isRunning(row) && end && end <= ctx.today) {
    return { key: "ended", label: "Ended on schedule", reason: `Ran until the end date set in Meta.` };
  }
  return {
    key: "ok",
    label: "Doing okay",
    reason: cost != null && ctx.average != null
      ? `About average: ${rupees(cost)} per hot lead (your average is ${rupees(ctx.average)}).`
      : "Nothing stands out yet.",
  };
}
