// Pure rules for the Bookings screens: grid placement, drag snapping, hours validation,
// flags on a booking, phone checks. No React, so it is unit-tested.
import type { Booking, BookingResource, BookingSettings, BookingStatus, FreeRanges, FreeTime, HoursBlock, VisitOutcome, WeekHours } from "@/lib/bookingsApi";
import { hhmmToMinutes, minutesOnDay, minutesToHhmm, weekdayIndex } from "./bookingsTime";

export const STEP_MIN = 15;
export const PX_PER_MIN = 1.6;
export const DEFAULT_GRID = { startMin: 9 * 60, endMin: 20 * 60 };

// ── Status ───────────────────────────────────────────────────────────────────

export const STATUS_LABEL: Record<BookingStatus, string> = {
  held: "Waiting for advance",
  booked: "Booked",
  came: "Came",
  no_show: "Didn't come",
  cancelled: "Cancelled",
};

/** Block colours on the timeline and chips in lists. */
export const STATUS_CLASS: Record<BookingStatus, string> = {
  held: "border-amber-300 bg-amber-50 text-amber-900",
  booked: "border-sky-300 bg-sky-50 text-sky-900",
  came: "border-emerald-300 bg-emerald-50 text-emerald-900",
  no_show: "border-rose-300 bg-rose-50 text-rose-900",
  cancelled: "border-slate-300 bg-slate-100 text-slate-600",
};

/** Held bookings may be released after about 15 minutes, so they are drawn lighter and hatched. */
export const HELD_HATCH_STYLE = {
  backgroundImage: "repeating-linear-gradient(135deg, rgba(180,83,9,0.12) 0 6px, transparent 6px 12px)",
} as const;

export function isLive(status: BookingStatus): boolean {
  return status === "held" || status === "booked" || status === "came";
}

/** Booked and held bookings can still be moved or cancelled. */
export function isOpen(status: BookingStatus): boolean {
  return status === "held" || status === "booked";
}

// ── Flags ────────────────────────────────────────────────────────────────────

export type FlagTone = "amber" | "red" | "green" | "slate";
export interface BookingFlag {
  key: "phone" | "waiting_confirm" | "advance_paid" | "advance_due" | "call_now" | "said_yes";
  label: string;
  tone: FlagTone;
}

export const FLAG_CLASS: Record<FlagTone, string> = {
  amber: "bg-amber-100 text-amber-900",
  red: "bg-rose-100 text-rose-800",
  green: "bg-emerald-100 text-emerald-800",
  slate: "bg-slate-100 text-slate-700",
};

/** ₹199 for whole rupees, ₹199.50 when there are paise. */
export function rupees(paise: number): string {
  const whole = Math.floor(Math.abs(paise) / 100);
  const part = Math.abs(paise) % 100;
  const sign = paise < 0 ? "-" : "";
  const text = whole.toLocaleString("en-IN");
  return `${sign}₹${text}${part ? "." + String(part).padStart(2, "0") : ""}`;
}

/** Two times are the same moment. Never compare the strings: "+05:30" and "Z" spell one moment two ways. */
export function sameInstant(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false;
  const x = Date.parse(a);
  const y = Date.parse(b);
  return !Number.isNaN(x) && !Number.isNaN(y) && x === y;
}

/**
 * The small flags on a booking. The amount is only in the words when the server sent it
 * (it leaves money out for people without orders access).
 */
export function bookingFlags(b: Pick<Booking, "status" | "phone_checked" | "advance_paid" | "advance_paise" | "call_now" | "confirmed_at"> & { advance_needed?: boolean; source?: Booking["source"] }): BookingFlag[] {
  const flags: BookingFlag[] = [];
  if (!isOpen(b.status)) return flags;
  if (b.call_now) flags.push({ key: "call_now", label: "Call now", tone: "red" });
  if (!b.phone_checked) {
    // A booking from the link is held until the customer confirms their number on WhatsApp.
    if (b.status === "held" && b.source === "link") flags.push({ key: "waiting_confirm", label: "Waiting for the customer to confirm on WhatsApp", tone: "amber" });
    else flags.push({ key: "phone", label: "Phone not checked", tone: "amber" });
  }
  const amount = typeof b.advance_paise === "number" && b.advance_paise > 0 ? ` ${rupees(b.advance_paise)}` : "";
  if (b.advance_paid) flags.push({ key: "advance_paid", label: `Advance paid${amount}`, tone: "green" });
  else if (b.status === "held" || amount || b.advance_needed) flags.push({ key: "advance_due", label: `Advance due${amount}`, tone: "amber" });
  if (b.confirmed_at && b.status === "booked") flags.push({ key: "said_yes", label: "Said yes", tone: "green" });
  return flags;
}

/** Came / Didn't come: the person with manage, or the staff member on their own column. */
export function canMarkVisit(b: Pick<Booking, "status" | "resource_id">, who: { canManage: boolean; myResourceId: string | null }): boolean {
  if (b.status !== "booked") return false;
  return who.canManage || (who.myResourceId !== null && who.myResourceId === b.resource_id);
}

// ── Site visit outcome (properties) ──────────────────────────────────────────

export const SITE_VISIT_SERVICE = "Site visit";
export const VISIT_OUTCOMES: { value: VisitOutcome; label: string }[] = [
  { value: "liked_thinking", label: "Liked it, thinking" },
  { value: "ready_to_book", label: "Ready to book" },
  { value: "not_interested", label: "Not interested" },
];
export const LOAN_HELP_LINE = "We'll WhatsApp them about home-loan help in 2 days.";

export function isSiteVisit(b: Pick<Booking, "service_name">): boolean {
  return (b.service_name ?? "").trim().toLowerCase() === SITE_VISIT_SERVICE.toLowerCase();
}

/** The outcome choice: a site visit already marked Came, for the same people who may mark Came. */
export function canSetVisitOutcome(b: Pick<Booking, "status" | "resource_id" | "service_name">, who: { canManage: boolean; myResourceId: string | null }): boolean {
  if (b.status !== "came" || !isSiteVisit(b)) return false;
  return who.canManage || (who.myResourceId !== null && who.myResourceId === b.resource_id);
}

/** "Liked it, thinking" gets the loan-help promise line. */
export function visitOutcomeNote(outcome: VisitOutcome | null | undefined): string | null {
  return outcome === "liked_thinking" ? LOAN_HELP_LINE : null;
}

/** "Didn't come" only makes sense once the booking time has started. */
export function canMarkNoShow(
  b: Pick<Booking, "status" | "resource_id" | "start_at">,
  who: { canManage: boolean; myResourceId: string | null },
  now: number = Date.now(),
): boolean {
  if (!canMarkVisit(b, who)) return false;
  const start = Date.parse(b.start_at);
  return !Number.isNaN(start) && start <= now;
}

// ── Grid ─────────────────────────────────────────────────────────────────────

export interface GridRange {
  startMin: number;
  endMin: number;
}

/** Working hours of one column on a date, as [startMin, endMin] pairs. */
export function dayBlocks(hours: WeekHours | undefined, date: string): [number, number][] {
  const out: [number, number][] = [];
  for (const [a, b] of hours?.[String(weekdayIndex(date))] ?? []) {
    const s = hhmmToMinutes(a);
    const e = hhmmToMinutes(b);
    if (s !== null && e !== null && e > s) out.push([s, e]);
  }
  return out;
}

/** The time axis: the earliest start and latest end of the day's hours and bookings, to whole hours. */
export function gridRange(date: string, resources: Pick<BookingResource, "hours">[], bookings: Pick<Booking, "start_at" | "block_end_at">[]): GridRange {
  let lo = Infinity;
  let hi = -Infinity;
  for (const r of resources) {
    for (const [s, e] of dayBlocks(r.hours, date)) {
      lo = Math.min(lo, s);
      hi = Math.max(hi, e);
    }
  }
  for (const b of bookings) {
    const s = minutesOnDay(b.start_at, date);
    const e = minutesOnDay(b.block_end_at, date);
    if (Number.isFinite(s)) lo = Math.min(lo, s);
    if (Number.isFinite(e)) hi = Math.max(hi, e);
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { ...DEFAULT_GRID };
  const startMin = Math.max(0, Math.floor(lo / 60) * 60);
  const endMin = Math.min(1440, Math.ceil(hi / 60) * 60);
  return endMin > startMin ? { startMin, endMin } : { ...DEFAULT_GRID };
}

export interface Placement {
  /** Minutes below the top of the grid. */
  top: number;
  /** The booking itself, in minutes. */
  height: number;
  /** The gap kept free after it, in minutes (drawn hatched). */
  gap: number;
}

export function placeBooking(b: Pick<Booking, "start_at" | "end_at" | "block_end_at">, date: string, gridStartMin: number): Placement | null {
  const s = minutesOnDay(b.start_at, date);
  const e = minutesOnDay(b.end_at, date);
  const be = minutesOnDay(b.block_end_at, date);
  if (![s, e, be].every(Number.isFinite)) return null;
  return { top: s - gridStartMin, height: Math.max(0, e - s), gap: Math.max(0, be - e) };
}

/** Free ranges of one column as { top, height } in minutes from the top of the grid. */
export function freeBands(ranges: FreeRanges[string] | undefined, date: string, gridStartMin: number): { top: number; height: number; startMin: number; endMin: number }[] {
  const out: { top: number; height: number; startMin: number; endMin: number }[] = [];
  for (const [a, b] of ranges ?? []) {
    const s = minutesOnDay(a, date);
    const e = minutesOnDay(b, date);
    if (Number.isFinite(s) && Number.isFinite(e) && e > s) out.push({ top: s - gridStartMin, height: e - s, startMin: s, endMin: e });
  }
  return out;
}

/** Nearest 15-minute mark. */
export function snapMinutes(min: number, step: number = STEP_MIN): number {
  return Math.round(min / step) * step;
}

/**
 * Where a dragged block lands. offsetY is the pointer's distance below the top of the column,
 * grabOffsetMin how far down the block the person grabbed it. Snapped to 15 minutes and kept
 * inside the visible day.
 */
export function dropMinutes(args: {
  offsetY: number;
  grabOffsetMin: number;
  gridStartMin: number;
  gridEndMin: number;
  blockMin: number;
  pxPerMin?: number;
}): number {
  const ppm = args.pxPerMin ?? PX_PER_MIN;
  const raw = args.gridStartMin + args.offsetY / ppm - args.grabOffsetMin;
  const snapped = snapMinutes(raw);
  const max = Math.max(args.gridStartMin, args.gridEndMin - args.blockMin);
  return Math.min(Math.max(snapped, args.gridStartMin), max);
}

/** A click inside a free gap: the 15-minute mark at or before the click, kept inside the gap. */
export function clickMinutes(offsetY: number, band: { startMin: number; endMin: number }, gridStartMin: number, pxPerMin: number = PX_PER_MIN): number {
  const raw = gridStartMin + offsetY / pxPerMin;
  const floored = Math.floor(raw / STEP_MIN) * STEP_MIN;
  const start = Math.ceil(band.startMin / STEP_MIN) * STEP_MIN;
  return Math.min(Math.max(floored, start), Math.max(start, band.endMin - STEP_MIN));
}

/** Which column the pointer is over, given each column's left edge and width. -1 when outside. */
export function columnAt(x: number, columns: { left: number; width: number }[]): number {
  return columns.findIndex((c) => x >= c.left && x < c.left + c.width);
}

// ── Hours editor ─────────────────────────────────────────────────────────────

export const MAX_BLOCKS_PER_DAY = 2;

export function emptyHours(): WeekHours {
  return { "0": [], "1": [], "2": [], "3": [], "4": [], "5": [], "6": [] };
}

/** Mon-Sat 10:00-20:00 as a starting point for a new column. */
export function defaultHours(): WeekHours {
  const h = emptyHours();
  for (let d = 0; d < 6; d++) h[String(d)] = [["10:00", "20:00"]];
  return h;
}

/** Fills missing days so the editor always has seven rows. */
export function normaliseHours(h: WeekHours | null | undefined): WeekHours {
  const out = emptyHours();
  for (let d = 0; d < 7; d++) {
    const blocks = h?.[String(d)];
    if (Array.isArray(blocks)) out[String(d)] = blocks.map((b) => [String(b[0]), String(b[1])] as HoursBlock);
  }
  return out;
}

/** null when fine, otherwise the plain-words reason. */
export function validateDay(blocks: HoursBlock[]): string | null {
  if (blocks.length > MAX_BLOCKS_PER_DAY) return "At most 2 time blocks a day.";
  const spans: [number, number][] = [];
  for (const [a, b] of blocks) {
    const s = hhmmToMinutes(a);
    const e = hhmmToMinutes(b);
    if (s === null || e === null) return "Pick both times.";
    if (e <= s) return "The end must be after the start.";
    spans.push([s, e]);
  }
  spans.sort((x, y) => x[0] - y[0]);
  for (let i = 1; i < spans.length; i++) if (spans[i][0] < spans[i - 1][1]) return "The two blocks overlap.";
  return null;
}

/** Day index -> reason, for the days that have a problem. */
export function validateHours(h: WeekHours): Record<string, string> {
  const errors: Record<string, string> = {};
  for (let d = 0; d < 7; d++) {
    const err = validateDay(h[String(d)] ?? []);
    if (err) errors[String(d)] = err;
  }
  return errors;
}

export function copyDayToAll(h: WeekHours, from: number): WeekHours {
  const src = (h[String(from)] ?? []).map((b) => [b[0], b[1]] as HoursBlock);
  const out = emptyHours();
  for (let d = 0; d < 7; d++) out[String(d)] = src.map((b) => [b[0], b[1]] as HoursBlock);
  return out;
}

/** "10:00–13:00, 16:00–20:00" or "Off". */
export function hoursSummary(blocks: HoursBlock[] | undefined): string {
  if (!blocks || blocks.length === 0) return "Off";
  return blocks.map(([a, b]) => `${a}–${b}`).join(", ");
}

export function addBlock(blocks: HoursBlock[]): HoursBlock[] {
  if (blocks.length >= MAX_BLOCKS_PER_DAY) return blocks;
  const last = blocks[blocks.length - 1];
  const lastEnd = last ? hhmmToMinutes(last[1]) : null;
  if (lastEnd === null) return [...blocks, ["10:00", "13:00"]];
  const s = Math.min(lastEnd + 60, 22 * 60);
  return [...blocks, [minutesToHhmm(s), minutesToHhmm(Math.min(s + 180, 1439))]];
}

// ── Phone and history ────────────────────────────────────────────────────────

/** Indian mobile: 10 digits starting 6-9, with an optional +91 / 91 / 0 in front. */
export function parsePhone(input: string): { ok: boolean; digits: string; error: string | null } {
  let d = input.replace(/[\s\-().]/g, "");
  if (d.startsWith("+")) d = d.slice(1);
  if (d.length === 12 && d.startsWith("91")) d = d.slice(2);
  else if (d.length === 11 && d.startsWith("0")) d = d.slice(1);
  if (!/^\d+$/.test(d)) return { ok: false, digits: "", error: "Use digits only." };
  if (d.length !== 10) return { ok: false, digits: d, error: "Enter a 10-digit mobile number." };
  if (!/^[6-9]/.test(d)) return { ok: false, digits: d, error: "A mobile number starts with 6, 7, 8 or 9." };
  return { ok: true, digits: d, error: null };
}

export function historyNote(h: { bookings_count: number; no_shows: number; advance_needed: boolean } | null | undefined): string | null {
  if (!h) return null;
  if (h.no_shows > 0) {
    const times = h.no_shows === 1 ? "1 didn't come" : `${h.no_shows} didn't come`;
    return h.advance_needed ? `${times} — ask for an advance` : times;
  }
  if (h.bookings_count > 0) return h.bookings_count === 1 ? "1 earlier booking" : `${h.bookings_count} earlier bookings`;
  return null;
}

// ── Lists ────────────────────────────────────────────────────────────────────

export function sortByStart<T extends Pick<Booking, "start_at">>(items: T[]): T[] {
  return [...items].sort((a, b) => a.start_at.localeCompare(b.start_at));
}

/** Customer name, else the phone. */
export function customerLabel(b: Pick<Booking, "customer_name" | "phone">): string {
  return (b.customer_name || "").trim() || b.phone;
}

export interface DaySummary {
  total: number;
  came: number;
  noShow: number;
  /** Booked or waiting for the advance, and the visit has not been marked yet. */
  toCome: number;
  byResource: Record<string, number>;
}

/** Counts for the Day and Week tabs: live bookings per column, plus came / to come / didn't come. */
export function summariseDay(bookings: Pick<Booking, "status" | "resource_id">[]): DaySummary {
  const s: DaySummary = { total: 0, came: 0, noShow: 0, toCome: 0, byResource: {} };
  for (const b of bookings) {
    if (b.status === "no_show") s.noShow += 1;
    if (!isLive(b.status)) continue;
    s.total += 1;
    if (b.status === "came") s.came += 1;
    else s.toCome += 1;
    s.byResource[b.resource_id] = (s.byResource[b.resource_id] ?? 0) + 1;
  }
  return s;
}

/** Columns that can do a service, in the order given. */
export function resourcesForService(resources: BookingResource[], serviceId: string): BookingResource[] {
  return resources.filter((r) => r.active && r.service_ids.includes(serviceId));
}

/** Group times: Morning before noon, Afternoon until 5 PM, Evening after. Reads the IST hour from the ISO stamp. */
export function timesByPart(times: FreeTime[]): { part: "Morning" | "Afternoon" | "Evening"; times: FreeTime[] }[] {
  const parts = { Morning: [] as FreeTime[], Afternoon: [] as FreeTime[], Evening: [] as FreeTime[] };
  for (const t of times) {
    const ms = Date.parse(t.start_at);
    if (Number.isNaN(ms)) continue;
    const hour = new Date(ms + 330 * 60_000).getUTCHours();
    parts[hour < 12 ? "Morning" : hour < 17 ? "Afternoon" : "Evening"].push(t);
  }
  return (["Morning", "Afternoon", "Evening"] as const).filter((p) => parts[p].length > 0).map((p) => ({ part: p, times: parts[p] }));
}


// ── Money fields ─────────────────────────────────────────────────────────────

/** "200" -> 20000, "199.5" -> 19950, "" -> 0. null when it is not a plain amount. */
export function rupeesTextToPaise(text: string): number | null {
  const t = text.replace(/[,\s₹]/g, "");
  if (t === "") return 0;
  if (!/^\d+(\.\d{1,2})?$/.test(t)) return null;
  const paise = Math.round(Number(t) * 100);
  return Number.isSafeInteger(paise) ? paise : null;
}

/** 20000 -> "200", 19950 -> "199.50", undefined or 0 -> "". */
export function paiseToRupeesText(paise: number | undefined | null): string {
  if (!paise) return "";
  return paise % 100 === 0 ? String(paise / 100) : (paise / 100).toFixed(2);
}

// ── Booking-link rules ───────────────────────────────────────────────────────


export const RULE_LIMITS = {
  days_ahead: { min: 1, max: 90 },
  min_notice_min: { min: 0, max: 2880 },
  cancel_cutoff_min: { min: 0, max: 2880 },
  no_show_limit: { min: 1, max: 10 },
} as const;

/** null when the rules are fine, else the plain-words reason (limits match the database). */
export function validateRules(r: BookingSettings): string | null {
  const labels: Record<keyof typeof RULE_LIMITS, string> = {
    days_ahead: "Days ahead",
    min_notice_min: "Notice",
    cancel_cutoff_min: "Cancel or move cut-off",
    no_show_limit: "Didn't-comes before an advance",
  };
  for (const key of Object.keys(RULE_LIMITS) as (keyof typeof RULE_LIMITS)[]) {
    const v = r[key];
    const { min, max } = RULE_LIMITS[key];
    if (!Number.isInteger(v) || v < min || v > max) return `${labels[key]} must be a whole number from ${min} to ${max}.`;
  }
  return null;
}

/** "3 hours", "90 minutes", "1 hour 30 minutes". */
export function minutesInWords(min: number): string {
  if (min < 60) return `${min} minute${min === 1 ? "" : "s"}`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  const hours = `${h} hour${h === 1 ? "" : "s"}`;
  return m ? `${hours} ${m} minutes` : hours;
}

/** State of a WhatsApp message template, in plain words. */
export function templateStatusText(state: string | null | undefined): { text: string; ready: boolean } {
  const s = (state ?? "").toUpperCase();
  if (s === "APPROVED") return { text: "Ready", ready: true };
  if (s === "PENDING" || s === "IN_REVIEW") return { text: "Waiting for WhatsApp to approve", ready: false };
  if (s === "REJECTED") return { text: "WhatsApp said no — set up again", ready: false };
  return { text: "Not set up yet", ready: false };
}
