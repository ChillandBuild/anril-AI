/** The Chats page filters. Everything here is applied by the server (GET /api/v1/conversations),
 *  so totals, counts and paging always describe exactly what the list shows. */

/** Chats page tabs. "needs_you" is the full-screen handover (escalation) page; the rest are chat lists. */
export type InboxView = "inbox" | "needs_you" | "ai_handling" | "archived" | "blocked";
export type ListView = Exclude<InboxView, "needs_you">;
export type InboxChannel = "all" | "whatsapp" | "instagram" | "facebook" | "telegram";
export type DateRange = "any" | "today" | "7d" | "30d" | "custom";

export interface InboxFilters {
  segments: string[];
  results: string[];
  cameFrom: string[];
  handledBy: string[];
  waiting: string[];
  date: DateRange;
  /** yyyy-mm-dd, used when date === "custom". */
  customFrom: string;
  tagId: string;
}

export const EMPTY_FILTERS: InboxFilters = {
  segments: [],
  results: [],
  cameFrom: [],
  handledBy: [],
  waiting: [],
  date: "any",
  customFrom: "",
  tagId: "",
};

export type Option = { value: string; label: string };

export const INTEREST_OPTIONS: Option[] = [
  { value: "A", label: "Hot" },
  { value: "B", label: "Warm" },
  { value: "C", label: "Cold" },
  { value: "D", label: "Not interested" },
];

export const RESULT_OPTIONS: Option[] = [
  { value: "none", label: "No result yet" },
  { value: "booked", label: "Booked" },
  { value: "paid", label: "Came / Paid" },
  { value: "lost", label: "Not buying" },
];

export const CAME_FROM_OPTIONS: Option[] = [
  { value: "meta_ads", label: "Meta ads" },
  { value: "direct", label: "Messaged us" },
  { value: "website", label: "Website" },
  { value: "indiamart", label: "IndiaMART" },
  { value: "justdial", label: "JustDial" },
  { value: "upload", label: "Uploaded list" },
  { value: "manual", label: "Added by hand" },
];

export const WAITING_OPTIONS: Option[] = [
  { value: "unread", label: "Unread" },
  { value: "over_1h", label: "Waiting over 1 hour" },
  { value: "payment_pending", label: "Payment pending" },
];

export const DATE_OPTIONS: { value: DateRange; label: string }[] = [
  { value: "any", label: "Any time" },
  { value: "today", label: "Today" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "custom", label: "From a date" },
];

/** How many filter groups are switched on (the number on the Filter button). */
export function activeFilterCount(f: InboxFilters): number {
  return (
    (f.segments.length ? 1 : 0) +
    (f.results.length ? 1 : 0) +
    (f.cameFrom.length ? 1 : 0) +
    (f.handledBy.length ? 1 : 0) +
    (f.waiting.length ? 1 : 0) +
    (sinceFor(f) ? 1 : 0) +
    (f.tagId ? 1 : 0)
  );
}

/** Start of the date range, as an ISO string, in IST for "today". */
export function sinceFor(f: InboxFilters, now: Date = new Date()): string | null {
  const day = 24 * 60 * 60 * 1000;
  if (f.date === "today") {
    // Midnight in India, whatever the browser's timezone.
    const ist = new Date(now.getTime() + 5.5 * 60 * 60 * 1000);
    const midnightIstAsUtc = Date.UTC(ist.getUTCFullYear(), ist.getUTCMonth(), ist.getUTCDate()) - 5.5 * 60 * 60 * 1000;
    return new Date(midnightIstAsUtc).toISOString();
  }
  if (f.date === "7d") return new Date(now.getTime() - 7 * day).toISOString();
  if (f.date === "30d") return new Date(now.getTime() - 30 * day).toISOString();
  if (f.date === "custom" && /^\d{4}-\d{2}-\d{2}$/.test(f.customFrom)) {
    return new Date(`${f.customFrom}T00:00:00+05:30`).toISOString();
  }
  return null;
}

/** Query-string params for the list and counts endpoints. */
export function filterParams(
  f: InboxFilters,
  opts: { view: ListView; channel: InboxChannel; search?: string }
): URLSearchParams {
  const qs = new URLSearchParams({ view: opts.view });
  if (opts.channel !== "all") qs.set("channels", opts.channel);
  if (opts.search) qs.set("q", opts.search);
  if (f.segments.length) qs.set("segments", f.segments.join(","));
  if (f.results.length) qs.set("results", f.results.join(","));
  if (f.cameFrom.length) qs.set("came_from", f.cameFrom.join(","));
  if (f.handledBy.length) qs.set("handled_by", f.handledBy.join(","));
  if (f.waiting.length) qs.set("waiting", f.waiting.join(","));
  const since = sinceFor(f);
  if (since) qs.set("since", since);
  if (f.tagId) qs.set("tag_id", f.tagId);
  return qs;
}

export interface InboxCounts {
  needs_you: number;
  ai_handling: number;
  all_active: number;
  channels: Partial<Record<InboxChannel, number>>;
}

export const EMPTY_COUNTS: InboxCounts = { needs_you: 0, ai_handling: 0, all_active: 0, channels: {} };
