"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Loader2, Target } from "lucide-react";
import { toast } from "sonner";
import { AiraLoader } from "@/components/AiraLoader";
import { SwitchPill } from "@/components/ui/controls";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { cleanNumberText } from "../payments/advanceText";
import { Card, ErrorBox, InShort, PageHeader } from "../payments/MyBusinessUi";
import { myBusinessApi, type TargetOverview } from "@/lib/myBusinessApi";
import { cn } from "@/lib/utils";
import {
  buildBody,
  costCoverageLine,
  draftError,
  draftFromSaved,
  editableMonths,
  effectiveTarget,
  formatRupees,
  monthLabel,
  paiseToText,
  prettyRupeesText,
  sameBody,
  suggestionLine,
  type Mode,
  type TargetDraft,
  type TargetSaved,
} from "./targetLogic";

const INPUT = "min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:bg-surface-subtle disabled:text-ink-muted";

const MODES: { mode: Mode; label: string }[] = [
  { mode: "same", label: "Same every month" },
  { mode: "different", label: "Different for some months" },
];

function savedOf(o: TargetOverview): TargetSaved {
  return { monthly_paise: o.monthly_paise, months: o.months, show_team: o.show_team };
}

export default function TargetPage() {
  const { role } = useAuthRole();
  const isOwner = role === "owner";
  const [data, setData] = useState<TargetOverview | null>(null);
  const [draft, setDraft] = useState<TargetDraft | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setState("loading");
    try {
      const o = await myBusinessApi.target();
      setData(o);
      setDraft(draftFromSaved(savedOf(o), o.this_month.month));
      setState("ready");
    } catch {
      setState("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const currentKey = data?.this_month.month ?? "";
  const error = draft && data ? draftError(draft, currentKey) : null;
  const body = useMemo(() => (draft && data && !error ? buildBody(draft, savedOf(data), currentKey) : null), [draft, data, error, currentKey]);
  const dirty = !!(body && data && !sameBody(body, savedOf(data)));

  function patch(change: Partial<TargetDraft>) {
    setDraft((d) => (d ? { ...d, ...change } : d));
  }

  async function save() {
    if (!body) return;
    setSaving(true);
    try {
      const o = await myBusinessApi.saveTarget(body);
      setData(o);
      setDraft(draftFromSaved(savedOf(o), o.this_month.month));
      toast.success("Target saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the target");
    } finally {
      setSaving(false);
    }
  }

  const monthsWithMoney = data ? data.last3.filter((m) => (m.money_in_paise ?? 0) > 0).length : 0;
  const suggestion = data ? suggestionLine(data.suggested_paise, monthsWithMoney) : null;
  const thisTarget = data ? effectiveTarget(savedOf(data), data.this_month.month) : null;
  const pct = data?.this_month.pct ?? null;
  const coverage = costCoverageLine(data?.cost_coverage);

  return (
    <div className="w-full space-y-4 pb-10">
      <PageHeader icon={Target} title="Target & profit" subtitle="Set what you want to sell each month, and see how you are doing." />

      {state === "loading" ? <AiraLoader inline className="min-h-[200px]" /> : null}
      {state === "error" ? <ErrorBox message="Couldn't load this page." onRetry={() => void load()} /> : null}

      {state === "ready" && data && draft ? (
        <>
          <InShort>
            {thisTarget && pct != null
              ? `This month you have reached ${pct}% of your ${formatRupees(thisTarget)} target.`
              : "You have not set a target for this month yet."}
          </InShort>

          <Card id="target-heading" title="Monthly sales target" hint="Money in, after refunds, is counted against this. It is the same Money in you see on Home.">
            <fieldset disabled={!isOwner || saving} className="space-y-4">
              <legend className="sr-only">Monthly sales target</legend>
              <label className="block">
                <span className="text-sm font-semibold text-ink">Target for each month (₹)</span>
                <input
                  inputMode="decimal"
                  value={draft.monthlyText}
                  onChange={(e) => patch({ monthlyText: cleanNumberText(e.target.value) })}
                  onBlur={() => patch({ monthlyText: prettyRupeesText(draft.monthlyText) })}
                  placeholder="2,00,000"
                  className={cn(INPUT, "mt-1 max-w-xs")}
                />
              </label>

              {suggestion ? (
                <p className="text-sm text-ink-secondary">
                  {suggestion}{" "}
                  {isOwner && data.suggested_paise != null ? (
                    <button
                      type="button"
                      onClick={() => patch({ monthlyText: prettyRupeesText(paiseToText(data.suggested_paise)) })}
                      className="min-h-11 font-semibold text-primary underline"
                    >
                      Use this
                    </button>
                  ) : null}
                </p>
              ) : (
                <p className="text-sm text-ink-muted">A suggestion appears here after you have taken some money in a full month.</p>
              )}

              <div role="radiogroup" aria-label="Same target or different" className="grid gap-2 sm:grid-cols-2">
                {MODES.map((m) => {
                  const selected = draft.mode === m.mode;
                  return (
                    <button
                      key={m.mode}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      disabled={!isOwner || saving}
                      onClick={() => patch({ mode: m.mode })}
                      className={cn(
                        "min-h-11 rounded-xl border-2 px-3 py-2 text-left text-sm font-semibold text-ink transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-default",
                        selected ? "border-primary bg-primary-50" : "border-border bg-white enabled:hover:bg-surface-mid",
                      )}
                    >
                      {m.label}
                    </button>
                  );
                })}
              </div>

              {draft.mode === "different" ? (
                <div className="space-y-2">
                  <p className="text-sm text-ink-muted">Leave a month empty to use the target above.</p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {editableMonths(currentKey).map((key) => (
                      <label key={key} className="block">
                        <span className="text-sm font-semibold text-ink">{monthLabel(key)} (₹)</span>
                        <input
                          inputMode="decimal"
                          value={draft.monthTexts[key] ?? ""}
                          onChange={(e) => patch({ monthTexts: { ...draft.monthTexts, [key]: cleanNumberText(e.target.value) } })}
                          onBlur={() => patch({ monthTexts: { ...draft.monthTexts, [key]: prettyRupeesText(draft.monthTexts[key] ?? "") } })}
                          placeholder={draft.monthlyText || "Same as above"}
                          className={cn(INPUT, "mt-1")}
                        />
                      </label>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="flex items-start justify-between gap-4 border-t border-border/70 pt-4">
                <div className="min-w-0">
                  <p id="show-team-label" className="text-sm font-semibold text-ink">Show the target to my team on Home</p>
                  <p className="mt-0.5 text-sm text-ink-muted">They see &ldquo;93% of target&rdquo;, not the money.</p>
                </div>
                <SwitchPill on={draft.showTeam} onChange={(v) => patch({ showTeam: v })} disabled={!isOwner || saving} aria-label="Show the target to my team on Home" />
              </div>
            </fieldset>

            {error ? <p className="mt-3 text-sm font-semibold text-danger" role="alert">{error}</p> : null}

            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-ink-muted">{isOwner ? "Home shows your target as a box called Target this month." : "Only the owner can change this."}</p>
              {isOwner ? (
                <button type="button" onClick={() => void save()} disabled={!dirty || !!error || saving} className="btn-primary min-h-11">
                  {saving ? <Loader2 size={14} className="animate-spin" aria-hidden /> : null}
                  {saving ? "Saving…" : "Save"}
                </button>
              ) : null}
            </div>
          </Card>

          <Card id="profit-heading" title="Profit">
            <p className="text-sm text-ink">Profit will show once each sale keeps what the item cost. Coming with Reports.</p>
            {coverage ? <p className="mt-2 text-sm font-semibold text-ink">{coverage}</p> : null}
            <p className="mt-1 text-sm text-ink-muted">
              Add a cost price to your items in the{" "}
              <Link href="/dashboard/catalog" className="font-semibold text-primary underline">Catalogue</Link>.
            </p>
          </Card>
        </>
      ) : null}
    </div>
  );
}
