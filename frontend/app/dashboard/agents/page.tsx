"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Circle } from "lucide-react";
import { cn } from "@/lib/utils";
import { companionsApi, type Companion, type CompanionInstall, type CompanionOverview } from "@/lib/api";
import { CopyButton } from "@/components/agents/CodeBlock";
import { installPrompt } from "@/components/agents/installPrompt";
import { setupSteps } from "@/components/agents/overviewSteps";
import { CARD, ErrorNote, LoadingRows } from "@/components/agents/ui";

/** Anril Agents home: setup checklist, four numbers, and the install prompt to copy. */
export default function AgentsOverviewPage() {
  const [overview, setOverview] = useState<CompanionOverview | null>(null);
  const [live, setLive] = useState<Companion | null>(null);
  const [install, setInstall] = useState<CompanionInstall | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    Promise.all([companionsApi.overview(), companionsApi.list()])
      .then(([o, list]) => {
        setOverview(o);
        const first = list.find((c) => c.status === "live") ?? null;
        setLive(first);
        if (first) companionsApi.install(first.id).then(setInstall).catch(() => setInstall(null));
      })
      .catch((e: Error) => setError(e.message || "Could not load the overview."));
  }, []);
  useEffect(load, [load]);

  if (error) return <div className="mx-auto max-w-5xl p-4 sm:p-6"><ErrorNote message={error} onRetry={load} /></div>;
  if (!overview) return <div className="mx-auto max-w-5xl p-4 sm:p-6"><LoadingRows rows={4} /></div>;

  const steps = setupSteps(overview);
  const allDone = steps.every((s) => s.done);
  const tiles = [
    { label: "Live characters", value: overview.live_characters },
    { label: "People", value: overview.people },
    { label: "Messages this week", value: overview.messages_this_week },
    { label: "Active keys", value: overview.active_keys },
  ];

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      {!overview.model_ready && (
        <div role="alert" className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>
            Characters can&apos;t answer yet: {overview.model ? `the API key for ${overview.model} is missing` : "no AI model is set"}. Ask Anril support to set it in your AI settings.
          </span>
        </div>
      )}

      {!allDone && (
        <section className={CARD} aria-labelledby="setup-title">
          <h2 id="setup-title" className="mb-3 text-sm font-semibold text-ink">Get your first character on your site</h2>
          <ol className="space-y-2">
            {steps.map((s, i) => (
              <li key={s.id} className="flex items-center gap-3 rounded-xl border border-border-subtle px-3 py-2.5">
                {s.done ? (
                  <CheckCircle2 size={18} className="shrink-0 text-success" aria-label="Done" />
                ) : (
                  <Circle size={18} className="shrink-0 text-ink-muted" aria-label="Not done" />
                )}
                <div className="min-w-0 flex-1">
                  <div className={cn("text-sm font-medium", s.done ? "text-ink-secondary" : "text-ink")}>
                    {i + 1}. {s.title}
                  </div>
                  <div className="text-xs text-ink-muted">{s.detail}</div>
                </div>
                {!s.done && (
                  <Link href={s.href} className="shrink-0 text-sm font-medium text-primary hover:underline">
                    {s.action}
                  </Link>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className={cn(CARD, "p-4")}>
            <div className="text-xs text-ink-muted">{t.label}</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums text-ink">{t.value.toLocaleString()}</div>
          </div>
        ))}
      </div>

      <section className={cn(CARD, "flex flex-wrap items-center justify-between gap-3")} aria-labelledby="prompt-title">
        <div className="min-w-0">
          <h2 id="prompt-title" className="text-sm font-semibold text-ink">Install with your AI coding tool</h2>
          <p className="text-sm text-ink-secondary">
            {live ? `Copy a prompt that installs ${live.name} on your site. No secret in it.` : "Set a character Live to get its install prompt."}
          </p>
        </div>
        {live && install ? (
          <CopyButton text={installPrompt(install, live.name)} label="Copy prompt" />
        ) : (
          <Link href="/dashboard/agents/install" className="text-sm font-medium text-primary hover:underline">Open Install</Link>
        )}
      </section>

      {overview.model && overview.model_ready && <p className="text-xs text-ink-muted">Replies use {overview.model}.</p>}
    </div>
  );
}
