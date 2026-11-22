import type { OtpOverviewBalance, OtpOverviewDay, OtpOverviewMonth } from "@/lib/otpOverviewApi";

/** 2704 -> "2,704", 123456 -> "1,23,456" (lakh grouping). */
export function formatIndian(n: number | null | undefined): string {
  const value = Math.trunc(Number.isFinite(n as number) ? (n as number) : 0);
  const sign = value < 0 ? "-" : "";
  const digits = String(Math.abs(value));
  if (digits.length <= 3) return sign + digits;
  const head = digits.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
  return `${sign}${head},${digits.slice(-3)}`;
}

/** 93 -> "93%", null -> "—". */
export function percentLabel(pct: number | null | undefined): string {
  return pct === null || pct === undefined || !Number.isFinite(pct) ? "—" : `${pct}%`;
}

export type ChangeTone = "up" | "down" | "flat" | "none";

/** The small line under "Codes sent": "▲ 12% vs last month". */
export function changeVsLastMonth(month: Pick<OtpOverviewMonth, "sent" | "prev_month_sent" | "change_pct">): {
  text: string;
  tone: ChangeTone;
} {
  const { change_pct: pct, prev_month_sent: prev } = month;
  if (pct === null) return { text: prev === 0 ? "Nothing sent last month" : "No change to show", tone: "none" };
  if (pct > 0) return { text: `▲ ${pct}% vs last month`, tone: "up" };
  if (pct < 0) return { text: `▼ ${Math.abs(pct)}% vs last month`, tone: "down" };
  return { text: "Same as last month", tone: "flat" };
}

export type ProblemStatus = "locked" | "not_requested" | "failed";

/** What each problem is called here, and the History filter it opens. */
export const PROBLEM_KINDS: { status: ProblemStatus; label: string }[] = [
  { status: "locked", label: "locked after wrong tries" },
  { status: "not_requested", label: "customer didn't ask" },
  { status: "failed", label: "not delivered" },
];

export function problemsTotal(month: Pick<OtpOverviewMonth, ProblemStatus>): number {
  return month.locked + month.not_requested + month.failed;
}

export function historyLink(status: ProblemStatus): string {
  return `/dashboard/otp/history?status=${status}`;
}

export type ProblemPart = { status: ProblemStatus; count: number; text: string; href: string };

/** The non-zero problems, each with its own "see History" link. */
export function problemParts(month: Pick<OtpOverviewMonth, ProblemStatus>): ProblemPart[] {
  return PROBLEM_KINDS.filter((k) => month[k.status] > 0).map((k) => ({
    status: k.status,
    count: month[k.status],
    text: `${formatIndian(month[k.status])} ${k.label}`,
    href: historyLink(k.status),
  }));
}

export type DayBar = { day: string; weekday: string; dayNumber: string; sent: number; verified: number; sentPct: number; verifiedPct: number; title: string };

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Bars for the 7 days. Heights are percentages of the busiest day; "verified" is a share of that day's bar. */
export function dailyBars(days: OtpOverviewDay[]): DayBar[] {
  const max = Math.max(0, ...days.map((d) => d.sent));
  return days.map((d) => {
    const [y, m, dd] = d.day.split("-").map(Number);
    const weekday = WEEKDAYS[new Date(Date.UTC(y, m - 1, dd)).getUTCDay()] ?? "";
    return {
      day: d.day,
      weekday,
      dayNumber: String(dd),
      sent: d.sent,
      verified: d.verified,
      sentPct: max > 0 ? (d.sent / max) * 100 : 0,
      verifiedPct: d.sent > 0 ? Math.min(100, (d.verified / d.sent) * 100) : 0,
      title: `${weekday} ${dd}: ${formatIndian(d.sent)} sent, ${formatIndian(d.verified)} used`,
    };
  });
}

export function hasAnyCodes(days: OtpOverviewDay[]): boolean {
  return days.some((d) => d.sent > 0);
}

export type HealthDot = { tone: "green" | "amber" | "grey"; word: string };

export function healthDot(ok: boolean | null): HealthDot {
  if (ok === true) return { tone: "green", word: "Working" };
  if (ok === false) return { tone: "amber", word: "Needs a look" };
  return { tone: "grey", word: "Not checked" };
}

export function balanceView(balance: OtpOverviewBalance): { headline: string; low: boolean; alertLine: string } {
  const alertLine = `You get an alert when SMS goes below ${formatIndian(balance.low_below)}.`;
  if (balance.sms_left === null) return { headline: "Not checked yet", low: false, alertLine };
  return {
    headline: `${formatIndian(balance.sms_left)} SMS left`,
    low: balance.sms_left < balance.low_below,
    alertLine,
  };
}
