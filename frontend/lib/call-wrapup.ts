/**
 * Call wrap-up v2: the one list of options, labels, colours and IST time helpers every
 * screen uses (spec: docs/superpowers/specs/2026-09-27-call-wrapup-v2-design.md).
 * Times are always tenant-local IST, computed with a fixed +05:30 offset so a telecaller
 * whose laptop is set to another zone still gets "Tomorrow 10 AM" in IST.
 */
import type {
  CallConnect, CallResult, CallTemperature, LeadCallStatus, NoConnect, OutcomeReason, PreferredLanguage,
} from "@/lib/api";

export type Tone = "won" | "hot" | "warm" | "cold" | "callback" | "lost" | "blocked" | "attention" | "missed" | "neutral";

export const TONE_CHIP: Record<Tone, string> = {
  won: "bg-emerald-50 text-emerald-700 border-emerald-200",
  hot: "bg-orange-50 text-orange-700 border-orange-200",
  warm: "bg-amber-50 text-amber-700 border-amber-200",
  cold: "bg-sky-50 text-sky-700 border-sky-200",
  callback: "bg-violet-50 text-violet-700 border-violet-200",
  lost: "bg-[#f8fafc] text-[#475569] border-[#e2e8f0]",
  blocked: "bg-red-50 text-red-700 border-red-200",
  attention: "bg-indigo-50 text-indigo-700 border-indigo-200",
  missed: "bg-rose-50 text-rose-700 border-rose-200",
  neutral: "bg-primary-light text-primary border-primary-muted",
};

export const TONE_DOT: Record<Tone, string> = {
  won: "bg-emerald-500", hot: "bg-orange-500", warm: "bg-amber-400", cold: "bg-sky-400",
  callback: "bg-violet-500", lost: "bg-[#94a3b8]", blocked: "bg-red-600", attention: "bg-indigo-500",
  missed: "bg-rose-400", neutral: "bg-primary",
};

export const TONE_HEX: Record<Tone, string> = {
  won: "#10b981", hot: "#f97316", warm: "#f59e0b", cold: "#38bdf8", callback: "#8b5cf6",
  lost: "#94a3b8", blocked: "#dc2626", attention: "#6366f1", missed: "#fb7185", neutral: "var(--primary-400)",
};

export interface ConnectOption { value: CallConnect; label: string; hint: string }

export const CONNECT_OPTIONS: ConnectOption[] = [
  { value: "connected", label: "Connected", hint: "Spoke to the customer" },
  { value: "not_picked", label: "Not picked", hint: "Rang, no answer" },
  { value: "busy", label: "Busy", hint: "Line busy or cut" },
  { value: "switched_off", label: "Switched off", hint: "Not reachable" },
];
export const NO_CONNECTS: NoConnect[] = ["not_picked", "busy", "switched_off"];

export interface ResultOption {
  value: CallResult;
  emoji: string;
  label: string;
  time: "required" | "optional" | null;
  timeLabel: string;
  notes: boolean;
  tone: Tone;
}

export const RESULT_OPTIONS: ResultOption[] = [
  { value: "interested_booked", emoji: "👍", label: "Interested, next step booked", time: "required", timeLabel: "Next step", notes: true, tone: "hot" },
  { value: "interested_needs_time", emoji: "🤔", label: "Interested, needs time or more information", time: "required", timeLabel: "Follow up", notes: true, tone: "warm" },
  { value: "maybe_later", emoji: "🙂", label: "Maybe later", time: "optional", timeLabel: "Follow up (optional)", notes: false, tone: "cold" },
  { value: "call_later", emoji: "📅", label: "Call later (customer asked)", time: "required", timeLabel: "Call back at", notes: false, tone: "callback" },
  { value: "converted", emoji: "🎉", label: "Converted", time: null, timeLabel: "", notes: true, tone: "won" },
  { value: "not_interested", emoji: "👎", label: "Not interested", time: null, timeLabel: "", notes: false, tone: "lost" },
  { value: "disqualified", emoji: "🚫", label: "Not a fit", time: null, timeLabel: "", notes: false, tone: "lost" },
  { value: "wrong_number", emoji: "❓", label: "Wrong number", time: null, timeLabel: "", notes: false, tone: "blocked" },
  { value: "language_barrier", emoji: "🗣️", label: "Language barrier", time: null, timeLabel: "", notes: false, tone: "attention" },
  { value: "do_not_call", emoji: "⛔", label: "Do not call", time: null, timeLabel: "", notes: false, tone: "blocked" },
];

export function resultOption(value: CallResult): ResultOption {
  return RESULT_OPTIONS.find((o) => o.value === value) as ResultOption;
}

export const NOT_INTERESTED_REASONS: { value: OutcomeReason; label: string }[] = [
  { value: "price", label: "Price" },
  { value: "already_bought", label: "Already bought" },
  { value: "no_need", label: "No need" },
  { value: "other", label: "Other" },
];
export const DISQUALIFIED_REASONS: { value: OutcomeReason; label: string }[] = [
  { value: "never_enquired", label: "Never enquired" },
  { value: "not_a_fit", label: "Not a fit" },
  { value: "not_decision_maker", label: "Not the decision maker" },
];
export const LANGUAGE_OPTIONS: { value: PreferredLanguage; label: string }[] = [
  { value: "tamil", label: "Tamil" },
  { value: "english", label: "English" },
  { value: "hindi", label: "Hindi" },
  { value: "telugu", label: "Telugu" },
  { value: "malayalam", label: "Malayalam" },
  { value: "kannada", label: "Kannada" },
  { value: "other", label: "Other" },
];

const CONNECT_LABEL: Record<CallConnect, string> = {
  connected: "Connected", not_picked: "Not picked", busy: "Busy", switched_off: "Switched off",
};

/** The one thing to show for a call: its result, else whether it connected. */
export function callResultKey(log: { outcome?: string | null; manual_status?: string | null }): string | null {
  return log.outcome || log.manual_status || null;
}

export function callResultLabel(key: string | null | undefined): string | null {
  if (!key) return null;
  const option = RESULT_OPTIONS.find((o) => o.value === key);
  if (option) return option.label;
  return CONNECT_LABEL[key as CallConnect] ?? null;
}

export function callResultTone(key: string | null | undefined): Tone {
  const option = RESULT_OPTIONS.find((o) => o.value === key);
  if (option) return option.tone;
  if (NO_CONNECTS.includes(key as NoConnect)) return "missed";
  return "neutral";
}

export const LEAD_CALL_STATUSES: LeadCallStatus[] = [
  "new", "trying", "hot", "warm", "cold", "callback", "language_barrier", "converted",
  "not_interested", "disqualified", "wrong_number", "dnc", "unreachable",
];

export const LEAD_STATUS_LABEL: Record<LeadCallStatus, string> = {
  new: "New", trying: "Trying", unreachable: "Unreachable", hot: "Hot", warm: "Warm", cold: "Cold",
  callback: "Call later", converted: "Converted", not_interested: "Not interested",
  disqualified: "Not a fit", wrong_number: "Wrong number", language_barrier: "Language barrier", dnc: "Do not call",
};

const LEAD_STATUS_TONE: Record<LeadCallStatus, Tone> = {
  new: "neutral", trying: "missed", unreachable: "lost", hot: "hot", warm: "warm", cold: "cold",
  callback: "callback", converted: "won", not_interested: "lost", disqualified: "lost",
  wrong_number: "blocked", language_barrier: "attention", dnc: "blocked",
};

export function leadStatusTone(status: LeadCallStatus | null | undefined): Tone {
  return status ? LEAD_STATUS_TONE[status] : "neutral";
}

const CLOSED: LeadCallStatus[] = ["converted", "not_interested", "disqualified", "wrong_number", "dnc", "unreachable"];
const WORKING: LeadCallStatus[] = ["trying", "hot", "warm", "cold", "language_barrier"];

export function isClosedLeadStatus(status: LeadCallStatus | null | undefined): boolean {
  return !!status && CLOSED.includes(status);
}

export function isWorkingLeadStatus(status: LeadCallStatus | null | undefined): boolean {
  return !!status && WORKING.includes(status);
}

export const TEMPERATURE_LABEL: Record<CallTemperature, string> = { hot: "Hot", warm: "Warm", cold: "Cold" };

// ── IST time helpers ──────────────────────────────────────────────
const IST_OFFSET_MS = 330 * 60_000;
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function istFields(d: Date) {
  const t = new Date(d.getTime() + IST_OFFSET_MS);
  return { y: t.getUTCFullYear(), mo: t.getUTCMonth(), d: t.getUTCDate(), h: t.getUTCHours(), mi: t.getUTCMinutes() };
}

function istDate(y: number, mo: number, d: number, h: number, mi: number): Date {
  return new Date(Date.UTC(y, mo, d, h, mi) - IST_OFFSET_MS);
}

export type QuickTimeKey = "in_1_hour" | "this_evening" | "tomorrow_10am";

export function quickTimes(now: Date): { key: QuickTimeKey; label: string; at: Date; disabled: boolean }[] {
  const f = istFields(now);
  const evening = istDate(f.y, f.mo, f.d, 18, 0);
  return [
    { key: "in_1_hour", label: "In 1 hour", at: new Date(now.getTime() + 3_600_000), disabled: false },
    { key: "this_evening", label: "This evening 6 PM", at: evening, disabled: evening.getTime() <= now.getTime() },
    { key: "tomorrow_10am", label: "Tomorrow 10 AM", at: istDate(f.y, f.mo, f.d + 1, 10, 0), disabled: false },
  ];
}

export function toIstInputs(d: Date): { date: string; time: string } {
  const f = istFields(d);
  return { date: `${f.y}-${pad(f.mo + 1)}-${pad(f.d)}`, time: `${pad(f.h)}:${pad(f.mi)}` };
}

export function fromIstInputs(date: string, time: string): Date | null {
  const dm = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  const tm = /^(\d{2}):(\d{2})$/.exec(time);
  if (!dm || !tm) return null;
  return istDate(Number(dm[1]), Number(dm[2]) - 1, Number(dm[3]), Number(tm[1]), Number(tm[2]));
}

export function formatIstWhen(d: Date, now: Date): string {
  const a = istFields(d);
  const b = istFields(now);
  const dayDiff = Math.round((Date.UTC(a.y, a.mo, a.d) - Date.UTC(b.y, b.mo, b.d)) / 86_400_000);
  const clock = `${a.h % 12 || 12}:${pad(a.mi)} ${a.h < 12 ? "AM" : "PM"}`;
  if (dayDiff === 0) return `Today, ${clock}`;
  if (dayDiff === 1) return `Tomorrow, ${clock}`;
  const weekday = WEEKDAYS[new Date(Date.UTC(a.y, a.mo, a.d)).getUTCDay()];
  return `${weekday} ${a.d} ${MONTHS[a.mo]}, ${clock}`;
}
