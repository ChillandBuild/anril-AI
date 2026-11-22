import { describe, expect, it } from "vitest";
import {
  buildBody,
  costCoverageLine,
  draftError,
  draftFromSaved,
  editableMonths,
  effectiveTarget,
  monthLabel,
  paiseToText,
  percentOf,
  prettyRupeesText,
  rupeesTextToPaise,
  sameBody,
  suggestionLine,
  type TargetSaved,
} from "./targetLogic";

const NOW = "2026-11";
const empty: TargetSaved = { monthly_paise: null, months: {}, show_team: false };

describe("months", () => {
  it("lists this month and the next three, across the year end", () => {
    expect(editableMonths("2026-11")).toEqual(["2026-11", "2026-12", "2027-01", "2027-02"]);
    expect(editableMonths("2026-01")).toEqual(["2026-01", "2026-02", "2026-03", "2026-04"]);
    expect(editableMonths("nonsense")).toEqual([]);
  });
  it("names a month", () => {
    expect(monthLabel("2026-12")).toBe("December 2026");
    expect(monthLabel("bad")).toBe("bad");
  });
});

describe("rupees text <-> paise", () => {
  it("parses typed money", () => {
    expect(rupeesTextToPaise("2,00,000")).toBe(20_000_000);
    expect(rupeesTextToPaise("₹ 1500.50")).toBe(150_050);
    expect(rupeesTextToPaise("  ")).toBeNull();
    expect(rupeesTextToPaise("abc")).toBe("bad");
    expect(rupeesTextToPaise("99999999999")).toBe("bad");
  });
  it("shows paise as a plain number and as Indian commas", () => {
    expect(paiseToText(20_000_000)).toBe("200000");
    expect(paiseToText(null)).toBe("");
    expect(prettyRupeesText("200000")).toBe("2,00,000");
    expect(prettyRupeesText("abc")).toBe("abc");
  });
});

describe("percentOf and effectiveTarget", () => {
  it("rounds to a whole percent and can pass 100", () => {
    expect(percentOf(18_600_000, 20_000_000)).toBe(93);
    expect(percentOf(30_000_000, 20_000_000)).toBe(150);
    expect(percentOf(100, null)).toBeNull();
    expect(percentOf(100, 0)).toBeNull();
  });
  it("a month's own number beats the every-month one", () => {
    const body = { monthly_paise: 100, months: { "2026-11": 250 } };
    expect(effectiveTarget(body, "2026-11")).toBe(250);
    expect(effectiveTarget(body, "2026-12")).toBe(100);
    expect(effectiveTarget({ monthly_paise: null, months: {} }, "2026-12")).toBeNull();
  });
});

describe("draft and body", () => {
  it("starts in 'different' mode only when an editable month has its own number", () => {
    expect(draftFromSaved(empty, NOW).mode).toBe("same");
    expect(draftFromSaved({ ...empty, months: { "2026-12": 5 } }, NOW).mode).toBe("different");
    expect(draftFromSaved({ ...empty, months: { "2025-01": 5 } }, NOW).mode).toBe("same");
  });
  it("'same every month' saves no overrides in the window but keeps later months", () => {
    const saved: TargetSaved = { monthly_paise: 100, months: { "2026-12": 9, "2027-09": 7 }, show_team: false };
    const draft = { ...draftFromSaved(saved, NOW), mode: "same" as const };
    expect(buildBody(draft, saved, NOW).months).toEqual({ "2027-09": 7 });
  });
  it("drops months before this month, so old overrides never pile up past the backend's 24", () => {
    const old = Object.fromEntries(Array.from({ length: 30 }, (_, i) => [`${2000 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}`, 1]));
    const saved: TargetSaved = { monthly_paise: 100, months: { ...old, "2026-10": 4, "2026-11": 5, "2027-09": 7 }, show_team: false };
    const body = buildBody({ ...draftFromSaved(saved, NOW), mode: "different" as const }, saved, NOW);
    expect(Object.keys(body.months).sort()).toEqual(["2026-11", "2027-09"]);
    expect(Object.keys(body.months).length).toBeLessThanOrEqual(24);
  });
  it("'different' saves typed months and leaves empty ones on the every-month target", () => {
    const draft = {
      monthlyText: "1,00,000", mode: "different" as const, showTeam: true,
      monthTexts: { "2026-11": "", "2026-12": "2,50,000", "2027-01": "", "2027-02": "" },
    };
    expect(buildBody(draft, empty, NOW)).toEqual({ monthly_paise: 10_000_000, months: { "2026-12": 25_000_000 }, show_team: true });
  });
  it("an empty target saves null", () => {
    expect(buildBody({ ...draftFromSaved(empty, NOW) }, empty, NOW).monthly_paise).toBeNull();
  });
  it("sameBody ignores key order and notices every change", () => {
    const a = { monthly_paise: 1, months: { a: 1, b: 2 }, show_team: false };
    expect(sameBody(a, { monthly_paise: 1, months: { b: 2, a: 1 }, show_team: false })).toBe(true);
    expect(sameBody(a, { ...a, show_team: true })).toBe(false);
    expect(sameBody(a, { ...a, months: { a: 1 } })).toBe(false);
    expect(sameBody(a, { ...a, monthly_paise: 2 })).toBe(false);
  });
  it("explains a bad amount", () => {
    expect(draftError({ ...draftFromSaved(empty, NOW), monthlyText: "abc" }, NOW)).toMatch(/number of rupees/);
    const diff = { ...draftFromSaved(empty, NOW), mode: "different" as const, monthTexts: { "2026-12": "zz" } };
    expect(draftError(diff, NOW)).toMatch(/December 2026/);
    expect(draftError(draftFromSaved(empty, NOW), NOW)).toBeNull();
  });
});

describe("lines", () => {
  it("suggestion line says where the number comes from", () => {
    expect(suggestionLine(20_500_000, 3)).toBe("Suggested: ₹2,05,000. That is the average of your last 3 months with sales, plus 10%.");
    expect(suggestionLine(19_000_000, 2)).toBe("Suggested: ₹1,90,000. That is the average of your last 2 months with sales, plus 10%.");
    expect(suggestionLine(11_000_000, 1)).toBe("Suggested: ₹1,10,000. That is your last month with sales, plus 10%.");
    expect(suggestionLine(null, 0)).toBeNull();
  });
  it("cost coverage", () => {
    expect(costCoverageLine({ with_cost: 1, total: 7 })).toBe("Items with a cost price: 1 of 7");
    expect(costCoverageLine(null)).toBeNull();
  });
});
