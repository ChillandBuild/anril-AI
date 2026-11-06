import { describe, expect, it } from "vitest";
import type { SmsCampaign, SmsMessage, SmsStatus, SmsWalletItem } from "@/lib/api";
import {
  attentionItems, checklistRows, failureSummary, monthSpend, outcomeLine, setupProgress, recentCampaigns, summarize, upcomingCampaigns,
} from "./DashboardCards";

const status = (over: Partial<SmsStatus> = {}): SmsStatus => ({
  enabled: true,
  connected: true,
  support_contact: null,
  templates_ready: false,
  ...over,
});

describe("checklistRows", () => {
  it("is all not-done for a brand new account", () => {
    const rows = checklistRows({ status: status(), dlt: null, balance: { sms_count: 0, wallet: 0 } });
    expect(rows.map((r) => r.done)).toEqual([false, false, false, false]);
    expect(rows[3].href).toBeNull();
  });
  it("links each step to the screen where it is done", () => {
    const hrefs = checklistRows({ status: status(), dlt: null, balance: null }).map((r) => r.href);
    expect(hrefs).toEqual([
      "/dashboard/sms/setup?sub=entities",
      "/dashboard/sms/setup?sub=senders",
      "/dashboard/sms/setup?sub=templates",
      null,
    ]);
  });
  it("counts a submitted entity and an approved sender from the DLT list", () => {
    const dlt = {
      entities: [{ entity_id: "E1", entity_name: null, status: "submitted" as const, at: null }],
      senders: [{ sender_id: "ANRIL", entity_id: "E1", entity_name: null, status: "approved" as const, at: null }],
      error: null,
    };
    const rows = checklistRows({ status: status(), dlt, balance: null });
    expect(rows[0].done).toBe(true);
    expect(rows[1].done).toBe(true);
  });
  it("ignores a submitted-only sender", () => {
    const dlt = { entities: [], senders: [{ sender_id: "A", entity_id: "E", entity_name: null, status: "submitted" as const, at: null }], error: null };
    expect(checklistRows({ status: status(), dlt, balance: null })[1].done).toBe(false);
  });
  it("has four steps and no PE-TM binding step", () => {
    const rows = checklistRows({ status: status(), dlt: null, balance: null });
    expect(rows.map((r) => r.key)).toEqual(["entity", "sender", "template", "balance"]);
  });
  it("marks everything done when the account is ready", () => {
    const dlt = {
      entities: [{ entity_id: "E1", entity_name: null, status: "approved" as const, at: null }],
      senders: [{ sender_id: "ANRIL", entity_id: "E1", entity_name: null, status: "approved" as const, at: null }],
      error: null,
    };
    const rows = checklistRows({ status: status({ templates_ready: true }), dlt, balance: { sms_count: 10, wallet: 1 } });
    expect(rows.every((r) => r.done)).toBe(true);
  });
});

describe("summarize", () => {
  it("matches the plan example", () => {
    expect(summarize({ delivered: 4102, failed: 46, submitted: 62 })).toEqual({ sent: 4210, delivered: 4102, failed: 46, pct: 97 });
  });
  it("ignores waiting, skipped and cancelled; handles empty", () => {
    expect(summarize({ queued: 5, skipped: 2, cancelled: 1 }).sent).toBe(0);
    expect(summarize(undefined).pct).toBeNull();
  });
});

const item = (over: Partial<SmsWalletItem>): SmsWalletItem => ({
  kind: "campaign", sms: -10, amount: 2, label: "x", campaign_id: null, at: "2026-11-02T10:00:00Z", balance_after: null, ...over,
});

describe("monthSpend", () => {
  const now = new Date("2026-11-03T08:00:00Z");
  it("sums only campaign spend in the current IST month", () => {
    const items = [item({ amount: 2.5 }), item({ amount: 1 }), item({ amount: 9, at: "2026-10-20T10:00:00Z" }), item({ kind: "topup", sms: 100, amount: null })];
    expect(monthSpend(items, now, 200)).toEqual({ total: 3.5, partial: false });
  });
  it("uses the IST month, not UTC (31 Oct 20:00 UTC is 1 Nov IST)", () => {
    expect(monthSpend([item({ amount: 4, at: "2026-10-31T20:00:00Z" })], now, 200).total).toBe(4);
  });
  it("flags partial when the history is cut inside this month", () => {
    expect(monthSpend([item({}), item({})], now, 2).partial).toBe(true);
    expect(monthSpend([item({}), item({ at: "2026-10-01T00:00:00Z" })], now, 2).partial).toBe(false);
  });
});

const camp = (id: string, status: SmsCampaign["status"], created_at: string, send_at: string | null = null): SmsCampaign =>
  ({ id, name: id, status, created_at, send_at, total: 1 }) as SmsCampaign;

describe("campaign lists", () => {
  const list = [
    camp("a", "scheduled", "2026-11-01T00:00:00Z", "2026-11-05T00:00:00Z"),
    camp("b", "scheduled", "2026-11-01T00:00:00Z", "2026-11-04T00:00:00Z"),
    camp("c", "completed", "2026-11-02T00:00:00Z"),
    camp("d", "cancelled", "2026-11-03T00:00:00Z"),
  ];
  it("upcoming is scheduled only, soonest first", () => {
    expect(upcomingCampaigns(list).map((c) => c.id)).toEqual(["b", "a"]);
  });
  it("recent excludes scheduled, newest first, capped", () => {
    expect(recentCampaigns(list).map((c) => c.id)).toEqual(["d", "c"]);
    expect(recentCampaigns(list, 1)).toHaveLength(1);
  });
});

describe("setupProgress", () => {
  const row = (key: string, done: boolean) => ({ key, label: `Do ${key}`, done, href: null, hint: "" });
  it("counts done steps and names the first one left", () => {
    expect(setupProgress([row("a", true), row("b", false), row("c", false)])).toEqual({ done: 1, total: 3, next: "Do b" });
  });
  it("has no next step when everything is done", () => {
    expect(setupProgress([row("a", true)])).toEqual({ done: 1, total: 1, next: null });
  });
});

describe("outcomeLine", () => {
  const counts = (c: Record<string, number>) => ({ queued: 0, sending: 0, submitted: 0, delivered: 0, failed: 0, unknown: 0, skipped: 0, cancelled: 0, ...c }) as SmsCampaign["counts"];
  it("lists only the parts that are there", () => {
    expect(outcomeLine(counts({ delivered: 1 }))).toBe("1 delivered");
    expect(outcomeLine(counts({ delivered: 2, failed: 1, submitted: 3, queued: 1 }))).toBe("2 delivered · 1 failed · 4 waiting");
    expect(outcomeLine(counts({}))).toBe("");
  });
});

describe("failureSummary", () => {
  const msg = (over: Partial<SmsMessage>): SmsMessage => ({
    id: "m", campaign_id: "c1", lead_id: null, lead_name: null, phone: "", content: "", status: "failed",
    failure_reason: "CTA_URL_NOT_MATCHED", sms_count: 1, submitted_at: "2026-11-04T17:17:09Z", delivered_at: null, updated_at: null, ...over,
  });
  it("groups failures by plain-English reason, most common first, and remembers each send's reason", () => {
    const s = failureSummary([
      msg({ id: "1", campaign_id: "a", submitted_at: "2026-11-04T17:19:09Z" }),
      msg({ id: "2", campaign_id: "b" }),
      msg({ id: "3", campaign_id: "c", failure_reason: "NDNC" }),
    ]);
    expect(s.groups[0]).toMatchObject({ text: "Blocked: the link isn't whitelisted on your DLT portal", count: 2, sends: 2, lastAt: "2026-11-04T17:19:09Z", href: "/dashboard/sms/setup?sub=templates" });
    expect(s.groups).toHaveLength(2);
    expect(s.byCampaign.get("a")).toBe("Blocked: the link isn't whitelisted on your DLT portal");
  });
  it("a failure with no reason is grouped as unknown and points at the report", () => {
    const s = failureSummary([msg({ failure_reason: null })]);
    expect(s.groups[0]).toMatchObject({ text: "No reason given by the operator", href: "/dashboard/sms/reports" });
  });
});

describe("attentionItems", () => {
  const groups = failureSummary([]).groups;
  it("is empty when nothing is wrong, so the card hides", () => {
    expect(attentionItems({ groups, smsLeft: 5000 })).toEqual([]);
  });
  it("flags a low or empty wallet", () => {
    expect(attentionItems({ groups, smsLeft: 496 })[0]).toMatchObject({ key: "wallet", tone: "warn" });
    expect(attentionItems({ groups, smsLeft: 0 })[0]).toMatchObject({ key: "wallet", tone: "danger" });
  });
  it("puts failures before the wallet", () => {
    const g = failureSummary([{ id: "1", campaign_id: "a", lead_id: null, lead_name: null, phone: "", content: "", status: "failed", failure_reason: "CTA_URL_NOT_MATCHED", sms_count: 1, submitted_at: null, delivered_at: null, updated_at: null }]).groups;
    expect(attentionItems({ groups: g, smsLeft: 496 }).map((i) => i.key)).toEqual(["fail:Blocked: the link isn't whitelisted on your DLT portal", "wallet"]);
  });
});
