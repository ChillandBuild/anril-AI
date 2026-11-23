"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/app/dashboard/settings/payments/MyBusinessUi";
import { callRulesApi, type CallingMode, type RulesPeople, type RulesPerson } from "@/lib/callRulesApi";
import { MODE_CHOICES, leaveLine, leaveResultLine, modeWords } from "./callRulesLogic";

const INPUT = "min-h-11 rounded-xl border border-border bg-white px-3 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:bg-surface-subtle";
const BTN = "inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-white px-3 text-sm font-semibold text-ink disabled:opacity-50";

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/**
 * SIM or cloud per person is hidden until the telecaller phone app (v9.2 #22) lands: today only the Call
 * button follows a per-person choice, the other calling screens read the business setting (Prem, 2026-11-23).
 */
const PER_PERSON_MODE = false;

function PersonRow({ p, canMode, canLeave, onChanged }: {
  p: RulesPerson; canMode: boolean; canLeave: boolean; onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState(today());
  const [to, setTo] = useState(today());
  const [reason, setReason] = useState("");
  const name = p.name || "Telecaller";
  const line = leaveLine(p);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "That did not save. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-ink">{name}</p>
          <p className="text-sm text-ink-muted">Calls with: {modeWords(p.effective_mode)}</p>
        </div>
        {PER_PERSON_MODE ? (
          <select aria-label={`How ${name} calls`} value={p.calling_mode} disabled={!canMode || busy} className={INPUT}
            onChange={(e) => void run(async () => {
              await callRulesApi.setMode(p.id, e.target.value as CallingMode);
              toast.success("Saved");
              onChanged();
            })}>
            {MODE_CHOICES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        ) : null}
      </div>

      {line ? <p className="mt-1 text-sm font-semibold text-ink">{line}</p> : null}

      {canLeave ? (
        <div className="mt-2">
          {line ? (
            <button type="button" className={BTN} disabled={busy}
              onClick={() => void run(async () => { await callRulesApi.endLeave(p.id); toast.success("Leave ended"); onChanged(); })}>
              End leave
            </button>
          ) : open ? (
            <div className="space-y-2 rounded-xl bg-surface-subtle/60 p-3">
              <div className="flex flex-wrap items-center gap-2 text-sm text-ink">
                <label className="flex items-center gap-2">First day
                  <input type="date" value={from} min={today()} onChange={(e) => setFrom(e.target.value)} className={INPUT} />
                </label>
                <label className="flex items-center gap-2">Last day
                  <input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} className={INPUT} />
                </label>
              </div>
              <input value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} placeholder="Reason (optional)"
                aria-label="Reason for leave" className={`${INPUT} w-full`} />
              <p className="text-sm text-ink-muted">{name}&apos;s open leads are given to the other telecallers, one by one.</p>
              <div className="flex gap-2">
                <button type="button" className={BTN} disabled={busy || !from || !to || to < from}
                  onClick={() => void run(async () => {
                    const r = await callRulesApi.startLeave(p.id, { from, to, reason: reason.trim() || undefined });
                    toast.success(leaveResultLine(name, r));
                    setOpen(false);
                    onChanged();
                  })}>
                  {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : null}Start leave
                </button>
                <button type="button" className={BTN} onClick={() => setOpen(false)}>Cancel</button>
              </div>
            </div>
          ) : (
            <button type="button" className={BTN} onClick={() => setOpen(true)}>Put on leave</button>
          )}
        </div>
      ) : null}
    </li>
  );
}

/** Per person: SIM or office number (hidden for now, see PER_PERSON_MODE), and leave. */
export function PeopleCard({ data, canMode, canLeave, onChanged }: {
  data: RulesPeople; canMode: boolean; canLeave: boolean; onChanged: () => void;
}) {
  return (
    <Card id="people-heading" title="Telecallers" hint={PER_PERSON_MODE
      ? `By default the business calls with: ${modeWords(data.business_mode)}. Each person can use the other way.`
      : `Everyone calls with: ${modeWords(data.business_mode)} (change it in Settings, Calling). Picking SIM or cloud per person comes later, with the phone app.`}>
      {data.callers.length === 0 ? (
        <p className="text-sm text-ink-muted">No telecallers yet. Add them in Settings, Team &amp; roles.</p>
      ) : (
        <ul className="divide-y divide-border/60">
          {data.callers.map((p) => <PersonRow key={p.id} p={p} canMode={canMode} canLeave={canLeave} onChanged={onChanged} />)}
        </ul>
      )}
    </Card>
  );
}
