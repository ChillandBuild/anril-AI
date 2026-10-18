/**
 * Call Report v1 helpers (SPEC.md): labels, tones and speech-bar layout for the manager's
 * report panel. Pure functions, no React. Tones reuse the TONE_CHIP palette in call-wrapup.ts.
 */
import type {
  CallLog, CallReport, ReportDirection, ReportHandling, ReportMood, SpeechSegments,
} from "@/lib/api";
import { TEMPERATURE_LABEL, type Tone } from "@/lib/call-wrapup";

export interface SpeechBar {
  leftPct: number;
  widthPct: number;
}

/** True when the report has at least one section the panel can draw (segments alone don't count). */
export function hasReportContent(report: CallReport | null | undefined): boolean {
  if (!report) return false;
  const talk = report.talk;
  return Boolean(
    report.mood?.length ||
      report.turning_point ||
      report.objections?.length ||
      report.promises?.length ||
      report.coach ||
      (talk && (isNumber(talk.longest_monologue_s) || isNumber(talk.dead_air_s))),
  );
}

function isNumber(n: unknown): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

/** The lead's temperature from the CRM check, or null when unknown ("none" / empty). */
export function temperatureOf(log: Pick<CallLog, "ai_call_status">): "hot" | "warm" | "cold" | null {
  const t = log.ai_call_status;
  return t === "hot" || t === "warm" || t === "cold" ? t : null;
}

/** True when the verdict row has something to show: a score, a temperature or a next step. */
export function hasVerdict(log: CallLog): boolean {
  const scored = log.score != null && (log.score_status === "scored" || log.score_status === "provisional");
  return scored || temperatureOf(log) !== null || Boolean(log.ai_summary?.next_action?.trim());
}

/** 48 -> "0:48", 125 -> "2:05". Negative, NaN and Infinity read as "0:00". */
export function formatSeconds(seconds: number): string {
  const total = isNumber(seconds) && seconds > 0 ? Math.round(seconds) : 0;
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export const MOOD_LABEL: Record<ReportMood, string> = { positive: "Positive", neutral: "Neutral", negative: "Negative" };
const MOOD_TONE: Record<ReportMood, Tone> = { positive: "won", neutral: "lost", negative: "missed" };

export function moodLabel(mood: ReportMood): string {
  return MOOD_LABEL[mood] ?? "Neutral";
}
export function moodTone(mood: ReportMood): Tone {
  return MOOD_TONE[mood] ?? "lost";
}

export const HANDLING_LABEL: Record<ReportHandling, string> = { handled: "Handled", partly: "Partly", dodged: "Dodged" };
const HANDLING_TONE: Record<ReportHandling, Tone> = { handled: "won", partly: "warm", dodged: "blocked" };

export function handlingLabel(handling: ReportHandling): string {
  return HANDLING_LABEL[handling] ?? "Partly";
}
export function handlingTone(handling: ReportHandling): Tone {
  return HANDLING_TONE[handling] ?? "warm";
}

export const DIRECTION_LABEL: Record<ReportDirection, string> = { warmed: "Warmed up", cooled: "Went cold" };
const DIRECTION_TONE: Record<ReportDirection, Tone> = { warmed: "won", cooled: "cold" };

export function directionLabel(direction: ReportDirection): string {
  return DIRECTION_LABEL[direction] ?? "Went cold";
}
export function directionTone(direction: ReportDirection): Tone {
  return DIRECTION_TONE[direction] ?? "cold";
}

/** Hot / Warm / Cold label for ai_call_status; null for "none", null or anything unknown. */
export function temperatureLabel(status: CallLog["ai_call_status"] | undefined): string | null {
  return status === "hot" || status === "warm" || status === "cold" ? TEMPERATURE_LABEL[status] : null;
}
export function temperatureTone(status: CallLog["ai_call_status"] | undefined): Tone {
  return status === "hot" || status === "warm" || status === "cold" ? status : "neutral";
}

/**
 * Lay speech segments [[start, end], ...] (seconds) out as bars on a 0-100% track.
 * Segments are clamped to the call length; empty, reversed or out-of-range ones are dropped.
 */
export function speechBars(segments: SpeechSegments | null | undefined, duration: number): SpeechBar[] {
  if (!segments?.length || !isNumber(duration) || duration <= 0) return [];
  const bars: SpeechBar[] = [];
  for (const seg of segments) {
    if (!Array.isArray(seg) || !isNumber(seg[0]) || !isNumber(seg[1])) continue;
    const start = Math.min(Math.max(seg[0], 0), duration);
    const end = Math.min(Math.max(seg[1], 0), duration);
    if (end <= start) continue;
    bars.push({ leftPct: (start / duration) * 100, widthPct: ((end - start) / duration) * 100 });
  }
  return bars;
}
