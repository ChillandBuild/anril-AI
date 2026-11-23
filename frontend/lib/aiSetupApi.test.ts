import { describe, expect, it } from "vitest";
import { percentLabel, questionFromSearch, rupees, safeFixHref, sameQuestion, timesLabel } from "./aiSetupApi";

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
