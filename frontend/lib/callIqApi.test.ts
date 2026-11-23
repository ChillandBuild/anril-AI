import { describe, expect, it } from "vitest";
import {
  callReviewHref,
  canOpenLive,
  canOpenTeamReports,
  canDownloadCalls,
  canSeeCallCharts,
  periodDates,
  sortResults,
  talkText,
  countByState,
  dueText,
  hasView,
  minutesText,
  pickedUpText,
  scoreText,
  scoreTone,
  showsMoney,
  sinceText,
  sortLive,
  stateLabel,
  type LivePerson,
  type ResultsPerson,
  type ResultsResponse,
} from "./callIqApi";

const person = (name: string, state: LivePerson["state"]): LivePerson => ({
  caller_id: name, name, state, since: null, calls_today: 0, break_minutes_today: 0,
});

describe("live board", () => {
  it("uses plain words for each state", () => {
    expect(stateLabel("on_call")).toBe("On a call");
    expect(stateLabel("on_break")).toBe("On a break");
    expect(stateLabel("idle")).toBe("Free");
    expect(stateLabel("off")).toBe("Not logged in");
    expect(stateLabel("something_new")).toBe("Not logged in");
  });

  it("sorts on a call, free, on a break, not logged in, then by name", () => {
    const sorted = sortLive([person("Dev", "off"), person("Bala", "idle"), person("Zara", "on_call"), person("Anitha", "idle"), person("Chitra", "on_break")]);
    expect(sorted.map((p) => p.name)).toEqual(["Zara", "Anitha", "Bala", "Chitra", "Dev"]);
  });

  it("counts people by state and treats unknown states as not logged in", () => {
    const counts = countByState([person("A", "idle"), person("B", "idle"), person("C", "on_call"), { ...person("D", "off"), state: "weird" as LivePerson["state"] }]);
    expect(counts).toEqual({ on_call: 1, on_break: 0, idle: 2, off: 1 });
  });

  it("writes minutes the short way", () => {
    expect(minutesText(0)).toBe("0 min");
    expect(minutesText(45.4)).toBe("45 min");
    expect(minutesText(60)).toBe("1h");
    expect(minutesText(125)).toBe("2h 5m");
    expect(minutesText(null)).toBe("—");
    expect(minutesText(-3)).toBe("0 min");
  });

  it("says how long a call or break has run, and since when someone is free", () => {
    const now = new Date("2026-11-22T07:00:00Z"); // 12:30 PM in India
    expect(sinceText({ state: "on_call", since: "2026-11-22T06:48:00Z" }, now)).toBe("for 12 min");
    expect(sinceText({ state: "on_break", since: "2026-11-22T05:55:00Z" }, now)).toBe("for 1h 5m");
    expect(sinceText({ state: "idle", since: "2026-11-22T04:32:00Z" }, now)).toBe("since 10:02 AM");
    expect(sinceText({ state: "off", since: "2026-11-20T12:00:00Z" }, now)).toBe("since 20 Nov, 5:30 PM");
    expect(sinceText({ state: "idle", since: null }, now)).toBe("");
    expect(sinceText({ state: "idle", since: "garbage" }, now)).toBe("");
  });
});

describe("evaluation", () => {
  it("picks a tone from the average score", () => {
    expect(scoreTone(90)).toBe("good");
    expect(scoreTone(75)).toBe("good");
    expect(scoreTone(74.9)).toBe("ok");
    expect(scoreTone(50)).toBe("ok");
    expect(scoreTone(49)).toBe("low");
    expect(scoreTone(null)).toBe("none");
  });

  it("shows whole scores plainly and decimals to one place", () => {
    expect(scoreText(80)).toBe("80");
    expect(scoreText(71.666)).toBe("71.7");
    expect(scoreText(null)).toBe("—");
  });

  it("links a low call to the call review page", () => {
    expect(callReviewHref("abc-123")).toBe("/dashboard/notes?call=abc-123");
    expect(callReviewHref("a b")).toBe("/dashboard/notes?call=a%20b");
  });
});

describe("results", () => {
  const withMoney: ResultsResponse = { period: "today", callers: [], totals: { calls: 5, connected: 4, orders: 2, revenue_paise: 150000 } };
  const withoutMoney: ResultsResponse = { period: "today", callers: [], totals: { calls: 5, connected: 4, orders: 2 } };

  it("shows the money column only when the server sent money", () => {
    expect(showsMoney(withMoney)).toBe(true);
    expect(showsMoney({ ...withMoney, totals: { ...withMoney.totals, revenue_paise: 0 } })).toBe(true);
    expect(showsMoney(withoutMoney)).toBe(false);
    expect(showsMoney(null)).toBe(false);
  });

  it("says how many calls were picked up", () => {
    expect(pickedUpText({ calls: 4, connected: 3 })).toBe("3 of 4 picked up");
    expect(pickedUpText({ calls: 0, connected: 0 })).toBe("No calls");
  });
});

describe("who may open what", () => {
  it("lets the owner open everything", () => {
    expect(canOpenLive("owner", [])).toBe(true);
    expect(canOpenTeamReports("owner", [])).toBe(true);
  });

  it("lets a telecaller open Live only", () => {
    expect(canOpenLive("caller", ["telecalling.view"])).toBe(true);
    expect(canOpenTeamReports("caller", ["telecalling.view"])).toBe(false);
  });

  it("counts a manage permission as view", () => {
    expect(hasView("caller", ["team.manage"], "team.view")).toBe(true);
    expect(hasView("caller", ["team.view"], "team.manage")).toBe(false);
    expect(canOpenLive("caller", ["team.view"])).toBe(true);
    expect(canOpenLive("caller", ["deals.view"])).toBe(false);
    expect(canOpenLive(null, [])).toBe(false);
  });
});

describe("callbacks due now", () => {
  const now = new Date("2026-11-22T07:00:00Z");
  it("says how far the scheduled time is, in plain words", () => {
    expect(dueText("2026-11-22T07:10:00Z", now)).toBe("due in 10 min");
    expect(dueText("2026-11-22T07:00:00Z", now)).toBe("due now");
    expect(dueText("2026-11-22T06:40:00Z", now)).toBe("20 min late");
    expect(dueText("not a date", now)).toBe("");
  });
});

describe("results table", () => {
  const row = (name: string, calls: number, orders: number, talk?: number): ResultsPerson => ({
    caller_id: name, name, calls, connected: 0, orders, talk_seconds: talk,
  });

  it("sorts by a number column, ties by name", () => {
    const rows = [row("Bala", 5, 1), row("Anitha", 5, 3), row("Chitra", 9, 0)];
    expect(sortResults(rows, "calls", "desc").map((r) => r.name)).toEqual(["Chitra", "Anitha", "Bala"]);
    expect(sortResults(rows, "orders", "asc").map((r) => r.name)).toEqual(["Chitra", "Bala", "Anitha"]);
    expect(sortResults(rows, "name", "asc").map((r) => r.name)).toEqual(["Anitha", "Bala", "Chitra"]);
  });

  it("treats a missing talk time as zero", () => {
    const rows = [row("Bala", 1, 0, 120), row("Anitha", 1, 0)];
    expect(sortResults(rows, "talk_seconds", "desc").map((r) => r.name)).toEqual(["Bala", "Anitha"]);
  });

  it("writes talk time in plain words", () => {
    expect(talkText(undefined)).toBe("0 min");
    expect(talkText(40)).toBe("40 s");
    expect(talkText(720)).toBe("12 min");
    expect(talkText(3900)).toBe("1 h 5 min");
  });

  it("turns a period into the same India-time days the server counts", () => {
    expect(periodDates("today", "2026-11-23")).toEqual({ from: "2026-11-23", to: "2026-11-23" });
    expect(periodDates("7d", "2026-11-23")).toEqual({ from: "2026-11-17", to: "2026-11-23" });
    expect(periodDates("30d", "2026-03-01")).toEqual({ from: "2026-01-31", to: "2026-03-01" });
  });

  it("shows charts to the owner, Reports access or a Team leader; the download needs Reports and lead download", () => {
    expect(canSeeCallCharts("owner", [], null)).toBe(true);
    expect(canSeeCallCharts("manager", ["team.view", "analytics.view"], null)).toBe(true);
    expect(canSeeCallCharts("manager", ["team.view"], "team_leader")).toBe(true);
    expect(canSeeCallCharts("manager", ["team.view"], null)).toBe(false);
    expect(canDownloadCalls("owner", [])).toBe(true);
    expect(canDownloadCalls("manager", ["analytics.view", "leads.download"])).toBe(true);
    expect(canDownloadCalls("manager", ["leads.download"])).toBe(false);
    expect(canDownloadCalls("manager", ["analytics.view"])).toBe(false);
  });
});
