/** Pure rules for the global search box: when "/" focuses it, how answers are grouped, what to highlight. */

export const MIN_QUERY = 2;
export const MAX_QUERY = 60;
export const DEBOUNCE_MS = 250;

export type GroupKey = "customers" | "orders" | "items" | "chats";

/** Fixed order and wording of the groups (the server sends them in the same order). */
export const GROUPS: readonly { key: GroupKey; heading: string }[] = [
  { key: "customers", heading: "CUSTOMERS" },
  { key: "orders", heading: "ORDERS & BILLS" },
  { key: "items", heading: "ITEMS" },
  { key: "chats", heading: "CHATS" },
];

export const FOOTER_TEXT = "Searches name, phone, order no., bill no., item and chat words. Press / from any page.";
export const PLACEHOLDER = "Search name, phone, order no. or item";

export interface SearchRow {
  /** Unique across groups, used as the option id. */
  id: string;
  groupKey: GroupKey;
  title: string;
  subtitle: string;
  /** Small grey line under the subtitle (chats: channel and date). */
  meta: string;
  href: string;
}

export interface SearchSection {
  key: GroupKey;
  heading: string;
  rows: SearchRow[];
}

type Raw = Record<string, unknown>;
const str = (v: unknown): string => (typeof v === "string" ? v : typeof v === "number" ? String(v) : "");

export function canSearch(q: string): boolean {
  const n = q.trim().length;
  return n >= MIN_QUERY && n <= MAX_QUERY;
}

/** Owners, and anyone who can see at least one of the four searched areas (manage implies view). */
export function canUseSearch(role: string | null, permissions: string[]): boolean {
  if (!role) return false;
  if (role === "owner") return true;
  const has = (area: string) => permissions.includes(`${area}.view`) || permissions.includes(`${area}.manage`);
  return has("leads") || has("deals") || has("catalog") || has("conversations") || permissions.includes("conversations.reply");
}

/** Minimal shape of a keyboard event / DOM node so this file stays testable without a browser. */
export interface TargetLike {
  tagName?: string;
  isContentEditable?: boolean;
  getAttribute?: (name: string) => string | null;
}

export function isTypingTarget(target: unknown): boolean {
  if (!target || typeof target !== "object") return false;
  const el = target as TargetLike;
  const tag = (el.tagName ?? "").toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.isContentEditable) return true;
  const editable = el.getAttribute?.("contenteditable");
  return editable === "" || editable === "true" || editable === "plaintext-only";
}

export interface KeyLike {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  isComposing?: boolean;
  defaultPrevented?: boolean;
  target?: unknown;
}

/** "/" from any page focuses the search, unless the person is typing somewhere or using a shortcut. */
export function isSlashShortcut(e: KeyLike): boolean {
  if (e.key !== "/") return false;
  if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing || e.defaultPrevented) return false;
  return !isTypingTarget(e.target);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "12 Nov" in Indian time; empty when the stamp can't be read. */
export function shortDate(value: unknown): string {
  const text = str(value);
  const ms = Date.parse(text);
  if (!text || Number.isNaN(ms)) return "";
  const ist = new Date(ms + 5.5 * 3600 * 1000);
  return `${ist.getUTCDate()} ${MONTHS[ist.getUTCMonth()]}`;
}

function channelName(channel: string): string {
  const c = channel.toLowerCase();
  if (c === "whatsapp") return "WhatsApp";
  if (c === "instagram") return "Instagram";
  if (c === "facebook" || c === "messenger") return "Facebook";
  if (c === "sms") return "SMS";
  if (c === "email") return "Email";
  return c ? c.charAt(0).toUpperCase() + c.slice(1) : "";
}

/** Only addresses inside this app are followed; anything else falls back to the page built from the id. */
function safeHref(href: unknown, fallback: string): string {
  const h = str(href);
  return h.startsWith("/dashboard/") && !h.startsWith("//") ? h : fallback;
}

function rowFor(key: GroupKey, item: Raw): SearchRow | null {
  if (key === "customers") {
    const id = str(item.id);
    if (!id) return null;
    const detail = str(item.detail);
    const phone = str(item.phone);
    return {
      id: `customers:${id}`, groupKey: key, title: str(item.name) || phone || "Unnamed",
      subtitle: [phone, detail].filter(Boolean).join(" · "), meta: "",
      href: safeHref(item.href, `/dashboard/leads/${id}`),
    };
  }
  if (key === "orders") {
    const id = str(item.id);
    if (!id) return null;
    return {
      id: `orders:${id}`, groupKey: key, title: str(item.label) || "Order", subtitle: str(item.detail), meta: "",
      href: safeHref(item.href, `/dashboard/deals/orders/${id}`),
    };
  }
  if (key === "items") {
    const id = str(item.id);
    if (!id) return null;
    return {
      id: `items:${id}`, groupKey: key, title: str(item.name) || "Item", subtitle: str(item.detail), meta: "",
      href: safeHref(item.href, `/dashboard/catalog/items/${id}`),
    };
  }
  const leadId = str(item.lead_id);
  if (!leadId) return null;
  return {
    id: `chats:${leadId}`, groupKey: key, title: str(item.name) || "Chat", subtitle: str(item.snippet),
    meta: [channelName(str(item.channel)), shortDate(item.date)].filter(Boolean).join(" · "),
    href: safeHref(item.href, `/dashboard/conversations?lead=${encodeURIComponent(leadId)}`),
  };
}

/** Server groups -> sections in the fixed order, up to 5 rows each, empty and unknown groups dropped. */
export function buildSections(groups: { key: string; title?: string; items: Raw[] }[] | undefined | null): SearchSection[] {
  const byKey = new Map((groups ?? []).map((g) => [g.key, g.items ?? []] as const));
  const sections: SearchSection[] = [];
  for (const { key, heading } of GROUPS) {
    const rows = (byKey.get(key) ?? [])
      .map((item) => rowFor(key, item))
      .filter((r): r is SearchRow => r !== null)
      .slice(0, 5);
    if (rows.length) sections.push({ key, heading, rows });
  }
  return sections;
}

export function flatRows(sections: SearchSection[]): SearchRow[] {
  return sections.flatMap((s) => s.rows);
}

/** Arrow-key movement through `count` rows. -1 means "none selected"; it wraps at both ends. */
export function nextIndex(current: number, delta: 1 | -1, count: number): number {
  if (count <= 0) return -1;
  if (current < 0) return delta === 1 ? 0 : count - 1;
  return (current + delta + count) % count;
}

/** Enter may open a row only when the rows on screen answer the current query and nothing newer is loading. */
export function isFreshAnswer(status: string, forQuery: string, query: string): boolean {
  return status === "done" && forQuery !== "" && forQuery === query.trim();
}

/** Tab / Shift+Tab inside the sheet: which of `count` focusable things comes next (wraps at both ends).
 *  `current` is the index of the focused one, or -1 when focus is elsewhere. */
export function nextFocusIndex(current: number, count: number, shift: boolean): number {
  if (count <= 0) return -1;
  if (current < 0) return shift ? count - 1 : 0;
  return (current + (shift ? -1 : 1) + count) % count;
}

export interface Part {
  text: string;
  match: boolean;
}

const escapeRegex = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Splits `text` into plain and matching parts for every word of the query (case-insensitive). */
export function highlightParts(text: string, query: string): Part[] {
  if (!text) return [];
  const raw = query.trim().replace(/^#/, "").split(/\s+/).filter(Boolean);
  const words = Array.from(new Set(raw.filter((w) => w.length >= 2 || raw.length === 1).map((w) => w.toLowerCase())))
    .sort((a, b) => b.length - a.length);
  if (!words.length) return [{ text, match: false }];
  const re = new RegExp(`(${words.map(escapeRegex).join("|")})`, "gi");
  const parts: Part[] = [];
  let last = 0;
  for (const m of Array.from(text.matchAll(re))) {
    const at = m.index ?? 0;
    if (m[0] === "") continue;
    if (at > last) parts.push({ text: text.slice(last, at), match: false });
    parts.push({ text: m[0], match: true });
    last = at + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), match: false });
  return parts.length ? parts : [{ text, match: false }];
}
