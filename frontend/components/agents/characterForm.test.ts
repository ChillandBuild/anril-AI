import { describe, expect, it } from "vitest";
import type { Companion } from "@/lib/api";
import { changedFields, collectionIdOf, linesToList, nextDraftName, ownReasoningOn } from "./characterForm";

const jothidar: Companion = {
  id: "c1", name: "Jothidar AI", industry: "astrology", role: "Family astrologer", backstory: "", speaking_style: "",
  sample_lines: ["Vanakkam!"], goals: [], temperament: "", default_mood: "calm", language: "ta-en", rules: [],
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
});
