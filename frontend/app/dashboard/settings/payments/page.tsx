"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Loader2, Wallet } from "lucide-react";
import { toast } from "sonner";
import { AiraLoader } from "@/components/AiraLoader";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { balanceRemindersApi, remindersLine } from "@/lib/balanceRemindersApi";
import { myBusinessApi, type AdvanceOptions, type AdvanceRuleBody, type PaymentsOverview } from "@/lib/myBusinessApi";
import { cn } from "@/lib/utils";
import {
  belowMinLine,
  cleanNumberText,
  customerPreview,
  draftError,
  draftFromRule,
  exampleLine,
  ruleFromDraft,
  sameRule,
  type AdvanceDraft,
  type AdvanceKind,
} from "./advanceText";
import { Card, ErrorBox, PageHeader, StatusDot } from "./MyBusinessUi";

const KINDS: { kind: AdvanceKind; label: string; hint: string }[] = [
  { kind: "none", label: "No advance", hint: "The customer pays when they collect." },
  { kind: "fixed", label: "Fixed amount ₹", hint: "The same amount on every order." },
  { kind: "percent", label: "Part of the bill %", hint: "A share of each order's total." },
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
  // null = could not read it (no Orders access, or the server said no): the card shows the plain text only.
  const [remindersOn, setRemindersOn] = useState<boolean | null>(null);
  const [remindersSaving, setRemindersSaving] = useState(false);
  const [options, setOptions] = useState<AdvanceOptions | null>(null);
  const [optionSaving, setOptionSaving] = useState<keyof AdvanceOptions | null>(null);

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
      balanceRemindersApi.get().then((r) => setRemindersOn(r.on), () => setRemindersOn(null));
      myBusinessApi.advanceOptions().then(setOptions, () => setOptions(null));
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

  async function toggleOption(key: keyof AdvanceOptions) {
    if (!options) return;
    const next = { ...options, [key]: !options[key] };
    setOptionSaving(key);
    try {
      setOptions(await myBusinessApi.saveAdvanceOptions(next));
      toast.success("Saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save");
    } finally {
      setOptionSaving(null);
    }
  }

  async function toggleReminders() {
    if (remindersOn == null) return;
    const next = !remindersOn;
    setRemindersSaving(true);
    try {
      const r = await balanceRemindersApi.set(next);
      setRemindersOn(r.on);
      toast.success(r.on ? "Balance reminders are on" : "Balance reminders are off");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not change balance reminders");
    } finally {
      setRemindersSaving(false);
    }
  }

  return (
    <div className="w-full space-y-4 pb-10">
      <PageHeader icon={Wallet} title="Payments & advance" subtitle="How you ask for money on orders, and what happens around it." />

      {state === "loading" ? <AiraLoader inline className="min-h-[200px]" /> : null}
      {state === "error" ? <ErrorBox message="Couldn't load this page." onRetry={() => void load()} /> : null}

      {state === "ready" && overview ? (
        <>
          <Card id="advance-heading" title="Ask for an advance on orders?" hint="This is the advance a new order starts with.">
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

          {!ruleHidden && rule ? (
            <Card id="advance-options-heading" title="Who can change it, and what the customer sees">
              {options ? (
                <div className="divide-y divide-border/70">
                  <OptionSwitch id="opt-staff" on={options.staff_can_change} busy={optionSaving === "staff_can_change"} disabled={!isOwner}
                    onToggle={() => void toggleOption("staff_can_change")}
                    title="Staff can change the advance on one order"
                    text={options.staff_can_change ? "On New bill and New quote, staff can type a different advance. Each change is logged." : "Only you can change an order's advance. Staff get the rule above."} />
                  <OptionSwitch id="opt-payfull" on={options.ai_pay_full} busy={optionSaving === "ai_pay_full"} disabled={!isOwner}
                    onToggle={() => void toggleOption("ai_pay_full")}
                    title="AI agent lets a customer pay the full amount"
                    text={options.ai_pay_full ? "When a customer asks to pay it all now, the AI sends one link for the whole amount." : "The AI always sends the advance link first."} />
                </div>
              ) : (
                <p className="text-sm text-ink-muted">Couldn&apos;t load these switches.</p>
              )}
              {!isOwner ? <p className="mt-1 text-sm text-ink-muted">Only the owner can change these.</p> : null}
              <p className="mt-4 text-sm font-semibold text-ink">What the customer gets on WhatsApp</p>
              <div className="mt-2 max-w-sm rounded-2xl rounded-tl-sm bg-primary-50 px-3.5 py-2.5 shadow-sm ring-1 ring-primary-100">
                <p className="whitespace-pre-line font-body text-sm leading-5 text-[#0A1528]">{customerPreview(error ? rule : draftRule)}</p>
              </div>
              <p className="mt-1.5 text-xs text-ink-muted">An example order. The real message has their items and a working pay link.</p>
            </Card>
          ) : null}

          <Card id="reminders-heading" title="Balance reminders" hint="When an order still has money to pay, the customer gets a gentle reminder by WhatsApp.">
            {remindersOn == null ? (
              <p className="text-sm font-semibold text-ink">{overview.balance_reminders}</p>
            ) : (
              <div className="flex items-start justify-between gap-4">
                <p id="reminders-switch-label" className="text-sm font-semibold text-ink">{remindersLine(remindersOn)}</p>
                <button
                  type="button"
                  role="switch"
                  aria-checked={remindersOn}
                  aria-labelledby="reminders-switch-label"
                  disabled={!isOwner || remindersSaving}
                  onClick={() => void toggleReminders()}
                  className={cn(
                    "relative inline-flex h-11 w-14 shrink-0 items-center justify-center rounded-full focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-60",
                  )}
                >
                  <span aria-hidden className={cn("flex h-7 w-12 items-center rounded-full px-1 transition-colors", remindersOn ? "bg-primary" : "bg-slate-400")}>
                    <span className={cn("h-5 w-5 rounded-full bg-white shadow transition-transform", remindersOn ? "translate-x-5" : "translate-x-0")} />
                  </span>
                </button>
              </div>
            )}
            <p className="mt-1 text-sm text-ink-muted">
              They stop once the balance is paid.{!isOwner && remindersOn != null ? " Only the owner can change this." : ""}
            </p>
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

        </>
      ) : null}
    </div>
  );
}

function OptionSwitch({ id, on, busy, disabled, onToggle, title, text }: {
  id: string; on: boolean; busy: boolean; disabled: boolean; onToggle: () => void; title: string; text: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-3 first:pt-0">
      <div className="min-w-0">
        <p id={`${id}-label`} className="text-sm font-semibold text-ink">{title}</p>
        <p className="text-sm text-ink-muted">{text}</p>
      </div>
      <button type="button" role="switch" aria-checked={on} aria-labelledby={`${id}-label`} disabled={disabled || busy} onClick={onToggle}
        className="relative inline-flex h-11 w-14 shrink-0 items-center justify-center rounded-full focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-60">
        <span aria-hidden className={cn("flex h-7 w-12 items-center rounded-full px-1 transition-colors", on ? "bg-primary" : "bg-slate-400")}>
          <span className={cn("h-5 w-5 rounded-full bg-white shadow transition-transform", on ? "translate-x-5" : "translate-x-0")} />
        </span>
      </button>
    </div>
  );
}

const WAY_TITLES: Record<string, string> = {
  razorpay: "Pay link (Razorpay)",
  in_shop: "In the shop",
  gst: "GST bills",
};
