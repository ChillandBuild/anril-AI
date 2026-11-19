import { describe, expect, it } from "vitest";
import { computeBill } from "./billMath";

// The same cases as backend tests/test_orders.py, so both sides agree to the paisa.
describe("computeBill", () => {
  it("spreads the discount and keeps GST inside the price", () => {
    const bill = computeBill(
      [{ unit_price_paise: 890000, qty: 1, gst_rate: 5 }, { unit_price_paise: 160000, qty: 1, gst_rate: 5 }],
      { discount_paise: 50000, include_gst: true, bill_type: "gst" },
    );
    expect(bill).toEqual({ subtotal_paise: 1050000, discount_paise: 50000, gst_paise: 47619, total_paise: 1000000 });
  });

  it("adds GST on top, and a simple bill has none", () => {
    const lines = [{ unit_price_paise: 100000, qty: 2, gst_rate: 12 }];
    expect(computeBill(lines, { discount_paise: 0, include_gst: false, bill_type: "gst" }).total_paise).toBe(224000);
    expect(computeBill(lines, { discount_paise: 0, include_gst: false, bill_type: "simple" })).toMatchObject({ total_paise: 200000, gst_paise: 0 });
  });

  it("never discounts below zero", () => {
    expect(computeBill([{ unit_price_paise: 5000, qty: 1, gst_rate: null }], { discount_paise: 99999, include_gst: true, bill_type: "gst" }).total_paise).toBe(0);
  });
});
