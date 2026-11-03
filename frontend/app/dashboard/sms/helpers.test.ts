import { describe, expect, it } from "vitest";
import {
  campaignStatusLabel,
  canDeleteCampaign,
  canDeleteTemplateRequest,
  canRescheduleCampaign,
  estimateLine,
  fromLocalInput,
  otpActionLabel,
  toLocalInput,
  campaignNeedsUpdates,
  previewKey,
  clampRange,
  countVars,
  defaultRange,
  formatIst,
  groupExcluded,
  isVariableMapComplete,
  maxToFor,
  splitTemplate,
  statusLabel,
  statusTone,
  balanceLevel,
  formatRupees,
  formatSignedSms,
  parseOtpSettings,
  sendBlock,
  setupComplete,
  setupSteps,
  walletCsv,
} from "./helpers";
import type { SmsWalletItem } from "@/lib/api";

describe("statusLabel", () => {
  it("uses the contract wording for every message status", () => {
    expect(statusLabel("queued")).toBe("Waiting");
    expect(statusLabel("sending")).toBe("Sending");
    expect(statusLabel("submitted")).toBe("Sent to operator");
    expect(statusLabel("delivered")).toBe("Delivered");
    expect(statusLabel("failed")).toBe("Failed");
    expect(statusLabel("unknown")).toBe("Checking…");
    expect(statusLabel("skipped")).toBe("Not sent");
    expect(statusLabel("cancelled")).toBe("Cancelled");
  });
  it("passes an unknown status through", () => {
    expect(statusLabel("weird")).toBe("weird");
    expect(statusTone("weird")).toBe("neutral");
  });
  it("labels campaign statuses", () => {
    expect(campaignStatusLabel("scheduled")).toBe("Scheduled");
  });
});

describe("formatIst", () => {
  it("converts UTC to IST", () => {
    expect(formatIst("2026-10-30T08:34:00Z")).toBe("30 Oct, 2:04 pm");
  });
  it("handles empty input", () => {
    expect(formatIst(null)).toBe("—");
  });
});

describe("date ranges", () => {
  it("builds an inclusive default window", () => {
    expect(defaultRange("2026-10-30", 3)).toEqual({ from: "2026-10-28", to: "2026-10-30" });
  });
  it("moves 'to' back when 'from' is edited past the window", () => {
    expect(clampRange({ from: "2026-10-20", to: "2026-10-30" }, "from", 3, "2026-10-30")).toEqual({
      from: "2026-10-20",
      to: "2026-10-22",
    });
  });
  it("moves 'from' forward when 'to' is edited past the window", () => {
    expect(clampRange({ from: "2026-10-20", to: "2026-10-30" }, "to", 3, "2026-10-30")).toEqual({
      from: "2026-10-28",
      to: "2026-10-30",
    });
  });
  it("never reaches into the future", () => {
    expect(clampRange({ from: "2026-10-29", to: "2026-11-05" }, "to", 3, "2026-10-30").to).toBe("2026-10-30");
    expect(maxToFor("2026-10-29", 3, "2026-10-30")).toBe("2026-10-30");
    expect(maxToFor("2026-10-01", 3, "2026-10-30")).toBe("2026-10-03");
  });
  it("fixes an inverted range", () => {
    expect(clampRange({ from: "2026-10-25", to: "2026-10-20" }, "from", 30, "2026-10-30")).toEqual({
      from: "2026-10-25",
      to: "2026-10-25",
    });
  });
});

describe("template variables", () => {
  const msg = "Hi {#var#}, your visit is on {#var#}. Call us.";
  it("splits wording into text and numbered slots", () => {
    expect(splitTemplate(msg)).toEqual([
      { kind: "text", text: "Hi " },
      { kind: "var", index: 0 },
      { kind: "text", text: ", your visit is on " },
      { kind: "var", index: 1 },
      { kind: "text", text: ". Call us." },
    ]);
    expect(countVars(msg)).toBe(2);
    expect(countVars("No variables")).toBe(0);
  });
  it("needs every slot filled", () => {
    expect(isVariableMapComplete([{ source: "field", value: "name" }, null], 2)).toBe(false);
    expect(isVariableMapComplete([{ source: "field", value: "name" }, { source: "text", value: " " }], 2)).toBe(false);
    expect(isVariableMapComplete([{ source: "field", value: "name" }, { source: "text", value: "2 Nov" }], 2)).toBe(true);
    expect(isVariableMapComplete([], 0)).toBe(true);
  });
});

describe("groupExcluded", () => {
  it("groups by reason, biggest first", () => {
    const grouped = groupExcluded([
      { lead_id: "1", name: "A", phone: "1", reason: "Opted out" },
      { lead_id: "2", name: "B", phone: "2", reason: "Duplicate number" },
      { lead_id: "3", name: "C", phone: "3", reason: "Duplicate number" },
    ]);
    expect(grouped.map((g) => [g.reason, g.leads.length])).toEqual([
      ["Duplicate number", 2],
      ["Opted out", 1],
    ]);
  });
});

describe("delivery updates", () => {
  it("keeps checking completed campaigns with submitted or unknown messages", () => {
    expect(campaignNeedsUpdates({ status: "completed", counts: { submitted: 2 } })).toBe(true);
    expect(campaignNeedsUpdates({ status: "completed", counts: { unknown: 1 } })).toBe(true);
    expect(campaignNeedsUpdates({ status: "completed", counts: { delivered: 2 } })).toBe(false);
    expect(campaignNeedsUpdates({ status: "scheduled", counts: {} })).toBe(true);
  });
});

describe("preview snapshot", () => {
  const template = { id: "t", message: "Hi {#var#}", template_type: "service" };
  const map = [{ source: "text" as const, value: "Sam" }];
  it("invalidates when recipients, wording, type or mapped values change", () => {
    const key = previewKey(template, map, new Set(["a"]));
    expect(previewKey(template, map, new Set(["b"]))).not.toBe(key);
    expect(previewKey({ ...template, message: "Hello" }, map, new Set(["a"]))).not.toBe(key);
    expect(previewKey({ ...template, template_type: "promotional" }, map, new Set(["a"]))).not.toBe(key);
    expect(previewKey(template, [{ source: "text", value: "Lee" }], new Set(["a"]))).not.toBe(key);
  });
  it("treats recipient order as the same snapshot", () => {
    expect(previewKey(template, map, new Set(["a", "b"]))).toBe(previewKey(template, map, new Set(["b", "a"])));
  });
});

describe("balanceLevel", () => {
  it("flags empty, low and ok", () => {
    expect(balanceLevel(0)).toBe("empty");
    expect(balanceLevel(null)).toBe("empty");
    expect(balanceLevel(499)).toBe("low");
    expect(balanceLevel(500)).toBe("ok");
  });
});

describe("formatRupees / formatSignedSms", () => {
  it("groups in en-IN with 2 decimals", () => {
    expect(formatRupees(1234567.5)).toBe("₹12,34,567.50");
    expect(formatRupees(0)).toBe("₹0.00");
  });
  it("signs SMS counts", () => {
    expect(formatSignedSms(1000)).toBe("+1,000");
    expect(formatSignedSms(-2140)).toBe("\u22122,140");
    expect(formatSignedSms(0)).toBe("0");
  });
});

describe("sendBlock", () => {
  const base = { loading: false, peTm: true, balance: 1000, needed: 200, support: null };
  it("allows a send when PE-TM is confirmed and balance covers it", () => {
    expect(sendBlock(base)).toEqual({ blocked: false, reason: null });
    expect(sendBlock({ ...base, balance: 200 }).blocked).toBe(false);
  });
  it("blocks silently while loading", () => {
    expect(sendBlock({ ...base, loading: true })).toEqual({ blocked: true, reason: null });
  });
  it("explains a missing PE-TM binding first", () => {
    expect(sendBlock({ ...base, peTm: false, balance: 0 }).reason).toBe("Waiting for your account manager to confirm PE–TM binding.");
  });
  it("explains an unknown balance", () => {
    expect(sendBlock({ ...base, balance: undefined }).reason).toBe("Couldn't check your SMS balance. Refresh and try again.");
  });
  it("explains too little balance with both numbers and the support contact", () => {
    expect(sendBlock({ ...base, balance: 320, needed: 2140, support: "98400 12345" }).reason).toBe(
      "Not enough SMS balance: this campaign needs 2,140 SMS and you have 320. Contact 98400 12345 to top up.",
    );
    expect(sendBlock({ ...base, balance: 5, needed: 6 }).reason).toContain("Contact your Anril account manager to top up.");
  });
});

describe("setupSteps", () => {
  it("is incomplete until templates, PE-TM and balance are all done", () => {
    const steps = setupSteps({ templatesReady: false, peTm: false, smsCount: 0 });
    expect(steps.map((x) => x.done)).toEqual([true, false, false, false]);
    expect(setupComplete(steps)).toBe(false);
    expect(setupComplete(setupSteps({ templatesReady: true, peTm: true, smsCount: 10 }))).toBe(true);
  });
  it("shows the balance as a hint once known", () => {
    expect(setupSteps({ templatesReady: true, peTm: true, smsCount: 1500 })[3].hint).toBe("1,500 SMS");
    expect(setupSteps({ templatesReady: true, peTm: true, smsCount: undefined })[3]).toMatchObject({ done: false, hint: null });
  });
});

describe("walletCsv", () => {
  const item = (over: Partial<SmsWalletItem>): SmsWalletItem => ({
    kind: "topup", sms: 1000, amount: 250, label: "Top-up", campaign_id: null, at: "2026-10-30T08:34:00Z", balance_after: 1500, ...over,
  });
  it("writes a header and IST dates", () => {
    expect(walletCsv([item({})])).toBe("Date,Type,Description,SMS,Amount\r\n2026-10-30 14:04,Top-up,Top-up,1000,250.00");
  });
  it("keeps negative usage, blank amounts and quotes commas", () => {
    const csv = walletCsv([item({ kind: "campaign", sms: -2140, amount: null, label: 'Diwali, "big" sale' })]);
    expect(csv.split("\r\n")[1]).toBe('2026-10-30 14:04,Campaign,"Diwali, ""big"" sale",-2140,');
  });
  it("defuses spreadsheet formulas in labels", () => {
    expect(walletCsv([item({ label: "=HYPERLINK(1)" })])).toContain(",'=HYPERLINK(1),");
  });
  it("is just the header with no items", () => {
    expect(walletCsv([])).toBe("Date,Type,Description,SMS,Amount");
  });
});

describe("parseOtpSettings", () => {
  it("accepts the defaults and trims the extra values", () => {
    expect(parseOtpSettings({ length: "6", expiry: "15", extra: "  a|b " })).toEqual({ error: null, length: 6, expiry: 15, extra: "a|b" });
    expect(parseOtpSettings({ length: "6", expiry: "15", extra: "" })).toMatchObject({ extra: undefined });
  });
  it("accepts the range edges", () => {
    expect(parseOtpSettings({ length: "4", expiry: "1", extra: "" }).error).toBeNull();
    expect(parseOtpSettings({ length: "10", expiry: "10080", extra: "x".repeat(200) }).error).toBeNull();
  });
  it("rejects out-of-range, fractional and empty numbers", () => {
    expect(parseOtpSettings({ length: "3", expiry: "15", extra: "" }).error).toMatch(/OTP length/);
    expect(parseOtpSettings({ length: "11", expiry: "15", extra: "" }).error).toMatch(/OTP length/);
    expect(parseOtpSettings({ length: "6", expiry: "0", extra: "" }).error).toMatch(/Expiry/);
    expect(parseOtpSettings({ length: "6", expiry: "10081", extra: "" }).error).toMatch(/Expiry/);
    expect(parseOtpSettings({ length: "6.5", expiry: "15", extra: "" }).error).toMatch(/OTP length/);
    expect(parseOtpSettings({ length: "", expiry: "15", extra: "" }).error).toMatch(/OTP length/);
  });
  it("rejects extra values over 200 characters", () => {
    expect(parseOtpSettings({ length: "6", expiry: "15", extra: "x".repeat(201) }).error).toMatch(/200/);
  });
});

describe("estimateLine", () => {
  it("shows the rupee estimate and rate when known", () => {
    const e = estimateLine({ rate_per_sms: 0.18, estimated_amount: 1800 });
    expect(e.known).toBe(true);
    expect(e.text).toBe("≈ ₹1,800.00 (about ₹0.18 per SMS, based on your recent charges)");
  });
  it("shows the muted line when either value is null", () => {
    expect(estimateLine({ rate_per_sms: null, estimated_amount: null })).toEqual({ text: "Cost shows after your first SMS is charged", known: false });
    expect(estimateLine({ rate_per_sms: 0.2, estimated_amount: null }).known).toBe(false);
  });
});

describe("status gates", () => {
  it("only a scheduled campaign can be rescheduled", () => {
    expect(canRescheduleCampaign("scheduled")).toBe(true);
    expect(["sending", "completed", "cancelled"].some(canRescheduleCampaign)).toBe(false);
  });
  it("only completed or cancelled campaigns can be deleted", () => {
    expect(canDeleteCampaign("completed")).toBe(true);
    expect(canDeleteCampaign("cancelled")).toBe(true);
    expect(canDeleteCampaign("scheduled")).toBe(false);
    expect(canDeleteCampaign("sending")).toBe(false);
  });
  it("only requested or rejected template requests can be deleted", () => {
    expect(canDeleteTemplateRequest("requested")).toBe(true);
    expect(canDeleteTemplateRequest("rejected")).toBe(true);
    expect(canDeleteTemplateRequest("in_progress")).toBe(false);
    expect(canDeleteTemplateRequest("ready")).toBe(false);
  });
});

describe("datetime-local conversion", () => {
  it("round-trips an instant at minute precision", () => {
    const iso = "2026-11-10T08:30:00.000Z";
    expect(fromLocalInput(toLocalInput(iso))).toBe(iso);
  });
  it("returns empty / null for empty or invalid input", () => {
    expect(toLocalInput(null)).toBe("");
    expect(toLocalInput("nope")).toBe("");
    expect(fromLocalInput("")).toBeNull();
    expect(fromLocalInput("nope")).toBeNull();
  });
  it("produces an ISO string with a timezone designator", () => {
    expect(fromLocalInput("2026-11-10T14:00")).toMatch(/Z$/);
  });
});

describe("otpActionLabel", () => {
  it("maps actions to plain words", () => {
    expect(otpActionLabel("send")).toBe("Sent");
    expect(otpActionLabel("resend")).toBe("Resent");
    expect(otpActionLabel("verify")).toBe("Checked");
    expect(otpActionLabel("other")).toBe("other");
  });
});
