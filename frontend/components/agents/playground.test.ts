import { describe, expect, it } from "vitest";
import type { CompanionKnowledgeHit, CompanionMemoryHit, CompanionSearchResult } from "@/lib/api";
import {
  FALLBACK_DEFAULTS,
  NOTICE_NO_COLLECTION,
  NOTICE_PRIVATE,
  NOTICE_SMALL_TALK,
  buildSearchView,
  documentLine,
  formatMs,
  formatToolCall,
  judgePill,
  memoryPersonLine,
  memoryScoreText,
  memoryStatusLine,
  memoryTag,
  modelChoices,
  modelLabel,
  pairCompareReplies,
  personLabel,
  resultCountText,
  NOTICE_KNOWLEDGE_ERROR,
  parseToolOutput,
  replySourceLine,
  saveMemoryResult,
  sourceText,
  sourcesSetting,
  suggestionsFor,
  toolNameError,
  usedLine,
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

describe("sourcesSetting", () => {
  it("sends only a source that differs from live chat", () => {
    expect(sourcesSetting("knowledge", FALLBACK_DEFAULTS)).toEqual({ sources: "knowledge" });
    expect(sourcesSetting("memories", FALLBACK_DEFAULTS)).toEqual({ sources: "memories" });
    expect(sourcesSetting("all", FALLBACK_DEFAULTS)).toEqual({});
  });
});

describe("model chip", () => {
  const models = [
    { id: "google/gemini-3.1-flash-lite", label: "Gemini 3.1 Flash Lite" },
    { id: "google/gemini-3.5-flash-lite", label: "Gemini 3.5 Flash Lite" },
  ];
  it("names the character's own model in the list", () => {
    expect(modelChoices(models, "google/gemini-3.1-flash-lite", "Maya")).toEqual([
      { value: "google/gemini-3.1-flash-lite", label: "Gemini 3.1 Flash Lite · Maya's model" },
      { value: "google/gemini-3.5-flash-lite", label: "Gemini 3.5 Flash Lite" },
    ]);
  });
  it("still lists a saved model that is no longer offered, first", () => {
    const out = modelChoices(models, "old/model", "Maya");
    expect(out[0]).toEqual({ value: "old/model", label: "old/model · Maya's model" });
    expect(out).toHaveLength(3);
  });
  it("labels a model, or falls back to its id", () => {
    expect(modelLabel(models, "google/gemini-3.5-flash-lite")).toBe("Gemini 3.5 Flash Lite");
    expect(modelLabel(models, "old/model")).toBe("old/model");
  });
});

describe("suggestionsFor", () => {
  const astro = { industry: "astrology" as const, knowledge_collection_id: null };
  const general = { industry: "general" as const };
  it("astrology in Tamil: two memory questions + the marriage question", () => {
    expect(suggestionsFor({ ...astro, language: "ta" })).toEqual([
      "என்னைப் பற்றி உங்களுக்கு என்ன தெரியும்?",
      "போன முறை நான் என்ன சொன்னேன்?",
      "திருமணம் பற்றி முதலில் எதைப் பார்க்க வேண்டும்?",
    ]);
  });
  it("astrology in Tanglish", () => {
    expect(suggestionsFor({ ...astro, language: "ta-en" })).toEqual([
      "Ennai pathi enna theriyum?",
      "Pona thadava naan enna sonnen?",
      "Kalyanam pathi mudhalla edha paakanum?",
    ]);
  });
  it("astrology in English, and an unknown language falls back to English", () => {
    const en = ["What do you know about me?", "What did I tell you last time?", "What should I check first about marriage?"];
    expect(suggestionsFor({ ...astro, language: "en" })).toEqual(en);
    expect(suggestionsFor({ ...astro, language: "fr" })).toEqual(en);
  });
  it("general with files asks what the files cover, per language", () => {
    expect(suggestionsFor({ ...general, language: "en", knowledge_collection_id: "col1" })[2]).toBe("What do your files cover?");
    expect(suggestionsFor({ ...general, language: "ta", knowledge_collection_id: "col1" })[2]).toBe("உங்கள் கோப்புகளில் என்ன இருக்கிறது?");
    expect(suggestionsFor({ ...general, language: "ta-en", knowledge_collection_id: "col1" })[2]).toBe("Unga files-la enna irukku?");
  });
  it("general without files (or with the field missing) gets the two memory questions only", () => {
    expect(suggestionsFor({ ...general, language: "en", knowledge_collection_id: null })).toEqual([
      "What do you know about me?",
      "What did I tell you last time?",
    ]);
    expect(suggestionsFor({ ...general, language: "ta" })).toHaveLength(2);
  });
  it("never mentions returns", () => {
    for (const language of ["ta", "ta-en", "en"]) {
      for (const industry of ["astrology", "general"] as const) {
        expect(suggestionsFor({ industry, language, knowledge_collection_id: "c" }).join(" ").toLowerCase()).not.toContain("return");
      }
    }
  });
});

describe("personLabel", () => {
  it("shows the typed name, 'You' for the owner's own test id, else the id", () => {
    expect(personLabel({ display_name: "Asha", is_test: true, external_user_id: "owner-test:u1:t4k9xz" })).toBe("Asha");
    expect(personLabel({ display_name: null, is_test: true, external_user_id: "owner-test:u1" })).toBe("You");
    expect(personLabel({ display_name: null, is_test: false, external_user_id: "cust_1042" })).toBe("cust_1042");
    expect(personLabel({ display_name: "Karthik", is_test: false, external_user_id: "cust_1042" })).toBe("Karthik");
  });
});

describe("memoryStatusLine", () => {
  const maya = { name: "Maya", history_messages: 10 };
  it("level 2: counts toward the save, Save now only when something is unread", () => {
    expect(memoryStatusLine({ level: 2, unread: 3, saves_at: 8 }, maya)).toEqual({
      text: "Maya saves memories after 8 messages or overnight. 3 of 8 so far",
      canSave: true,
    });
    expect(memoryStatusLine({ level: 2, unread: 0, saves_at: 8 }, maya).canSave).toBe(false);
  });
  it("level 1: says nothing is saved long-term, no button", () => {
    expect(memoryStatusLine({ level: 1, unread: 4, saves_at: 8 }, maya)).toEqual({
      text: "Maya keeps only the last 10 messages; nothing is saved long-term.",
      canSave: false,
    });
  });
});

describe("saveMemoryResult", () => {
  const o = { facts: 3, character: "Maya", person: "Asha", isYou: false };
  it("saved: names the facts and the person, links to the memories", () => {
    expect(saveMemoryResult("saved", o)).toEqual({ text: "Memory saved: Maya remembers 3 facts about Asha.", tone: "ok", seeThem: true });
    expect(saveMemoryResult("saved", { ...o, facts: 1 }).text).toBe("Memory saved: Maya remembers 1 fact about Asha.");
    expect(saveMemoryResult("saved", { ...o, isYou: true }).text).toBe("Memory saved: Maya remembers 3 facts about you.");
    expect(saveMemoryResult("saved", { ...o, facts: null })).toMatchObject({ tone: "ok", seeThem: false });
  });
  it("the other outcomes explain themselves and show no link", () => {
    expect(saveMemoryResult("nothing_new", o)).toEqual({ text: "Nothing new to save yet.", tone: "info", seeThem: false });
    expect(saveMemoryResult("busy", o).text).toBe("Already saving, try again in a minute.");
    expect(saveMemoryResult("waiting", o).text).toBe("The last reply is still being written. Try again in a few seconds.");
    expect(saveMemoryResult("waiting", o).seeThem).toBe(false);
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
    const v = buildSearchView(base, { showDropped: false });
    expect(v.knowledge).toHaveLength(1);
    expect(v.memories).toHaveLength(1);
    expect(v.hiddenLine).toBe("2 weak-match memories hidden");
  });
  it("shows them all, no hidden line, when the dropped box is ticked", () => {
    const v = buildSearchView(base, { showDropped: true });
    expect(v.knowledge).toHaveLength(2);
    expect(v.memories).toHaveLength(3);
    expect(v.hiddenLine).toBe("");
  });
  it("says 'memory' for one", () => {
    const v = buildSearchView({ ...base, memories: [m(false)] }, { showDropped: false });
    expect(v.hiddenLine).toBe("1 weak-match memory hidden");
  });
  it("explains empty states", () => {
    const empty = { ...base, knowledge: [], memories: [] };
    expect(buildSearchView({ ...empty, no_collection: true }, { showDropped: false }).notices).toEqual([NOTICE_NO_COLLECTION]);
    expect(buildSearchView({ ...empty, needs_docs: false }, { showDropped: false }).notices).toEqual([NOTICE_SMALL_TALK]);
    expect(buildSearchView({ ...empty, memories_hidden: "private" }, { showDropped: false }).notices).toEqual([NOTICE_PRIVATE]);
    const none = buildSearchView(empty, { showDropped: false });
    expect(none.notices).toEqual([]);
    expect(none.nothingPassed).toBe(true);
  });
  it("flags a knowledge failure and does not call it 'nothing passed'", () => {
    const v = buildSearchView({ ...base, knowledge: [], memories: [], knowledge_error: true }, { showDropped: false });
    expect(v.knowledgeError).toBe(true);
    expect(v.nothingPassed).toBe(false);
    expect(NOTICE_KNOWLEDGE_ERROR).toContain("isn't available");
    expect(buildSearchView({ ...base, in: "memories", knowledge_error: true }, { showDropped: false }).knowledgeError).toBe(false);
  });
  it("counts what is listed, for the screen reader", () => {
    expect(resultCountText({ knowledge: [k(true), k(true)], memories: [m(true)] })).toBe("2 passages, 1 memory");
    expect(resultCountText({ knowledge: [], memories: [] })).toBe("No results");
  });
  it("ignores the side that was not searched", () => {
    const v = buildSearchView({ ...base, in: "memories", no_collection: true, needs_docs: false }, { showDropped: false });
    expect(v.knowledge).toEqual([]);
    expect(v.notices).toEqual([]);
    const kn = buildSearchView({ ...base, in: "knowledge", memories_hidden: "private" }, { showDropped: false });
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

describe("usedLine", () => {
  const src = [{ document: "Main resource", page_from: 12, page_to: 12 }];
  it("names notes and past chats, and the files", () => {
    expect(usedLine({ card_lines: 6, memory_hits: 2 }, "primary", src, null)).toBe(
      "Its notes about you + 2 past chats · From Main resource, p. 12",
    );
  });
  it("uses the person's name for a test customer", () => {
    expect(usedLine({ card_lines: 6, memory_hits: 0 }, "own", [], "Meena")).toBe("Its notes about Meena · Own reasoning, not from your files");
    expect(usedLine({ card_lines: 0, memory_hits: 1 }, null, [], "Meena")).toBe("1 past chat with Meena · Not from your files");
    expect(usedLine({ card_lines: 0, memory_hits: 3 }, "chat", [], null)).toBe("3 past chats with you · Not from your files");
  });
  it("says so when nothing was remembered", () => {
    expect(usedLine({ card_lines: 0, memory_hits: 0 }, "chat", [], "Meena")).toBe("Nothing it remembers about Meena yet · Not from your files");
    expect(usedLine({ card_lines: 0, memory_hits: 0 }, "chat", [], null)).toBe("Nothing it remembers about you yet · Not from your files");
  });
  it("for an old saved reply (no used) shows only the file part, or nothing", () => {
    expect(usedLine(undefined, "book", src, null)).toBe("From Main resource, p. 12");
    expect(usedLine(undefined, "chat", [], null)).toBe("");
    expect(usedLine(undefined, null, undefined, null)).toBe("");
  });
});
