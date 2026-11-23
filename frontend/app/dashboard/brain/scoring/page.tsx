"use client";
import { useEffect, useState } from "react";
import { NoAccess, SetupShell, useSetupAccess } from "@/components/ai-setup/SetupShell";
import { aiSetupApi, type ScoringView } from "@/lib/aiSetupApi";

// Order of the bar, low to high; flex weights are the width of each score range (0 / 1-3 / 4-7 / 8-10).
const BAR = [
  { key: "not_interested", label: "Not interested", range: "0", weight: 1, color: "#64748b", tint: "#f8fafc" },
  { key: "cold", label: "Cold", range: "1 to 3", weight: 3, color: "#3b82f6", tint: "#eff6ff" },
  { key: "warm", label: "Warm", range: "4 to 7", weight: 4, color: "#d97706", tint: "#fffbeb" },
  { key: "hot", label: "Hot", range: "8 to 10", weight: 3, color: "#e11d48", tint: "#fff1f2" },
] as const;

const LABEL = "font-label text-[11px] font-bold uppercase tracking-wide text-ink-secondary";

export default function ScoringPage() {
  const { loading: roleLoading, canView } = useSetupAccess();
  const [view, setView] = useState<ScoringView | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!canView) return;
    let live = true;
    aiSetupApi.scoring().then((v) => { if (live) setView(v); }).catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [canView]);

  if (roleLoading) return <div className="m-6 min-h-[320px] animate-pulse rounded-2xl bg-border-subtle" />;
  if (!canView) return <NoAccess />;

  const levels = view ? BAR.map((b) => ({ bar: b, level: view.levels.find((l) => l.key === b.key) })) : [];

  return (
    <SetupShell toolbar={view ? <span className="font-body text-sm text-ink-secondary">This is how it works today. {view.note}</span> : undefined}>
      {failed && <p role="alert" className="rounded-xl bg-surface-low px-3 py-2 font-body text-sm text-ink-secondary">Could not load this. Please refresh.</p>}
      {!view && !failed && <div className="min-h-[200px] animate-pulse rounded-2xl bg-border-subtle" />}
      {view && (
        <>
          <section className="card flex flex-col gap-3" aria-labelledby="pts-h">
            <div>
              <h2 id="pts-h" className="font-display text-base font-bold text-ink">Points from 0 to 10</h2>
              <p className="font-body text-xs text-ink-secondary">After every message the AI agent gives the customer a score. The score picks the type.</p>
            </div>
            <div className="flex gap-0.5" role="img" aria-label="Not interested 0 points, Cold 1 to 3, Warm 4 to 7, Hot 8 to 10">
              {BAR.map((b, i) => (
                <div key={b.key} title={`${b.label}: points ${b.range}`} style={{ flex: b.weight, background: b.color }}
                  className={`h-3.5 ${i === 0 ? "rounded-l-full" : ""} ${i === BAR.length - 1 ? "rounded-r-full" : ""}`} />
              ))}
            </div>
            <div className="-mt-1 flex gap-0.5 font-body text-xs text-ink-secondary" aria-hidden>
              {BAR.map((b) => <span key={b.key} style={{ flex: b.weight }}>{b.label} · {b.range}</span>)}
            </div>
          </section>
          <ul className="flex flex-wrap items-stretch gap-3">
            {[...levels].reverse().map(({ bar, level }) => level && (
              <li key={bar.key} className="card flex min-w-0 flex-[1_1_250px] flex-col gap-3 !p-[18px]" style={{ borderTop: `4px solid ${bar.color}` }}>
                <div className="flex items-baseline justify-between gap-3">
                  <h2 className="font-display text-lg font-bold text-ink">{level.label}</h2>
                  <span className="font-body text-xs text-ink-secondary">Points {level.points}</span>
                </div>
                <p className="font-body text-sm text-ink-secondary">{level.meaning}</p>
                <div className="rounded-xl px-3 py-2.5" style={{ background: bar.tint }}>
                  <p className={LABEL}>Your own examples</p>
                  {level.your_examples.length > 0 ? (
                    <ul className="mt-1 space-y-0.5 font-body text-[13px] text-ink">{level.your_examples.map((e) => <li key={e}>{e}</li>)}</ul>
                  ) : (
                    <p className="mt-1 font-body text-[13px] text-ink-secondary">None added yet.</p>
                  )}
                </div>
                {level.key === "not_interested" && view.not_interested_words.length > 0 && (
                  <div>
                    <p className={LABEL}>Words that count straight away</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {view.not_interested_words.map((w) => <span key={w} className="rounded-full border border-border px-2.5 py-0.5 font-body text-xs text-ink">{w}</span>)}
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
          <section className="card" aria-labelledby="q-h">
            <h2 id="q-h" className="font-display text-base font-bold text-ink">Questions to ask every customer</h2>
            {view.questions.length ? (
              <ol className="mt-2 list-decimal space-y-1 pl-5 font-body text-sm text-ink">{view.questions.map((q) => <li key={q}>{q}</li>)}</ol>
            ) : (
              <p className="mt-2 font-body text-sm text-ink-secondary">{view.questions_note}</p>
            )}
          </section>
        </>
      )}
    </SetupShell>
  );
}
