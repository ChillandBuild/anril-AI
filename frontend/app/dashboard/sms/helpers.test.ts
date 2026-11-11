import { describe, expect, it } from "vitest";
import {
  EMPTY_MANUAL,
  campaignStage,
  dailyBars,
  formatRate,
  planSummary,
  categoryLabel,
  manualProblem,
  heldUntil,
  quietRelease,
  sendPrefill,
  onTheWayCount,
  sendProgress,
  UNICODE_NOTE,
  creditAmountError,
  sendSummary,
  requestedOn,
  buildCurl,
  buildPython,
  EMPTY_NUMBERS,
  MAX_TYPED_ROWS,
  typedVarIndexes,
  typedRowsProblem,
  seedTypedRows,
  rowsToNumbersText,
  pasteIntoRows,
  looksLikeOtp,
  type TypedRow,
  buildRecipients,
  buildSendRequest,
  defaultSendName,
  numbersReady,
  sendFormProblem,
  withNumbersChange,
  pruneVarMap,
  nextIdempotencyKey,
  isValidEntityId,
  isValidDltTemplateId,
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
  walletCsv,
  hasLink,
  dltReason,
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
  const base = { loading: false, balance: 1000, needed: 200, support: null };
  it("allows a send when the balance covers it", () => {
    expect(sendBlock(base)).toEqual({ blocked: false, reason: null });
    expect(sendBlock({ ...base, balance: 200 }).blocked).toBe(false);
  });
  it("blocks silently while loading", () => {
    expect(sendBlock({ ...base, loading: true })).toEqual({ blocked: true, reason: null });
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
  it("blocks promotional Contact numbers until consent is ticked", () => {
    const c = n({ mode: "contact", numbersText: "9876543210\n9123456780" });
    expect(numbersReady(c, true)).toBe(false);
    expect(numbersReady({ ...c, consent: true }, true)).toBe(true);
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
  const svc = { id: "t2", message: "Your order shipped", template_type: "service" as const, var_count: 0 };
  const nameVar = { source: "field" as const, value: "name" };
  const base: SendFormInput = { template: null, varMap: [], numbers: EMPTY_NUMBERS };

  it("sends a picked template with no kind or manual fields", () => {
    const input: SendFormInput = { ...base, template: tpl, varMap: [nameVar], numbers: { ...EMPTY_NUMBERS, mode: "list", groupIds: ["g1"] } };
    const req = buildSendRequest(input);
    expect(req).toEqual({ template_id: "t1", variable_map: [nameVar], source: "contacts", group_ids: ["g1"] });
    expect(req).not.toHaveProperty("kind");
    expect(req).not.toHaveProperty("manual");
  });
  it("needs the consent tick for promotional Contact, but not service", () => {
    const promo: SendFormInput = { ...base, template: { ...tpl, message: "20% off", var_count: 0 }, numbers: { ...EMPTY_NUMBERS, numbersText: "9876543210" } };
    expect(buildSendRequest(promo)).toBeNull();
    expect(sendFormProblem(promo)).toMatch(/consent/i);
    const ticked = { ...promo, numbers: { ...promo.numbers, consent: true } };
    expect(buildSendRequest(ticked)).toMatchObject({ source: "numbers", consent_confirmed: true });
    expect(buildSendRequest({ ...promo, template: svc })).not.toBeNull();
  });
  it("waits for a template and for every template variable to be mapped", () => {
    expect(sendFormProblem(base)).toMatch(/template/i);
    const input: SendFormInput = { ...base, template: tpl, varMap: [null], numbers: { ...EMPTY_NUMBERS, mode: "list", groupIds: ["g1"] } };
    expect(buildSendRequest(input)).toBeNull();
  });
  it("names a send like SMS 3 Nov 18:05 in Indian time", () => {
    expect(defaultSendName(new Date("2026-11-03T12:35:00Z"))).toBe("SMS 3 Nov 18:05");
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
  it("clears consent on a mode change, groups or leads", () => {
    expect(withNumbersChange(ticked, { mode: "list" }).consent).toBe(false);
    expect(withNumbersChange(ticked, { groupIds: ["g1"] }).consent).toBe(false);
    expect(withNumbersChange(ticked, { leadIds: ["l1"] }).consent).toBe(false);
  });
  it("keeps consent when a patch repeats the same values", () => {
    expect(withNumbersChange(ticked, { leadIds: [], groupIds: [] }).consent).toBe(true);
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

describe("Type numbers table", () => {
  const row = (phone: string, values: string[] = []): TypedRow => ({ phone, values });
  const typed = { source: "typed" as const, value: "" as const };
  const fixed = { source: "text" as const, value: "2 Nov" };
  const tpl = { id: "t1", message: "Your code is {#var#} for {#var#}", template_type: "service" as const, var_count: 2 };
  const withRows = (rows: TypedRow[]): SendFormInput => ({
    template: tpl,
    varMap: [typed, fixed],
    numbers: { ...EMPTY_NUMBERS, rows },
  });

  it("finds the typed variable positions", () => {
    expect(typedVarIndexes([{ source: "field", value: "name" }, typed, typed], 2)).toEqual([1]);
    expect(typedVarIndexes([typed], 0)).toEqual([]);
  });
  it("counts a typed variable as complete and keeps it on prune", () => {
    expect(isVariableMapComplete([typed], 1)).toBe(true);
    expect(isVariableMapComplete([typed, null], 2)).toBe(false);
    const m = [typed, fixed];
    expect(pruneVarMap(m, [])).toBe(m);
    expect(pruneVarMap(m, [], false)).toEqual([null, fixed]);
  });
  it("reports a blank phone or a blank value, naming the row", () => {
    expect(typedRowsProblem([row("9876543210", ["", "Ravi"]), row("", ["", "Asha"])], [1])).toBe("Add the mobile number on row 2.");
    expect(typedRowsProblem([row("9876543210", ["", "Ravi"]), row("9123456780", ["", " "])], [1])).toBe("Fill Variable 2 on row 2.");
  });
  it("ignores fully empty rows", () => {
    expect(typedRowsProblem([row("", ["", ""]), row("9876543210", ["", "Ravi"]), row("")], [1])).toBeNull();
    expect(typedRowsProblem([], [1])).toBeNull();
  });
  it("stops at the row limit", () => {
    const rows = Array.from({ length: MAX_TYPED_ROWS + 1 }, (_, i) => row(String(9000000000 + i), ["Ravi"]));
    expect(typedRowsProblem(rows, [0])).toBe("Up to 100 numbers can be typed here. For more, upload them to the Address Book.");
  });
  it("builds the request with one typed value list per number, padded to the variable count", () => {
    expect(buildSendRequest(withRows([row("9876543210", ["Ravi"]), row("", []), row("9123456780", [" Asha "])]))).toEqual({
      template_id: "t1",
      variable_map: [typed, fixed],
      source: "numbers",
      numbers: ["9876543210", "9123456780"],
      typed_values: [
        ["Ravi", ""],
        ["Asha", ""],
      ],
    });
  });
  it("gives the row message as the send problem", () => {
    expect(sendFormProblem(withRows([row("", ["Ravi"])]))).toBe("Add the mobile number on row 1.");
    expect(buildSendRequest(withRows([row("", ["Ravi"])]))).toBeNull();
  });
  it("counts the table phones as ready, and clears consent only when a number changes", () => {
    expect(numbersReady({ ...EMPTY_NUMBERS, rows: [row("9876543210")] }, false, true)).toBe(true);
    const ticked = { ...EMPTY_NUMBERS, rows: [row("9876543210")], consent: true };
    expect(withNumbersChange(ticked, { rows: [row("9876543210", ["x"])] }).consent).toBe(true);
    expect(withNumbersChange(ticked, { rows: [row("9123456780")] }).consent).toBe(false);
    expect(withNumbersChange(ticked, { rows: [row("9876543210"), row("9123456780")] }).consent).toBe(false);
  });
  it("seeds rows from typed numbers, with one blank row when there are none", () => {
    expect(seedTypedRows("9876543210\n9123456780")).toEqual([row("9876543210"), row("9123456780")]);
    expect(seedTypedRows("")).toEqual([row("")]);
  });
  it("writes the phones back as plain numbers", () => {
    expect(rowsToNumbersText([row(" 9876543210 ", ["x"]), row(""), row("9123456780")])).toBe("9876543210\n9123456780");
  });
  it("fills phone and one typed variable from a multi-line Excel paste", () => {
    const out = pasteIntoRows([row("")], 0, 0, "9876543210\tRavi\r\n9123456780\tAsha\r\n", [1]);
    expect(out).toEqual([row("9876543210", ["", "Ravi"]), row("9123456780", ["", "Asha"])]);
  });
  it("pastes from a middle row without changing the original rows", () => {
    const before = [row("1"), row("2"), row("3")];
    const out = pasteIntoRows(before, 1, 0, "9000000001\tX", [0]);
    expect(out).toEqual([row("1"), row("9000000001", ["X"]), row("3")]);
    expect(before[1]).toEqual(row("2"));
  });
  it("starts in a typed column and adds rows as needed", () => {
    expect(pasteIntoRows([row("9876543210")], 0, 1, "Ravi\nAsha", [0])).toEqual([row("9876543210", ["Ravi"]), row("", ["Asha"])]);
  });
  it("ignores cells past the last column", () => {
    expect(pasteIntoRows([row("")], 0, 0, "9876543210\tRavi\tExtra", [0])).toEqual([row("9876543210", ["Ravi"])]);
  });
  it("stops pasting at the row limit", () => {
    const text = Array.from({ length: 150 }, (_, i) => String(9000000000 + i)).join("\n");
    const out = pasteIntoRows([], 0, 0, text, []);
    expect(out).toHaveLength(MAX_TYPED_ROWS);
    expect(out[MAX_TYPED_ROWS - 1].phone).toBe("9000000099");
  });
  it("spots an OTP message but not a word that only contains otp", () => {
    expect(looksLikeOtp("Your OTP is {#var#}")).toBe(true);
    expect(looksLikeOtp("Enter this verification code: {#var#}")).toBe(true);
    expect(looksLikeOtp("Hotpot offer")).toBe(false);
    expect(looksLikeOtp("Hi {#var#}")).toBe(false);
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

describe("sendSummary", () => {
  const preview = { total_segments: 6, eligible_count: 3, excluded: [], samples: [], estimated: true, rate_per_sms: 0.25, estimated_amount: 1.5 };
  it("shows dashes until the preview runs", () => {
    expect(sendSummary({ preview: null, parts: 1, balance: null })).toEqual([
      { label: "Recipients", value: "—" },
      { label: "SMS each", value: "1" },
      { label: "Credits needed", value: "—" },
      { label: "Estimated cost", value: "—" },
      { label: "Balance", value: "—" },
    ]);
  });
  it("fills in from the preview and flags a balance that doesn't cover it", () => {
    const rows = sendSummary({ preview, parts: 2, balance: { sms_count: 5, wallet: 1.25 } });
    expect(rows.map((r) => r.value)).toEqual(["3", "2", "6", "≈ ₹1.50", "5 SMS · ₹1.25"]);
    expect(rows[4].bad).toBe(true);
    expect(sendSummary({ preview, parts: 2, balance: { sms_count: 6, wallet: null } })[4]).toEqual({ label: "Balance", value: "6 SMS" });
  });
  it("leaves the cost blank when there is no charge history yet", () => {
    expect(sendSummary({ preview: { ...preview, rate_per_sms: null, estimated_amount: null }, parts: 1, balance: null })[3].value).toBe("—");
  });
});

describe("sendProgress", () => {
  it("counts delivered, failed and on-the-way against the total", () => {
    expect(sendProgress({ delivered: 117, failed: 2, submitted: 1 }, 120)).toEqual({ delivered: 117, failed: 2, onTheWay: 1, total: 120, pct: 98 });
  });
  it("has no percentage when nobody was counted", () => {
    expect(sendProgress({}, 0).pct).toBeNull();
  });
});

describe("onTheWayCount", () => {
  it("adds waiting, sending, with the operator and checking", () => {
    expect(onTheWayCount({ queued: 3, sending: 2, submitted: 5, unknown: 1, delivered: 9 })).toBe(11);
    expect(onTheWayCount(null)).toBe(0);
  });
});

describe("sendPrefill", () => {
  const g1 = "6f1c2a3b-1111-4222-8333-944455556666";
  const g2 = "7a2d3c4e-1111-4222-8333-944455556666";
  it("picks Address Book groups from ?groups=", () => {
    expect(sendPrefill(`?groups=${g1},${g2}`, null)).toEqual({ mode: "list", groupIds: [g1, g2] });
  });
  it("drops anything that is not a group id", () => {
    expect(sendPrefill("?groups=abc,<script>", null)).toBeNull();
  });
  it("fills Type numbers from the stored list when ?numbers=1", () => {
    expect(sendPrefill("?numbers=1", "9876543210\n9123456780\n")).toEqual({ mode: "contact", numbersText: "9876543210\n9123456780" });
  });
  it("does nothing without a hand-off", () => {
    expect(sendPrefill("", "9876543210")).toBeNull();
    expect(sendPrefill("?numbers=1", null)).toBeNull();
  });
});

describe("hasLink", () => {
  it("spots http, https and www links", () => {
    expect(hasLink("Visit https://anril.ai/offer today")).toBe(true);
    expect(hasLink("Open http://x.in")).toBe(true);
    expect(hasLink("See www.anril.ai")).toBe(true);
  });
  it("spots a bare domain with or without a path", () => {
    expect(hasLink("Get the app: play.google.com/store/apps/details?id=x")).toBe(true);
    expect(hasLink("Shop at anril.in now")).toBe(true);
    expect(hasLink("Book on shop.co.in/abc.")).toBe(true);
  });
  it("ignores ordinary text, numbers and emails", () => {
    expect(hasLink("Hi {#var#}, your order 123 ships today.")).toBe(false);
    expect(hasLink("Pay Rs.50 by 5.30pm. Thanks.")).toBe(false);
    expect(hasLink("Mail us at help@anril.com")).toBe(false);
    expect(hasLink("")).toBe(false);
    expect(hasLink(null)).toBe(false);
  });
});

describe("dltReason", () => {
  it("explains a non-whitelisted link and keeps the raw code", () => {
    expect(dltReason("CTA_URL_NOT_MATCHED")).toEqual({ text: "Blocked: the link isn't whitelisted on your DLT portal", code: "CTA_URL_NOT_MATCHED" });
    expect(dltReason("cta not whitelisted").text).toBe("Blocked: the link isn't whitelisted on your DLT portal");
  });
  it("maps the common DLT and operator codes", () => {
    expect(dltReason("TEMPLATE_MISMATCH").text).toBe("Blocked: the wording doesn't match the approved DLT template");
    expect(dltReason("Content template not matched").text).toBe("Blocked: the wording doesn't match the approved DLT template");
    expect(dltReason("HEADER_NOT_REGISTERED").text).toBe("Blocked: the sender ID isn't registered or active on DLT");
    expect(dltReason("Sender inactive").text).toBe("Blocked: the sender ID isn't registered or active on DLT");
    expect(dltReason("PE_TM_BINDING_FAILED").text).toBe("Blocked: your DLT entity isn't linked to the telemarketer");
    expect(dltReason("Invalid entity id").text).toBe("Blocked: your DLT entity isn't linked to the telemarketer");
    expect(dltReason("NCPR_DND").text).toBe("Blocked: the number is on DND or has no consent");
    expect(dltReason("NO_CONSENT").text).toBe("Blocked: the number is on DND or has no consent");
    expect(dltReason("INVALID_NUMBER").text).toBe("Invalid mobile number");
    expect(dltReason("Wrong number").text).toBe("Invalid mobile number");
    expect(dltReason("ABSENT_SUBSCRIBER").text).toBe("Phone unreachable (switched off or out of coverage)");
    expect(dltReason("Handset switched off").text).toBe("Phone unreachable (switched off or out of coverage)");
    expect(dltReason("MESSAGE_EXPIRED").text).toBe("Phone unreachable (switched off or out of coverage)");
    expect(dltReason("BLACKLISTED").text).toBe("Number is blacklisted");
  });
  it("does not mistake words that merely contain 'cta'", () => {
    expect(dltReason("CONTACT_LIST_EMPTY").text).toBe("Contact list empty");
  });
  it("humanises an unknown code and keeps it", () => {
    expect(dltReason("SOME_NEW_CODE")).toEqual({ text: "Some new code", code: "SOME_NEW_CODE" });
  });
  it("returns nothing for an empty reason", () => {
    expect(dltReason("No SMS consent (promotional template)")).toEqual({ text: "No SMS consent (promotional template)", code: null });
    expect(dltReason("Opted out").text).toBe("Opted out");
    expect(dltReason("SMS is not enabled for this account.").text).toBe("SMS is not enabled for this account.");
    expect(dltReason("Not an Indian mobile number").text).toBe("Not an Indian mobile number");
    expect(dltReason("Some operator sentence").text).toBe("Some operator sentence");
    expect(dltReason(null)).toEqual({ text: "", code: null });
    expect(dltReason("  ")).toEqual({ text: "", code: null });
  });
});

describe("night-time hold", () => {
  // 4 Nov 2026 10:47 PM IST = 17:17 UTC
  const lateNight = "2026-11-04T17:17:09Z";
  it("releases a 10:47 PM send at 10 AM next day", () => {
    expect(quietRelease(lateNight)?.toISOString()).toBe("2026-11-05T04:30:00.000Z");
  });
  it("releases an early-morning send at 10 AM the same day", () => {
    expect(quietRelease("2026-11-05T01:00:00Z")?.toISOString()).toBe("2026-11-05T04:30:00.000Z"); // 6:30 AM IST
  });
  it("does not hold daytime sends, edges included", () => {
    expect(quietRelease("2026-11-05T04:30:00Z")).toBeNull(); // 10:00 AM IST
    expect(quietRelease("2026-11-05T15:29:59Z")).toBeNull(); // 8:59:59 PM IST
    expect(quietRelease("2026-11-05T15:30:00Z")).not.toBeNull(); // 9:00 PM IST
    expect(quietRelease(null)).toBeNull();
    expect(quietRelease("junk")).toBeNull();
  });
  it("crosses month ends", () => {
    expect(quietRelease("2026-11-30T17:00:00Z")?.toISOString()).toBe("2026-12-01T04:30:00.000Z");
  });
  it("shows held only for submitted messages before the release", () => {
    const m = { status: "submitted", submitted_at: lateNight };
    expect(heldUntil(m, new Date("2026-11-04T20:00:00Z"))?.toISOString()).toBe("2026-11-05T04:30:00.000Z");
    expect(heldUntil(m, new Date("2026-11-05T04:31:00Z"))).toBeNull();
    expect(heldUntil({ ...m, status: "delivered" }, new Date("2026-11-04T20:00:00Z"))).toBeNull();
  });
});

describe("DLT category and Type my own", () => {
  it("labels categories the way Bulk9 does and never asks when unknown", () => {
    expect(categoryLabel("service")).toBe("Service Implicit");
    expect(categoryLabel("promotional")).toBe("Service Explicit / Promo");
    expect(categoryLabel("unclassified")).toBe("Set by DLT");
    expect(categoryLabel("unknown")).toBe("Set by DLT");
  });

  const manual = { sender_id: "KELIR", entity_id: "1701176655431156940", dlt_template_id: "1707176655431156001", message: "Your booking is confirmed" };

  it("checks a typed message step by step", () => {
    expect(manualProblem(EMPTY_MANUAL)).toMatch(/sender/);
    expect(manualProblem({ ...manual, dlt_template_id: "12" })).toMatch(/DLT template ID/);
    expect(manualProblem({ ...manual, message: "  " })).toMatch(/Type the message/);
    expect(manualProblem({ ...manual, message: "Hi {#var#}" })).toMatch(/Replace/);
    expect(manualProblem(manual)).toBeNull();
  });

  it("builds a dlt_manual request with no template and no category", () => {
    const req = buildSendRequest({ template: null, manual: { ...manual, message: " Your booking is confirmed " }, varMap: [], numbers: { ...EMPTY_NUMBERS, mode: "contact", numbersText: "9876543210" } });
    expect(req).toMatchObject({ kind: "manual", manual: { ...manual } });
    expect(req && "template_id" in req).toBe(false);
  });
});

describe("campaignStage", () => {
  const base = { status: "completed" as const, created_at: "2026-11-04T17:17:00Z", send_at: "2026-11-04T17:17:00Z", completed_at: "2026-11-04T17:17:08Z" };
  const counts = (c: Record<string, number>) => ({ queued: 0, sending: 0, submitted: 0, delivered: 0, failed: 0, unknown: 0, skipped: 0, cancelled: 0, ...c }) as never;
  it("a night send still with the operator reads Held until 10 AM, not Completed", () => {
    const s = campaignStage({ ...base, counts: counts({ submitted: 1 }) }, new Date("2026-11-04T21:53:00Z"));
    expect(s.tone).toBe("warn");
    expect(s.label).toMatch(/^Held until 10:00/);
  });
  it("after 10 AM with no receipt it is Waiting for delivery", () => {
    expect(campaignStage({ ...base, counts: counts({ submitted: 1 }) }, new Date("2026-11-05T05:00:00Z")).label).toBe("Waiting for delivery");
  });
  it("a send that started before 9 PM is not shown as held", () => {
    const evening = { ...base, send_at: "2026-11-04T15:10:00Z", created_at: "2026-11-04T15:10:00Z", completed_at: "2026-11-04T15:40:00Z" };
    expect(campaignStage({ ...evening, counts: counts({ submitted: 5 }) }, new Date("2026-11-04T21:53:00Z")).label).toBe("Waiting for delivery");
  });
  it("after 3 days without a receipt it stops saying Waiting", () => {
    expect(campaignStage({ ...base, counts: counts({ delivered: 4, submitted: 1 }) }, new Date("2026-11-09T00:00:00Z")).label).toBe("Completed · 1 without receipt");
  });
  it("once every SMS has a receipt, the badge says how it went", () => {
    const stage = (c: Record<string, number>) => campaignStage({ ...base, counts: counts(c) }, new Date());
    expect(stage({ delivered: 3 })).toMatchObject({ label: "Delivered", tone: "success" });
    expect(stage({ failed: 1 })).toMatchObject({ label: "Failed", tone: "danger" });
    expect(stage({ delivered: 2, failed: 1 })).toMatchObject({ label: "2 of 3 delivered", tone: "warn" });
  });
  it("a finished send where nothing went out (all skipped or cancelled) is not shown as delivered", () => {
    expect(campaignStage({ ...base, counts: counts({ skipped: 2, cancelled: 1 }) }, new Date())).toMatchObject({ label: "Nothing sent", tone: "neutral" });
  });
  it("keeps the server label for other states", () => {
    expect(campaignStage({ ...base, status: "scheduled", counts: counts({ queued: 3 }) }, new Date()).label).toBe("Scheduled");
  });
});

describe("planSummary", () => {
  it("matches the operator's Plan Details: price = money left / SMS left, total = left + used", () => {
    const items = [
      { kind: "campaign", sms: -3, amount: -0.39, label: "x", campaign_id: null, at: "2026-11-04", balance_after: null },
      { kind: "outside_usage", sms: -1, amount: null, label: "y", campaign_id: null, at: "2026-11-04", balance_after: null },
      { kind: "topup", sms: 500, amount: null, label: "z", campaign_id: null, at: "2026-11-03", balance_after: null },
    ] as never[];
    const p = planSummary({ sms_count: 496, wallet: 64.58 }, items, 100);
    expect(formatRate(p.perSms!)).toBe("₹0.1302");
    expect([p.used, p.total, p.partial]).toEqual([4, 500, false]);
  });
  it("has no price when the wallet is unknown or empty", () => {
    expect(planSummary({ sms_count: 0, wallet: 0 }, [], 100).perSms).toBeNull();
    expect(planSummary({ sms_count: 10, wallet: null }, [], 100).perSms).toBeNull();
  });
});

describe("dailyBars", () => {
  it("scales SMS and OTP bars to their own busiest day and labels the date", () => {
    const bars = dailyBars([
      { day: "2026-11-03", delivered: 1, failed: 0, waiting: 0, otp: 4 },
      { day: "2026-11-04", delivered: 0, failed: 1, waiting: 3, otp: 2 },
    ]);
    expect(bars.map((b) => [b.label, b.sms, b.smsPct, b.otpPct])).toEqual([["3 Nov", 1, 25, 100], ["4 Nov", 4, 100, 50]]);
  });
  it("a quiet day next to a busy one still gets a visible sliver", () => {
    const bars = dailyBars([
      { day: "2026-11-03", delivered: 1, failed: 0, waiting: 0, otp: 0 },
      { day: "2026-11-04", delivered: 1000, failed: 0, waiting: 0, otp: 0 },
    ]);
    expect(bars[0].smsPct).toBe(3);
  });
  it("an empty period gives zero heights", () => {
    expect(dailyBars([{ day: "2026-11-03", delivered: 0, failed: 0, waiting: 0, otp: 0 }])[0].smsPct).toBe(0);
  });
});
