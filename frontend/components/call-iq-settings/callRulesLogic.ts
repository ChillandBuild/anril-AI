import type { CallRules, CallingMode, LeaveResult, RulesPerson } from "@/lib/callRulesApi";

export const MAX_DAILY_LIMIT = 1000;
export const MAX_BREAK_MINUTES = 240;

/** "09:00" -> "9 AM", "21:30" -> "9:30 PM". Anything else comes back unchanged. */
export function clockWords(hhmm: string): string {
  const m = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(hhmm);
  if (!m) return hhmm;
  const h = Number(m[1]);
  const mins = m[2];
  const h12 = h % 12 || 12;
  const suffix = h < 12 ? "AM" : "PM";
  return mins === "00" ? `${h12} ${suffix}` : `${h12}:${mins} ${suffix}`;
}

/** A plain-words problem with the rules, or null when they can be saved. */
export function rulesProblem(r: CallRules): string | null {
  if (r.calling_hours_on && r.calling_end <= r.calling_start) return "Calling hours must end after they start.";
  if (!Number.isInteger(r.daily_limit) || r.daily_limit < 1 || r.daily_limit > MAX_DAILY_LIMIT)
    return `The daily limit must be between 1 and ${MAX_DAILY_LIMIT} calls.`;
  if (!Number.isInteger(r.break_limit_minutes) || r.break_limit_minutes < 0 || r.break_limit_minutes > MAX_BREAK_MINUTES)
    return `The break limit must be between 0 and ${MAX_BREAK_MINUTES} minutes (0 switches it off).`;
  return null;
}

export function sameRules(a: CallRules, b: CallRules): boolean {
  return (Object.keys(a) as (keyof CallRules)[]).every((k) => a[k] === b[k]);
}

/** Digits only, or null when the box is empty. */
export function wholeNumber(text: string): number | null {
  const digits = text.replace(/\D/g, "");
  return digits === "" ? null : Number(digits);
}

export const MODE_CHOICES: { value: CallingMode; label: string }[] = [
  { value: "business_default", label: "Same as the business" },
  { value: "sim", label: "Own SIM (phone app)" },
  { value: "cloud", label: "Office number (cloud)" },
];

export function modeWords(mode: "sim" | "cloud"): string {
  return mode === "sim" ? "Own SIM" : "Office number";
}

/** "5 Dec 2026". Dates come as YYYY-MM-DD and are never shifted by the time zone. */
export function dayLabel(iso: string | null): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  if (!m) return "";
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(m[3])} ${months[Number(m[2]) - 1]} ${m[1]}`;
}

export function leaveLine(p: RulesPerson): string | null {
  if (!p.leave_from || !p.leave_to) return null;
  const range = p.leave_from === p.leave_to ? dayLabel(p.leave_from) : `${dayLabel(p.leave_from)} to ${dayLabel(p.leave_to)}`;
  return `${p.on_leave ? "On leave" : "Leave planned"}: ${range}${p.leave_reason ? ` (${p.leave_reason})` : ""}`;
}

/** What to tell the owner after starting a leave. */
export function leaveResultLine(name: string, r: LeaveResult): string {
  if (r.starts_later) return `Leave saved. ${name}'s open leads move to the others on the first day.`;
  if (r.no_one_free) return `Leave saved, but no other telecaller is free, so ${name}'s leads stayed with ${name}.`;
  if (r.moved === 0) return `Leave saved. ${name} had no open leads to hand over.`;
  const who = r.to.map((t) => `${t.name} ${t.count}`).join(", ");
  return `Leave saved. ${r.moved} open ${r.moved === 1 ? "lead was" : "leads were"} given to: ${who}.`;
}
