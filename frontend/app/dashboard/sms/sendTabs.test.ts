import { describe, expect, it } from "vitest";
import {
  hasCurlyQuotes,
  languageLine,
  matchSavedTemplate,
  planRate,
  popupCost,
  sendNameFor,
  sendersFrom,
  skipCounts,
  straightenQuotes,
} from "./helpers";

const T = (sender_id: string, message: string, id = message) => ({ id, sender_id, message });

describe("sendersFrom", () => {
  it("counts templates per sender, A to Z", () => {
    expect(sendersFrom([T("KELIR", "a"), T("ASTTML", "b"), T("KELIR", "c")])).toEqual([
      { sender_id: "ASTTML", count: 1 },
      { sender_id: "KELIR", count: 2 },
    ]);
  });
});

describe("matchSavedTemplate", () => {
  const saved = [T("KELIR", "Dear Parent, tomorrow's class is cancelled due to rain. -KELIR", "14894")];
  it("finds the same wording for the same sender, ignoring extra spaces", () => {
    expect(matchSavedTemplate(saved, "KELIR", "  Dear Parent,  tomorrow's class is cancelled due to rain. -KELIR ")?.id).toBe("14894");
  });
  it("ignores another sender's template and changed wording", () => {
    expect(matchSavedTemplate(saved, "ASTTML", saved[0].message)).toBeNull();
    expect(matchSavedTemplate(saved, "KELIR", "Dear Parent, tomorrow's Class is cancelled due to rain. -KELIR")).toBeNull();
    expect(matchSavedTemplate(saved, "KELIR", "")).toBeNull();
  });
});

describe("curly quotes", () => {
  it("spots and straightens them", () => {
    expect(hasCurlyQuotes("tomorrow’s")).toBe(true);
    expect(hasCurlyQuotes("tomorrow's")).toBe(false);
    expect(straightenQuotes("“Hi” it’s")).toBe("\"Hi\" it's");
  });
});

describe("languageLine", () => {
  it("names English, Tamil and other Unicode with the per-SMS size", () => {
    expect(languageLine("Hello")).toBe("English · 160 characters per SMS · this message = 1 SMS");
    expect(languageLine("வணக்கம்")).toBe("Unicode (Tamil) · 70 characters per SMS · this message = 1 SMS");
    expect(languageLine("Hi ’")).toMatch(/^Unicode · 70/);
    expect(languageLine("x".repeat(161))).toMatch(/= 2 SMS$/);
  });
});

describe("plan price and popup cost", () => {
  // KELIR on 2026-11-07: Bulk9 showed ₹64.3188 and 494 SMS at You Sell ₹0.1302.
  const kelir = { sms_count: 494, wallet: 64.3188 };
  it("is wallet ÷ SMS left, the Your plan figure", () => {
    expect(planRate(kelir)).toBeCloseTo(0.1302, 6);
    expect(planRate({ sms_count: 0, wallet: 10 })).toBeNull();
    expect(planRate({ sms_count: 10, wallet: null })).toBeNull();
    expect(planRate(null)).toBeNull();
  });
  it("shows credits, credits left and rupees", () => {
    expect(popupCost(496, kelir)).toEqual({ credits: 496, left: -2, rate: expect.closeTo(0.1302, 6), rupees: 64.58 });
    expect(popupCost(10, { sms_count: 100, wallet: null })).toEqual({ credits: 10, left: 90, rate: null, rupees: null });
    expect(popupCost(10, null).left).toBeNull();
  });
});

describe("skipCounts", () => {
  it("counts per reason and how many the capped list leaves out", () => {
    const ex = (reason: string) => ({ name: null, phone: null, reason });
    expect(skipCounts({ excluded: [ex("Duplicate number"), ex("Not an Indian mobile number"), ex("Duplicate number")], excluded_total: 5 })).toEqual({
      rows: [
        { reason: "Duplicate number", count: 2 },
        { reason: "Not an Indian mobile number", count: 1 },
      ],
      more: 2,
    });
  });
});

describe("sendNameFor", () => {
  it("names a send by sender, template and Indian date", () => {
    expect(sendNameFor("KELIR", "14893", new Date("2026-11-06T20:00:00Z"))).toBe("KELIR · 14893 · 7 Nov");
    expect(sendNameFor("", "x", new Date("2026-11-06T20:00:00Z"))).toMatch(/^SMS 7 Nov/);
  });
});
