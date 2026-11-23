import { describe, expect, it } from "vitest";
import { feedbackRowTarget } from "./feedbackHighlight";

const row = (id: string) => ({ id, lead_id: null, name: null, phone: null, stars: 2, reason: null, staff_name: null, asked_at: null });
const report = { unhappy_open: [row("a"), row("b")], recent: [row("b"), row("c")] };

describe("feedbackRowTarget", () => {
  it("prefers the unhappy list", () => expect(feedbackRowTarget(report, "b")).toBe("fb-b"));
  it("falls back to recent", () => expect(feedbackRowTarget(report, "c")).toBe("fb-recent-c"));
  it("returns null when the row is not there", () => expect(feedbackRowTarget(report, "zzz")).toBeNull());
  it("returns null with no fb", () => {
    expect(feedbackRowTarget(report, null)).toBeNull();
    expect(feedbackRowTarget(report, "  ")).toBeNull();
  });
});
