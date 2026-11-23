import { describe, expect, it } from "vitest";
import { actionLabel, activityDetail, isMoneyRow, typeOptions } from "@/lib/activityLog";

describe("activity log words", () => {
  it("names the new rows in plain words and leaves old ones as they are", () => {
    expect(actionLabel("order.refund")).toBe("Refund given");
    expect(actionLabel("auth.login")).toBe("Signed in");
    expect(actionLabel("team.member_created")).toBe("team.member_created");
  });

  it("flags money rows even without the server flag", () => {
    expect(isMoneyRow({ action: "order.discount", metadata: {} })).toBe(true);
    expect(isMoneyRow({ action: "auth.login", metadata: {}, money: false })).toBe(false);
    expect(isMoneyRow({ action: "team.member_created", metadata: {}, money: true })).toBe(true);
  });

  it("shows rupees on money rows only to people who may see money", () => {
    const refund = { action: "order.refund", metadata: { amount_paise: 150000, method: "cash", reason: "wrong size", order: "D-7" } };
    expect(activityDetail(refund, true)).toBe("₹1,500 · cash · wrong size · order D-7");
    expect(activityDetail(refund, false)).toBe("");
    const discount = { action: "order.discount", metadata: { discount_paise: 50000, subtotal_paise: 100000, kind: "bill" } };
    expect(activityDetail(discount, true)).toBe("₹500 off a ₹1,000 bill");
    const advance = { action: "order.advance_changed", metadata: { from_paise: 50000, to_paise: 30000 } };
    expect(activityDetail(advance, true)).toBe("₹500 to ₹300");
  });

  it("describes a login by address and device, and hides stray rupee keys from others", () => {
    expect(activityDetail({ action: "auth.login", metadata: { ip: "1.2.3.4", device: "Chrome" } }, false)).toBe("from 1.2.3.4 · Chrome");
    expect(activityDetail({ action: "team.member_updated", metadata: { name: "Ravi", fee_paise: 500 } }, false)).toBe("name: Ravi");
  });

  it("offers only the types the server allows", () => {
    expect(typeOptions(["team", "roles", "login"]).map((o) => o.value)).toEqual(["", "team", "roles", "login"]);
    expect(typeOptions(["team", "money"]).map((o) => o.value)).toEqual(["", "team", "money"]);
  });
});
