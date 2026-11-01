import { MessageSquare, TrendingUp, CheckCircle2 } from "lucide-react";
import { AnalyticsOverview } from "@/lib/api";
import { TrendBadge } from "./TrendBadge";
import { HeroSparkline } from "./HeroSparkline";

interface HeroCardProps {
  icon: React.ReactNode;
  iconTone: string;
  label: string;
  value: number;
  sparklineData: { day: string; count: number }[];
  sparklineColor: string;
  gradientId: string;
  trendPct: number | null;
  trendLabel: string;
  sub?: string;
}

function HeroCard({
  icon, iconTone, label, value,
  sparklineData, sparklineColor, gradientId, trendPct, trendLabel, sub,
}: HeroCardProps) {
  return (
    <div className="flex min-h-48 flex-col justify-between rounded-xl border border-border bg-white p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-mono text-[11px] font-medium uppercase tracking-wider text-ink-secondary">{label}</div>
          <div className="mt-2 text-4xl font-semibold tracking-tight tabular-nums text-ink">{value}</div>
        </div>
        <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border ${iconTone}`}>
          {icon}
        </div>
      </div>
      <div className="mt-6 flex min-h-10 flex-wrap items-center justify-between gap-3 border-t border-border-subtle pt-4">
        <div className="min-w-0">
          {sub && <div className="font-mono text-xs text-ink-secondary">{sub}</div>}
          <TrendBadge pct={trendPct} label={trendLabel} />
        </div>
        {sparklineData.length > 1 && <HeroSparkline data={sparklineData} color={sparklineColor} gradientId={gradientId} />}
      </div>
    </div>
  );
}

// Same-day counts swing a lot on their own; "vs yesterday" (not "vs last
// week") is the only fair comparison for a number that resets every morning.
function pctVsYesterday(series: { day: string; count: number }[]): number | null {
  if (series.length < 2) return null;
  const today = series[series.length - 1].count;
  const yesterday = series[series.length - 2].count;
  if (yesterday === 0) return null;
  return Math.round(((today - yesterday) / yesterday) * 100);
}

export function PipelinePulse({ overview }: { overview: AnalyticsOverview }) {
  // A lead created months ago who clicks a fresh ad today is a real
  // conversation that ad money bought, but daily_leads only ever counts leads
  // by their creation date, so they landed in no tile at all. Fresh + Returned
  // is the honest "conversations started today"; the split stays visible so a
  // day carried by the old list doesn't read as new growth.
  const returningByDay = new Map(
    (overview.returning_ad_leads_daily ?? []).map((d) => [d.day, d.count]),
  );
  const combinedDailyLeads = overview.daily_leads.map((d) => ({
    day: d.day,
    count: d.count + (returningByDay.get(d.day) ?? 0),
  }));

  const freshLeadsToday = overview.daily_leads[overview.daily_leads.length - 1]?.count ?? 0;
  const returningLeadsToday =
    returningByDay.get(overview.daily_leads[overview.daily_leads.length - 1]?.day ?? "") ?? 0;
  const newLeadsToday = freshLeadsToday + returningLeadsToday;
  const newHotLeadsToday = overview.new_hot_leads_daily[overview.new_hot_leads_daily.length - 1]?.count ?? 0;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-mono text-xs font-medium uppercase tracking-wider text-ink-secondary">Today’s leads</h2>
        <p className="font-mono text-xs text-ink-secondary">{overview.total_leads.toLocaleString()} total leads all-time</p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <HeroCard
          icon={<MessageSquare size={18} />}
          iconTone="border-segment-a-border bg-segment-a-bg text-segment-a-text"
          label="New Leads Today"
          value={newLeadsToday}
          sub={`Fresh ${freshLeadsToday} · Returned ${returningLeadsToday}`}
          sparklineData={combinedDailyLeads}
          sparklineColor="#10b981"
          gradientId="totalLeadsGrad"
          trendPct={pctVsYesterday(combinedDailyLeads)}
          trendLabel="vs yesterday"
        />
        <HeroCard
          icon={<TrendingUp size={18} />}
          iconTone="border-segment-b-border bg-segment-b-bg text-segment-b-text"
          label="New Hot Leads Today"
          value={newHotLeadsToday}
          sparklineData={overview.new_hot_leads_daily}
          sparklineColor="#f59e0b"
          gradientId="hotLeadsGrad"
          trendPct={pctVsYesterday(overview.new_hot_leads_daily)}
          trendLabel="vs yesterday"
        />
        <HeroCard
          icon={<CheckCircle2 size={18} />}
          iconTone="border-primary-100 bg-primary-50 text-primary"
          label="Conversions Today"
          value={overview.converted_today}
          sparklineData={[]}
          sparklineColor="var(--primary-800)"
          gradientId="conversionsGrad"
          trendPct={null}
          trendLabel=""
        />
      </div>
    </div>
  );
}
