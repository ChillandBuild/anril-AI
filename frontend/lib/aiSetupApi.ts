import { apiFetch } from "@/lib/api";

/** Anril Setup: Couldn't answer, AI report card, thumbs-down on AI replies, Questions & scoring (read-only). */

export type Period = "7d" | "30d" | "90d";
export const PERIODS: { value: Period; label: string }[] = [
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
];

export type CouldntAnswerRow = { question: string; count: number; last_at: string; sample_lead_ids: string[] };
export type FixThis = { kind: string; text: string; href: string };
export type ReportCard = {
  period: { days: number; from: string; to: string };
  chats: number;
  handled_alone_pct: number | null;
  passed_to_person: number;
  wrong_answers: number;
  revenue_from_ai_paise?: number;
  money_hidden?: boolean;
  fix_these: FixThis[];
};
export type ScoringLevel = { key: string; label: string; points: string; meaning: string; your_examples: string[] };
export type ScoringView = {
  read_only: boolean;
  note: string;
  questions: string[];
  questions_note: string;
  levels: ScoringLevel[];
  not_interested_words: string[];
};
export type FeedbackReason = "wrong" | "rude" | "too_long" | "other";
export const FEEDBACK_REASONS: { value: FeedbackReason; label: string }[] = [
  { value: "wrong", label: "Wrong answer" },
  { value: "rude", label: "Rude" },
  { value: "too_long", label: "Too long" },
  { value: "other", label: "Something else" },
];

const BASE = "/api/v1/ai-setup";

export const aiSetupApi = {
  couldntAnswer: (period: Period) =>
    apiFetch<{ period: { days: number }; questions: CouldntAnswerRow[] }>(`${BASE}/couldnt-answer?period=${period}`),
  answer: (question: string, answer: string) =>
    apiFetch<{ marked_answered: number }>(`${BASE}/couldnt-answer/answer`, {
      method: "POST", body: JSON.stringify({ question, answer }),
    }),
  reportCard: (period: Period) => apiFetch<ReportCard>(`${BASE}/report-card?period=${period}`),
  scoring: () => apiFetch<ScoringView>(`${BASE}/scoring`),
  thumbsDown: (messageId: string, reason: FeedbackReason, note?: string) =>
    apiFetch<{ ok: boolean }>(`${BASE}/reply-feedback`, {
      method: "POST", body: JSON.stringify({ message_id: messageId, reason, note: note?.trim() || null }),
    }),
  undoThumbsDown: (messageId: string) =>
    apiFetch<{ ok: boolean }>(`${BASE}/reply-feedback/${encodeURIComponent(messageId)}`, { method: "DELETE" }),
};

/** "3 times" / "once". */
export function timesLabel(count: number): string {
  return count === 1 ? "asked once" : `asked ${count} times`;
}

/** "62%" or a dash when there were no chats to measure. */
export function percentLabel(pct: number | null | undefined): string {
  return pct === null || pct === undefined ? "-" : `${Math.round(pct)}%`;
}

/** Paise to "Rs 1,18,000"-style rupees with Indian grouping. */
export function rupees(paise: number): string {
  return `₹${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(Math.round(paise / 100))}`;
}

/** A fix link is only followed when it stays inside the dashboard. */
export function safeFixHref(href: string): string {
  return href.startsWith("/dashboard/") && !href.startsWith("//") ? href : "/dashboard/brain";
}

/** The question a Fix link pre-filled (?question=...), trimmed and capped. */
export function questionFromSearch(search: string): string {
  return (new URLSearchParams(search).get("question") ?? "").trim().slice(0, 300);
}

/** Same wording once case, punctuation and spaces are ignored (the server groups the same way). */
export function sameQuestion(a: string, b: string): boolean {
  const norm = (t: string) => t.toLowerCase().replace(/[!-/:-@[-`{-~‘’“”…]/g, " ").replace(/\s+/g, " ").trim();
  return norm(a) === norm(b);
}
