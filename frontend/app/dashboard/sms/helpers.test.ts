import { describe, expect, it } from "vitest";
import {
  campaignStatusLabel,
  campaignNeedsUpdates,
  previewKey,
  clampRange,
  countVars,
  defaultRange,
  formatIst,
  groupExcluded,
  isVariableMapComplete,
  maxToFor,
  splitTemplate,
  statusLabel,
  statusTone,
} from "./helpers";

describe("statusLabel", () => {
  it("uses the contract wording for every message status", () => {
    expect(statusLabel("queued")).toBe("Waiting");
    expect(statusLabel("sending")).toBe("Sending");
    expect(statusLabel("submitted")).toBe("Sent to operator");
    expect(statusLabel("delivered")).toBe("Delivered");
    expect(statusLabel("failed")).toBe("Failed");
    expect(statusLabel("unknown")).toBe("Checking…");
    expect(statusLabel("skipped")).toBe("Not sent");
    expect(statusLabel("cancelled")).toBe("Cancelled");
  });
  it("passes an unknown status through", () => {
    expect(statusLabel("weird")).toBe("weird");
    expect(statusTone("weird")).toBe("neutral");
  });
  it("labels campaign statuses", () => {
    expect(campaignStatusLabel("scheduled")).toBe("Scheduled");
  });
});

describe("formatIst", () => {
  it("converts UTC to IST", () => {
    expect(formatIst("2026-10-30T08:34:00Z")).toBe("30 Oct, 2:04 pm");
  });
  it("handles empty input", () => {
    expect(formatIst(null)).toBe("—");
  });
});

describe("date ranges", () => {
  it("builds an inclusive default window", () => {
    expect(defaultRange("2026-10-30", 3)).toEqual({ from: "2026-10-28", to: "2026-10-30" });
  });
  it("moves 'to' back when 'from' is edited past the window", () => {
    expect(clampRange({ from: "2026-10-20", to: "2026-10-30" }, "from", 3, "2026-10-30")).toEqual({
      from: "2026-10-20",
      to: "2026-10-22",
    });
  });
  it("moves 'from' forward when 'to' is edited past the window", () => {
    expect(clampRange({ from: "2026-10-20", to: "2026-10-30" }, "to", 3, "2026-10-30")).toEqual({
      from: "2026-10-28",
      to: "2026-10-30",
    });
  });
  it("never reaches into the future", () => {
    expect(clampRange({ from: "2026-10-29", to: "2026-11-05" }, "to", 3, "2026-10-30").to).toBe("2026-10-30");
    expect(maxToFor("2026-10-29", 3, "2026-10-30")).toBe("2026-10-30");
    expect(maxToFor("2026-10-01", 3, "2026-10-30")).toBe("2026-10-03");
  });
  it("fixes an inverted range", () => {
    expect(clampRange({ from: "2026-10-25", to: "2026-10-20" }, "from", 30, "2026-10-30")).toEqual({
      from: "2026-10-25",
      to: "2026-10-25",
    });
  });
});

describe("template variables", () => {
  const msg = "Hi {#var#}, your visit is on {#var#}. Call us.";
  it("splits wording into text and numbered slots", () => {
    expect(splitTemplate(msg)).toEqual([
      { kind: "text", text: "Hi " },
      { kind: "var", index: 0 },
      { kind: "text", text: ", your visit is on " },
      { kind: "var", index: 1 },
      { kind: "text", text: ". Call us." },
    ]);
    expect(countVars(msg)).toBe(2);
    expect(countVars("No variables")).toBe(0);
  });
  it("needs every slot filled", () => {
    expect(isVariableMapComplete([{ source: "field", value: "name" }, null], 2)).toBe(false);
    expect(isVariableMapComplete([{ source: "field", value: "name" }, { source: "text", value: " " }], 2)).toBe(false);
    expect(isVariableMapComplete([{ source: "field", value: "name" }, { source: "text", value: "2 Nov" }], 2)).toBe(true);
    expect(isVariableMapComplete([], 0)).toBe(true);
  });
});

describe("groupExcluded", () => {
  it("groups by reason, biggest first", () => {
    const grouped = groupExcluded([
      { lead_id: "1", name: "A", phone: "1", reason: "Opted out" },
      { lead_id: "2", name: "B", phone: "2", reason: "Duplicate number" },
      { lead_id: "3", name: "C", phone: "3", reason: "Duplicate number" },
    ]);
    expect(grouped.map((g) => [g.reason, g.leads.length])).toEqual([
      ["Duplicate number", 2],
      ["Opted out", 1],
    ]);
  });
});

describe("delivery updates", () => {
  it("keeps checking completed campaigns with submitted or unknown messages", () => {
    expect(campaignNeedsUpdates({ status: "completed", counts: { submitted: 2 } })).toBe(true);
    expect(campaignNeedsUpdates({ status: "completed", counts: { unknown: 1 } })).toBe(true);
    expect(campaignNeedsUpdates({ status: "completed", counts: { delivered: 2 } })).toBe(false);
    expect(campaignNeedsUpdates({ status: "scheduled", counts: {} })).toBe(true);
  });
});

describe("preview snapshot", () => {
  const template = { id: "t", message: "Hi {#var#}", template_type: "service" };
  const map = [{ source: "text" as const, value: "Sam" }];
  it("invalidates when recipients, wording, type or mapped values change", () => {
    const key = previewKey(template, map, new Set(["a"]));
    expect(previewKey(template, map, new Set(["b"]))).not.toBe(key);
    expect(previewKey({ ...template, message: "Hello" }, map, new Set(["a"]))).not.toBe(key);
    expect(previewKey({ ...template, template_type: "promotional" }, map, new Set(["a"]))).not.toBe(key);
    expect(previewKey(template, [{ source: "text", value: "Lee" }], new Set(["a"]))).not.toBe(key);
  });
  it("treats recipient order as the same snapshot", () => {
    expect(previewKey(template, map, new Set(["a", "b"]))).toBe(previewKey(template, map, new Set(["b", "a"])));
  });
});
