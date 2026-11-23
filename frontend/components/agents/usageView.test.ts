import { describe, expect, it } from "vitest";
import { byCharacter, cycleBars, meter, rupees, shortDate } from "./usageView";

describe("meter", () => {
  it("shows the share used, amber near the limit and red over it", () => {
    expect(meter(3420, 10000)).toEqual({ pct: 34, bar: 34, tone: "ok" });
    expect(meter(8500, 10000)).toEqual({ pct: 85, bar: 85, tone: "near" });
    expect(meter(10000, 10000)).toEqual({ pct: 100, bar: 100, tone: "near" });
    expect(meter(10420, 10000)).toEqual({ pct: 104, bar: 100, tone: "over" });
  });
  it("has no meter without a plan", () => {
    expect(meter(12, 0)).toBeNull();
  });
});

describe("cycleBars", () => {
  const today = new Date("2026-11-23T15:00:00Z");
  it("has a bar for every day of the cycle so far, missing days as 0", () => {
    const bars = cycleBars(
      { period_start: "2026-11-20", period_end: "2026-12-20", daily: [{ date: "2026-11-22", count: 4, by_companion: {} }] },
      today,
    );
    expect(bars).toEqual([
      { date: "2026-11-20", count: 0 },
      { date: "2026-11-21", count: 0 },
      { date: "2026-11-22", count: 4 },
      { date: "2026-11-23", count: 0 },
    ]);
  });
  it("stops the day before the cycle renews", () => {
    const bars = cycleBars({ period_start: "2026-10-20", period_end: "2026-10-22", daily: [] }, today);
    expect(bars.map((b) => b.date)).toEqual(["2026-10-20", "2026-10-21"]);
  });
});

describe("byCharacter", () => {
  it("adds up each character over the cycle, most first, and names deleted ones", () => {
    expect(
      byCharacter({
        companions: { c1: "Jothidar AI", c2: "Vastu Guru" },
        daily: [
          { date: "2026-11-22", count: 3, by_companion: { c1: 2, c2: 1 } },
          { date: "2026-11-23", count: 4, by_companion: { c1: 3, unknown: 1 } },
        ],
      }),
    ).toEqual([
      { name: "Jothidar AI", count: 5 },
      { name: "Vastu Guru", count: 1 },
      { name: "Deleted character", count: 1 },
    ]);
  });
});

describe("formatting", () => {
  it("writes rupees and short dates", () => {
    expect(rupees(3000)).toBe("₹3,000");
    expect(rupees(2999.5)).toBe("₹2,999.5");
    expect(shortDate("2026-11-05")).toBe("5 Nov");
  });
});
