/** Pure helpers for the invoice preview on Settings > Business details. No React, no network. */

export type GstType = "regular" | "composition" | "none";

export interface TaxSplit {
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
}

/** The two-digit GST state code: the one typed in, else the first two digits of the GSTIN, else "". */
export function stateCodeOf(stateCode: string | null | undefined, gstin: string | null | undefined): string {
  const typed = (stateCode ?? "").trim();
  if (/^\d{2}$/.test(typed)) return typed;
  const fromGstin = (gstin ?? "").trim().slice(0, 2);
  return /^\d{2}$/.test(fromGstin) ? fromGstin : "";
}

/**
 * Same state: half CGST and half SGST (an odd paisa goes to CGST, as the backend does).
 * Another state: all IGST. If either state is unknown we assume the same state, like the backend.
 * A shop that is not "regular" (composition or not registered) charges no GST on the bill.
 */
export function taxSplit(args: {
  gstPaise: number;
  businessStateCode: string;
  customerStateCode: string;
  gstType?: GstType;
}): TaxSplit {
  const gst = Math.max(0, Math.round(args.gstPaise || 0));
  const none: TaxSplit = { cgst_paise: 0, sgst_paise: 0, igst_paise: 0 };
  if (!gst || (args.gstType && args.gstType !== "regular")) return none;
  const a = args.businessStateCode;
  const b = args.customerStateCode;
  if (a && b && a !== b) return { cgst_paise: 0, sgst_paise: 0, igst_paise: gst };
  const half = Math.floor(gst / 2);
  return { cgst_paise: gst - half, sgst_paise: half, igst_paise: 0 };
}

/** What the paper is called: a registered shop issues a tax invoice, a composition shop a bill of supply. */
export function billTitle(gstType: GstType): string {
  if (gstType === "composition") return "Bill of supply";
  if (gstType === "none") return "Bill";
  return "Tax invoice";
}

/** The number as the backend will write it: DS/26-27/0001, or 2026-27/0001 with no prefix. */
export function previewBillNumber(prefix: string, fy: string, n: number): string {
  const cleaned = prefix.trim().toUpperCase();
  const seq = String(n).padStart(4, "0");
  return cleaned ? `${cleaned}/${fy.slice(2)}/${seq}` : `${fy}/${seq}`;
}

/** Indian financial year (April to March) for a date: Nov 2026 -> "2026-27". */
export function financialYear(at: Date): string {
  const start = at.getMonth() >= 3 ? at.getFullYear() : at.getFullYear() - 1;
  return `${start}-${String(start + 1).slice(-2)}`;
}

/** Same rule as the server: capital letters and digits only, up to 6. Returns "" for nothing. */
export function cleanPrefix(raw: string): string {
  return raw.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 6);
}

export const PAN_PATTERN = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
export const IFSC_PATTERN = /^[A-Z]{4}0[A-Z0-9]{6}$/;
export const UPI_PATTERN = /^[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9.-]{1,63}$/;

/** "₹1,234" or "₹1,234.50" from paise. */
export function inr(paise: number): string {
  const rupees = paise / 100;
  const whole = Number.isInteger(rupees);
  return `₹${rupees.toLocaleString("en-IN", { minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2 })}`;
}
