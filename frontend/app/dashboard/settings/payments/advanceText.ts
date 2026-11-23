// Pure helpers for Settings > Payments & advance: the advance rule's form draft, the maths behind
// the live example line (same as backend order_quotes.advance_for), and plain-words text.
// No React here, so it is unit-tested.

export type AdvanceKind = "none" | "fixed" | "percent";

/** The rule as /api/v1/orders/advance-rule sends and saves it. `value` is rupees for fixed, a percent for percent. */
export type AdvanceRule = { kind: AdvanceKind; value: number; min_total_paise: number };

/** What the form holds while the owner types. */
export type AdvanceDraft = { kind: AdvanceKind; valueText: string; minText: string };

export const EXAMPLE_TOTAL_PAISE = 10_500 * 100;

/** The backend limits (AdvanceRuleIn): the advance up to ₹1 crore, the order amount up to ₹1 crore, a percent up to 100. */
export const MAX_PERCENT = 100;
export const MAX_ADVANCE_RUPEES = 10_000_000;
export const MAX_MIN_ORDER_RUPEES = 10_000_000;

/** ₹1,86,400 (Indian grouping); paise only when there are some. */
export function formatRupees(paise: number | null | undefined): string {
  if (paise == null || !Number.isFinite(paise)) return "—";
  const whole = paise % 100 === 0;
  return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2 });
}

/** Round half to even, like Python's round() in the backend, so the example never differs by a paisa. */
export function roundHalfEven(x: number): number {
  const floor = Math.floor(x);
  const diff = x - floor;
  if (Math.abs(diff - 0.5) < 1e-9) return floor % 2 === 0 ? floor : floor + 1;
  return Math.round(x);
}

/** The advance a rule asks for on this total (never more than the total). Mirrors advance_for. */
export function advanceFor(totalPaise: number, rule: AdvanceRule): number {
  if (rule.kind === "none" || totalPaise <= 0) return 0;
  if (rule.min_total_paise && totalPaise < rule.min_total_paise) return 0;
  const amount = rule.kind === "percent" ? roundHalfEven((totalPaise * rule.value) / 100) : roundHalfEven(rule.value * 100);
  return Math.max(0, Math.min(amount, totalPaise));
}

/** "Example: a ₹10,500 order → advance ₹4,200, balance ₹6,300 at pickup". */
export function exampleLine(rule: AdvanceRule): string {
  const total = rule.min_total_paise > EXAMPLE_TOTAL_PAISE ? rule.min_total_paise : EXAMPLE_TOTAL_PAISE;
  const advance = advanceFor(total, rule);
  const order = `Example: a ${formatRupees(total)} order`;
  if (rule.kind === "none") return `${order} → no advance, all ${formatRupees(total)} is paid at pickup`;
  if (advance === 0) return `${order} → no advance`;
  return `${order} → advance ${formatRupees(advance)}, balance ${formatRupees(total - advance)} at pickup`;
}

/** What happens to an order under the "only for orders of ₹X or more" amount (shown when that amount is set). */
export function belowMinLine(rule: AdvanceRule): string | null {
  if (rule.kind === "none" || !rule.min_total_paise) return null;
  return `Orders under ${formatRupees(rule.min_total_paise)} pay in full.`;
}

/** "30% of the bill, only for orders of ₹5,000 or more" · "₹1,000" · "No advance". */
export function ruleSummary(rule: AdvanceRule): string {
  if (rule.kind === "none") return "No advance";
  const base = rule.kind === "percent" ? `${Number(rule.value)}% of the bill` : formatRupees(Math.round(rule.value * 100));
  return rule.min_total_paise ? `${base}, only for orders of ${formatRupees(rule.min_total_paise)} or more` : base;
}

/** Digits (and one dot) from what was typed: "₹ 2,00,000" -> "200000". */
export function cleanNumberText(text: string): string {
  const stripped = text.replace(/[₹,\s]/g, "");
  return /^\d*\.?\d*$/.test(stripped) ? stripped : "";
}

function numberFrom(text: string): number | null {
  const t = cleanNumberText(text);
  if (!t || t === ".") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

export function draftFromRule(rule: AdvanceRule): AdvanceDraft {
  return {
    kind: rule.kind,
    valueText: rule.kind === "none" || !rule.value ? "" : String(Number(rule.value)),
    minText: rule.min_total_paise ? String(rule.min_total_paise / 100) : "",
  };
}

/** The first problem with the draft in plain words, or null when it can be saved. */
export function draftError(draft: AdvanceDraft): string | null {
  if (draft.kind === "none") return null;
  const value = numberFrom(draft.valueText);
  if (draft.kind === "percent" && (value == null || value <= 0 || value > MAX_PERCENT)) return "Type a percent above 0 and up to 100.";
  if (draft.kind === "fixed" && (value == null || value <= 0)) return "Type the advance amount in rupees.";
  if (draft.kind === "fixed" && value != null && value > MAX_ADVANCE_RUPEES) return "That advance is too large. Type ₹1,00,00,000 or less.";
  if (draft.minText.trim()) {
    const min = numberFrom(draft.minText);
    if (min == null) return "Type the order amount in numbers, or leave it empty.";
    if (min > MAX_MIN_ORDER_RUPEES) return "That order amount is too large. Type ₹1,00,00,000 or less.";
  }
  return null;
}

/** The rule to save (or to show in the live example). Not valid until draftError is null. */
export function ruleFromDraft(draft: AdvanceDraft): AdvanceRule {
  if (draft.kind === "none") return { kind: "none", value: 0, min_total_paise: 0 };
  const min = numberFrom(draft.minText);
  return {
    kind: draft.kind,
    value: numberFrom(draft.valueText) ?? 0,
    min_total_paise: min && min > 0 ? Math.round(min * 100) : 0,
  };
}

/** Same rule? (decides whether Save is on). */
export function sameRule(a: AdvanceRule, b: AdvanceRule): boolean {
  if (a.kind !== b.kind) return false;
  if (a.kind === "none") return true;
  return Number(a.value) === Number(b.value) && a.min_total_paise === b.min_total_paise;
}

/** Screen 155: the WhatsApp message a customer gets with the example order (mirrors deal_actions._quote_text). */
export function customerPreview(rule: AdvanceRule): string {
  const total = rule.min_total_paise > EXAMPLE_TOTAL_PAISE ? rule.min_total_paise : EXAMPLE_TOTAL_PAISE;
  const advance = advanceFor(total, rule);
  const head = `• Silk saree x1 — ${formatRupees(total)}\nTotal: ${formatRupees(total)}`;
  if (advance > 0 && advance < total) {
    return `${head}\nAdvance to book: ${formatRupees(advance)} (the rest, ${formatRupees(total - advance)}, later)\n\nPay the advance here: rzp.io/l/…`;
  }
  return `${head}\n\nPay here: rzp.io/l/…`;
}
