"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { History, Loader2, Target, UserRound, Ban } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { aiSetupApi, type ReportCard } from "@/lib/aiSetupApi";
import { formatRupees } from "@/components/deals/money";
import { cn } from "@/lib/utils";

export type BrainOverviewData = {
  knows_pct: number;
  missing: string[];
  who: { talks_like: string | null; language: string; about: string | null };
  goals: string[];
  goal_choices: { key: string; label: string }[];
  never: { count: number; first: string[] };
  recent: { id: string; reason: string | null; at: string | null }[];
};

const DESCRIPTION_HREF = "/dashboard/knowledge?tab=description";

/** "Picked 1st/2nd": a click adds the goal at the end, or takes it off. Two at most. */
export function toggleGoal(goals: string[], key: string): string[] {
  if (goals.includes(key)) return goals.filter((g) => g !== key);
  return goals.length >= 2 ? [goals[0], key] : [...goals, key];
}

function when(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" });
}

function Ring({ pct }: { pct: number }) {
  const r = 22;
  const c = 2 * Math.PI * r;
  return (
    <svg width="56" height="56" viewBox="0 0 56 56" aria-hidden="true" className="shrink-0">
      <circle cx="28" cy="28" r={r} fill="none" stroke="currentColor" strokeWidth="6" className="text-primary/15" />
      <circle cx="28" cy="28" r={r} fill="none" stroke="currentColor" strokeWidth="6" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={c * (1 - pct / 100)} transform="rotate(-90 28 28)" className="text-primary" />
      <text x="28" y="32" textAnchor="middle" className="fill-ink font-display text-[12px] font-bold">{pct}%</text>
    </svg>
  );
}

/**
 * Top of Anril Brain: how much the AI agent knows, who it is, the goal of every chat (a real
 * setting the AI reads), Never do, recent changes, and this week's numbers.
 */
export function BrainOverview({ canManage, canSeeMoney }: { canManage: boolean; canSeeMoney: boolean }) {
  const [data, setData] = useState<BrainOverviewData | null>(null);
  const [week, setWeek] = useState<ReportCard | null>(null);
  const [goals, setGoals] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let live = true;
    apiFetch<BrainOverviewData>("/api/v1/brain/overview")
      .then((d) => { if (live) { setData(d); setGoals(d.goals); } })
      .catch(() => {});
    aiSetupApi.reportCard("7d").then((r) => live && setWeek(r)).catch(() => {});
    return () => { live = false; };
  }, []);

  if (!data) return null;
  const changed = goals.join(",") !== data.goals.join(",");

  async function saveGoals() {
    setSaving(true);
    try {
      const res = await apiFetch<{ goals: string[] }>("/api/v1/brain/goals", { method: "PUT", body: JSON.stringify({ goals }) });
      setData((d) => (d ? { ...d, goals: res.goals } : d));
      toast.success("Saved. The AI agent works towards it from the next message.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save the goals");
    } finally {
      setSaving(false);
    }
  }

  const card = "rounded-2xl border border-border bg-white p-4 shadow-card";
  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0 space-y-3">
        <div className={cn(card, "flex flex-wrap items-center gap-4 border-primary/20 bg-primary-light/40")}>
          <Ring pct={data.knows_pct} />
          <div className="min-w-0 flex-1">
            <p className="font-display text-[15px] font-bold text-ink">Your AI agent knows {data.knows_pct}% of what it needs</p>
            <p className="text-[13px] text-ink-secondary">
              {data.missing.length ? <>Add these to reach 100%: <span className="font-semibold text-primary">{data.missing.join(" · ")}</span></> : "It has everything on the list. Keep it up to date."}
            </p>
          </div>
          {data.missing.length > 0 && canManage && (
            <Link href="/dashboard/knowledge" className="inline-flex h-10 items-center rounded-xl bg-primary px-4 text-sm font-bold text-white hover:bg-primary-dark">Add now</Link>
          )}
        </div>

        <div className={card}>
          <div className="flex items-center justify-between gap-2">
            <h3 className="flex items-center gap-2 font-display text-[15px] font-bold text-ink"><UserRound size={15} className="text-primary" /> Who your AI agent is</h3>
            {canManage && <Link href={DESCRIPTION_HREF} className="text-xs font-bold text-primary hover:underline">Edit ›</Link>}
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            {[["About", data.who.about], ["Talks like", data.who.talks_like], ["Language", data.who.language]].map(([label, value]) => (
              <div key={label as string} className="min-w-0 rounded-xl border border-border px-3 py-2">
                <p className="text-[11px] text-ink-muted">{label}</p>
                <p className="truncate text-[13px] font-semibold text-ink" title={(value as string) || ""}>{value || <span className="font-normal text-ink-muted">Not written yet</span>}</p>
              </div>
            ))}
          </div>
        </div>

        <div className={card}>
          <h3 className="flex flex-wrap items-baseline gap-2 font-display text-[15px] font-bold text-ink">
            <Target size={15} className="self-center text-primary" /> Goal of every chat
            <span className="font-body text-xs font-normal text-ink-muted">pick 1 or 2 · the AI works on one at a time: 1 first, 2 only if the customer says not now</span>
          </h3>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {data.goal_choices.map((g) => {
              const at = goals.indexOf(g.key);
              return (
                <button key={g.key} type="button" disabled={!canManage} aria-pressed={at >= 0}
                  onClick={() => setGoals((cur) => toggleGoal(cur, g.key))}
                  className={cn("inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-[13px] font-semibold transition disabled:cursor-not-allowed",
                    at >= 0 ? "border-primary bg-primary/5 text-primary" : "border-border text-ink hover:border-ink-muted")}>
                  {at >= 0 && <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary text-[11px] text-white">{at + 1}</span>}
                  {g.label}
                </button>
              );
            })}
            {canManage && changed && (
              <button type="button" onClick={() => void saveGoals()} disabled={saving}
                className="ml-auto inline-flex h-9 items-center gap-1.5 rounded-xl bg-primary px-4 text-[13px] font-bold text-white disabled:opacity-50">
                {saving && <Loader2 size={13} className="animate-spin" />} Save
              </button>
            )}
          </div>
          {goals.length === 0 && <p className="mt-2 text-xs text-ink-muted">No goal picked: the AI agent answers questions and hands over when needed.</p>}
        </div>

        <div className={cn(card, "flex items-start gap-3")}>
          <Ban size={15} className="mt-0.5 shrink-0 text-red-500" />
          <div className="min-w-0 flex-1">
            <p className="font-display text-[15px] font-bold text-ink">Never do <span className="font-body text-xs font-normal text-ink-muted">· {data.never.count} {data.never.count === 1 ? "rule" : "rules"}</span></p>
            <p className="truncate text-[13px] text-ink-secondary">{data.never.first.length ? data.never.first.join(" · ") : "Nothing written yet. Add what your AI agent must never say or promise."}</p>
          </div>
          {canManage && <Link href={DESCRIPTION_HREF} className="shrink-0 text-xs font-bold text-primary hover:underline">Edit ›</Link>}
        </div>
      </div>

      <aside className="space-y-3">
        <div className={card}>
          <h3 className="flex items-center gap-2 font-display text-[15px] font-bold text-ink"><History size={15} className="text-primary" /> Recent changes</h3>
          {data.recent.length === 0 ? (
            <p className="mt-2 text-[13px] text-ink-muted">No changes yet.</p>
          ) : (
            <ul className="mt-2 divide-y divide-border">
              {data.recent.map((r) => (
                <li key={r.id} className="py-2">
                  <p className="truncate text-[13px] font-semibold text-ink">{r.reason || "Description edited"}</p>
                  <p className="text-xs text-ink-muted">{when(r.at)}</p>
                </li>
              ))}
            </ul>
          )}
          <Link href={DESCRIPTION_HREF} className="text-xs font-bold text-primary hover:underline">All versions and undo ›</Link>
        </div>
        {week && (
          <div className={cn(card, "border-primary/20 bg-primary-light/40")}>
            <h3 className="font-display text-[15px] font-bold text-ink">This week</h3>
            <dl className="mt-2 space-y-1 text-[13px] text-ink-secondary">
              <div className="flex justify-between"><dt>AI handled alone</dt><dd className="font-bold text-ink">{week.handled_alone_pct == null ? "—" : `${week.handled_alone_pct}% of chats`}</dd></div>
              <div className="flex justify-between"><dt>Passed to a person</dt><dd className="font-bold text-ink">{week.passed_to_person}</dd></div>
              <div className="flex justify-between"><dt>Wrong answers marked 👎</dt><dd className="font-bold text-ink">{week.wrong_answers}</dd></div>
              {canSeeMoney && week.revenue_from_ai_paise != null && (
                <div className="flex justify-between"><dt>Money from AI chats</dt><dd className="font-bold text-ink">{formatRupees(week.revenue_from_ai_paise)}</dd></div>
              )}
            </dl>
            <Link href="/dashboard/brain/report-card" className="mt-2 inline-block text-xs font-bold text-primary hover:underline">Full report card ›</Link>
          </div>
        )}
      </aside>
    </div>
  );
}
