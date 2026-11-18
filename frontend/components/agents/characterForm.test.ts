import { describe, expect, it } from "vitest";
import type { Companion } from "@/lib/api";
import { STARTER_RULES, changedFields, collectionIdOf, genericHandoff, linesToList, nameMatches, nextDraftName, ownReasoningOn, answerModeOf, withIndustry } from "./characterForm";

const jothidar: Companion = {
  id: "c1", name: "Maya", industry: "general", role: "Support guide", backstory: "", speaking_style: "",
  sample_lines: ["Vanakkam!"], goals: [], temperament: "", default_mood: "calm", language: "ta-en", model: "google/gemini-3.1-flash-lite", rules: [],
  knowledge_tag_id: null, knowledge_collection_id: null, own_reasoning: true, memory_level: 2, memory_engine: "card", history_messages: 10, privacy_mode: "A", status: "draft",
};

describe("nextDraftName", () => {
  it("picks the first free name, case-insensitive", () => {
    expect(nextDraftName([])).toBe("New character");
    expect(nextDraftName(["new character", "New character 2"])).toBe("New character 3");
  });
});

describe("linesToList", () => {
  it("trims and drops blank lines", () => {
    expect(linesToList(" Vanakkam!\n\n  Eppadi irukeenga? \n")).toEqual(["Vanakkam!", "Eppadi irukeenga?"]);
  });
});

describe("changedFields", () => {
  it("sends only what changed", () => {
    expect(changedFields(jothidar, { ...jothidar, default_mood: "warm", status: "live" })).toEqual({ default_mood: "warm", status: "live" });
  });

  it("compares lists by value", () => {
    expect(changedFields(jothidar, { ...jothidar, sample_lines: ["Vanakkam!"] })).toEqual({});
  });

  it("sends only the model when the AI model changes", () => {
    expect(changedFields(jothidar, { ...jothidar, model: "google/gemini-3.5-flash-lite" })).toEqual({ model: "google/gemini-3.5-flash-lite" });
    expect(changedFields(jothidar, { ...jothidar })).not.toHaveProperty("model");
    expect(changedFields(jothidar, { ...jothidar, full_main_resource: false })).not.toHaveProperty("full_main_resource");
    expect(changedFields(jothidar, { ...jothidar, full_main_resource: true })).toEqual({ full_main_resource: true });
    expect(changedFields(jothidar, { ...jothidar, working_step: true })).toEqual({ working_step: true });
    // Small talk model: missing and null are the same ("same as AI model"); a pick or a clear is sent.
    expect(changedFields(jothidar, { ...jothidar, small_talk_model: null })).not.toHaveProperty("small_talk_model");
    expect(changedFields(jothidar, { ...jothidar, small_talk_model: "google/gemini-3.5-flash-lite" })).toEqual({ small_talk_model: "google/gemini-3.5-flash-lite" });
    expect(changedFields({ ...jothidar, small_talk_model: "google/gemini-3.5-flash-lite" }, { ...jothidar, small_talk_model: null })).toEqual({ small_talk_model: null });
  });

  it("never sends the old books tag", () => {
    expect(changedFields(jothidar, { ...jothidar, knowledge_tag_id: "t1" })).toEqual({});
  });

  it("sends neither book field when the form is unchanged", () => {
    const out = changedFields(jothidar, { ...jothidar });
    expect(out).not.toHaveProperty("knowledge_collection_id");
    expect(out).not.toHaveProperty("own_reasoning");
  });

  it("sends only the collection when it changes", () => {
    expect(changedFields(jothidar, { ...jothidar, knowledge_collection_id: "col1" })).toEqual({ knowledge_collection_id: "col1" });
  });

  it("sends null when No books replaces a collection", () => {
    const reading = { ...jothidar, knowledge_collection_id: "col1" };
    expect(changedFields(reading, { ...reading, knowledge_collection_id: null })).toEqual({ knowledge_collection_id: null });
  });

  it("sends own_reasoning false only when switched off", () => {
    expect(changedFields(jothidar, { ...jothidar, own_reasoning: false })).toEqual({ own_reasoning: false });
  });

  it("treats a character without the new fields as no books and reasoning on", () => {
    const older: Companion = { ...jothidar };
    delete older.knowledge_collection_id;
    delete older.own_reasoning;
    expect(collectionIdOf(older)).toBeNull();
    expect(ownReasoningOn(older)).toBe(true);
    expect(changedFields(older, { ...older })).toEqual({});
    expect(changedFields(older, { ...older, own_reasoning: false })).toEqual({ own_reasoning: false });
    expect(changedFields(older, { ...older, own_reasoning: true })).toEqual({});
  });

  it("shows own reasoning on as Mixed and off as Strict; an older character is Mixed", () => {
    const older: Companion = { ...jothidar };
    delete older.own_reasoning;
    expect(answerModeOf(jothidar)).toBe("mixed");
    expect(answerModeOf({ ...jothidar, own_reasoning: false })).toBe("strict");
    expect(answerModeOf(older)).toBe("mixed");
  });
});

describe("nameMatches (typing a Live character's name before Delete permanently)", () => {
  it("ignores case and spaces at the ends", () => {
    expect(nameMatches(" jothidar ai ", "Jothidar AI")).toBe(true);
  });
  it("needs the whole name", () => {
    expect(nameMatches("Jothidar", "Jothidar AI")).toBe(false);
    expect(nameMatches("", "Jothidar AI")).toBe(false);
    expect(nameMatches("   ", "   ")).toBe(false);
  });
});

describe("Strict handoff line", () => {
  it("sends the trimmed line, and null when the box is emptied", () => {
    expect(changedFields(jothidar, { ...jothidar, handoff_line: "  Ask our astrologer.  " })).toEqual({ handoff_line: "Ask our astrologer." });
    const own = { ...jothidar, handoff_line: "Ask our astrologer." };
    expect(changedFields(own, { ...own, handoff_line: "   " })).toEqual({ handoff_line: null });
  });

  it("sends nothing for an older character with no line, or spaces only", () => {
    expect(changedFields(jothidar, { ...jothidar })).toEqual({});
    expect(changedFields(jothidar, { ...jothidar, handoff_line: "" })).toEqual({});
    expect(changedFields({ ...jothidar, handoff_line: null }, { ...jothidar, handoff_line: "  " })).toEqual({});
  });

  it("shows the generic line in the character's language as the placeholder", () => {
    expect(genericHandoff("en")).toBe("Our team can help you with this better.");
    expect(genericHandoff("xx")).toBe("Our team can help you with this better.");
    expect(genericHandoff("ta")).toBe("இதற்கு எங்கள் குழுவிடம் கேட்பது நல்லது.");
  });
});

describe("withIndustry", () => {
  it("fills the astrology starter rules into an empty Rules box, editable like any rule", () => {
    const astro = withIndustry(jothidar, "astrology");
    expect(astro.industry).toBe("astrology");
    expect(astro.rules).toEqual(STARTER_RULES.astrology);
    expect(astro.rules[0]).toContain("Never predict death");
    expect(changedFields(jothidar, astro)).toEqual({ industry: "astrology", rules: STARTER_RULES.astrology });
  });

  it("never touches rules the owner already wrote", () => {
    const written = { ...jothidar, rules: ["Speak only Tamil"] };
    expect(withIndustry(written, "astrology").rules).toBe(written.rules);
    expect(withIndustry({ ...written, industry: "astrology" }, "general").rules).toBe(written.rules);
  });

  it("gives General no rules of its own", () => {
    expect(withIndustry(jothidar, "general").rules).toEqual([]);
  });
});
