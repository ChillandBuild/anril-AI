import { describe, expect, it } from "vitest";
import type { AlertRow, QuietTime } from "@/lib/automationsApi";
import { changedAlerts, quietChanged } from "./alertsDraft";

const row = (key: string, on: boolean, who: AlertRow["who"]): AlertRow => ({
  key, label: key, area: "A", who, how: ["bell"], on, comes_through_in_quiet_time: false,
});
const quiet: QuietTime = { on: true, start_hour: 21, end_hour: 9, is_default: false, still_comes_through: [] };

describe("changedAlerts", () => {
  const rows = [row("a", true, ["owner"]), row("b", false, ["owner"])];
  it("is empty when nothing differs", () => {
    expect(changedAlerts(rows, { a: { on: true, who: ["owner"] } })).toEqual([]);
  });
  it("sends only on when only the switch changed", () => {
    expect(changedAlerts(rows, { b: { on: true, who: ["owner"] } })).toEqual([{ key: "b", on: true }]);
  });
  it("sends who when the people changed", () => {
    const who = ["owner", "team"] as AlertRow["who"];
    expect(changedAlerts(rows, { a: { on: true, who } })).toEqual([{ key: "a", on: true, who }]);
  });
});

describe("quietChanged", () => {
  it("detects no edit and real edits", () => {
    expect(quietChanged(quiet, null)).toBe(false);
    expect(quietChanged(quiet, { on: true, start: 21, end: 9 })).toBe(false);
    expect(quietChanged(quiet, { on: true, start: 22, end: 9 })).toBe(true);
  });
});
