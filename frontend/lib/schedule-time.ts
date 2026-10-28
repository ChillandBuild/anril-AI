/**
 * "When to send" for a template: Send now, or pick a time (always IST, like call wrap-up).
 * The limits mirror backend/app/services/scheduled_templates.py (check_send_at); the server has the last word.
 */
import { fromIstInputs, toIstInputs } from "@/lib/call-wrapup";

export { fromIstInputs, toIstInputs };

const MINUTE = 60_000;
const DAY = 86_400_000;
export const MIN_AHEAD_MS = 5 * MINUTE;
export const MAX_AHEAD_MS = 30 * DAY;

/** What the control holds: date and time are the raw `<input>` strings, read as IST. */
export interface WhenValue {
  mode: "now" | "later";
  date: string;
  time: string;
}

export interface ResolvedWhen {
  mode: "now" | "later";
  /** The send time, when mode is "later" and the inputs hold a real date and time. */
  at: Date | null;
  /** Plain-words problem with the chosen time; empty when it is fine (or when sending now). */
  error: string;
}

export interface QuickSlot {
  key: "hour" | "tomorrow" | "monday";
  label: string;
  at: Date;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function istWeekday(d: Date): number {
  return new Date(`${toIstInputs(d).date}T00:00:00Z`).getUTCDay();
}

/** 10:00 IST on the day `offsetDays` after `now`. IST has no daylight saving, so adding whole days is exact. */
function tenAm(now: Date, offsetDays: number): Date {
  const { date } = toIstInputs(new Date(now.getTime() + offsetDays * DAY));
  return fromIstInputs(date, `${pad(10)}:00`) as Date;
}

export function quickSlots(now: Date): QuickSlot[] {
  const hour = new Date(Math.ceil((now.getTime() + 60 * MINUTE) / (5 * MINUTE)) * 5 * MINUTE);
  const tomorrow = tenAm(now, 1);
  const slots: QuickSlot[] = [
    { key: "hour", label: "In 1 hour", at: hour },
    { key: "tomorrow", label: "Tomorrow", at: tomorrow },
  ];
  for (let i = 1; i <= 7; i++) {
    const day = tenAm(now, i);
    if (istWeekday(day) === 1) {
      if (day.getTime() !== tomorrow.getTime()) slots.push({ key: "monday", label: "Monday", at: day });
      break;
    }
  }
  return slots;
}

export function checkSendAt(at: Date | null, now: Date): string {
  if (!at) return "Pick a date and time.";
  const ahead = at.getTime() - now.getTime();
  if (ahead < MIN_AHEAD_MS) return "Pick a time at least 5 minutes from now.";
  if (ahead > MAX_AHEAD_MS) return "Scheduling goes up to 30 days ahead.";
  return "";
}

export function defaultWhen(now: Date): WhenValue {
  return { mode: "later", ...toIstInputs(tenAm(now, 1)) };
}

export function resolveWhen(value: WhenValue, now: Date): ResolvedWhen {
  if (value.mode === "now") return { mode: "now", at: null, error: "" };
  const at = fromIstInputs(value.date, value.time);
  return { mode: "later", at, error: checkSendAt(at, now) };
}

/** The earliest and latest date the date field should offer. */
export function dateBounds(now: Date): { min: string; max: string } {
  return { min: toIstInputs(now).date, max: toIstInputs(new Date(now.getTime() + MAX_AHEAD_MS)).date };
}

const DAY_FORMAT = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", weekday: "short", day: "numeric", month: "short" });
const TIME_FORMAT = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", hour12: true });

/** "10:00 AM" */
export function clockOf(d: Date): string {
  return TIME_FORMAT.format(d).replace(/\s/g, " ").toUpperCase();
}

/** "Thu 29 Oct, 10:00 AM": always the full date, because this is the confirmation of when it goes out. */
export function formatSendTime(d: Date): string {
  const p: Record<string, string> = {};
  for (const part of DAY_FORMAT.formatToParts(d)) p[part.type] = part.value;
  return `${p.weekday} ${p.day} ${p.month}, ${clockOf(d)}`;
}

export function untilSend(at: Date, now: Date): string {
  const minutes = Math.round((at.getTime() - now.getTime()) / MINUTE);
  if (minutes < 60) return `in ${Math.max(minutes, 0)} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `in ${hours} h`;
  return `in ${Math.round(hours / 24)} days`;
}
