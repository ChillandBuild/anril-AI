"use client";

import { useState } from "react";
import Link from "next/link";
import { AiraLoader } from "@/components/AiraLoader";
import { cn } from "@/lib/utils";
import {
  EVALUATION_PERIODS, callReviewHref, getEvaluation, scoreText, scoreTone,
  type EvaluationPeriod, type EvaluationPerson, type EvaluationResponse, type ScoreTone,
} from "@/lib/callIqApi";
import { Card, ErrorBox, PeriodPicker, Stat } from "./CallIqShell";
import { useCallIqData } from "./useCallIqData";

const TONE_STYLE: Record<ScoreTone, string> = {
  good: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  ok: "bg-amber-50 text-amber-900 ring-amber-200",
  low: "bg-red-50 text-red-800 ring-red-200",
  none: "bg-slate-100 text-slate-700 ring-slate-200",
};

function whenText(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true }).format(d);
}

function PersonCard({ person }: { person: EvaluationPerson }) {
  const tone = scoreTone(person.avg_score);
  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <h2 className="min-w-0 truncate font-display text-base font-bold text-primary">{person.name}</h2>
        <span className={cn("shrink-0 rounded-full px-3 py-1 font-display text-base font-bold ring-1", TONE_STYLE[tone])} aria-label={`Average score ${scoreText(person.avg_score)} out of 100`}>
          {scoreText(person.avg_score)}
        </span>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3">
        <Stat label="Calls scored" value={person.calls_scored} />
        <Stat label="Best" value={scoreText(person.best)} />
        <Stat label="Lowest" value={scoreText(person.worst)} />
      </div>
      <div className="mt-4">
        <p className="font-label text-xs font-bold uppercase tracking-wide text-ink-secondary">Where to help</p>
        {person.top_weak_points.length === 0 ? (
          <p className="mt-1 font-label text-sm text-ink-secondary">
            {person.calls_scored === 0 ? "No scored calls in these days." : "Nothing stands out. Good work."}
          </p>
        ) : (
          <ul className="mt-1 space-y-1">
            {person.top_weak_points.map((w) => <li key={w} className="font-label text-sm text-primary">{w}</li>)}
          </ul>
        )}
      </div>
    </Card>
  );
}

export function EvaluationBoard() {
  const [period, setPeriod] = useState<EvaluationPeriod>("7d");
  const { data, err, loading, reload } = useCallIqData<EvaluationResponse>(() => getEvaluation(period), period);

  return (
    <div className="space-y-4">
      <PeriodPicker label="Days to look at" options={EVALUATION_PERIODS} value={period} onChange={setPeriod} />
      {err ? <ErrorBox message={err} onRetry={reload} /> : null}
      {loading && !data ? <AiraLoader inline className="min-h-40" /> : null}
      {data && !data.available ? (
        <Card><p className="font-label text-sm text-ink-secondary">{data.message || "Call scores are not available for your plan."}</p></Card>
      ) : null}
      {data && data.available ? (
        <>
          <p className="font-label text-xs text-ink-secondary">Scores are out of 100, marked by the AI on each recorded conversation.</p>
          {data.callers.length === 0 ? (
            <Card><p className="font-label text-sm text-ink-secondary">No telecallers to show yet.</p></Card>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {data.callers.map((p) => <PersonCard key={p.caller_id} person={p} />)}
            </div>
          )}
          <Card>
            <h2 className="font-display text-base font-bold text-primary">Lowest scored calls</h2>
            <p className="mb-3 mt-1 font-label text-xs text-ink-secondary">Open one to read what was said and what to fix.</p>
            {data.lowest_calls.length === 0 ? (
              <p className="font-label text-sm text-ink-secondary">No scored calls in these days.</p>
            ) : (
              <ul className="divide-y divide-[#c4c7c7]/30">
                {data.lowest_calls.map((c) => (
                  <li key={c.call_log_id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate font-label text-sm font-bold text-primary">
                        {c.caller_name || "Unnamed"}{c.lead_name ? ` called ${c.lead_name}` : ""}
                      </p>
                      <p className="font-label text-xs text-ink-secondary">{whenText(c.at)}</p>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className={cn("rounded-full px-2.5 py-1 font-label text-sm font-bold ring-1", TONE_STYLE[scoreTone(c.score)])}>{scoreText(c.score)}</span>
                      <Link href={callReviewHref(c.call_log_id)} className="inline-flex min-h-10 items-center rounded-lg px-3 font-label text-sm font-bold text-primary underline hover:bg-black/5">
                        Review call
                      </Link>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      ) : null}
    </div>
  );
}
