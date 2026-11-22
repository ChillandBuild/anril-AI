import { apiFetch } from "@/lib/api";

/** Settings > My business: Payments & advance, and Target & profit. */

export type WayToPay = { key: "razorpay" | "in_shop" | "gst" | string; ok: boolean | null; detail: string };

export type PaymentsOverview = {
  refund_who: string[];
  balance_reminders: string;
  refund_message: { razorpay: string; other: string };
  ways_to_pay: WayToPay[];
};

/** The rule as /api/v1/orders/advance-rule sends and saves it (the same rule Orders > Settings edits). */
export type AdvanceRuleBody = { kind: "none" | "fixed" | "percent"; value: number; min_total_paise: number };

export type TargetOverview = {
  monthly_paise: number | null;
  months: Record<string, number>;
  show_team: boolean;
  suggested_paise: number | null;
  last3: { month: string; money_in_paise: number | null }[];
  this_month: { month: string; target_paise: number | null; money_in_paise: number | null; pct: number | null };
  cost_coverage: { with_cost: number; total: number } | null;
};

export type TargetSaveBody = { monthly_paise: number | null; months: Record<string, number>; show_team: boolean };

export const myBusinessApi = {
  payments: () => apiFetch<PaymentsOverview>("/api/v1/my-business/payments"),
  target: () => apiFetch<TargetOverview>("/api/v1/my-business/target"),
  /** Owner only (403 "Only the owner can set the target."). Answers with the fresh overview. */
  saveTarget: (body: TargetSaveBody) =>
    apiFetch<TargetOverview>("/api/v1/my-business/target", { method: "PUT", body: JSON.stringify(body) }),
  /** The existing Orders API: anyone who can see Orders may read it. */
  advanceRule: () => apiFetch<AdvanceRuleBody>("/api/v1/orders/advance-rule"),
  /** The existing Orders API: owner only. */
  saveAdvanceRule: (body: AdvanceRuleBody) =>
    apiFetch<AdvanceRuleBody>("/api/v1/orders/advance-rule", { method: "PUT", body: JSON.stringify(body) }),
};
