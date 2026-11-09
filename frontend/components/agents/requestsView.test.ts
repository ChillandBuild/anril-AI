import { describe, expect, it } from "vitest";
import { barMax, dailyBars, errorRate } from "./requestsView";

describe("dailyBars", () => {
  it("fills empty days, oldest first", () => {
    const bars = dailyBars([{ date: "2026-11-08", ok: 2, error: 1 }], 3, new Date("2026-11-09T10:00:00Z"));
    expect(bars).toEqual([
      { date: "2026-11-07", ok: 0, error: 0 },
      { date: "2026-11-08", ok: 2, error: 1 },
      { date: "2026-11-09", ok: 0, error: 0 },
    ]);
  });
  it("crosses month ends", () => {
    expect(dailyBars([], 2, new Date("2026-12-01T00:30:00Z")).map((b) => b.date)).toEqual(["2026-11-30", "2026-12-01"]);
  });
});

describe("barMax and errorRate", () => {
  it("never divides by zero", () => {
    expect(barMax([])).toBe(1);
    expect(barMax([{ ok: 2, error: 1 }, { ok: 1, error: 0 }])).toBe(3);
    expect(errorRate(0, 0)).toBe("0%");
    expect(errorRate(3, 120)).toBe("3%");
  });
});
