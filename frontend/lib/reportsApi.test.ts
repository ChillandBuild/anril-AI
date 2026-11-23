import { describe, expect, it } from "vitest";
import type { NavAccess } from "@/components/nav/navSections";
import {
  cleanChart, deltaOf, formatRupees, formatSeconds, formatValue, humanizeKey, lowerIsBetter, metricKind,
  monthLabel, monthRange, peopleMetricFor, previousMonth, rangeDates, reportQuery, resolveTab, safeLinks, visibleTabs,
} from "./reportsApi";

const NOW = new Date("2026-11-23T06:00:00Z"); // 11:30 in India

function access(over: Partial<NavAccess> & { perms?: string[] } = {}): NavAccess {
  const perms = over.perms ?? [];
  return {
    isSubscribed: true, messagingOn: true, inboundOn: true, outboundOn: true, smsOn: false,
    canServices: false, canSettings: false, brainGate: false, telecallingVisible: false, telecallingPages: [],
    can: (p) => perms.includes(p), canAny: (ps) => ps.some((p) => perms.includes(p)),
    ...over,
  };
}

describe("resolveTab", () => {
  it("opens Overview for nothing or something unknown", () => {
    expect(resolveTab(null)).toBe("overview");
    expect(resolveTab("nope")).toBe("overview");
  });
  it("keeps the new keys", () => {
    for (const t of ["overview", "money", "customers", "ads", "team", "items", "campaigns", "ask"]) expect(resolveTab(t)).toBe(t);
  });
  it("keeps the old keys working", () => {
    expect(resolveTab("templates")).toBe("campaigns");
    expect(resolveTab("inbound")).toBe("customers");
    expect(resolveTab("channels")).toBe("team");
  });
});

describe("visibleTabs", () => {
  it("shows only the always-on tabs with no extra access", () => {
    expect(visibleTabs(access())).toEqual(["overview", "customers", "team", "ask"]);
  });
  it("Money and Items follow the orders menu item", () => {
    expect(visibleTabs(access({ perms: ["deals.view"] }))).toEqual(["overview", "money", "customers", "team", "items", "ask"]);
  });
  it("Money goes away when the server hides money", () => {
    expect(visibleTabs(access({ perms: ["deals.view"] }), true)).not.toContain("money");
  });
  it("Ads need Meta Ads access and inbound; Campaigns need Reach and outbound", () => {
    const a = access({ perms: ["meta_ads.view", "outbound_leads.view"] });
    expect(visibleTabs(a)).toEqual(["overview", "customers", "ads", "team", "campaigns", "ask"]);
    expect(visibleTabs({ ...a, inboundOn: false, outboundOn: false })).toEqual(["overview", "customers", "team", "ask"]);
  });
  it("shows nothing gated without a subscription", () => {
    expect(visibleTabs(access({ isSubscribed: false, perms: ["deals.view", "meta_ads.view", "outbound_leads.view"] }))).toEqual(["overview", "customers", "team", "ask"]);
  });
});

describe("dates", () => {
  it("7 days ends today and starts 6 days before (India time)", () => {
    expect(rangeDates({ preset: "last_7d", start: "", end: "" }, NOW)).toEqual({ from: "2026-11-17", to: "2026-11-23" });
  });
  it("today, yesterday, 14 and 30 days", () => {
    expect(rangeDates({ preset: "today", start: "", end: "" }, NOW)).toEqual({ from: "2026-11-23", to: "2026-11-23" });
    expect(rangeDates({ preset: "yesterday", start: "", end: "" }, NOW)).toEqual({ from: "2026-11-22", to: "2026-11-22" });
    expect(rangeDates({ preset: "last_14d", start: "", end: "" }, NOW)?.from).toBe("2026-11-10");
    expect(rangeDates({ preset: "last_30d", start: "", end: "" }, NOW)?.from).toBe("2026-10-25");
  });
  it("uses the India day even late in the UTC evening", () => {
    expect(rangeDates({ preset: "today", start: "", end: "" }, new Date("2026-11-23T19:00:00Z"))?.to).toBe("2026-11-24");
  });
  it("custom needs both dates in order", () => {
    expect(rangeDates({ preset: "custom", start: "", end: "" })).toBeNull();
    expect(rangeDates({ preset: "custom", start: "2026-11-05", end: "2026-11-01" })).toBeNull();
    expect(rangeDates({ preset: "custom", start: "2026-11-01", end: "2026-11-05" })).toEqual({ from: "2026-11-01", to: "2026-11-05" });
  });
  it("monthRange covers a whole month, including a leap February", () => {
    expect(monthRange("2026-10")).toEqual({ preset: "custom", start: "2026-10-01", end: "2026-10-31" });
    expect(monthRange("2028-02")?.end).toBe("2028-02-29");
    expect(monthRange("2026-13")).toBeNull();
    expect(monthRange(null)).toBeNull();
  });
  it("previousMonth and labels", () => {
    expect(previousMonth(NOW)).toBe("2026-10");
    expect(previousMonth(new Date("2026-01-10T06:00:00Z"))).toBe("2025-12");
    expect(monthLabel("2026-10")).toBe("October 2026");
  });
  it("reportQuery builds from, to and compare, or null for an unfinished range", () => {
    expect(reportQuery({ preset: "last_7d", start: "", end: "" }, "previous", {}, NOW)).toBe("from=2026-11-17&to=2026-11-23&compare=previous");
    expect(reportQuery({ preset: "custom", start: "", end: "" }, "off")).toBeNull();
  });
});

describe("formatting", () => {
  it("rupees come from paise, Indian grouping", () => {
    expect(formatRupees(1840000)).toBe("₹18,400");
    expect(formatRupees(12345)).toBe("₹123.45");
    expect(formatRupees(null)).toBe("—");
    expect(formatRupees(-5000)).toBe("-₹50");
  });
  it("seconds", () => {
    expect(formatSeconds(45)).toBe("45s");
    expect(formatSeconds(300)).toBe("5 min");
    expect(formatSeconds(3600)).toBe("1h");
    expect(formatSeconds(5400)).toBe("1h 30m");
    expect(formatSeconds(undefined)).toBe("—");
  });
  it("guesses the kind of a number from its key", () => {
    expect(metricKind("sales_paise")).toBe("paise");
    expect(metricKind("p50_seconds")).toBe("seconds");
    expect(metricKind("answered_pct")).toBe("percent");
    expect(metricKind("hot")).toBe("count");
    expect(formatValue(42, "percent")).toBe("42%");
    expect(formatValue(1.234, "ratio")).toBe("₹1.23");
  });
  it("makes plain names", () => {
    expect(humanizeKey("first_chats")).toBe("First chats");
    expect(humanizeKey("still_to_collect_paise")).toBe("Still to collect");
  });
});

describe("deltaOf", () => {
  it("a rise is good for most numbers and bad for costs", () => {
    expect(deltaOf(120, 100)).toEqual({ pct: 20, dir: "up", good: true });
    expect(deltaOf(120, 100, lowerIsBetter("cost_per_chat_paise"))).toEqual({ pct: 20, dir: "up", good: false });
  });
  it("no percent when before was zero, nothing when equal or missing", () => {
    expect(deltaOf(5, 0).pct).toBeNull();
    expect(deltaOf(5, 5)).toEqual({ pct: 0, dir: "same", good: null });
    expect(deltaOf(5, null).good).toBeNull();
  });
  it("lowerIsBetter spots costs and waits, not sales", () => {
    expect(lowerIsBetter("refunds_paise")).toBe(true);
    expect(lowerIsBetter("p50_seconds")).toBe(true);
    expect(lowerIsBetter("sales_paise")).toBe(false);
  });
});

describe("people keys", () => {
  it("maps number keys to the people list", () => {
    expect(peopleMetricFor("first_chats")).toBe("new_chats");
    expect(peopleMetricFor("repeat_buyers")).toBe("repeat");
    expect(peopleMetricFor("sales_paise")).toBeNull();
  });
});

describe("ask answers", () => {
  it("keeps a chart only when it can be drawn", () => {
    expect(cleanChart(null)).toBeNull();
    expect(cleanChart({ kind: "bar", labels: [], values: [] })).toBeNull();
    expect(cleanChart({ kind: "bar", labels: ["a", "b", "c"], values: [1, 2] })).toEqual({ kind: "bar", labels: ["a", "b"], values: [1, 2] });
    expect(cleanChart({ kind: "line", labels: ["a"], values: [Number.NaN] })?.values).toEqual([0]);
  });
  it("keeps only links that stay inside the app", () => {
    const out = safeLinks([
      { label: "Orders", href: "/dashboard/deals?stage=won" },
      { label: "Bad", href: "https://evil.example" },
      { label: "Sneaky", href: "//evil.example" },
    ]);
    expect(out.map((l) => l.label)).toEqual(["Orders"]);
    expect(safeLinks(undefined)).toEqual([]);
  });
});
