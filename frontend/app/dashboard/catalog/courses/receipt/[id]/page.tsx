"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { coursesApi } from "@/lib/coursesApi";
import { BTN_PRIMARY, Notice, errorText } from "@/app/dashboard/bookings/bookingsUi";
import { dayText, rupees } from "../../coursesLogic";

const METHOD_TEXT: Record<string, string> = { cash: "Cash", upi: "UPI", card: "Card", bank_transfer: "Bank transfer", other: "Other" };

/** A fee receipt the owner can print or save as PDF from the browser. */
export default function ReceiptPage() {
  const id = String(useParams<{ id: string }>().id ?? "");
  const { data, error } = useSWR(["courses/receipt", id], () => coursesApi.receipt(id), { revalidateOnFocus: false });

  return (
    <div className="mx-auto max-w-xl space-y-4">
      <div className="flex items-center justify-between gap-2 print:hidden">
        <Link href="/dashboard/catalog/courses" className="text-sm font-bold text-primary underline">Back to courses</Link>
        {data ? <button type="button" className={BTN_PRIMARY} onClick={() => window.print()}>Print or save as PDF</button> : null}
      </div>
      {error ? <Notice tone="red">{errorText(error, "Could not load this receipt.")}</Notice> : null}
      {!data && !error ? <div className="h-64 animate-pulse rounded-xl bg-surface-low" /> : null}
      {data ? (
        <article className="rounded-xl border border-[#e2e8f0] bg-white p-6 text-ink print:border-0 print:p-0">
          <p className="text-sm font-bold text-ink-secondary">{data.business_name}</p>
          <h1 className="mt-1 text-xl font-extrabold">Fee receipt {data.receipt_no}</h1>
          <p className="text-sm text-ink-secondary">{dayText(data.paid_at)} · {METHOD_TEXT[data.method] ?? data.method}</p>
          <dl className="mt-5 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-ink-secondary">Student</dt><dd className="font-bold">{data.student_name || data.phone}</dd>
            <dt className="text-ink-secondary">Course</dt><dd>{data.course_name}</dd>
            <dt className="text-ink-secondary">Batch</dt><dd>{data.batch_name}</dd>
            <dt className="text-ink-secondary">Part</dt><dd>{data.part_number} of {data.parts_total}</dd>
            <dt className="text-ink-secondary">Course fee</dt><dd>{rupees(data.fee_total_paise)}</dd>
          </dl>
          <div className="mt-5 flex items-baseline justify-between border-t border-[#e2e8f0] pt-4">
            <span className="text-sm font-bold">Amount received</span>
            <span className="text-2xl font-extrabold">{rupees(data.amount_paise)}</span>
          </div>
          <p className="mt-1 text-sm text-ink-secondary">Balance left: {rupees(data.balance_paise)}</p>
          {data.paid_by ? <p className="mt-3 text-sm text-ink-secondary">Received by {data.paid_by}</p> : null}
        </article>
      ) : null}
    </div>
  );
}
