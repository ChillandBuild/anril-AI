import { describe, expect, it } from "vitest";
import { formatDelay, isDayStep, splitDelay, toDelayHours } from "./reengagementDelay";

describe("follow-up delays", () => {
  it("labels hours and days", () => {
    expect(formatDelay(1)).toBe("1 hr");
    expect(formatDelay(2)).toBe("2 hrs");
    expect(formatDelay(23)).toBe("23 hrs");
    expect(formatDelay(24)).toBe("Day 1");
    expect(formatDelay(72)).toBe("Day 3");
    expect(formatDelay(36)).toBe("36 hrs");
    expect(formatDelay(720)).toBe("Day 30");
  });

  it("splits a stored delay for the editor", () => {
    expect(splitDelay(6)).toEqual({ value: 6, unit: "hours" });
    expect(splitDelay(48)).toEqual({ value: 2, unit: "days" });
    expect(splitDelay(36)).toEqual({ value: 36, unit: "hours" });
  });

  it("converts typed values to hours, max 30 days", () => {
    expect(toDelayHours(3, "days")).toBe(72);
    expect(toDelayHours(5, "hours")).toBe(5);
    expect(toDelayHours(30, "days")).toBe(720);
    expect(toDelayHours(31, "days")).toBeNull();
    expect(toDelayHours(721, "hours")).toBeNull();
    expect(toDelayHours(0, "hours")).toBeNull();
    expect(toDelayHours(1.5, "days")).toBeNull();
  });

  it("treats 24 hours and up as a template-only step", () => {
    expect(isDayStep(23)).toBe(false);
    expect(isDayStep(24)).toBe(true);
  });
});
