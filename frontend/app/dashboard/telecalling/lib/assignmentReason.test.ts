import { describe, expect, it } from "vitest";
import { assignmentReasonLabel } from "./assignmentReason";

describe("assignmentReasonLabel", () => {
  it("names the person who was on leave", () => {
    expect(assignmentReasonLabel("moved_for_leave", "Ravi")).toBe("Moved: Ravi on leave");
  });
  it("still reads well when the name is missing", () => {
    expect(assignmentReasonLabel("moved_for_leave", null)).toBe("Moved: on leave");
    expect(assignmentReasonLabel("moved_for_leave", "  ")).toBe("Moved: on leave");
  });
  it("keeps the old labels and shows unknown reasons as they are", () => {
    expect(assignmentReasonLabel("round_robin")).toBe("Round-robin");
    expect(assignmentReasonLabel("something_new")).toBe("something_new");
    expect(assignmentReasonLabel(null)).toBe("—");
  });
});
