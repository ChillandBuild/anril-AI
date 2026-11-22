import { describe, expect, it } from "vitest";
import type { TeachItem } from "@/lib/api";
import { addDays, filterItems, offerLabel, shortDate, taughtLabel, todayIst } from "./teachLogic";

const item = (prompt: string, reply: string): TeachItem => ({
  id: prompt, kind: "answer", prompt, reply, source: "manual", times_taught: 1, created_at: "", updated_at: "",
});

describe("teachLogic", () => {
  it("shows Taught N times only when taught more than once", () => {
    expect(taughtLabel(1)).toBeNull();
    expect(taughtLabel(3)).toBe("Taught 3 times");
  });
  it("searches question and answer, ignoring case", () => {
    const list = [item("Do you deliver?", "Yes all India"), item("Open Sunday?", "10 to 6")];
    expect(filterItems(list, "DELIVER")).toHaveLength(1);
    expect(filterItems(list, "10 to")).toHaveLength(1);
    expect(filterItems(list, "  ")).toHaveLength(2);
  });
  it("labels offers by state", () => {
    expect(offerLabel({ status: "live", starts_on: "2026-11-01", ends_on: "2026-11-30" })).toBe("Live · ends 30 Nov");
    expect(offerLabel({ status: "upcoming", starts_on: "2026-12-05", ends_on: "2026-12-09" })).toBe("Starts 5 Dec");
    expect(offerLabel({ status: "ended", starts_on: "2026-10-01", ends_on: "2026-10-09" })).toBe("Ended · AI stopped");
  });
  it("does date maths on plain calendar days", () => {
    expect(shortDate("2026-01-09")).toBe("9 Jan");
    expect(addDays("2026-02-27", 2)).toBe("2026-03-01");
    expect(todayIst(new Date("2026-11-21T20:00:00Z"))).toBe("2026-11-22");
  });
});
