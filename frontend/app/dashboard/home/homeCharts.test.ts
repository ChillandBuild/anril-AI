import { describe, expect, it } from "vitest";
import {
  aiShare,
  barPct,
  boxSeries,
  dayName,
  donutSlices,
  linePlot,
  niceMax,
  pointsAttr,
  ringDash,
  seriesCaption,
  sparkPoints,
  targetPct,
  weekdayLabels,
} from "./homeCharts";

describe("sparkPoints", () => {
  it("scales from zero: the top value sits at the top pad, zero at the bottom pad", () => {
    const pts = sparkPoints([5, 3, 6, 4, 8, 1, 6]);
    expect(pts).toHaveLength(7);
    expect(pts[0].x).toBe(4);
    expect(pts[6].x).toBe(80);
    expect(pts[4].y).toBe(4); // 8 is the max
    expect(sparkPoints([0, 8])[0].y).toBe(24); // 0 is the baseline
  });

  it("draws an all-zero week as a flat line on the baseline, never NaN", () => {
    const pts = sparkPoints([0, 0, 0, 0, 0, 0, 0]);
    expect(new Set(pts.map((p) => p.y))).toEqual(new Set([24]));
    expect(pointsAttr(pts)).not.toContain("NaN");
  });

  it("keeps a negative day inside the box", () => {
    const pts = sparkPoints([-5, 5]);
    expect(pts[0].y).toBe(24);
    expect(pts[1].y).toBe(4);
  });

  it("handles empty and single-value input", () => {
    expect(sparkPoints([])).toEqual([]);
    expect(sparkPoints([3])).toHaveLength(1);
  });

  it("formats points with one decimal", () => {
    expect(pointsAttr([{ x: 4, y: 24 }, { x: 80, y: 4.04 }])).toBe("4.0,24.0 80.0,4.0");
  });
});

describe("boxSeries", () => {
  it("returns the series only when it is 2+ finite numbers", () => {
    expect(boxSeries({ series: [1, 2, 3] })).toEqual([1, 2, 3]);
    expect(boxSeries({ series: [1] })).toBeNull();
    expect(boxSeries({ series: [] })).toBeNull();
    expect(boxSeries({})).toBeNull();
    expect(boxSeries({ series: null })).toBeNull();
    expect(boxSeries(undefined)).toBeNull();
    expect(boxSeries({ series: [1, Number.NaN, 3] })).toBeNull();
  });
});

describe("day names", () => {
  it("names a day", () => {
    expect(dayName("2026-11-23")).toBe("Mon");
    expect(dayName("nonsense")).toBe("");
  });

  it("lists the weekdays ending on a day, oldest first", () => {
    expect(weekdayLabels("2026-11-23", 7)).toEqual(["Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Mon"]);
    expect(weekdayLabels("bad", 3)).toEqual(["", "", ""]);
  });
});

describe("line chart", () => {
  it("rounds the axis up to a multiple of 4", () => {
    expect(niceMax(0)).toBe(4);
    expect(niceMax(3)).toBe(4);
    expect(niceMax(5)).toBe(8);
    expect(niceMax(8)).toBe(8);
    expect(niceMax(9)).toBe(12);
  });

  it("places points across the plot box", () => {
    const box = { left: 34, right: 590, top: 22, bottom: 150 };
    const pts = linePlot([0, 4, 8], box, 8);
    expect(pts[0]).toEqual({ x: 34, y: 150 });
    expect(pts[2]).toEqual({ x: 590, y: 22 });
    expect(pts[1].y).toBe(86);
  });
});

describe("rings and gauges", () => {
  it("splits a ring into slices that add up to the circle", () => {
    const r = 46;
    const slices = donutSlices([3, 3, 4], r);
    expect(slices.map((s) => s.offset)).toEqual([0, -86.71, -173.42]);
    expect(slices[0].dash).toBe("83.71 205.32");
    expect(slices[2].dash).toBe("112.61 176.42");
  });

  it("skips empty slices and gives one full slice the whole circle", () => {
    const slices = donutSlices([0, 5, 0], 46);
    expect(slices[0].dash).toBeNull();
    expect(slices[2].dash).toBeNull();
    expect(slices[1].dash).toBe("289.03 0.00");
    expect(donutSlices([0, 0], 46).every((s) => s.dash === null)).toBe(true);
  });

  it("fills a ring by percent and clamps it", () => {
    expect(ringDash(50, 26)).toBe("81.68 163.36");
    expect(ringDash(150, 26)).toBe("163.36 163.36");
    expect(ringDash(-5, 26)).toBe("0.00 163.36");
  });

  it("reads the target percent from the box", () => {
    expect(targetPct({ value: 18600000, unit: "paise", sub: "of ₹2,00,000 · 93%" })).toBe(93);
    expect(targetPct({ value: 93, unit: "percent", sub: "of target" })).toBe(93);
    expect(targetPct({ value: 130, unit: "percent", sub: "of target" })).toBe(100);
    expect(targetPct({ value: 0, unit: "set_target", sub: "Tap to choose one" })).toBeNull();
    expect(targetPct({ value: 100, unit: "paise", sub: null })).toBeNull();
  });

  it("works out the AI share", () => {
    expect(aiShare(41, 5)).toBe(89);
    expect(aiShare(0, 0)).toBeNull();
    expect(aiShare(0, 3)).toBe(0);
    expect(aiShare(7, 0)).toBe(100);
  });
});

describe("barPct", () => {
  it("is relative to the longest bar", () => {
    expect(barPct(24, 24)).toBe(100);
    expect(barPct(12, 24)).toBe(50);
  });

  it("keeps a tiny non-zero bar visible and a zero bar empty", () => {
    expect(barPct(1, 1000)).toBe(2);
    expect(barPct(0, 10)).toBe(0);
    expect(barPct(5, 0)).toBe(0);
  });
});

describe("seriesCaption", () => {
  it("says what each line plots, per day, not the box number", () => {
    expect(seriesCaption("won_month", "Won this month")).toBe("Won per day");
    expect(seriesCaption("callbacks_today", "Follow-ups due today")).toBe("Call-backs scheduled per day");
    expect(seriesCaption("new_enquiries_today", "New enquiries today")).toBe("New enquiries per day");
    expect(seriesCaption("money_in_today", "Money in today")).toBe("Money in per day");
  });

  it("falls back to the box label for a box added later", () => {
    expect(seriesCaption("something_new", "Something")).toBe("Something per day");
  });
});
