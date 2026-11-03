import { describe, expect, it } from "vitest";
import {
  UNICODE_NOTE,
  creditAmountError,
  requestedOn,
  buildCurl,
  buildPython,
  EMPTY_NUMBERS,
  EMPTY_OWN,
  OWN_VAR_ERROR,
  buildRecipients,
  buildSendRequest,
  defaultSendName,
  excelSummary,
  numbersReady,
  sendFormProblem,
  withNumbersChange,
  pruneVarMap,
  nextIdempotencyKey,
  isValidEntityId,
  isValidDltTemplateId,
  isValidOwnSenderId,
  parseContactsSub,
  type SendFormInput,
  canCancelCampaign,
  maskKey,
  otpDelivery,
  parseNumbers,
  skippedRowsCsv,
  smsCounterLine,
  smsSegments,
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

describe("smsSegments", () => {
  it("counts plain GSM-7 text as 160 for one part, 153 per part after", () => {
    expect(smsSegments("a".repeat(160))).toEqual({ length: 160, parts: 1, unicode: false });
    expect(smsSegments("a".repeat(161))).toEqual({ length: 161, parts: 2, unicode: false });
    expect(smsSegments("a".repeat(306))).toEqual({ length: 306, parts: 2, unicode: false });
    expect(smsSegments("a".repeat(307))).toEqual({ length: 307, parts: 3, unicode: false });
  });

  it("counts GSM extension characters as 2", () => {
    expect(smsSegments("{}[]")).toEqual({ length: 8, parts: 1, unicode: false });
    expect(smsSegments("€".repeat(80))).toEqual({ length: 160, parts: 1, unicode: false });
    expect(smsSegments("€".repeat(81))).toEqual({ length: 162, parts: 2, unicode: false });
    expect(smsSegments("a\\b|~^").length).toBe(1 + 2 + 1 + 2 + 2 + 2);
  });

  it("switches to Unicode (70 / 67) for any non-GSM character", () => {
    expect(smsSegments("வணக்கம்")).toMatchObject({ unicode: true, parts: 1 });
    expect(smsSegments("a".repeat(70) + "ø".repeat(0) + "é")).toMatchObject({ unicode: false });
    expect(smsSegments("த" + "a".repeat(69))).toEqual({ length: 70, parts: 1, unicode: true });
    expect(smsSegments("த" + "a".repeat(70))).toEqual({ length: 71, parts: 2, unicode: true });
    expect(smsSegments("த" + "a".repeat(133))).toEqual({ length: 134, parts: 2, unicode: true });
    expect(smsSegments("த" + "a".repeat(134))).toEqual({ length: 135, parts: 3, unicode: true });
  });

  it("counts an emoji as two characters, like the backend", () => {
    expect(smsSegments("😀")).toEqual({ length: 2, parts: 1, unicode: true });
  });

  it("matches the backend for an empty message (one part)", () => {
    expect(smsSegments("")).toEqual({ length: 0, parts: 1, unicode: false });
  });
});

describe("smsCounterLine", () => {
  it("shows characters and SMS", () => {
    expect(smsCounterLine("")).toBe("0 characters · 0 SMS");
    expect(smsCounterLine("a")).toBe("1 character · 1 SMS");
    expect(smsCounterLine("a".repeat(161))).toBe("161 characters · 2 SMS");
  });
  it("has the Unicode note wording", () => {
    expect(UNICODE_NOTE).toBe("Unicode message (e.g. Tamil or emoji): 70 characters per SMS");
  });
});

describe("preparing campaigns", () => {
  it("labels preparing and keeps polling it", () => {
    expect(campaignStatusLabel("preparing")).toBe("Preparing…");
    expect(campaignNeedsUpdates({ status: "preparing", counts: {} })).toBe(true);
  });
  it("can be cancelled but not rescheduled or deleted", () => {
    expect(canCancelCampaign("preparing")).toBe(true);
    expect(canCancelCampaign("scheduled")).toBe(true);
    expect(canCancelCampaign("sending")).toBe(false);
    expect(canRescheduleCampaign("preparing")).toBe(false);
    expect(canDeleteCampaign("preparing")).toBe(false);
  });
});

describe("otpDelivery", () => {
  it("maps the delivery report", () => {
    expect(otpDelivery("delivered")).toEqual({ label: "Delivered", tone: "success" });
    expect(otpDelivery("failed")).toEqual({ label: "Failed", tone: "danger" });
    expect(otpDelivery(null)).toEqual({ label: "—", tone: null });
  });
});

describe("recipients", () => {
  const n = (patch: Partial<typeof EMPTY_NUMBERS>) => ({ ...EMPTY_NUMBERS, ...patch });
  it("needs a group, a lead or a number depending on the mode", () => {
    expect(numbersReady(n({ mode: "list" }), false)).toBe(false);
    expect(numbersReady(n({ mode: "list", groupIds: ["g1"] }), false)).toBe(true);
    expect(numbersReady(n({ mode: "leads", leadIds: ["l1"] }), false)).toBe(true);
    expect(numbersReady(n({ mode: "contact", numbersText: "9876543210" }), false)).toBe(true);
  });
  it("blocks promotional Contact and Excel numbers until consent is ticked", () => {
    const c = n({ mode: "contact", numbersText: "9876543210\n9123456780" });
    expect(numbersReady(c, true)).toBe(false);
    expect(numbersReady({ ...c, consent: true }, true)).toBe(true);
    const x = n({ mode: "excel", excelNumbers: ["9876543210"] });
    expect(numbersReady(x, true)).toBe(false);
    expect(numbersReady({ ...x, consent: true }, true)).toBe(true);
  });
  it("does not ask for consent on a List (contacts carry their own)", () => {
    expect(numbersReady(n({ mode: "list", groupIds: ["g1"] }), true)).toBe(true);
  });
  it("rejects more than 5,000 numbers and more than 50 groups", () => {
    const text = Array.from({ length: 5001 }, (_, i) => String(9000000000 + i)).join("\n");
    expect(numbersReady(n({ mode: "contact", numbersText: text }), false)).toBe(false);
    expect(numbersReady(n({ mode: "list", groupIds: Array.from({ length: 51 }, (_, i) => `g${i}`) }), false)).toBe(false);
  });
  it("splits pasted numbers on lines, commas and spaces", () => {
    expect(parseNumbers("9876543210, 9123456780\n\n 9000000000;")).toEqual(["9876543210", "9123456780", "9000000000"]);
  });
  it("builds the request fields per source", () => {
    expect(buildRecipients(n({ mode: "list", groupIds: ["g1"] }), false)).toEqual({ source: "contacts", group_ids: ["g1"] });
    expect(buildRecipients(n({ mode: "leads", leadIds: ["l1"] }), false)).toEqual({ source: "leads", lead_ids: ["l1"] });
    expect(buildRecipients(n({ mode: "contact", numbersText: "9876543210", consent: true }), true)).toEqual({
      source: "numbers",
      numbers: ["9876543210"],
      consent_confirmed: true,
    });
    expect(buildRecipients(n({ mode: "contact", numbersText: "9876543210" }), false)).toEqual({ source: "numbers", numbers: ["9876543210"] });
  });
});

describe("send form request", () => {
  const tpl = { id: "t1", message: "Hi {#var#}, 20% off", template_type: "promotional" as const, var_count: 1 };
  const nameVar = { source: "field" as const, value: "name" };
  const own = { ...EMPTY_OWN, sender_id: "ANRILT", entity_id: "110100", dlt_template_id: "110700", message: "Your order shipped", template_type: "service" as const };
  const base: SendFormInput = { route: null, template: null, varMap: [], own: EMPTY_OWN, numbers: EMPTY_NUMBERS };

  it("sends a picked template through the approved-template route", () => {
    const input: SendFormInput = {
      ...base,
      route: "template",
      template: tpl,
      varMap: [nameVar],
      numbers: { ...EMPTY_NUMBERS, mode: "list", groupIds: ["g1"] },
    };
    expect(buildSendRequest(input)).toEqual({ kind: "template", template_id: "t1", variable_map: [nameVar], source: "contacts", group_ids: ["g1"] });
  });
  it("sends Type my own through the manual (DLT IDs) route", () => {
    const input: SendFormInput = { ...base, route: "own", own: { ...own, sender_id: " ANRILT " }, numbers: { ...EMPTY_NUMBERS, numbersText: "9876543210" } };
    expect(buildSendRequest(input)).toEqual({
      kind: "manual",
      manual: { sender_id: "ANRILT", entity_id: "110100", dlt_template_id: "110700", template_type: "service", message: "Your order shipped" },
      source: "numbers",
      numbers: ["9876543210"],
    });
  });
  it("sends Excel numbers exactly like pasted ones", () => {
    const pasted = { ...base, route: "own" as const, own, numbers: { ...EMPTY_NUMBERS, mode: "contact" as const, numbersText: "9876543210\n9123456780" } };
    const excel = { ...pasted, numbers: { ...EMPTY_NUMBERS, mode: "excel" as const, excelNumbers: ["9876543210", "9123456780"] } };
    expect(buildSendRequest(excel)).toEqual(buildSendRequest(pasted));
    expect(buildSendRequest(excel)).not.toBeNull();
  });
  it("rejects {#var#} in Type my own", () => {
    const input: SendFormInput = { ...base, route: "own", own: { ...own, message: "Hi {#var#}" }, numbers: { ...EMPTY_NUMBERS, numbersText: "9876543210" } };
    expect(sendFormProblem(input)).toBe(OWN_VAR_ERROR);
    expect(buildSendRequest(input)).toBeNull();
  });
  it("needs the consent tick for promotional Contact and Excel, but not service", () => {
    const promo: SendFormInput = { ...base, route: "own", own: { ...own, template_type: "promotional" }, numbers: { ...EMPTY_NUMBERS, numbersText: "9876543210" } };
    expect(buildSendRequest(promo)).toBeNull();
    expect(sendFormProblem(promo)).toMatch(/consent/i);
    const ticked = { ...promo, numbers: { ...promo.numbers, consent: true } };
    expect(buildSendRequest(ticked)).toMatchObject({ source: "numbers", consent_confirmed: true });
    const excelPromo = { ...promo, numbers: { ...EMPTY_NUMBERS, mode: "excel" as const, excelNumbers: ["9876543210"] } };
    expect(buildSendRequest(excelPromo)).toBeNull();
    expect(buildSendRequest({ ...promo, own })).not.toBeNull();
  });
  it("waits for every template variable to be mapped and for a route", () => {
    expect(sendFormProblem(base)).toMatch(/template/i);
    const input: SendFormInput = { ...base, route: "template", template: tpl, varMap: [null], numbers: { ...EMPTY_NUMBERS, mode: "list", groupIds: ["g1"] } };
    expect(buildSendRequest(input)).toBeNull();
  });
  it("names a send like SMS 3 Nov 18:05 in Indian time", () => {
    expect(defaultSendName(new Date("2026-11-03T12:35:00Z"))).toBe("SMS 3 Nov 18:05");
  });
  it("summarises an Excel read", () => {
    expect(excelSummary({ total: 4120, skipped_total: 18 })).toBe("4,120 numbers · 18 skipped");
    expect(excelSummary({ total: 1, skipped_total: 0 })).toBe("1 number");
  });
});

describe("skippedRowsCsv", () => {
  it("writes a header and quotes awkward values", () => {
    const csv = skippedRowsCsv([
      { row: 3, value: "12345", reason: "Not an Indian mobile number" },
      { row: 4, value: "=SUM(A1)", reason: "Empty row" },
      { row: 5, value: "a,b", reason: "Duplicate number in this file" },
    ]);
    expect(csv.split("\r\n")).toEqual([
      "Row,Value,Reason",
      "3,12345,Not an Indian mobile number",
      "4,'=SUM(A1),Empty row",
      '5,"a,b",Duplicate number in this file',
    ]);
  });
});

describe("developer request examples", () => {
  const input = { senderId: "ANRIL", messageId: "tpl123", variables: ["Asha", "5|0"], numbers: ["9876543210", "9123456780"], apiKey: "abcd1234" };
  it("masks a key to its first 4 characters", () => {
    expect(maskKey("abcd1234efgh")).toBe("abcd••••");
    expect(maskKey("ab")).toBe("••••");
  });
  it("builds the curl call", () => {
    const curl = buildCurl(input);
    expect(curl).toContain("https://sms.anrilaitech.com/dev/bulkV2");
    expect(curl).toContain('authorization: abcd1234');
    expect(curl).toContain('"route": "dlt"');
    expect(curl).toContain('"message": "tpl123"');
    expect(curl).toContain('"variables_values": "Asha|50"');
    expect(curl).toContain('"numbers": "9876543210,9123456780"');
  });
  it("builds the python call and omits variables when there are none", () => {
    const py = buildPython({ ...input, variables: [] });
    expect(py).toContain("import requests");
    expect(py).toContain("https://sms.anrilaitech.com/dev/bulkV2");
    expect(py).not.toContain("variables_values");
  });
  it("never leaves a bulk9 name in the examples", () => {
    expect((buildCurl(input) + buildPython(input)).toLowerCase()).not.toContain("bulk9");
  });
});

describe("withNumbersChange (consent follows the audience)", () => {
  const ticked = { ...EMPTY_NUMBERS, numbersText: "9876543210", consent: true };
  it("keeps consent when only the tick changes", () => {
    expect(withNumbersChange({ ...ticked, consent: false }, { consent: true }).consent).toBe(true);
    expect(withNumbersChange(ticked, {}).consent).toBe(true);
  });
  it("clears consent when the typed numbers change", () => {
    expect(withNumbersChange(ticked, { numbersText: "9123456780" })).toMatchObject({ numbersText: "9123456780", consent: false });
  });
  it("clears consent on a new Excel read, a mode change, groups or leads", () => {
    const x = { ...EMPTY_NUMBERS, mode: "excel" as const, excelNumbers: ["9876543210"], consent: true };
    expect(withNumbersChange(x, { excelNumbers: ["9123456780"] }).consent).toBe(false);
    expect(withNumbersChange(x, { excel: { fileName: "a.xlsx", total: 1, skipped_total: 0, phone_column: "A", skipped: [] } }).consent).toBe(false);
    expect(withNumbersChange(ticked, { mode: "list" }).consent).toBe(false);
    expect(withNumbersChange(ticked, { groupIds: ["g1"] }).consent).toBe(false);
    expect(withNumbersChange(ticked, { leadIds: ["l1"] }).consent).toBe(false);
  });
  it("keeps consent when a patch repeats the same values", () => {
    expect(withNumbersChange(ticked, { excelNumbers: [], groupIds: [] }).consent).toBe(true);
  });
  it("drops an explicit consent:true that arrives with a changed audience", () => {
    expect(withNumbersChange(ticked, { numbersText: "9000000000", consent: true }).consent).toBe(false);
  });
});

describe("pruneVarMap", () => {
  const name = { source: "field" as const, value: "name" };
  const city = { source: "field" as const, value: "city" };
  const fixed = { source: "text" as const, value: "2 Nov" };
  it("drops field mappings that are no longer offered and keeps fixed text", () => {
    expect(pruneVarMap([name, city, fixed, null], ["name", "phone"])).toEqual([name, null, fixed, null]);
  });
  it("returns the same array when nothing changes", () => {
    const m = [name, fixed, null];
    expect(pruneVarMap(m, ["name"])).toBe(m);
  });
  it("makes the map incomplete so the form asks again", () => {
    expect(isVariableMapComplete(pruneVarMap([city], ["name"]), 1)).toBe(false);
  });
});

describe("nextIdempotencyKey", () => {
  let n = 0;
  const make = () => `key${++n}`;
  it("reuses the key for the same request and renews it for any change", () => {
    const a = nextIdempotencyKey(null, "A", make);
    expect(nextIdempotencyKey(a, "A", make)).toBe(a);
    const b = nextIdempotencyKey(a, "B", make);
    expect(b.key).not.toBe(a.key);
    expect(b.signature).toBe("B");
  });
});

describe("DLT id checks", () => {
  it("entity and template ids are 5 to 30 digits", () => {
    for (const f of [isValidEntityId, isValidDltTemplateId]) {
      expect(f("12345")).toBe(true);
      expect(f(" 1234567890123456789012345678 ")).toBe(true);
      expect(f("1234")).toBe(false);
      expect(f("1".repeat(31))).toBe(false);
      expect(f("12a45")).toBe(false);
      expect(f("")).toBe(false);
    }
  });
  it("own sender is 3 to 6 letters or digits", () => {
    expect(isValidOwnSenderId("ANR1")).toBe(true);
    expect(isValidOwnSenderId("ab")).toBe(false);
    expect(isValidOwnSenderId("ABCDEFG")).toBe(false);
    expect(isValidOwnSenderId("AB-CD")).toBe(false);
  });
  const ok = { ...EMPTY_OWN, sender_id: "ANRILT", entity_id: "110100", dlt_template_id: "110700", message: "Hello" };
  const input = (own: typeof ok): SendFormInput => ({ route: "own", template: null, varMap: [], own, numbers: { ...EMPTY_NUMBERS, numbersText: "9876543210" } });
  it("Type my own refuses bad ids with a clear message", () => {
    expect(sendFormProblem(input(ok))).toBeNull();
    expect(sendFormProblem(input({ ...ok, sender_id: "AB-CD" }))).toMatch(/Sender ID/);
    expect(sendFormProblem(input({ ...ok, entity_id: "12ab" }))).toMatch(/entity ID must be 5 to 30 digits/);
    expect(sendFormProblem(input({ ...ok, dlt_template_id: "123" }))).toMatch(/template ID must be 5 to 30 digits/);
    expect(buildSendRequest(input({ ...ok, entity_id: "12ab" }))).toBeNull();
  });
  it("Type my own upper-cases the sender id in the request", () => {
    expect(buildSendRequest(input({ ...ok, sender_id: "anrilt" }))).toMatchObject({ manual: { sender_id: "ANRILT" } });
  });
});

describe("parseContactsSub", () => {
  it("opens groups only for ?tab=groups", () => {
    expect(parseContactsSub("groups")).toBe("groups");
    expect(parseContactsSub("contacts")).toBe("contacts");
    expect(parseContactsSub("x")).toBe("contacts");
    expect(parseContactsSub(null)).toBe("contacts");
  });
});

describe("creditAmountError", () => {
  it("accepts whole rupees from 100 to 10 lakh", () => {
    expect(creditAmountError("100")).toBeNull();
    expect(creditAmountError(" 5000 ")).toBeNull();
    expect(creditAmountError("1000000")).toBeNull();
  });
  it("refuses empty, fractions, too small and too big", () => {
    for (const v of ["", "  ", "99", "1000001", "250.5", "abc", "-500"]) {
      expect(creditAmountError(v)).toBe("Enter a whole amount between ₹100 and ₹10,00,000.");
    }
  });
});

describe("requestedOn", () => {
  it("shows the IST day and month", () => {
    expect(requestedOn("2026-11-02T20:00:00Z")).toBe("3 Nov");
    expect(requestedOn("not a date")).toBe("");
  });
});
