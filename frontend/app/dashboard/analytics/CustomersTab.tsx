"use client";

import type { CustomersReport, LabelCount } from "@/lib/reportsApi";
import { PeriodMetrics } from "./PeriodMetrics";
import { ReportFrame, type FrameTools } from "./ReportFrame";
import { Empty, SectionCard } from "./reportsUi";

const LABELS: Record<string, string> = {
  first_chats: "New chats",
  new_chats: "New chats",
  hot: "Hot chats",
  paid: "Paid",
  new_buyers: "First-time buyers",
  repeat_buyers: "Buyers who came back",
};

export function CountBars({ rows, tools }: { rows: LabelCount[]; tools: FrameTools }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  if (rows.length === 0) return <Empty>Nothing in these days yet.</Empty>;
  return (
    <ul className="space-y-3">
      {rows.map((r) => {
        const open = r.people && r.count > 0 ? () => tools.openPeople(r.people!, r.label) : undefined;
        return (
          <li key={r.key ?? r.label}>
            <div className="mb-1 flex items-baseline justify-between gap-3 font-label text-sm text-on-surface">
              <span>{r.label}</span>
              {open ? (
                <button type="button" onClick={open} aria-label={`${r.label}: ${r.count}. Show the people`} className="font-bold text-primary underline decoration-dotted underline-offset-4">
                  {r.count.toLocaleString("en-IN")}
                </button>
              ) : (
                <span className="font-bold">{r.count.toLocaleString("en-IN")}</span>
              )}
            </div>
            <div className="h-2.5 overflow-hidden rounded-full bg-surface-mid" aria-hidden="true">
              <div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(2, Math.round((r.count / max) * 100))}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function CustomersTab({ query }: { query: string | null }) {
  return (
    <ReportFrame<CustomersReport> tab="customers" query={query} csvTab="customers">
      {(data, tools) => (
        <div className="space-y-5">
          <PeriodMetrics report={data} tools={tools} labels={LABELS} />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 lg:gap-6">
            <SectionCard title="From first chat to paid" hint="How many people got to each step.">
              <CountBars rows={data.funnel ?? []} tools={tools} />
            </SectionCard>
            <SectionCard title="Where they came from" hint="How new people found you.">
              <CountBars rows={data.came_from ?? []} tools={tools} />
            </SectionCard>
          </div>
        </div>
      )}
    </ReportFrame>
  );
}
