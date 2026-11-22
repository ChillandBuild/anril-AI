import { describe, expect, it } from "vitest";
import {
  buildDayGrid,
  buildIcs,
  checkIndianMobile,
  checkName,
  classifyError,
  cleanPhoneInput,
  cutoffText,
  dayPartOf,
  errorMessage,
  errorText,
  flowReducer,
  formatCountdown,
  formatDay,
  formatDuration,
  formatTime,
  formatWhen,
  groupTimes,
  heldSteps,
  icsEscape,
  initialFlow,
  istDateOf,
  nextPollDelay,
  rupees,
  safePaymentUrl,
  safeWhatsappUrl,
  secondsLeft,
  staffChoices,
  statusLabel,
  type FlowState,
} from "./publicBookingLogic";

// 2026-11-26 10:30 UTC = 16:00 IST on Thu 26 Nov 2026
const THU_4PM = "2026-11-26T10:30:00Z";

describe("IST formatting", () => {
  it("shows 4:00 PM IST for 10:30 UTC", () => {
    expect(formatTime(THU_4PM)).toBe("4:00 PM");
    expect(formatDay(THU_4PM)).toBe("Thu 26 Nov");
    expect(formatWhen(THU_4PM)).toBe("Thu 26 Nov, 4:00 PM");
  });
  it("rolls to the next IST day after 18:30 UTC", () => {
    expect(istDateOf("2026-11-26T18:29:00Z")).toBe("2026-11-26");
    expect(istDateOf("2026-11-26T18:30:00Z")).toBe("2026-11-27");
    expect(formatTime("2026-11-26T18:30:00Z")).toBe("12:00 AM");
  });
  it("handles noon and 12:15 AM", () => {
    expect(formatTime("2026-11-26T06:30:00Z")).toBe("12:00 PM");
    expect(formatTime("2026-11-26T18:45:00Z")).toBe("12:15 AM");
  });
  it("formats rupees and durations", () => {
    expect(rupees(20000)).toBe("₹200");
    expect(rupees(25050)).toBe("₹250.50");
    expect(rupees(150000)).toBe("₹1,500");
    expect(formatDuration(45)).toBe("45 min");
    expect(formatDuration(60)).toBe("1 hr");
    expect(formatDuration(90)).toBe("1 hr 30 min");
  });
});

describe("phone validation", () => {
  it("accepts common Indian formats and returns +91", () => {
    for (const raw of ["9876543210", "98765 43210", "+91 98765-43210", "919876543210", "09876543210", "(98765) 43210"]) {
      const r = checkIndianMobile(raw);
      expect(r.ok, raw).toBe(true);
      if (r.ok) {
        expect(r.phone).toBe("+919876543210");
        expect(r.digits).toBe("9876543210");
      }
    }
  });
  it("rejects bad numbers with plain words", () => {
    expect(checkIndianMobile("")).toMatchObject({ ok: false, message: "Enter your mobile number." });
    expect(checkIndianMobile("98765")).toMatchObject({ ok: false, message: "Enter a 10-digit mobile number." });
    expect(checkIndianMobile("98765432101")).toMatchObject({ ok: false });
    expect(checkIndianMobile("5876543210")).toMatchObject({ ok: false, message: "Mobile numbers start with 6, 7, 8 or 9." });
    expect(checkIndianMobile("9999999999")).toMatchObject({ ok: false });
    expect(checkIndianMobile("98abc43210")).toMatchObject({ ok: false, message: "Use digits only in the phone number." });
  });
  it("cleans a pasted number to 10 digits", () => {
    expect(cleanPhoneInput("+91 98765 43210")).toBe("9876543210");
    expect(cleanPhoneInput("098765 43210")).toBe("9876543210");
    expect(cleanPhoneInput("98765x4321099")).toBe("9876543210");
    expect(cleanPhoneInput("9876")).toBe("9876");
  });
  it("checks the name", () => {
    expect(checkName(" ").ok).toBe(false);
    expect(checkName("A").ok).toBe(false);
    expect(checkName("  Priya   S ")).toEqual({ ok: true, name: "Priya S" });
  });
  it("allows at most 60 characters", () => {
    expect(checkName("a".repeat(60)).ok).toBe(true);
    expect(checkName("a".repeat(61))).toMatchObject({ ok: false });
  });
  it("turns links away", () => {
    for (const bad of ["http://spam.example", "https://x.io/win", "www.free-gift", "visit offers.com now", "pay.in"]) {
      expect(checkName(bad), bad).toMatchObject({ ok: false, message: "Please type just your name, without a link." });
    }
    expect(checkName("Anil Kumar K.")).toMatchObject({ ok: true });
    expect(checkName("Dr. Meena S")).toMatchObject({ ok: true });
  });
});

describe("time grouping", () => {
  const slot = (utc: string, rid = "r1", name = "Ravi") => ({ start_at: utc, resource_id: rid, resource_name: name });
  // IST: 9:30 AM, 11:45 AM, 12:00 PM, 4:59 PM, 5:00 PM, 8:00 PM
  const slots = [
    slot("2026-11-26T14:30:00Z"), // 8:00 PM
    slot("2026-11-26T04:00:00Z"), // 9:30 AM
    slot("2026-11-26T11:29:00Z"), // 4:59 PM
    slot("2026-11-26T06:15:00Z"), // 11:45 AM
    slot("2026-11-26T06:30:00Z"), // 12:00 PM
    slot("2026-11-26T11:30:00Z"), // 5:00 PM
  ];
  it("splits at 12:00 and 5:00 PM IST, in time order", () => {
    const g = groupTimes(slots, false);
    expect(g.map((x) => x.part)).toEqual(["Morning", "Afternoon", "Evening"]);
    expect(g[0].slots.map((s) => formatTime(s.start_at))).toEqual(["9:30 AM", "11:45 AM"]);
    expect(g[1].slots.map((s) => formatTime(s.start_at))).toEqual(["12:00 PM", "4:59 PM"]);
    expect(g[2].slots.map((s) => formatTime(s.start_at))).toEqual(["5:00 PM", "8:00 PM"]);
  });
  it("drops empty groups", () => {
    expect(groupTimes([slot("2026-11-26T14:30:00Z")], false).map((x) => x.part)).toEqual(["Evening"]);
    expect(groupTimes([], false)).toEqual([]);
  });
  it("dedupes equal start times for 'anyone free' and keeps them for a named column", () => {
    const two = [slot("2026-11-26T10:30:00Z", "r1", "Ravi"), slot("2026-11-26T10:30:00Z", "r2", "Meena")];
    expect(groupTimes(two, true)[0].slots).toHaveLength(1);
    expect(groupTimes(two, true)[0].slots[0].resource_name).toBe("Ravi");
    expect(groupTimes(two, false)[0].slots).toHaveLength(2);
  });
  it("classifies day parts by IST hour", () => {
    expect(dayPartOf("2026-11-26T18:30:00Z")).toBe("Morning"); // 12:00 AM next day
  });
});

describe("day grid", () => {
  // 2026-11-26 10:30 UTC = Thu 26 Nov IST
  const now = new Date(THU_4PM).getTime();
  it("covers today through days_ahead and enables only free days", () => {
    const grid = buildDayGrid(now, 14, ["2026-11-27", "2026-12-02"]);
    expect(grid).toHaveLength(15);
    expect(grid[0]).toMatchObject({ date: "2026-11-26", weekday: "Thu", day: 26, month: "Nov", isToday: true, enabled: false });
    expect(grid.filter((c) => c.enabled).map((c) => c.date)).toEqual(["2026-11-27", "2026-12-02"]);
    expect(grid[14].date).toBe("2026-12-10");
  });
  it("uses the IST date, not UTC, when it is late evening in India", () => {
    const lateIst = new Date("2026-11-26T19:00:00Z").getTime(); // 12:30 AM Fri IST
    expect(buildDayGrid(lateIst, 1, [])[0].date).toBe("2026-11-27");
  });
  it("is empty-safe for odd days_ahead", () => {
    expect(buildDayGrid(now, 0, [])).toHaveLength(1);
    expect(buildDayGrid(now, -3, [])).toHaveLength(1);
  });
});

describe("step state machine", () => {
  const slot = { start_at: THU_4PM, resource_id: "r1", resource_name: "Ravi" };
  const run = (...actions: Parameters<typeof flowReducer>[1][]) => actions.reduce(flowReducer, initialFlow);

  it("walks service -> staff -> day -> time -> details", () => {
    expect(run({ type: "service", id: "s1" }).step).toBe("staff");
    expect(run({ type: "service", id: "s1" }, { type: "staff", id: "any" }).step).toBe("day");
    expect(run({ type: "service", id: "s1" }, { type: "staff", id: "any" }, { type: "day", date: "2026-11-26" }).step).toBe("time");
    const done = run({ type: "service", id: "s1" }, { type: "staff", id: "any" }, { type: "day", date: "2026-11-26" }, { type: "time", slot });
    expect(done).toEqual({ step: "details", serviceId: "s1", resourceId: "any", date: "2026-11-26", slot });
  });
  it("ignores an action that skips ahead", () => {
    expect(flowReducer(initialFlow, { type: "staff", id: "r1" })).toBe(initialFlow);
    expect(flowReducer(initialFlow, { type: "day", date: "2026-11-26" })).toBe(initialFlow);
    expect(flowReducer(initialFlow, { type: "time", slot })).toBe(initialFlow);
  });
  const atDetails: FlowState = { step: "details", serviceId: "s1", resourceId: "any", date: "2026-11-26", slot };
  it("editing an earlier step clears everything after it", () => {
    expect(flowReducer(atDetails, { type: "edit", step: "time" })).toEqual({ ...atDetails, step: "time", slot: null });
    expect(flowReducer(atDetails, { type: "edit", step: "day" })).toEqual({ ...atDetails, step: "day", date: null, slot: null });
    expect(flowReducer(atDetails, { type: "edit", step: "staff" })).toEqual({ step: "staff", serviceId: "s1", resourceId: null, date: null, slot: null });
    expect(flowReducer(atDetails, { type: "edit", step: "service" })).toEqual(initialFlow);
  });
  it("cannot reopen a step that is not answered yet", () => {
    const atDay: FlowState = { step: "day", serviceId: "s1", resourceId: "any", date: null, slot: null };
    expect(flowReducer(atDay, { type: "edit", step: "details" })).toBe(atDay);
    expect(flowReducer(atDay, { type: "edit", step: "time" })).toBe(atDay);
  });
  it("a taken slot sends the person back to the times, keeping service/staff/day", () => {
    expect(flowReducer(atDetails, { type: "slotTaken" })).toEqual({ ...atDetails, step: "time", slot: null });
  });
  it("a new service resets staff/day/time", () => {
    expect(flowReducer(atDetails, { type: "service", id: "s2" })).toEqual({ step: "staff", serviceId: "s2", resourceId: null, date: null, slot: null });
  });
});

describe("staff choices", () => {
  const resources = [
    { id: "r1", name: "Ravi", service_ids: ["s1", "s2"] },
    { id: "r2", name: "Meena", service_ids: ["s2"] },
  ];
  it("puts Anyone free first, then only people who do the service", () => {
    expect(staffChoices(resources, "s1").map((c) => c.name)).toEqual(["Anyone free", "Ravi"]);
    expect(staffChoices(resources, "s2").map((c) => c.name)).toEqual(["Anyone free", "Ravi", "Meena"]);
  });
  it("is empty when nobody does the service", () => {
    expect(staffChoices(resources, "s9")).toEqual([]);
  });
});

describe("error words", () => {
  it("maps statuses and server messages", () => {
    expect(classifyError(0, "")).toBe("offline");
    expect(classifyError(429, "")).toBe("busy");
    expect(classifyError(404, "")).toBe("gone");
    expect(classifyError(409, "That time was just taken, pick another")).toBe("slot_taken");
    expect(classifyError(409, "This phone already has a booking that day")).toBe("one_per_day");
    expect(classifyError(400, "It's less than 3 hours away")).toBe("too_late");
    expect(classifyError(500, "")).toBe("other");
  });
  it("handles the newer server messages", () => {
    expect(classifyError(400, "Please enter a 10-digit mobile number")).toBe("bad_phone");
    expect(errorText(400, "Please enter a 10-digit mobile number")).toBe("Please enter a 10-digit mobile number.");
    const waiting = "Too many bookings waiting — please confirm one on WhatsApp first";
    expect(classifyError(429, waiting)).toBe("too_many_waiting");
    expect(errorText(429, waiting)).toBe("Too many bookings waiting. Please confirm one on WhatsApp first.");
    expect(classifyError(429, "Too many requests. Try again in a minute.")).toBe("busy");
    expect(classifyError(403, "Please call the business to change it again")).toBe("too_late");
    expect(errorText(403, "anything")).toBe("Please call the business to change it again.");
  });
  it("shows a generic 409 from the server as it is", () => {
    const msg = "This number can't book this time. Please call the business.";
    expect(classifyError(409, msg)).toBe("show_detail");
    expect(errorText(409, msg)).toBe(msg);
    // the two known 409s keep their own wording
    expect(classifyError(409, "That time is already taken, pick another")).toBe("slot_taken");
    expect(classifyError(409, "This phone already has a booking that day")).toBe("one_per_day");
  });
  it("has a plain message for each kind", () => {
    expect(errorMessage("slot_taken")).toContain("just taken");
    expect(errorMessage("one_per_day")).toContain("already has a booking");
    expect(errorMessage("other")).toContain("Something went wrong");
  });
  it("words the cutoff", () => {
    expect(cutoffText(180)).toBe("3 hours");
    expect(cutoffText(60)).toBe("1 hour");
    expect(cutoffText(90)).toBe("90 minutes");
  });
});

describe("hold countdown", () => {
  const now = new Date("2026-11-26T10:00:00Z").getTime();
  it("counts down to the hold end and stops at zero", () => {
    expect(secondsLeft("2026-11-26T10:15:00Z", now)).toBe(900);
    expect(secondsLeft("2026-11-26T10:14:30.400Z", now)).toBe(871);
    expect(secondsLeft("2026-11-26T09:59:00Z", now)).toBe(0);
  });
  it("returns null when there is no (valid) hold time", () => {
    expect(secondsLeft(null, now)).toBeNull();
    expect(secondsLeft("not a date", now)).toBeNull();
  });
  it("formats m:ss", () => {
    expect(formatCountdown(900)).toBe("15:00");
    expect(formatCountdown(872)).toBe("14:32");
    expect(formatCountdown(5)).toBe("0:05");
    expect(formatCountdown(-4)).toBe("0:00");
  });
});

describe("calendar file", () => {
  const ics = buildIcs({
    code: "BK-0012",
    businessName: "Anil, Hair & Co",
    serviceName: "Reading",
    resourceName: "Ravi",
    startAt: THU_4PM,
    durationMin: 45,
    nowMs: new Date("2026-11-20T00:00:00Z").getTime(),
  });
  it("is a valid VEVENT with CRLF line endings", () => {
    const lines = ics.split("\r\n");
    expect(lines[0]).toBe("BEGIN:VCALENDAR");
    expect(lines).toContain("BEGIN:VEVENT");
    expect(lines).toContain("END:VEVENT");
    expect(lines[lines.length - 2]).toBe("END:VCALENDAR");
    expect(ics.endsWith("\r\n")).toBe(true);
    expect(ics.replace(/\r\n/g, "").includes("\n")).toBe(false);
  });
  it("has the right start, end (start + duration) in UTC", () => {
    expect(ics).toContain("DTSTART:20261126T103000Z");
    expect(ics).toContain("DTEND:20261126T111500Z");
    expect(ics).toContain("DTSTAMP:20261120T000000Z");
  });
  it("escapes commas and includes the code and column", () => {
    expect(ics).toContain("SUMMARY:Reading at Anil\\, Hair & Co");
    expect(ics).toContain("DESCRIPTION:Booking code BK-0012 with Ravi");
  });
  it("folds long lines at 75 characters", () => {
    const long = buildIcs({ code: "BK-1", businessName: "B".repeat(200), serviceName: "S", startAt: THU_4PM, durationMin: 30 });
    for (const line of long.split("\r\n")) expect(line.length).toBeLessThanOrEqual(75);
  });
});

describe("links in hrefs", () => {
  it("only https pay links", () => {
    expect(safePaymentUrl("https://rzp.io/l/abc")).toBe("https://rzp.io/l/abc");
    expect(safePaymentUrl("http://rzp.io/l/abc")).toBeNull();
    expect(safePaymentUrl("javascript:alert(1)")).toBeNull();
    expect(safePaymentUrl("//evil.com")).toBeNull();
    expect(safePaymentUrl("https://a.com/x y")).toBeNull();
    expect(safePaymentUrl(null)).toBeNull();
    expect(safePaymentUrl(undefined)).toBeNull();
  });
  it("only https://wa.me/ WhatsApp links", () => {
    expect(safeWhatsappUrl("https://wa.me/919876543210?text=Hi%2C%20my%20booking%20code%20is%20BK-0012")).toContain("https://wa.me/");
    expect(safeWhatsappUrl("https://api.whatsapp.com/send?phone=1")).toBeNull();
    expect(safeWhatsappUrl("http://wa.me/91987")).toBeNull();
    expect(safeWhatsappUrl("https://wa.me.evil.com/1")).toBeNull();
    expect(safeWhatsappUrl("javascript:alert(1)")).toBeNull();
    expect(safeWhatsappUrl(null)).toBeNull();
  });
});

describe("held booking steps", () => {
  it("step 1 open, step 2 open", () => {
    expect(heldSteps({ phone_checked: false, advance_paise: 20000, advance_paid: false })).toEqual({
      numberConfirmed: false, needsAdvance: true, advancePaid: false, confirming: false,
    });
  });
  it("a missing phone_checked counts as not confirmed", () => {
    expect(heldSteps({ advance_paise: 0, advance_paid: false }).numberConfirmed).toBe(false);
  });
  it("no advance: confirmed number means just waiting for the server", () => {
    const s = heldSteps({ phone_checked: true, advance_paise: 0, advance_paid: false });
    expect(s).toMatchObject({ needsAdvance: false, confirming: true });
  });
  it("advance: needs both", () => {
    expect(heldSteps({ phone_checked: true, advance_paise: 20000, advance_paid: false }).confirming).toBe(false);
    expect(heldSteps({ phone_checked: false, advance_paise: 20000, advance_paid: true }).confirming).toBe(false);
    expect(heldSteps({ phone_checked: true, advance_paise: 20000, advance_paid: true })).toMatchObject({ advancePaid: true, confirming: true });
  });
  it("says Booked! only for booked", () => {
    expect(statusLabel("booked")).toBe("Booked!");
    expect(statusLabel("held")).not.toContain("Booked");
  });
});

describe("polling delay", () => {
  it("10 s normally, 30 s after a 429, back to 10 s after a success", () => {
    expect(nextPollDelay(10_000, "ok")).toBe(10_000);
    expect(nextPollDelay(10_000, "rate_limited")).toBe(30_000);
    expect(nextPollDelay(30_000, "rate_limited")).toBe(30_000);
    expect(nextPollDelay(30_000, "ok")).toBe(10_000);
  });
  it("keeps the delay after another kind of error", () => {
    expect(nextPollDelay(10_000, "error")).toBe(10_000);
    expect(nextPollDelay(30_000, "error")).toBe(30_000);
  });
});

describe("ics text escaping", () => {
  it("escapes backslash first, then semicolon, comma and every kind of newline", () => {
    expect(icsEscape("a\\b")).toBe("a\\\\b");
    expect(icsEscape("a;b,c")).toBe("a\\;b\\,c");
    expect(icsEscape("l1\nl2\r\nl3\rl4")).toBe("l1\\nl2\\nl3\\nl4");
    expect(icsEscape("\\;")).toBe("\\\\\\;");
  });
  it("cannot be used to inject a calendar line", () => {
    const ics = buildIcs({ code: "BK-1", businessName: "X\r\nATTENDEE:mailto:a@b.c", serviceName: "S", startAt: THU_4PM, durationMin: 30 });
    expect(ics.split("\r\n")).not.toContain("ATTENDEE:mailto:a@b.c");
  });
  it("folds by bytes so multi-byte letters are never split", () => {
    const ics = buildIcs({ code: "BK-1", businessName: "வணக்கம்".repeat(20), serviceName: "S", startAt: THU_4PM, durationMin: 30 });
    const enc = new TextEncoder();
    for (const line of ics.split("\r\n")) expect(enc.encode(line).length).toBeLessThanOrEqual(75);
    // unfolding gives the original text back
    expect(ics.replace(/\r\n /g, "")).toContain("வணக்கம்".repeat(20));
  });
});
