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
