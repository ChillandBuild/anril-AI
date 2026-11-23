import type { Template, UsageEntry } from "./types";
import { isStaffAlertMarketing, liveUsage, plainRejection } from "./template-filters";

/** Plain-word status for the chip. */
export const STATUS_LABEL: Record<string, string> = {
  APPROVED: "Approved",
  PENDING: "Pending Review",
  REJECTED: "Rejected",
  PAUSED: "Paused",
  DISABLED: "Turned off",
  ARCHIVED: "Archived",
  DELETED: "Deleted",
};

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status.charAt(0) + status.slice(1).toLowerCase();
}

/** "just now", "20 min ago", "3 hours ago", "2 days ago". */
export function timeAgo(iso: string | undefined | null, now: number = Date.now()): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.max(0, Math.round((now - then) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

const AREA_ICON: Record<string, string> = {
  reach: "📣",
  staff_alert: "🔔",
  commerce: "🧾",
  otp: "🔐",
  auto_messages: "⚡",
  one_time_sends: "🗓️",
  follow_ups: "🔁",
  instant_forms: "📝",
  whatsapp_forms: "📋",
  marketplace: "🛍️",
  purchases: "📦",
  back_in_stock: "🆕",
  reply_ready: "💬",
};

export type UsedIn =
  | { kind: "live"; icon: string; label: string; more: number }
  | { kind: "ended"; label: string }
  | { kind: "none" };

/** The card's "Used in" line: the first live place (+N more), else where it was, else not used. */
export function usedIn(entries: UsageEntry[] | undefined): UsedIn {
  const live = liveUsage(entries);
  if (live.length) {
    return { kind: "live", icon: AREA_ICON[live[0].area] ?? "•", label: live[0].label, more: live.length - 1 };
  }
  const ended = (entries ?? []).filter((e) => e.ended);
  if (ended.length) return { kind: "ended", label: `Was in ${ended[0].label.replace(/^was in /i, "")}` };
  return { kind: "none" };
}

export type CardNote =
  | { kind: "staff-marketing" }
  | { kind: "pending"; text: string }
  | { kind: "paused"; text: string }
  | { kind: "rejected"; text: string }
  | { kind: "disabled"; text: string };

/** The one coloured line a card may show. The staff-alert warning wins: it costs money every send. */
export function cardNote(t: Template, entries: UsageEntry[] | undefined, now: number = Date.now()): CardNote | null {
  if (isStaffAlertMarketing(t, entries)) return { kind: "staff-marketing" };
  const why = plainRejection(t.rejection_reason);
  switch (t.status) {
    case "PENDING": {
      const ago = timeAgo(t.submitted_at, now);
      return { kind: "pending", text: ago ? `Sent to Meta ${ago} · usually under 1 hour` : "Meta is checking · usually under 1 hour" };
    }
    case "PAUSED":
      return { kind: "paused", text: why ? `Paused by Meta: ${why}.` : "Paused by Meta: people blocked it." };
    case "REJECTED":
      return { kind: "rejected", text: why ? `Meta: "${why}".` : "Meta rejected it and didn't say why." };
    case "DISABLED":
      return { kind: "disabled", text: "Meta turned it off after repeated pauses. Make a new copy." };
    default:
      return null;
  }
}
