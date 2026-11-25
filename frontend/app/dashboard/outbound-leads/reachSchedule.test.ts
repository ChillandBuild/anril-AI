import { describe, expect, it } from "vitest";
import { dripTimeProblem, scheduleChoices, scheduleProblem } from "./reachSchedule";

describe("Reach schedule hours", () => {
  it("accepts 9 AM to 8:59 PM India time and refuses the night", () => {
    // Explicit +05:30 so the result does not depend on the machine's zone.
    const ist = (hhmm: string) => new Date(`2026-11-25T${hhmm}:00+05:30`);
    const local = (hhmm: string) => {
      const d = ist(hhmm);
      const p = (n: number) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
    };
    expect(scheduleProblem(local("09:00"))).toBeNull();
    expect(scheduleProblem(local("20:59"))).toBeNull();
    expect(scheduleProblem(local("21:00"))).toMatch(/9 AM to 9 PM/);
    expect(scheduleProblem(local("08:59"))).toMatch(/9 AM to 9 PM/);
    expect(scheduleProblem(local("00:30"))).toMatch(/9 AM to 9 PM/);
  });
  it("says nothing for an empty or unreadable value", () => {
    expect(scheduleProblem("")).toBeNull();
    expect(scheduleProblem("garbage")).toBeNull();
    expect(dripTimeProblem("")).toBeNull();
  });
  it("judges a drip daily time as India time directly", () => {
    expect(dripTimeProblem("09:00")).toBeNull();
    expect(dripTimeProblem("20:59")).toBeNull();
    expect(dripTimeProblem("21:00")).not.toBeNull();
    expect(dripTimeProblem("07:15")).not.toBeNull();
  });
});

describe("time left while sending", () => {
  it("guesses from the pace so far, and waits until there is enough to go on", async () => {
    const { timeLeftText } = await import("./reachSchedule");
    expect(timeLeftText(312, 772, 3 * 60_000)).toBe("about 4 minutes left");
    expect(timeLeftText(2, 772, 10_000)).toBeNull();
    expect(timeLeftText(770, 772, 600_000)).toBe("less than a minute left");
  });
});

describe("one-tap schedule choices", () => {
  const pad = (n: number) => String(n).padStart(2, "0");
  const at = (day: number, hour: number) => `2026-11-${pad(day)}T${pad(hour)}:00`;
  it("offers all three in the morning", () => {
    const c = scheduleChoices(new Date(2026, 10, 25, 10, 0));
    expect(c.map((x) => x.label)).toEqual(["Today 6 PM", "Tomorrow 10 AM", "Tomorrow 6 PM"]);
    expect(c.map((x) => x.value)).toEqual([at(25, 18), at(26, 10), at(26, 18)]);
    c.forEach((x) => expect(scheduleProblem(x.value)).toBeNull());
  });
  it("drops Today 6 PM once it has passed", () => {
    const c = scheduleChoices(new Date(2026, 10, 25, 19, 0));
    expect(c.map((x) => x.label)).toEqual(["Tomorrow 10 AM", "Tomorrow 6 PM"]);
    expect(c.map((x) => x.value)).toEqual([at(26, 10), at(26, 18)]);
  });
  it("each value parses back to the local date-time", () => {
    const [first] = scheduleChoices(new Date(2026, 10, 25, 10, 0));
    const d = new Date(first.value);
    expect([d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), d.getMinutes()]).toEqual([2026, 10, 25, 18, 0]);
  });
});
