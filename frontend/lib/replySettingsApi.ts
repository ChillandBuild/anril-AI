import { apiFetch } from "@/lib/api";

/** v9.2 #157 after-hours message and #171 the photo / voice note rule. */

export type AfterHours = { enabled: boolean; open: string; close: string; message: string; max_chars: number };

export const replySettingsApi = {
  afterHours: () => apiFetch<AfterHours>("/api/v1/reply-settings/after-hours"),
  saveAfterHours: (body: Omit<AfterHours, "max_chars">) =>
    apiFetch<AfterHours>("/api/v1/reply-settings/after-hours", { method: "PUT", body: JSON.stringify(body) }),
};

export type MediaRule = { rule: string; max_chars: number };

export const mediaRuleApi = {
  get: () => apiFetch<MediaRule>("/api/v1/ai-teach/media-rule"),
  save: (rule: string) => apiFetch<MediaRule>("/api/v1/ai-teach/media-rule", { method: "PUT", body: JSON.stringify({ rule }) }),
};

/** One-tap choices for the photo / voice note rule. The text is what the AI is told. */
export const MEDIA_RULE_PRESETS: { label: string; text: string }[] = [
  { label: "Ask what they want to know", text: "Ask what they would like to know about it, then answer from the Knowledge Base." },
  { label: "Hand to a person", text: "Tell them a person from the team will look at it and reply, and hand the chat to the team." },
  { label: "Ask them to type it", text: "Politely ask them to type their question, because you cannot open photos or voice notes yet." },
];

/** The reason the owner can't save the after-hours message yet, or null. Matches the server's checks. */
export function afterHoursProblem(d: Pick<AfterHours, "enabled" | "open" | "close" | "message">, max = 300): string | null {
  const time = /^([01]\d|2[0-3]):[0-5]\d$/;
  if (!time.test(d.open) || !time.test(d.close)) return "Choose the times as hours and minutes, like 09:00.";
  if (d.message.trim().length > max) return `Keep the message under ${max} characters.`;
  if (d.enabled && !d.message.trim()) return "Write the message first, then switch it on.";
  return null;
}

/** v9.2 #59 / #92 open hours: one setting read by the AI, customer bookings and the after-hours message. */
export type OpenHoursBlocks = Record<string, [string, string][]>; // "0" = Monday … "6" = Sunday; a missing day is closed
export type OpenHours = { set: boolean; hours: OpenHoursBlocks; national_holidays: boolean; summary: string; status: string };

export const openHoursApi = {
  get: () => apiFetch<OpenHours>("/api/v1/reply-settings/open-hours"),
  save: (body: { hours: OpenHoursBlocks; national_holidays: boolean }) =>
    apiFetch<OpenHours>("/api/v1/reply-settings/open-hours", { method: "PUT", body: JSON.stringify(body) }),
};

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;
export type OpenDay = { on: boolean; open: string; close: string };

/** The editor's 7 rows from the saved setting. Not set yet → Mon–Sat 10 AM–8 PM, Sunday closed (the usual shop). */
export function openDaysFrom(h: Pick<OpenHours, "set" | "hours">): OpenDay[] {
  return WEEKDAYS.map((_, d) => {
    const blocks = h.hours[String(d)] ?? [];
    if (!h.set) return { on: d < 6, open: "10:00", close: "20:00" };
    if (!blocks.length) return { on: false, open: "10:00", close: "20:00" };
    return { on: true, open: blocks[0][0], close: blocks[blocks.length - 1][1] === "24:00" ? "23:59" : blocks[blocks.length - 1][1] };
  });
}

/** What the editor sends. Keeps a day's two blocks (a lunch break set elsewhere) when its times were not changed. */
export function openDaysToHours(days: OpenDay[], saved?: OpenHoursBlocks): OpenHoursBlocks {
  const out: OpenHoursBlocks = {};
  days.forEach((d, i) => {
    if (!d.on) return;
    const before = saved?.[String(i)];
    const end = before?.[before.length - 1]?.[1];
    const same = before && before.length > 1 && before[0][0] === d.open && (end === "24:00" ? "23:59" : end) === d.close;
    out[String(i)] = same ? before : [[d.open, d.close]];
  });
  return out;
}

/** Why the open hours can't be saved yet, or null. Matches the server's checks. */
export function openHoursProblem(days: OpenDay[]): string | null {
  const time = /^([01]\d|2[0-3]):[0-5]\d$/;
  if (!days.some((d) => d.on)) return "Switch on at least one day you are open.";
  for (let i = 0; i < days.length; i++) {
    const d = days[i];
    if (!d.on) continue;
    if (!time.test(d.open) || !time.test(d.close)) return `${WEEKDAYS[i]}: choose the times as hours and minutes.`;
    if (d.close <= d.open) return `${WEEKDAYS[i]}: closing time must be after opening time.`;
  }
  return null;
}
