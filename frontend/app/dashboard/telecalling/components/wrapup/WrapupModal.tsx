"use client";
import { useEffect, useState } from "react";
import { Check, PhoneCall, PhoneMissed, PhoneOff, Power, RefreshCw } from "lucide-react";
import type { CallConnect, CatalogItem, WrapupContext } from "@/lib/api";
import {
  CONNECT_OPTIONS, DISQUALIFIED_REASONS, LANGUAGE_OPTIONS, NOT_INTERESTED_REASONS, RESULT_OPTIONS, TONE_CHIP, resultOption,
} from "@/lib/call-wrapup";
import { TickMark } from "@/components/ui/controls";
import { draftError, selectConnect, selectOutcome, type WrapupDraft } from "../../lib/wrapup-draft";
import QuickTimePicker from "./QuickTimePicker";
import SalePicker from "./SalePicker";
import BookVisit from "./BookVisit";

const CONNECT_ICON: Record<CallConnect, typeof PhoneCall> = {
  connected: PhoneCall, not_picked: PhoneMissed, busy: PhoneOff, switched_off: Power,
};
const LABEL = "font-label text-[11px] text-[#94a3b8] uppercase tracking-wider font-extrabold block mb-2";

function chip(selected: boolean): string {
  return `px-3 h-9 sm:h-auto sm:py-1.5 text-xs sm:text-[11px] rounded-full border font-label font-bold transition-all ${
    selected ? "bg-primary border-primary text-white shadow-sm" : "bg-[#f8fafc] border-[#e2e8f0] text-[#334155] hover:border-primary-muted hover:text-primary"
  }`;
}

export interface SimTiming {
  startedAt: string;
  endedAt: string;
  setStartedAt: (value: string) => void;
  setEndedAt: (value: string) => void;
}

export interface WrapupModalProps {
  callee: string;
  provider: "telecmi" | "sim_basic";
  context: WrapupContext | null;
  draft: WrapupDraft;
  onChange: (draft: WrapupDraft) => void;
  saving: boolean;
  onSubmit: () => void;
  catalogItems: CatalogItem[];
  simTiming: SimTiming | null;
  /** Fixed "now" for previews/tests — omit for live use, where the clock ticks every 30s so a
   * suggestion that's gone stale (e.g. "in 1 hour" after an hour) can't leave Save enabled. */
  now?: Date;
}

const CLOCK_INTERVAL_MS = 30_000;

function simSeconds(t: SimTiming): number | null {
  if (!t.startedAt || !t.endedAt) return null;
  const s = Math.round((new Date(t.endedAt).getTime() - new Date(t.startedAt).getTime()) / 1000);
  return Number.isFinite(s) ? Math.max(0, s) : null;
}

/** The mandatory two-tap wrap-up, identical for SIM and cloud calls. */
export default function WrapupModal({
  callee, provider, context, draft, onChange, saving, onSubmit, catalogItems, simTiming, now,
}: WrapupModalProps) {
  const [editTiming, setEditTiming] = useState(false);
  const [clock, setClock] = useState(() => now ?? new Date());
  useEffect(() => {
    if (now) return; // a fixed value was supplied (tests/previews): never tick
    const id = setInterval(() => setClock(new Date()), CLOCK_INTERVAL_MS);
    return () => clearInterval(id);
  }, [now]);
  const neverConnected = !!context?.never_connected;
  const problem = draftError(draft, clock, neverConnected);
  const option = draft.outcome ? resultOption(draft.outcome) : null;
  const noConnect = draft.manualStatus !== null && draft.manualStatus !== "connected";
  const streak = (context?.failed_before ?? 0) + 1;
  const suggested = draft.manualStatus && draft.manualStatus !== "connected" ? context?.retry_suggestions[draft.manualStatus] ?? null : null;
  const seconds = simTiming ? simSeconds(simTiming) : null;
  // Any time the telecaller sets themselves — quick chip, custom pick, or clearing an optional
  // follow-up — stops tracking the server's suggestion (W7); only selectConnect/applyContext may
  // set retrySuggested back to true.
  const setTime = (iso: string | null) => onChange({ ...draft, nextActionAt: iso, retrySuggested: false });

  return (
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-[#0A1528]/80 p-0 backdrop-blur-sm sm:items-center sm:p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="wrapup-title"
        className="flex max-h-[88dvh] w-full max-w-lg flex-col rounded-t-3xl border border-[#e2e8f0] bg-white shadow-2xl animate-in fade-in slide-in-from-bottom-4 sm:max-h-[92dvh] sm:rounded-3xl sm:zoom-in-95"
      >
        <div className="border-b border-[#f1f5f9] px-5 pb-4 pt-5 sm:px-7 sm:pt-6">
          <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 font-label text-[10px] font-black uppercase tracking-wider text-amber-700">
            {provider === "sim_basic" ? "SIM call" : "Cloud call"}
          </span>
          <h3 id="wrapup-title" className="mt-2 font-display text-xl font-bold text-[#0A1528]">Wrap up the call</h3>
          <p className="mt-0.5 font-body text-xs text-[#94a3b8]">
            with <span className="font-semibold text-[#1e293b]">{callee}</span>
          </p>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5 sm:px-7">
          {simTiming && (
            <section className="rounded-2xl border border-primary-muted bg-primary-light/40 p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="font-label text-[11px] font-black tracking-wider text-primary">
                    Call lasted {seconds !== null ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : "0m"}
                  </p>
                  <p className="mt-0.5 font-body text-[11px] text-[#475569]">Anril can&apos;t read SIM call time, so check it before saving.</p>
                </div>
                <button
                  type="button"
                  aria-expanded={editTiming}
                  onClick={() => setEditTiming((v) => !v)}
                  className="inline-flex min-h-8 shrink-0 items-center px-2 font-label text-xs font-bold text-primary underline"
                >
                  {editTiming ? "Done" : "Edit"}
                </button>
              </div>
              {editTiming && (
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {([["Started", simTiming.startedAt, simTiming.setStartedAt], ["Ended", simTiming.endedAt, simTiming.setEndedAt]] as const).map(([label, value, set]) => (
                  <label key={label} className="block">
                    <span className="mb-1 block font-label text-[11px] font-black uppercase tracking-wider text-[#94a3b8]">{label}</span>
                    <input
                      type="datetime-local"
                      value={value}
                      onChange={(e) => set(e.target.value)}
                      className="w-full rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 font-body text-xs focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                  </label>
                ))}
              </div>
              )}
            </section>
          )}

          <section>
            <p className={LABEL}>1 · Did the call connect?</p>
            <div className="grid grid-cols-2 gap-2">
              {CONNECT_OPTIONS.map((o) => {
                const Icon = CONNECT_ICON[o.value];
                const selected = draft.manualStatus === o.value;
                const blocked = o.value === "connected" && neverConnected;
                return (
                  <button
                    key={o.value}
                    type="button"
                    disabled={blocked}
                    title={blocked ? "The call record shows nobody answered" : undefined}
                    onClick={() => onChange(selectConnect(draft, o.value, context))}
                    className={`flex items-center gap-2.5 rounded-2xl border px-3 py-2.5 text-left transition-all disabled:cursor-not-allowed disabled:opacity-40 ${
                      selected ? "border-primary bg-primary text-white shadow-md" : "border-[#e2e8f0] bg-[#f8fafc] text-[#1e293b] hover:bg-[#f1f5f9]"
                    }`}
                  >
                    <Icon size={15} className="shrink-0" />
                    <span className="min-w-0">
                      <span className="block font-label text-xs font-bold">{o.label}</span>
                      <span className={`block font-label text-[10px] ${selected ? "text-white/75" : "text-[#94a3b8]"}`}>{o.hint}</span>
                    </span>
                  </button>
                );
              })}
            </div>
            {provider === "telecmi" && context?.connect_prefill && draft.manualStatus === context.connect_prefill && (
              <p className="mt-2 font-label text-[10px] text-[#94a3b8]">Filled in from the call record. Change it if it&apos;s wrong.</p>
            )}
          </section>

          {noConnect && (
            <section className="rounded-2xl border border-amber-200 bg-amber-50/60 p-4">
              <p className="mb-1 font-label text-[10px] font-extrabold uppercase tracking-wider text-amber-700">Try again</p>
              {streak >= 3 && (
                <p className="mb-2 font-body text-[11px] text-amber-800">{streak} missed calls in a row, so the next try is tomorrow morning.</p>
              )}
              <QuickTimePicker value={draft.nextActionAt} onChange={setTime} now={clock} suggested={suggested} />
              <p className="mt-2 font-label text-[10px] text-amber-700/80">Saving adds this to Scheduled Calls.</p>
            </section>
          )}

          {draft.manualStatus === "connected" && (
            <section>
              <p className={LABEL}>2 · What happened?</p>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {RESULT_OPTIONS.map((o) => {
                  const selected = draft.outcome === o.value;
                  return (
                    <button
                      key={o.value}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => onChange(selectOutcome(draft, o.value))}
                      className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-left font-label text-xs font-bold transition-all ${
                        selected ? `${TONE_CHIP[o.tone]} ring-2 ring-primary/30 ring-offset-1` : "border-[#e2e8f0] bg-white text-[#1e293b] hover:bg-[#f8fafc]"
                      }`}
                    >
                      <span aria-hidden className="text-base leading-none">{o.emoji}</span>
                      <span>{o.label}</span>
                    </button>
                  );
                })}
              </div>
            </section>
          )}

          {draft.outcome === "interested_booked" && <BookVisit draft={draft} onChange={onChange} />}

          {option?.time && !draft.booking && (
            <section>
              <p className={LABEL}>{option.timeLabel}{option.time === "required" ? " *" : ""}</p>
              <QuickTimePicker value={draft.nextActionAt} onChange={setTime} now={clock} optional={option.time === "optional"} />
            </section>
          )}

          {(draft.outcome === "not_interested" || draft.outcome === "disqualified") && (
            <section>
              <p className={LABEL}>Why? *</p>
              <div className="flex flex-wrap gap-1.5">
                {(draft.outcome === "not_interested" ? NOT_INTERESTED_REASONS : DISQUALIFIED_REASONS).map((r) => (
                  <button key={r.value} type="button" onClick={() => onChange({ ...draft, reason: r.value })} className={chip(draft.reason === r.value)}>
                    {r.label}
                  </button>
                ))}
              </div>
            </section>
          )}

          {draft.outcome === "language_barrier" && (
            <section>
              <p className={LABEL}>Customer&apos;s language *</p>
              <div className="flex flex-wrap gap-1.5">
                {LANGUAGE_OPTIONS.map((l) => (
                  <button key={l.value} type="button" onClick={() => onChange({ ...draft, preferredLanguage: l.value })} className={chip(draft.preferredLanguage === l.value)}>
                    {l.label}
                  </button>
                ))}
              </div>
              <p className="mt-2 font-label text-[10px] text-[#94a3b8]">Your admin gets an alert to hand this lead to someone who speaks it.</p>
            </section>
          )}

          {draft.outcome === "converted" && (
            <section>
              <p className={LABEL}>What was sold? *</p>
              <SalePicker
                mode={draft.saleMode}
                products={draft.products}
                amountRupees={draft.amountRupees}
                catalogItems={catalogItems}
                onChange={(patch) => onChange({ ...draft, ...patch })}
              />
            </section>
          )}

          {draft.outcome === "do_not_call" && (
            <button
              type="button"
              role="checkbox"
              aria-checked={draft.stopMessages}
              onClick={() => onChange({ ...draft, stopMessages: !draft.stopMessages })}
              className="flex w-full items-center gap-2.5 rounded-2xl border border-red-200 bg-red-50/60 px-3 py-2.5 text-left font-body text-xs font-semibold text-red-800"
            >
              <TickMark checked={draft.stopMessages} size="sm" />
              Also stop WhatsApp/SMS
            </button>
          )}

          <section>
            <label htmlFor="wrapup-notes" className={LABEL}>Notes{option?.notes ? " *" : ""}</label>
            <textarea
              id="wrapup-notes"
              value={draft.notes}
              onChange={(e) => onChange({ ...draft, notes: e.target.value })}
              placeholder="What did the customer say? Need, budget, next step…"
              rows={3}
              maxLength={2000}
              className="w-full resize-none rounded-2xl border border-[#e2e8f0] bg-[#f8fafc] px-4 py-3 font-body text-base sm:text-xs shadow-inner focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </section>
        </div>

        <div className="space-y-2 border-t border-[#f1f5f9] px-5 py-4 pb-[calc(1rem+env(safe-area-inset-bottom,0px))] sm:px-7 sm:pb-5">
          {problem && draft.manualStatus && <p className="text-center font-label text-[11px] text-[#94a3b8]">{problem}</p>}
          <button
            type="button"
            onClick={onSubmit}
            disabled={saving || !!problem}
            className="flex w-full items-center justify-center gap-1.5 rounded-2xl bg-primary h-12 sm:h-auto sm:py-3 font-label text-sm sm:text-xs font-black text-white shadow-md transition-all hover:scale-[1.01] hover:bg-primary-dark active:scale-[0.99] disabled:opacity-50"
          >
            {saving ? <RefreshCw size={14} className="animate-spin" /> : <Check size={14} />}
            <span>Save wrap-up</span>
          </button>
        </div>
      </div>
    </div>
  );
}
