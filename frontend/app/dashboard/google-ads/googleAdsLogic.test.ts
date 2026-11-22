import { describe, expect, it } from "vitest";
import {
  countCell, currentMonthIst, formatRupees, isMonth, monthLabel, paidCell, parseWholeNumber, rupeesToPaise, shiftMonth,
} from "./googleAdsLogic";

describe("months", () => {
  it("uses the Indian month near midnight", () => {
    // 31 Oct 20:00 UTC is already 1 Nov in India
    expect(currentMonthIst(new Date("2026-10-31T20:00:00Z"))).toBe("2026-11");
    expect(currentMonthIst(new Date("2026-10-31T10:00:00Z"))).toBe("2026-10");
  });
  it("steps across years", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
  });
  it("labels and validates", () => {
    expect(monthLabel("2026-11")).toBe("November 2026");
    expect(isMonth("2026-13")).toBe(false);
    expect(isMonth("2026-11")).toBe(true);
    expect(isMonth(null)).toBe(false);
  });
});

describe("money", () => {
  it("formats rupees with Indian grouping", () => {
    expect(formatRupees(12345600)).toBe("₹1,23,456");
    expect(formatRupees(null)).toBe("—");
    expect(formatRupees(0)).toBe("₹0");
  });
  it("reads what people type", () => {
    expect(rupeesToPaise("₹1,234.50")).toBe(123450);
    expect(rupeesToPaise("1200")).toBe(120000);
    expect(rupeesToPaise("Rs. 99")).toBe(9900);
    expect(rupeesToPaise("")).toBeNull();
    expect(rupeesToPaise("abc")).toBeNull();
    expect(rupeesToPaise("-5")).toBeNull();
    expect(rupeesToPaise("1.234")).toBeNull();
  });
  it("reads whole numbers", () => {
    expect(parseWholeNumber("1,234")).toBe(1234);
    expect(parseWholeNumber("12.5")).toBeNull();
    expect(parseWholeNumber("")).toBeNull();
  });
});

describe("cells", () => {
  it("hides rupees when money is not sent", () => {
    expect(paidCell(3, undefined)).toBe("3");
    expect(paidCell(3, 150000)).toBe("3 · ₹1,500");
    expect(paidCell(0, 0)).toBe("0");
  });
  it("shows a dash for unknown counts", () => {
    expect(countCell(null)).toBe("—");
    expect(countCell(1500)).toBe("1,500");
  });
});
