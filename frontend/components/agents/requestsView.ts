import type { CompanionRequestKind, CompanionRequestLog } from "@/lib/api";

export const KIND_LABEL: Record<CompanionRequestKind, string> = {
  chat: "Chat (server)",
  chat_continue: "Tool answer (server)",
  widget_session: "Widget opened",
  widget_chat: "Chat (widget)",
  widget_continue: "Tool answer (widget)",
};

/**
 * One bar per day for the last `days` days, oldest first, with empty days filled in.
 * Example: days=3 on 9 Nov with 2 ok + 1 error on 8 Nov →
 * [{date:"2026-11-07",ok:0,error:0}, {date:"2026-11-08",ok:2,error:1}, {date:"2026-11-09",ok:0,error:0}].
 */
export function dailyBars(daily: CompanionRequestLog["daily"], days: number, today = new Date()) {
  const byDate = new Map(daily.map((d) => [d.date, d]));
  const out: { date: string; ok: number; error: number }[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - i));
    const key = d.toISOString().slice(0, 10);
    out.push({ date: key, ok: byDate.get(key)?.ok ?? 0, error: byDate.get(key)?.error ?? 0 });
  }
  return out;
}

/** The tallest bar, never 0 (so empty charts don't divide by zero). */
export function barMax(bars: { ok: number; error: number }[]): number {
  return Math.max(1, ...bars.map((b) => b.ok + b.error));
}

/** Error share as a whole percent. 3 of 120 → "2.5%" rounds to "3%"; 0 total → "0%". */
export function errorRate(errors: number, total: number): string {
  return total ? `${Math.round((errors / total) * 100)}%` : "0%";
}
