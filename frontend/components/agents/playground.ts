import type {
  ApiError,
  Companion,
  CompanionKnowledgeHit,
  CompanionMemoryHit,
  CompanionMemoryStatus,
  CompanionModel,
  CompanionPerson,
  CompanionReply,
  CompanionSearchResult,
  CompanionToolCall,
  PlaygroundDefaults,
  PlaygroundSettings,
  PlaygroundSources,
  SaveMemoryOutcome,
} from "@/lib/api";
import { pageSpanText } from "@/components/agents/collectionRows";

/** How a tool call reads in the chat: get_chart({"dob":"1990-04-12"}), long args cut at 80 chars. */
export function formatToolCall(call: CompanionToolCall): string {
  const args = call.args && Object.keys(call.args).length ? JSON.stringify(call.args) : "";
  const shown = args.length > 80 ? `${args.slice(0, 79)}…` : args;
  return `${call.name}(${shown})`;
}

/** The owner types a tool's answer by hand: JSON if it parses as an object, else plain text. */
export function parseToolOutput(text: string): Record<string, unknown> | string {
  const trimmed = text.trim();
  if (trimmed.startsWith("{")) {
    try {
      const parsed: unknown = JSON.parse(trimmed);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
    } catch {
      /* not JSON: send as text */
    }
  }
  return trimmed;
}

/** "1.4 s" or "820 ms". */
export function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

/** The line shown when a test chat fails. 409 = paused character; 400 = no AI model set up. */
export function chatErrorText(err: unknown): string {
  const e = err as ApiError;
  return e?.message || "The character didn't answer. Try again.";
}

const TOOL_NAME = /^[a-z][a-z0-9_]{0,39}$/;
export function toolNameError(name: string, taken: string[]): string {
  if (!TOOL_NAME.test(name)) return "Use lowercase letters, numbers and _, starting with a letter (e.g. get_chart).";
  if (taken.includes(name)) return "That tool is already in the list.";
  return "";
}

/** "Book 7, pp. 212-213" or "Main resource, p. 12": the owner's title, then the pages. */
export function sourceText(s: { document: string; page_from: number; page_to: number }): string {
  return `${s.document}, ${pageSpanText(s.page_from, s.page_to)}`;
}

/** The line under a test-chat answer. primary/file → "From Main resource, p. 12; Book 7, pp. 212-213"; own → a note; chat/none → "". */
export function replySourceLine(basis: CompanionReply["basis"], sources: CompanionReply["sources"]): string {
  if (basis === "own") return "Own reasoning, not from your files";
  if ((basis === "primary" || basis === "book") && sources && sources.length > 0) {
    return `From ${sources.map(sourceText).join("; ")}`;
  }
  return "";
}

/**
 * The plain "Used:" line under a reply (without the "Used:" label): what it drew on, in words.
 * Example: used { card_lines: 6, memory_hits: 2 }, basis "primary", Meena -> "Its notes about Meena + 2 past chats · From Main resource, p. 12".
 * `used` missing (an old saved reply) -> the memory part is left out, and with no file part either the result is "".
 * `personName` null = the owner ("you").
 */
export function usedLine(
  used: CompanionReply["used"],
  basis: CompanionReply["basis"],
  sources: CompanionReply["sources"],
  personName: string | null,
): string {
  const files = replySourceLine(basis, sources);
  if (!used) return files;
  const who = personName ?? "you";
  const { card_lines: card, memory_hits: hits } = used;
  const chats = `${hits} past ${hits === 1 ? "chat" : "chats"}`;
  const memory =
    card > 0 && hits > 0
      ? `Its notes about ${who} + ${chats}`
      : card > 0
        ? `Its notes about ${who}`
        : hits > 0
          ? `${chats} with ${who}`
          : `Nothing it remembers about ${who} yet`;
  return `${memory} · ${files || "Not from your files"}`;
}

// ---------------------------------------------------------------------------
// What the chat and the search send
// ---------------------------------------------------------------------------

/** What live chat uses, until GET /models says otherwise. Same numbers the backend reports. */
export const FALLBACK_DEFAULTS: PlaygroundDefaults = {
  sources: "all",
  results: 5,
  memory_floor: 0.7,
  judge_min: 2,
  rerank: true,
  rewrite: true,
  memory_card: true,
  mode: "auto",
};

/**
 * The only setting the Playground changes from live chat. Example: "knowledge" -> { sources: "knowledge" };
 * "all" (what live chat does) -> {} so the backend behaves exactly as live.
 */
export function sourcesSetting(sources: PlaygroundSources, live: PlaygroundDefaults): PlaygroundSettings {
  return sources === live.sources ? {} : { sources };
}

// ---------------------------------------------------------------------------
// Model chip
// ---------------------------------------------------------------------------

/** A model as the owner reads it: its label, or the raw id when it is no longer offered. */
export function modelLabel(models: CompanionModel[], id: string): string {
  return models.find((m) => m.id === id)?.label ?? id;
}

/**
 * The chip's dropdown. The character's own model carries its name.
 * Example: Jothidar on 3.1 -> ["Gemini 3.1 Flash Lite · Jothidar's model", "Gemini 3.5 Flash Lite"].
 * A saved model that is no longer offered is still listed, so the chip never shows a blank.
 */
export function modelChoices(models: CompanionModel[], characterModel: string, characterName: string): { value: string; label: string }[] {
  const all = models.some((m) => m.id === characterModel) ? models : [{ id: characterModel, label: characterModel }, ...models];
  return all.map((m) => ({ value: m.id, label: m.id === characterModel ? `${m.label} · ${characterName}'s model` : m.label }));
}

// ---------------------------------------------------------------------------
// Suggestions
// ---------------------------------------------------------------------------

type SuggestionSet = { memory: [string, string]; marriage: string; files: string };

const SUGGESTIONS: Record<"ta" | "ta-en" | "en", SuggestionSet> = {
  ta: {
    memory: ["என்னைப் பற்றி உங்களுக்கு என்ன தெரியும்?", "போன முறை நான் என்ன சொன்னேன்?"],
    marriage: "திருமணம் பற்றி முதலில் எதைப் பார்க்க வேண்டும்?",
    files: "உங்கள் கோப்புகளில் என்ன இருக்கிறது?",
  },
  "ta-en": {
    memory: ["Ennai pathi enna theriyum?", "Pona thadava naan enna sonnen?"],
    marriage: "Kalyanam pathi mudhalla edha paakanum?",
    files: "Unga files-la enna irukku?",
  },
  en: {
    memory: ["What do you know about me?", "What did I tell you last time?"],
    marriage: "What should I check first about marriage?",
    files: "What do your files cover?",
  },
};

/**
 * Starter questions that fit the character, in its language (unknown language -> English).
 * Always the two memory questions; then astrology -> the marriage question, general with a
 * collection -> "what do your files cover", general without one -> nothing more.
 * Example: Tanglish astrology -> ["Ennai pathi enna theriyum?", "Pona thadava naan enna sonnen?", "Kalyanam pathi mudhalla edha paakanum?"].
 */
export function suggestionsFor(c: Pick<Companion, "industry" | "language" | "knowledge_collection_id">): string[] {
  const set = SUGGESTIONS[c.language as keyof typeof SUGGESTIONS] ?? SUGGESTIONS.en;
  if (c.industry === "astrology") return [...set.memory, set.marriage];
  return c.knowledge_collection_id ? [...set.memory, set.files] : [...set.memory];
}

// ---------------------------------------------------------------------------
// Test customers and memory status
// ---------------------------------------------------------------------------

/** How a person is named in the Memories list: the typed name, "You" for the owner's own test id, else the id. */
export function personLabel(p: Pick<CompanionPerson, "display_name" | "is_test" | "external_user_id">): string {
  if (p.display_name) return p.display_name;
  return p.is_test ? "You" : p.external_user_id;
}

/**
 * The grey line under the chat box. Level 2 -> "Jothidar saves memories after 8 messages or overnight. 3 of 8 so far",
 * with a Save now button (canSave) only when something is unread. Level 1 -> says nothing is saved long-term.
 */
export function memoryStatusLine(
  status: CompanionMemoryStatus,
  c: { name: string; history_messages: number },
): { text: string; canSave: boolean } {
  if (status.level === 1) {
    return { text: `${c.name} keeps only the last ${c.history_messages} messages; nothing is saved long-term.`, canSave: false };
  }
  return {
    text: `${c.name} saves memories after ${status.saves_at} messages or overnight. ${status.unread} of ${status.saves_at} so far`,
    canSave: status.unread > 0,
  };
}

/**
 * What the owner reads after "Save now". Example: saved, 3 facts, Jothidar, Asha ->
 * { text: "Memory saved: Jothidar remembers 3 facts about Asha.", tone: "ok", seeThem: true }.
 * For the owner's own test id the sentence says "about you".
 */
export function saveMemoryResult(
  outcome: SaveMemoryOutcome,
  o: { facts: number | null; character: string; person: string; isYou: boolean },
): { text: string; tone: "ok" | "info"; seeThem: boolean } {
  switch (outcome) {
    case "saved": {
      // Privacy mode B: the business can't read what the character remembers, not even a count.
      if (o.facts === null) return { text: "Memory saved. This character is in privacy mode B, so its memories can't be shown.", tone: "ok", seeThem: false };
      const facts = `${o.facts} ${o.facts === 1 ? "fact" : "facts"}`;
      return { text: `Memory saved: ${o.character} remembers ${facts} about ${o.isYou ? "you" : o.person}.`, tone: "ok", seeThem: true };
    }
    case "nothing_new":
      return { text: "Nothing new to save yet.", tone: "info", seeThem: false };
    case "busy":
      return { text: "Already saving, try again in a minute.", tone: "info", seeThem: false };
    default:
      return { text: "The last reply is still being written. Try again in a few seconds.", tone: "info", seeThem: false };
  }
}

// ---------------------------------------------------------------------------
// Search results
// ---------------------------------------------------------------------------

/** The pill on a knowledge row. Example: score 3 kept -> "judge 3/3 · kept" (ok); score null -> "judge off" (neutral). */
export function judgePill(score: number | null, kept: boolean): { text: string; tone: "ok" | "bad" | "neutral" } {
  if (score === null || score === undefined) return { text: "judge off", tone: "neutral" };
  return { text: `judge ${score}/3 · ${kept ? "kept" : "dropped"}`, tone: kept ? "ok" : "bad" };
}

const MEMORY_KIND: Record<CompanionMemoryHit["kind"], string> = { fact: "Fact", messages: "Conversation", diary: "Diary" };

/** The tag on a memory row. Example: kind "messages" -> "Memory · Conversation". */
export function memoryTag(kind: CompanionMemoryHit["kind"]): string {
  return `Memory · ${MEMORY_KIND[kind] ?? "Fact"}`;
}

/** "📄 Returns policy.pdf · p. 2" or "... · pp. 2-3". */
export function documentLine(hit: Pick<CompanionKnowledgeHit, "document" | "page_from" | "page_to">): string {
  return `${hit.document} · ${pageSpanText(hit.page_from, hit.page_to)}`;
}

/** "meaning 0.83", or "words 2" when memories were matched word by word. "" when nothing was measured. */
export function memoryScoreText(hit: Pick<CompanionMemoryHit, "meaning" | "words">, mode: CompanionSearchResult["memory_mode"]): string {
  if (mode === "words") return hit.words === null || hit.words === undefined ? "" : `words ${hit.words}`;
  return hit.meaning === null || hit.meaning === undefined ? "" : `meaning ${hit.meaning.toFixed(2)}`;
}

export function meaningText(meaning: number | null): string {
  return meaning === null || meaning === undefined ? "" : `meaning ${meaning.toFixed(2)}`;
}

/** Words mode: whose fact this is. Example: "Karthik (cust_1042)"; no name -> "cust_1042"; no id -> "". */
export function memoryPersonLine(hit: Pick<CompanionMemoryHit, "external_user_id" | "display_name">): string {
  if (!hit.external_user_id) return "";
  return hit.display_name ? `${hit.display_name} (${hit.external_user_id})` : hit.external_user_id;
}

export type SearchView = {
  /** Kept first; dropped ones only when "Show pages it found but dropped" is on. */
  knowledge: CompanionKnowledgeHit[];
  /** Kept first; below-floor ones only when "Show pages it found but dropped" is on. */
  memories: CompanionMemoryHit[];
  /** "2 weak-match memories hidden", or "". */
  hiddenLine: string;
  /** The knowledge side failed (an "all" search); show NOTICE_KNOWLEDGE_ERROR where its rows would be. */
  knowledgeError: boolean;
  /** Why something is missing. Example: "Small talk — the files were not searched." */
  notices: string[];
  /** Shown when there is nothing to list and no notice explains it. */
  nothingPassed: boolean;
};

export const NOTICE_NO_COLLECTION = "This character reads no collection. Pick one on Characters.";
export const NOTICE_SMALL_TALK = "Small talk — the files were not searched.";
export const NOTICE_PRIVATE = "This character is in privacy mode B: memories can't be shown.";
export const NOTICE_KNOWLEDGE_ERROR = "Knowledge search isn't available right now. Try again.";
export const NOTICE_NOTHING = "Nothing passed the checks, so nothing would be read.";

/**
 * Turns one search response into what the screen lists, using the display-only
 * checkbox. Example: 3 knowledge hits (1 dropped) + 2 weak memories, with
 * "Show pages it found but dropped" off -> 2 knowledge rows, 0 memory rows, hiddenLine "2 weak-match memories hidden".
 */
export function buildSearchView(result: CompanionSearchResult, o: { showDropped: boolean }): SearchView {
  const wantsKnowledge = result.in !== "memories";
  const wantsMemories = result.in !== "knowledge";
  const knowledge = wantsKnowledge ? result.knowledge.filter((h) => h.kept || o.showDropped) : [];
  const memories = wantsMemories ? result.memories.filter((m) => m.kept || o.showDropped) : [];
  const belowFloor = wantsMemories ? result.memories.filter((m) => !m.kept).length : 0;
  const hiddenLine =
    !o.showDropped && belowFloor > 0
      ? `${belowFloor} weak-match ${belowFloor === 1 ? "memory" : "memories"} hidden`
      : "";

  const notices: string[] = [];
  if (wantsKnowledge && result.no_collection) notices.push(NOTICE_NO_COLLECTION);
  else if (wantsKnowledge && !result.needs_docs) notices.push(NOTICE_SMALL_TALK);
  if (wantsMemories && result.memories_hidden === "private") notices.push(NOTICE_PRIVATE);

  const knowledgeError = wantsKnowledge && !!result.knowledge_error;
  const nothingPassed = knowledge.length === 0 && memories.length === 0 && notices.length === 0 && !knowledgeError;
  return { knowledge, memories, hiddenLine, knowledgeError, notices, nothingPassed };
}

/** The short line a screen reader announces after a search. Example: "2 passages, 1 memory"; nothing -> "No results". */
export function resultCountText(view: Pick<SearchView, "knowledge" | "memories">): string {
  const parts: string[] = [];
  const k = view.knowledge.length;
  const m = view.memories.length;
  if (k) parts.push(`${k} ${k === 1 ? "passage" : "passages"}`);
  if (m) parts.push(`${m} ${m === 1 ? "memory" : "memories"}`);
  return parts.length ? parts.join(", ") : "No results";
}

/**
 * Puts a compare reply next to the reply it belongs to. Example: [user, reply, reply "Without memory"] ->
 * [user, [reply, reply "Without memory"]]. A labelled reply with no partner stays alone.
 */
export function pairCompareReplies<T extends { kind: string; label?: string }>(items: T[]): (T | [T, T])[] {
  const out: (T | [T, T])[] = [];
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    const next = items[i + 1];
    if (item.kind === "reply" && !item.label && next?.kind === "reply" && next.label) {
      out.push([item, next]);
      i++;
    } else {
      out.push(item);
    }
  }
  return out;
}
