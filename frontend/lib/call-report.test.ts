import { describe, expect, it } from "vitest";
import type { CallLog, CallReport } from "./api";
import {
  directionLabel, directionTone, formatSeconds, handlingLabel, handlingTone, hasReportContent, hasSegments, hasVerdict,
  segmentsDuration,
  moodLabel, moodTone, speechBars, temperatureLabel, temperatureTone, temperatureOf,
} from "./call-report";

const moment = { time: "02:40", start: 160, quote: "fees romba jaasthi" };
const log = (extra: Partial<CallLog>): CallLog => ({ id: "c1", ...extra }) as CallLog;

describe("hasReportContent", () => {
  it("is false for a missing or empty report", () => {
    expect(hasReportContent(undefined)).toBe(false);
    expect(hasReportContent(null)).toBe(false);
    expect(hasReportContent({})).toBe(false);
    expect(hasReportContent({ mood: [], objections: [], promises: [], talk: {} })).toBe(false);
  });

  it("does not count speech segments alone", () => {
    expect(hasReportContent({ segments: { telecaller: [[0, 5]], customer: [] } })).toBe(false);
  });

  it.each<[string, CallReport]>([
    ["mood", { mood: [{ ...moment, mood: "negative" }] }],
    ["turning point", { turning_point: { ...moment, direction: "cooled", why: "x" } }],
    ["objections", { objections: [{ ...moment, handling: "dodged", why: "" }] }],
    ["promises", { promises: [{ ...moment, risky: true, why: "x" }] }],
    ["coach", { coach: { ...moment, tip: "x" } }],
    ["talk monologue", { talk: { longest_monologue_s: 48 } }],
    ["talk dead air of zero", { talk: { dead_air_s: 0 } }],
  ])("is true with %s", (_name, report) => {
    expect(hasReportContent(report)).toBe(true);
  });
});

describe("verdict", () => {
  it("reads the temperature, hiding none and null", () => {
    expect(temperatureOf({ ai_call_status: "warm" })).toBe("warm");
    expect(temperatureOf({ ai_call_status: "none" })).toBeNull();
    expect(temperatureOf({ ai_call_status: null })).toBeNull();
    expect(temperatureOf({})).toBeNull();
  });

  it("has a verdict with a scored call, a temperature or a next step", () => {
    expect(hasVerdict(log({ score: 62, score_status: "scored" }))).toBe(true);
    expect(hasVerdict(log({ score: 62, score_status: "provisional" }))).toBe(true);
    expect(hasVerdict(log({ ai_call_status: "hot" }))).toBe(true);
    expect(hasVerdict(log({ ai_summary: { next_action: "Send fee details" } }))).toBe(true);
  });

  it("has no verdict for an unscored, untagged call with no next step", () => {
    expect(hasVerdict(log({ score: 62, score_status: "failed" }))).toBe(false);
    expect(hasVerdict(log({ ai_call_status: "none", ai_summary: { next_action: "  " } }))).toBe(false);
    expect(hasVerdict(log({}))).toBe(false);
  });
});

describe("formatSeconds", () => {
  it("formats minutes and seconds", () => {
    expect(formatSeconds(48)).toBe("0:48");
    expect(formatSeconds(125)).toBe("2:05");
    expect(formatSeconds(0)).toBe("0:00");
    expect(formatSeconds(22.4)).toBe("0:22");
    expect(formatSeconds(3600)).toBe("60:00");
  });

  it("treats bad input as 0:00", () => {
    expect(formatSeconds(-5)).toBe("0:00");
    expect(formatSeconds(Number.NaN)).toBe("0:00");
    expect(formatSeconds(Number.POSITIVE_INFINITY)).toBe("0:00");
  });
});

describe("labels and tones", () => {
  it("maps moods", () => {
    expect(moodLabel("positive")).toBe("Positive");
    expect(moodLabel("negative")).toBe("Negative");
    expect(moodTone("positive")).toBe("won");
    expect(moodTone("neutral")).toBe("lost");
    expect(moodTone("negative")).toBe("missed");
  });

  it("maps handling", () => {
    expect(handlingLabel("handled")).toBe("Handled");
    expect(handlingLabel("partly")).toBe("Partly");
    expect(handlingLabel("dodged")).toBe("Dodged");
    expect(handlingTone("handled")).toBe("won");
    expect(handlingTone("partly")).toBe("warm");
    expect(handlingTone("dodged")).toBe("blocked");
  });

  it("maps turning point direction", () => {
    expect(directionLabel("warmed")).toBe("Warmed up");
    expect(directionLabel("cooled")).toBe("Went cold");
    expect(directionTone("warmed")).toBe("won");
    expect(directionTone("cooled")).toBe("cold");
  });

  it("falls back for values the backend might add later", () => {
    expect(moodLabel("angry" as never)).toBe("Neutral");
    expect(handlingTone("???" as never)).toBe("warm");
    expect(directionLabel("???" as never)).toBe("Went cold");
  });

  it("maps lead temperature, hiding none and null", () => {
    expect(temperatureLabel("hot")).toBe("Hot");
    expect(temperatureLabel("warm")).toBe("Warm");
    expect(temperatureLabel("cold")).toBe("Cold");
    expect(temperatureLabel("none")).toBeNull();
    expect(temperatureLabel(null)).toBeNull();
    expect(temperatureLabel(undefined)).toBeNull();
    expect(temperatureTone("hot")).toBe("hot");
    expect(temperatureTone("none")).toBe("neutral");
  });
});

describe("speechBars", () => {
  it("lays segments out as percentages of the call", () => {
    expect(speechBars([[0, 25], [50, 100]], 100)).toEqual([
      { leftPct: 0, widthPct: 25 },
      { leftPct: 50, widthPct: 50 },
    ]);
  });

  it("clamps segments that run past the ends of the call", () => {
    expect(speechBars([[-10, 10], [90, 130]], 100)).toEqual([
      { leftPct: 0, widthPct: 10 },
      { leftPct: 90, widthPct: 10 },
    ]);
  });

  it("drops empty, reversed, out-of-range and malformed segments", () => {
    const bad = [[5, 5], [30, 10], [120, 140], [Number.NaN, 4], ["a", 2]] as unknown as [number, number][];
    expect(speechBars(bad, 100)).toEqual([]);
  });

  it("returns nothing without segments or a usable duration", () => {
    expect(speechBars(undefined, 100)).toEqual([]);
    expect(speechBars(null, 100)).toEqual([]);
    expect(speechBars([], 100)).toEqual([]);
    expect(speechBars([[0, 5]], 0)).toEqual([]);
    expect(speechBars([[0, 5]], Number.NaN)).toEqual([]);
  });
});

describe("hasSegments", () => {
  it("is true when either side has a segment", () => {
    expect(hasSegments({ telecaller: [[0, 5]], customer: [] })).toBe(true);
    expect(hasSegments({ customer: [[1, 2]] })).toBe(true);
  });

  it("is false for null, undefined and empty sides", () => {
    expect(hasSegments(null)).toBe(false);
    expect(hasSegments(undefined)).toBe(false);
    expect(hasSegments({})).toBe(false);
    expect(hasSegments({ telecaller: [], customer: [] })).toBe(false);
  });
});

describe("segmentsDuration", () => {
  it("is the latest end across both sides", () => {
    expect(segmentsDuration({ telecaller: [[0, 5], [10, 42.5]], customer: [[3, 60]] })).toBe(60);
    expect(segmentsDuration({ telecaller: [[0, 7]] })).toBe(7);
  });

  it("is 0 with no usable segments", () => {
    expect(segmentsDuration(null)).toBe(0);
    expect(segmentsDuration({ telecaller: [], customer: [] })).toBe(0);
    expect(segmentsDuration({ telecaller: [[0, Number.NaN]] as unknown as [number, number][] })).toBe(0);
  });
});
