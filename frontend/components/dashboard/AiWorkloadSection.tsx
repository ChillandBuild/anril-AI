"use client";
import { useEffect, useState } from "react";
import { api, AnalyticsOverview } from "@/lib/api";

export function AiWorkloadSection({ overview }: { overview: AnalyticsOverview }) {
  const [escalations, setEscalations] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    api.chatHandovers.count(true)
      .then(res => { if (active) setEscalations(res.count); })
      .catch(() => { if (active) setEscalations(null); });
    return () => { active = false; };
  }, []);

  const today = overview.daily_messages[overview.daily_messages.length - 1];
  const totalRepliesToday = (today?.ai ?? 0) + (today?.human ?? 0);
  const aiPct = totalRepliesToday > 0 ? Math.round(((today?.ai ?? 0) / totalRepliesToday) * 100) : 0;

  return (
    <div className="card rounded-xl p-6 md:p-7">
      <h2 className="font-display font-semibold text-ink text-sm">
        Is my AI carrying its weight?
      </h2>
      <p className="mt-1 text-xs text-ink-secondary">Today’s AI replies and conversation activity</p>
      <div className="swiss-workload mt-6 grid grid-cols-2 gap-6 border-t border-border-subtle pt-6 lg:grid-cols-5">
        <div>
          <div className="font-mono text-[10px] font-medium text-ink-secondary uppercase tracking-wider">AI Auto-Reply Share Today</div>
          <div className="font-display font-semibold text-2xl text-ink tracking-tight mt-2">{aiPct}%</div>
          <div className="text-[11px] text-ink-secondary mt-1 font-mono">
            {today?.ai ?? 0} AI · {today?.human ?? 0} human
          </div>
        </div>
        <div>
          <div className="font-mono text-[10px] font-medium text-ink-secondary uppercase tracking-wider">Inbound Today</div>
          <div className="font-display font-semibold text-2xl text-ink tracking-tight mt-2">{today?.inbound ?? 0}</div>
        </div>
        <div>
          <div className="font-mono text-[10px] font-medium text-ink-secondary uppercase tracking-wider">Outbound Today</div>
          <div className="font-display font-semibold text-2xl text-ink tracking-tight mt-2">{today?.outbound ?? 0}</div>
        </div>
        <div>
          <div className="font-mono text-[10px] font-medium text-ink-secondary uppercase tracking-wider">Awaiting Response</div>
          <div className={`font-display font-semibold text-2xl tracking-tight mt-2 ${overview.unreplied_24h > 0 ? "text-rose-600" : "text-ink"}`}>
            {overview.unreplied_24h}
          </div>
        </div>
        <div>
          <div className="font-mono text-[10px] font-medium text-ink-secondary uppercase tracking-wider">Escalations</div>
          <div className={`font-display font-semibold text-2xl tracking-tight mt-2 ${(escalations ?? 0) > 0 ? "text-rose-600" : "text-ink"}`}>
            {escalations ?? "—"}
          </div>
        </div>
      </div>
    </div>
  );
}
