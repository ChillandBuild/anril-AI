import { describe, expect, it } from "vitest";
import { tomorrowAt } from "./quickTimes";

describe("tomorrowAt", () => {
  it("returns tomorrow at the hour, minutes zero", () => {
    const now = new Date(2026, 10, 25, 22, 30);
    expect(tomorrowAt(11, now)).toEqual(new Date(2026, 10, 26, 11, 0, 0, 0));
  });

  it("rolls over the month end", () => {
    const now = new Date(2026, 10, 30, 9, 0);
    expect(tomorrowAt(9, now)).toEqual(new Date(2026, 11, 1, 9, 0, 0, 0));
  });

  it("treats hour 14 as 2 PM", () => {
    const now = new Date(2026, 10, 25, 8, 15, 30, 500);
    expect(tomorrowAt(14, now)).toEqual(new Date(2026, 10, 26, 14, 0, 0, 0));
  });
});
