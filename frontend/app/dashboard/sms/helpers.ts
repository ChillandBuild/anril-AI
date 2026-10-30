/** Pure helpers for the SMS page (kept out of components so they can be unit-tested). */
import type { SmsMessageStatus, SmsPreviewExcluded, SmsVarSource } from "@/lib/api";

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

/** Whole rupees or paise, never more than 4 decimals: 0.25 -> ₹0.25, 12 -> ₹12.00, 0.0625 -> ₹0.0625. */
export function formatRupees(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}

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

/** Every variable must have a field chosen or non-empty fixed text. */
export function isVariableMapComplete(map: (SmsVarSource | null)[], varCount: number): boolean {
  if (map.length < varCount) return false;
  for (let i = 0; i < varCount; i++) {
    const v = map[i];
    if (!v || !v.value || !v.value.trim()) return false;
  }
  return true;
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
  if (status === "sending") return "info";
  if (status === "scheduled") return "warn";
  return "neutral";
}

/** Pack label: "₹500 → 2,000 SMS". */
export function packLabel(amountRupees: number, smsCount: number): string {
  return `₹${amountRupees.toLocaleString("en-IN")} → ${smsCount.toLocaleString("en-IN")} SMS`;
}

/** Short, readable "Name" for a ledger kind coming from the server (snake_case). */
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
