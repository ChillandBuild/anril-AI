// Pure logic for the public booking page (/book/<token>). No React, no network, so it can be
// tested. All times shown to people are IST (Asia/Kolkata, UTC+5:30, no daylight saving).

const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A Date whose UTC fields read as IST wall-clock fields. */
function istParts(ms: number) {
  const d = new Date(ms + IST_OFFSET_MS);
  return {
    year: d.getUTCFullYear(),
    month: d.getUTCMonth(),
    day: d.getUTCDate(),
    weekday: d.getUTCDay(),
    hour: d.getUTCHours(),
    minute: d.getUTCMinutes(),
  };
}

const pad = (n: number) => String(n).padStart(2, "0");

/** IST calendar date (YYYY-MM-DD) of an instant. */
export function istDateOf(iso: string | number | Date): string {
  const ms = typeof iso === "number" ? iso : new Date(iso).getTime();
  const p = istParts(ms);
  return `${p.year}-${pad(p.month + 1)}-${pad(p.day)}`;
}

/** "4:00 PM" */
export function formatTime(iso: string): string {
  const p = istParts(new Date(iso).getTime());
  const h12 = p.hour % 12 === 0 ? 12 : p.hour % 12;
  return `${h12}:${pad(p.minute)} ${p.hour < 12 ? "AM" : "PM"}`;
}

/** "Thu 28 Nov" */
export function formatDay(iso: string): string {
  const p = istParts(new Date(iso).getTime());
  return `${WEEKDAYS[p.weekday]} ${p.day} ${MONTHS[p.month]}`;
}

/** "Thu 28 Nov, 4:00 PM" */
export function formatWhen(iso: string): string {
  return `${formatDay(iso)}, ${formatTime(iso)}`;
}

/** ₹ text from paise: 20000 -> "₹200", 25050 -> "₹250.50". */
export function rupees(paise: number): string {
  const r = paise / 100;
  return "₹" + r.toLocaleString("en-IN", { minimumFractionDigits: Number.isInteger(r) ? 0 : 2, maximumFractionDigits: 2 });
}

/** "30 min", "1 hr", "1 hr 30 min" */
export function formatDuration(min: number): string {
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h} hr ${m} min` : `${h} hr`;
}

// ── Phone ─────────────────────────────────────────────────────────────────────

export type PhoneCheck = { ok: true; phone: string; digits: string } | { ok: false; message: string };

/**
 * Indian mobile check. Accepts "98765 43210", "+91 98765-43210", "919876543210", "09876543210".
 * Returns the number as +91XXXXXXXXXX (what the server normalises to) or a plain-words message.
 */
export function checkIndianMobile(raw: string): PhoneCheck {
  const typed = (raw ?? "").trim();
  if (!typed) return { ok: false, message: "Enter your mobile number." };
  if (/[^\d\s+\-().]/.test(typed)) return { ok: false, message: "Use digits only in the phone number." };
  let d = typed.replace(/\D/g, "");
  if (d.length === 12 && d.startsWith("91")) d = d.slice(2);
  else if (d.length === 11 && d.startsWith("0")) d = d.slice(1);
  if (d.length !== 10) return { ok: false, message: "Enter a 10-digit mobile number." };
  if (!/^[6-9]/.test(d)) return { ok: false, message: "Mobile numbers start with 6, 7, 8 or 9." };
  if (/^(\d)\1{9}$/.test(d)) return { ok: false, message: "That number doesn't look right." };
  return { ok: true, phone: `+91${d}`, digits: d };
}

/** Keep only what a person can still be typing into the 10-digit box (drops +91 / 0 prefixes on paste). */
export function cleanPhoneInput(raw: string): string {
  let d = (raw ?? "").replace(/\D/g, "");
  if (d.length > 10 && d.startsWith("91")) d = d.slice(2);
  else if (d.length > 10 && d.startsWith("0")) d = d.slice(1);
  return d.slice(0, 10);
}

export const NAME_MAX = 60;

// http(s):, www., or something.tld (the server turns links away too).
const LINK_RE = /(https?:|www\.|\b[a-z0-9-]+\.(com|in|net|org|co|io|me|app|link|ly|xyz|info|biz|site|online|shop)\b)/i;

export function checkName(raw: string): { ok: true; name: string } | { ok: false; message: string } {
  const name = (raw ?? "").replace(/\s+/g, " ").trim();
  if (name.length < 2) return { ok: false, message: "Enter your name." };
  if (name.length > NAME_MAX) return { ok: false, message: `Use ${NAME_MAX} letters or fewer for your name.` };
  if (LINK_RE.test(name)) return { ok: false, message: "Please type just your name, without a link." };
  return { ok: true, name };
}

// ── Links we are willing to put in an href ────────────────────────────────────

/** The pay link, only when it is https://. Anything else is dropped. */
export function safePaymentUrl(url: string | null | undefined): string | null {
  return typeof url === "string" && url.startsWith("https://") && !/\s/.test(url) ? url : null;
}

/** The WhatsApp link, only when it is https://wa.me/... */
export function safeWhatsappUrl(url: string | null | undefined): string | null {
  return typeof url === "string" && url.startsWith("https://wa.me/") && !/\s/.test(url) ? url : null;
}

// ── Times ─────────────────────────────────────────────────────────────────────

export interface SlotLike {
  start_at: string;
  resource_id: string;
  resource_name: string;
}

export type DayPart = "Morning" | "Afternoon" | "Evening";

export function dayPartOf(iso: string): DayPart {
  const h = istParts(new Date(iso).getTime()).hour;
  if (h < 12) return "Morning";
  if (h < 17) return "Afternoon";
  return "Evening";
}

/**
 * Group free times into Morning (before 12), Afternoon (12 to 5 PM), Evening (5 PM on), in time
 * order, leaving out empty groups. With dedupe (the "Anyone free" choice) one button per start
 * time is shown even when several columns are free then.
 */
export function groupTimes<T extends SlotLike>(slots: T[], dedupe: boolean): { part: DayPart; slots: T[] }[] {
  const sorted = [...slots].sort((a, b) => new Date(a.start_at).getTime() - new Date(b.start_at).getTime());
  const seen = new Set<number>();
  const kept: T[] = [];
  for (const s of sorted) {
    const t = new Date(s.start_at).getTime();
    if (Number.isNaN(t)) continue;
    if (dedupe) {
      if (seen.has(t)) continue;
      seen.add(t);
    }
    kept.push(s);
  }
  const order: DayPart[] = ["Morning", "Afternoon", "Evening"];
  return order
    .map((part) => ({ part, slots: kept.filter((s) => dayPartOf(s.start_at) === part) }))
    .filter((g) => g.slots.length > 0);
}

export interface DayCell {
  date: string;
  weekday: string;
  day: number;
  month: string;
  enabled: boolean;
  isToday: boolean;
}

/** Today (IST) through today + daysAhead, each enabled only when the server listed it as free. */
export function buildDayGrid(nowMs: number, daysAhead: number, freeDates: string[]): DayCell[] {
  const free = new Set(freeDates);
  const today = istDateOf(nowMs);
  const cells: DayCell[] = [];
  const n = Math.max(0, Math.min(daysAhead, 120));
  for (let i = 0; i <= n; i++) {
    const ms = nowMs + i * 24 * 60 * 60 * 1000;
    const p = istParts(ms);
    const date = `${p.year}-${pad(p.month + 1)}-${pad(p.day)}`;
    cells.push({ date, weekday: WEEKDAYS[p.weekday], day: p.day, month: MONTHS[p.month], enabled: free.has(date), isToday: date === today });
  }
  return cells;
}

// ── Step state machine ────────────────────────────────────────────────────────

export type Step = "service" | "staff" | "day" | "time" | "details";
export const STEPS: Step[] = ["service", "staff", "day", "time", "details"];

export const STEP_TITLES: Record<Step, string> = {
  service: "What do you want to book?",
  staff: "Who with?",
  day: "Pick a day",
  time: "Pick a time",
  details: "Your details",
};

export interface FlowState {
  step: Step;
  serviceId: string | null;
  /** "any" or a column id. */
  resourceId: string | null;
  date: string | null;
  slot: SlotLike | null;
}

export type FlowAction =
  | { type: "service"; id: string }
  | { type: "staff"; id: string }
  | { type: "day"; date: string }
  | { type: "time"; slot: SlotLike }
  | { type: "edit"; step: Step }
  | { type: "slotTaken" };

export const initialFlow: FlowState = { step: "service", serviceId: null, resourceId: null, date: null, slot: null };

export const stepIndex = (s: Step) => STEPS.indexOf(s);

export function flowReducer(state: FlowState, action: FlowAction): FlowState {
  switch (action.type) {
    case "service":
      return { step: "staff", serviceId: action.id, resourceId: null, date: null, slot: null };
    case "staff":
      if (!state.serviceId) return state;
      return { ...state, step: "day", resourceId: action.id, date: null, slot: null };
    case "day":
      if (!state.serviceId || !state.resourceId) return state;
      return { ...state, step: "time", date: action.date, slot: null };
    case "time":
      if (!state.serviceId || !state.resourceId || !state.date) return state;
      return { ...state, step: "details", slot: action.slot };
    case "slotTaken":
      if (!state.serviceId || !state.resourceId || !state.date) return state;
      return { ...state, step: "time", slot: null };
    case "edit": {
      // Only steps already answered can be reopened; everything after them is cleared.
      if (stepIndex(action.step) > stepIndex(state.step)) return state;
      switch (action.step) {
        case "service":
          return initialFlow;
        case "staff":
          return { ...state, step: "staff", resourceId: null, date: null, slot: null };
        case "day":
          return { ...state, step: "day", date: null, slot: null };
        case "time":
          return { ...state, step: "time", slot: null };
        default:
          return state;
      }
    }
    default:
      return state;
  }
}

/** The staff choices for a service: "Anyone free" first, then the columns that do it. */
export function staffChoices(
  resources: { id: string; name: string; service_ids: string[] }[],
  serviceId: string,
): { id: string; name: string }[] {
  const people = resources.filter((r) => r.service_ids.includes(serviceId)).map((r) => ({ id: r.id, name: r.name }));
  if (people.length === 0) return [];
  return [{ id: "any", name: "Anyone free" }, ...people];
}

// ── Errors in plain words ─────────────────────────────────────────────────────

export type BookingErrorKind =
  | "slot_taken"
  | "one_per_day"
  | "too_late"
  | "bad_phone"
  | "too_many_waiting"
  | "show_detail"
  | "busy"
  | "gone"
  | "offline"
  | "other";

export function classifyError(status: number, detail: string): BookingErrorKind {
  if (status === 0) return "offline";
  const d = (detail || "").toLowerCase();
  if (status === 429) return d.includes("whatsapp") || d.includes("waiting") ? "too_many_waiting" : "busy";
  if (status === 404) return "gone";
  if (status === 403) return "too_late";
  if (status === 400 && (d.includes("10-digit") || d.includes("phone number") || d.includes("mobile number"))) return "bad_phone";
  if (d.includes("taken") || d.includes("no longer free") || d.includes("not free")) return "slot_taken";
  if (d.includes("already has a booking") || d.includes("one booking")) return "one_per_day";
  if (d.includes("cutoff") || d.includes("less than") || d.includes("too late") || d.includes("too soon") || d.includes("too close")) return "too_late";
  // A 409 from the server ("This number can't book this time…") is already plain words: show it.
  if (status === 409 && detail.trim() && detail.length <= 200) return "show_detail";
  return "other";
}

export function errorMessage(kind: BookingErrorKind, detail = ""): string {
  switch (kind) {
    case "slot_taken":
      return "Sorry, that time was just taken. Please pick another.";
    case "one_per_day":
      return "This phone number already has a booking that day. Pick another day, or call the business to change it.";
    case "too_late":
      return "Please call the business to change it again.";
    case "bad_phone":
      return "Please enter a 10-digit mobile number.";
    case "too_many_waiting":
      return "Too many bookings waiting. Please confirm one on WhatsApp first.";
    case "show_detail":
      return detail.trim() || "Something went wrong. Please try again, or call the business.";
    case "busy":
      return "Too many tries. Wait a minute and try again.";
    case "gone":
      return "This booking link is not working. Ask the business for a new one.";
    case "offline":
      return "Can't reach the server. Check your internet and try again.";
    default:
      return "Something went wrong. Please try again, or call the business.";
  }
}

/** One call: server error (status + detail) to words. */
export function errorText(status: number, detail: string): string {
  return errorMessage(classifyError(status, detail), detail);
}

// ── Cancel / change window ────────────────────────────────────────────────────

/** "3 hours" from minutes, for "less than 3 hours away". */
export function cutoffText(min: number): string {
  if (min % 60 === 0) {
    const h = min / 60;
    return h === 1 ? "1 hour" : `${h} hours`;
  }
  return `${min} minutes`;
}

// ── Hold countdown ────────────────────────────────────────────────────────────

export function secondsLeft(holdUntilIso: string | null | undefined, nowMs: number): number | null {
  if (!holdUntilIso) return null;
  const t = new Date(holdUntilIso).getTime();
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.ceil((t - nowMs) / 1000));
}

/** 872 -> "14:32" */
export function formatCountdown(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  return `${Math.floor(s / 60)}:${pad(s % 60)}`;
}

// ── Add to calendar (.ics) ────────────────────────────────────────────────────

function icsStamp(ms: number): string {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}T${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`;
}

/** RFC 5545 TEXT: backslash first, then ; and , and every kind of line break becomes \\n. */
export function icsEscape(s: string): string {
  return s
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\r\n|\r|\n/g, "\\n");
}

/** RFC 5545: lines over 75 bytes (UTF-8) are folded with CRLF + a space, never inside a character. */
function icsFold(line: string): string {
  const enc = new TextEncoder();
  const parts: string[] = [];
  let cur = "";
  let bytes = 0;
  let limit = 75;
  for (const ch of line) {
    const n = enc.encode(ch).length;
    if (bytes + n > limit) {
      parts.push(cur);
      cur = "";
      bytes = 0;
      limit = 74; // continuation lines start with a space
    }
    cur += ch;
    bytes += n;
  }
  parts.push(cur);
  return parts.join("\r\n ");
}

export interface IcsInput {
  code: string;
  businessName: string;
  serviceName: string;
  resourceName?: string;
  startAt: string;
  durationMin: number;
  nowMs?: number;
}

export function buildIcs(b: IcsInput): string {
  const start = new Date(b.startAt).getTime();
  const end = start + Math.max(1, b.durationMin) * 60 * 1000;
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Anril//Booking//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "BEGIN:VEVENT",
    `UID:${b.code}-${start}@anril-booking`,
    `DTSTAMP:${icsStamp(b.nowMs ?? Date.now())}`,
    `DTSTART:${icsStamp(start)}`,
    `DTEND:${icsStamp(end)}`,
    `SUMMARY:${icsEscape(`${b.serviceName} at ${b.businessName}`)}`,
    `DESCRIPTION:${icsEscape(`Booking code ${b.code}${b.resourceName ? ` with ${b.resourceName}` : ""}`)}`,
    "BEGIN:VALARM",
    "TRIGGER:-PT1H",
    "ACTION:DISPLAY",
    "DESCRIPTION:Your booking is in 1 hour",
    "END:VALARM",
    "END:VEVENT",
    "END:VCALENDAR",
  ];
  return lines.map(icsFold).join("\r\n") + "\r\n";
}

/** Status words for the status page. "Booked!" is only for a booking that is really booked. */
export function statusLabel(status: string): string {
  switch (status) {
    case "held":
      return "Not confirmed yet";
    case "booked":
      return "Booked!";
    case "came":
      return "Done";
    case "cancelled":
      return "Cancelled";
    case "no_show":
      return "Missed";
    default:
      return status;
  }
}

export const isLive = (status: string) => status === "held" || status === "booked";

/**
 * A held booking needs the customer's number confirmed on WhatsApp (step 1) and, when an advance
 * is due, the advance paid (step 2). It turns into "booked" on the server once both are done.
 */
export function heldSteps(b: { phone_checked?: boolean; advance_paise: number; advance_paid: boolean }) {
  const numberConfirmed = b.phone_checked === true;
  const needsAdvance = b.advance_paise > 0;
  const advancePaid = needsAdvance && b.advance_paid;
  return {
    numberConfirmed,
    needsAdvance,
    advancePaid,
    /** Everything is done and we are only waiting for the server to flip it to booked. */
    confirming: numberConfirmed && (!needsAdvance || advancePaid),
  };
}

// ── Polling ───────────────────────────────────────────────────────────────────

export const POLL_MS = 10_000;
export const POLL_BACKOFF_MS = 30_000;

export type PollOutcome = "ok" | "rate_limited" | "error";

/** Next wait between status checks: 10 s normally, 30 s after a 429, unchanged after another error. */
export function nextPollDelay(current: number, outcome: PollOutcome): number {
  if (outcome === "rate_limited") return POLL_BACKOFF_MS;
  if (outcome === "ok") return POLL_MS;
  return current;
}
