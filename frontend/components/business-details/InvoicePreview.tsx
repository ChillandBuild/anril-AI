"use client";

import { useMemo, useState } from "react";
import type { BusinessDetails } from "@/lib/businessDetailsApi";
import {
  billTitle,
  financialYear,
  inr,
  previewBillNumber,
  stateCodeOf,
  taxSplit,
} from "./taxSplit";

// A made-up sale so the owner can see how the bill will look: one item priced at Rs 1,000 with 5% GST.
const SAMPLE_PRICE_PAISE = 100000;
const SAMPLE_GST_RATE = 5;

type Props = {
  details: BusinessDetails;
  /** Links to the saved pictures (the page asks the server for them). */
  logoUrl?: string | null;
  signatureUrl?: string | null;
};

export function InvoicePreview({ details, logoUrl, signatureUrl }: Props) {
  const [customerPlace, setCustomerPlace] = useState<"same" | "other">("same");
  const [customerGstin, setCustomerGstin] = useState("");

  const businessState = stateCodeOf(details.state_code, details.gstin);
  const otherState = businessState === "29" ? "33" : "29";
  const gstinState = stateCodeOf("", customerGstin.trim().toUpperCase());
  const customerState = gstinState || (customerPlace === "other" ? otherState : businessState);
  const taxed = details.gst_type === "regular";

  const money = useMemo(() => {
    if (!taxed) return { taxable: SAMPLE_PRICE_PAISE, gst: 0, total: SAMPLE_PRICE_PAISE };
    if (details.prices_include_gst) {
      const gst = Math.round((SAMPLE_PRICE_PAISE * SAMPLE_GST_RATE) / (100 + SAMPLE_GST_RATE));
      return { taxable: SAMPLE_PRICE_PAISE - gst, gst, total: SAMPLE_PRICE_PAISE };
    }
    const gst = Math.round((SAMPLE_PRICE_PAISE * SAMPLE_GST_RATE) / 100);
    return { taxable: SAMPLE_PRICE_PAISE, gst, total: SAMPLE_PRICE_PAISE + gst };
  }, [taxed, details.prices_include_gst]);

  const split = taxSplit({
    gstPaise: money.gst,
    businessStateCode: businessState,
    customerStateCode: customerState,
    gstType: details.gst_type,
  });

  const name = details.bill_name.trim() || details.legal_name.trim() || "Your business name";
  const place = [details.address.trim(), [details.city.trim(), details.pincode.trim()].filter(Boolean).join(" ")]
    .filter(Boolean)
    .join(", ");
  const number = previewBillNumber(details.bill_prefix, financialYear(new Date()), 1);
  const last4 = details.bank_account_number.replace(/\D/g, "").slice(-4);
  const hasBank = !!(details.bank_name.trim() || last4 || details.bank_ifsc.trim());

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <fieldset className="min-w-0">
          <legend className="mb-1.5 font-label text-xs font-bold uppercase tracking-wider text-ink-secondary">
            Sample customer is in
          </legend>
          <div className="inline-flex overflow-hidden rounded-xl border border-border">
            {(
              [
                ["same", "Your state"],
                ["other", "Another state"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setCustomerPlace(value)}
                aria-pressed={customerPlace === value && !gstinState}
                disabled={!!gstinState}
                className={`px-3 py-2 font-label text-xs font-semibold transition disabled:opacity-60 ${
                  customerPlace === value && !gstinState ? "bg-primary text-white" : "bg-white text-ink-secondary"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </fieldset>
        <label className="min-w-0 flex-1 basis-48">
          <span className="mb-1.5 block font-label text-xs font-bold uppercase tracking-wider text-ink-secondary">
            Customer GSTIN (for a business customer)
          </span>
          <input
            value={customerGstin}
            onChange={(e) => setCustomerGstin(e.target.value.toUpperCase())}
            maxLength={15}
            placeholder="e.g. 29AAAAA0000A1Z5"
            className="w-full rounded-xl border border-border bg-white px-3 py-2 font-mono text-sm uppercase text-ink outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15"
          />
        </label>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-white font-body text-sm text-ink shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border-subtle p-4">
          <div className="flex min-w-0 items-start gap-3">
            {logoUrl && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={logoUrl} alt="Your logo" className="h-14 w-14 shrink-0 rounded-lg object-contain" />
            )}
            <div className="min-w-0">
              <p className="break-words font-display text-base font-bold">{name}</p>
              {place && <p className="break-words text-xs text-ink-secondary">{place}</p>}
              <p className="mt-1 flex flex-wrap gap-x-3 text-xs text-ink-secondary">
                {details.gst_type === "regular" && details.gstin && <span>GSTIN {details.gstin}</span>}
                {details.pan && <span>PAN {details.pan}</span>}
                {details.licence_number && <span>Licence {details.licence_number}</span>}
              </p>
            </div>
          </div>
          <div className="text-right">
            <p className="font-label text-xs font-bold uppercase tracking-wider text-ink-secondary">
              {billTitle(details.gst_type)}
            </p>
            <p className="font-mono text-sm font-semibold">{number}</p>
          </div>
        </div>

        <div className="border-b border-border-subtle px-4 py-3 text-xs text-ink-secondary">
          <p>
            Bill to: <span className="font-semibold text-ink">Sample Customer</span>
            {customerState ? ` · State code ${customerState}` : ""}
          </p>
          {customerGstin.trim() && <p>Customer GSTIN: {customerGstin.trim()}</p>}
        </div>

        <div className="space-y-1.5 px-4 py-3">
          <Row label="Cotton kurti × 1" value={inr(money.taxable)} />
          {taxed && split.igst_paise > 0 && <Row label={`IGST ${SAMPLE_GST_RATE}%`} value={inr(split.igst_paise)} />}
          {taxed && split.cgst_paise > 0 && (
            <>
              <Row label={`CGST ${SAMPLE_GST_RATE / 2}%`} value={inr(split.cgst_paise)} />
              <Row label={`SGST ${SAMPLE_GST_RATE / 2}%`} value={inr(split.sgst_paise)} />
            </>
          )}
          <div className="border-t border-border-subtle pt-1.5">
            <Row label="Total" value={inr(money.total)} strong />
          </div>
          {!taxed && (
            <p className="pt-1 text-xs text-ink-secondary">
              {details.gst_type === "composition"
                ? "Composition dealer: no tax is collected on this bill."
                : "Not GST registered: no tax on this bill."}
            </p>
          )}
        </div>

        {(details.upi_id || hasBank) && (
          <div className="border-t border-border-subtle px-4 py-3 text-xs text-ink-secondary">
            {details.upi_id && <p>Pay by UPI: <span className="font-semibold text-ink">{details.upi_id}</span></p>}
            {hasBank && (
              <p>
                Bank: {[details.bank_account_name, details.bank_name].filter(Boolean).join(", ")}
                {last4 ? ` · A/c ••••${last4}` : ""}
                {details.bank_ifsc ? ` · IFSC ${details.bank_ifsc}` : ""}
              </p>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-end justify-between gap-3 border-t border-border-subtle px-4 py-3">
          <p className="min-w-0 max-w-xs whitespace-pre-line break-words text-xs text-ink-secondary">
            {details.terms.trim() || "Your terms and conditions show here."}
          </p>
          <div className="text-center">
            {signatureUrl && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={signatureUrl} alt="Your signature" className="mx-auto h-10 max-w-[140px] object-contain" />
            )}
            <p className="border-t border-border pt-1 text-xs text-ink-secondary">Authorised signatory</p>
          </div>
        </div>
      </div>
      <p className="mt-2 text-xs text-ink-secondary">
        A sample sale of one item at ₹1,000 with 5% GST, only to show the layout. It is not saved anywhere.
      </p>
    </div>
  );
}

function Row({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={`flex items-baseline justify-between gap-3 ${strong ? "font-bold" : ""}`}>
      <span>{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}
