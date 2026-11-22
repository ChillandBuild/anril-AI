import { describe, expect, it } from "vitest";
import type { MetaCharges } from "@/lib/connectionsApi";
import { barTone, barWidth, dailyLimitText, formatCount, formatMoney, inShort } from "./chargesText";

const charges = (cost: number, currency = "INR"): MetaCharges => ({
  available: true,
  month: "2026-11",
  currency,
  rows: [],
  total: { messages: 10, cost },
  gst_note: "+ GST",
});

describe("formatMoney", () => {
  it("groups the Indian way", () => {
    expect(formatMoney(200000, "INR")).toBe("₹2,00,000");
    expect(formatMoney(2140, "INR")).toBe("₹2,140");
  });
  it("shows paise only when there are some", () => {
    expect(formatMoney(2140.5, "INR")).toBe("₹2,140.50");
    expect(formatMoney(0, "INR")).toBe("₹0");
  });
  it("can round to whole rupees", () => {
    expect(formatMoney(2139.6, "INR", true)).toBe("₹2,140");
  });
  it("names other currencies by code", () => {
    expect(formatMoney(12.5, "USD")).toBe("USD 12.50");
  });
});

describe("formatCount", () => {
  it("uses Indian grouping", () => expect(formatCount(1234567)).toBe("12,34,567"));
});

describe("bar", () => {
  it("clamps the width", () => {
    expect(barWidth(76)).toBe(76);
    expect(barWidth(140)).toBe(100);
    expect(barWidth(-5)).toBe(0);
    expect(barWidth(null)).toBe(0);
  });
  it("warns at 80 and is full at 100", () => {
    expect(barTone(79)).toBe("ok");
    expect(barTone(80)).toBe("warn");
    expect(barTone(100)).toBe("full");
    expect(barTone(null)).toBe("ok");
  });
});

describe("inShort", () => {
  it("joins the charge and the AI use", () => {
    expect(inShort(charges(2140), { used: 760, included: 1000, pct: 76 })).toBe(
      "Meta charged ₹2,140 this month. You have used 76% of your AI replies.",
    );
  });
  it("says Meta hasn't shared when it hasn't", () => {
    expect(inShort({ available: false, reason: "x" }, { used: 1, included: null, pct: null })).toBe(
      "Meta hasn't shared this month's charges yet. You have used 1 AI reply this month.",
    );
  });
  it("counts replies when the plan has no allowance", () => {
    expect(inShort(charges(0), { used: 1200, included: null, pct: null })).toBe(
      "Meta charged ₹0 this month. You have used 1,200 AI replies this month.",
    );
  });
});

describe("dailyLimitText", () => {
  it("shows the number", () => expect(dailyLimitText(10000)).toBe("Up to 10,000 different customers a day"));
  it("says so when unknown", () => expect(dailyLimitText(null)).toBe("Meta hasn't told us your limit yet."));
});
