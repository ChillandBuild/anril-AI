import { describe, expect, it } from "vitest";
import { dripTimeProblem, scheduleProblem } from "./reachSchedule";

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
