import { describe, expect, it } from "vitest";
import {
  billTitle,
  cleanPrefix,
  financialYear,
  IFSC_PATTERN,
  inr,
  PAN_PATTERN,
  previewBillNumber,
  stateCodeOf,
  taxSplit,
  UPI_PATTERN,
} from "./taxSplit";

describe("taxSplit", () => {
  it("splits into CGST + SGST inside the state", () => {
    expect(taxSplit({ gstPaise: 5000, businessStateCode: "33", customerStateCode: "33" })).toEqual({
      cgst_paise: 2500, sgst_paise: 2500, igst_paise: 0,
    });
  });
  it("gives the odd paisa to CGST so the two add up", () => {
    const s = taxSplit({ gstPaise: 5001, businessStateCode: "33", customerStateCode: "33" });
    expect(s.cgst_paise + s.sgst_paise).toBe(5001);
    expect(s.cgst_paise).toBe(2501);
  });
  it("charges IGST alone for another state", () => {
    expect(taxSplit({ gstPaise: 5000, businessStateCode: "33", customerStateCode: "29" })).toEqual({
      cgst_paise: 0, sgst_paise: 0, igst_paise: 5000,
    });
  });
  it("treats an unknown state as the same state", () => {
    expect(taxSplit({ gstPaise: 400, businessStateCode: "33", customerStateCode: "" }).igst_paise).toBe(0);
    expect(taxSplit({ gstPaise: 400, businessStateCode: "", customerStateCode: "29" }).cgst_paise).toBe(200);
  });
  it("charges no tax on a composition or not-registered bill", () => {
    for (const gstType of ["composition", "none"] as const) {
      expect(taxSplit({ gstPaise: 5000, businessStateCode: "33", customerStateCode: "29", gstType })).toEqual({
        cgst_paise: 0, sgst_paise: 0, igst_paise: 0,
      });
    }
  });
  it("is zero for no tax", () => {
    expect(taxSplit({ gstPaise: 0, businessStateCode: "33", customerStateCode: "29" }).igst_paise).toBe(0);
  });
});

describe("stateCodeOf", () => {
  it("prefers the typed code, then the GSTIN", () => {
    expect(stateCodeOf("29", "33AAAAA0000A1Z5")).toBe("29");
    expect(stateCodeOf("", "33AAAAA0000A1Z5")).toBe("33");
    expect(stateCodeOf("x", "")).toBe("");
  });
});

describe("bill numbers", () => {
  it("matches the server format", () => {
    expect(previewBillNumber("", "2026-27", 1)).toBe("2026-27/0001");
    expect(previewBillNumber("ds", "2026-27", 45)).toBe("DS/26-27/0045");
  });
  it("finds the financial year", () => {
    expect(financialYear(new Date(2026, 10, 23))).toBe("2026-27");
    expect(financialYear(new Date(2027, 2, 31))).toBe("2026-27");
    expect(financialYear(new Date(2027, 3, 1))).toBe("2027-28");
  });
  it("cleans the prefix like the server", () => {
    expect(cleanPrefix("d s/1-x!abcdefg")).toBe("DS1XAB");
  });
  it("names the paper", () => {
    expect(billTitle("regular")).toBe("Tax invoice");
    expect(billTitle("composition")).toBe("Bill of supply");
    expect(billTitle("none")).toBe("Bill");
  });
});

describe("patterns and money", () => {
  it("checks PAN, IFSC and UPI", () => {
    expect(PAN_PATTERN.test("ABCDE1234F")).toBe(true);
    expect(PAN_PATTERN.test("ABCDE12345")).toBe(false);
    expect(IFSC_PATTERN.test("SBIN0001234")).toBe(true);
    expect(IFSC_PATTERN.test("SBIN1001234")).toBe(false);
    expect(UPI_PATTERN.test("shop@okbank")).toBe(true);
    expect(UPI_PATTERN.test("shop")).toBe(false);
  });
  it("formats paise", () => {
    expect(inr(123400)).toBe("₹1,234");
    expect(inr(123450)).toBe("₹1,234.50");
  });
});
