import { describe, expect, it } from "vitest";
import { keptDetail, keptHeadline } from "./keptOnTime";

describe("kept on time", () => {
  it("shows a dash until a scheduled call has fallen due", () => {
    const none = { kept: 0, due: 0, percent: null, days: 30 };
    expect(keptHeadline(none)).toBe("—");
    expect(keptHeadline(null)).toBe("—");
    expect(keptDetail(none)).toContain("No scheduled calls");
  });

  it("shows the percent and the plain count", () => {
    const s = { kept: 3, due: 4, percent: 75, days: 30 };
    expect(keptHeadline(s)).toBe("75%");
    expect(keptDetail(s)).toBe("3 of 4 scheduled calls were made within 15 minutes of their time (last 30 days).");
  });

  it("0% is a real figure, not a dash", () => {
    expect(keptHeadline({ kept: 0, due: 2, percent: 0, days: 30 })).toBe("0%");
  });
});
