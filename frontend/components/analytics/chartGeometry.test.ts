import { describe, expect, it } from "vitest";
import { barGeometry, lineGeometry } from "./chartGeometry";

describe("barGeometry", () => {
  it("nothing in, nothing out", () => {
    expect(barGeometry([], [], 360, 160)).toEqual([]);
  });
  it("the biggest value gets the tallest bar and bars stay inside the box", () => {
    const bars = barGeometry(["a", "b", "c"], [10, 5, 0], 360, 160);
    expect(bars[0].h).toBeGreaterThan(bars[1].h);
    expect(bars[1].h).toBeGreaterThan(bars[2].h);
    expect(bars[2].h).toBeGreaterThan(0);
    for (const b of bars) {
      expect(b.x).toBeGreaterThanOrEqual(0);
      expect(b.x + b.w).toBeLessThanOrEqual(360);
      expect(b.y + b.h).toBeLessThanOrEqual(160);
    }
  });
});

describe("lineGeometry", () => {
  it("draws a path through every point, higher values higher up", () => {
    const g = lineGeometry(["a", "b", "c"], [1, 3, 2], 360, 160);
    expect(g.points).toHaveLength(3);
    expect(g.path.startsWith("M")).toBe(true);
    expect(g.points[1].y).toBeLessThan(g.points[0].y);
  });
  it("one point sits in the middle", () => {
    expect(lineGeometry(["a"], [4], 360, 160).points[0].x).toBe(180);
  });
  it("empty is empty", () => {
    expect(lineGeometry([], [], 360, 160)).toEqual({ points: [], path: "" });
  });
});
