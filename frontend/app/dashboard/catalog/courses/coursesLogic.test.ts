import { describe, expect, it } from "vitest";
import { dayText, dropNotice, modeLabel, partLabel, partsProblem, reminderHelp, rupees, rupeesToPaise, seatsText, splitParts } from "./coursesLogic";

describe("money", () => {
  it("formats rupees", () => {
    expect(rupees(500000)).toBe("₹5,000");
    expect(rupees(500050)).toBe("₹5,000.50");
    expect(rupees(undefined)).toBe("₹0");
  });
  it("reads what people type", () => {
    expect(rupeesToPaise("5,000")).toBe(500000);
    expect(rupeesToPaise("₹ 5000.5")).toBe(500050);
    expect(rupeesToPaise("abc")).toBeNull();
    expect(rupeesToPaise("")).toBeNull();
  });
});

describe("fee plan parts", () => {
  it("splits with the leftover on the first part", () => {
    const parts = splitParts(1000001, 3, "2026-12-01");
    expect(parts.map((p) => p.amount_paise)).toEqual([333335, 333333, 333333]);
    expect(parts.map((p) => p.due_on)).toEqual(["2026-12-01", "2026-12-31", "2027-01-30"]);
    expect(splitParts(900000, 0, "2026-12-01")).toHaveLength(1);
    expect(splitParts(900000, 99, "2026-12-01")).toHaveLength(24);
  });
  it("explains a plan that does not add up", () => {
    const ok = splitParts(900000, 3, "2026-12-01");
    expect(partsProblem(ok, 900000)).toBeNull();
    expect(partsProblem(ok, 800000)).toBe("The parts add up to ₹9,000 but the fee is ₹8,000");
    expect(partsProblem([{ due_on: "soon", amount_paise: 5 }], 5)).toMatch(/due date/);
    expect(partsProblem([{ due_on: "2026-12-01", amount_paise: 0 }], 0)).toMatch(/more than/);
    expect(partsProblem([], 0)).toMatch(/1 to 24/);
  });
});

describe("words", () => {
  it("says the seats", () => {
    expect(seatsText({ status: "open", seats_left: 3, seats_total: 20, seats_waiting: 2 })).toBe("3 of 20 seats left (2 yet to pay)");
    expect(seatsText({ status: "full", seats_left: 0, seats_total: 20, seats_waiting: 0 })).toBe("Full");
    expect(seatsText({ status: "closed", seats_left: 5, seats_total: 20, seats_waiting: 0 })).toBe("Closed");
  });
  it("formats days and parts", () => {
    expect(dayText("2026-11-28", 2026)).toBe("28 Nov");
    expect(dayText("2027-01-05", 2026)).toBe("5 Jan 2027");
    expect(dayText(null)).toBe("");
    expect(partLabel({ paid: true, late: false, due_on: "2026-11-28" })).toBe("Paid");
    expect(partLabel({ paid: false, late: true, due_on: "2020-11-28" })).toContain("Late");
    expect(modeLabel("both")).toBe("Online and in person");
  });
  it("explains the reminder switch", () => {
    expect(reminderHelp({ enabled: false, template: null, template_body: "" })).toMatch(/First send/);
    expect(reminderHelp({ enabled: false, template: "PENDING", template_body: "" })).toMatch(/still checking/);
    expect(reminderHelp({ enabled: true, template: "APPROVED", template_body: "" })).toMatch(/3 days before/);
  });
});

describe("dropping a student", () => {
  it("tells the owner when the order was kept because money was paid", () => {
    expect(dropNotice({ order_cancelled: false, paid_paise: 300000 })).toBe("Order kept: this student has paid ₹3,000. Refund it from the order if needed.");
    expect(dropNotice({ order_cancelled: true, paid_paise: 0 })).toBe("");
    expect(dropNotice({ order_cancelled: false, paid_paise: 0 })).toBe("");
  });
  it("marks a part paid on the order itself", () => {
    expect(partLabel({ paid: true, late: false, due_on: "2026-11-28", on_order: true })).toBe("Paid on the order");
  });
});
