"use client";
import { useEffect, useState } from "react";
import { api, AdPerformanceSummary } from "@/lib/api";

export function AdSpendSection() {
  const [data, setData] = useState<AdPerformanceSummary | null>(null);

  useEffect(() => {
    let active = true;
    api.analytics.adPerformance().then(res => { if (active) setData(res); }).catch(() => {});
    return () => { active = false; };
  }, []);

  if (!data || data.campaigns.length === 0) return null;

  return (
    <div className="card rounded-xl p-6 md:p-7">
      <h2 className="font-display font-bold text-ink mb-6 text-[18px]">Ad Spend</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-6 divide-x divide-[#f1f5f9]">
        <div>
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wider">Campaigns</div>
          <div className="font-display font-bold text-[32px] text-ink tracking-tight mt-2">{data.totals.campaigns}</div>
        </div>
        <div className="pl-6">
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wider">Tracked Leads Today</div>
          <div className="font-display font-bold text-[32px] text-ink tracking-tight mt-2">{data.totals.tracked_leads_today}</div>
          <div className="text-xs text-ink-muted mt-1 font-medium">{data.totals.tracked_leads} all-time</div>
        </div>
        <div className="pl-6">
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wider">Conversion Rate (7d)</div>
          <div className="font-display font-bold text-[32px] text-ink tracking-tight mt-2">{Math.round(data.totals.conversion_rate_7d * 100)}%</div>
        </div>
        <div className="pl-6">
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wider">Progressive Rate (7d)</div>
          <div className="font-display font-bold text-[32px] text-ink tracking-tight mt-2">{Math.round(data.totals.progressive_rate_7d * 100)}%</div>
        </div>
      </div>
    </div>
  );
}
