import { describe, expect, it } from "vitest";
import type { AdvanceOptions } from "@/lib/myBusinessApi";
import { optionsChanged, remindersChanged } from "./paymentsDraft";

const o = (a: boolean, b: boolean): AdvanceOptions => ({ staff_can_change: a, ai_pay_full: b });

describe("optionsChanged", () => {
  it("compares both switches", () => {
    expect(optionsChanged(o(true, false), o(true, false))).toBe(false);
    expect(optionsChanged(o(true, false), o(false, false))).toBe(true);
    expect(optionsChanged(o(true, false), o(true, true))).toBe(true);
  });
  it("ignores a missing side", () => {
    expect(optionsChanged(null, o(true, true))).toBe(false);
    expect(optionsChanged(o(true, true), null)).toBe(false);
  });
});

describe("remindersChanged", () => {
  it("is true only when both are known and differ", () => {
    expect(remindersChanged(true, false)).toBe(true);
    expect(remindersChanged(true, true)).toBe(false);
    expect(remindersChanged(null, true)).toBe(false);
  });
});
