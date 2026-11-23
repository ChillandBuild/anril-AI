"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Loader2, Wallet } from "lucide-react";
import { toast } from "sonner";
import { AiraLoader } from "@/components/AiraLoader";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { myBusinessApi, type AdvanceRuleBody, type PaymentsOverview } from "@/lib/myBusinessApi";
import { cn } from "@/lib/utils";
import {
  belowMinLine,
  cleanNumberText,
  draftError,
  draftFromRule,
  exampleLine,
  ruleFromDraft,
  sameRule,
  type AdvanceDraft,
  type AdvanceKind,
} from "./advanceText";
import { Card, ComingLater, ErrorBox, PageHeader, StatusDot } from "./MyBusinessUi";

const KINDS: { kind: AdvanceKind; label: string; hint: string }[] = [
  { kind: "none", label: "No advance", hint: "The customer pays when they collect." },
  { kind: "fixed", label: "Fixed amount ₹", hint: "The same amount on every order." },
  { kind: "percent", label: "Part of the bill %", hint: "A share of each order's total." },
];

const COMING_LATER = [
  "AI agent offers Pay full or advance",
  "Show who changed the advance on an order",
  "Turn balance reminders on/off",
];

const INPUT = "min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:bg-surface-subtle disabled:text-ink-muted";

export default function PaymentsPage() {
  const { role } = useAuthRole();
  const isOwner = role === "owner";
  const [overview, setOverview] = useState<PaymentsOverview | null>(null);
  const [rule, setRule] = useState<AdvanceRuleBody | null>(null);
  const [ruleHidden, setRuleHidden] = useState<false | "forbidden" | "failed">(false);
  const [draft, setDraft] = useState<AdvanceDraft>({ kind: "none", valueText: "", minText: "" });
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setState("loading");
    try {
      const [ov, ruleResult] = await Promise.all([
        myBusinessApi.payments(),
        // Reading the rule needs Orders access; a person without it still sees the rest of the page.
        myBusinessApi.advanceRule().then(
          (r) => ({ ok: true as const, r }),
          (e: unknown) => ({ ok: false as const, forbidden: (e as { status?: number } | null)?.status === 403 }),
        ),
      ]);
      setOverview(ov);
      if (ruleResult.ok) {
        setRule(ruleResult.r);
        setDraft(draftFromRule(ruleResult.r));
        setRuleHidden(false);
      } else {
        setRule(null);
        setRuleHidden(ruleResult.forbidden ? "forbidden" : "failed");
      }
      setState("ready");
    } catch {
      setState("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const error = draftError(draft);
  const draftRule = useMemo(() => ruleFromDraft(draft), [draft]);
  const dirty = rule != null && !sameRule(draftRule, rule);

  async function save() {
    if (!rule || error) return;
    setSaving(true);
    try {
      const saved = await myBusinessApi.saveAdvanceRule(draftRule);
      setRule(saved);
      setDraft(draftFromRule(saved));
      toast.success("Advance rule saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the advance rule");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl space-y-4 pb-10">
      <PageHeader icon={Wallet} title="Payments & advance" subtitle="How you ask for money on orders, and what happens around it." />

      {state === "loading" ? <AiraLoader inline className="min-h-[200px]" /> : null}
      {state === "error" ? <ErrorBox message="Couldn't load this page." onRetry={() => void load()} /> : null}

      {state === "ready" && overview ? (
        <>
          <Card id="advance-heading" title="Ask for an advance on orders?" hint="This is the advance a new order starts with. Staff can change it on one order.">
            {ruleHidden === "forbidden" ? (
              <p className="text-sm text-ink-muted">The advance rule is shown to people who can see Orders. Ask the owner to change it.</p>
            ) : ruleHidden === "failed" ? (
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-ink-muted">Couldn&apos;t load the advance rule. Try again.</p>
                <button type="button" onClick={() => void load()} className="btn-secondary min-h-11">Try again</button>
              </div>
            ) : (
              <fieldset disabled={!isOwner || saving} className="space-y-4">
                <legend className="sr-only">Advance on orders</legend>
                <div role="radiogroup" aria-labelledby="advance-heading" className="grid gap-2 sm:grid-cols-3">
                  {KINDS.map((k) => {
                    const selected = draft.kind === k.kind;
                    return (
                      <button
                        key={k.kind}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        disabled={!isOwner || saving}
                        onClick={() => setDraft((d) => ({ ...d, kind: k.kind }))}
                        className={cn(
                          "min-h-11 rounded-xl border-2 px-3 py-2.5 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-default",
                          selected ? "border-primary bg-primary-50" : "border-border bg-white enabled:hover:bg-surface-mid",
                        )}
                      >
                        <span className="block text-sm font-semibold text-ink">{k.label}</span>
                        <span className="mt-0.5 block text-sm text-ink-muted">{k.hint}</span>
                      </button>
                    );
                  })}
                </div>

                {draft.kind !== "none" ? (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="block">
                      <span className="text-sm font-semibold text-ink">{draft.kind === "percent" ? "Percent of the bill" : "Advance amount (₹)"}</span>
                      <input
                        inputMode="decimal"
                        value={draft.valueText}
                        onChange={(e) => setDraft((d) => ({ ...d, valueText: cleanNumberText(e.target.value) }))}
                        placeholder={draft.kind === "percent" ? "30" : "1000"}
                        className={cn(INPUT, "mt-1")}
                      />
                    </label>
                    <label className="block">
                      <span className="text-sm font-semibold text-ink">Only for orders of this amount or more (₹)</span>
                      <input
                        inputMode="decimal"
                        value={draft.minText}
                        onChange={(e) => setDraft((d) => ({ ...d, minText: cleanNumberText(e.target.value) }))}
                        placeholder="Leave empty for every order"
                        className={cn(INPUT, "mt-1")}
                      />
                    </label>
                  </div>
                ) : null}

                <div className="rounded-xl bg-surface-subtle px-4 py-3" aria-live="polite">
                  {error ? (
                    <p className="text-sm font-semibold text-danger">{error}</p>
                  ) : (
                    <>
                      <p className="text-sm font-semibold text-ink">{exampleLine(draftRule)}</p>
                      {belowMinLine(draftRule) ? <p className="mt-0.5 text-sm text-ink-muted">{belowMinLine(draftRule)}</p> : null}
                    </>
                  )}
                </div>
              </fieldset>
            )}

            <p className="mt-4 text-sm text-ink-muted">
              An item can have its own advance:{" "}
              <Link href="/dashboard/catalog" className="font-semibold text-primary underline">set it on the item&apos;s page</Link>.
            </p>

            {!ruleHidden ? (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-ink-muted">
                  {isOwner ? "Orders › Settings changes the same rule." : "Only the owner can change this."}
                </p>
                {isOwner ? (
                  <button type="button" onClick={() => void save()} disabled={!dirty || !!error || saving} className="btn-primary min-h-11">
                    {saving ? <Loader2 size={14} className="animate-spin" aria-hidden /> : null}
                    {saving ? "Saving…" : "Save"}
                  </button>
                ) : null}
              </div>
            ) : null}
          </Card>

          <Card id="reminders-heading" title="Balance reminders" hint="When an order still has money to pay, the customer gets a gentle reminder by WhatsApp.">
            <p className="text-sm font-semibold text-ink">{overview.balance_reminders}</p>
            <p className="mt-1 text-sm text-ink-muted">They stop once the balance is paid.</p>
          </Card>

          <Card id="refunds-heading" title="Refunds">
            <p className="text-sm text-ink">
              <span className="font-semibold">Who can refund: </span>
              {overview.refund_who.join(", ")}
            </p>
            <p className="mt-1 text-sm text-ink-muted">
              Give a role the &ldquo;Refund orders&rdquo; permission in{" "}
              <Link href="/dashboard/roles" className="font-semibold text-primary underline">Team &amp; roles</Link>.
            </p>
            <div className="mt-3 space-y-2">
              <p className="text-sm font-semibold text-ink">What the customer is told</p>
              <div className="rounded-xl bg-surface-subtle px-4 py-3">
                <p className="text-sm font-semibold text-ink">Refund by Razorpay</p>
                <p className="mt-0.5 text-sm text-ink-secondary">{overview.refund_message.razorpay}</p>
              </div>
              <div className="rounded-xl bg-surface-subtle px-4 py-3">
                <p className="text-sm font-semibold text-ink">Refund by cash, UPI or bank</p>
                <p className="mt-0.5 text-sm text-ink-secondary">{overview.refund_message.other}</p>
              </div>
            </div>
          </Card>

          <Card id="ways-heading" title="Ways to pay">
            <ul className="divide-y divide-border/70">
              {overview.ways_to_pay.map((w) => (
                <li key={w.key} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 py-2.5 first:pt-0 last:pb-0">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-ink">{WAY_TITLES[w.key] ?? w.key}</p>
                    <p className="text-sm text-ink-muted">{w.detail}</p>
                  </div>
                  <StatusDot ok={w.ok} okLabel={w.key === "gst" ? "GST bills" : "Ready"} badLabel={w.key === "gst" ? "Simple bills" : "Not set up"} unknownLabel="Can't check" />
                </li>
              ))}
            </ul>
          </Card>

          <ComingLater items={COMING_LATER} />
        </>
      ) : null}
    </div>
  );
}

const WAY_TITLES: Record<string, string> = {
  razorpay: "Pay link (Razorpay)",
  in_shop: "In the shop",
  gst: "GST bills",
};
