"use client";
import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { companionsApi, type AgentUsage } from "@/lib/api";
import { byCharacter, cycleBars, meter, rupees, shortDate } from "@/components/agents/usageView";
import { CARD, ErrorNote, LoadingRows } from "@/components/agents/ui";

const TONE_BAR = { ok: "bg-primary", near: "bg-warning", over: "bg-danger" } as const;
const TONE_TEXT = { ok: "text-ink-secondary", near: "text-warning", over: "text-danger" } as const;

/** This cycle's agent replies against the plan. Example: "3,420 of 10,000 included · ₹3,000 / month · 0 over". */
export default function AgentUsagePage() {
  const [usage, setUsage] = useState<AgentUsage | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    setUsage(null);
    companionsApi
      .usage()
      .then(setUsage)
      .catch((e: Error) => setError(e.message || "Could not load usage."));
  }, []);
  useEffect(load, [load]);

  if (error) return <div className="p-4 sm:p-6"><ErrorNote message={error} onRetry={load} /></div>;
  if (!usage) return <div className="p-4 sm:p-6"><LoadingRows rows={4} /></div>;

  const m = meter(usage.used, usage.included);
  const bars = cycleBars(usage);
  const max = Math.max(1, ...bars.map((b) => b.count));
  const characters = byCharacter(usage);
  const cycle = `${shortDate(usage.period_start)}${usage.period_end ? ` – renews ${shortDate(usage.period_end)}` : ""}`;

  return (
    <div className="w-full space-y-4 p-4 sm:p-6">
      <section className={CARD} aria-labelledby="replies">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="replies" className="text-sm font-semibold text-ink">Agent replies</h2>
          <span className="text-xs text-ink-muted">{cycle}</span>
        </div>
        <div className="mt-2 flex flex-wrap items-baseline gap-2">
          <span className="text-3xl font-semibold tabular-nums text-ink">{usage.used.toLocaleString("en-IN")}</span>
          <span className="text-sm text-ink-secondary">
            {usage.plan ? `of ${usage.included.toLocaleString("en-IN")} included` : "replies this cycle"}
          </span>
          {m && <span className={cn("text-sm font-medium tabular-nums", TONE_TEXT[m.tone])}>{m.pct}%</span>}
        </div>
        {m && (
          <div
            className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-surface-mid"
            role="meter"
            aria-label="Agent replies used"
            aria-valuemin={0}
            aria-valuemax={usage.included}
            aria-valuenow={usage.used}
          >
            <div className={cn("h-full rounded-full", TONE_BAR[m.tone])} style={{ width: `${m.bar}%` }} />
          </div>
        )}
        {!usage.plan && (
          <p className="mt-3 text-sm text-ink-secondary">
            Agent replies aren&apos;t on your plan yet. Every reply is still counted here. Contact us to add a plan.
          </p>
        )}
      </section>

      {usage.plan && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {[
            { label: "Your plan", value: `${rupees(usage.plan.monthly_price)} / month` },
            { label: "Included replies", value: usage.plan.included.toLocaleString("en-IN") },
            { label: "Over the limit", value: `${usage.over.toLocaleString("en-IN")} replies`, warn: usage.over > 0 },
          ].map((t) => (
            <div key={t.label} className={cn(CARD, "p-4")}>
              <div className="text-xs text-ink-muted">{t.label}</div>
              <div className={cn("mt-1 text-xl font-semibold tabular-nums", t.warn ? "text-danger" : "text-ink")}>{t.value}</div>
            </div>
          ))}
        </div>
      )}
      {usage.over > 0 && (
        <p className="text-sm text-ink-secondary">
          Your agents keep answering over the limit. Replies past the included number are billed separately.
        </p>
      )}

      <section className={CARD} aria-labelledby="per-day">
        <h2 id="per-day" className="mb-3 text-sm font-semibold text-ink">Replies per day</h2>
        {bars.length === 0 || bars.every((b) => b.count === 0) ? (
          <p className="text-sm text-ink-secondary">No replies yet this cycle. They show up here once your app or site talks to a character.</p>
        ) : (
          <>
            <div className="flex h-32 items-end gap-1" role="img" aria-label={bars.map((b) => `${b.date}: ${b.count}`).join("; ")}>
              {bars.map((b) => (
                <div key={b.date} className="flex h-full min-w-0 flex-1 flex-col justify-end" title={`${shortDate(b.date)}: ${b.count}`}>
                  <div className="w-full rounded-t bg-primary" style={{ height: `${(b.count / max) * 100}%` }} />
                </div>
              ))}
            </div>
            <div className="mt-2 flex justify-between text-xs text-ink-muted">
              <span>{shortDate(bars[0].date)}</span>
              <span>{shortDate(bars[bars.length - 1].date)}</span>
            </div>
          </>
        )}
        {characters.length > 0 && (
          <ul className="mt-4 divide-y divide-border-subtle border-t border-border-subtle text-sm">
            {characters.map((c) => (
              <li key={c.name} className="flex justify-between py-2">
                <span className="text-ink">{c.name}</span>
                <span className="tabular-nums text-ink-secondary">{c.count.toLocaleString("en-IN")}</span>
              </li>
            ))}
          </ul>
        )}
        {usage.capped && <p className="mt-2 text-xs text-ink-muted">The chart shows the latest 20,000 replies.</p>}
      </section>
    </div>
  );
}
