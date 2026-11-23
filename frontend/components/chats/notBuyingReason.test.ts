import { describe, expect, it } from "vitest";
import { cleanOtherReason, OTHER_REASON_MAX } from "./notBuyingReason";

describe("Other… not-buying reason", () => {
  it("trims and collapses spaces and line breaks", () => {
    expect(cleanOtherReason("  Wants   a cheaper\n option ")).toBe("Wants a cheaper option");
  });

  it("is empty when nothing real was typed, so Save stays off", () => {
    expect(cleanOtherReason("   \n ")).toBe("");
  });

  it("cuts at the same length the server does", () => {
    expect(cleanOtherReason("x".repeat(500))).toHaveLength(OTHER_REASON_MAX);
    expect(OTHER_REASON_MAX).toBe(120);
  });
});
