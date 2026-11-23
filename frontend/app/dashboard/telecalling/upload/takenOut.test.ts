import { describe, expect, it } from "vitest";
import { takenOutReasons, takenOutTotal } from "./takenOut";

describe("taken out", () => {
  it("older uploads have nothing recorded: no total, no reasons", () => {
    expect(takenOutTotal(null)).toBeNull();
    expect(takenOutTotal(undefined)).toBeNull();
    expect(takenOutReasons(null)).toBe("");
  });

  it("an upload that took nothing out shows 0, not a dash", () => {
    expect(takenOutTotal({})).toBe(0);
  });

  it("totals and lists reasons biggest first in plain words", () => {
    const counts = { said_stop: 1, bad_number: 3, duplicate: 3, mystery: 2 };
    expect(takenOutTotal(counts)).toBe(9);
    expect(takenOutReasons(counts)).toBe("3 bad number · 3 repeated in the file · 2 mystery · 1 said stop");
  });
});
