import type { BusinessDetails } from "@/lib/businessDetailsApi";
import { IFSC_PATTERN, PAN_PATTERN, UPI_PATTERN } from "./taxSplit";

export type FieldErrors = Partial<
  Record<"gstin" | "pan" | "bank_ifsc" | "upi_id" | "bank_account_number" | "state_code", string>
>;

export const GSTIN_PATTERN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

/** What is wrong with the typed details, in plain words, per field. An empty object means good to save. */
export function businessDetailErrors(d: BusinessDetails): FieldErrors {
  const errors: FieldErrors = {};
  const gstin = d.gstin.trim();
  if (gstin && !GSTIN_PATTERN.test(gstin)) errors.gstin = "Doesn't look like a valid GSTIN";
  if (d.pan.trim() && !PAN_PATTERN.test(d.pan.trim())) errors.pan = "Doesn't look like a valid PAN (like ABCDE1234F)";
  if (d.bank_ifsc.trim() && !IFSC_PATTERN.test(d.bank_ifsc.trim())) {
    errors.bank_ifsc = "Doesn't look like a valid IFSC (like SBIN0001234)";
  }
  if (d.upi_id.trim() && !UPI_PATTERN.test(d.upi_id.trim())) {
    errors.upi_id = "Doesn't look like a UPI ID (like shopname@upi)";
  }
  const acct = d.bank_account_number.trim();
  if (acct && !acct.startsWith("•") && !/^[0-9]{5,20}$/.test(acct)) {
    errors.bank_account_number = "Digits only, 5 to 20 of them";
  }
  if (d.state_code.trim() && !/^[0-9]{2}$/.test(d.state_code.trim())) errors.state_code = "Two digits";
  return errors;
}
