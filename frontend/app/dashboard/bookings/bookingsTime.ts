// IST date/time helpers for Bookings. India has no daylight saving, so a fixed +05:30 offset is exact.
// Dates are "YYYY-MM-DD" strings in IST; times of day are minutes since IST midnight.

export const IST_OFFSET_MIN = 330;
export const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"] as const;
export const DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

export function isDateString(v: unknown): v is string {
  if (typeof v !== "string" || !DATE_RE.test(v)) return false;
  const [y, m, d] = v.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
}

function utcMs(date: string): number {
  const [y, m, d] = date.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

/** IST date and minutes-of-day for an instant; null when the stamp can't be read. */
export function istOf(iso: string): { date: string; minutes: number } | null {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return null;
  const d = new Date(ms + IST_OFFSET_MIN * 60_000);
  return { date: d.toISOString().slice(0, 10), minutes: d.getUTCHours() * 60 + d.getUTCMinutes() };
}

/** The instant (ISO, UTC) for an IST date and minutes since midnight. */
export function toIso(date: string, minutes: number): string {
  return new Date(utcMs(date) + minutes * 60_000 - IST_OFFSET_MIN * 60_000).toISOString();
}

/** Minutes from IST midnight of `date` to `iso`; can be negative or past 1440 for another day. */
export function minutesOnDay(iso: string, date: string): number {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return NaN;
  return (ms - (utcMs(date) - IST_OFFSET_MIN * 60_000)) / 60_000;
}

export function todayIst(now: Date = new Date()): string {
  return new Date(now.getTime() + IST_OFFSET_MIN * 60_000).toISOString().slice(0, 10);
}

export function addDays(date: string, n: number): string {
  return new Date(utcMs(date) + n * 86_400_000).toISOString().slice(0, 10);
}

/** 0 = Monday ... 6 = Sunday (the hours keys). */
export function weekdayIndex(date: string): number {
  return (new Date(utcMs(date)).getUTCDay() + 6) % 7;
}

export function mondayOf(date: string): string {
  return addDays(date, -weekdayIndex(date));
}

export function hhmmToMinutes(v: string): number | null {
  const m = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(v);
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

export function minutesToHhmm(min: number): string {
  const m = Math.max(0, Math.min(1439, Math.round(min)));
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

/** "4:00 PM" from minutes since midnight. */
export function clock(min: number): string {
  const total = ((Math.round(min) % 1440) + 1440) % 1440;
  const h = Math.floor(total / 60);
  const mm = String(total % 60).padStart(2, "0");
  return `${h % 12 === 0 ? 12 : h % 12}:${mm} ${h < 12 ? "AM" : "PM"}`;
}

export function formatTime(iso: string): string {
  const p = istOf(iso);
  return p ? clock(p.minutes) : "";
}

/** "Thu 28 Nov" */
export function formatDay(date: string): string {
  if (!isDateString(date)) return "";
  const d = Number(date.slice(8));
  return `${DAY_SHORT[weekdayIndex(date)]} ${d} ${MONTHS[Number(date.slice(5, 7)) - 1]}`;
}

/** "Thu 28 Nov, 4:00 PM" */
export function formatDateTime(iso: string): string {
  const p = istOf(iso);
  return p ? `${formatDay(p.date)}, ${clock(p.minutes)}` : "";
}

/** "Today", "Tomorrow", "Yesterday" or "Thu 28 Nov". */
export function dayLabel(date: string, today: string): string {
  if (date === today) return "Today";
  if (date === addDays(today, 1)) return "Tomorrow";
  if (date === addDays(today, -1)) return "Yesterday";
  return formatDay(date);
}
