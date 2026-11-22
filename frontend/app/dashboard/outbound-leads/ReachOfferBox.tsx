"use client";
import { useEffect, useRef } from "react";
import { addDays, todayIst } from "../teach/teachLogic";

export interface ReachOfferDraft {
  on: boolean;
  title: string;
  endsOn: string;
}

export const NO_REACH_OFFER: ReachOfferDraft = { on: false, title: "", endsOn: "" };

/** What goes in the send request: nothing unless the box is ticked. */
export function reachOfferPayload(d: ReachOfferDraft): { title: string; ends_on: string } | undefined {
  return d.on ? { title: d.title.trim(), ends_on: d.endsOn } : undefined;
}

/** Null when fine, else the plain-words problem to show before sending. */
export function reachOfferProblem(d: ReachOfferDraft): string | null {
  if (!d.on) return null;
  if (!d.title.trim()) return "Name the offer, or untick \"This is an offer\".";
  if (!d.endsOn) return "Pick the date this offer ends, or untick \"This is an offer\".";
  return null;
}

/** Reach confirm step: optionally tell the AI agent this campaign is an offer, until a date. */
export function ReachOfferBox({ templateName, value, onChange }: {
  templateName: string;
  value: ReachOfferDraft;
  onChange: (next: ReachOfferDraft) => void;
}) {
  const titled = useRef(false);
  // Prefill the name from the template once, when the box is first ticked.
  useEffect(() => {
    if (value.on && !value.title && !titled.current) {
      titled.current = true;
      onChange({ ...value, title: templateName.replace(/_/g, " ") });
    }
  }, [value, templateName, onChange]);

  const today = todayIst();
  return (
    <div className="rounded-xl border border-surface-mid bg-white p-3 space-y-2">
      <label className="flex cursor-pointer items-start gap-2.5">
        <input type="checkbox" checked={value.on} onChange={(e) => onChange({ ...value, on: e.target.checked })}
          className="mt-0.5 h-4 w-4 shrink-0 accent-primary" />
        <span className="font-body text-sm text-on-surface">
          This is an offer. Tell the AI agent about it until the end date.
        </span>
      </label>
      {value.on && (
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="block font-label text-xs font-bold text-on-surface">
            Offer name
            <input value={value.title} maxLength={120} onChange={(e) => onChange({ ...value, title: e.target.value })}
              className="mt-1 w-full rounded-lg border border-surface-mid px-3 py-2 font-body text-sm font-normal focus:outline-none focus:ring-2 focus:ring-primary/20" />
          </label>
          <label className="block font-label text-xs font-bold text-on-surface">
            Ends on (required)
            <input type="date" value={value.endsOn} min={today} max={addDays(today, 365)}
              onChange={(e) => onChange({ ...value, endsOn: e.target.value })}
              className="mt-1 w-full rounded-lg border border-surface-mid px-3 py-2 font-body text-sm font-normal focus:outline-none focus:ring-2 focus:ring-primary/20" />
          </label>
          <p className="font-body text-xs text-on-surface-muted sm:col-span-2">
            Customers who reply about it get answers that match. After the end date the AI stops mentioning it. You can change it in Teach &amp; offers.
          </p>
        </div>
      )}
    </div>
  );
}
