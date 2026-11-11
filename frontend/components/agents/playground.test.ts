import { describe, expect, it } from "vitest";
import type { CompanionKnowledgeHit, CompanionMemoryHit, CompanionSearchResult } from "@/lib/api";
import {
  FALLBACK_DEFAULTS,
  SEARCH_KEYS,
  NOTICE_NO_COLLECTION,
  NOTICE_PRIVATE,
  NOTICE_SMALL_TALK,
  buildSearchView,
  changedSettings,
  chatRequestSnippet,
  documentLine,
  formatMs,
  formatSetting,
  formatToolCall,
  judgePill,
  liveNote,
  memoryScoreText,
  memoryPersonLine,
  memoryTag,
  pairCompareReplies,
  resultCountText,
  NOTICE_KNOWLEDGE_ERROR,
  parseToolOutput,
  replySourceLine,
  settingsToSend,
  sourceText,
  stepValue,
  toolNameError,
} from "./playground";

describe("formatToolCall", () => {
  it("shows name and args", () => {
    expect(formatToolCall({ id: "1", name: "get_chart", args: { dob: "1990-04-12" } })).toBe('get_chart({"dob":"1990-04-12"})');
    expect(formatToolCall({ id: "1", name: "get_chart" })).toBe("get_chart()");
  });

  it("cuts long args", () => {
    const out = formatToolCall({ id: "1", name: "t", args: { x: "a".repeat(200) } });
    expect(out.length).toBeLessThanOrEqual(84);
    expect(out.endsWith("…)")).toBe(true);
  });
});

describe("parseToolOutput", () => {
  it("sends a JSON object as an object, anything else as text", () => {
    expect(parseToolOutput(' {"lagna": "Kumbham"} ')).toEqual({ lagna: "Kumbham" });
    expect(parseToolOutput("Lagna is Kumbham")).toBe("Lagna is Kumbham");
    expect(parseToolOutput("{broken")).toBe("{broken");
    expect(parseToolOutput("[1,2]")).toBe("[1,2]");
  });
});

describe("formatMs", () => {
  it("uses ms under a second, seconds above", () => {
    expect(formatMs(820.4)).toBe("820 ms");
    expect(formatMs(1400)).toBe("1.4 s");
  });
});

describe("toolNameError", () => {
  it("matches the backend name rule", () => {
    expect(toolNameError("get_chart", [])).toBe("");
    expect(toolNameError("GetChart", [])).not.toBe("");
    expect(toolNameError("get_chart", ["get_chart"])).toBe("That tool is already in the list.");
  });
});

describe("sourceText", () => {
  it("gives the title and the page or page range", () => {
    expect(sourceText({ document: "Book 7", page_from: 212, page_to: 213 })).toBe("Book 7, pp. 212-213");
    expect(sourceText({ document: "Main resource", page_from: 12, page_to: 12 })).toBe("Main resource, p. 12");
  });
});

describe("replySourceLine", () => {
  const sources = [
    { document: "Main resource", page_from: 12, page_to: 12 },
    { document: "Book 7", page_from: 212, page_to: 213 },
  ];
  it("lists the sources for a book answer", () => {
    expect(replySourceLine("primary", sources)).toBe("From Main resource, p. 12; Book 7, pp. 212-213");
    expect(replySourceLine("book", [sources[1]])).toBe("From Book 7, pp. 212-213");
  });
  it("says an own answer is not from the books", () => {
    expect(replySourceLine("own", [])).toBe("Own reasoning, not from your files");
  });
  it("shows nothing for chat, null, missing, or a book answer with no sources", () => {
    expect(replySourceLine("chat", sources)).toBe("");
    expect(replySourceLine(null, sources)).toBe("");
    expect(replySourceLine(undefined, undefined)).toBe("");
    expect(replySourceLine("book", [])).toBe("");
  });
});

describe("stepValue", () => {
  it("steps without float noise and stays in range", () => {
    expect(stepValue(0.7, 0.05, 0.3, 0.95)).toBe(0.75);
    expect(stepValue(0.95, 0.05, 0.3, 0.95)).toBe(0.95);
    expect(stepValue(0.3, -0.05, 0.3, 0.95)).toBe(0.3);
    expect(stepValue(20, 1, 1, 20)).toBe(20);
    expect(stepValue(0, -1, 0, 3)).toBe(0);
  });
});

describe("settings vs live chat", () => {
  const live = FALLBACK_DEFAULTS;
  it("formats values the way the panel shows them", () => {
    expect(formatSetting("memory_floor", 0.7)).toBe("0.70");
    expect(formatSetting("judge_min", 2)).toBe("2 / 3");
    expect(formatSetting("rerank", true)).toBe("Judge");
    expect(formatSetting("rerank", false)).toBe("Off");
    expect(formatSetting("rewrite", false)).toBe("off");
    expect(formatSetting("mode", "agentic")).toBe("Agentic");
    expect(formatSetting("sources", "memories")).toBe("Memories");
  });
  it("says what live chat uses only for a changed setting", () => {
    const moved = { ...live, memory_floor: 0.6, rewrite: false };
    expect(liveNote("memory_floor", moved, live)).toBe("Live chat uses 0.70");
    expect(liveNote("rewrite", moved, live)).toBe("Live chat uses on");
    expect(liveNote("results", moved, live)).toBe("");
  });
  it("lists and sends only what differs", () => {
    const moved = { ...live, memory_floor: 0.6, rerank: false };
    expect(changedSettings(moved, live)).toEqual(["memory_floor", "rerank"]);
    expect(settingsToSend(moved, live)).toEqual({ memory_floor: 0.6, rerank: false });
    expect(settingsToSend(live, live)).toEqual({});
  });
  it("a search leaves out chat-only settings", () => {
    const moved = { ...live, mode: "agentic" as const, memory_card: false, judge_min: 3 };
    expect(settingsToSend(moved, live, SEARCH_KEYS)).toEqual({ judge_min: 3 });
  });
});

describe("chatRequestSnippet", () => {
  const o = { apiBase: "https://api.example.com/", companionId: "c-1", message: "Can I return my shoes?" };
  it("builds the real public chat call in cURL", () => {
    const out = chatRequestSnippet("cURL", o);
    expect(out).toContain("curl -X POST https://api.example.com/api/v1/companion/chat \\");
    expect(out).toContain('Authorization: Bearer $ANRIL_SECRET_KEY');
    expect(out).toContain('"companion_id": "c-1", "user_id": "your-user-id", "message": "Can I return my shoes?"');
  });
  it("uses Hello when nothing was typed, and keeps an apostrophe from ending the shell string", () => {
    expect(chatRequestSnippet("Python", { ...o, message: "  " })).toContain('"message": "Hello"');
    expect(chatRequestSnippet("cURL", { ...o, message: "what's up" })).toContain("what'\\''s up");
  });
  it("builds Python and TypeScript", () => {
    expect(chatRequestSnippet("Python", o)).toContain('"https://api.example.com/api/v1/companion/chat"');
    expect(chatRequestSnippet("TypeScript", o)).toContain("JSON.stringify({");
    expect(chatRequestSnippet("TypeScript", o)).toContain("process.env.ANRIL_SECRET_KEY");
  });
});

describe("row labels", () => {
  it("judgePill shows the mark and the verdict", () => {
    expect(judgePill(3, true)).toEqual({ text: "judge 3/3 · kept", tone: "ok" });
    expect(judgePill(1, false)).toEqual({ text: "judge 1/3 · dropped", tone: "bad" });
    expect(judgePill(null, true)).toEqual({ text: "judge off", tone: "neutral" });
  });
  it("memoryTag names the kind", () => {
    expect(memoryTag("fact")).toBe("Memory · Fact");
    expect(memoryTag("messages")).toBe("Memory · Conversation");
    expect(memoryTag("diary")).toBe("Memory · Diary");
  });
  it("documentLine gives the file and its pages", () => {
    expect(documentLine({ document: "Returns policy.pdf", page_from: 2, page_to: 2 })).toBe("Returns policy.pdf · p. 2");
    expect(documentLine({ document: "FAQ", page_from: 2, page_to: 3 })).toBe("FAQ · pp. 2-3");
  });
  it("memoryScoreText shows meaning, or words when matched word by word", () => {
    const hit = { meaning: 0.834, words: 2 };
    expect(memoryScoreText(hit, "meaning")).toBe("meaning 0.83");
    expect(memoryScoreText(hit, "words")).toBe("words 2");
    expect(memoryScoreText({ meaning: null, words: null }, "meaning")).toBe("");
  });
});

describe("memoryPersonLine", () => {
  it("names whose fact it is", () => {
    expect(memoryPersonLine({ external_user_id: "cust_1042", display_name: "Karthik" })).toBe("Karthik (cust_1042)");
    expect(memoryPersonLine({ external_user_id: "cust_1042", display_name: null })).toBe("cust_1042");
    expect(memoryPersonLine({})).toBe("");
  });
});

describe("buildSearchView", () => {
  const k = (kept: boolean): CompanionKnowledgeHit => ({
    document: "Returns policy.pdf", page_from: 2, page_to: 2, heading_path: "", text: "t", tier: 1, step: "main", score: kept ? 3 : 1, meaning: 0.8, kept,
  });
  const m = (kept: boolean): CompanionMemoryHit => ({ kind: "fact", day: null, text: "x", meaning: 0.8, words: null, kept });
  const base: CompanionSearchResult = {
    in: "all", needs_docs: true, no_collection: false, rewritten: null,
    knowledge: [k(true), k(false)], memories: [m(true), m(false), m(false)], memory_mode: "meaning", memories_hidden: null,
  };

  it("hides dropped passages and below-floor memories, and says how many memories", () => {
    const v = buildSearchView(base, { showDropped: false, strictness: 0.7 });
    expect(v.knowledge).toHaveLength(1);
    expect(v.memories).toHaveLength(1);
    expect(v.hiddenLine).toBe("2 memories below strictness 0.70 hidden");
  });
  it("shows them all, no hidden line, when Dropped by judge is on", () => {
    const v = buildSearchView(base, { showDropped: true, strictness: 0.7 });
    expect(v.knowledge).toHaveLength(2);
    expect(v.memories).toHaveLength(3);
    expect(v.hiddenLine).toBe("");
  });
  it("says 'memory' for one", () => {
    const v = buildSearchView({ ...base, memories: [m(false)] }, { showDropped: false, strictness: 0.6 });
    expect(v.hiddenLine).toBe("1 memory below strictness 0.60 hidden");
  });
  it("explains empty states", () => {
    const empty = { ...base, knowledge: [], memories: [] };
    expect(buildSearchView({ ...empty, no_collection: true }, { showDropped: false, strictness: 0.7 }).notices).toEqual([NOTICE_NO_COLLECTION]);
    expect(buildSearchView({ ...empty, needs_docs: false }, { showDropped: false, strictness: 0.7 }).notices).toEqual([NOTICE_SMALL_TALK]);
    expect(buildSearchView({ ...empty, memories_hidden: "private" }, { showDropped: false, strictness: 0.7 }).notices).toEqual([NOTICE_PRIVATE]);
    const none = buildSearchView(empty, { showDropped: false, strictness: 0.7 });
    expect(none.notices).toEqual([]);
    expect(none.nothingPassed).toBe(true);
  });
  it("flags a knowledge failure and does not call it 'nothing passed'", () => {
    const v = buildSearchView({ ...base, knowledge: [], memories: [], knowledge_error: true }, { showDropped: false, strictness: 0.7 });
    expect(v.knowledgeError).toBe(true);
    expect(v.nothingPassed).toBe(false);
    expect(NOTICE_KNOWLEDGE_ERROR).toContain("isn't available");
    expect(buildSearchView({ ...base, in: "memories", knowledge_error: true }, { showDropped: false, strictness: 0.7 }).knowledgeError).toBe(false);
  });
  it("counts what is listed, for the screen reader", () => {
    expect(resultCountText({ knowledge: [k(true), k(true)], memories: [m(true)] })).toBe("2 passages, 1 memory");
    expect(resultCountText({ knowledge: [], memories: [] })).toBe("No results");
  });
  it("ignores the side that was not searched", () => {
    const v = buildSearchView({ ...base, in: "memories", no_collection: true, needs_docs: false }, { showDropped: false, strictness: 0.7 });
    expect(v.knowledge).toEqual([]);
    expect(v.notices).toEqual([]);
    const kn = buildSearchView({ ...base, in: "knowledge", memories_hidden: "private" }, { showDropped: false, strictness: 0.7 });
    expect(kn.memories).toEqual([]);
    expect(kn.hiddenLine).toBe("");
    expect(kn.notices).toEqual([]);
  });
});

describe("pairCompareReplies", () => {
  type B = { kind: string; text: string; label?: string };
  it("puts the without-memory reply beside its reply", () => {
    const user: B = { kind: "user", text: "hi" };
    const a: B = { kind: "reply", text: "a" };
    const b: B = { kind: "reply", text: "b", label: "Without memory" };
    expect(pairCompareReplies([user, a, b])).toEqual([user, [a, b]]);
  });
  it("leaves lone replies alone", () => {
    const a: B = { kind: "reply", text: "a" };
    const b: B = { kind: "reply", text: "b", label: "Without memory" };
    expect(pairCompareReplies([a])).toEqual([a]);
    expect(pairCompareReplies([b])).toEqual([b]);
  });
});
