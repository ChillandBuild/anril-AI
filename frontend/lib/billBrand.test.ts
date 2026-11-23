import { describe, expect, it } from "vitest";
import { advanceChangeText, bankLines, billTitle, costsHidden, hasPayBlock, idsLine, showsTax, type BillBrand } from "./billBrand";

const empty: BillBrand = { pan: "", licence_number: "", upi_id: "", terms: "", bank: { account_name: "", bank_name: "", ifsc: "", account_number: "" }, logo_url: null, signature_url: null };

describe("billTitle", () => {
  it("keeps today's titles for a shop that set nothing", () => {
    expect(billTitle({ bill_type: "gst" })).toBe("Tax invoice");
    expect(billTitle({ bill_type: "simple" })).toBe("Bill");
  });
  it("says Bill of supply for a composition shop and Quotation for a quote", () => {
    expect(billTitle({ bill_type: "gst", title: "Bill of supply", composition: true })).toBe("Bill of supply");
    expect(billTitle({ bill_type: "gst", title: "Bill of supply", quote: {} })).toBe("Quotation");
  });
});

describe("showsTax", () => {
  it("is false for a composition shop even on a gst bill", () => {
    expect(showsTax({ bill_type: "gst" })).toBe(true);
    expect(showsTax({ bill_type: "gst", composition: true })).toBe(false);
    expect(showsTax({ bill_type: "simple" })).toBe(false);
  });
});

describe("pay block", () => {
  it("is empty when nothing is set", () => {
    expect(hasPayBlock(empty)).toBe(false);
    expect(hasPayBlock(null)).toBe(false);
    expect(bankLines(empty)).toEqual([]);
    expect(idsLine(empty)).toBe("");
  });
  it("lists bank lines, UPI and ids", () => {
    const b = { ...empty, upi_id: "shop@okhdfc", bank: { account_name: "Demo Silks", bank_name: "HDFC Bank", ifsc: "HDFC0001234", account_number: "50100" }, pan: "ABCDE1234F", licence_number: "L-9" };
    expect(hasPayBlock(b)).toBe(true);
    expect(bankLines(b)).toEqual(["HDFC Bank · Demo Silks", "A/c no. 50100 · IFSC HDFC0001234"]);
    expect(idsLine(b)).toBe("PAN ABCDE1234F · Licence L-9");
    expect(hasPayBlock({ ...empty, upi_id: "a@b" })).toBe(true);
  });
});

describe("advanceChangeText", () => {
  it("reads like the owner would say it", () => {
    expect(advanceChangeText({ from_paise: 50000, to_paise: 30000, by: "Ravi", at: "2026-11-23T08:00:00+00:00" })).toBe("Advance changed ₹500 → ₹300 by Ravi, 23 Nov");
  });
  it("leaves out an unknown name or date", () => {
    expect(advanceChangeText({ from_paise: 50000, to_paise: 0, by: null, at: null })).toBe("Advance changed ₹500 → ₹0");
  });
});

describe("costsHidden", () => {
  it("is true only when the API says so", () => {
    expect(costsHidden({ costs_hidden: true })).toBe(true);
    expect(costsHidden({})).toBe(false);
    expect(costsHidden(null)).toBe(false);
  });
});
