import { describe, expect, it } from "vitest";
import { toggleGoal } from "./BrainOverview";

describe("goal picker", () => {
  it("adds in order, takes off, and keeps the first when a third is picked", () => {
    expect(toggleGoal([], "order")).toEqual(["order"]);
    expect(toggleGoal(["order"], "callback")).toEqual(["order", "callback"]);
    expect(toggleGoal(["order", "callback"], "visit")).toEqual(["order", "visit"]);
    expect(toggleGoal(["order", "callback"], "order")).toEqual(["callback"]);
  });
});
