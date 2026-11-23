// What a shop prints on its bill besides the items (Settings > Business details & bills): logo,
// signature, PAN, licence number, UPI ID, bank details, terms, and the "Bill of supply" title of a
// composition-scheme shop. The backend (services/bill_brand.py) sends these as `brand`, `title` and
// `composition` on the public bill. A shop that set none of them gets the bill it always had.

export interface BillBrand {
  pan: string;
  licence_number: string;
  upi_id: string;
  terms: string;
  bank: { account_name: string; bank_name: string; ifsc: string; account_number: string };
  logo_url: string | null;
  signature_url: string | null;
}

export interface BillExtras {
  brand?: BillBrand | null;
  title?: string;
  composition?: boolean;
}

export interface BillTitleInput extends BillExtras {
  quote?: unknown;
  bill_type: "gst" | "simple";
}

/** "Quotation", "Bill of supply" (composition shop), "Tax invoice" (GST bill) or plain "Bill". */
export function billTitle(bill: BillTitleInput): string {
  if (bill.quote) return "Quotation";
  if (bill.title) return bill.title;
  return bill.bill_type === "gst" ? "Tax invoice" : "Bill";
}

/** Tax columns and lines show only on a tax invoice: never on a quote, a simple bill or a bill of supply. */
export function showsTax(bill: BillTitleInput): boolean {
  return bill.bill_type === "gst" && !bill.composition;
}

/** "HDFC Bank · Name", then "A/c no. 1234 · IFSC HDFC0001234": short lines, empty parts left out. */
export function bankLines(brand: BillBrand | null | undefined): string[] {
  const bank = brand?.bank;
  if (!bank) return [];
  const out: string[] = [];
  const head = [bank.bank_name, bank.account_name].filter(Boolean).join(" · ");
  if (head) out.push(head);
  const detail = [bank.account_number ? `A/c no. ${bank.account_number}` : "", bank.ifsc ? `IFSC ${bank.ifsc}` : ""].filter(Boolean).join(" · ");
  if (detail) out.push(detail);
  return out;
}

/** Is there anything to say under "How to pay": a UPI ID or bank details. */
export function hasPayBlock(brand: BillBrand | null | undefined): boolean {
  return !!brand && (!!brand.upi_id || bankLines(brand).length > 0);
}

/** PAN and licence number as one line ("PAN ABCDE1234F · Licence 123"), or "" when neither is set. */
export function idsLine(brand: BillBrand | null | undefined): string {
  if (!brand) return "";
  return [brand.pan ? `PAN ${brand.pan}` : "", brand.licence_number ? `Licence ${brand.licence_number}` : ""].filter(Boolean).join(" · ");
}

export interface AdvanceChange {
  from_paise: number;
  to_paise: number;
  by: string | null;
  at: string | null;
}

function rupees(paise: number): string {
  return "₹" + (paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

/** "Advance changed ₹500 → ₹300 by Ravi, 23 Nov" (the name and date are left out when unknown). */
export function advanceChangeText(c: AdvanceChange): string {
  const when = c.at ? new Date(c.at) : null;
  const day = when && !Number.isNaN(when.getTime()) ? when.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" }) : "";
  const who = [c.by ? `by ${c.by}` : "", day].filter(Boolean).join(", ");
  return `Advance changed ${rupees(c.from_paise)} → ${rupees(c.to_paise)}${who ? " " + who : ""}`;
}

/** The API leaves cost prices out for people without Orders & payments access (`costs_hidden`). */
export function costsHidden(row: { costs_hidden?: boolean } | null | undefined): boolean {
  return !!row?.costs_hidden;
}
