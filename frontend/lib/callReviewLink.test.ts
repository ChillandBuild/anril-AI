import { describe, expect, it } from "vitest";
import { callIdFromParam, localDayOf } from "./callReviewLink";

describe("callIdFromParam", () => {
  it("accepts an id and trims it", () => {
    expect(callIdFromParam(" 3f2a1b9c-1111-4222-8333-444455556666 ")).toBe("3f2a1b9c-1111-4222-8333-444455556666");
  });
  it("rejects missing or odd values", () => {
    expect(callIdFromParam(null)).toBeNull();
    expect(callIdFromParam("")).toBeNull();
    expect(callIdFromParam("../etc")).toBeNull();
    expect(callIdFromParam("abc")).toBeNull();
  });
});

describe("localDayOf", () => {
  it("gives the local calendar day of a call", () => {
    const d = new Date(2026, 10, 23, 15, 30); // 23 Nov 2026, local time
    expect(localDayOf(d.toISOString())).toBe("2026-11-23");
  });
  it("is null for nothing or nonsense", () => {
    expect(localDayOf(null)).toBeNull();
    expect(localDayOf("not a date")).toBeNull();
  });
});
