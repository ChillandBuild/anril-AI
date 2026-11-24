import { describe, expect, it } from "vitest";
import { buttonSlots, issuesFor, previewOf, rowForCheck, variablesIn, type BulkRow } from "./template-excel";

const row: BulkRow = {
  row: 4, name: "festival_offer", type: "MARKETING", language: "ta",
  header: "Offer for {{1}}", header_example: "Priya",
  body: "Hi {{1}}, flat {{2}} off this week.", examples: ["Priya", "20%", "", "", ""],
  footer: "Reply STOP to stop",
  buttons: [{ type: "URL", text: "Shop now", value: "https://example.com" }],
  issues: [{ field: "example_2", text: "{{2}} has no example" }], problems: ["{{2}} has no example"], status: "need_fix",
};

describe("Excel review helpers", () => {
  it("finds the variables a text uses", () => {
    expect(variablesIn("Hi {{2}} and {{1}} and {{2}}")).toEqual([1, 2]);
    expect(variablesIn("no blanks")).toEqual([]);
  });

  it("gives each field its own problems", () => {
    expect(issuesFor(row, "example_2")).toEqual(["{{2}} has no example"]);
    expect(issuesFor(row, "body")).toEqual([]);
  });

  it("always shows three button slots", () => {
    expect(buttonSlots(row)).toHaveLength(3);
    expect(buttonSlots(row)[1]).toEqual({ type: "", text: "", value: "" });
  });

  it("sends back the edited row with five examples and only filled buttons", () => {
    const out = rowForCheck({ ...row, examples: ["Priya"], buttons: [...buttonSlots(row)] });
    expect(out.examples).toEqual(["Priya", "", "", "", ""]);
    expect(out.buttons).toEqual([{ type: "URL", text: "Shop now", value: "https://example.com" }]);
    expect(out).not.toHaveProperty("status");
  });

  it("previews with the examples in place of {{n}}", () => {
    const p = previewOf(row);
    expect(p.headerType).toBe("TEXT");
    expect(p.headerSample).toBe("Priya");
    expect(p.bodySamples).toEqual({ 1: "Priya", 2: "20%" });
    expect(p.buttons).toEqual([{ type: "URL", text: "Shop now", url: "https://example.com", phone: undefined }]);
  });
});
