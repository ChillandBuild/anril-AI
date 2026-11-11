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
  "default_mood", "language", "rules", "memory_level", "memory_engine",
  "history_messages", "privacy_mode", "status",
];

/** A character saved before the switch existed has no value: it answers from its own reasoning (on). */
export function ownReasoningOn(c: Companion): boolean {
  return c.own_reasoning ?? true;
}

/** The book collection a character reads, or null for "No books". */
export function collectionIdOf(c: Companion): string | null {
  return c.knowledge_collection_id ?? null;
}

/**
 * Only the fields the owner changed, for the PATCH. Example: Jothidar AI with
 * default mood calm → warm gives { default_mood: "warm" }. Picking "No books" on a
 * character that read a collection gives { knowledge_collection_id: null }.
 */
export function changedFields(original: Companion, draft: Companion): CompanionInput {
  const out: Record<string, unknown> = {};
  for (const key of EDITABLE) {
    if (JSON.stringify(original[key]) !== JSON.stringify(draft[key])) out[key] = draft[key];
  }
  // Missing means "No books" / "on", so an untouched older character sends nothing.
  if (collectionIdOf(original) !== collectionIdOf(draft)) out.knowledge_collection_id = collectionIdOf(draft);
  if (ownReasoningOn(original) !== ownReasoningOn(draft)) out.own_reasoning = ownReasoningOn(draft);
  return out as CompanionInput;
}
