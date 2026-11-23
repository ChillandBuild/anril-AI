// Pure helpers for the Home charts: scaling, ring and gauge maths, labels. No React here, so it is unit-tested.
import type { HomeBox } from "@/lib/api";

export type Pt = { x: number; y: number };

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** "2026-11-23" -> "Mon". Empty for anything that is not a YYYY-MM-DD day. */
export function dayName(day: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(day ?? "");
  if (!m) return "";
  return WEEKDAYS[new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))).getUTCDay()] ?? "";
}

/** The n weekday names ending on endDay (a YYYY-MM-DD day), oldest first. */
export function weekdayLabels(endDay: string, n: number): string[] {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(endDay ?? "");
  if (!m) return Array.from({ length: n }, () => "");
  const end = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Array.from({ length: n }, (_, i) => WEEKDAYS[new Date(end - (n - 1 - i) * 86_400_000).getUTCDay()]);
}

/** A box's 7-day series when the server sent a usable one (2+ finite numbers), else null: no line is drawn. */
export function boxSeries(box: Pick<HomeBox, "series"> | null | undefined): number[] | null {
  const s = box?.series;
  if (!Array.isArray(s) || s.length < 2) return null;
  return s.every((v) => typeof v === "number" && Number.isFinite(v)) ? s : null;
}

/**
 * Points for a small trend line in a w x h box. The scale starts at zero (or the lowest value when
 * negative) so a quiet day is not drawn as a collapse. The last point sits `pad` in from the right edge,
 * which leaves room for the end dot.
 */
export function sparkPoints(values: readonly number[], w = 84, h = 28, pad = 4): Pt[] {
  if (values.length === 0) return [];
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const span = hi - lo || 1;
  const step = values.length > 1 ? (w - 2 * pad) / (values.length - 1) : 0;
  return values.map((v, i) => ({
    x: pad + i * step,
    y: h - pad - ((v - lo) / span) * (h - 2 * pad),
  }));
}

/** SVG points="x,y x,y" text, one decimal. */
export function pointsAttr(pts: readonly Pt[]): string {
  return pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
}

/** Top of a chart's y axis: 4, or the next multiple of 4, so the middle tick is a whole number. */
export function niceMax(max: number): number {
  if (!Number.isFinite(max) || max <= 4) return 4;
  return Math.ceil(max / 4) * 4;
}

/** Points of a line chart inside the plot box [left..right] x [top..bottom], y axis 0..yMax. */
export function linePlot(
  values: readonly number[],
  box: { left: number; right: number; top: number; bottom: number },
  yMax: number,
): Pt[] {
  const step = values.length > 1 ? (box.right - box.left) / (values.length - 1) : 0;
  const top = yMax > 0 ? yMax : 1;
  return values.map((v, i) => ({
    x: box.left + i * step,
    y: box.bottom - (Math.max(0, v) / top) * (box.bottom - box.top),
  }));
}

/**
 * Slices of a ring drawn as stroked circles. Each slice is a dash of its share of the circle (less `gap`)
 * pushed round by the slices before it. Zero-count slices are skipped (dash is null).
 */
export function donutSlices(
  counts: readonly number[],
  r: number,
  gap = 3,
): { dash: string | null; offset: number }[] {
  const circ = 2 * Math.PI * r;
  const total = counts.reduce((a, b) => a + Math.max(0, b), 0);
  let done = 0;
  return counts.map((c) => {
    const n = Math.max(0, c);
    if (total <= 0 || n === 0) return { dash: null, offset: 0 };
    const share = (n / total) * circ;
    const len = n === total ? circ : Math.max(share - gap, 0.5);
    const out = { dash: `${len.toFixed(2)} ${(circ - len).toFixed(2)}`, offset: done === 0 ? 0 : -Number(done.toFixed(2)) };
    done += share;
    return out;
  });
}

/** Stroke dash for a ring r wide filled pct (0..100) of the way round. */
export function ringDash(pct: number, r: number): string {
  const circ = 2 * Math.PI * r;
  const p = Math.max(0, Math.min(100, Number.isFinite(pct) ? pct : 0));
  return `${((p / 100) * circ).toFixed(2)} ${circ.toFixed(2)}`;
}

/** How full the Target ring is (0..100), or null when the box has no percent to show (the "Set a target" box). */
export function targetPct(box: Pick<HomeBox, "value" | "unit" | "sub">): number | null {
  if (box.unit === "percent") return typeof box.value === "number" && Number.isFinite(box.value) ? clampPct(box.value) : null;
  if (box.unit === "paise") {
    // "of ₹2,00,000 · 93%": the percent is the last number in the sub line.
    const m = /(\d+(?:\.\d+)?)\s*%/.exec(box.sub ?? "");
    return m ? clampPct(Number(m[1])) : null;
  }
  return null;
}

function clampPct(n: number): number {
  return Math.max(0, Math.min(100, Math.round(n)));
}

/** Share of the AI's answered chats among answered + couldn't answer, 0..100. Null when there is nothing to share. */
export function aiShare(answered: number, couldnt: number): number | null {
  const a = Math.max(0, answered || 0);
  const c = Math.max(0, couldnt || 0);
  return a + c > 0 ? Math.round((a / (a + c)) * 100) : null;
}

/** Bar length as a percent of the longest bar. A non-zero value never shrinks below `min` so it stays visible. */
export function barPct(value: number, max: number, min = 2): number {
  if (!(max > 0) || !(value > 0)) return 0;
  return Math.max(min, Math.min(100, (value / max) * 100));
}

/**
 * What a box's 7-day line plots. It is not always the box number: "Won" shows the month so far but its line
 * is won per day, and "Follow-ups due" shows what is still pending today but its line is call-backs scheduled
 * per day. The line's last point is today's own count, so the caption says "per day", never "the number".
 */
const SERIES_WHAT: Record<string, string> = {
  new_enquiries_today: "New enquiries per day",
  callbacks_today: "Call-backs scheduled per day",
  won_month: "Won per day",
  money_in_today: "Money in per day",
  target_month: "Money in per day",
};

export function seriesCaption(boxKey: string, fallbackLabel: string): string {
  return SERIES_WHAT[boxKey] ?? `${fallbackLabel} per day`;
}
