import { describe, expect, it } from "vitest";
import {
  balanceView, changeVsLastMonth, dailyBars, formatIndian, hasAnyCodes, healthDot, historyLink, percentLabel,
  problemParts, problemsTotal,
} from "./overviewText";

describe("formatIndian", () => {
  it.each([
    [0, "0"], [999, "999"], [1000, "1,000"], [2704, "2,704"], [100000, "1,00,000"],
    [1234567, "12,34,567"], [12345678, "1,23,45,678"], [-2704, "-2,704"],
  ])("%s -> %s", (n, text) => expect(formatIndian(n)).toBe(text));

  it("treats missing numbers as 0", () => {
    expect(formatIndian(null)).toBe("0");
    expect(formatIndian(undefined)).toBe("0");
    expect(formatIndian(Number.NaN)).toBe("0");
  });
});

describe("percentLabel", () => {
  it("shows a dash when there is nothing to divide by", () => {
    expect(percentLabel(null)).toBe("—");
    expect(percentLabel(93)).toBe("93%");
    expect(percentLabel(0)).toBe("0%");
  });
});

describe("changeVsLastMonth", () => {
  it("points up, down or says same", () => {
    expect(changeVsLastMonth({ sent: 9, prev_month_sent: 5, change_pct: 80 })).toEqual({ text: "▲ 80% vs last month", tone: "up" });
    expect(changeVsLastMonth({ sent: 1, prev_month_sent: 4, change_pct: -75 })).toEqual({ text: "▼ 75% vs last month", tone: "down" });
    expect(changeVsLastMonth({ sent: 4, prev_month_sent: 4, change_pct: 0 }).tone).toBe("flat");
  });
  it("explains a missing percentage instead of showing NaN", () => {
    expect(changeVsLastMonth({ sent: 9, prev_month_sent: 0, change_pct: null })).toEqual({ text: "Nothing sent last month", tone: "none" });
  });
});

describe("problems", () => {
  const month = { locked: 2, not_requested: 0, failed: 3 };
  it("adds up locked, customer didn't ask and not delivered", () => {
    expect(problemsTotal(month)).toBe(5);
    expect(problemsTotal({ locked: 0, not_requested: 0, failed: 0 })).toBe(0);
  });
  it("links each non-zero problem to its History filter", () => {
    expect(historyLink("locked")).toBe("/dashboard/otp/history?status=locked");
    expect(problemParts(month).map((p) => [p.text, p.href])).toEqual([
      ["2 locked after wrong tries", "/dashboard/otp/history?status=locked"],
      ["3 not delivered", "/dashboard/otp/history?status=failed"],
    ]);
    expect(problemParts({ locked: 0, not_requested: 0, failed: 0 })).toEqual([]);
  });
});

describe("dailyBars", () => {
  const days = [
    { day: "2026-11-14", sent: 0, verified: 0 },
    { day: "2026-11-15", sent: 50, verified: 25 },
    { day: "2026-11-16", sent: 100, verified: 100 },
  ];
  it("scales to the busiest day and shows verified as a share of each bar", () => {
    const bars = dailyBars(days);
    expect(bars.map((b) => b.sentPct)).toEqual([0, 50, 100]);
    expect(bars.map((b) => b.verifiedPct)).toEqual([0, 50, 100]);
    expect(bars[1]).toMatchObject({ weekday: "Sun", dayNumber: "15", title: "Sun 15: 50 sent, 25 used" });
    expect(bars[0].weekday).toBe("Sat");
  });
  it("handles a quiet week without dividing by zero", () => {
    const quiet = dailyBars([{ day: "2026-11-20", sent: 0, verified: 0 }]);
    expect(quiet[0].sentPct).toBe(0);
    expect(hasAnyCodes([{ day: "2026-11-20", sent: 0, verified: 0 }])).toBe(false);
    expect(hasAnyCodes(days)).toBe(true);
  });
});

describe("healthDot", () => {
  it("green, amber, grey", () => {
    expect(healthDot(true).tone).toBe("green");
    expect(healthDot(false).tone).toBe("amber");
    expect(healthDot(null).tone).toBe("grey");
  });
});

describe("balanceView", () => {
  it("shows the count and the alert line", () => {
    expect(balanceView({ sms_left: 1240, checked_at: null, low_below: 500 })).toEqual({
      headline: "1,240 SMS left", low: false, alertLine: "You get an alert when SMS goes below 500.",
    });
  });
  it("flags low and unknown balances", () => {
    expect(balanceView({ sms_left: 499, checked_at: null, low_below: 500 }).low).toBe(true);
    expect(balanceView({ sms_left: 500, checked_at: null, low_below: 500 }).low).toBe(false);
    expect(balanceView({ sms_left: null, checked_at: null, low_below: 500 }).headline).toBe("Not checked yet");
  });
});
