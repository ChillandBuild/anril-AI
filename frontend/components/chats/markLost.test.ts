import { describe, expect, it } from "vitest";
import { blanks, lostReasonText } from "./MarkLostDialog";

describe("Mark Lost", () => {
  it("counts a template's blanks once each", () => {
    expect(blanks("Hi {{1}}, new flats under {{2}}. {{1}}")).toBe(2);
    expect(blanks("No blanks here")).toBe(0);
    expect(blanks(null)).toBe(0);
  });

  it("saves the chip with the note, within 120 characters", () => {
    expect(lostReasonText("Budget too high", "wants ground floor")).toBe("Budget too high · wants ground floor");
    expect(lostReasonText("Just checking", "")).toBe("Just checking");
    expect(lostReasonText("Other", "x".repeat(200)).length).toBe(120);
  });
});
