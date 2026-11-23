"use client";
import { useState } from "react";
import Link from "next/link";
import { coursesApi, type FeePlan, type PayMethod } from "@/lib/coursesApi";
import { BTN_SECONDARY, Notice, errorText } from "@/app/dashboard/bookings/bookingsUi";
import { partLabel, rupees } from "./coursesLogic";

const METHODS: { id: PayMethod; label: string }[] = [
  { id: "cash", label: "Cash" },
  { id: "upi", label: "UPI" },
  { id: "card", label: "Card" },
  { id: "bank_transfer", label: "Bank transfer" },
  { id: "other", label: "Other" },
];

/** One student's fee parts, each with a button to mark it paid and a link to the receipt. */
export function FeePlanView({ plan, canPay, onChanged }: { plan: FeePlan; canPay: boolean; onChanged: () => void }) {
  const [method, setMethod] = useState<PayMethod>("cash");
  const [busy, setBusy] = useState<number | null>(null);
  const [err, setErr] = useState("");

  async function pay(index: number) {
    setBusy(index);
    setErr("");
    try {
      await coursesApi.payPart(plan.id, index, method);
      onChanged();
    } catch (e) {
      setErr(errorText(e, "Could not mark that as paid."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mt-2 rounded-lg bg-[#f8fafc] p-3">
      <p className="text-sm text-ink-secondary">Paid {rupees(plan.paid_paise)} of {rupees(plan.total_paise)}</p>
      <ul className="mt-2 space-y-2">
        {plan.parts.map((p) => (
          <li key={p.index} className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="min-w-0">
              <span className="font-bold text-ink">Part {p.index + 1}: {rupees(p.amount_paise)}</span>
              <span className={`ml-2 ${p.late && !p.paid ? "font-bold text-rose-700" : "text-ink-secondary"}`}>{partLabel(p)}</span>
              {p.paid && p.by_name ? <span className="ml-2 text-ink-secondary">marked by {p.by_name}</span> : null}
            </span>
            {p.paid && p.payment_id ? (
              <Link className="text-sm font-bold text-primary underline" href={`/dashboard/catalog/courses/receipt/${p.payment_id}`}>Receipt {p.receipt_no ?? ""}</Link>
            ) : null}
            {!p.paid && canPay ? (
              <button type="button" className={BTN_SECONDARY} disabled={busy !== null} onClick={() => pay(p.index)}>
                {busy === p.index ? "Saving…" : "Mark paid"}
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {canPay ? (
        <label className="mt-3 flex items-center gap-2 text-sm text-ink-secondary">
          Paid by
          <select className="h-9 rounded-lg border border-[#e2e8f0] bg-white px-2 text-sm text-ink" value={method} onChange={(e) => setMethod(e.target.value as PayMethod)}>
            {METHODS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </label>
      ) : null}
      {err ? <div className="mt-2"><Notice tone="red">{err}</Notice></div> : null}
    </div>
  );
}
