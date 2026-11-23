// v9.2 #184 Activity log (Team & roles): plain words for each row, the filter choices, and the "money" rows
// (refunds, discounts, advance changes) that are shown pale yellow. Rupee figures only when the viewer may see money.
import { formatRupees } from "@/lib/reportsApi";

export type ActivityEntry = {
  action: string;
  metadata: Record<string, unknown> | null;
  money?: boolean;
};

export const ACTIVITY_TYPE_LABELS: Record<string, string> = {
  team: "Team changes",
  roles: "Role changes",
  money: "Money (refunds, discounts, advance)",
  login: "Logins",
  claude: "Anril AI connector",
};

const ACTION_WORDS: Record<string, string> = {
  "order.refund": "Refund given",
  "order.discount": "Discount given on a bill",
  "order.advance_changed": "Advance changed",
  "auth.login": "Signed in",
};

export function typeOptions(allowed: string[] | undefined): { value: string; label: string }[] {
  const list = (allowed ?? ["team", "roles", "login"]).filter((t) => t in ACTIVITY_TYPE_LABELS);
  return [{ value: "", label: "Everything" }, ...list.map((value) => ({ value, label: ACTIVITY_TYPE_LABELS[value] }))];
}

export function actionLabel(action: string): string {
  return ACTION_WORDS[action] ?? action;
}

export function isMoneyRow(e: ActivityEntry): boolean {
  return e.money === true || e.action in { "order.refund": 1, "order.discount": 1, "order.advance_changed": 1 };
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function text(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

export function activityDetail(e: ActivityEntry, canSeeMoney: boolean): string {
  const m = e.metadata ?? {};
  const join = (parts: (string | null)[]) => parts.filter(Boolean).join(" · ");
  if (isMoneyRow(e)) {
    if (!canSeeMoney) return "";
    if (e.action === "order.refund") {
      const amount = num(m.amount_paise);
      return join([amount === null ? null : formatRupees(amount), text(m.method), text(m.reason), text(m.order) ? `order ${text(m.order)}` : null]);
    }
    if (e.action === "order.discount") {
      const off = num(m.discount_paise);
      const total = num(m.subtotal_paise);
      return join([off === null ? null : `${formatRupees(off)} off${total === null ? "" : ` a ${formatRupees(total)} ${text(m.kind) ?? "bill"}`}`]);
    }
    if (e.action === "order.advance_changed") {
      const from = num(m.from_paise);
      const to = num(m.to_paise);
      return join([from !== null && to !== null ? `${formatRupees(from)} to ${formatRupees(to)}` : null, text(m.note)]);
    }
  }
  if (e.action === "auth.login") {
    return join([text(m.ip) ? `from ${text(m.ip)}` : null, text(m.device)]);
  }
  return Object.entries(m)
    .filter(([k, v]) => v !== null && v !== undefined && v !== "********" && !(!canSeeMoney && k.endsWith("_paise")))
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" · ");
}
