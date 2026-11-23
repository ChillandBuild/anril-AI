import { describe, expect, it } from "vitest";
import { paiseToRupeesText, rupeesToPaise, usedByLabel } from "./groupRuleMoney";

describe("rupeesToPaise", () => {
  it("reads plain, comma and rupee-sign amounts", () => {
    expect(rupeesToPaise("1500")).toBe(150000);
    expect(rupeesToPaise("₹ 1,500")).toBe(150000);
    expect(rupeesToPaise("99.5")).toBe(9950);
  });
  it("gives undefined for empty, text or negative", () => {
    expect(rupeesToPaise("")).toBeUndefined();
    expect(rupeesToPaise("abc")).toBeUndefined();
    expect(rupeesToPaise("-5")).toBeUndefined();
  });
  it("caps a huge number", () => {
    expect(rupeesToPaise("999999999999")).toBe(100_000_000 * 100);
  });
});

describe("paiseToRupeesText", () => {
  it("shows whole rupees without decimals", () => {
    expect(paiseToRupeesText(150000)).toBe("1500");
    expect(paiseToRupeesText(9950)).toBe("99.50");
  });
  it("is empty for zero or missing", () => {
    expect(paiseToRupeesText(0)).toBe("");
    expect(paiseToRupeesText(undefined)).toBe("");
  });
});

describe("usedByLabel", () => {
  it("joins the places with dots", () => {
    expect(usedByLabel(["Reach", "Call IQ", "Follow-ups"])).toBe("Used by Reach · Call IQ · Follow-ups");
  });
  it("says so when nothing uses the group", () => {
    expect(usedByLabel([])).toBe("Not used yet");
    expect(usedByLabel(undefined)).toBe("Not used yet");
  });
});
