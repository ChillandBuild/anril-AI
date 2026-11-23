import { apiFetch } from "@/lib/api";

/**
 * Call IQ reports: Live, Evaluation, Results (v9.2 #21). Every call is /api/v1/call-iq/...
 * Readers are defensive: a key the server leaves out is simply not shown (revenue_paise is left out
 * for people without deals.view, and the screens then hide the money column).
 */

// ─── Live ─────────────────────────────────────────────────────────────────────

export type LiveState = "on_call" | "on_break" | "idle" | "off";

export interface LivePerson {
  caller_id: string;
  name: string;
  state: LiveState;
  since: string | null;
  calls_today: number;
  break_minutes_today: number;
}

export interface LiveResponse { callers: LivePerson[]; as_of?: string }

export const LIVE_REFRESH_MS = 20_000;

export function getLive(): Promise<LiveResponse> {
  return apiFetch<LiveResponse>("/api/v1/call-iq/live");
}

const STATE_LABELS: Record<LiveState, string> = {
  on_call: "On a call",
  on_break: "On a break",
  idle: "Free",
  off: "Not logged in",
};

export function stateLabel(state: string): string {
  return STATE_LABELS[state as LiveState] ?? "Not logged in";
}

const STATE_ORDER: Record<LiveState, number> = { on_call: 0, idle: 1, on_break: 2, off: 3 };

/** On a call first, then free, then on a break, then not logged in; names A to Z inside each group. */
export function sortLive(people: LivePerson[]): LivePerson[] {
  return [...people].sort(
    (a, b) => (STATE_ORDER[a.state] ?? 9) - (STATE_ORDER[b.state] ?? 9) || a.name.localeCompare(b.name),
  );
}

export function countByState(people: LivePerson[]): Record<LiveState, number> {
  const out: Record<LiveState, number> = { on_call: 0, on_break: 0, idle: 0, off: 0 };
  for (const p of people) out[(p.state in out ? p.state : "off") as LiveState] += 1;
  return out;
}

export function minutesText(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || Number.isNaN(minutes)) return "—";
  const m = Math.max(0, Math.round(minutes));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h}h ${r}m` : `${h}h`;
}

/** "for 12 min" while on a call or break, "since 10:02 AM" for free / not logged in. "" when unknown. */
export function sinceText(person: Pick<LivePerson, "state" | "since">, now: Date = new Date()): string {
  if (!person.since) return "";
  const at = new Date(person.since);
  if (Number.isNaN(at.getTime())) return "";
  if (person.state === "on_call" || person.state === "on_break") {
    return `for ${minutesText((now.getTime() - at.getTime()) / 60_000)}`;
  }
  const clock = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", hour12: true }).format(at);
  const day = (d: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(d);
  if (day(at) === day(now)) return `since ${clock.toUpperCase()}`;
  const date = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short" }).format(at);
  return `since ${date}, ${clock.toUpperCase()}`;
}

// ─── Evaluation ───────────────────────────────────────────────────────────────

export type EvaluationPeriod = "7d" | "30d";

export interface EvaluationPerson {
  caller_id: string;
  name: string;
  calls_scored: number;
  avg_score: number | null;
  best: number | null;
  worst: number | null;
  top_weak_points: string[];
}

export interface LowestCall {
  call_log_id: string;
  caller_id: string;
  caller_name: string | null;
  score: number;
  at: string | null;
  lead_id: string | null;
  lead_name: string | null;
}

export interface EvaluationResponse {
  period: EvaluationPeriod;
  available: boolean;
  message?: string;
  callers: EvaluationPerson[];
  lowest_calls: LowestCall[];
}

export const EVALUATION_PERIODS: { value: EvaluationPeriod; label: string }[] = [
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
];

export function getEvaluation(period: EvaluationPeriod): Promise<EvaluationResponse> {
  return apiFetch<EvaluationResponse>(`/api/v1/call-iq/evaluation?period=${period}`);
}

export type ScoreTone = "good" | "ok" | "low" | "none";

/** 75 and up is good, 50 to 74 is okay, below 50 needs help. */
export function scoreTone(score: number | null | undefined): ScoreTone {
  if (score === null || score === undefined || Number.isNaN(score)) return "none";
  if (score >= 75) return "good";
  if (score >= 50) return "ok";
  return "low";
}

export function scoreText(score: number | null | undefined): string {
  if (score === null || score === undefined || Number.isNaN(score)) return "—";
  return Number.isInteger(score) ? String(score) : score.toFixed(1);
}

/** The call review page for one call. */
export function callReviewHref(callLogId: string): string {
  return `/dashboard/notes?call=${encodeURIComponent(callLogId)}`;
}

// ─── Results ──────────────────────────────────────────────────────────────────

export type ResultsPeriod = "today" | "7d" | "30d";

export interface ResultsRow {
  calls: number;
  connected: number;
  /** Visits booked by phone. Left out by an older server. */
  visits?: number;
  orders: number;
  revenue_paise?: number;
}

export interface ResultsPerson extends ResultsRow { caller_id: string; name: string }

export interface ResultsResponse {
  period: ResultsPeriod;
  callers: ResultsPerson[];
  totals: ResultsRow;
}

export const RESULTS_PERIODS: { value: ResultsPeriod; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
];

export function getResults(period: ResultsPeriod): Promise<ResultsResponse> {
  return apiFetch<ResultsResponse>(`/api/v1/call-iq/results?period=${period}`);
}

/** The money column is shown only when the server sent money. */
export function showsMoney(data: ResultsResponse | null | undefined): boolean {
  return !!data && typeof data.totals?.revenue_paise === "number";
}

/** "3 of 4 picked up", or "No calls". */
export function pickedUpText(row: Pick<ResultsRow, "calls" | "connected">): string {
  if (!row.calls) return "No calls";
  return `${row.connected} of ${row.calls} picked up`;
}

// ─── Who may open which screen ────────────────────────────────────────────────

/** Same rule as the server: the owner passes; a .manage permission also counts as .view. */
export function hasView(role: string | null, permissions: string[], permission: string): boolean {
  if (role === "owner") return true;
  if (permissions.includes(permission)) return true;
  return permission.endsWith(".view") && permissions.includes(`${permission.slice(0, -5)}.manage`);
}

export function canOpenLive(role: string | null, permissions: string[]): boolean {
  return hasView(role, permissions, "team.view") || hasView(role, permissions, "telecalling.view");
}

export function canOpenTeamReports(role: string | null, permissions: string[]): boolean {
  return hasView(role, permissions, "team.view");
}
