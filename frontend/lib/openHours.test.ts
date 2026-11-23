import { describe, expect, it } from "vitest";
import { openDaysFrom, openDaysToHours, openHoursProblem } from "./replySettingsApi";

describe("open hours editor (v9.2 #59)", () => {
  it("starts a new shop on Mon–Sat 10 to 8, Sunday closed", () => {
    const days = openDaysFrom({ set: false, hours: {} });
    expect(days.map((d) => d.on)).toEqual([true, true, true, true, true, true, false]);
    expect(openDaysToHours(days)).toEqual(Object.fromEntries([0, 1, 2, 3, 4, 5].map((d) => [String(d), [["10:00", "20:00"]]])));
  });

  it("reads saved hours and keeps an untouched lunch break", () => {
    const saved = { "0": [["10:00", "13:00"], ["16:00", "24:00"]] as [string, string][], "2": [["09:00", "18:00"]] as [string, string][] };
    const days = openDaysFrom({ set: true, hours: saved });
    expect(days[0]).toEqual({ on: true, open: "10:00", close: "23:59" });
    expect(days[1].on).toBe(false);
    expect(openDaysToHours(days, saved)["0"]).toEqual(saved["0"]);
    days[0] = { ...days[0], close: "20:00" };
    expect(openDaysToHours(days, saved)["0"]).toEqual([["10:00", "20:00"]]);
  });

  it("says what is wrong in plain words", () => {
    const days = openDaysFrom({ set: false, hours: {} });
    expect(openHoursProblem(days)).toBeNull();
    expect(openHoursProblem(days.map((d) => ({ ...d, on: false })))).toMatch(/at least one day/);
    expect(openHoursProblem(days.map((d, i) => (i === 2 ? { ...d, close: "09:00" } : d)))).toBe("Wed: closing time must be after opening time.");
  });
});
