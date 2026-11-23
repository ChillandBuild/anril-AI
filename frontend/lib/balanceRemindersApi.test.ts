import { describe, expect, it } from "vitest";
import { remindersLine } from "./balanceRemindersApi";

describe("remindersLine", () => {
  it("says what on and off mean", () => {
    expect(remindersLine(true)).toMatch(/^On:/);
    expect(remindersLine(false)).toMatch(/^Off:/);
  });
});
