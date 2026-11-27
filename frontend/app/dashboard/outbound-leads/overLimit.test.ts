import { describe, expect, it } from "vitest";
import { keepKnown, matchPeople, toggleAll, weekRangeLabel, type OverLimitPerson } from "./overLimit";

const person = (phone: string, name: string | null = null, this_week = 2): OverLimitPerson => ({ phone, name, this_week });

describe("weekRangeLabel", () => {
  it("writes Sunday to Saturday", () => {
    expect(weekRangeLabel("2026-11-15", "2026-11-21")).toBe("Sun 15 Nov – Sat 21 Nov");
  });
});

describe("matchPeople", () => {
  const people = [person("919876543210", "Ravi Kumar"), person("919811122233", "Priya"), person("918000000001", null)];

  it("returns everyone for an empty query", () => {
    expect(matchPeople(people, "  ")).toHaveLength(3);
  });
  it("matches names case-insensitively", () => {
    expect(matchPeople(people, "ravi").map((p) => p.phone)).toEqual(["919876543210"]);
  });
  it("matches digits inside the phone", () => {
    expect(matchPeople(people, "98765").map((p) => p.phone)).toEqual(["919876543210"]);
  });
  it("ignores spaces and plus in a phone query", () => {
    expect(matchPeople(people, "+91 98765 43210").map((p) => p.phone)).toEqual(["919876543210"]);
  });
  it("does not match a name query against phones of people without a name", () => {
    expect(matchPeople(people, "zzz")).toEqual([]);
  });
});

describe("toggleAll", () => {
  const shown = Array.from({ length: 300 }, (_, i) => person(`9190000${String(i).padStart(5, "0")}`));

  it("picks every person in the search result", () => {
    expect(toggleAll(new Set(), shown, true).size).toBe(300);
  });
  it("removes only those in the search result", () => {
    const picked = new Set(["outside", ...shown.map((p) => p.phone)]);
    const next = toggleAll(picked, shown, false);
    expect(Array.from(next)).toEqual(["outside"]);
  });
  it("does not change the set it was given", () => {
    const picked = new Set<string>();
    toggleAll(picked, shown, true);
    expect(picked.size).toBe(0);
  });
});

describe("keepKnown", () => {
  it("drops phones no longer listed", () => {
    const next = keepKnown(new Set(["a", "b"]), [person("a")]);
    expect(Array.from(next)).toEqual(["a"]);
  });
});
