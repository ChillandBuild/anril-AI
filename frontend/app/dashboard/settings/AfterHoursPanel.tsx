"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { afterHoursProblem, openHoursApi, replySettingsApi, type AfterHours, type OpenHours } from "@/lib/replySettingsApi";
import type { SectionLoadState } from "./SettingsSection";

const DEFAULT: AfterHours = { enabled: false, open: "09:00", close: "21:00", message: "", max_chars: 300 };
const FIELD =
  "rounded-xl border border-border-subtle bg-white px-3 py-2 font-body text-sm text-ink focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-60";

export type AfterHoursState = ReturnType<typeof useAfterHours>;

/** v9.2 #157: what the AI tells a customer waiting for a person when the team is out (India time). */
export function useAfterHours() {
  const [saved, setSaved] = useState<AfterHours>(DEFAULT);
  const [draft, setDraft] = useState<AfterHours>(DEFAULT);
  const [loadState, setLoadState] = useState<SectionLoadState>("loading");
  // v9.2 #59: when the team is "out" comes from the shop's open hours (one place), not times kept here.
  const [hours, setHours] = useState<OpenHours | null>(null);

  const load = useCallback(async () => {
    setLoadState("loading");
    try {
      const [r, h] = await Promise.all([replySettingsApi.afterHours(), openHoursApi.get().catch(() => null)]);
      setSaved(r);
      setDraft(r);
      setHours(h);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }, []);
  useEffect(() => void load(), [load]);

  const dirty =
    loadState === "ready" &&
    (draft.enabled !== saved.enabled || draft.open !== saved.open || draft.close !== saved.close || draft.message.trim() !== saved.message);
  const problem = afterHoursProblem(draft, draft.max_chars);

  /** Returns an error message, or null when saved. */
  const save = useCallback(async (): Promise<string | null> => {
    if (problem) return problem;
    try {
      const r = await replySettingsApi.saveAfterHours({ enabled: draft.enabled, open: draft.open, close: draft.close, message: draft.message });
      setSaved(r);
      setDraft(r);
      return null;
    } catch (err) {
      return err instanceof Error ? err.message : "After-hours message did not save";
    }
  }, [draft, problem]);

  return { draft, setDraft, hours, loadState, load, dirty, problem, save };
}

export function AfterHoursFields({ state, disabled }: { state: AfterHoursState; disabled: boolean }) {
  const { draft, setDraft, hours } = state;
  return (
    <div className="space-y-3">
      {hours?.set ? (
        <p className="rounded-xl bg-surface-low px-3 py-2 font-body text-sm text-ink">
          Closed whenever the shop is closed: <span className="font-semibold">{hours.summary}</span>.{" "}
          <Link href="/dashboard/settings/business-hours" className="font-semibold text-primary underline">Change open hours</Link>
        </p>
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <label className="font-label text-sm font-semibold text-ink" htmlFor="ah-open">Team is in from</label>
            <input id="ah-open" type="time" value={draft.open} disabled={disabled} onChange={(e) => setDraft({ ...draft, open: e.target.value })} className={FIELD} />
            <label className="font-label text-sm font-semibold text-ink" htmlFor="ah-close">until</label>
            <input id="ah-close" type="time" value={draft.close} disabled={disabled} onChange={(e) => setDraft({ ...draft, close: e.target.value })} className={FIELD} />
          </div>
          <p className="font-body text-xs text-ink-muted">
            India time. Or <Link href="/dashboard/settings/business-hours" className="font-semibold text-primary underline">set your open hours</Link> and this follows them.
          </p>
        </div>
      )}
      <div>
        <label className="mb-1 block font-label text-sm font-semibold text-ink" htmlFor="ah-message">Message</label>
        <textarea
          id="ah-message"
          rows={4}
          value={draft.message}
          maxLength={draft.max_chars}
          disabled={disabled}
          onChange={(e) => setDraft({ ...draft, message: e.target.value })}
          placeholder="We are closed now. Our team will reply when we open at 9 AM."
          className={`${FIELD} w-full`}
        />
        <p className="mt-1 font-body text-xs text-ink-muted">
          {draft.message.length}/{draft.max_chars}. The AI uses your words, in the customer&apos;s language. It never promises a call time.
        </p>
      </div>
    </div>
  );
}
