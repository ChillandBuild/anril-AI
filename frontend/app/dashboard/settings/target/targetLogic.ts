// Pure helpers for Settings > Target & profit: typed rupees <-> paise, the editable months,
// the form draft and the body to save, and the plain-words lines. No React, so it is unit-tested.
import { cleanNumberText, formatRupees } from "../payments/advanceText";

export { formatRupees };

/** The backend refuses more than this many paise (and more than this many months). */
export const MAX_PAISE = 1_000_000_000_000;
export const MAX_MONTHS = 24;
/** This month and the next three can be given their own target. */
export const EDITABLE_MONTHS = 4;

export type TargetSaved = { monthly_paise: number | null; months: Record<string, number>; show_team: boolean };
export type Mode = "same" | "different";
export type TargetDraft = {
  monthlyText: string;
  mode: Mode;
  monthTexts: Record<string, string>;
  showTeam: boolean;
};
export type TargetBody = { monthly_paise: number | null; months: Record<string, number>; show_team: boolean };

/** "2026-11" -> "November 2026". */
export function monthLabel(key: string): string {
  const [y, m] = key.split("-").map(Number);
  if (!y || !m) return key;
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-IN", { month: "long", year: "numeric", timeZone: "UTC" });
}

/** The editable month keys, starting with `currentKey` (this month, IST): ["2026-11", "2026-12", "2027-01", "2027-02"]. */
export function editableMonths(currentKey: string, count: number = EDITABLE_MONTHS): string[] {
  const [y, m] = currentKey.split("-").map(Number);
  if (!y || !m) return [];
  return Array.from({ length: count }, (_, i) => {
    const idx = y * 12 + (m - 1) + i;
    return `${Math.floor(idx / 12)}-${String((idx % 12) + 1).padStart(2, "0")}`;
  });
}

/** Rupees typed by a person -> paise. null = empty (no target), "bad" = not a usable amount. */
export function rupeesTextToPaise(text: string): number | null | "bad" {
  if (!text.trim()) return null;
  const clean = cleanNumberText(text);
  if (!clean || clean === ".") return "bad";
  const paise = Math.round(Number(clean) * 100);
  if (!Number.isFinite(paise) || paise < 0 || paise > MAX_PAISE) return "bad";
  return paise;
}

/** Paise -> the plain number to put in the box: 20000000 -> "200000". */
export function paiseToText(paise: number | null | undefined): string {
  if (paise == null || paise <= 0) return "";
  return String(paise / 100);
}

/** Show typed digits with Indian commas when the box loses focus: "200000" -> "2,00,000". */
export function prettyRupeesText(text: string): string {
  const paise = rupeesTextToPaise(text);
  if (paise == null || paise === "bad") return text;
  return (paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

export function draftFromSaved(saved: TargetSaved, currentKey: string): TargetDraft {
  const window = editableMonths(currentKey);
  const monthTexts: Record<string, string> = {};
  for (const key of window) monthTexts[key] = paiseToText(saved.months[key]);
  const different = window.some((k) => saved.months[k] != null);
  return { monthlyText: paiseToText(saved.monthly_paise), mode: different ? "different" : "same", monthTexts, showTeam: saved.show_team };
}

/** The first problem in plain words, or null. */
export function draftError(draft: TargetDraft, currentKey: string): string | null {
  if (rupeesTextToPaise(draft.monthlyText) === "bad") return "Type the target as a number of rupees, like 2,00,000.";
  if (draft.mode === "different") {
    for (const key of editableMonths(currentKey)) {
      if (rupeesTextToPaise(draft.monthTexts[key] ?? "") === "bad") return `Type the ${monthLabel(key)} target as a number of rupees.`;
    }
  }
  return null;
}

/**
 * What to save. Months after the editable window stay as they were; months before this month are
 * dropped (they no longer matter, and the backend allows only 24 saved months). In "different"
 * mode a month left empty uses the every-month target.
 */
export function buildBody(draft: TargetDraft, saved: TargetSaved, currentKey: string): TargetBody {
  const window = editableMonths(currentKey);
  const months: Record<string, number> = {};
  for (const [key, value] of Object.entries(saved.months)) if (key >= currentKey && !window.includes(key)) months[key] = value;
  if (draft.mode === "different") {
    for (const key of window) {
      const paise = rupeesTextToPaise(draft.monthTexts[key] ?? "");
      if (typeof paise === "number") months[key] = paise;
    }
  }
  const monthly = rupeesTextToPaise(draft.monthlyText);
  return { monthly_paise: typeof monthly === "number" ? monthly : null, months, show_team: draft.showTeam };
}

export function sameBody(a: TargetBody, b: TargetBody): boolean {
  if (a.monthly_paise !== b.monthly_paise || a.show_team !== b.show_team) return false;
  const ak = Object.keys(a.months).sort();
  const bk = Object.keys(b.months).sort();
  return ak.length === bk.length && ak.every((k, i) => k === bk[i] && a.months[k] === b.months[k]);
}

/** The target for one month: its own number if set, else the every-month one. */
export function effectiveTarget(body: Pick<TargetBody, "monthly_paise" | "months">, key: string): number | null {
  const own = body.months[key];
  const value = own != null ? own : body.monthly_paise;
  return value ? value : null;
}

/** 186000, 200000 -> 93. null when there is no target. */
export function percentOf(moneyIn: number, target: number | null | undefined): number | null {
  if (!target || target <= 0) return null;
  return Math.round((moneyIn * 100) / target);
}

/** "Suggested: ₹2,05,000. That is the average of your last 3 months with sales, plus 10%." (empty months are left out) */
export function suggestionLine(suggestedPaise: number | null, monthsWithMoney: number): string | null {
  if (suggestedPaise == null) return null;
  const basis = monthsWithMoney === 1 ? "your last month with sales" : `the average of your last ${Math.max(monthsWithMoney, 2)} months with sales`;
  return `Suggested: ${formatRupees(suggestedPaise)}. That is ${basis}, plus 10%.`;
}

/** "Items with a cost price: 1 of 7"; null when it can't be counted. */
export function costCoverageLine(c: { with_cost: number; total: number } | null | undefined): string | null {
  if (!c) return null;
  return `Items with a cost price: ${c.with_cost.toLocaleString("en-IN")} of ${c.total.toLocaleString("en-IN")}`;
}
