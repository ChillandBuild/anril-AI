/** Pure helpers for the SMS page (kept out of components so they can be unit-tested). */
import { clockOf } from "@/lib/schedule-time";
import type {
  SmsBalance,
  SmsCampaign,
  SmsCampaignPreviewRequest,
  SmsMessageStatus,
  SmsPreview,
  SmsPreviewExcluded,
  SmsRecipients,
  SmsRecipientSource,
  SmsReportDay,
  SmsSkippedRow,
  SmsTemplate,
  SmsTemplateType,
  SmsVarSource,
  SmsWalletItem,
} from "@/lib/api";

export const MAX_LEADS_PER_CAMPAIGN = 5000;

const STATUS_LABELS: Record<SmsMessageStatus, string> = {
  queued: "Waiting",
  sending: "Sending",
  submitted: "Sent to operator",
  delivered: "Delivered",
  failed: "Failed",
  unknown: "Checking…",
  skipped: "Not sent",
  cancelled: "Cancelled",
};

export const MESSAGE_STATUSES = Object.keys(STATUS_LABELS) as SmsMessageStatus[];

/** Wording shown to the client for a message status (exactly as in the API contract). */
export function statusLabel(status: string): string {
  return STATUS_LABELS[status as SmsMessageStatus] ?? status;
}

export type Tone = "neutral" | "info" | "success" | "danger" | "warn";

export function statusTone(status: string): Tone {
  switch (status) {
    case "delivered":
      return "success";
    case "failed":
      return "danger";
    case "unknown":
    case "skipped":
      return "warn";
    case "submitted":
    case "sending":
      return "info";
    default:
      return "neutral";
  }
}

// ---------------------------------------------------------------- night-time hold
// TRAI night-time rule: SMS sent between 9 PM and 10 AM IST are held by Bulk9 and go out at
// 10 AM (seen live 2026-11-04: three 10:47-11:39 PM sends were scheduled for 10:01 AM).
const IST_OFFSET_MS = 330 * 60_000;
const QUIET_FROM_HOUR = 21;
const QUIET_UNTIL_HOUR = 10;

function toDate(at: Date | string | null | undefined): Date | null {
  if (!at) return null;
  const d = at instanceof Date ? at : new Date(at);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** The 10 AM IST that releases a send made at `at`, or null when `at` is outside 9 PM–10 AM. */
export function quietRelease(at: Date | string | null | undefined): Date | null {
  const d = toDate(at);
  if (!d) return null;
  const ist = new Date(d.getTime() + IST_OFFSET_MS);
  const hour = ist.getUTCHours();
  if (hour >= QUIET_UNTIL_HOUR && hour < QUIET_FROM_HOUR) return null;
  const day = ist.getUTCDate() + (hour >= QUIET_FROM_HOUR ? 1 : 0);
  return new Date(Date.UTC(ist.getUTCFullYear(), ist.getUTCMonth(), day, QUIET_UNTIL_HOUR) - IST_OFFSET_MS);
}

/** When a message sent to the operator at night is still being held: the 10 AM release, else null. */
export function heldUntil(m: { status: string; submitted_at: string | null }, now: Date): Date | null {
  if (m.status !== "submitted") return null;
  const release = quietRelease(m.submitted_at);
  return release && now < release ? release : null;
}

export const NIGHT_RULE =
  "SMS sent between 9 PM and 10 AM are held by the operator and go out at 10 AM (TRAI night-time rule).";

export function formatCount(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString("en-IN");
}

const IST_FORMAT = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  day: "numeric",
  month: "short",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
});

/** "30 Oct, 2:04 pm" in IST from an ISO-8601 UTC string. */
export function formatIst(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return IST_FORMAT.format(d).replace(/\s?(am|pm)/i, (m) => m.toLowerCase());
}

/** YYYY-MM-DD of an instant as seen in India. */
export function istDateString(d: Date): string {
  const shifted = new Date(d.getTime() + 330 * 60_000);
  return shifted.toISOString().slice(0, 10);
}

function addDays(date: string, days: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Days between two YYYY-MM-DD dates, `to` minus `from`. */
export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);
}

/**
 * Keep a date range inside a window of `maxDays` calendar days, both ends counted (a 3-day window
 * is 28 Oct to 30 Oct). Counting inclusively is the safe reading of "<= 3 days" for the API.
 * The date you just edited wins; the other end moves. Never reaches past `today`.
 */
export function clampRange(
  range: { from: string; to: string },
  edited: "from" | "to",
  maxDays: number,
  today: string,
): { from: string; to: string } {
  let { from, to } = range;
  const span = maxDays - 1;
  if (to > today) to = today;
  if (from > today) from = today;
  if (from > to) {
    if (edited === "from") to = from;
    else from = to;
  }
  if (daysBetween(from, to) > span) {
    if (edited === "from") {
      to = addDays(from, span);
      if (to > today) to = today;
    } else from = addDays(to, -span);
  }
  return { from, to };
}

/** The last `days` calendar days ending today (both ends counted). */
export function defaultRange(today: string, days: number): { from: string; to: string } {
  return { from: addDays(today, -(days - 1)), to: today };
}

/** The max `to` date allowed for a given `from` (used for the picker's max attribute). */
export function maxToFor(from: string, maxDays: number, today: string): string {
  const cap = addDays(from, maxDays - 1);
  return cap > today ? today : cap;
}

export type TemplatePart = { kind: "text"; text: string } | { kind: "var"; index: number };

const VAR_RE = /\{#var#\}/gi;

/** Split SMS wording into text pieces and numbered {#var#} slots. */
export function splitTemplate(message: string): TemplatePart[] {
  const parts: TemplatePart[] = [];
  let last = 0;
  let index = 0;
  for (const m of Array.from(message.matchAll(VAR_RE))) {
    const at = m.index ?? 0;
    if (at > last) parts.push({ kind: "text", text: message.slice(last, at) });
    parts.push({ kind: "var", index: index++ });
    last = at + m[0].length;
  }
  if (last < message.length) parts.push({ kind: "text", text: message.slice(last) });
  return parts;
}

export function countVars(message: string): number {
  return (message.match(VAR_RE) ?? []).length;
}

/** Every variable must have a field chosen, fixed text, or a value typed per number. */
export function isVariableMapComplete(map: (SmsVarSource | null)[], varCount: number): boolean {
  if (map.length < varCount) return false;
  for (let i = 0; i < varCount; i++) {
    const v = map[i];
    if (!v) return false;
    if (v.source !== "typed" && (!v.value || !v.value.trim())) return false;
  }
  return true;
}

/**
 * Drop mappings that point at a contact field the current audience no longer offers. Fixed-text
 * sources stay; "typed" stays unless the audience cannot type values (not Type numbers).
 * Returns the same array when nothing changed, so it is safe in a state update.
 */
export function pruneVarMap(map: (SmsVarSource | null)[], availableKeys: string[], allowTyped = true): (SmsVarSource | null)[] {
  let changed = false;
  const next = map.map((v) => {
    if (v && ((v.source === "field" && !availableKeys.includes(v.value)) || (v.source === "typed" && !allowTyped))) {
      changed = true;
      return null;
    }
    return v;
  });
  return changed ? next : map;
}

/** Group excluded leads by reason, largest group first. */
export function groupExcluded(excluded: SmsPreviewExcluded[]): { reason: string; leads: SmsPreviewExcluded[] }[] {
  const by = new Map<string, SmsPreviewExcluded[]>();
  for (const e of excluded) {
    const list = by.get(e.reason) ?? [];
    list.push(e);
    by.set(e.reason, list);
  }
  return Array.from(by.entries())
    .map(([reason, leads]) => ({ reason, leads }))
    .sort((a, b) => b.leads.length - a.leads.length);
}

export function errorStatus(err: unknown): number | undefined {
  return typeof err === "object" && err !== null && "status" in err
    ? (err as { status?: number }).status
    : undefined;
}

export function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/** Plain-words version of the two states the API uses for "not available". */
export function friendlyError(err: unknown, fallback: string): string {
  const status = errorStatus(err);
  if (status === 403) return "You don't have permission to do this, or SMS isn't turned on for this account.";
  if (status === 409) return "SMS isn't connected yet. Setup is still in progress.";
  return errorText(err, fallback);
}

const CAMPAIGN_STATUS_LABELS: Record<string, string> = {
  preparing: "Preparing…",
  scheduled: "Scheduled",
  sending: "Sending",
  completed: "Completed",
  cancelled: "Cancelled",
};

export function campaignStatusLabel(status: string): string {
  return CAMPAIGN_STATUS_LABELS[status] ?? status;
}

export function campaignStatusTone(status: string): Tone {
  if (status === "completed") return "success";
  if (status === "sending" || status === "preparing") return "info";
  if (status === "scheduled") return "warn";
  return "neutral";
}

/**
 * The badge a send shows. The server marks a campaign "completed" as soon as every SMS is handed to
 * the operator, which is not the same as delivered: while some still have no receipt it reads
 * "Waiting for delivery", or "Held until 10:00 AM" while the TRAI night rule is holding them.
 * Once every receipt is in it reads Delivered, Failed or "2 of 3 delivered".
 */
const RECEIPT_WAIT_DAYS = 3;

export function campaignStage(
  c: Pick<SmsCampaign, "status" | "counts" | "completed_at" | "created_at" | "send_at">,
  now: Date,
): { label: string; tone: Tone; heldUntil: Date | null } {
  if (c.status !== "completed") return { label: campaignStatusLabel(c.status), tone: campaignStatusTone(c.status), heldUntil: null };
  const n = (k: SmsMessageStatus) => Number(c.counts?.[k]) || 0;
  const waiting = n("queued") + n("sending") + n("submitted") + n("unknown");
  if (waiting === 0) return finishedOutcome(n("delivered"), n("failed"));
  // Held only when the whole send went out inside one night window (started and finished before the same 10 AM).
  const started = quietRelease(c.send_at ?? c.created_at);
  const finished = quietRelease(c.completed_at ?? c.send_at ?? c.created_at);
  if (n("submitted") > 0 && started && finished && started.getTime() === finished.getTime() && now < finished) {
    return { label: `Held until ${clockOf(finished)}`, tone: "warn", heldUntil: finished };
  }
  // Delivery checks stop after a few days; past that a missing receipt won't come.
  const done = toDate(c.completed_at ?? c.send_at ?? c.created_at);
  if (done && now.getTime() - done.getTime() > RECEIPT_WAIT_DAYS * 86_400_000) {
    return { label: `Completed · ${waiting} without receipt`, tone: "neutral", heldUntil: null };
  }
  return { label: "Waiting for delivery", tone: "info", heldUntil: null };
}

/**
 * The badge for a send where every SMS has its receipt. "Completed" alone hid failures (a send
 * where every SMS failed showed a green Completed), so it names the result instead.
 */
function finishedOutcome(delivered: number, failed: number): { label: string; tone: Tone; heldUntil: null } {
  const sent = delivered + failed;
  if (sent === 0) return { label: "Nothing sent", tone: "neutral", heldUntil: null };
  if (failed === 0) return { label: "Delivered", tone: "success", heldUntil: null };
  if (delivered === 0) return { label: "Failed", tone: "danger", heldUntil: null };
  return { label: `${formatCount(delivered)} of ${formatCount(sent)} delivered`, tone: "warn", heldUntil: null };
}

/** "₹0.1302": a per-SMS price needs four decimals. */
export function formatRate(n: number): string {
  return `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;
}

export interface PlanSummary { perSms: number | null; smsLeft: number; moneyLeft: number | null; used: number; total: number; partial: boolean }

/**
 * The client's plan, like the operator panel's Plan Details: price per SMS (money left ÷ SMS left),
 * what's left, what's been used (campaigns + use outside Anril, from the balance history) and the
 * total (left + used). `partial` = the history hit `limit`, so used/total are "at least".
 */
export function planSummary(balance: SmsBalance, items: SmsWalletItem[], limit: number): PlanSummary {
  const smsLeft = Math.max(0, Number(balance.sms_count) || 0);
  const used = items.reduce((sum, i) => (i.kind === "topup" ? sum : sum + Math.abs(Number(i.sms) || 0)), 0);
  const moneyLeft = balance.wallet ?? null;
  return {
    perSms: planRate(balance),
    smsLeft,
    moneyLeft,
    used,
    total: smsLeft + used,
    partial: items.length >= limit,
  };
}

/** Bar heights for the daily chart: each day's share of the busiest day (0–100), SMS and OTP scaled apart. */
/** Bar colours shared by the Reports "By day" chart and the dashboard's 7-day bars. */
export const SMS_CHART_COLORS = { delivered: "#038285", failed: "#e11d48", waiting: "#cbd5e1", otp: "#6366f1" };

export function dailyBars(days: SmsReportDay[]): { day: string; label: string; sms: number; otp: number; delivered: number; failed: number; waiting: number; smsPct: number; otpPct: number }[] {
  const smsMax = Math.max(0, ...days.map((d) => d.delivered + d.failed + d.waiting));
  const otpMax = Math.max(0, ...days.map((d) => d.otp));
  return days.map((d) => {
    const sms = d.delivered + d.failed + d.waiting;
    const [, m, dd] = d.day.split("-").map(Number);
    const label = `${dd} ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][(m || 1) - 1]}`;
    return {
      day: d.day, label, sms, otp: d.otp, delivered: d.delivered, failed: d.failed, waiting: d.waiting,
      // A busy day must not flatten a quiet one to nothing: any non-zero day gets at least a sliver.
      smsPct: sms > 0 ? Math.max(3, Math.round((sms / smsMax) * 100)) : 0,
      otpPct: d.otp > 0 ? Math.max(3, Math.round((d.otp / otpMax) * 100)) : 0,
    };
  });
}

export function humanizeKind(kind: string): string {
  const s = kind.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Flatten a raw object into displayable scalar entries (used for the Bulk9 summary/logs blobs). */
export function scalarEntries(obj: Record<string, unknown> | null | undefined): [string, string][] {
  if (!obj) return [];
  const out: [string, string][] = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v === null || v === undefined) continue;
    if (typeof v === "object") continue;
    out.push([k, String(v)]);
  }
  return out;
}

/** Column keys for a raw log table: scalar keys of the first rows, capped. */
export function logColumns(rows: Record<string, unknown>[], max = 8): string[] {
  const keys: string[] = [];
  for (const row of rows.slice(0, 10)) {
    for (const [k, v] of Object.entries(row)) {
      if (v !== null && typeof v === "object") continue;
      if (!keys.includes(k)) keys.push(k);
      if (keys.length >= max) return keys;
    }
  }
  return keys;
}

export function campaignNeedsUpdates(campaign: { status: string; counts: Partial<Record<SmsMessageStatus, number>> } | null | undefined): boolean {
  return !!campaign && (campaign.status === "preparing" || campaign.status === "scheduled" || campaign.status === "sending" ||
    ["queued", "sending", "submitted", "unknown"].some((status) => (campaign.counts[status as SmsMessageStatus] ?? 0) > 0));
}

export function previewKey(template: { id: string; message: string; template_type: string } | null, map: (SmsVarSource | null)[], selected: Set<string>): string {
  return JSON.stringify([template, map, Array.from(selected).sort()]);
}

// Below this many SMS the balance turns amber.
export const LOW_BALANCE_SMS = 500;

export function balanceLevel(count: number | null | undefined): "empty" | "low" | "ok" {
  const n = Number(count) || 0;
  if (n <= 0) return "empty";
  return n < LOW_BALANCE_SMS ? "low" : "ok";
}

export const SUPPORT_FALLBACK = "your Anril account manager";

/** "₹1,234.50" (en-IN grouping, always 2 decimals). */
export function formatRupees(n: number): string {
  return `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export interface SendBlock { blocked: boolean; reason: string | null }

/**
 * Why a campaign can't be sent yet. While status or balance is still loading it blocks without a
 * message; once loaded, a missing value blocks with a message.
 */
export function sendBlock(input: {
  loading: boolean;
  balance: number | undefined;
  needed: number;
  support: string | null;
}): SendBlock {
  if (input.loading) return { blocked: true, reason: null };
  if (input.balance === undefined) return { blocked: true, reason: "Couldn't check your SMS balance. Refresh and try again." };
  if (input.balance < input.needed) {
    return {
      blocked: true,
      reason: `Not enough SMS balance: this campaign needs ${formatCount(input.needed)} SMS and you have ${formatCount(input.balance)}. Contact ${input.support || SUPPORT_FALLBACK} to top up.`,
    };
  }
  return { blocked: false, reason: null };
}

/** "+1,000" for a top-up, "−2,140" (true minus sign) for usage. */
export function formatSignedSms(n: number): string {
  if (n > 0) return `+${formatCount(n)}`;
  if (n < 0) return `\u2212${formatCount(-n)}`;
  return "0";
}

export const WALLET_KIND_LABELS: Record<SmsWalletItem["kind"], string> = {
  topup: "Top-up",
  outside_usage: "Used outside Anril",
  campaign: "Campaign",
};

export function walletKindTone(kind: SmsWalletItem["kind"]): Tone {
  return kind === "topup" ? "success" : kind === "campaign" ? "info" : "neutral";
}

/** "2026-10-30 14:04" in IST from an ISO-8601 string. */
function istStamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Date(d.getTime() + 330 * 60_000).toISOString().slice(0, 16).replace("T", " ");
}

function csvCell(value: string, text = false): string {
  // Text from other people must not run as a spreadsheet formula.
  const safe = text && /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function walletCsv(items: SmsWalletItem[]): string {
  const rows = items.map((i) =>
    [
      csvCell(istStamp(i.at)),
      csvCell(WALLET_KIND_LABELS[i.kind] ?? i.kind, true),
      csvCell(i.label, true),
      String(i.sms),
      i.amount == null ? "" : i.amount.toFixed(2),
    ].join(","),
  );
  return ["Date,Type,Description,SMS,Amount", ...rows].join("\r\n");
}

export const OTP_LENGTH_RANGE = { min: 4, max: 10 };
export const OTP_EXPIRY_RANGE = { min: 1, max: 10080 };
export const OTP_EXTRA_MAX = 200;

/** Checks the OTP form's number boxes; returns a message for the first problem, or the parsed values. */
export function parseOtpSettings(input: { length: string; expiry: string; extra: string }):
  | { error: string }
  | { error: null; length: number; expiry: number; extra: string | undefined } {
  const length = Number(input.length);
  if (!Number.isInteger(length) || length < OTP_LENGTH_RANGE.min || length > OTP_LENGTH_RANGE.max) {
    return { error: `OTP length must be a whole number from ${OTP_LENGTH_RANGE.min} to ${OTP_LENGTH_RANGE.max}.` };
  }
  const expiry = Number(input.expiry);
  if (!Number.isInteger(expiry) || expiry < OTP_EXPIRY_RANGE.min || expiry > OTP_EXPIRY_RANGE.max) {
    return { error: `Expiry must be a whole number of minutes from ${OTP_EXPIRY_RANGE.min} to ${formatCount(OTP_EXPIRY_RANGE.max)}.` };
  }
  const extra = input.extra.trim();
  if (extra.length > OTP_EXTRA_MAX) return { error: `Extra message values can be at most ${OTP_EXTRA_MAX} characters.` };
  return { error: null, length, expiry, extra: extra || undefined };
}

/** The cost line under the credit count; null estimate means no charge has been reported yet. */
export function estimateLine(preview: { rate_per_sms: number | null; estimated_amount: number | null }): { text: string; known: boolean } {
  if (preview.estimated_amount == null || preview.rate_per_sms == null) {
    return { text: "Cost shows after your first SMS is charged", known: false };
  }
  return {
    text: `≈ ${formatRupees(preview.estimated_amount)} (about ${formatRupees(preview.rate_per_sms)} per SMS, based on your recent charges)`,
    known: true,
  };
}

export function canRescheduleCampaign(status: string): boolean {
  return status === "scheduled";
}

/** A campaign still being built can be cancelled but not moved to another time. */
export function canCancelCampaign(status: string): boolean {
  return status === "scheduled" || status === "preparing";
}

export function canDeleteCampaign(status: string): boolean {
  return status === "completed" || status === "cancelled";
}

/** ISO instant -> value for a datetime-local input (browser-local time, minute precision). */
export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** datetime-local value -> ISO string with offset (UTC "Z"); null when empty or invalid. */
export function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

const OTP_ACTION_LABELS: Record<string, string> = { send: "Sent", resend: "Resent", verify: "Checked" };

export function otpActionLabel(action: string): string {
  return OTP_ACTION_LABELS[action] ?? action;
}

/** Delivery column of the OTP history: "—" until the operator reports back. */
export function otpDelivery(status: string | null | undefined): { label: string; tone: Tone | null } {
  if (status === "delivered") return { label: "Delivered", tone: "success" };
  if (status === "failed") return { label: "Failed", tone: "danger" };
  return { label: "—", tone: null };
}

// ---- Contacts and recipients ----

export type ContactsSub = "contacts" | "groups";

/** The ?tab= value on the Contacts page, defaulting to contacts for anything unknown. */
export function parseContactsSub(value: string | null | undefined): ContactsSub {
  return value === "groups" ? "groups" : "contacts";
}

export const MAX_PASTED_NUMBERS = 5000;
/** The Type numbers table holds at most this many rows; more belong in the Address Book. */
export const MAX_TYPED_ROWS = 100;
export const CONSENT_LABEL = "Everyone on this list agreed to get promotional SMS from us";
export const CONSENT_HINT = "Leave this off and these contacts only get service SMS (like order updates and OTPs), never promotions.";

/** Split pasted text into one entry per number (newlines, commas, semicolons and spaces all separate). */
export function parseNumbers(text: string): string[] {
  return text.split(/[\s,;]+/).map((n) => n.trim()).filter(Boolean);
}

// ---- The one Send SMS form: numbers, template choice, request body ----

export type NumbersMode = "contact" | "list" | "leads";
export const NUMBERS_MODE_LABELS: Record<NumbersMode, string> = { contact: "Type numbers", list: "Address Book", leads: "Leads" };

/** sessionStorage key the Address Book uses to hand picked contacts' numbers to Send SMS. */
export const SEND_PREFILL_KEY = "sms:send-prefill";

/**
 * What Send SMS should start with when opened from the Address Book: ?groups=a,b picks those groups
 * (Address Book tab); ?numbers=1 puts the numbers the Address Book stored into the Type numbers box.
 */
export function sendPrefill(search: string, stored: string | null): Partial<NumbersState> | null {
  const q = new URLSearchParams(search);
  const groupIds = (q.get("groups") ?? "")
    .split(",")
    .map((g) => g.trim())
    .filter((g) => /^[0-9a-f-]{36}$/i.test(g))
    .slice(0, MAX_LIST_GROUPS);
  if (groupIds.length > 0) return { mode: "list", groupIds };
  if (q.get("numbers") === "1" && stored?.trim()) return { mode: "contact", numbersText: stored.trim() };
  return null;
}
export const MAX_LIST_GROUPS = 50;
export const MAX_LIST_CONTACTS = 50_000;

/** One line of the Type numbers table: a mobile number and the value typed for each variable. */
export interface TypedRow {
  phone: string;
  /** Indexed by variable position. */
  values: string[];
}

export interface NumbersState {
  mode: NumbersMode;
  /** Contact mode: typed or pasted numbers. */
  numbersText: string;
  /** Type numbers with a value per number: the table rows. */
  rows: TypedRow[];
  groupIds: string[];
  leadIds: string[];
  /** The promotional consent tick (Contact only). */
  consent: boolean;
}

export const EMPTY_NUMBERS: NumbersState = { mode: "contact", numbersText: "", rows: [], groupIds: [], leadIds: [], consent: false };

function sameList(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

/**
 * Apply a change to the numbers step. The promotional consent tick belongs to one specific audience,
 * so any change to who gets the SMS (mode, typed text, groups, leads) clears it.
 * A patch that only touches `consent` keeps it.
 */
export function withNumbersChange(prev: NumbersState, patch: Partial<NumbersState>): NumbersState {
  const next = { ...prev, ...patch };
  const audienceChanged =
    next.mode !== prev.mode ||
    next.numbersText !== prev.numbersText ||
    // Only the table's numbers are the audience; editing a typed value keeps the tick.
    !sameList(next.rows.map((r) => r.phone.trim()), prev.rows.map((r) => r.phone.trim())) ||
    !sameList(next.groupIds, prev.groupIds) ||
    !sameList(next.leadIds, prev.leadIds);
  return audienceChanged ? { ...next, consent: false } : next;
}

/** The loose numbers a Contact send carries (the table's phones when `typed`). */
export function looseNumbers(n: NumbersState, typed = false): string[] {
  if (n.mode !== "contact") return [];
  if (typed) return n.rows.map((r) => r.phone.trim()).filter(Boolean);
  return parseNumbers(n.numbersText);
}

/** Whether the numbers step has what it needs. Promotional + Contact also needs the consent tick. */
export function numbersReady(n: NumbersState, promotional: boolean, typed = false): boolean {
  if (n.mode === "leads") return n.leadIds.length > 0;
  if (n.mode === "list") return n.groupIds.length > 0 && n.groupIds.length <= MAX_LIST_GROUPS;
  const count = looseNumbers(n, typed).length;
  if (count === 0 || count > MAX_PASTED_NUMBERS) return false;
  if (typed && count > MAX_TYPED_ROWS) return false;
  return !promotional || n.consent;
}

/** The recipient fields of a preview/create request, per the API contract. */
export function buildRecipients(n: NumbersState, promotional: boolean, typed?: { varCount: number }): SmsRecipients {
  if (n.mode === "leads") return { source: "leads", lead_ids: n.leadIds };
  if (n.mode === "list") return { source: "contacts", group_ids: n.groupIds };
  let out: SmsRecipients = { source: "numbers", numbers: looseNumbers(n) };
  if (typed) {
    const filled = n.rows.filter((r) => r.phone.trim());
    out = {
      source: "numbers",
      numbers: filled.map((r) => r.phone.trim()),
      typed_values: filled.map((r) => Array.from({ length: typed.varCount }, (_, i) => (r.values[i] ?? "").trim())),
    };
  }
  if (promotional) out.consent_confirmed = n.consent;
  return out;
}

/** Variable positions (below varCount) whose source is "typed", i.e. values typed per number. */
export function typedVarIndexes(map: (SmsVarSource | null)[], varCount: number): number[] {
  const out: number[] = [];
  for (let i = 0; i < varCount; i++) if (map[i]?.source === "typed") out.push(i);
  return out;
}

/** The first problem in the Type numbers table, or null. Fully empty rows are ignored. */
export function typedRowsProblem(rows: TypedRow[], typedIdx: number[]): string | null {
  let count = 0;
  for (let r = 0; r < rows.length; r++) {
    const row = rows[r];
    const phoneBlank = !row.phone.trim();
    const blankAt = typedIdx.filter((i) => !(row.values[i] ?? "").trim());
    if (phoneBlank && blankAt.length === typedIdx.length) continue;
    count++;
    if (phoneBlank) return `Add the mobile number on row ${r + 1}.`;
    if (blankAt.length > 0) return `Fill Variable ${blankAt[0] + 1} on row ${r + 1}.`;
  }
  if (count > MAX_TYPED_ROWS) return `Up to ${MAX_TYPED_ROWS} numbers can be typed here. For more, upload them to the Address Book.`;
  return null;
}

/** True when the picked template has a variable typed per number (Contact mode only). */
export function usesTypedRows(input: SendFormInput): boolean {
  return !input.manual && input.numbers.mode === "contact" && typedVarIndexes(input.varMap, templateVarCount(input.template)).length > 0;
}

/** Turn the numbers typed into Type numbers into table rows (one per number, no values yet). */
export function seedTypedRows(numbersText: string): TypedRow[] {
  const rows: TypedRow[] = parseNumbers(numbersText)
    .slice(0, MAX_TYPED_ROWS)
    .map((phone) => ({ phone, values: [] }));
  return rows.length > 0 ? rows : [{ phone: "", values: [] }];
}

/** The phones in the table, one per line, for the plain numbers box. */
export function rowsToNumbersText(rows: TypedRow[]): string {
  return rows
    .map((r) => r.phone.trim())
    .filter(Boolean)
    .join("\n");
}

/**
 * Paste tab-separated rows (copied from Excel) into the table, starting at a cell. Columns are the
 * phone, then each typed variable in order. Returns a new array; rows stop at MAX_TYPED_ROWS.
 */
export function pasteIntoRows(rows: TypedRow[], startRow: number, startCol: number, text: string, typedIdx: number[]): TypedRow[] {
  const lines = text.split(/\r?\n/);
  if (lines[lines.length - 1] === "") lines.pop();
  const next: TypedRow[] = rows.map((r) => ({ phone: r.phone, values: [...r.values] }));
  const columns = typedIdx.length + 1;
  lines.forEach((line, r) => {
    const target = startRow + r;
    if (target >= MAX_TYPED_ROWS) return;
    while (next.length <= target) next.push({ phone: "", values: [] });
    line.split("\t").forEach((cell, c) => {
      const col = startCol + c;
      if (col >= columns) return;
      const value = cell.trim();
      if (col === 0) {
        next[target].phone = value;
        return;
      }
      const idx = typedIdx[col - 1];
      while (next[target].values.length <= idx) next[target].values.push("");
      next[target].values[idx] = value;
    });
  });
  return next;
}

/** Whether a template reads like a one-time password message (the app should make OTPs itself). */
export function looksLikeOtp(message: string): boolean {
  return /\b(otp|one[\s-]?time password|verification code)\b/i.test(message);
}

/** Which fields endpoint feeds the {#var#} source dropdown for these numbers. */
export function fieldsSourceFor(mode: NumbersMode): SmsRecipientSource {
  return mode === "list" ? "contacts" : mode === "leads" ? "leads" : "numbers";
}

/** DLT entity (PE) and content-template IDs are plain numbers, 5 to 30 digits. */
export const ENTITY_ID_MESSAGE = "The DLT entity ID must be 5 to 30 digits (numbers only).";
export const DLT_TEMPLATE_ID_MESSAGE = "The DLT template ID must be 5 to 30 digits (numbers only).";

export function isValidEntityId(id: string): boolean {
  return /^\d{5,30}$/.test(id.trim());
}

/** DLT's template categories, worded the way Bulk9's panel shows them. */
export const CATEGORY_LABELS = { service: "Service Implicit", promotional: "Service Explicit / Promo" } as const;

/** "Service Implicit" / "Service Explicit / Promo", or "Set by DLT" when Bulk9 didn't report it. */
export function categoryLabel(type: string | null | undefined): string {
  return type === "service" || type === "promotional" ? CATEGORY_LABELS[type] : "Set by DLT";
}

export function isValidDltTemplateId(id: string): boolean {
  return /^\d{5,30}$/.test(id.trim());
}

/** "Type my own": the DLT IDs and the exact approved text, typed by the client. */
export interface ManualInput { sender_id: string; entity_id: string; dlt_template_id: string; message: string }

export const EMPTY_MANUAL: ManualInput = { sender_id: "", entity_id: "", dlt_template_id: "", message: "" };

export const MANUAL_WARNING =
  "The text must match your DLT-approved template exactly, with every {#var#} replaced by the real value. If it doesn't match, the SMS fails and the credit is still used.";

/** The first thing missing in a "Type my own" message, or null. */
export function manualProblem(m: ManualInput): string | null {
  if (!m.sender_id || !m.entity_id) return "Pick the sender ID.";
  if (!isValidDltTemplateId(m.dlt_template_id)) return "Enter the DLT template ID (the long number from your DLT portal).";
  if (!m.message.trim()) return "Type the message.";
  if (countVars(m.message) > 0) return "Replace each {#var#} with the exact text to send.";
  return null;
}

export interface SendFormInput {
  /** The approved template picked in step 1; null until one is chosen. */
  template: Pick<SmsTemplate, "id" | "message" | "template_type" | "var_count"> | null;
  /** Set when "Type my own" is picked instead of a template. */
  manual?: ManualInput | null;
  varMap: (SmsVarSource | null)[];
  numbers: NumbersState;
}

/** How many {#var#} the picked template needs (the template's own count, or what the wording shows). */
export function templateVarCount(t: Pick<SmsTemplate, "message" | "var_count"> | null): number {
  return t ? Math.max(t.var_count ?? 0, countVars(t.message)) : 0;
}

/** Service or promotional, per the picked template. null until one is chosen. */
export function sendType(input: SendFormInput): SmsTemplateType | null {
  if (input.template) return input.template.template_type === "promotional" ? "promotional" : "service";
  return null;
}

/** The first thing missing before the preview, or null when the form is ready. */
export function sendFormProblem(input: SendFormInput): string | null {
  const type = sendType(input);
  if (input.manual) {
    const p = manualProblem(input.manual);
    if (p) return p;
  } else {
    if (!input.template) return "Pick a template.";
    if (!isVariableMapComplete(input.varMap, templateVarCount(input.template))) return "Choose what fills each {#var#}.";
  }
  const typed = usesTypedRows(input);
  if (typed) {
    const rowProblem = typedRowsProblem(input.numbers.rows, typedVarIndexes(input.varMap, templateVarCount(input.template)));
    if (rowProblem) return rowProblem;
  }
  if (!numbersReady(input.numbers, type === "promotional", typed)) {
    const n = input.numbers;
    if (type === "promotional" && n.mode === "contact" && looseNumbers(n, typed).length > 0 && !n.consent) {
      return "Tick the consent box to send promotional SMS to these numbers.";
    }
    return "Add who should get it.";
  }
  return null;
}

/** The preview/create body (without name, send_at and idempotency key), or null if the form is not ready. */
export function buildSendRequest(input: SendFormInput): SmsCampaignPreviewRequest | null {
  if (sendFormProblem(input)) return null;
  const promotional = sendType(input) === "promotional";
  const recipients = buildRecipients(
    input.numbers,
    promotional,
    usesTypedRows(input) ? { varCount: templateVarCount(input.template) } : undefined,
  );
  if (input.manual) {
    const m = input.manual;
    return {
      kind: "manual",
      manual: { sender_id: m.sender_id, entity_id: m.entity_id, dlt_template_id: m.dlt_template_id.trim(), message: m.message.trim() },
      ...recipients,
    };
  }
  const t = input.template!;
  return {
    template_id: t.id,
    variable_map: input.varMap.slice(0, templateVarCount(t)) as SmsVarSource[],
    ...recipients,
  };
}

/**
 * One idempotency key per exact request. The same body, name and schedule reuse the key (a double
 * click or a retry after a lost reply cannot create a second campaign); any change gets a new key.
 */
export function nextIdempotencyKey(
  prev: { signature: string; key: string } | null,
  signature: string,
  makeKey: () => string,
): { signature: string; key: string } {
  return prev && prev.signature === signature ? prev : { signature, key: makeKey() };
}

/** "SMS 3 Nov 18:05", in Indian time. */
export function defaultSendName(now: Date): string {
  const p: Record<string, string> = {};
  for (const part of new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(now)) {
    p[part.type] = part.value;
  }
  return `SMS ${p.day} ${p.month} ${p.hour}:${p.minute}`;
}

/** CSV the client can download for rows an upload skipped. */
export function skippedRowsCsv(rows: SmsSkippedRow[]): string {
  const lines = rows.map((r) => [String(r.row), csvCell(r.value, true), csvCell(r.reason, true)].join(","));
  return ["Row,Value,Reason", ...lines].join("\r\n");
}

// ---- Message length (mirrors segments() in backend/app/services/sms_campaigns.py) ----

const GSM_BASIC = new Set(
  "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?" +
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà",
);
const GSM_EXT = new Set("^{}\\[~]|€\f");

export interface SmsLength { length: number; parts: number; unicode: boolean }

/** GSM-7 text is 160 per SMS (153 per part when split); anything else is Unicode, 70 (67 per part). */
export function smsSegments(text: string): SmsLength {
  const t = text ?? "";
  let gsm = true;
  let gsmLength = 0;
  for (const c of t) {
    if (GSM_EXT.has(c)) gsmLength += 2;
    else if (GSM_BASIC.has(c)) gsmLength += 1;
    else {
      gsm = false;
      break;
    }
  }
  if (gsm) return { length: gsmLength, parts: gsmLength <= 160 ? 1 : Math.ceil(gsmLength / 153), unicode: false };
  // JS string length counts UTF-16 units, same as the backend (emoji count twice).
  const units = t.length;
  return { length: units, parts: units <= 70 ? 1 : Math.ceil(units / 67), unicode: true };
}

export const UNICODE_NOTE = "Unicode message (e.g. Tamil or emoji): 70 characters per SMS";

/** "123 characters · 1 SMS" */
export function smsCounterLine(text: string): string {
  if (!text) return "0 characters · 0 SMS";
  const { length, parts } = smsSegments(text);
  return `${formatCount(length)} character${length === 1 ? "" : "s"} · ${formatCount(parts)} SMS`;
}

// ---- "Send from your own app" code examples ----

export const DEV_API_URL = "https://sms.anrilaitech.com/dev/bulkV2";
export const KEY_PLACEHOLDER = "YOUR_API_KEY";

/** First 4 characters, then dots. Short keys show only dots. */
export function maskKey(key: string): string {
  return key.length > 4 ? `${key.slice(0, 4)}••••` : "••••";
}

export interface DevRequestInput {
  senderId: string;
  /** The template's message_id (what the API calls "message"). */
  messageId: string;
  variables: string[];
  numbers: string[];
  apiKey: string;
}

function devBody(i: DevRequestInput) {
  const body: Record<string, string> = { route: "dlt", sender_id: i.senderId, message: i.messageId };
  // A "|" would shift every later variable, so it is dropped.
  const vars = i.variables.map((v) => v.replace(/\|/g, "").trim());
  if (vars.length > 0) body.variables_values = vars.join("|");
  body.numbers = i.numbers.map((n) => n.trim()).filter(Boolean).join(",");
  return body;
}

export function buildCurl(i: DevRequestInput): string {
  const json = JSON.stringify(devBody(i), null, 2).replace(/'/g, "'\\''");
  return `curl -X POST ${DEV_API_URL} \\\n  -H "authorization: ${i.apiKey}" \\\n  -H "Content-Type: application/json" \\\n  -d '${json}'`;
}

export function buildPython(i: DevRequestInput): string {
  const body = JSON.stringify(devBody(i), null, 4);
  return [
    "import requests",
    "",
    `url = "${DEV_API_URL}"`,
    `headers = {"authorization": "${i.apiKey}", "Content-Type": "application/json"}`,
    `payload = ${body}`,
    "",
    "response = requests.post(url, json=payload, headers=headers, timeout=30)",
    "print(response.status_code, response.text)",
  ].join("\n");
}

export const CREDIT_MIN = 100;
export const CREDIT_MAX = 1_000_000;
export const CREDIT_NOTE_MAX = 300;

/** Why an Add credit amount is refused, or null when it is a whole ₹100 to ₹10,00,000. */
export function creditAmountError(raw: string): string | null {
  const v = raw.trim();
  const n = Number(v);
  if (v && /^\d+$/.test(v) && n >= CREDIT_MIN && n <= CREDIT_MAX) return null;
  return `Enter a whole amount between ₹${CREDIT_MIN.toLocaleString("en-IN")} and ₹${CREDIT_MAX.toLocaleString("en-IN")}.`;
}

/** "3 Nov", in IST. Empty for a bad date. */
export function requestedOn(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
}

export interface SummaryRow { label: string; value: string; bad?: true }

/** The Send SMS side panel: what goes out, what it costs, what you have. Dashes until Preview runs. */
export function sendSummary(input: { preview: SmsPreview | null; parts: number; balance: SmsBalance | null }): SummaryRow[] {
  const { preview: p, parts, balance: b } = input;
  const cost = p ? estimateLine(p) : null;
  const balance: SummaryRow = {
    label: "Balance",
    value: b ? `${formatCount(b.sms_count)} SMS${b.wallet != null ? ` · ${formatRupees(b.wallet)}` : ""}` : "—",
  };
  if (p && b && b.sms_count < p.total_segments) balance.bad = true;
  return [
    { label: "Recipients", value: p ? formatCount(p.eligible_count) : "—" },
    { label: "SMS each", value: formatCount(parts) },
    { label: "Credits needed", value: p ? formatCount(p.total_segments) : "—" },
    { label: "Estimated cost", value: p && cost?.known && p.estimated_amount != null ? `≈ ${formatRupees(p.estimated_amount)}` : "—" },
    balance,
  ];
}

/** Report periods offered as chips on Delivery Reports (days, ending today in IST). */
export const REPORT_PERIODS = [
  { days: 1, label: "Today" },
  { days: 7, label: "Last 7 days" },
  { days: 30, label: "Last 30 days" },
] as const;

/**
 * One send's progress for the Reports list: delivered out of everyone it went to, failed, and still
 * on its way (waiting, sending, with the operator or being checked). `pct` is null until anyone was counted.
 */
export function sendProgress(counts: Partial<Record<SmsMessageStatus, number>>, total: number) {
  const n = (k: SmsMessageStatus) => Number(counts[k]) || 0;
  const delivered = n("delivered");
  const failed = n("failed");
  const onTheWay = n("queued") + n("sending") + n("submitted") + n("unknown");
  return { delivered, failed, onTheWay, total, pct: total > 0 ? Math.round((delivered / total) * 100) : null };
}

/** Messages still on their way in a period's status counts (waiting + sending + with the operator + checking). */
export function onTheWayCount(anril: Record<string, number> | null | undefined): number {
  const n = (k: string) => Number(anril?.[k]) || 0;
  return n("queued") + n("sending") + n("submitted") + n("unknown");
}

/** True when the text carries a link: http(s)://, www., or a bare domain such as play.google.com/x. */
export function hasLink(text: string | null | undefined): boolean {
  if (!text) return false;
  if (/https?:\/\//i.test(text) || /\bwww\./i.test(text)) return true;
  return /(?:^|[^@\w.-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:com|in|co|org|net|io|app|me|ly|gl|page|link|store|shop|online|site|xyz|info|biz|edu|gov)\b(?:\/|\?|#|\s|$|[.,;:!)])/i.test(text);
}

const ANRIL_REASONS = new Set(["Opted out", "No SMS consent (promotional template)", "Not an Indian mobile number", "Duplicate number"]);

const DLT_REASONS: { test: RegExp; text: string }[] = [
  { test: /\bcta\b|url.*(not.*match|whitelist|not.*regist)|link.*(not.*match|whitelist)/, text: "Blocked: the link isn't whitelisted on your DLT portal" },
  { test: /templ.*(mismatch|not.*match|not.*found|invalid|not.*approved|not.*regist|variable)|content.*(mismatch|not.*match|invalid|not.*approved)|message.*(not.*match|mismatch)/, text: "Blocked: the wording doesn't match the approved DLT template" },
  { test: /(header|sender|sid|cli).*(not.*(regist|found|valid|active|approved)|invalid|inactive|blocked|expired|mismatch)|(unregistered|invalid|inactive).*(header|sender)/, text: "Blocked: the sender ID isn't registered or active on DLT" },
  { test: /entity|pe.?tm|tm.?chain|telemarketer|binding|chain.*(not|invalid|missing)|principal/, text: "Blocked: your DLT entity isn't linked to the telemarketer" },
  { test: /consent|dnd|ncpr|ndnc|do.?not.?disturb|preference|opt.?out|blocked.*number|number.*blocked/, text: "Blocked: the number is on DND or has no consent" },
  { test: /black.?list/, text: "Number is blacklisted" },
  { test: /invalid.*(number|mobile|msisdn|destination|subscriber)|(number|mobile|msisdn|destination).*invalid|wrong.*number|bad.*number|incorrect.*number/, text: "Invalid mobile number" },
  { test: /expire|absent|switched.?off|unreachable|out.?of.?(coverage|reach)|handset|not.?reachable|subscriber.*(busy|unavailable)|phone.*off/, text: "Phone unreachable (switched off or out of coverage)" },
];

/**
 * Plain English for a DLT / operator failure code or description. `code` is the raw text as
 * received (null when there was none), so the screen can keep it in a tooltip.
 */
export function dltReason(raw: string | null | undefined): { text: string; code: string | null } {
  const code = (raw ?? "").trim();
  if (!code) return { text: "", code: null };
  // Anril's own reasons (backend sms_campaigns R_* and its full sentences) are already plain English.
  if (ANRIL_REASONS.has(code) || code.endsWith(".")) return { text: code, code: null };
  const norm = code.toLowerCase().replace(/[_\-\s]+/g, " ");
  const hit = DLT_REASONS.find((r) => r.test.test(norm));
  if (hit) return { text: hit.text, code };
  // Only a CODE_LIKE_THIS gets reworded; a sentence from the operator is shown as written.
  if (/[a-z]/.test(code)) return { text: code, code: null };
  const words = code.replace(/_+/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
  return { text: words.charAt(0).toUpperCase() + words.slice(1), code };
}

// ---- Send SMS: Saved templates / DLT Manual tabs and the preview popup ----

/** Each sender that has at least one ready template, with how many, in A–Z order. */
export function sendersFrom(templates: Pick<SmsTemplate, "sender_id">[]): { sender_id: string; count: number }[] {
  const by = new Map<string, number>();
  for (const t of templates) by.set(t.sender_id, (by.get(t.sender_id) ?? 0) + 1);
  return Array.from(by.entries())
    .map(([sender_id, count]) => ({ sender_id, count }))
    .sort((a, b) => a.sender_id.localeCompare(b.sender_id));
}

/** Whitespace-insensitive, case-sensitive: DLT treats "Class" and "class" as different text. */
function sameWording(a: string, b: string): boolean {
  const norm = (s: string) => s.trim().replace(/\s+/g, " ");
  return norm(a) === norm(b);
}

/**
 * The saved template of this sender whose wording is exactly this text, or null. Only templates
 * without {#var#} can match a typed DLT Manual message (the typed text has real values in place).
 */
export function matchSavedTemplate<T extends Pick<SmsTemplate, "sender_id" | "message">>(
  templates: T[],
  senderId: string,
  message: string,
): T | null {
  if (!senderId || !message.trim()) return null;
  return templates.find((t) => t.sender_id === senderId && sameWording(t.message, message)) ?? null;
}

const CURLY_RE = /[‘’‚‛“”„‟]/;

/** True when the text has a curly quote (’ “ ”), which turns the SMS into Unicode and rarely matches DLT. */
export function hasCurlyQuotes(text: string): boolean {
  return CURLY_RE.test(text);
}

/** The same text with curly quotes made straight (’ → ', “ ” → "). */
export function straightenQuotes(text: string): string {
  return text.replace(/[‘’‚‛]/g, "'").replace(/[“”„‟]/g, '"');
}

/** "English · 160 characters per SMS · this message = 1 SMS" or "Unicode (Tamil) · 70 characters per SMS · …". */
export function languageLine(text: string): string {
  const { parts, unicode } = smsSegments(text);
  const lang = !unicode ? "English" : /[஀-௿]/.test(text) ? "Unicode (Tamil)" : "Unicode";
  return `${lang} · ${unicode ? 70 : 160} characters per SMS · this message = ${formatCount(parts)} SMS`;
}

/** The client's own price per SMS, the same figure as the "Your plan" card (wallet ₹ ÷ SMS left). */
export function planRate(balance: SmsBalance | null | undefined): number | null {
  if (!balance || balance.wallet == null) return null;
  const left = Number(balance.sms_count);
  return left > 0 && balance.wallet > 0 ? balance.wallet / left : null;
}

export interface PopupCost {
  credits: number;
  /** Credits left after this send; negative when there aren't enough. */
  left: number | null;
  rate: number | null;
  rupees: number | null;
}

/** SMS credits first, then ₹ at the client's plan price. */
export function popupCost(totalSegments: number, balance: SmsBalance | null | undefined): PopupCost {
  const rate = planRate(balance);
  return {
    credits: totalSegments,
    left: balance ? Number(balance.sms_count) - totalSegments : null,
    rate,
    rupees: rate != null ? Math.round(rate * totalSegments * 100) / 100 : null,
  };
}

/**
 * Skipped numbers per reason, largest first. The preview lists at most 1,000; `more` is how many
 * skipped people that list leaves out.
 */
export function skipCounts(preview: Pick<SmsPreview, "excluded" | "excluded_total">): { rows: { reason: string; count: number }[]; more: number } {
  const rows = groupExcluded(preview.excluded).map((g) => ({ reason: g.reason, count: g.leads.length }));
  const total = preview.excluded_total ?? preview.excluded.length;
  return { rows, more: Math.max(0, total - preview.excluded.length) };
}

/** "KELIR · 14893 · 7 Nov" (or "KELIR · DLT Manual · 7 Nov"), in Indian time. Falls back to the old "SMS 3 Nov 18:05". */
export function sendNameFor(senderId: string, label: string, now: Date): string {
  if (!senderId) return defaultSendName(now);
  const day = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", day: "numeric", month: "short" }).format(now);
  return `${senderId} · ${label} · ${day}`;
}
