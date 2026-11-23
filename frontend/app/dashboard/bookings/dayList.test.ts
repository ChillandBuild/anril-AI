import { describe, expect, it } from "vitest";
import { dayCounts } from "./DayList";

describe("day tiles", () => {
  it("counts booked by AI, came, still to come with confirmed, and didn't come", () => {
    const c = dayCounts([
      { status: "came", source: "ai", confirmed_at: null },
      { status: "booked", source: "ai", confirmed_at: "x" },
      { status: "booked", source: "phone", confirmed_at: null },
      { status: "no_show", source: "chat", confirmed_at: null },
      { status: "cancelled", source: "ai", confirmed_at: null },
    ]);
    expect(c).toEqual({ booked: 4, byAi: 2, came: 1, toCome: 2, confirmed: 1, noShow: 1 });
  });
});
