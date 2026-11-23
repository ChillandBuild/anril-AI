import { describe, expect, it } from "vitest";
import { isNumberEntry, worthLooking } from "./dialLookup";

describe("dial lookup entry", () => {
  it("treats digits, plus, dash and spaces as a number and anything with a letter as a name", () => {
    expect(isNumberEntry("+91 98765-43210")).toBe(true);
    expect(isNumberEntry("98765*")).toBe(true);
    expect(isNumberEntry("Priya")).toBe(false);
    expect(isNumberEntry("Priya 98")).toBe(false);
  });
  it("waits for 3 digits or 2 letters before asking the server", () => {
    expect(worthLooking("")).toBe(false);
    expect(worthLooking("98")).toBe(false);
    expect(worthLooking("987")).toBe(true);
    expect(worthLooking("+9 8")).toBe(false);
    expect(worthLooking("p")).toBe(false);
    expect(worthLooking("pr")).toBe(true);
  });
});
