import { apiFetch } from "@/lib/api";

/** Settings > Calling rules (v9.2 Call IQ): hours, limits, hidden numbers, SIM or cloud per person, leave. */

export type CallRules = {
  calling_hours_on: boolean;
  calling_start: string; // "09:00", India time
  calling_end: string;
  daily_limit_on: boolean;
  daily_limit: number;
  break_limit_minutes: number; // 0 = off
  hide_numbers_for_callers: boolean;
};

export type CallingMode = "business_default" | "sim" | "cloud";

export type RulesPerson = {
  id: string;
  name: string | null;
  status: string | null;
  calling_mode: CallingMode;
  effective_mode: "sim" | "cloud";
  leave_from: string | null;
  leave_to: string | null;
  leave_reason: string | null;
  on_leave: boolean;
};

export type RulesPeople = { business_mode: "sim" | "cloud"; callers: RulesPerson[] };

export type LeaveResult = {
  moved: number;
  to: { name: string; count: number }[];
  no_one_free: boolean;
  starts_later: boolean;
};

const BASE = "/api/v1/call-iq-settings";

export const callRulesApi = {
  rules: () => apiFetch<CallRules>(`${BASE}/rules`),
  /** Needs permission to change settings. Answers with the saved rules. */
  saveRules: (body: CallRules) => apiFetch<CallRules>(`${BASE}/rules`, { method: "PUT", body: JSON.stringify(body) }),
  people: () => apiFetch<RulesPeople>(`${BASE}/callers`),
  setMode: (id: string, mode: CallingMode) =>
    apiFetch<{ caller_id: string; calling_mode: CallingMode }>(`${BASE}/callers/${id}/mode`, {
      method: "PUT",
      body: JSON.stringify({ mode }),
    }),
  /** Needs permission to manage the team. Open leads move to the others on the first day. */
  startLeave: (id: string, body: { from: string; to: string; reason?: string }) =>
    apiFetch<LeaveResult>(`${BASE}/callers/${id}/leave`, { method: "POST", body: JSON.stringify(body) }),
  endLeave: (id: string) => apiFetch<{ caller_id: string; on_leave: boolean }>(`${BASE}/callers/${id}/leave`, { method: "DELETE" }),
};
