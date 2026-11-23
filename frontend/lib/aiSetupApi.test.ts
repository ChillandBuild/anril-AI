import { describe, expect, it } from "vitest";
import { percentLabel, questionFromSearch, rupees, safeFixHref, sameQuestion, splitChats, timesLabel } from "./aiSetupApi";

describe("aiSetupApi helpers", () => {
  it("says how often a question was asked", () => {
    expect(timesLabel(1)).toBe("asked once");
    expect(timesLabel(4)).toBe("asked 4 times");
  });
  it("shows a dash when there were no chats", () => {
    expect(percentLabel(null)).toBe("-");
    expect(percentLabel(0)).toBe("0%");
    expect(percentLabel(61.6)).toBe("62%");
  });
  it("formats rupees with Indian grouping", () => {
    expect(rupees(11800000)).toBe("₹1,18,000");
    expect(rupees(0)).toBe("₹0");
  });
  it("keeps fix links inside the dashboard", () => {
    expect(safeFixHref("/dashboard/teach")).toBe("/dashboard/teach");
    expect(safeFixHref("https://evil.example")).toBe("/dashboard/brain");
    expect(safeFixHref("//evil.example")).toBe("/dashboard/brain");
  });
  it("reads and caps the prefilled question", () => {
    expect(questionFromSearch("?question=Is%20it%20open%3F")).toBe("Is it open?");
    expect(questionFromSearch("")).toBe("");
    expect(questionFromSearch(`?question=${"a".repeat(500)}`)).toHaveLength(300);
  });
  it("matches the same question ignoring case, punctuation and spaces", () => {
    expect(sameQuestion("Do you deliver?", "do  you DELIVER")).toBe(true);
    expect(sameQuestion("Price", "Prices")).toBe(false);
  });
});


describe("splitChats", () => {
  it("takes couldn't-answer chats out of the passed-to-person segment", () => {
    expect(splitChats({ chats: 46, passed_to_person: 5, couldnt_answer: 2 })).toEqual({ alone: 41, person: 3, couldnt: 2 });
  });
  it("never goes below zero and treats a missing couldnt_answer as 0", () => {
    expect(splitChats({ chats: 2, passed_to_person: 5 })).toEqual({ alone: 0, person: 2, couldnt: 0 });
    expect(splitChats({ chats: 3, passed_to_person: 1, couldnt_answer: 4 })).toEqual({ alone: 2, person: 0, couldnt: 1 });
  });
});
