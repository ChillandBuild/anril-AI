"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Circle } from "lucide-react";
import { cn, timeAgo } from "@/lib/utils";
import {
  companionsApi,
  type AgentUsage,
  type Companion,
  type CompanionInstall,
  type CompanionOverview,
  type CompanionPerson,
  type CompanionRequestLog,
} from "@/lib/api";
import { CopyButton } from "@/components/agents/CodeBlock";
import { appPrompt } from "@/components/agents/installPrompt";
import { setupSteps } from "@/components/agents/overviewSteps";
import { personLabel } from "@/components/agents/playground";
import { barMax, dailyBars } from "@/components/agents/requestsView";
import { CARD, ErrorNote, LoadingRows } from "@/components/agents/ui";

const CHART_DAYS = 14;

/**
 * Anril Agents home: setup checklist (until done), four numbers, calls per day for 14 days,
 * the 5 people who talked to the live character most recently, and the install prompt to copy.
 * The extras (usage, calls, people) load on their own; if one fails its card says so and the rest still show.
 */
export default function AgentsOverviewPage() {
  const [overview, setOverview] = useState<CompanionOverview | null>(null);
  const [live, setLive] = useState<Companion | null>(null);
  const [install, setInstall] = useState<CompanionInstall | null>(null);
  const [error, setError] = useState("");
  const [usage, setUsage] = useState<AgentUsage | null>(null);
  const [calls, setCalls] = useState<CompanionRequestLog | null | "failed">(null);
  const [recent, setRecent] = useState<CompanionPerson[] | null | "failed">(null);

  const load = useCallback(() => {
    setError("");
    Promise.all([companionsApi.overview(), companionsApi.list()])
      .then(([o, list]) => {
        setOverview(o);
        const first = list.find((c) => c.status === "live") ?? null;
        setLive(first);
        if (first) {
          companionsApi.install(first.id).then(setInstall).catch(() => setInstall(null));
          companionsApi
            .people(first.id, { limit: 5 })
            .then((r) => setRecent([...r.people].sort((a, b) => b.last_seen_at.localeCompare(a.last_seen_at)).slice(0, 5)))
            .catch(() => setRecent("failed"));
        } else {
          setRecent([]);
        }
      })
      .catch((e: Error) => setError(e.message || "Could not load the overview."));
    companionsApi.usage().then(setUsage).catch(() => setUsage(null));
    companionsApi
      .requests({ days: CHART_DAYS })
      .then(setCalls)
      .catch(() => setCalls("failed"));
  }, []);
  useEffect(load, [load]);

  if (error) return <div className="w-full p-4 sm:p-6"><ErrorNote message={error} onRetry={load} /></div>;
  if (!overview) return <div className="w-full p-4 sm:p-6"><LoadingRows rows={4} /></div>;

  const steps = setupSteps(overview);
  const allDone = steps.every((s) => s.done);
  const tiles = [
    { label: "Live characters", value: overview.live_characters },
    { label: "People", value: overview.people },
    { label: "Messages this week", value: overview.messages_this_week },
    {
      label: "Replies this cycle",
      value: usage?.used ?? null,
      of: usage && usage.included > 0 ? `of ${usage.included.toLocaleString()} included` : undefined,
    },
  ];
  const bars = calls && calls !== "failed" ? dailyBars(calls.daily, CHART_DAYS) : [];
  const max = barMax(bars);

  return (
    <div className="w-full space-y-4 p-4 sm:p-6">
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
            <div className="mt-1 text-2xl font-semibold tabular-nums text-ink">{t.value === null ? "—" : t.value.toLocaleString()}</div>
            {"of" in t && t.of && <div className="text-xs text-ink-muted">{t.of}</div>}
          </div>
        ))}
      </div>

      <div className="grid gap-3 lg:grid-cols-5">
        <section className={cn(CARD, "lg:col-span-3")} aria-labelledby="calls-title">
          <h2 id="calls-title" className="mb-3 text-sm font-semibold text-ink">Calls from your app or site, last {CHART_DAYS} days</h2>
          {calls === null ? (
            <LoadingRows rows={2} />
          ) : calls === "failed" ? (
            <p className="text-sm text-ink-secondary">Could not load calls. They are on the Requests page.</p>
          ) : calls.total === 0 ? (
            <p className="text-sm text-ink-secondary">
              No calls in the last {CHART_DAYS} days. They show up here once your app or site talks to a character. Playground chats are not counted.
            </p>
          ) : (
            <>
              <div className="flex h-28 items-end gap-1" role="img" aria-label={bars.map((b) => `${b.date}: ${b.ok} ok, ${b.error} failed`).join("; ")}>
                {bars.map((b) => (
                  <div key={b.date} className="flex h-full min-w-0 flex-1 flex-col justify-end" title={`${b.date}: ${b.ok} ok, ${b.error} failed`}>
                    <div className="w-full rounded-t bg-danger/70" style={{ height: `${(b.error / max) * 100}%` }} />
                    <div className={cn("w-full bg-primary", b.error === 0 && "rounded-t")} style={{ height: `${(b.ok / max) * 100}%` }} />
                  </div>
                ))}
              </div>
              <p className="mt-2 text-xs text-ink-muted">
                {calls.total.toLocaleString()} calls · {calls.errors.toLocaleString()} failed
                {calls.median_ms !== null && ` · median reply ${(calls.median_ms / 1000).toFixed(1)} s`} ·{" "}
                <Link href="/dashboard/agents/requests" className="font-medium text-primary hover:underline">See requests</Link>
              </p>
            </>
          )}
        </section>

        <section className={cn(CARD, "lg:col-span-2")} aria-labelledby="recent-title">
          <h2 id="recent-title" className="mb-2 text-sm font-semibold text-ink">Recent people{live ? ` · ${live.name}` : ""}</h2>
          {recent === null ? (
            <LoadingRows rows={3} />
          ) : recent === "failed" ? (
            <p className="text-sm text-ink-secondary">Could not load people.</p>
          ) : !live ? (
            <p className="text-sm text-ink-secondary">Set a character Live to see who talks to it.</p>
          ) : recent.length === 0 ? (
            <p className="text-sm text-ink-secondary">No one has chatted with {live.name} yet.</p>
          ) : (
            <ul className="divide-y divide-border-subtle">
              {recent.map((p) => (
                <li key={p.external_user_id} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="truncate text-ink">{personLabel(p)}</span>
                    {p.is_test && <span className="shrink-0 rounded-full bg-surface-mid px-1.5 py-0.5 text-[10px] font-medium text-ink-muted">Playground</span>}
                  </span>
                  <span className="shrink-0 text-xs tabular-nums text-ink-muted">
                    {p.message_count.toLocaleString()} msgs · {timeAgo(p.last_seen_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {live && recent !== null && recent !== "failed" && recent.length > 0 && (
            <Link href="/dashboard/agents/memories" className="mt-2 inline-block text-sm font-medium text-primary hover:underline">
              See all in Memories →
            </Link>
          )}
        </section>
      </div>

      <section className={cn(CARD, "flex flex-wrap items-center justify-between gap-3")} aria-labelledby="prompt-title">
        <div className="min-w-0">
          <h2 id="prompt-title" className="text-sm font-semibold text-ink">Connect with your AI coding tool</h2>
          <p className="text-sm text-ink-secondary">
            {live
              ? `Copy a prompt that connects ${live.name} to your own app's chat, from any backend. No secret in it.`
              : "Set a character Live to get its setup prompt."}{" "}
            <Link href="/dashboard/agents/install" className="font-medium text-primary hover:underline">Website chat bubble instead</Link>
          </p>
        </div>
        {live && install ? (
          <CopyButton text={appPrompt(install, live.name)} label="Copy setup prompt" />
        ) : (
          <Link href="/dashboard/agents/install" className="text-sm font-medium text-primary hover:underline">Open Install</Link>
        )}
      </section>

      {overview.model && overview.model_ready && <p className="text-xs text-ink-muted">Replies use {overview.model}.</p>}
    </div>
  );
}
