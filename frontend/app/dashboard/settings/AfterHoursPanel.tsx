"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Moon } from "lucide-react";
import { toast } from "sonner";
import { afterHoursProblem, openHoursApi, replySettingsApi, type AfterHours, type OpenHours } from "@/lib/replySettingsApi";
import {
  SaveButton,
  SaveStatus,
  SectionFooter,
  SectionLoadGate,
  SettingsSection,
  SummaryHint,
  type SectionLoadState,
} from "./SettingsSection";
import { SwitchPill } from "@/components/ui/controls";

const DEFAULT: AfterHours = { enabled: false, open: "09:00", close: "21:00", message: "", max_chars: 300 };
const FIELD =
  "rounded-xl border border-border-subtle bg-white px-3 py-2 font-body text-sm text-ink focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-60";

/** v9.2 #157: what the AI tells a customer who is waiting for a person when your team is out (India time). */
export function AfterHoursPanel({ canManage = true }: { canManage?: boolean }) {
  const [saved, setSaved] = useState<AfterHours>(DEFAULT);
  const [draft, setDraft] = useState<AfterHours>(DEFAULT);
  const [loadState, setLoadState] = useState<SectionLoadState>("loading");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);
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
    draft.enabled !== saved.enabled || draft.open !== saved.open || draft.close !== saved.close || draft.message.trim() !== saved.message;
  const problem = afterHoursProblem(draft, draft.max_chars);

  async function save() {
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    setSaveState("saving");
    try {
      const r = await replySettingsApi.saveAfterHours({ enabled: draft.enabled, open: draft.open, close: draft.close, message: draft.message });
      setSaved(r);
      setDraft(r);
      setSaveState("saved");
      toast.success("After-hours message saved");
      setTimeout(() => setSaveState("idle"), 2000);
    } catch (err) {
      setSaveState("idle");
      setError(err instanceof Error ? err.message : "Could not save. Please try again.");
    }
  }

  return (
    <SettingsSection
      id="after-hours"
      icon={Moon}
      accent="violet"
      title="After-hours message"
      description="What the AI tells a customer who is waiting for a person when your team is out."
      status={loadState === "ready" ? { label: draft.enabled ? "On" : "Off", tone: draft.enabled ? "on" : "off" } : undefined}
      dirty={dirty}
      headerAction={
        loadState === "ready" ? (
          <SwitchPill on={draft.enabled} size="sm" disabled={!canManage} aria-label="After-hours message on or off" onChange={(v) => setDraft({ ...draft, enabled: v })} />
        ) : undefined
      }
      summary={
        loadState !== "ready" ? undefined : draft.enabled ? (
          <SummaryHint>{hours?.set ? `Out whenever the shop is closed (${hours.summary}).` : `Team in ${saved.open} to ${saved.close} (India time).`}</SummaryHint>
        ) : (
          <SummaryHint>Off. The AI does not mention your hours.</SummaryHint>
        )
      }
    >
      <SectionLoadGate state={loadState} onRetry={load}>
        <div className="space-y-4">
          {hours?.set ? (
            <p className="rounded-xl bg-surface-low px-3 py-2 font-body text-sm text-ink">
              The team counts as out whenever the shop is closed: <span className="font-semibold">{hours.summary}</span>.{" "}
              <Link href="/dashboard/settings/business-hours" className="font-semibold text-primary underline">Change open hours</Link>
            </p>
          ) : (
          <div className="flex flex-wrap items-center gap-3">
            <label className="font-label text-sm font-semibold text-ink" htmlFor="ah-open">Team is in from</label>
            <input id="ah-open" type="time" value={draft.open} disabled={!canManage} onChange={(e) => setDraft({ ...draft, open: e.target.value })} className={FIELD} />
            <label className="font-label text-sm font-semibold text-ink" htmlFor="ah-close">until</label>
            <input id="ah-close" type="time" value={draft.close} disabled={!canManage} onChange={(e) => setDraft({ ...draft, close: e.target.value })} className={FIELD} />
            <span className="font-body text-xs text-ink-muted">
              India time. Or <Link href="/dashboard/settings/business-hours" className="font-semibold text-primary underline">set your open hours</Link> and this follows them.
            </span>
          </div>
          )}
          <div>
            <label className="mb-1 block font-label text-sm font-semibold text-ink" htmlFor="ah-message">Message</label>
            <textarea
              id="ah-message"
              rows={3}
              value={draft.message}
              maxLength={draft.max_chars}
              disabled={!canManage}
              onChange={(e) => setDraft({ ...draft, message: e.target.value })}
              placeholder="We are closed now. Our team will reply when we open at 9 AM."
              className={`${FIELD} w-full`}
            />
            <p className="mt-1 font-body text-xs text-ink-muted">
              {draft.message.length}/{draft.max_chars}. The AI uses your words, in the customer&apos;s language. It never promises a call time.
            </p>
          </div>
          {error && <p role="alert" className="font-body text-sm text-danger">{error}</p>}
        </div>
        <SectionFooter status={<SaveStatus state={saveState} dirty={dirty} idleLabel={draft.enabled ? "After-hours message is live" : "After-hours message is off"} />}>
          <SaveButton state={saveState} dirty={dirty} disabled={!canManage} onClick={save} />
        </SectionFooter>
      </SectionLoadGate>
    </SettingsSection>
  );
}
