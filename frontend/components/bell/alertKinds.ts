// Alert kinds for the bell: which chip an alert belongs to, its icon, and its one action button.
// Pure logic (no React) so it can be unit-tested.

export type AlertCategory = "needs_you" | "money" | "stock" | "calls" | "other";
export type AlertIcon = "chat" | "phone" | "money" | "box" | "sms" | "alert" | "info";

/** The fields of a stored alert this file needs. */
export interface BellAlert {
  id: string;
  type: string;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;
  /** Page the alert opens (app_notifications.url, once migration 315 is applied). */
  url?: string | null;
}

export interface AlertAction {
  label: string;
  /** Where the button goes; null when there is nowhere sensible to send the person. */
  href: (n: BellAlert) => string | null;
}

export interface AlertKind {
  category: AlertCategory;
  icon: AlertIcon;
  /** Plain-words area shown next to the time, e.g. "Chats · 2 min ago". */
  module: string;
  action: AlertAction | null;
}

export const CHIPS: { key: "all" | Exclude<AlertCategory, "other">; label: string }[] = [
  { key: "all", label: "All" },
  { key: "needs_you", label: "Needs you" },
  { key: "money", label: "Money" },
  { key: "stock", label: "Stock" },
  { key: "calls", label: "Calls" },
];
export type ChipKey = (typeof CHIPS)[number]["key"];

const CONVERSATIONS = "/dashboard/conversations";
const TELECALLING = "/dashboard/telecalling";
// Alerts about one lead open that lead's chat (or, for assignments, the telecalling page) when no link is stored.
const TELECALLING_LEAD_TYPES = new Set(["lead_assigned", "lead_reassigned", "sim_call_handoff"]);
const SCHEDULED = "/dashboard/telecalling/scheduled";

function fixed(label: string, href: string | null): AlertAction {
  return { label, href: () => href };
}

/** Chat-type alerts: no fixed page; the stored link or the [lead_id:] tag decides, else the chats page. */
const chatAction: AlertAction = { label: "Open chat", href: () => null };

const BOOKINGS = "/dashboard/bookings";

/** Booking alerts open the page stored with the alert (the day and booking), else the Bookings page. */
function bookingsAction(label: string): AlertAction {
  return { label, href: (n) => safeInternalPath(n.url) ?? BOOKINGS };
}

const KINDS: Record<string, AlertKind> = {
  lead_replied: { category: "needs_you", icon: "chat", module: "Chats", action: chatAction },
  lead_assigned: { category: "needs_you", icon: "chat", module: "Leads", action: chatAction },
  lead_reassigned: { category: "needs_you", icon: "chat", module: "Leads", action: chatAction },
  handover_new: { category: "needs_you", icon: "chat", module: "Chats", action: chatAction },
  lead_hot: { category: "needs_you", icon: "chat", module: "Leads", action: chatAction },
  hot_lead_waiting: { category: "needs_you", icon: "chat", module: "Chats", action: chatAction },
  supplier_message: { category: "needs_you", icon: "chat", module: "Purchases", action: chatAction },
  booking_new: { category: "needs_you", icon: "info", module: "Bookings", action: bookingsAction("Open bookings") },
  booking_cancelled: { category: "needs_you", icon: "alert", module: "Bookings", action: bookingsAction("Open bookings") },
  booking_call_now: { category: "calls", icon: "phone", module: "Bookings", action: bookingsAction("Call now") },

  callback_taken_over: { category: "calls", icon: "phone", module: "Calling", action: fixed("Call back list", SCHEDULED) },
  callback_reminder: { category: "calls", icon: "phone", module: "Calling", action: fixed("Call back list", SCHEDULED) },
  callback_due: { category: "calls", icon: "phone", module: "Calling", action: fixed("Call back list", SCHEDULED) },
  callback_late: { category: "calls", icon: "phone", module: "Calling", action: fixed("Call back list", SCHEDULED) },
  callback_claimable: { category: "calls", icon: "phone", module: "Calling", action: fixed("Call back list", SCHEDULED) },
  leads_waiting: { category: "calls", icon: "phone", module: "Calling", action: fixed("Open", TELECALLING) },
  sim_call_handoff: { category: "calls", icon: "phone", module: "Calling", action: { label: "Open", href: () => null } },
  call_alerts_summary: { category: "calls", icon: "phone", module: "Calling", action: fixed("Open", `${TELECALLING}#needs-attention`) },

  deal_double_payment: { category: "money", icon: "money", module: "Orders", action: fixed("See", "/dashboard/deals") },
  intake_double_payment: { category: "money", icon: "money", module: "Paid forms", action: fixed("See", "/dashboard/intake") },
  intake_paid: { category: "money", icon: "money", module: "Paid forms", action: fixed("See", "/dashboard/intake") },
  quote_accepted: { category: "money", icon: "money", module: "Orders", action: fixed("See", "/dashboard/deals") },
  day_closing: { category: "money", icon: "money", module: "Orders", action: fixed("See", "/dashboard/deals/day-closing") },
  purchase_order: { category: "money", icon: "money", module: "Purchases", action: fixed("See", "/dashboard/purchases") },
  refund_done: { category: "money", icon: "money", module: "Orders", action: fixed("See", "/dashboard/deals") },

  batch_expiry: { category: "stock", icon: "box", module: "Stock", action: fixed("See batches", "/dashboard/catalog?tab=batches") },
  stock_low: { category: "stock", icon: "box", module: "Stock", action: fixed("See stock", "/dashboard/catalog") },
  course_seat_free: { category: "other", icon: "alert", module: "Courses", action: fixed("See batches", "/dashboard/catalog/courses") },

  sms_low_balance: { category: "other", icon: "sms", module: "SMS", action: fixed("Top up", "/dashboard/sms") },
  scheduled_template_failed: { category: "other", icon: "alert", module: "Scheduled messages", action: fixed("See", "/dashboard/scheduled-templates") },
  system_error: { category: "other", icon: "alert", module: "System", action: fixed("See", "/dashboard") },
  intake_trigger_failed: { category: "other", icon: "alert", module: "Paid forms", action: fixed("See", "/dashboard/intake") },
  intake_bridge_auth_failed: { category: "other", icon: "alert", module: "Paid forms", action: fixed("See", "/dashboard/intake") },
  intake_astro_push_failed: { category: "other", icon: "alert", module: "Paid forms", action: fixed("See", "/dashboard/intake") },
  intake_reply_undelivered: { category: "other", icon: "alert", module: "Paid forms", action: fixed("See", "/dashboard/intake") },
  unmarked_bookings: { category: "other", icon: "info", module: "Bookings", action: fixed("See", "/dashboard/inbound-leads") },
  brain_digest: { category: "other", icon: "info", module: "Brain", action: fixed("See", "/dashboard/brain") },
  milestone_achieved: { category: "other", icon: "info", module: "Calling", action: null },
};

const UNKNOWN: AlertKind = { category: "other", icon: "info", module: "Alerts", action: null };

/** call_alert_<x> carries the alert kind after the prefix. */
const CALL_ALERT: AlertKind = {
  category: "calls",
  icon: "phone",
  module: "Calling",
  action: fixed("Open", `${TELECALLING}#needs-attention`),
};

export function alertKindFor(type: string): AlertKind {
  if (KINDS[type]) return KINDS[type];
  if (type.startsWith("call_alert_")) return CALL_ALERT;
  return UNKNOWN;
}

/** Only same-site paths are followed; anything else stored in url is ignored. */
export function safeInternalPath(url: string | null | undefined): string | null {
  if (!url) return null;
  const u = url.trim();
  if (!u.startsWith("/") || u.startsWith("//") || u.includes("\\")) return null;
  // Browsers drop tabs/newlines inside a URL, so "/\t/evil.com" would turn into "//evil.com".
  if (/[\u0000-\u001f\u007f\s]/.test(u)) return null;
  return u;
}

/** The Chats page reads ?lead=<id>; some alerts were stored with ?lead_id=<id>. */
export function normaliseChatLink(path: string): string {
  const m = path.match(/^(\/dashboard\/conversations)\?([^#]*)(#.*)?$/);
  if (!m) return path;
  const params = new URLSearchParams(m[2]);
  if (!params.has("lead_id") || params.has("lead")) return path;
  const lead = params.get("lead_id") ?? "";
  params.delete("lead_id");
  const rest = params.toString();
  return `${m[1]}?lead=${encodeURIComponent(lead)}${rest ? `&${rest}` : ""}${m[3] ?? ""}`;
}

export function leadIdFromMessage(message: string): string | null {
  const m = message.match(/\[lead_id:([^\]\s]+)\]/);
  return m ? m[1] : null;
}

/** Message text without the internal [lead_id:...] / [handover_id:...] tags. */
export function cleanMessage(message: string): string {
  return message.replace(/\s*\[(lead_id|handover_id):.*?\]/g, "");
}

/**
 * Where an alert's button goes. Order: the stored link, the type's own page, the [lead_id:] tag
 * (today's behaviour), then the chats page for chat-type alerts. null when nowhere fits.
 */
export function alertHref(n: BellAlert): string | null {
  const kind = alertKindFor(n.type);
  if (!kind.action) return null;
  const stored = safeInternalPath(n.url);
  const leadId = leadIdFromMessage(n.message);
  const tagLink = leadId
    ? TELECALLING_LEAD_TYPES.has(n.type)
      ? `${TELECALLING}?lead_id=${encodeURIComponent(leadId)}`
      : `${CONVERSATIONS}?lead=${encodeURIComponent(leadId)}`
    : null;
  // Chat alerts: the lead tag is the most exact link, so it beats a stored link (some older senders
  // stored a link the Chats page does not read).
  if (kind.action === chatAction && tagLink) return tagLink;
  if (stored) return normaliseChatLink(stored);
  const own = safeInternalPath(kind.action.href(n));
  if (own) return own;
  if (tagLink) return tagLink;
  return kind.category === "needs_you" ? CONVERSATIONS : n.type === "sim_call_handoff" ? TELECALLING : null;
}

/** Money alerts are only for people who can see orders (the owner always can). */
export function canSeeAlert(
  n: Pick<BellAlert, "type">,
  who: { isOwner: boolean; permissions: readonly string[] },
): boolean {
  if (alertKindFor(n.type).category !== "money") return true;
  return who.isOwner || who.permissions.includes("deals.view") || who.permissions.includes("deals.manage");
}

export function chipCounts(items: Pick<BellAlert, "type">[]): Record<ChipKey, number> {
  const counts: Record<ChipKey, number> = { all: items.length, needs_you: 0, money: 0, stock: 0, calls: 0 };
  for (const n of items) {
    const c = alertKindFor(n.type).category;
    if (c !== "other") counts[c] += 1;
  }
  return counts;
}

/** Chips to show: All always, the others only when something from the last 7 days belongs to them. */
export function visibleChips(items: Pick<BellAlert, "type">[]): { key: ChipKey; label: string; count: number }[] {
  const counts = chipCounts(items);
  return CHIPS.filter((c) => c.key === "all" || counts[c.key] > 0).map((c) => ({ ...c, count: counts[c.key] }));
}

export function filterByChip<T extends Pick<BellAlert, "type">>(items: T[], chip: ChipKey): T[] {
  if (chip === "all") return items;
  return items.filter((n) => alertKindFor(n.type).category === chip);
}

export function unreadCount(items: Pick<BellAlert, "is_read">[]): number {
  return items.filter((n) => !n.is_read).length;
}

/** "just now", "2 min ago", "3 hours ago", "yesterday", "4 days ago". */
export function timeAgo(iso: string, now: Date = new Date()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.floor((now.getTime() - then) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}
