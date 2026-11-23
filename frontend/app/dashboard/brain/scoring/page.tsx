"use client";
import { useEffect, useState } from "react";
import { NoAccess, SetupShell, useSetupAccess } from "@/components/ai-setup/SetupShell";
import { aiSetupApi, type ScoringView } from "@/lib/aiSetupApi";

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

  return (
    <SetupShell title="Questions & scoring" intro="How the AI agent decides if a customer is Hot, Warm, Cold or Not interested.">
      {failed && <p role="alert" className="rounded-xl bg-surface-low px-3 py-2 font-body text-sm text-ink-secondary">Could not load this. Please refresh.</p>}
      {!view && !failed && <div className="min-h-[200px] animate-pulse rounded-2xl bg-border-subtle" />}
      {view && (
        <>
          <p className="rounded-xl bg-surface-low px-3 py-2 font-body text-sm text-ink-secondary">This is how it works today. {view.note}</p>
          <section className="card" aria-labelledby="q-h">
            <h2 id="q-h" className="font-display text-base font-bold text-ink">Questions to ask every customer</h2>
            {view.questions.length ? (
              <ol className="mt-2 list-decimal space-y-1 pl-5 font-body text-sm text-ink">{view.questions.map((q) => <li key={q}>{q}</li>)}</ol>
            ) : (
              <p className="mt-2 font-body text-sm text-ink-secondary">{view.questions_note}</p>
            )}
          </section>
          <ul className="space-y-3">
            {view.levels.map((level) => (
              <li key={level.key} className="card">
                <div className="flex items-baseline justify-between gap-3">
                  <h2 className="font-display text-base font-bold text-ink">{level.label}</h2>
                  <span className="font-label text-xs font-bold text-ink-secondary">Points: {level.points}</span>
                </div>
                <p className="mt-1 font-body text-sm text-ink-secondary">{level.meaning}</p>
                {level.your_examples.length > 0 && (
                  <div className="mt-2">
                    <p className="font-label text-xs font-bold text-ink">Your own examples</p>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {level.your_examples.map((e) => <span key={e} className="rounded-full bg-surface-low px-2.5 py-1 font-body text-xs text-ink">{e}</span>)}
                    </div>
                  </div>
                )}
                {level.key === "not_interested" && view.not_interested_words.length > 0 && (
                  <div className="mt-2">
                    <p className="font-label text-xs font-bold text-ink">Words that count straight away</p>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {view.not_interested_words.map((w) => <span key={w} className="rounded-full bg-surface-low px-2.5 py-1 font-body text-xs text-ink">{w}</span>)}
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </SetupShell>
  );
}
