import { describe, expect, it } from "vitest";
import type { AdPerformanceRow } from "@/lib/api";
import { biggestDrop } from "./AdJourney";

const LABELS = { booked: "Booked", paid: "Came / Paid", lost: "Lost" };
const row = (values: Partial<AdPerformanceRow>) => ({
  inline_link_clicks: 298, messages: 130, hot: 18, booked: 3, paid: 1, ...values,
}) as AdPerformanceRow;

describe("biggestDrop", () => {
  it("picks the step where the most people fall away", () => {
    // 44% of taps message, 14% of chats turn hot, 17% of hot book, 33% of booked pay.
    expect(biggestDrop(row({}), LABELS)).toMatch(/^Only 14% of chats turned hot/);
  });

  it("skips steps with under 5 people before them, and none when nothing qualifies", () => {
    expect(biggestDrop(row({ inline_link_clicks: 10, messages: 9, hot: 8, booked: 1, paid: 0 }), LABELS))
      .toMatch(/^8 hot leads, but 1 booked/);
    expect(biggestDrop(row({ inline_link_clicks: 4, messages: 2, hot: 1, booked: 0, paid: 0 }), LABELS)).toBeNull();
  });

  it("ignores a step where more people come out than went in", () => {
    // More booked than hot (warm leads book too): not a drop.
    expect(biggestDrop(row({ inline_link_clicks: 100, messages: 90, hot: 5, booked: 9, paid: 8 }), LABELS))
      .toMatch(/^Only 5\.6% of chats turned hot/);
  });
});
