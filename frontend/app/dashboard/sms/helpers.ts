/** Pure helpers for the SMS page (kept out of components so they can be unit-tested). */
import type {
  SmsCampaignPreviewRequest,
  SmsMessageStatus,
  SmsPreviewExcluded,
  SmsRecipients,
  SmsRecipientSource,
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

/**
 * Drop mappings that point at a contact field the current audience no longer offers. Fixed-text
 * sources stay. Returns the same array when nothing changed, so it is safe in a state update.
 */
export function pruneVarMap(map: (SmsVarSource | null)[], availableKeys: string[]): (SmsVarSource | null)[] {
  let changed = false;
  const next = map.map((v) => {
    if (v && v.source === "field" && !availableKeys.includes(v.value)) {
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
  peTm: boolean | undefined;
  balance: number | undefined;
  needed: number;
  support: string | null;
}): SendBlock {
  if (input.loading) return { blocked: true, reason: null };
  if (input.peTm === undefined) return { blocked: true, reason: "Couldn't check your SMS setup. Refresh and try again." };
  if (input.peTm !== true) return { blocked: true, reason: "Waiting for your account manager to confirm PE–TM binding." };
  if (input.balance === undefined) return { blocked: true, reason: "Couldn't check your SMS balance. Refresh and try again." };
  if (input.balance < input.needed) {
    return {
      blocked: true,
      reason: `Not enough SMS balance: this campaign needs ${formatCount(input.needed)} SMS and you have ${formatCount(input.balance)}. Contact ${input.support || SUPPORT_FALLBACK} to top up.`,
    };
  }
  return { blocked: false, reason: null };
}

export interface SetupStep { key: "connected" | "templates" | "pe_tm" | "balance"; label: string; done: boolean; hint: string | null }

export function setupSteps(input: { templatesReady: boolean; peTm: boolean; smsCount: number | null | undefined }): SetupStep[] {
  const hasBalance = (input.smsCount ?? 0) > 0;
  return [
    { key: "connected", label: "Connected to SMS", done: true, hint: null },
    { key: "templates", label: "Add your DLT entity, sender and approved templates", done: input.templatesReady, hint: "Templates tab" },
    { key: "pe_tm", label: "PE–TM binding confirmed", done: input.peTm, hint: "Done by your account manager" },
    { key: "balance", label: "SMS balance", done: hasBalance, hint: input.smsCount == null ? null : `${formatCount(input.smsCount)} SMS` },
  ];
}

export function setupComplete(steps: SetupStep[]): boolean {
  return steps.every((s) => s.done);
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

export function canDeleteTemplateRequest(status: string): boolean {
  return status === "requested" || status === "rejected";
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
export const CONSENT_LABEL = "Everyone on this list agreed to get promotional SMS from us";
export const CONSENT_HINT = "Leave this off and these contacts only get service SMS (like order updates and OTPs), never promotions.";

/** Split pasted text into one entry per number (newlines, commas, semicolons and spaces all separate). */
export function parseNumbers(text: string): string[] {
  return text.split(/[\s,;]+/).map((n) => n.trim()).filter(Boolean);
}

// ---- The one Send SMS form: numbers, template choice, request body ----

export type NumbersMode = "contact" | "list" | "excel" | "leads";
export const NUMBERS_MODE_LABELS: Record<NumbersMode, string> = { contact: "Contact", list: "List", excel: "Excel", leads: "Leads" };
export const MAX_LIST_GROUPS = 50;
export const MAX_LIST_CONTACTS = 50_000;

/** What the server said about an uploaded file (kept so the summary survives switching modes). */
export interface ExcelInfo { fileName: string; total: number; skipped_total: number; phone_column: string | null; skipped: SmsSkippedRow[] }

export interface NumbersState {
  mode: NumbersMode;
  /** Contact mode: typed or pasted numbers. */
  numbersText: string;
  /** Excel mode: numbers the server read from the uploaded file. */
  excelNumbers: string[];
  excel: ExcelInfo | null;
  groupIds: string[];
  leadIds: string[];
  /** The promotional consent tick (Contact and Excel only). */
  consent: boolean;
}

export const EMPTY_NUMBERS: NumbersState = { mode: "contact", numbersText: "", excelNumbers: [], excel: null, groupIds: [], leadIds: [], consent: false };

function sameList(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

/**
 * Apply a change to the numbers step. The promotional consent tick belongs to one specific audience,
 * so any change to who gets the SMS (mode, typed text, a new Excel read, groups, leads) clears it.
 * A patch that only touches `consent` keeps it.
 */
export function withNumbersChange(prev: NumbersState, patch: Partial<NumbersState>): NumbersState {
  const next = { ...prev, ...patch };
  const audienceChanged =
    next.mode !== prev.mode ||
    next.numbersText !== prev.numbersText ||
    next.excel !== prev.excel ||
    !sameList(next.excelNumbers, prev.excelNumbers) ||
    !sameList(next.groupIds, prev.groupIds) ||
    !sameList(next.leadIds, prev.leadIds);
  return audienceChanged ? { ...next, consent: false } : next;
}

/** The loose numbers a Contact or Excel send carries. Excel numbers are sent exactly like pasted ones. */
export function looseNumbers(n: NumbersState): string[] {
  if (n.mode === "contact") return parseNumbers(n.numbersText);
  if (n.mode === "excel") return n.excelNumbers;
  return [];
}

/** Whether the numbers step has what it needs. Promotional + Contact/Excel also needs the consent tick. */
export function numbersReady(n: NumbersState, promotional: boolean): boolean {
  if (n.mode === "leads") return n.leadIds.length > 0;
  if (n.mode === "list") return n.groupIds.length > 0 && n.groupIds.length <= MAX_LIST_GROUPS;
  const count = looseNumbers(n).length;
  if (count === 0 || count > MAX_PASTED_NUMBERS) return false;
  return !promotional || n.consent;
}

/** The recipient fields of a preview/create request, per the API contract. */
export function buildRecipients(n: NumbersState, promotional: boolean): SmsRecipients {
  if (n.mode === "leads") return { source: "leads", lead_ids: n.leadIds };
  if (n.mode === "list") return { source: "contacts", group_ids: n.groupIds };
  const out: SmsRecipients = { source: "numbers", numbers: looseNumbers(n) };
  if (promotional) out.consent_confirmed = n.consent;
  return out;
}

/** Which fields endpoint feeds the {#var#} source dropdown for these numbers. */
export function fieldsSourceFor(mode: NumbersMode): SmsRecipientSource {
  return mode === "list" ? "contacts" : mode === "leads" ? "leads" : "numbers";
}

/** The "Type my own" fields. */
export interface OwnDlt {
  sender_id: string;
  entity_id: string;
  dlt_template_id: string;
  template_type: SmsTemplateType;
  message: string;
}
export const EMPTY_OWN: OwnDlt = { sender_id: "", entity_id: "", dlt_template_id: "", template_type: "service", message: "" };

/** DLT entity (PE) and content-template IDs are plain numbers, 5 to 30 digits. */
export const ENTITY_ID_MESSAGE = "The DLT entity ID must be 5 to 30 digits (numbers only).";
export const DLT_TEMPLATE_ID_MESSAGE = "The DLT template ID must be 5 to 30 digits (numbers only).";
export const SENDER_ID_MESSAGE = "The Sender ID must be 3 to 6 letters or digits.";

export function isValidEntityId(id: string): boolean {
  return /^\d{5,30}$/.test(id.trim());
}

export function isValidDltTemplateId(id: string): boolean {
  return /^\d{5,30}$/.test(id.trim());
}

/** "Type my own" sender: 3 to 6 letters or digits (sent upper-cased). */
export function isValidOwnSenderId(id: string): boolean {
  return /^[A-Za-z0-9]{3,6}$/.test(id.trim());
}

export const OWN_VAR_ERROR = "Type my own can't have {#var#} in the message. Write the exact text to send, or pick a template that has variables.";

/** "Type my own" sends no per-person values, so a {#var#} in the message is refused. */
export function ownVarError(message: string): string | null {
  return countVars(message) > 0 ? OWN_VAR_ERROR : null;
}

export interface SendFormInput {
  /** "template" = an approved template is picked; "own" = Type my own; null = nothing chosen yet. */
  route: "template" | "own" | null;
  template: Pick<SmsTemplate, "id" | "message" | "template_type" | "var_count"> | null;
  varMap: (SmsVarSource | null)[];
  own: OwnDlt;
  numbers: NumbersState;
}

/** How many {#var#} the picked template needs (the template's own count, or what the wording shows). */
export function templateVarCount(t: Pick<SmsTemplate, "message" | "var_count"> | null): number {
  return t ? Math.max(t.var_count ?? 0, countVars(t.message)) : 0;
}

/** Service or promotional, per the route. null until a route is chosen. */
export function sendType(input: SendFormInput): SmsTemplateType | null {
  if (input.route === "own") return input.own.template_type;
  if (input.route === "template" && input.template) return input.template.template_type === "promotional" ? "promotional" : "service";
  return null;
}

/** The first thing missing before Preview, or null when the form is ready. */
export function sendFormProblem(input: SendFormInput): string | null {
  const type = sendType(input);
  if (!input.route) return "Pick a template or Type my own.";
  if (input.route === "template") {
    if (!input.template) return "Pick a template.";
    if (!isVariableMapComplete(input.varMap, templateVarCount(input.template))) return "Choose what fills each {#var#}.";
  } else {
    const o = input.own;
    if (!o.sender_id.trim()) return "Pick a Sender ID.";
    if (!isValidOwnSenderId(o.sender_id)) return SENDER_ID_MESSAGE;
    if (!o.entity_id.trim()) return "Enter the DLT entity ID.";
    if (!isValidEntityId(o.entity_id)) return ENTITY_ID_MESSAGE;
    if (!o.dlt_template_id.trim()) return "Enter the DLT template ID.";
    if (!isValidDltTemplateId(o.dlt_template_id)) return DLT_TEMPLATE_ID_MESSAGE;
    if (!o.message.trim()) return "Type the message.";
    const v = ownVarError(o.message);
    if (v) return v;
  }
  if (!numbersReady(input.numbers, type === "promotional")) {
    const n = input.numbers;
    if (type === "promotional" && (n.mode === "contact" || n.mode === "excel") && looseNumbers(n).length > 0 && !n.consent) {
      return "Tick the consent box to send promotional SMS to these numbers.";
    }
    return "Add who should get it.";
  }
  return null;
}

/**
 * The preview/create body (without name, send_at and idempotency key), or null if the form is
 * not ready. A picked template goes through the approved-template route; Type my own goes through
 * the DLT-IDs ("manual") route.
 */
export function buildSendRequest(input: SendFormInput): SmsCampaignPreviewRequest | null {
  if (sendFormProblem(input)) return null;
  const promotional = sendType(input) === "promotional";
  const recipients = buildRecipients(input.numbers, promotional);
  if (input.route === "own") {
    const o = input.own;
    return {
      kind: "manual",
      manual: {
        sender_id: o.sender_id.trim().toUpperCase(),
        entity_id: o.entity_id.trim(),
        dlt_template_id: o.dlt_template_id.trim(),
        template_type: o.template_type,
        message: o.message,
      },
      ...recipients,
    };
  }
  const t = input.template!;
  return {
    kind: "template",
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

/** "4,120 numbers · 18 skipped" after an Excel upload. */
export function excelSummary(r: { total: number; skipped_total: number }): string {
  const nums = `${formatCount(r.total)} number${r.total === 1 ? "" : "s"}`;
  return r.skipped_total > 0 ? `${nums} · ${formatCount(r.skipped_total)} skipped` : nums;
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
