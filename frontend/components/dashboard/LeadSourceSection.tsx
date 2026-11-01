import { AnalyticsOverview } from "@/lib/api";

const CHANNEL_LABELS: Record<string, string> = {
  whatsapp: "WhatsApp",
  instagram: "Instagram",
  facebook: "Facebook",
  telegram: "Telegram",
  upload: "Upload",
  manual: "Manual",
  indiamart: "IndiaMART",
  justdial: "JustDial",
  website: "Website form",
  api: "App / API",
  store: "Shop counter",
};

export function LeadSourceSection({ overview }: { overview: AnalyticsOverview }) {
  const breakdown = overview.channel_breakdown_today;
  const total = Object.values(breakdown).reduce((a, b) => a + b, 0);
  const entries = (Object.entries(breakdown) as [string, number][])
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);

  const adAttributedPct = total > 0
    ? Math.round((overview.ad_attributed_leads_today / total) * 100)
    : 0;

  if (total === 0) {
    return (
      <div className="card rounded-xl p-6 md:p-7">
        <h2 className="font-display font-bold text-ink mb-2 text-[18px]">Where did today&apos;s leads come from?</h2>
        <p className="text-sm text-ink-muted">No leads yet today.</p>
      </div>
    );
  }

  return (
    <div className="card rounded-xl p-6 md:p-7">
      <h2 className="font-display font-bold text-ink mb-6 text-[18px]">Where did today&apos;s leads come from?</h2>
      <div className="space-y-3">
        {entries.map(([channel, count]) => {
          const pct = total ? Math.round((count / total) * 100) : 0;
          return (
            <div key={channel} className="flex items-center gap-3">
              <div className="w-24 text-xs font-semibold text-ink-secondary">{CHANNEL_LABELS[channel] ?? channel}</div>
              <div className="flex-1 h-2 rounded-full bg-surface-mid overflow-hidden">
                <div className="h-full bg-[var(--primary-800)]" style={{ width: `${pct}%` }} />
              </div>
              <div className="w-16 shrink-0 whitespace-nowrap text-right text-xs font-mono text-ink-muted">{count} · {pct}%</div>
            </div>
          );
        })}
      </div>
      <div className="mt-5 pt-5 border-t border-[#f1f5f9] flex items-center justify-between">
        <span className="text-xs font-semibold text-ink-muted uppercase tracking-wider">Ad-attributed</span>
        <span className="text-sm font-mono font-semibold text-ink">
          {overview.ad_attributed_leads_today} of {total} ({adAttributedPct}%)
        </span>
      </div>
    </div>
  );
}
