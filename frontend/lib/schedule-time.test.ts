import { describe, expect, it } from "vitest";
import {
  MAX_AHEAD_MS,
  MIN_AHEAD_MS,
  checkSendAt,
  clockOf,
  dateBounds,
  defaultWhen,
  formatSendTime,
  fromIstInputs,
  quickSlots,
  resolveWhen,
  toIstInputs,
  untilSend,
} from "./schedule-time";

// Wednesday 28 Oct 2026, 4:00 PM IST
const NOW = new Date("2026-10-28T10:30:00Z");
const ist = (date: string, time: string) => fromIstInputs(date, time) as Date;

describe("quickSlots", () => {
  it("offers an hour from now, tomorrow 10 AM and the next Monday 10 AM, all in IST", () => {
    const slots = quickSlots(NOW);
    expect(slots.map((s) => s.label)).toEqual(["In 1 hour", "Tomorrow", "Monday"]);
    expect(toIstInputs(slots[0].at)).toEqual({ date: "2026-10-28", time: "17:00" });
    expect(toIstInputs(slots[1].at)).toEqual({ date: "2026-10-29", time: "10:00" });
    expect(toIstInputs(slots[2].at)).toEqual({ date: "2026-11-02", time: "10:00" });
  });

  it("rounds the hour up to the next five minutes", () => {
    const slots = quickSlots(new Date("2026-10-28T10:32:10Z"));
    expect(toIstInputs(slots[0].at).time).toBe("17:05");
  });

  it("drops Monday when tomorrow already is Monday", () => {
    const sunday = new Date("2026-11-01T10:30:00Z");
    expect(quickSlots(sunday).map((s) => s.label)).toEqual(["In 1 hour", "Tomorrow"]);
  });

  it("uses the IST date even when the UTC date is still the day before", () => {
    // 1:00 AM IST on Thursday 29 Oct is still Wednesday 28 Oct in UTC.
    const lateNight = new Date("2026-10-28T19:30:00Z");
    expect(toIstInputs(quickSlots(lateNight)[1].at).date).toBe("2026-10-30");
  });
});

describe("checkSendAt", () => {
  it("accepts exactly five minutes ahead and exactly thirty days ahead", () => {
    expect(checkSendAt(new Date(NOW.getTime() + MIN_AHEAD_MS), NOW)).toBe("");
    expect(checkSendAt(new Date(NOW.getTime() + MAX_AHEAD_MS), NOW)).toBe("");
  });

  it("refuses sooner, past and later times, and a missing one, in plain words", () => {
    expect(checkSendAt(new Date(NOW.getTime() + MIN_AHEAD_MS - 1000), NOW)).toBe("Pick a time at least 5 minutes from now.");
    expect(checkSendAt(new Date(NOW.getTime() - 3_600_000), NOW)).toBe("Pick a time at least 5 minutes from now.");
    expect(checkSendAt(new Date(NOW.getTime() + MAX_AHEAD_MS + 1000), NOW)).toBe("Scheduling goes up to 30 days ahead.");
    expect(checkSendAt(null, NOW)).toBe("Pick a date and time.");
  });
});

describe("resolveWhen", () => {
  it("sending now has no time and no error, whatever the inputs hold", () => {
    expect(resolveWhen({ mode: "now", date: "", time: "" }, NOW)).toEqual({ mode: "now", at: null, error: "" });
  });

  it("reads the inputs as IST", () => {
    const r = resolveWhen({ mode: "later", date: "2026-10-29", time: "10:00" }, NOW);
    expect(r.error).toBe("");
    expect(r.at?.toISOString()).toBe("2026-10-29T04:30:00.000Z");
  });

  it("flags empty or bad inputs", () => {
    expect(resolveWhen({ mode: "later", date: "", time: "10:00" }, NOW)).toMatchObject({ at: null, error: "Pick a date and time." });
    expect(resolveWhen({ mode: "later", date: "2026-10-28", time: "16:02" }, NOW).error).toBe("Pick a time at least 5 minutes from now.");
  });

  it("starts as tomorrow 10 AM", () => {
    const start = defaultWhen(NOW);
    expect(start).toEqual({ mode: "later", date: "2026-10-29", time: "10:00" });
    expect(resolveWhen(start, NOW).error).toBe("");
  });
});

describe("date bounds", () => {
  it("run from today to thirty days ahead, in IST", () => {
    expect(dateBounds(NOW)).toEqual({ min: "2026-10-28", max: "2026-11-27" });
  });
});

describe("display", () => {
  it("writes the full date and an upper-case clock", () => {
    const at = ist("2026-10-29", "10:00");
    expect(formatSendTime(at)).toBe("Thu 29 Oct, 10:00 AM");
    expect(clockOf(ist("2026-10-29", "16:05"))).toBe("4:05 PM");
  });

  it("says how long until it goes", () => {
    expect(untilSend(new Date(NOW.getTime() + 20 * 60_000), NOW)).toBe("in 20 min");
    expect(untilSend(new Date(NOW.getTime() + 11 * 3_600_000), NOW)).toBe("in 11 h");
    expect(untilSend(new Date(NOW.getTime() + 5 * 86_400_000), NOW)).toBe("in 5 days");
  });
});
