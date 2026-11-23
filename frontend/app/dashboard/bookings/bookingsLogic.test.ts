import { describe, expect, it } from "vitest";
import type { Booking, WeekHours } from "@/lib/bookingsApi";
import {
  addBlock, bookingFlags, canMarkNoShow, canMarkVisit, rupees, sameInstant, clickMinutes, columnAt, copyDayToAll, defaultHours, dropMinutes, freeBands, gridRange,
  historyNote, hoursSummary, normaliseHours, parsePhone, placeBooking, resourcesForService, snapMinutes, summariseDay, timesByPart, validateDay,
  minutesInWords, paiseToRupeesText, rupeesTextToPaise, templateStatusText, validateRules,
  validateHours,
} from "./bookingsLogic";
import { addDays, clock, dayLabel, formatDateTime, formatDay, istOf, mondayOf, toIso, todayIst, weekdayIndex } from "./bookingsTime";

// 2026-11-26 is a Thursday.
const DATE = "2026-11-26";
const at = (hhmm: string) => {
  const [h, m] = hhmm.split(":").map(Number);
  return toIso(DATE, h * 60 + m);
};

describe("IST time helpers", () => {
  it("converts between IST wall time and UTC instants", () => {
    expect(toIso(DATE, 16 * 60)).toBe("2026-11-26T10:30:00.000Z");
    expect(istOf("2026-11-26T10:30:00Z")).toEqual({ date: DATE, minutes: 960 });
  });
  it("rolls to the next IST day after 6:30 PM UTC", () => {
    expect(istOf("2026-11-26T19:00:00Z")).toEqual({ date: "2026-11-27", minutes: 30 });
    expect(todayIst(new Date("2026-11-26T19:00:00Z"))).toBe("2026-11-27");
    expect(todayIst(new Date("2026-11-26T18:29:00Z"))).toBe("2026-11-26");
  });
  it("knows weekdays (Monday = 0) and week starts", () => {
    expect(weekdayIndex(DATE)).toBe(3);
    expect(weekdayIndex("2026-11-30")).toBe(0);
    expect(weekdayIndex("2026-11-29")).toBe(6);
    expect(mondayOf(DATE)).toBe("2026-11-23");
    expect(mondayOf("2026-11-29")).toBe("2026-11-23");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
  });
  it("writes times and days in plain words", () => {
    expect(clock(0)).toBe("12:00 AM");
    expect(clock(12 * 60)).toBe("12:00 PM");
    expect(clock(16 * 60)).toBe("4:00 PM");
    expect(formatDay(DATE)).toBe("Thu 26 Nov");
    expect(formatDateTime(at("16:00"))).toBe("Thu 26 Nov, 4:00 PM");
    expect(dayLabel(DATE, DATE)).toBe("Today");
    expect(dayLabel("2026-11-27", DATE)).toBe("Tomorrow");
    expect(dayLabel("2026-11-25", DATE)).toBe("Yesterday");
    expect(dayLabel("2026-12-01", DATE)).toBe("Tue 1 Dec");
  });
});

describe("grid placement", () => {
  const hours: WeekHours = { "3": [["10:00", "13:00"], ["16:00", "20:30"]] };
  it("spans the day's hours to whole hours", () => {
    expect(gridRange(DATE, [{ hours }], [])).toEqual({ startMin: 600, endMin: 1260 });
  });
  it("widens for a booking outside the hours", () => {
    const b = { start_at: at("08:30"), block_end_at: at("09:15") };
    expect(gridRange(DATE, [{ hours }], [b])).toEqual({ startMin: 480, endMin: 1260 });
  });
  it("falls back to 9-8 with no hours and no bookings", () => {
    expect(gridRange(DATE, [{ hours: {} }], [])).toEqual({ startMin: 540, endMin: 1200 });
  });
  it("places a block with its hatched gap", () => {
    const p = placeBooking({ start_at: at("16:00"), end_at: at("16:45"), block_end_at: at("17:00") }, DATE, 600);
    expect(p).toEqual({ top: 360, height: 45, gap: 15 });
  });
  it("turns free ranges into bands", () => {
    const bands = freeBands([[at("10:00"), at("12:30")]], DATE, 600);
    expect(bands).toEqual([{ top: 0, height: 150, startMin: 600, endMin: 750 }]);
    expect(freeBands(undefined, DATE, 600)).toEqual([]);
  });
});

describe("snapping a drag to 15 minutes", () => {
  it("rounds to the nearest 15", () => {
    expect(snapMinutes(607)).toBe(600);
    expect(snapMinutes(608)).toBe(615);
    expect(snapMinutes(622)).toBe(615);
  });
  it("lands where the block was grabbed, not where the pointer is", () => {
    // Grid starts 10:00; pointer 160px down = 100 min = 11:40, grabbed 20 min into the block -> 11:20 -> 11:15.
    const m = dropMinutes({ offsetY: 160, grabOffsetMin: 20, gridStartMin: 600, gridEndMin: 1200, blockMin: 45, pxPerMin: 1.6 });
    expect(m).toBe(675);
  });
  it("stays inside the visible day", () => {
    const base = { gridStartMin: 600, gridEndMin: 1200, blockMin: 60, pxPerMin: 1.6, grabOffsetMin: 0 };
    expect(dropMinutes({ ...base, offsetY: -500 })).toBe(600);
    expect(dropMinutes({ ...base, offsetY: 5000 })).toBe(1140);
  });
  it("a click in a free gap picks the mark at or before the click, inside the gap", () => {
    const band = { startMin: 610, endMin: 700 };
    expect(clickMinutes(0, band, 600, 1.6)).toBe(615);
    expect(clickMinutes(40, band, 600, 1.6)).toBe(615);
    expect(clickMinutes(48, band, 600, 1.6)).toBe(630);
    expect(clickMinutes(9999, band, 600, 1.6)).toBe(685);
  });
  it("finds the column under the pointer", () => {
    const cols = [{ left: 0, width: 100 }, { left: 100, width: 100 }];
    expect(columnAt(50, cols)).toBe(0);
    expect(columnAt(100, cols)).toBe(1);
    expect(columnAt(250, cols)).toBe(-1);
  });
});

describe("hours editor validation", () => {
  it("accepts one or two ordered blocks", () => {
    expect(validateDay([])).toBeNull();
    expect(validateDay([["10:00", "13:00"]])).toBeNull();
    expect(validateDay([["16:00", "20:00"], ["10:00", "13:00"]])).toBeNull();
    expect(validateDay([["10:00", "13:00"], ["13:00", "20:00"]])).toBeNull();
  });
  it("refuses an end that is not after the start", () => {
    expect(validateDay([["13:00", "13:00"]])).toMatch(/end must be after/);
    expect(validateDay([["14:00", "10:00"]])).toMatch(/end must be after/);
  });
  it("refuses overlap and a third block", () => {
    expect(validateDay([["10:00", "14:00"], ["13:00", "18:00"]])).toMatch(/overlap/);
    expect(validateDay([["08:00", "09:00"], ["10:00", "11:00"], ["12:00", "13:00"]])).toMatch(/At most 2/);
  });
  it("refuses a blank time", () => {
    expect(validateDay([["", "13:00"]])).toMatch(/both times/);
  });
  it("reports the days with a problem", () => {
    const h = normaliseHours({ "1": [["10:00", "09:00"]], "4": [["10:00", "13:00"]] });
    expect(Object.keys(validateHours(h))).toEqual(["1"]);
    expect(validateHours(defaultHours())).toEqual({});
  });
  it("copies one day to all seven without sharing arrays", () => {
    const h = copyDayToAll(normaliseHours({ "2": [["09:00", "12:00"], ["14:00", "18:00"]] }), 2);
    for (let d = 0; d < 7; d++) expect(h[String(d)]).toEqual([["09:00", "12:00"], ["14:00", "18:00"]]);
    h["0"][0][0] = "10:00";
    expect(h["1"][0][0]).toBe("09:00");
  });
  it("adds a second block after the first, never a third", () => {
    const one = addBlock([["10:00", "13:00"]]);
    expect(one).toEqual([["10:00", "13:00"], ["14:00", "17:00"]]);
    expect(addBlock(one)).toBe(one);
    expect(addBlock([])).toEqual([["10:00", "13:00"]]);
  });
  it("summarises hours", () => {
    expect(hoursSummary([])).toBe("Off");
    expect(hoursSummary([["10:00", "13:00"], ["16:00", "20:00"]])).toBe("10:00–13:00, 16:00–20:00");
  });
});

const base: Booking = {
  id: "b1", number: 12, code: "BK-0012", status: "booked", source: "phone", start_at: at("16:00"), end_at: at("16:45"),
  block_end_at: at("17:00"), service_id: "s1", service_name: "Reading", resource_id: "r1", customer_name: "Priya",
  phone: "+919876543210", lead_id: "L1", phone_checked: true, advance_paid: false, deal_id: null, confirmed_at: null,
  call_now: false, note: null,
};

describe("booking flags", () => {
  const labels = (b: Partial<Booking>) => bookingFlags({ ...base, ...b }).map((f) => f.label);
  it("shows nothing for a plain, checked booking", () => {
    expect(labels({})).toEqual([]);
  });
  it("Phone not checked is amber", () => {
    const f = bookingFlags({ ...base, phone_checked: false });
    expect(f).toEqual([{ key: "phone", label: "Phone not checked", tone: "amber" }]);
  });
  it("Call now is red and comes first", () => {
    const f = bookingFlags({ ...base, call_now: true, phone_checked: false });
    expect(f[0]).toEqual({ key: "call_now", label: "Call now", tone: "red" });
  });
  it("advance flags carry the rupees only when the server sent them", () => {
    expect(labels({ advance_paid: true, advance_paise: 20000 })).toEqual(["Advance paid ₹200"]);
    expect(labels({ status: "held", advance_paise: 20000 })).toEqual(["Advance due ₹200"]);
    expect(labels({ status: "held" })).toEqual(["Advance due"]);
    expect(labels({ advance_paid: true })).toEqual(["Advance paid"]);
    expect(labels({ advance_paise: 20000 })).toEqual(["Advance due ₹200"]);
  });
  it("Said yes shows once confirmed", () => {
    expect(labels({ confirmed_at: "2026-11-26T05:00:00Z" })).toEqual(["Said yes"]);
  });
  it("no flags once it is came, didn't come or cancelled", () => {
    for (const status of ["came", "no_show", "cancelled"] as const) expect(labels({ status, phone_checked: false, call_now: true })).toEqual([]);
  });
});

describe("who can mark a visit", () => {
  it("manage can; the linked staff can on their own column only", () => {
    expect(canMarkVisit(base, { canManage: true, myResourceId: null })).toBe(true);
    expect(canMarkVisit(base, { canManage: false, myResourceId: "r1" })).toBe(true);
    expect(canMarkVisit(base, { canManage: false, myResourceId: "r2" })).toBe(false);
    expect(canMarkVisit(base, { canManage: false, myResourceId: null })).toBe(false);
  });
  it("only a booked booking can be marked", () => {
    expect(canMarkVisit({ ...base, status: "came" }, { canManage: true, myResourceId: null })).toBe(false);
    expect(canMarkVisit({ ...base, status: "held" }, { canManage: true, myResourceId: null })).toBe(false);
  });
});

describe("phone and history", () => {
  it("accepts 10-digit Indian mobiles with +91, 91 or 0 in front", () => {
    for (const v of ["9876543210", "+91 98765 43210", "919876543210", "09876543210", "98765-43210"]) {
      expect(parsePhone(v), v).toMatchObject({ ok: true, digits: "9876543210" });
    }
  });
  it("refuses wrong lengths and landline starts", () => {
    expect(parsePhone("98765").ok).toBe(false);
    expect(parsePhone("1234567890").error).toMatch(/starts with 6/);
    expect(parsePhone("98765abcde").ok).toBe(false);
    expect(parsePhone("").ok).toBe(false);
  });
  it("tells staff to ask for an advance after didn't-comes", () => {
    expect(historyNote({ bookings_count: 5, no_shows: 2, advance_needed: true })).toBe("2 didn't come — ask for an advance");
    expect(historyNote({ bookings_count: 3, no_shows: 1, advance_needed: false })).toBe("1 didn't come");
    expect(historyNote({ bookings_count: 3, no_shows: 0, advance_needed: false })).toBe("3 earlier bookings");
    expect(historyNote({ bookings_count: 0, no_shows: 0, advance_needed: false })).toBeNull();
    expect(historyNote(null)).toBeNull();
  });
});

describe("summaries", () => {
  it("counts live bookings per column; cancelled are left out", () => {
    const s = summariseDay([
      { status: "booked", resource_id: "r1" }, { status: "came", resource_id: "r1" }, { status: "held", resource_id: "r2" },
      { status: "cancelled", resource_id: "r2" }, { status: "no_show", resource_id: "r2" },
    ]);
    expect(s).toEqual({ total: 3, came: 1, noShow: 1, byResource: { r1: 2, r2: 1 } });
  });
  it("lists the columns that do a service", () => {
    const r = (id: string, active: boolean, ids: string[]) => ({ id, active, service_ids: ids }) as never;
    const got = resourcesForService([r("a", true, ["s1"]), r("b", false, ["s1"]), r("c", true, ["s2"])], "s1");
    expect(got.map((x: { id: string }) => x.id)).toEqual(["a"]);
  });
});

describe("free times grouped for the picker", () => {
  const t = (hhmm: string) => ({ start_at: at(hhmm), resource_id: "r1", resource_name: "Ravi" });
  it("splits Morning (before 12), Afternoon (12 to 5 PM) and Evening", () => {
    const parts = timesByPart([t("09:00"), t("11:45"), t("12:00"), t("16:45"), t("17:00"), t("19:30")]);
    expect(parts.map((p) => [p.part, p.times.length])).toEqual([["Morning", 2], ["Afternoon", 2], ["Evening", 2]]);
  });
  it("leaves out an empty part", () => {
    expect(timesByPart([t("18:00")]).map((p) => p.part)).toEqual(["Evening"]);
    expect(timesByPart([])).toEqual([]);
  });
});

describe("money fields", () => {
  it("reads rupee text as paise", () => {
    expect(rupeesTextToPaise("200")).toBe(20000);
    expect(rupeesTextToPaise("₹1,250")).toBe(125000);
    expect(rupeesTextToPaise("199.5")).toBe(19950);
    expect(rupeesTextToPaise("")).toBe(0);
  });
  it("refuses anything that is not a plain amount", () => {
    for (const v of ["abc", "-5", "1.234", "12.", "1e3"]) expect(rupeesTextToPaise(v), v).toBeNull();
  });
  it("writes paise back as rupee text", () => {
    expect(paiseToRupeesText(20000)).toBe("200");
    expect(paiseToRupeesText(19950)).toBe("199.50");
    expect(paiseToRupeesText(0)).toBe("");
    expect(paiseToRupeesText(undefined)).toBe("");
  });
});

describe("booking-link rules", () => {
  const ok = { link_on: true, days_ahead: 14, min_notice_min: 60, cancel_cutoff_min: 180, one_per_day: true, no_show_limit: 2 };
  it("accepts the defaults", () => expect(validateRules(ok)).toBeNull());
  it("keeps to the database limits", () => {
    expect(validateRules({ ...ok, days_ahead: 0 })).toMatch(/Days ahead/);
    expect(validateRules({ ...ok, days_ahead: 91 })).toMatch(/1 to 90/);
    expect(validateRules({ ...ok, min_notice_min: -1 })).toMatch(/Notice/);
    expect(validateRules({ ...ok, cancel_cutoff_min: 2881 })).toMatch(/cut-off/);
    expect(validateRules({ ...ok, no_show_limit: 11 })).toMatch(/1 to 10/);
    expect(validateRules({ ...ok, no_show_limit: 1.5 })).not.toBeNull();
    expect(validateRules({ ...ok, min_notice_min: Number.NaN })).not.toBeNull();
  });
  it("says minutes in words", () => {
    expect(minutesInWords(45)).toBe("45 minutes");
    expect(minutesInWords(180)).toBe("3 hours");
    expect(minutesInWords(90)).toBe("1 hour 30 minutes");
    expect(minutesInWords(1)).toBe("1 minute");
  });
  it("says the message template state in words", () => {
    expect(templateStatusText("APPROVED")).toEqual({ text: "Ready", ready: true });
    expect(templateStatusText("pending").ready).toBe(false);
    expect(templateStatusText("REJECTED").text).toMatch(/set up again/);
    expect(templateStatusText(null).text).toBe("Not set up yet");
  });
});

describe("rupees", () => {
  it("shows whole rupees plainly and paise when there are any", () => {
    expect(rupees(20000)).toBe("₹200");
    expect(rupees(19950)).toBe("₹199.50");
    expect(rupees(19905)).toBe("₹199.05");
    expect(rupees(125000)).toBe("₹1,250");
    expect(rupees(0)).toBe("₹0");
  });
});

describe("sameInstant", () => {
  it("compares moments, not spellings", () => {
    expect(sameInstant("2026-11-28T16:00:00+05:30", "2026-11-28T10:30:00Z")).toBe(true);
    expect(sameInstant("2026-11-28T16:00:00+05:30", "2026-11-28T10:45:00Z")).toBe(false);
    expect(sameInstant(null, "2026-11-28T10:30:00Z")).toBe(false);
    expect(sameInstant("nope", "nope")).toBe(false);
  });
});

describe("advance_needed when the amount is hidden", () => {
  it("shows Advance due from the flag alone", () => {
    const base = { status: "booked" as const, phone_checked: true, advance_paid: false, call_now: false, confirmed_at: null };
    expect(bookingFlags({ ...base, advance_needed: true }).map((f) => f.label)).toEqual(["Advance due"]);
    expect(bookingFlags({ ...base, advance_needed: false })).toEqual([]);
  });
});

describe("Didn't come", () => {
  const b = { status: "booked" as const, resource_id: "r1", start_at: "2026-11-28T10:30:00Z" };
  const who = { canManage: true, myResourceId: null };
  const at = Date.parse("2026-11-28T10:30:00Z");
  it("is hidden before the booking starts and shown once it has", () => {
    expect(canMarkNoShow(b, who, at - 1)).toBe(false);
    expect(canMarkNoShow(b, who, at)).toBe(true);
  });
  it("still needs the usual permission", () => {
    expect(canMarkNoShow(b, { canManage: false, myResourceId: "r2" }, at + 1000)).toBe(false);
  });
});

describe("held link bookings", () => {
  const base = { status: "held" as const, source: "link" as const, phone_checked: false, advance_paid: false, call_now: false, confirmed_at: null };
  it("say they wait for the customer on WhatsApp, not Phone not checked", () => {
    const labels = bookingFlags(base).map((f) => f.label);
    expect(labels).toEqual(["Waiting for the customer to confirm on WhatsApp", "Advance due"]);
  });
  it("a held booking from the phone keeps Phone not checked", () => {
    expect(bookingFlags({ ...base, source: "phone" }).map((f) => f.label)).toContain("Phone not checked");
  });
  it("once the number is confirmed the waiting flag goes", () => {
    expect(bookingFlags({ ...base, phone_checked: true }).map((f) => f.label)).toEqual(["Advance due"]);
  });
});
