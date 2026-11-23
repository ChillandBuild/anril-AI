import { describe, expect, it } from "vitest";
import {
  advanceFor,
  belowMinLine,
  cleanNumberText,
  draftError,
  draftFromRule,
  exampleLine,
  formatRupees,
  roundHalfEven,
  ruleFromDraft,
  ruleSummary,
  sameRule,
  type AdvanceRule,
} from "./advanceText";

const pct = (value: number, min = 0): AdvanceRule => ({ kind: "percent", value, min_total_paise: min });
const fixed = (value: number, min = 0): AdvanceRule => ({ kind: "fixed", value, min_total_paise: min });
const none: AdvanceRule = { kind: "none", value: 0, min_total_paise: 0 };

describe("formatRupees", () => {
  it("uses Indian grouping and shows paise only when there are some", () => {
    expect(formatRupees(20_000_000)).toBe("₹2,00,000");
    expect(formatRupees(1_050_000)).toBe("₹10,500");
    expect(formatRupees(150)).toBe("₹1.50");
    expect(formatRupees(null)).toBe("—");
  });
});

describe("advanceFor (same maths as the backend)", () => {
  it("percent of the bill", () => {
    expect(advanceFor(1_050_000, pct(40))).toBe(420_000);
  });
  it("fixed rupees, never more than the bill", () => {
    expect(advanceFor(1_050_000, fixed(1000))).toBe(100_000);
    expect(advanceFor(50_000, fixed(1000))).toBe(50_000);
  });
  it("none, zero total and below the minimum ask for nothing", () => {
    expect(advanceFor(1_050_000, none)).toBe(0);
    expect(advanceFor(0, pct(30))).toBe(0);
    expect(advanceFor(400_000, pct(30, 500_000))).toBe(0);
    expect(advanceFor(500_000, pct(30, 500_000))).toBe(150_000);
  });
  it("rounds half to even like Python, so the example matches what the order asks", () => {
    // 25 paise x 30% = 7.5 -> 8 (even); 35 paise x 30% = 10.5 -> 10 (even)
    expect(roundHalfEven(7.5)).toBe(8);
    expect(roundHalfEven(10.5)).toBe(10);
    expect(roundHalfEven(2.4)).toBe(2);
    expect(advanceFor(35, pct(30))).toBe(10);
  });
});

describe("exampleLine", () => {
  it("shows advance and balance at pickup", () => {
    expect(exampleLine(pct(40))).toBe("Example: a ₹10,500 order → advance ₹4,200, balance ₹6,300 at pickup");
  });
  it("no advance rule", () => {
    expect(exampleLine(none)).toBe("Example: a ₹10,500 order → no advance, all ₹10,500 is paid at pickup");
  });
  it("uses an order above the minimum when the minimum is bigger than the example", () => {
    expect(exampleLine(fixed(5000, 2_000_000))).toBe("Example: a ₹20,000 order → advance ₹5,000, balance ₹15,000 at pickup");
  });
  it("belowMinLine only when a minimum is set", () => {
    expect(belowMinLine(pct(30))).toBeNull();
    expect(belowMinLine(pct(30, 500_000))).toBe("Orders under ₹5,000 pay in full.");
  });
});

describe("ruleSummary", () => {
  it("reads in plain words", () => {
    expect(ruleSummary(none)).toBe("No advance");
    expect(ruleSummary(pct(30))).toBe("30% of the bill");
    expect(ruleSummary(fixed(1000, 500_000))).toBe("₹1,000, only for orders of ₹5,000 or more");
  });
});

describe("draft", () => {
  it("round-trips a rule", () => {
    for (const rule of [none, pct(30), fixed(1000, 500_000)]) {
      expect(sameRule(ruleFromDraft(draftFromRule(rule)), rule)).toBe(true);
    }
  });
  it("accepts typed money with commas and the rupee sign", () => {
    expect(cleanNumberText("₹ 5,000")).toBe("5000");
    expect(cleanNumberText("abc")).toBe("");
    expect(ruleFromDraft({ kind: "fixed", valueText: "1,000", minText: "₹5,000" })).toEqual(fixed(1000, 500_000));
  });
  it("explains what is wrong", () => {
    expect(draftError({ kind: "none", valueText: "", minText: "" })).toBeNull();
    expect(draftError({ kind: "percent", valueText: "", minText: "" })).toMatch(/percent/);
    expect(draftError({ kind: "percent", valueText: "101", minText: "" })).toMatch(/up to 100/);
    expect(draftError({ kind: "percent", valueText: "0", minText: "" })).toMatch(/above 0/);
    expect(draftError({ kind: "percent", valueText: "30", minText: "" })).toBeNull();
    expect(draftError({ kind: "fixed", valueText: "0", minText: "" })).toMatch(/rupees/);
    expect(draftError({ kind: "fixed", valueText: "500", minText: "x" })).toMatch(/numbers/);
  });
  it("allows a small percent like the backend does, and refuses amounts over the backend caps", () => {
    expect(draftError({ kind: "percent", valueText: "0.5", minText: "" })).toBeNull();
    expect(draftError({ kind: "percent", valueText: "100", minText: "" })).toBeNull();
    expect(draftError({ kind: "fixed", valueText: "10000000", minText: "" })).toBeNull();
    expect(draftError({ kind: "fixed", valueText: "10000001", minText: "" })).toMatch(/too large/);
    expect(draftError({ kind: "fixed", valueText: "500", minText: "10000000" })).toBeNull();
    expect(draftError({ kind: "fixed", valueText: "500", minText: "10000001" })).toMatch(/too large/);
  });
  it("a different kind is not the same rule", () => {
    expect(sameRule(pct(30), fixed(30))).toBe(false);
    expect(sameRule(pct(30), pct(31))).toBe(false);
  });
});

describe("customerPreview (the WhatsApp message, same as the AI's quote)", () => {
  it("shows the advance line and the advance link when an advance is asked", async () => {
    const { customerPreview } = await import("./advanceText");
    const text = customerPreview({ kind: "percent", value: 40, min_total_paise: 0 });
    expect(text).toContain("Advance to book: ₹4,200 (the rest, ₹6,300, later)");
    expect(text).toContain("Pay the advance here:");
  });
  it("asks the full amount when there is no advance", async () => {
    const { customerPreview } = await import("./advanceText");
    const text = customerPreview({ kind: "none", value: 0, min_total_paise: 0 });
    expect(text).not.toContain("Advance");
    expect(text).toContain("Pay here:");
  });
});
