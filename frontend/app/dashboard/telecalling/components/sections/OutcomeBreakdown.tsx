"use client";

import type { TelecallingAnalyticsExtended } from "@/lib/api";
import { RESULT_OPTIONS, TONE_DOT } from "@/lib/call-wrapup";

export default function OutcomeBreakdown({ stats }: { stats: TelecallingAnalyticsExtended | null }) {
  const ob = stats?.outcome_breakdown;
  const total = ob ? RESULT_OPTIONS.reduce((sum, o) => sum + (ob[o.value] ?? 0), 0) : 0;

  return (
    <div className="bg-surface rounded-card p-4 md:p-6 shadow-card ring-1 ring-[#c4c7c7]/15">
      <h2 className="font-display text-base font-bold text-primary mb-1">Outcome Breakdown</h2>
      <p className="font-label text-xs text-on-surface-muted mb-5">What happened on connected calls.</p>

      {total === 0 ? (
        <p className="font-body text-sm text-on-surface-muted text-center py-6">No call outcomes in this window.</p>
      ) : (
        <div className="space-y-3">
          {RESULT_OPTIONS.map(({ value, label, tone }) => {
            const count = ob?.[value] ?? 0;
            const pct = Math.round((count / total) * 100);
            return (
              <div key={value} className="flex items-center gap-3 max-md:flex-wrap max-md:gap-y-1">
                <span className="font-label text-xs text-on-surface-muted w-44 shrink-0 truncate max-md:w-full" title={label}>{label}</span>
                <div className="flex-1 bg-surface-mid rounded-full h-4 overflow-hidden max-md:min-w-0">
                  <div className={`h-4 rounded-full ${TONE_DOT[tone]} transition-all`} style={{ width: `${pct}%` }} />
                </div>
                <span className="font-label text-xs text-on-surface w-8 text-right shrink-0">{count}</span>
                <span className="font-label text-xs text-on-surface-muted w-8 shrink-0">{pct}%</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
