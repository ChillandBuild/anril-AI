"use client";
import { useEffect, useState } from "react";
import { api, type TelecallingAnalytics } from "@/lib/api";
import { CARD, ChartCard, ChartCardSkeleton } from "./ChartCard";
import { barPct } from "./homeCharts";

const CALLER_ROWS = 8;

/** Calls per caller today: the whole bar is calls made, the dark part of it is calls that connected. */
export function TeamCallsCard() {
  const [data, setData] = useState<TelecallingAnalytics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    api.analytics
      .telecalling()
      .then((res) => {
        if (active) setData(res);
      })
      .catch(() => {})
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  // Hold the slot while the first answer is in flight so the cards beside it don't jump.
  if (loading) return <ChartCardSkeleton />;
  if (!data) return null;

  const callers = [...(data.per_caller ?? [])]
    .sort((a, b) => (b.calls_today ?? 0) - (a.calls_today ?? 0))
    .slice(0, CALLER_ROWS);
  const max = Math.max(0, ...callers.map((c) => c.calls_today ?? 0));
  // Older backends send no connected count: draw plain call bars and no legend.
  const hasConnected = callers.length > 0 && callers.every((c) => typeof c.connected_today === "number");

  return (
    <ChartCard title="Team calls" note={`today · ${data.calls_today ?? 0} calls`} className={CARD}>
      {callers.length === 0 || max === 0 ? (
        <p className="font-body text-sm text-ink-muted">No calls made yet today.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {callers.map((c) => {
            const calls = c.calls_today ?? 0;
            const connected = Math.min(c.connected_today ?? 0, calls);
            const label = hasConnected ? `${c.name || "Caller"}: ${calls} calls, ${connected} connected` : `${c.name || "Caller"}: ${calls} calls`;
            return (
              <div key={c.caller_id} className="flex items-center gap-2.5 font-body text-[13px]" title={label}>
                <span className="w-[72px] shrink-0 truncate text-ink-secondary">{c.name || "Caller"}</span>
                <div className="flex h-3.5 flex-1 gap-0.5" role="img" aria-label={label}>
                  {hasConnected ? (
                    <>
                      <div className="rounded-l bg-primary-800" style={{ width: `${barPct(connected, max, 0)}%` }} />
                      <div className="rounded-r bg-primary-200" style={{ width: `${barPct(calls - connected, max, 0)}%` }} />
                    </>
                  ) : (
                    <div className="rounded bg-primary-800" style={{ width: `${barPct(calls, max)}%` }} />
                  )}
                </div>
                <b className="w-11 shrink-0 text-right tabular-nums text-ink">{hasConnected ? `${connected}/${calls}` : calls}</b>
              </div>
            );
          })}
          {hasConnected && (
            <div className="mt-1 flex gap-3.5 font-label text-xs text-ink-muted">
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-[3px] bg-primary-800" aria-hidden />
                Connected
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-[3px] bg-primary-200" aria-hidden />
                Not connected
              </span>
            </div>
          )}
        </div>
      )}
    </ChartCard>
  );
}
