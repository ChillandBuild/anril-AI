import type { Template, TemplateUsage, UsageEntry } from "./types";
import { languageName } from "./types";

export type TemplateFilters = {
  search: string;
  category: string; // ALL | MARKETING | UTILITY | AUTHENTICATION
  status: string; // ALL | APPROVED | ...
  language: string; // ALL | a language code
  usedIn: string; // ALL | NONE | an area key from the usage call
};

/** The "Rejected / Paused" summary card: every template Meta has stopped. */
export const NEEDS_FIX = "NEEDS_FIX";
export const NEEDS_FIX_STATUSES: string[] = ["REJECTED", "PAUSED", "DISABLED"];

export const NO_FILTERS: TemplateFilters = { search: "", category: "ALL", status: "ALL", language: "ALL", usedIn: "ALL" };

/** Places that count right now: a finished Reach campaign is history, not use. */
export function liveUsage(entries: UsageEntry[] | undefined): UsageEntry[] {
  return (entries ?? []).filter((e) => !e.ended);
}

export function filterTemplates(list: Template[], f: TemplateFilters, usage: TemplateUsage = {}): Template[] {
  const q = f.search.trim().toLowerCase();
  return list.filter((t) => {
    const matchesSearch = !q ||
      t.name.toLowerCase().includes(q) ||
      t.body_text.toLowerCase().includes(q) ||
      (t.short_code ?? "").includes(q);
    if (!matchesSearch) return false;
    if (f.category !== "ALL" && t.category !== f.category) return false;
    if (f.status === NEEDS_FIX) {
      if (!NEEDS_FIX_STATUSES.includes(t.status)) return false;
    } else if (f.status !== "ALL" && t.status !== f.status) return false;
    if (f.language !== "ALL" && t.language !== f.language) return false;
    if (f.usedIn === "NONE") return (usage[t.id] ?? []).length === 0;
    if (f.usedIn !== "ALL") return liveUsage(usage[t.id]).some((e) => e.area === f.usedIn);
    return true;
  });
}

/** The languages that are actually on this account, by name, A to Z. */
export function languageOptions(list: Template[]): { value: string; label: string }[] {
  const codes = Array.from(new Set(list.map((t) => t.language).filter(Boolean)));
  return codes
    .map((code) => ({ value: code, label: languageName(code) }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** One entry per area (an area can appear with several labels), in the order first seen. */
export function usedInOptions(usage: TemplateUsage): { value: string; label: string }[] {
  const seen = new Map<string, string>();
  for (const entries of Object.values(usage)) {
    for (const e of liveUsage(entries)) {
      if (!seen.has(e.area)) seen.set(e.area, e.label.split(" · ")[0]);
    }
  }
  return Array.from(seen, ([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label));
}

/** "Used in: Auto-Messages · Purchased, Follow-ups" / "Was in Reach · ended" / "Not used yet". */
export function usedInText(entries: UsageEntry[] | undefined): string {
  const live = liveUsage(entries);
  if (live.length) return `Used in: ${live.map((e) => e.label).join(", ")}`;
  const ended = (entries ?? []).filter((e) => e.ended);
  if (ended.length) return ended[0].label.charAt(0).toUpperCase() + ended[0].label.slice(1);
  return "Not used yet";
}

/** Set as a staff alert but filed as Marketing: costs more and Meta may block it. */
export function isStaffAlertMarketing(t: Template, entries: UsageEntry[] | undefined): boolean {
  return t.category === "MARKETING" && liveUsage(entries).some((e) => e.area === "staff_alert");
}

export const STAFF_ALERT_WARNING =
  "Staff alert set as Marketing: costs more and Meta may block it. Make a Utility copy.";

// Meta's own rejection codes, in plain words.
const REJECTION_WORDS: Record<string, string> = {
  INVALID_FORMAT: "the wording or format isn't allowed",
  ABUSIVE_CONTENT: "it looks abusive or against WhatsApp's rules",
  TAG_CONTENT_MISMATCH: "the type (Marketing or Utility) doesn't match what the message says",
  INCORRECT_CATEGORY: "the type (Marketing or Utility) doesn't match what the message says",
  PROMOTIONAL: "it reads like a promotion, so it can't be Utility",
  SCAM: "it looks like a scam",
  NONE: "",
};

export function plainRejection(reason: string | null | undefined): string {
  const raw = (reason ?? "").trim();
  if (!raw) return "";
  const key = raw.toUpperCase().replace(/[\s-]+/g, "_");
  if (key in REJECTION_WORDS) return REJECTION_WORDS[key];
  return raw;
}

export type StatusNote = { text: string; fixHref?: string };

/** Why a Rejected / Paused / Disabled template is in that state; null for the other statuses. */
export function statusNote(t: Template): StatusNote | null {
  const why = plainRejection(t.rejection_reason);
  if (t.status === "REJECTED") {
    return { text: why ? `Meta: ${why}` : "Meta rejected it and didn't say why.", fixHref: `/dashboard/templates/${t.id}` };
  }
  if (t.status === "PAUSED") {
    return {
      text: why
        ? `Meta: ${why}`
        : "Paused by Meta because people blocked or reported it. It goes back on by itself after a few hours if quality improves.",
    };
  }
  if (t.status === "DISABLED") return { text: "Meta turned it off after repeated pauses. Make a new copy." };
  return null;
}
