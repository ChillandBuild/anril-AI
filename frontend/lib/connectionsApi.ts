import { apiFetch } from "@/lib/api";

/** One line of Meta's own bill for this month. */
export type ChargeRow = { key: string; label: string; messages: number; cost: number };

export type ChargesAvailable = {
  available: true;
  month: string;
  currency: string;
  rows: ChargeRow[];
  total: { messages: number; cost: number };
  gst_note: string;
};
export type ChargesNotAvailable = { available: false; reason: string };
export type MetaCharges = ChargesAvailable | ChargesNotAvailable;

export type AiReplies = { used: number; included: number | null; pct: number | null };
export type DailyLimit = { tier: number | null; link: string };

export type MetaChargesResponse = { charges: MetaCharges; ai_replies: AiReplies; daily_limit: DailyLimit };

export type CallingProvider = "sim" | "cloud";
export type CallingPerson = { name: string; ready: boolean; detail: string };
export type CallingOverview = {
  available: boolean;
  provider: CallingProvider;
  people: CallingPerson[];
  rules: { daily_target_calls: number; calling_hours: string };
};

export type ReachLimit = { weekly_limit: number; default: number; min: number; max: number };

export const connectionsApi = {
  metaCharges: () => apiFetch<MetaChargesResponse>("/api/v1/connections/meta-charges"),
  calling: () => apiFetch<CallingOverview>("/api/v1/connections/calling"),
  reachLimit: () => apiFetch<ReachLimit>("/api/v1/connections/reach-limit"),
  saveReachLimit: (weekly_limit: number) =>
    apiFetch<{ weekly_limit: number }>("/api/v1/connections/reach-limit", {
      method: "PUT",
      body: JSON.stringify({ weekly_limit }),
    }),
};
