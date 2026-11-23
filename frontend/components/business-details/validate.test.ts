import { describe, expect, it } from "vitest";
import { EMPTY_BUSINESS_DETAILS } from "@/lib/businessDetailsApi";
import { businessDetailErrors } from "./validate";

const base = EMPTY_BUSINESS_DETAILS;

describe("businessDetailErrors", () => {
  it("is empty for a blank form and for good values", () => {
    expect(businessDetailErrors(base)).toEqual({});
    expect(
      businessDetailErrors({
        ...base,
        gstin: "33AAAAA0000A1Z5",
        pan: "ABCDE1234F",
        bank_ifsc: "SBIN0001234",
        upi_id: "shop@okbank",
        bank_account_number: "123456789012",
        state_code: "33",
      }),
    ).toEqual({});
  });
  it("names each wrong field", () => {
    const e = businessDetailErrors({
      ...base, gstin: "33AAAAA", pan: "123", bank_ifsc: "X", upi_id: "nope", bank_account_number: "12ab", state_code: "3",
    });
    expect(Object.keys(e).sort()).toEqual(["bank_account_number", "bank_ifsc", "gstin", "pan", "state_code", "upi_id"]);
  });
  it("accepts the masked account number the server sends back", () => {
    expect(businessDetailErrors({ ...base, bank_account_number: "••••9012" })).toEqual({});
  });
});
