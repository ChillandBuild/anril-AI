import { describe, expect, it } from "vitest";
import type { Companion } from "@/lib/api";
import { changedFields, linesToList, nextDraftName } from "./characterForm";

const jothidar: Companion = {
  id: "c1", name: "Jothidar AI", industry: "astrology", role: "Family astrologer", backstory: "", speaking_style: "",
  sample_lines: ["Vanakkam!"], goals: [], temperament: "", default_mood: "calm", language: "ta-en", rules: [],
  knowledge_tag_id: null, memory_level: 2, memory_engine: "card", history_messages: 10, privacy_mode: "A", status: "draft",
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

  it("compares lists by value and sends a cleared tag as null", () => {
    const withTag = { ...jothidar, knowledge_tag_id: "t1" };
    expect(changedFields(jothidar, { ...jothidar, sample_lines: ["Vanakkam!"] })).toEqual({});
    expect(changedFields(withTag, jothidar)).toEqual({ knowledge_tag_id: null });
  });
});
