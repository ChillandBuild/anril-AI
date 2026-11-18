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
  "default_mood", "language", "model", "rules", "memory_level", "memory_engine",
  "history_messages", "privacy_mode", "status",
];

/** A character saved before the switch existed has no value: it answers from its own reasoning (on). */
export function ownReasoningOn(c: Companion): boolean {
  return c.own_reasoning ?? true;
}

/** Knowledge tab "When your files don't cover a question": Mixed = own_reasoning on, Strict = off. */
export type AnswerMode = "mixed" | "strict";

export function answerModeOf(c: Companion): AnswerMode {
  return ownReasoningOn(c) ? "mixed" : "strict";
}

/** Strict's line when the owner wrote none (= backend engine.HANDOFF_LINES): the box's placeholder. */
export const GENERIC_HANDOFF: Record<string, string> = {
  "ta-en": "Idharku engal team-idam ketpadhu nalladhu.",
  ta: "இதற்கு எங்கள் குழுவிடம் கேட்பது நல்லது.",
  en: "Our team can help you with this better.",
};

export function genericHandoff(language: string): string {
  return GENERIC_HANDOFF[language] ?? GENERIC_HANDOFF.en;
}

/** The owner's own handoff line, "" when none (null and missing mean the generic line). */
export function handoffLineOf(c: Companion): string {
  return c.handoff_line ?? "";
}

/**
 * Persona rules a character starts with when the owner picks its industry. Nothing here is fixed:
 * they land in the Rules box, where the owner can edit or delete them before saving.
 * Only rules common to every industry are fixed (backend platform_rules.PLATFORM_RULES).
 */
export const STARTER_RULES: Record<Companion["industry"], string[]> = {
  astrology: [
    "Never predict death, accidents or serious illness. Never frighten the user.",
    "Present astrology as guidance, not certainty. The user's own choices matter most.",
    "Remedies must be free or low-cost (prayer, a temple visit, charity, simple habits). Never present paid poojas, gemstones or yantras as required.",
  ],
  general: [],
};

/** Switching industry fills the starter rules only into an empty Rules box; rules already written stay as they are.
 * Example: a new draft (no rules) switched to Astrology gets the 3 astrology rules; Jothidar AI's 30 rules are untouched. */
export function withIndustry(c: Companion, industry: Companion["industry"]): Companion {
  const rules = c.rules.length === 0 ? [...STARTER_RULES[industry]] : c.rules;
  return { ...c, industry, rules };
}

/** The collection a character reads, or null for "No files". */
export function collectionIdOf(c: Companion): string | null {
  return c.knowledge_collection_id ?? null;
}

/**
 * Only the fields the owner changed, for the PATCH. Example: Maya with
 * default mood calm → warm gives { default_mood: "warm" }. Picking "No files" on a
 * character that read a collection gives { knowledge_collection_id: null }.
 */
export function changedFields(original: Companion, draft: Companion): CompanionInput {
  const out: Record<string, unknown> = {};
  for (const key of EDITABLE) {
    if (JSON.stringify(original[key]) !== JSON.stringify(draft[key])) out[key] = draft[key];
  }
  // Missing means "No files" / "on", so an untouched older character sends nothing.
  if (collectionIdOf(original) !== collectionIdOf(draft)) out.knowledge_collection_id = collectionIdOf(draft);
  if (ownReasoningOn(original) !== ownReasoningOn(draft)) out.own_reasoning = ownReasoningOn(draft);
  if ((original.full_main_resource ?? false) !== (draft.full_main_resource ?? false)) out.full_main_resource = draft.full_main_resource ?? false;
  if ((original.working_step ?? false) !== (draft.working_step ?? false)) out.working_step = draft.working_step ?? false;
  if (handoffLineOf(original).trim() !== handoffLineOf(draft).trim()) out.handoff_line = handoffLineOf(draft).trim() || null;
  // Missing and null both mean "same as the AI model", so an untouched older character sends nothing.
  if ((original.small_talk_model ?? null) !== (draft.small_talk_model ?? null)) out.small_talk_model = draft.small_talk_model ?? null;
  return out as CompanionInput;
}

/** Live characters need their name typed before a permanent delete. Spaces at the ends and letter case don't matter.
 * Example: "jothidar ai " matches "Jothidar AI"; "Jothidar" does not. */
export function nameMatches(typed: string, name: string): boolean {
  return typed.trim().length > 0 && typed.trim().toLowerCase() === name.trim().toLowerCase();
}
