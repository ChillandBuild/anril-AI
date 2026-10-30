import { API_URL, getAuthHeaders } from "@/lib/api";
import type {
  PrivateSendNewKey,
  PrivateSendOverview,
  PrivateSendSettingsPatch,
} from "@/app/operator/(console)/client/[id]/types";

/**
 * Shared fetch helper for the operator console. Adds JSON content-type +
 * auth headers, and throws `detail || "Request failed"` on non-ok responses.
 * Returns the parsed JSON body as-is — callers that expect an `{ data }`
 * envelope must unwrap it themselves (this mirrors the per-page helpers it
 * replaces, some of which returned raw arrays/objects and some `{ data }`).
 */
export async function operatorFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const auth = await getAuthHeaders();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...auth, ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = new Error((body as { detail?: string }).detail || "Request failed") as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json() as Promise<T>;
}

/**
 * Relative time formatter for the operator console. Handles both past
 * ("Xs ago") and future ("in Xs") timestamps across seconds/minutes/hours/days.
 * Returns "—" for null.
 */
export function relTime(iso: string | null): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const future = diff < 0;
  const s = Math.abs(diff) / 1000;

  let fmt: string;
  if (s < 60) fmt = `${Math.round(s)}s`;
  else if (s < 3600) fmt = `${Math.round(s / 60)}m`;
  else if (s < 86400) fmt = `${Math.round(s / 3600)}h`;
  else fmt = `${Math.round(s / 86400)}d`;

  return future ? `in ${fmt}` : `${fmt} ago`;
}

/* ------------------------------------------------------------------ *
 * Private Send (operator side)
 * ------------------------------------------------------------------ */

const privateSendPath = (tenantId: string) => `/api/v1/operator/clients/${tenantId}/private-send`;

export const getPrivateSend = (tenantId: string) =>
  operatorFetch<PrivateSendOverview>(privateSendPath(tenantId));

export const createPrivateSendKey = (tenantId: string) =>
  operatorFetch<PrivateSendNewKey>(`${privateSendPath(tenantId)}/keys`, { method: "POST" });

export const revokePrivateSendKey = (tenantId: string, keyId: string) =>
  operatorFetch<{ ok: boolean }>(`${privateSendPath(tenantId)}/keys/${keyId}`, { method: "DELETE" });

export const updatePrivateSendSettings = (tenantId: string, patch: PrivateSendSettingsPatch) =>
  operatorFetch<PrivateSendOverview>(`${privateSendPath(tenantId)}/settings`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export type PrivateSendTier = "starter" | "growth" | "custom" | "none";

export const PRIVATE_SEND_TIERS: { id: PrivateSendTier; label: string; cap: number | null }[] = [
  { id: "starter", label: "Starter — 10,000 / month", cap: 10_000 },
  { id: "growth", label: "Growth — 50,000 / month", cap: 50_000 },
  { id: "custom", label: "Custom", cap: null },
  { id: "none", label: "No cap", cap: null },
];

export const PRIVATE_SEND_GRACE_HOURS = [1, 6, 24, 72] as const;

/** Which tier a stored monthly cap belongs to. null = no cap; unknown numbers = custom. */
export function tierForCap(cap: number | null): PrivateSendTier {
  if (cap === null) return "none";
  const match = PRIVATE_SEND_TIERS.find((t) => t.cap === cap);
  return match ? match.id : "custom";
}

/**
 * Cap to save for a tier. Starter/Growth/No cap are fixed; Custom needs a
 * positive whole number typed by the operator. Returns undefined when the
 * custom input is not a valid cap, so callers can refuse to save.
 */
export function capForTier(tier: PrivateSendTier, customInput: string): number | null | undefined {
  if (tier === "none") return null;
  if (tier !== "custom") return PRIVATE_SEND_TIERS.find((t) => t.id === tier)?.cap ?? undefined;
  const trimmed = customInput.trim();
  if (!/^\d+$/.test(trimmed)) return undefined;
  const n = Number(trimmed);
  return Number.isSafeInteger(n) && n > 0 ? n : undefined;
}

/** Share of the monthly cap used, clamped to 0..100. 0 when there is no cap. */
/** Meta reports a day's count a few hours late, so a day's meta_volume can be null. */
export function formatCount(n: number | null): string {
  return n === null ? "—" : n.toLocaleString();
}

/** Same rule the backend uses to block: the larger of reported and Meta's count. */
export function usedTowardCap(reported: number, meta: number | null): number {
  return Math.max(reported, meta ?? 0);
}

export function capUsagePercent(used: number, cap: number | null): number {
  if (cap === null || cap <= 0) return 0;
  return Math.min(100, Math.max(0, Math.round((used / cap) * 100)));
}

/* ------------------------------------------------------------------ *
 * SMS (operator side) -- contract: docs/plans/2026-10-30-sms-api-contract.md
 * ------------------------------------------------------------------ */

export type OperatorSmsChecklist = { dlt: boolean; pe_tm: boolean; sender: boolean };
export type OperatorSmsLedgerEntry = {
  id: string;
  kind: string;
  sms_count: number;
  price_per_sms: number | null;
  buy_rate: number | null;
  amount: number | null;
  expiry_date: string | null;
  note: string | null;
  created_at: string;
};
export type OperatorSmsTemplateRequest = {
  id: string;
  wording: string;
  template_type: string;
  status: "pending" | "in_progress" | "ready" | "rejected" | string;
  reason: string | null;
  created_at: string;
  updated_at: string | null;
};
export type OperatorSmsPayment = {
  id: string;
  amount_rupees: number;
  sms_count: number;
  status: "created" | "paid" | "credited" | "credit_failed" | "amount_mismatch" | "expired" | "cancelled" | string;
  error: string | null;
  created_at: string;
  paid_at: string | null;
  credited_at: string | null;
};
export type OperatorSms = {
  enabled: boolean;
  connected: boolean;
  key_masked: string | null;
  bulk9_username: string | null;
  webhook_registered: boolean;
  price_per_sms: number | null;
  buy_rate: number | null;
  checklist: OperatorSmsChecklist;
  support_contact: string | null;
  balance: { wallet: number; sms_count: number } | null;
  balance_error: string | null;
  ledger: OperatorSmsLedgerEntry[];
  template_requests: OperatorSmsTemplateRequest[];
  payments: OperatorSmsPayment[];
  profit: { sms_sold: number; revenue: number; cost: number; profit: number };
};
export type OperatorSmsStock = {
  sms_count: number | null;
  sms_balance: number | null;
  threshold: number;
  low: boolean;
  error: string | null;
};
export type OperatorSmsSettingsPatch = {
  bulk9_username?: string;
  price_per_sms?: number;
  buy_rate?: number;
  checklist?: OperatorSmsChecklist;
  support_contact?: string;
};

const smsPath = (tenantId: string) => `/api/v1/operator/clients/${tenantId}/sms`;
const smsPost = (tenantId: string, sub: string, body?: unknown) =>
  operatorFetch<OperatorSms>(`${smsPath(tenantId)}/${sub}`, {
    method: "POST",
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });

export const getOperatorSms = (tenantId: string) => operatorFetch<OperatorSms>(smsPath(tenantId));
export const createOperatorSmsAccount = (
  tenantId: string,
  body: { username: string; name: string; email?: string; mobile?: string },
) => smsPost(tenantId, "account", body);
export const putOperatorSmsKey = (tenantId: string, api_key: string) =>
  operatorFetch<OperatorSms>(`${smsPath(tenantId)}/key`, { method: "PUT", body: JSON.stringify({ api_key }) });
export const patchOperatorSmsSettings = (tenantId: string, body: OperatorSmsSettingsPatch) =>
  operatorFetch<OperatorSms>(`${smsPath(tenantId)}/settings`, { method: "PATCH", body: JSON.stringify(body) });
export const enableOperatorSms = (tenantId: string) => smsPost(tenantId, "enable");
export const disableOperatorSms = (tenantId: string) => smsPost(tenantId, "disable");
export const registerOperatorSmsWebhook = (tenantId: string) => smsPost(tenantId, "webhook");
export const creditOperatorSms = (
  tenantId: string,
  body: { kind: "manual_credit" | "bonus"; sms_count: number; price_per_sms?: number; expiry_date?: string; note?: string },
) => smsPost(tenantId, "credit", body);
export const debitOperatorSms = (tenantId: string, body: { sms_count: number; note?: string }) =>
  smsPost(tenantId, "debit", body);
export const updateOperatorSmsTemplateRequest = (
  tenantId: string,
  id: string,
  body: { status: "in_progress" | "ready" | "rejected"; reason?: string },
) =>
  operatorFetch<OperatorSms>(`${smsPath(tenantId)}/template-requests/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
export const retryOperatorSmsCredit = (tenantId: string, paymentId: string) =>
  smsPost(tenantId, `payments/${paymentId}/retry-credit`);
export const getOperatorSmsStock = () => operatorFetch<OperatorSmsStock>("/api/v1/operator/sms/stock");

/** ₹ with 2 decimals (prices pass 4 for sub-paisa rates). */
export function rupees(n: number | null | undefined, decimals = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `₹${n.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
}
