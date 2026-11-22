import { describe, expect, it } from "vitest";
import { NO_REACH_OFFER, reachOfferPayload, reachOfferProblem } from "./ReachOfferBox";

describe("Reach offer box", () => {
  it("sends nothing when unticked, exactly like today's flow", () => {
    expect(reachOfferPayload(NO_REACH_OFFER)).toBeUndefined();
    expect(reachOfferPayload({ on: false, title: "Sale", endsOn: "2026-12-01" })).toBeUndefined();
    expect(reachOfferProblem({ on: false, title: "", endsOn: "" })).toBeNull();
  });
  it("sends the name and end date when ticked", () => {
    expect(reachOfferPayload({ on: true, title: " Diwali sale ", endsOn: "2026-12-01" })).toEqual({ title: "Diwali sale", ends_on: "2026-12-01" });
  });
  it("blocks a ticked offer with no name or no end date", () => {
    expect(reachOfferProblem({ on: true, title: "", endsOn: "2026-12-01" })).toMatch(/Name the offer/);
    expect(reachOfferProblem({ on: true, title: "Sale", endsOn: "" })).toMatch(/end/);
    expect(reachOfferProblem({ on: true, title: "Sale", endsOn: "2026-12-01" })).toBeNull();
  });
});
