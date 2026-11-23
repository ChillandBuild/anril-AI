"use client";

import { Loader2 } from "lucide-react";
import { SwitchPill } from "@/components/ui/controls";
import { Card } from "@/app/dashboard/settings/payments/MyBusinessUi";
import type { CallRules } from "@/lib/callRulesApi";
import { clockWords, wholeNumber } from "./callRulesLogic";

const INPUT = "min-h-11 rounded-xl border border-border bg-white px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:bg-surface-subtle disabled:text-ink-muted";

function Row({ label, hint, on, onChange, disabled, children }: {
  label: string; hint: string; on: boolean; onChange: (v: boolean) => void; disabled: boolean; children?: React.ReactNode;
}) {
  return (
    <div className="border-b border-border/60 py-3 last:border-b-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-ink">{label}</p>
          <p className="mt-0.5 text-sm text-ink-muted">{hint}</p>
        </div>
        <SwitchPill on={on} onChange={onChange} disabled={disabled} aria-label={label} />
      </div>
      {on && children ? <div className="mt-3">{children}</div> : null}
    </div>
  );
}

/** The business-wide rules. Everything here is off or relaxed for the owner and managers: it holds telecallers only. */
export function RulesCard({ draft, onChange, canEdit, dirty, saving, problem, onSave }: {
  draft: CallRules; onChange: (patch: Partial<CallRules>) => void; canEdit: boolean;
  dirty: boolean; saving: boolean; problem: string | null; onSave: () => void;
}) {
  const locked = !canEdit || saving;
  return (
    <Card id="rules-heading" title="Rules for telecallers" hint="These hold your telecallers. You and your managers can always dial.">
      <Row
        label="Calling hours"
        hint={`Telecallers can only dial between ${clockWords(draft.calling_start)} and ${clockWords(draft.calling_end)} (India time).`}
        on={draft.calling_hours_on} onChange={(v) => onChange({ calling_hours_on: v })} disabled={locked}
      >
        <div className="flex flex-wrap items-center gap-2 text-sm text-ink">
          <label className="flex items-center gap-2">From
            <input type="time" value={draft.calling_start} disabled={locked} aria-label="Calling starts at"
              onChange={(e) => onChange({ calling_start: e.target.value })} className={INPUT} />
          </label>
          <label className="flex items-center gap-2">to
            <input type="time" value={draft.calling_end} disabled={locked} aria-label="Calling ends at"
              onChange={(e) => onChange({ calling_end: e.target.value })} className={INPUT} />
          </label>
        </div>
      </Row>

      <Row
        label="Daily call limit"
        hint="Off by default. When on, each telecaller can make this many calls a day."
        on={draft.daily_limit_on} onChange={(v) => onChange({ daily_limit_on: v })} disabled={locked}
      >
        <label className="flex items-center gap-2 text-sm text-ink">Calls per telecaller per day
          <input inputMode="numeric" value={String(draft.daily_limit)} disabled={locked} aria-label="Calls per telecaller per day"
            onChange={(e) => onChange({ daily_limit: wholeNumber(e.target.value) ?? 0 })} className={`${INPUT} w-24`} />
        </label>
      </Row>

      <Row
        label="Long break alert"
        hint="You get a bell when a telecaller stays on break for too long. Once per break."
        on={draft.break_limit_minutes > 0} onChange={(v) => onChange({ break_limit_minutes: v ? 30 : 0 })} disabled={locked}
      >
        <label className="flex items-center gap-2 text-sm text-ink">Tell me after
          <input inputMode="numeric" value={String(draft.break_limit_minutes)} disabled={locked} aria-label="Minutes on break before the alert"
            onChange={(e) => onChange({ break_limit_minutes: wholeNumber(e.target.value) ?? 0 })} className={`${INPUT} w-24`} />
          minutes
        </label>
      </Row>

      <Row
        label="Hide phone numbers from telecallers"
        hint="Off by default. When on, telecallers who call through the cloud see 98•••••210 instead of the full number, and calling still works. People calling from their own SIM phone still see it, because the phone needs the number to dial."
        on={draft.hide_numbers_for_callers} onChange={(v) => onChange({ hide_numbers_for_callers: v })} disabled={locked}
      />

      {problem ? <p role="alert" className="mt-3 text-sm font-semibold text-danger">{problem}</p> : null}
      {canEdit ? (
        <button type="button" onClick={onSave} disabled={!dirty || !!problem || saving}
          className="mt-4 inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-white disabled:opacity-50">
          {saving ? <Loader2 size={16} className="animate-spin" aria-hidden /> : null}
          Save rules
        </button>
      ) : (
        <p className="mt-3 text-sm text-ink-muted">Only people who can change settings can edit these.</p>
      )}
    </Card>
  );
}
