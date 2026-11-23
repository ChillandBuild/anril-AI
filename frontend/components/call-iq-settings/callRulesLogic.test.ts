import { describe, expect, it } from "vitest";
import type { CallRules, RulesPerson } from "@/lib/callRulesApi";
import { clockWords, dayLabel, leaveLine, leaveResultLine, rulesProblem, sameRules, wholeNumber } from "./callRulesLogic";

const rules: CallRules = {
  calling_hours_on: true,
  calling_start: "09:00",
  calling_end: "21:00",
  daily_limit_on: false,
  daily_limit: 100,
  break_limit_minutes: 30,
  hide_numbers_for_callers: false,
};

const person = (p: Partial<RulesPerson>): RulesPerson => ({
  id: "1", name: "Asha", status: "active", calling_mode: "business_default", effective_mode: "cloud",
  leave_from: null, leave_to: null, leave_reason: null, on_leave: false, ...p,
});

describe("clockWords", () => {
  it("speaks plain times", () => {
    expect(clockWords("09:00")).toBe("9 AM");
    expect(clockWords("21:30")).toBe("9:30 PM");
    expect(clockWords("00:00")).toBe("12 AM");
    expect(clockWords("12:00")).toBe("12 PM");
    expect(clockWords("nonsense")).toBe("nonsense");
  });
});

describe("rulesProblem", () => {
  it("accepts the defaults", () => expect(rulesProblem(rules)).toBeNull());
  it("refuses hours that end before they start, only when hours are on", () => {
    expect(rulesProblem({ ...rules, calling_end: "08:00" })).toMatch(/end after/);
    expect(rulesProblem({ ...rules, calling_end: "08:00", calling_hours_on: false })).toBeNull();
  });
  it("checks the two numbers", () => {
    expect(rulesProblem({ ...rules, daily_limit: 0 })).toMatch(/daily limit/);
    expect(rulesProblem({ ...rules, daily_limit: 5000 })).toMatch(/daily limit/);
    expect(rulesProblem({ ...rules, break_limit_minutes: 0 })).toBeNull();
    expect(rulesProblem({ ...rules, break_limit_minutes: 999 })).toMatch(/break limit/);
  });
});

describe("small helpers", () => {
  it("compares rules", () => {
    expect(sameRules(rules, { ...rules })).toBe(true);
    expect(sameRules(rules, { ...rules, daily_limit: 99 })).toBe(false);
  });
  it("reads whole numbers", () => {
    expect(wholeNumber("1,00")).toBe(100);
    expect(wholeNumber("")).toBeNull();
    expect(wholeNumber("abc")).toBeNull();
  });
  it("labels days without time zone shifts", () => {
    expect(dayLabel("2026-12-05")).toBe("5 Dec 2026");
    expect(dayLabel(null)).toBe("");
  });
});

describe("leave words", () => {
  it("describes planned and current leave", () => {
    expect(leaveLine(person({}))).toBeNull();
    expect(leaveLine(person({ leave_from: "2026-12-01", leave_to: "2026-12-03", leave_reason: "wedding" }))).toBe("Leave planned: 1 Dec 2026 to 3 Dec 2026 (wedding)");
    expect(leaveLine(person({ leave_from: "2026-12-01", leave_to: "2026-12-01", on_leave: true }))).toBe("On leave: 1 Dec 2026");
  });
  it("tells what moved", () => {
    const base = { moved: 0, to: [], no_one_free: false, starts_later: false };
    expect(leaveResultLine("Asha", { ...base, starts_later: true })).toMatch(/first day/);
    expect(leaveResultLine("Asha", { ...base, no_one_free: true })).toMatch(/no other telecaller/);
    expect(leaveResultLine("Asha", base)).toMatch(/no open leads/);
    expect(leaveResultLine("Asha", { ...base, moved: 5, to: [{ name: "Bala", count: 3 }, { name: "Dev", count: 2 }] })).toBe(
      "Leave saved. 5 open leads were given to: Bala 3, Dev 2.",
    );
  });
});
