"use client";
import { useEffect, useState } from "react";
import { AiraLoader } from "@/components/AiraLoader";
import { api, TelecallingAnalytics } from "@/lib/api";

export function TeamCallsSection() {
  const [data, setData] = useState<TelecallingAnalytics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    api.analytics.telecalling().then(res => { if (active) setData(res); }).catch(() => {}).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  // Hold the slot while the first answer is in flight so the cards below don't jump.
  if (loading) return <AiraLoader inline className="min-h-[120px]" />;
  if (!data) return null;

  return (
    <div className="card rounded-xl p-6 md:p-7">
      <h2 className="font-display font-bold text-ink mb-6 text-[18px]">Team &amp; Calls</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-6 divide-x divide-[#f1f5f9]">
        <div>
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wider">Calls Today</div>
          <div className="font-display font-bold text-[32px] text-ink tracking-tight mt-2">{data.calls_today}</div>
        </div>
        <div className="pl-6">
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wider">Calls This Week</div>
          <div className="font-display font-bold text-[32px] text-ink tracking-tight mt-2">{data.calls_this_week}</div>
        </div>
        <div className="pl-6">
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wider">Converted Today</div>
          <div className="font-display font-bold text-[32px] text-ink tracking-tight mt-2">{data.conversions_today ?? 0}</div>
        </div>
        <div className="pl-6">
          <div className="text-xs font-semibold text-ink-muted uppercase tracking-wider">Callback Today</div>
          <div className="font-display font-bold text-[32px] text-ink tracking-tight mt-2">{data.followups_scheduled ?? 0}</div>
        </div>
      </div>
    </div>
  );
}
