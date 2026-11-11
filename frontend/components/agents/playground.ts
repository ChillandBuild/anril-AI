import type {
  ApiError,
  CompanionKnowledgeHit,
  CompanionMemoryHit,
  CompanionReply,
  CompanionSearchResult,
  CompanionToolCall,
  PlaygroundDefaults,
  PlaygroundSettings,
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

// ---------------------------------------------------------------------------
// Settings panel
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

/** Search-tab checkboxes. Display only: they change what is listed, never what is searched. */
export type ResultDisplay = { showDocs: boolean; showDropped: boolean };
export const DEFAULT_DISPLAY: ResultDisplay = { showDocs: true, showDropped: false };

export const SOURCE_LABEL: Record<PlaygroundDefaults["sources"], string> = {
  all: "All sources",
  memories: "Memories",
  knowledge: "Knowledge",
};

/** A stepper click, kept inside its range and free of float noise. Example: 0.7 + 0.05 -> 0.75, never 0.7500000001. */
export function stepValue(current: number, delta: number, min: number, max: number): number {
  const next = Math.round((current + delta) * 100) / 100;
  return Math.min(max, Math.max(min, next));
}

/** A setting as the owner reads it. Example: memory_floor 0.7 -> "0.70"; rerank true -> "Judge"; judge_min 2 -> "2 / 3". */
export function formatSetting(key: keyof PlaygroundDefaults, value: PlaygroundDefaults[keyof PlaygroundDefaults]): string {
  switch (key) {
    case "memory_floor":
      return Number(value).toFixed(2);
    case "judge_min":
      return `${value} / 3`;
    case "rerank":
      return value ? "Judge" : "Off";
    case "rewrite":
    case "memory_card":
      return value ? "on" : "off";
    case "mode":
      return value === "agentic" ? "Agentic" : "Auto-search";
    case "sources":
      return SOURCE_LABEL[value as PlaygroundDefaults["sources"]] ?? String(value);
    default:
      return String(value);
  }
}

/** Under a changed setting. Example: strictness 0.6 while live is 0.7 -> "Live chat uses 0.70"; same -> "". */
export function liveNote(key: keyof PlaygroundDefaults, settings: PlaygroundDefaults, live: PlaygroundDefaults): string {
  return settings[key] === live[key] ? "" : `Live chat uses ${formatSetting(key, live[key])}`;
}

/** The settings that differ from live chat. Example: only memory_floor moved -> ["memory_floor"]. */
export function changedSettings(settings: PlaygroundDefaults, live: PlaygroundDefaults): (keyof PlaygroundDefaults)[] {
  return (Object.keys(live) as (keyof PlaygroundDefaults)[]).filter((k) => settings[k] !== live[k]);
}

/**
 * What goes to the backend: only what differs from live chat ({} when nothing moved, so the backend behaves as live).
 * `only` limits it to some settings, e.g. SEARCH_KEYS for a search.
 */
export function settingsToSend(
  settings: PlaygroundDefaults,
  live: PlaygroundDefaults,
  only?: (keyof PlaygroundDefaults)[],
): PlaygroundSettings {
  const out: Record<string, unknown> = {};
  for (const k of changedSettings(settings, live)) if (!only || only.includes(k)) out[k] = settings[k];
  return out as PlaygroundSettings;
}

/** The settings a search uses. Memory mode and the memory card only matter in chat. */
export const SEARCH_KEYS: (keyof PlaygroundDefaults)[] = ["sources", "results", "memory_floor", "judge_min", "rerank", "rewrite"];

// ---------------------------------------------------------------------------
// REQUEST block
// ---------------------------------------------------------------------------

export type RequestLang = "cURL" | "Python" | "TypeScript";
export const REQUEST_LANGS: RequestLang[] = ["cURL", "Python", "TypeScript"];

export const SEARCH_NO_API =
  "Search has no public API yet. This tab shows what your character would find; characters search for themselves on every chat call.";

/**
 * The real public call a business's server makes to chat with this character.
 * Example: Maya, "Can I return my shoes?" ->
 *   curl -X POST https://api.example.com/api/v1/companion/chat -H "Authorization: Bearer $ANRIL_SECRET_KEY" ...
 */
export function chatRequestSnippet(lang: RequestLang, o: { apiBase: string; companionId: string; message: string }): string {
  const url = `${o.apiBase.replace(/\/+$/, "")}/api/v1/companion/chat`;
  const message = o.message.trim() || "Hello";
  const body = `{"companion_id": ${JSON.stringify(o.companionId)}, "user_id": "your-user-id", "message": ${JSON.stringify(message)}}`;
  if (lang === "cURL") {
    const shellBody = body.replace(/'/g, `'\\''`);   // a ' inside the message must not end the shell string
    return [
      `curl -X POST ${url} \\`,
      `  -H "Authorization: Bearer $ANRIL_SECRET_KEY" \\`,
      `  -H "Content-Type: application/json" \\`,
      `  -d '${shellBody}'`,
    ].join("\n");
  }
  if (lang === "Python") {
    return [
      "import os, httpx",
      "",
      "r = httpx.post(",
      `    ${JSON.stringify(url)},`,
      `    headers={"Authorization": f"Bearer {os.environ['ANRIL_SECRET_KEY']}"},`,
      `    json=${body},`,
      ")",
      `print(r.json()["reply"])`,
    ].join("\n");
  }
  return [
    `const r = await fetch(${JSON.stringify(url)}, {`,
    `  method: "POST",`,
    `  headers: {`,
    "    Authorization: `Bearer ${process.env.ANRIL_SECRET_KEY}`,",
    `    "Content-Type": "application/json",`,
    `  },`,
    `  body: JSON.stringify(${body}),`,
    `});`,
    `console.log((await r.json()).reply);`,
  ].join("\n");
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
  /** Kept first; dropped ones only when "Dropped by judge" is on. */
  knowledge: CompanionKnowledgeHit[];
  /** Kept first; below-floor ones only when "Dropped by judge" is on. */
  memories: CompanionMemoryHit[];
  /** "2 memories below strictness 0.70 hidden", or "". */
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
export const NOTICE_NOTHING = "Nothing passed. Lower the strictness or the judge minimum.";

/**
 * Turns one search response into what the screen lists, using the display-only
 * checkboxes. Example: 3 knowledge hits (1 dropped) + 2 memories below 0.70, with
 * "Dropped by judge" off -> 2 knowledge rows, 0 memory rows, hiddenLine "2 memories below strictness 0.70 hidden".
 */
export function buildSearchView(result: CompanionSearchResult, o: { showDropped: boolean; strictness: number }): SearchView {
  const wantsKnowledge = result.in !== "memories";
  const wantsMemories = result.in !== "knowledge";
  const knowledge = wantsKnowledge ? result.knowledge.filter((h) => h.kept || o.showDropped) : [];
  const memories = wantsMemories ? result.memories.filter((m) => m.kept || o.showDropped) : [];
  const belowFloor = wantsMemories ? result.memories.filter((m) => !m.kept).length : 0;
  const hiddenLine =
    !o.showDropped && belowFloor > 0
      ? `${belowFloor} ${belowFloor === 1 ? "memory" : "memories"} below strictness ${o.strictness.toFixed(2)} hidden`
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
