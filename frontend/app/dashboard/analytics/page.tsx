"use client";

import { Suspense, useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { RangePicker, type RangeValue } from "@/components/analytics/RangePicker";
import { Select } from "@/components/ui/Select";
import { AiraLoader } from "@/components/AiraLoader";
import { useNavAccess } from "@/components/nav/useNavAccess";
import {
  TAB_LABELS, monthRange, rangeDates, reportQuery, resolveTab, visibleTabs,
  type CompareMode, type ReportTab,
} from "@/lib/reportsApi";
import { AdsTab } from "./AdsTab";
import { AskTab } from "./AskTab";
import { CustomersTab } from "./CustomersTab";
import { ChannelsSection, InboundSection, TemplatesSection } from "./LegacySections";
import { ItemsTab, CampaignsTab } from "./ItemsCampaignsTabs";
import { MoneyTab } from "./MoneyTab";
import { OverviewTab } from "./OverviewTab";
import { TeamTab } from "./TeamTab";

// Print / Save as PDF: leave only the report. The menu, header and every control disappear.
const PRINT_CSS = `@media print {
  aside, header, nav, [data-print-hide] { display: none !important; }
  body, main { background: #fff !important; }
  main { padding: 0 !important; margin: 0 !important; }
}`;

function MoreDetail({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-8 space-y-3 border-t border-surface-mid pt-6">
      <h2 className="font-display text-base font-bold text-primary">More detail</h2>
      {children}
    </div>
  );
}

function ReportsPage() {
  const params = useSearchParams();
  const { access, telecallingOn, roleLoading } = useNavAccess();
  const tabParam = params.get("tab");
  const monthParam = params.get("month");
  const accountant = params.get("accountant") === "1";

  const [range, setRange] = useState<RangeValue>(() => monthRange(monthParam) ?? { preset: "last_7d", start: "", end: "" });
  const [compare, setCompare] = useState<CompareMode>("previous");
  const [moneyHidden, setMoneyHidden] = useState(false);
  const onMoneyHidden = useCallback((hidden: boolean) => setMoneyHidden(hidden), []);

  const tabs = useMemo(() => visibleTabs(access, moneyHidden), [access, moneyHidden]);
  const wanted = resolveTab(tabParam === null && accountant ? "money" : tabParam);
  const active: ReportTab = tabs.includes(wanted) ? wanted : "overview";

  const query = useMemo(() => reportQuery(range, compare), [range, compare]);
  const dates = rangeDates(range);

  if (roleLoading) return <AiraLoader inline className="min-h-40" />;

  return (
    <div className="min-w-0 space-y-5">
      <nav data-print-hide aria-label="Report tabs" className="-mx-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <ul className="flex w-max min-w-full gap-1 border-b border-surface-mid px-1">
          {tabs.map((t) => (
            <li key={t}>
              <Link
                href={`/dashboard/analytics?tab=${t}`}
                aria-current={t === active ? "page" : undefined}
                className={cn(
                  "-mb-px block whitespace-nowrap border-b-[3px] px-3 py-3 font-label text-sm font-bold transition-colors",
                  t === active ? "border-primary text-primary" : "border-transparent text-[#556274] hover:text-on-surface",
                )}
              >
                {TAB_LABELS[t]}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      {active !== "ask" && (
        <div className="space-y-2">
          <div data-print-hide className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-label text-xs font-bold text-[#556274]">Period</span>
              <RangePicker value={range} onChange={setRange} idPrefix="reports-range" />
            </div>
            <div className="flex items-center gap-2">
              <span className="font-label text-xs font-bold text-[#556274]">Compare</span>
              <Select
                size="sm"
                aria-label="Compare with the days before"
                className="h-9 w-[170px] shrink-0"
                value={compare}
                onChange={(v) => setCompare(v === "off" ? "off" : "previous")}
                options={[
                  { value: "previous", label: "With the days before" },
                  { value: "off", label: "Don't compare" },
                ]}
              />
            </div>
          </div>
          <p className="font-label text-xs text-[#556274]">
            {TAB_LABELS[active]}
            {dates ? `: ${dates.from} to ${dates.to}` : ""}
          </p>
        </div>
      )}

      {active === "overview" && (
        <OverviewTab query={query} range={range} comparison={{ mode: compare, start: "", end: "" }} onMoneyHidden={onMoneyHidden} />
      )}
      {active === "money" && <MoneyTab query={query} onMoneyHidden={onMoneyHidden} accountant={accountant} />}
      {active === "customers" && (
        <>
          <CustomersTab query={query} />
          <MoreDetail><InboundSection range={range} /></MoreDetail>
        </>
      )}
      {active === "ads" && <AdsTab query={query} />}
      {active === "team" && (
        <>
          <TeamTab query={query} telecallingOn={telecallingOn} />
          <MoreDetail><ChannelsSection range={range} /></MoreDetail>
        </>
      )}
      {active === "items" && <ItemsTab query={query} />}
      {active === "campaigns" && (
        <>
          <CampaignsTab query={query} />
          <MoreDetail><TemplatesSection range={range} /></MoreDetail>
        </>
      )}
      {active === "ask" && <AskTab />}
      <style>{PRINT_CSS}</style>
    </div>
  );
}

export default function AnalyticsPage() {
  return (
    <Suspense fallback={<AiraLoader inline className="min-h-40" />}>
      <ReportsPage />
    </Suspense>
  );
}
