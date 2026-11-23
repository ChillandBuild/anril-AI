"use client";

import { useState } from "react";
import Link from "next/link";
import { Receipt } from "lucide-react";
import { downloadAccountantFile, monthLabel, previousMonth, type MoneyReport } from "@/lib/reportsApi";
import { PeriodMetrics } from "./PeriodMetrics";
import { ReportFrame } from "./ReportFrame";
import { ErrorBox, PlainNote, SectionCard } from "./reportsUi";

const MONEY_LABELS: Record<string, string> = {
  sales_paise: "Sales (before GST)",
  refunds_paise: "Refunds",
  cost_paise: "Cost of items",
  expenses_paise: "Expenses",
  profit_paise: "Profit",
  gst_collected_paise: "GST you collected",
  gst_paid_paise: "GST you paid",
  still_to_collect_paise: "Still to collect",
  cash_short_paise: "Cash short at day close",
  owed_to_suppliers_paise: "Owed to suppliers",
};

const MONEY_HINTS: Record<string, string> = {
  still_to_collect_paise: "Orders waiting for payment",
  owed_to_suppliers_paise: "Bills not paid yet",
};

export function AccountantFile({ startOpen }: { startOpen: boolean }) {
  const [open, setOpen] = useState(startOpen);
  const [month, setMonth] = useState(previousMonth());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const go = async () => {
    if (!/^\d{4}-\d{2}$/.test(month)) {
      setErr("Pick a month first.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await downloadAccountantFile(month);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The file did not download. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-print-hide className="space-y-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 font-label text-sm font-bold text-white shadow-sm hover:bg-primary/90"
      >
        <Receipt size={16} /> For your accountant
      </button>
      {open && (
        <div className="space-y-3 rounded-2xl bg-white p-4 ring-1 ring-surface-mid">
          <p className="font-body text-sm text-on-surface">
            One Excel file for the month: sales to businesses and to customers, credit notes, purchases, expenses and how you were paid.
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 font-label text-xs font-bold text-[#556274]">
              Month
              <input
                type="month"
                value={month}
                onChange={(e) => setMonth(e.target.value)}
                className="h-10 rounded-xl border border-surface-mid bg-white px-3 font-body text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-200"
              />
            </label>
            <button
              type="button"
              onClick={go}
              disabled={busy}
              className="h-10 rounded-xl bg-primary px-4 font-label text-xs font-bold text-white hover:bg-primary/90 disabled:opacity-40"
            >
              {busy ? "Getting the file…" : `Download ${/^\d{4}-\d{2}$/.test(month) ? monthLabel(month) : "file"}`}
            </button>
          </div>
          {err && <ErrorBox message={err} />}
        </div>
      )}
    </div>
  );
}

export function MoneyTab({
  query, onMoneyHidden, accountant,
}: {
  query: string | null;
  onMoneyHidden: (hidden: boolean) => void;
  accountant: boolean;
}) {
  return (
    <div className="space-y-5">
      <AccountantFile startOpen={accountant} />
      <ReportFrame<MoneyReport> tab="money" query={query} onMoneyHidden={onMoneyHidden}>
        {(data, tools) => {
          const cov = data.cost_coverage;
          const noCosts = data.has_cost_prices === false || (!!cov && cov.total > 0 && cov.with_cost === 0);
          return (
            <div className="space-y-5">
              {data.scope === "month" && (
                <PlainNote>Profit and expenses are for {data.scope_label || "this month"}, not only the days you picked.</PlainNote>
              )}
              {noCosts && (
                <PlainNote>
                  Add cost prices to items to see real profit.{" "}
                  <Link href="/dashboard/catalog" className="font-bold underline">Open items</Link>
                </PlainNote>
              )}
              <SectionCard title="Your money" hint={data.scope_label}>
                <PeriodMetrics report={data} tools={tools} labels={MONEY_LABELS} hints={MONEY_HINTS} />
              </SectionCard>
            </div>
          );
        }}
      </ReportFrame>
    </div>
  );
}
