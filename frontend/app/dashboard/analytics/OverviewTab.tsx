"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import type { RangeValue } from "@/components/analytics/RangePicker";
import type { ComparisonSelection } from "@/components/analytics/periodSelection";
import { formatRupees, monthLabel, type OverviewReport, type SalesTarget } from "@/lib/reportsApi";
import { CompareTab } from "./CompareTab";
import { ReportFrame } from "./ReportFrame";
import { Metric, MetricGrid, SectionCard } from "./reportsUi";

export function TargetBar({ target }: { target?: SalesTarget | null }) {
  const t = target?.this_month;
  if (!t || !t.target_paise) return null;
  const pct = Math.max(0, Math.round(t.pct ?? 0));
  const money = t.money_in_paise !== null && t.money_in_paise !== undefined;
  return (
    <SectionCard title={`Target for ${t.month ? monthLabel(t.month) : "this month"}`}>
      <p className="font-body text-sm text-on-surface">
        {money ? `${formatRupees(t.money_in_paise)} of ${formatRupees(t.target_paise)} · ` : ""}
        <span className="font-bold">{pct}%</span>
        {!money ? " of the target" : ""}
      </p>
      <div className="mt-3 h-3 overflow-hidden rounded-full bg-surface-mid" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(pct, 100)} aria-label="Target progress">
        <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
    </SectionCard>
  );
}

export function OverviewTab({
  query, range, comparison, onMoneyHidden,
}: {
  query: string | null;
  range: RangeValue;
  comparison: ComparisonSelection;
  onMoneyHidden: (hidden: boolean) => void;
}) {
  return (
    <div className="space-y-6">
      <ReportFrame<OverviewReport> tab="overview" query={query} csvTab="overview" onMoneyHidden={onMoneyHidden}>
        {(data, tools) => (
          <div className="space-y-5">
            {data.unmarked_chats && data.unmarked_chats.count > 0 && (
              <Link
                href={data.unmarked_chats.href}
                className="inline-flex items-center gap-2 rounded-full bg-amber-50 px-4 py-2 font-label text-sm font-bold text-amber-900 ring-1 ring-amber-200 hover:bg-amber-100"
              >
                {data.unmarked_chats.count.toLocaleString("en-IN")} chats not marked yet <ArrowRight size={14} />
              </Link>
            )}
            <TargetBar target={data.target} />
            {data.todo?.length > 0 && (
              <SectionCard title="3 things to do this week">
                <ul className="space-y-2">
                  {data.todo.slice(0, 3).map((item) => (
                    <li key={item.href + item.text}>
                      <Link href={item.href} className="flex items-center justify-between gap-3 rounded-xl px-3 py-3 ring-1 ring-surface-mid hover:bg-surface-low">
                        <span className="font-body text-sm text-on-surface">{item.text}</span>
                        <ArrowRight size={14} className="shrink-0 text-[#556274]" aria-hidden="true" />
                      </Link>
                    </li>
                  ))}
                </ul>
              </SectionCard>
            )}
            {data.cards?.length > 0 && (
              <MetricGrid>
                {data.cards.slice(0, 6).map((c) => (
                  <Metric
                    key={c.key}
                    statKey={c.key}
                    label={c.label}
                    value={c.value}
                    before={data.before ? c.before ?? null : undefined}
                    kind={c.kind}
                    people={c.people ?? null}
                    href={c.href}
                    onPeople={tools.openPeople}
                  />
                ))}
              </MetricGrid>
            )}
          </div>
        )}
      </ReportFrame>
      <CompareTab range={range} comparison={comparison} />
    </div>
  );
}
