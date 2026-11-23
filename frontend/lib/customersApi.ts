import useSWR from "swr";
import { API_URL, apiFetch, getAuthHeaders, type Lead, type LeadFilters, type LeadsSummary } from "@/lib/api";

/**
 * Customers screens (Batch H, #17): tags, "Came from" / "Leads only" filters, Send to calling, Feedback.
 * lib/api.ts is not touched: the extra list filters and the new calls live here and use the same apiFetch.
 * Shapes follow the CB1 (tags, filters, calling) and CB2 (feedback) backend contracts; anything the backend may
 * leave out is optional so an older backend never crashes a screen.
 */

/* ------------------------------------------------------------------ *
 * Customer list: the filters lib/api.ts does not know yet
 * ------------------------------------------------------------------ */

/** A row of the Customers list, plus the tag chips (absent until the backend sends them). */
export type LeadRow = Lead & { tags?: string[] };

export interface LeadFiltersX extends LeadFilters {
  /** "leads" = people who never bought. */
  only?: "leads";
  /** One of CAME_FROM_OPTIONS (qr, google_ads, ...). */
  came_from?: string;
  tag?: string;
}

export const CAME_FROM_OPTIONS: { value: string; label: string }[] = [
  { value: "all", label: "All" },
  { value: "qr", label: "QR code" },
  { value: "google_ads", label: "Google Ads" },
  { value: "meta_ad", label: "Meta ad" },
  { value: "instant_form", label: "Instant form" },
  { value: "website", label: "Website" },
  { value: "inbound", label: "Messaged you first" },
  { value: "organic", label: "Organic" },
  { value: "broadcast", label: "Campaign" },
  { value: "upload", label: "Uploaded list" },
];

const MAX_LIST_LIMIT = 200;

/** The query string for the Customers list, the cards above it and the download: one place, so the numbers match. */
export function buildLeadsQuery(
  params: LeadFiltersX & { page?: number; limit?: number; sort?: "newest" | "oldest" | "urgent" } = {},
): URLSearchParams {
  const qs = new URLSearchParams();
  if (params.segment) qs.set("segment", params.segment);
  if (params.buyer) qs.set("buyer", "true");
  if (params.group_id) qs.set("group_id", params.group_id);
  if (params.bought) qs.set("bought", params.bought);
  if (params.search) qs.set("search", params.search);
  if (params.assigned_to) qs.set("assigned_to", params.assigned_to);
  if (params.source_filter) qs.set("source_filter", params.source_filter);
  if (params.broadcast_id) qs.set("broadcast_id", params.broadcast_id);
  if (params.ad_campaign_id) qs.set("ad_campaign_id", params.ad_campaign_id);
  if (params.date_from) qs.set("date_from", params.date_from);
  if (params.date_to) qs.set("date_to", params.date_to);
  if (params.reply_window) qs.set("reply_window", params.reply_window);
  if (params.only) qs.set("only", params.only);
  if (params.came_from && params.came_from !== "all") qs.set("came_from", params.came_from);
  if (params.tag && params.tag.trim()) qs.set("tag", params.tag.trim());
  if (params.sort) qs.set("sort", params.sort);
  if (typeof params.page === "number" && Number.isFinite(params.page)) qs.set("page", String(params.page));
  if (typeof params.limit === "number" && Number.isFinite(params.limit)) {
    qs.set("limit", String(Math.min(Math.max(Math.trunc(params.limit), 1), MAX_LIST_LIMIT)));
  }
  return qs;
}

export async function fetchLeadsPage(
  params: LeadFiltersX & { page?: number; limit?: number; sort?: "newest" | "oldest" | "urgent" },
): Promise<{ data: LeadRow[]; total: number }> {
  const res = await apiFetch<{ data: LeadRow[]; total: number }>(`/api/v1/leads/?${buildLeadsQuery(params)}`);
  return { data: res.data || [], total: res.total ?? 0 };
}

export function fetchLeadsSummary(params: LeadFiltersX = {}): Promise<LeadsSummary> {
  return apiFetch<LeadsSummary>(`/api/v1/leads/summary?${buildLeadsQuery(params)}`);
}

export async function downloadLeadsCsv(params: LeadFiltersX = {}): Promise<void> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_URL}/api/v1/leads/export?${buildLeadsQuery(params)}`, { headers });
  if (!res.ok) throw new Error(`Export failed: ${res.status} ${res.statusText}`);
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `leads_${params.segment || "all"}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

const LIST_SWR = { revalidateOnFocus: true, revalidateOnReconnect: true, dedupingInterval: 5_000, errorRetryCount: 2, keepPreviousData: true };

export function useLeadsPageX(params: Parameters<typeof fetchLeadsPage>[0], enabled = true) {
  const key = enabled ? `customersList:${JSON.stringify(params)}` : null;
  return useSWR<{ data: LeadRow[]; total: number }>(key, () => fetchLeadsPage(params), LIST_SWR);
}

export function useLeadsSummaryX(params: LeadFiltersX, enabled = true) {
  const key = enabled ? `customersSummary:${JSON.stringify(params)}` : null;
  return useSWR<LeadsSummary>(key, () => fetchLeadsSummary(params), LIST_SWR);
}

/* ------------------------------------------------------------------ *
 * Tags
 * ------------------------------------------------------------------ */

export const MAX_TAG_LENGTH = 30;
export const MAX_TAGS_PER_PERSON = 10;

export interface TagCount {
  tag: string;
  count: number;
}

export interface TagChangeResult {
  added?: number;
  removed?: number;
  skipped_limit?: number;
}

/** One tag as typed: spaces tidied, at most 30 characters; null when nothing is left. */
export function cleanTag(raw: string): string | null {
  const tidy = raw.replace(/\s+/g, " ").trim().slice(0, MAX_TAG_LENGTH).trim();
  return tidy ? tidy : null;
}

/** "vip, diwali  ,VIP" -> ["vip", "diwali"]: split on commas, tidy, drop empties and repeats (any case, first spelling kept). */
export function parseTagInput(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of raw.split(",")) {
    const tag = cleanTag(part);
    if (!tag) continue;
    const key = tag.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(tag);
  }
  return out;
}

/** The tag list in whatever shape the backend sends it ([{tag,count}], {tags:[...]}, {data:[...]}, plain strings). */
export function normalizeTagList(raw: unknown): TagCount[] {
  const list: unknown =
    Array.isArray(raw) ? raw
      : raw && typeof raw === "object" ? ((raw as { tags?: unknown; data?: unknown }).tags ?? (raw as { data?: unknown }).data ?? [])
        : [];
  if (!Array.isArray(list)) return [];
  const out: TagCount[] = [];
  for (const item of list) {
    if (typeof item === "string") {
      const tag = cleanTag(item);
      if (tag) out.push({ tag, count: 0 });
    } else if (item && typeof item === "object") {
      const o = item as { tag?: unknown; name?: unknown; count?: unknown };
      const tag = typeof o.tag === "string" ? o.tag : typeof o.name === "string" ? o.name : "";
      if (tag) out.push({ tag, count: typeof o.count === "number" ? o.count : 0 });
    }
  }
  return out;
}

/** The one-line toast after tagging: "Tagged 12 people. 2 skipped: 10 tags is the most one person can have." */
export function describeTagResult(kind: "add" | "remove", result: TagChangeResult): string {
  const n = kind === "add" ? result.added ?? 0 : result.removed ?? 0;
  const people = `${n} ${n === 1 ? "tag" : "tags"}`;
  const head = kind === "add" ? `Added ${people}` : `Removed ${people}`;
  const skipped = result.skipped_limit ?? 0;
  if (skipped > 0) {
    return `${head}. ${skipped} skipped: ${MAX_TAGS_PER_PERSON} tags is the most one person can have.`;
  }
  return head;
}

export const tagsApi = {
  list: async (): Promise<TagCount[]> => normalizeTagList(await apiFetch<unknown>("/api/v1/lead-tags")),
  add: (leadIds: string[], tags: string[]) =>
    apiFetch<TagChangeResult>("/api/v1/lead-tags/add", { method: "POST", body: JSON.stringify({ lead_ids: leadIds, tags }) }),
  remove: (leadIds: string[], tags: string[]) =>
    apiFetch<TagChangeResult>("/api/v1/lead-tags/remove", { method: "POST", body: JSON.stringify({ lead_ids: leadIds, tags }) }),
};

/* ------------------------------------------------------------------ *
 * Send to calling
 * ------------------------------------------------------------------ */

export interface SendToCallingResult {
  added: number;
  already: number;
  said_stop: number;
  bought: number;
  closed: number;
  not_found: number;
  no_callers: boolean;
  added_ids?: string[];
}

/** Where an owner adds a caller. */
export const ADD_CALLER_HREF = "/dashboard/team";
export const NO_CALLERS_TEXT = "Add a caller in Call IQ › Team first";

/** "18 sent to calling · 3 said stop · 2 already bought · 4 already with a caller". Zero parts are left out. */
export function describeCallingResult(r: SendToCallingResult): string {
  const parts = [`${r.added} sent to calling`];
  if (r.said_stop > 0) parts.push(`${r.said_stop} said stop`);
  if (r.bought > 0) parts.push(`${r.bought} already bought`);
  if (r.already > 0) parts.push(`${r.already} already with a caller`);
  const cannot = (r.closed ?? 0) + (r.not_found ?? 0);
  if (cannot > 0) parts.push(`${cannot} can't be called`);
  return parts.join(" · ");
}

export const callingApi = {
  sendPeople: (leadIds: string[]) =>
    apiFetch<SendToCallingResult>("/api/v1/leads/send-to-calling", { method: "POST", body: JSON.stringify({ lead_ids: leadIds }) }),
  sendGroup: (groupId: string) =>
    apiFetch<SendToCallingResult>(`/api/v1/customer-groups/${encodeURIComponent(groupId)}/send-to-calling`, { method: "POST" }),
};

/** Reach (the campaign page) with a group already picked. Reach reads ?group=<id>. */
export function campaignHrefForGroup(groupId: string): string {
  return `/dashboard/outbound-leads?group=${encodeURIComponent(groupId)}`;
}

/** Follow-ups tab with a group already picked in the builder. */
export function followUpHrefForGroup(groupId: string): string {
  return `/dashboard/leads?tab=follow-ups&group=${encodeURIComponent(groupId)}`;
}

/* ------------------------------------------------------------------ *
 * Said stop: people on "Don't call" only
 * ------------------------------------------------------------------ */

export const DONT_CALL_LABEL = "Don't call (from a call)";

/** True for a Said-stop-list row that is there only because it is marked Don't call. Tolerates how the backend flags it. */
export function isDontCallRow(p: { source?: string | null; do_not_call?: boolean; opted_out_at?: string | null }): boolean {
  if (p.source === "do_not_call" || p.source === "dont_call") return true;
  return p.do_not_call === true && !p.opted_out_at && p.source == null;
}

/* ------------------------------------------------------------------ *
 * Feedback
 * ------------------------------------------------------------------ */

export interface FeedbackSettings {
  on: boolean;
  offer: string | null;
  review_link: string | null;
  /** What Meta says about the star message: none / pending / approved / rejected (any case). */
  template_status: string | null;
  cost_per_message_rupees?: number;
}

export interface FeedbackRow {
  id: string;
  lead_id: string | null;
  name: string | null;
  phone: string | null;
  stars: number | null;
  reason: string | null;
  staff_name: string | null;
  asked_at: string | null;
  answered_at?: string | null;
  status?: string | null;
}

export interface FeedbackReport {
  average: number | null;
  answered_pct: number | null;
  asked: number;
  answered: number;
  unhappy_open: FeedbackRow[];
  reasons: { text: string; count: number }[];
  by_staff: { staff_name: string | null; avg: number | null; count: number }[];
  recent: FeedbackRow[];
}

export interface TemplateStatusView {
  label: string;
  tone: "good" | "wait" | "bad" | "none";
}

/** What the star message's Meta status means for the owner: Waiting for Meta / Approved / Turned down / Not set up. */
export function feedbackTemplateStatus(status: string | null | undefined): TemplateStatusView {
  const s = (status ?? "").toLowerCase();
  if (s === "approved") return { label: "Approved", tone: "good" };
  if (["pending", "in_review", "submitted", "pending_deletion"].includes(s)) return { label: "Waiting for Meta", tone: "wait" };
  if (["rejected", "disabled", "paused", "flagged"].includes(s)) return { label: "Turned down", tone: "bad" };
  return { label: "Not set up", tone: "none" };
}

/** "about ₹0.86 per message". */
export function feedbackCostText(rupees: number | undefined): string {
  const n = typeof rupees === "number" && Number.isFinite(rupees) && rupees > 0 ? rupees : 0.86;
  return `about ₹${n.toFixed(2)} per message`;
}

/** "⭐⭐⭐ 3" style label for a 1-5 star rating. */
export function starsText(stars: number | null | undefined): string {
  if (!stars || stars < 1) return "No rating";
  const n = Math.min(5, Math.round(stars));
  return `${"⭐".repeat(n)} ${n}`;
}

/** An average like 4.3 (one decimal); "—" when nobody answered. */
export function averageText(avg: number | null | undefined): string {
  return typeof avg === "number" && Number.isFinite(avg) ? avg.toFixed(1) : "—";
}

/** "62%" or "—". */
export function percentText(pct: number | null | undefined): string {
  return typeof pct === "number" && Number.isFinite(pct) ? `${Math.round(pct)}%` : "—";
}

/** tel: link for a phone with or without +/spaces; null if there is no number. */
export function telHref(phone: string | null | undefined): string | null {
  const digits = (phone ?? "").replace(/[^\d+]/g, "");
  return digits.length >= 7 ? `tel:${digits.startsWith("+") ? digits : `+${digits}`}` : null;
}

const IST = "Asia/Kolkata";

/** YYYY-MM-DD for an instant, in India time. */
export function istDay(d: Date): string {
  return d.toLocaleDateString("en-CA", { timeZone: IST });
}

/** The last `days` days up to and including today, in India time. */
export function lastDaysRange(days: number, now: Date = new Date()): { from: string; to: string } {
  const to = istDay(now);
  const from = istDay(new Date(now.getTime() - (days - 1) * 24 * 60 * 60 * 1000));
  return { from, to };
}

export const feedbackApi = {
  settings: () => apiFetch<FeedbackSettings>("/api/v1/customer-feedback/settings"),
  saveSettings: (body: { on: boolean; offer: string }) =>
    apiFetch<FeedbackSettings>("/api/v1/customer-feedback/settings", { method: "PUT", body: JSON.stringify(body) }),
  setupTemplate: () =>
    apiFetch<{ status?: string | null; template_status?: string | null }>("/api/v1/customer-feedback/setup-template", { method: "POST" }),
  report: (range: { from: string; to: string }) =>
    apiFetch<FeedbackReport>(`/api/v1/customer-feedback/?${new URLSearchParams(range)}`),
  markFixed: (id: string) =>
    apiFetch<{ ok?: boolean }>(`/api/v1/customer-feedback/${encodeURIComponent(id)}/fixed`, { method: "POST" }),
};

/* ------------------------------------------------------------------ *
 * Customer page: new timeline events, totals and tags
 * ------------------------------------------------------------------ */

/** Events CB1 adds to the customer timeline. Every field but kind/at may be missing. */
export interface ExtraCustomerEvent {
  kind: "refund" | "visit" | "no_show" | "feedback";
  at: string;
  amount_paise?: number | null;
  method?: string | null;
  number?: number | null;
  service?: string | null;
  staff?: string | null;
  by?: string | null;
  stars?: number | null;
  reason?: string | null;
}

/** A booking event from the bookings table (the older "booked a visit" event only has for/note). */
export interface BookingEventFields {
  service?: string | null;
  staff?: string | null;
  status?: string | null;
  time?: string | null;
  for?: string | null;
  note?: string | null;
}

export interface CustomerProfileExtras {
  tags?: string[];
  totals?: { refunds_paise?: number; visits?: number; no_shows?: number; avg_stars?: number | null };
}

export type ChipKey = "all" | "order" | "chat" | "call" | "broadcast" | "refund" | "visit" | "feedback";

export const TIMELINE_CHIPS: { key: ChipKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "order", label: "Orders" },
  { key: "refund", label: "Refunds" },
  { key: "visit", label: "Visits" },
  { key: "feedback", label: "Feedback" },
  { key: "chat", label: "Chats" },
  { key: "call", label: "Calls" },
  { key: "broadcast", label: "Broadcasts" },
];

/** Which event kinds each filter chip shows. "Visits" covers bookings, visits that happened and no-shows. */
export function eventMatchesChip(kind: string, chip: ChipKey): boolean {
  if (chip === "all") return true;
  if (chip === "visit") return kind === "visit" || kind === "no_show" || kind === "booking";
  return kind === chip;
}

const REFUND_METHODS: Record<string, string> = {
  razorpay: "online",
  cash: "cash",
  upi: "UPI",
  card: "card",
  bank_transfer: "bank transfer",
  credit_note: "credit note",
};

export function refundMethodWords(method: string | null | undefined): string | null {
  if (!method) return null;
  return REFUND_METHODS[method] ?? method.replace(/_/g, " ");
}

/** Booking status in plain words; null when unknown. */
export function bookingStatusWords(status: string | null | undefined): string | null {
  switch (status) {
    case "held": return "held";
    case "booked": return "booked";
    case "came": return "came";
    case "no_show": return "didn't come";
    case "cancelled": return "cancelled";
    default: return null;
  }
}
