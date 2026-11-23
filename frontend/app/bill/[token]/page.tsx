"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Check, Download, Loader2 } from "lucide-react";
import { acceptPublicQuote, fetchPublicBill, type PublicBill as ApiBill } from "@/lib/api";
import { bankLines, billTitle, hasPayBlock, idsLine, showsTax, type BillExtras } from "@/lib/billBrand";

// The API adds logo, signature, UPI, bank, terms and the Bill of supply title (lib/billBrand.ts).
type PublicBill = ApiBill & BillExtras;

// The customer's bill, opened from the WhatsApp link. No sign-in: the link's secret token is
// the key. "Download PDF" prints this page (Save as PDF), so the PDF is exactly what they see.

function rupees(paise: number): string {
  return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function dateText(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export default function BillPage() {
  const { token } = useParams<{ token: string }>();
  const [bill, setBill] = useState<PublicBill | null | undefined>(undefined);
  const [failed, setFailed] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [accepted, setAccepted] = useState<{ status: string; payment_link: string | null; advance_paise: number } | null>(null);

  async function accept() {
    setAccepting(true);
    try {
      setAccepted(await acceptPublicQuote(token));
    } catch {
      setAccepted({ status: "error", payment_link: null, advance_paise: 0 });
    } finally {
      setAccepting(false);
    }
  }

  useEffect(() => {
    fetchPublicBill(token).then(setBill).catch(() => setFailed(true));
  }, [token]);

  useEffect(() => {
    if (bill) document.title = `${billTitle(bill)} ${bill.invoice_number ?? bill.order_label} · ${bill.business.legal_name}`;
  }, [bill]);

  if (failed) return <Shell><p className="py-24 text-center text-sm text-slate-500">This bill couldn&apos;t be loaded. Check your connection and open the link again.</p></Shell>;
  if (bill === undefined) return <Shell><div className="flex justify-center py-24"><Loader2 className="animate-spin text-slate-400" /></div></Shell>;
  if (bill === null) return <Shell><p className="py-24 text-center text-sm text-slate-500">This bill link isn&apos;t valid. Ask the shop to send it again.</p></Shell>;

  const b = bill.business;
  const q = bill.quote;
  const isGst = showsTax(bill);
  const brand = bill.brand ?? null;
  const ids = idsLine(brand);
  const title = billTitle(bill);
  const place = [b.address, b.city, b.state, b.pincode].filter(Boolean).join(", ");
  return (
    <Shell>
      {q && !accepted && (
        <div className="mx-auto mb-4 flex max-w-[760px] flex-wrap items-center justify-between gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 print:hidden">
          <p className="text-sm text-emerald-900">
            {q.expired ? "This quote has expired. Ask the shop for a fresh one."
              : <>Happy with this quote? Accept it{q.advance_paise ? ` and pay the ${rupees(q.advance_paise)} advance` : ""} to confirm your order.</>}
          </p>
          {!q.expired && (
            <button type="button" onClick={accept} disabled={accepting}
              className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-sm font-bold text-white shadow-sm hover:bg-emerald-700 disabled:opacity-60">
              {accepting ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} Accept quote
            </button>
          )}
        </div>
      )}
      {accepted && (
        <div className="mx-auto mb-4 flex max-w-[760px] flex-wrap items-center justify-between gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 print:hidden">
          <p className="text-sm font-semibold text-emerald-900">
            {accepted.status === "accepted" || accepted.status === "already"
              ? `Order confirmed. Thank you!${accepted.payment_link ? ` Pay the ${rupees(accepted.advance_paise)} advance to start.` : ""}`
              : accepted.status === "expired" ? "This quote has expired. Ask the shop for a fresh one." : "This quote couldn't be accepted. Please message the shop."}
          </p>
          {accepted.payment_link && (
            <a href={accepted.payment_link} className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-bold text-white shadow-sm hover:bg-emerald-700">
              Pay {rupees(accepted.advance_paise)}
            </a>
          )}
        </div>
      )}
      <div className="mx-auto mb-4 flex max-w-[760px] justify-end gap-2 print:hidden">
        {!q && bill.pay_link && bill.balance_paise > 0 && (
          <a href={bill.pay_link} className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-bold text-white shadow-sm hover:bg-emerald-700">
            Pay {rupees(bill.balance_paise)}
          </a>
        )}
        <button type="button" onClick={() => window.print()}
          className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-700 shadow-sm hover:border-slate-300">
          <Download size={15} /> Download PDF
        </button>
      </div>

      <article className="mx-auto max-w-[760px] rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-10 print:rounded-none print:border-0 print:p-0 print:shadow-none">
        <header className="flex flex-wrap items-start justify-between gap-6 border-b border-slate-200 pb-6">
          <div className="min-w-0">
            {brand?.logo_url && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={brand.logo_url} alt="" className="mb-2 max-h-16 w-auto max-w-[180px] object-contain" />
            )}
            <h1 className="text-xl font-bold text-slate-900">{b.legal_name || "Bill"}</h1>
            {place && <p className="mt-1 max-w-xs text-xs leading-5 text-slate-500">{place}</p>}
            {(b.phone || b.email) && <p className="text-xs text-slate-500">{[b.phone, b.email].filter(Boolean).join(" · ")}</p>}
            {(isGst || bill.composition) && b.gstin && <p className="mt-1 text-xs font-semibold text-slate-700">GSTIN {b.gstin}</p>}
            {ids && <p className="text-xs text-slate-600">{ids}</p>}
          </div>
          <div className="text-right">
            <p className="text-xs font-bold uppercase tracking-[0.14em] text-slate-600">{title}</p>
            <p className="mt-1 text-lg font-bold text-slate-900">{q ? bill.order_label : bill.invoice_number ?? bill.order_label}</p>
            <p className="text-xs text-slate-500">{dateText(bill.invoice_date)}{q ? "" : ` · Order ${bill.order_label}`}</p>
            {q?.valid_until && <p className="text-xs font-semibold text-slate-600">Valid till {dateText(q.valid_until)}</p>}
            {bill.cancelled && <p className="mt-1 text-xs font-bold text-rose-600">Cancelled</p>}
          </div>
        </header>

        <section className="grid gap-1 py-5 text-sm">
          <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">{q ? "Quote for" : "Billed to"}</p>
          <p className="font-semibold text-slate-900">{bill.customer.business || bill.customer.name || "Customer"}</p>
          {bill.customer.business && bill.customer.name && <p className="text-xs text-slate-500">{bill.customer.name}</p>}
          {bill.customer.phone && <p className="text-xs text-slate-500">{bill.customer.phone}</p>}
          {bill.customer.gstin && <p className="text-xs font-semibold text-slate-700">GSTIN {bill.customer.gstin}</p>}
        </section>

        <table className="w-full text-sm">
          <thead>
            <tr className="border-y border-slate-200 text-left text-[11px] font-bold uppercase tracking-wider text-slate-400">
              <th className="py-2.5 pr-2">Item</th>
              <th className="py-2.5 px-2 text-right">Qty</th>
              <th className="py-2.5 px-2 text-right">Rate</th>
              {isGst && <th className="py-2.5 px-2 text-right">GST</th>}
              <th className="py-2.5 pl-2 text-right">Amount</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {bill.lines.map((l, i) => (
              <tr key={i}>
                <td className="py-3 pr-2">
                  <span className="font-semibold text-slate-900">{l.name}</span>
                  {l.variant && <span className="block text-xs text-slate-500">{l.variant}</span>}
                </td>
                <td className="py-3 px-2 text-right tabular-nums">{l.qty}</td>
                <td className="py-3 px-2 text-right tabular-nums">{rupees(l.unit_price_paise)}</td>
                {isGst && <td className="py-3 px-2 text-right tabular-nums text-slate-500">{l.gst_rate != null ? `${l.gst_rate}%` : "—"}</td>}
                <td className="py-3 pl-2 text-right font-semibold tabular-nums">{rupees(l.amount_paise)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <dl className="ml-auto mt-4 max-w-xs space-y-1.5 border-t border-slate-200 pt-4 text-sm">
          <Row label="Items" value={rupees(bill.subtotal_paise)} />
          {bill.discount_paise > 0 && <Row label="Discount" value={`− ${rupees(bill.discount_paise)}`} />}
          {isGst && bill.gst_paise > 0 && (
            bill.igst_paise > 0
              ? <Row label={bill.prices_include_gst ? "IGST (included)" : "IGST"} value={rupees(bill.igst_paise)} muted />
              : <>
                  <Row label={bill.prices_include_gst ? "CGST (included)" : "CGST"} value={rupees(bill.cgst_paise)} muted />
                  <Row label={bill.prices_include_gst ? "SGST (included)" : "SGST"} value={rupees(bill.sgst_paise)} muted />
                </>
          )}
          <div className="flex justify-between border-t border-slate-200 pt-2 text-base font-bold text-slate-900">
            <dt>Total</dt><dd className="tabular-nums">{rupees(bill.total_paise)}</dd>
          </div>
          {q && q.advance_paise > 0 && <Row label="Advance to confirm" value={rupees(q.advance_paise)} />}
          {q?.ready_in_days != null && <Row label="Ready" value={`${q.ready_in_days} days after you accept`} muted />}
          {bill.paid_paise > 0 && bill.paid_paise < bill.total_paise && <Row label="Paid" value={rupees(bill.paid_paise)} />}
          {bill.refunded_paise > 0 && <Row label="Refunded" value={`− ${rupees(bill.refunded_paise)}`} />}
          {bill.balance_paise > 0 && !bill.cancelled && !q && (
            <div className="flex justify-between font-bold text-amber-700"><dt>Balance to pay</dt><dd className="tabular-nums">{rupees(bill.balance_paise)}</dd></div>
          )}
          {bill.balance_paise === 0 && bill.paid_paise > 0 && <p className="pt-1 text-right text-xs font-bold text-emerald-700">Paid in full · thank you</p>}
        </dl>

        {bill.composition && !q && (
          <p className="mt-6 text-xs text-slate-600">Composition taxable person, not eligible to collect tax on supplies.</p>
        )}

        {(hasPayBlock(brand) || brand?.terms || brand?.signature_url) && (
          <section className="mt-8 grid gap-6 border-t border-slate-200 pt-5 sm:grid-cols-2">
            <div className="min-w-0 space-y-3">
              {hasPayBlock(brand) && (
                <div>
                  <p className="text-xs font-bold uppercase tracking-wider text-slate-600">How to pay</p>
                  {brand?.upi_id && <p className="mt-1 break-all text-sm text-slate-800">UPI: {brand.upi_id}</p>}
                  {bankLines(brand).map((line) => <p key={line} className="text-sm text-slate-800">{line}</p>)}
                </div>
              )}
              {brand?.terms && (
                <div>
                  <p className="text-xs font-bold uppercase tracking-wider text-slate-600">Terms</p>
                  <p className="mt-1 whitespace-pre-line text-xs leading-5 text-slate-600">{brand.terms}</p>
                </div>
              )}
            </div>
            {brand?.signature_url && (
              <div className="flex flex-col items-end justify-end">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={brand.signature_url} alt="Signature" className="max-h-16 w-auto max-w-[200px] object-contain" />
                <p className="mt-1 text-xs text-slate-600">Authorised signatory</p>
              </div>
            )}
          </section>
        )}

        <footer className="mt-10 border-t border-slate-100 pt-4 text-center text-[11px] text-slate-400">
          {q ? "This is a quotation, not a bill." : isGst ? "This is a computer-made tax invoice." : "Thank you for shopping with us."} Made with Anril.
        </footer>
      </article>
    </Shell>
  );
}

function Row({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className={muted ? "flex justify-between text-xs text-slate-500" : "flex justify-between text-slate-700"}>
      <dt>{label}</dt><dd className="tabular-nums">{value}</dd>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <main className="min-h-screen bg-slate-50 px-4 py-6 sm:py-10 print:bg-white print:p-0">{children}</main>;
}
