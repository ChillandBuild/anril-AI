import type { Companion, CompanionInput } from "@/lib/api";

export const LANGUAGES: { value: string; label: string }[] = [
  { value: "ta-en", label: "Tanglish (Tamil in English letters)" },
  { value: "ta", label: "Tamil" },
  { value: "en", label: "English" },
];

export const LANGUAGE_LABEL: Record<string, string> = { "ta-en": "Tanglish", ta: "Tamil", en: "English" };

export const MOODS = ["calm", "warm", "happy", "concerned", "encouraging", "serious"] as const;

/** First free "New character", "New character 2", ... so the create never hits the 409. */
export function nextDraftName(existing: string[]): string {
  const taken = new Set(existing.map((n) => n.trim().toLowerCase()));
  if (!taken.has("new character")) return "New character";
  for (let i = 2; ; i++) if (!taken.has(`new character ${i}`)) return `New character ${i}`;
}

/** Textarea, one item per line, blank lines dropped. */
export function linesToList(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

const EDITABLE: (keyof CompanionInput)[] = [
  "name", "industry", "role", "backstory", "speaking_style", "sample_lines", "goals", "temperament",
  "default_mood", "language", "rules", "knowledge_tag_id", "memory_level", "memory_engine",
  "history_messages", "privacy_mode", "status",
];

/**
 * Only the fields the owner changed, for the PATCH. Example: Jothidar AI with
 * default mood calm → warm gives { default_mood: "warm" }.
 */
export function changedFields(original: Companion, draft: Companion): CompanionInput {
  const out: Record<string, unknown> = {};
  for (const key of EDITABLE) {
    if (JSON.stringify(original[key]) !== JSON.stringify(draft[key])) out[key] = draft[key];
  }
  return out as CompanionInput;
}
