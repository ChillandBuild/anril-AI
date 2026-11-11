"use client";

import { useMemo, useState } from "react";
import { toast } from "sonner";
import {
  ArrowRight,
  Bell,
  Clock,
  Minus,
  Moon,
  Plus,
  Shield,
  Timer,
  X,
  Zap,
} from "lucide-react";
import { useSettingsForm } from "../SettingsFormContext";
import { parseSilenceDelays } from "../parseSilenceDelays";
import {
  Fact,
  Facts,
  SaveButton,
  SaveStatus,
  SummaryHint,
  SectionFooter,
  SettingsAccordion,
  SettingsSection,
  SwitchPill,
} from "../SettingsSection";

const SILENCE_NUDGE_KEYS = {
  enabled: "silence_nudge_enabled",
  delays: "silence_nudge_delays",
  cap: "silence_nudge_daily_cap",
  quietStart: "silence_nudge_quiet_start",
  quietEnd: "silence_nudge_quiet_end",
} as const;

const MAX_REMINDERS = 3;

const isValidMinutes = (s: string) => /^\d+$/.test(s) && +s >= 1 && +s <= 1440;

const SILENCE_NUDGE_DEFAULTS: Record<string, string> = {
  [SILENCE_NUDGE_KEYS.enabled]: "false",
  [SILENCE_NUDGE_KEYS.delays]: "5",
  [SILENCE_NUDGE_KEYS.cap]: "1",
  [SILENCE_NUDGE_KEYS.quietStart]: "21:00",
  [SILENCE_NUDGE_KEYS.quietEnd]: "09:00",
};

const DURATION_PRESETS = [
  { label: "5m", mins: "5" },
  { label: "15m", mins: "15" },
  { label: "30m", mins: "30" },
  { label: "1h", mins: "60" },
  { label: "2h", mins: "120" },
  { label: "24h", mins: "1440" },
];

const CAP_PRESETS = ["1", "2", "3", "5"];

function formatDuration(minsStr: string): string {
  const mins = parseInt(minsStr, 10);
  if (isNaN(mins) || mins <= 0) return "";
  if (mins < 60) return `${mins} min${mins > 1 ? "s" : ""}`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (m === 0) return `${h} hr${h > 1 ? "s" : ""}`;
  return `${h}h ${m}m`;
}

function formatTime12h(timeStr: string): string {
  if (!timeStr || !timeStr.includes(":")) return timeStr || "--:--";
  const [hStr, mStr] = timeStr.split(":");
  let h = parseInt(hStr, 10);
  const m = mStr || "00";
  if (isNaN(h)) return timeStr;
  const ampm = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  return `${h}:${m.padStart(2, "0")} ${ampm}`;
}

export default function FollowUpsSettingsPage() {
  const { settingFor, drafts, setDrafts, saveStates, canManageSettings, handleSave, saveValues } =
    useSettingsForm();

  const stored = (key: string) => {
    const s = settingFor(key)?.display_value;
    return !s || s === "Not set" ? SILENCE_NUDGE_DEFAULTS[key] : s;
  };
  const value = (key: string) => drafts[key] ?? stored(key);
  // On/off is the card's header switch, which saves right away, so it always
  // reads the saved value. The summary shows saved timing too.
  const enabled = stored(SILENCE_NUDGE_KEYS.enabled) === "true";
  const savedReminders = stored(SILENCE_NUDGE_KEYS.delays)
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
  const [toggling, setToggling] = useState(false);

  async function toggle(next: boolean) {
    setToggling(true);
    try {
      await saveValues({ [SILENCE_NUDGE_KEYS.enabled]: next ? "true" : "false" });
      toast.success(`Quiet-lead follow-ups turned ${next ? "on" : "off"}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : `Couldn't turn follow-ups ${next ? "on" : "off"}`);
    } finally {
      setToggling(false);
    }
  }
  const dirty = Object.values(SILENCE_NUDGE_KEYS).some(
    (key) => drafts[key] !== undefined && drafts[key] !== stored(key)
  );
  const delaysValid = parseSilenceDelays(value(SILENCE_NUDGE_KEYS.delays)) !== null;
  const capNum = parseInt(value(SILENCE_NUDGE_KEYS.cap), 10);
  const capValid =
    /^\d+$/.test(value(SILENCE_NUDGE_KEYS.cap)) && capNum >= 1 && capNum <= 10;

  // Stored as "5,60"; edited as one item per reminder. Blank entries stay on screen to block save.
  const rawDelays = value(SILENCE_NUDGE_KEYS.delays);
  const reminders = useMemo(
    () => rawDelays.split(",").map((s) => s.trim()),
    [rawDelays]
  );

  const setReminders = (next: string[]) =>
    setDrafts((d) => ({ ...d, [SILENCE_NUDGE_KEYS.delays]: next.join(",") }));

  const setReminder = (i: number, mins: string) =>
    setReminders(reminders.map((m, j) => (j === i ? mins : m)));

  const removeReminder = (i: number) =>
    setReminders(reminders.filter((_, j) => j !== i));

  const addReminder = () => {
    if (reminders.length >= MAX_REMINDERS) return;
    const defaultNext = reminders.length === 1 ? "60" : "1440";
    setReminders([...reminders, defaultNext]);
  };

  const setCap = (newCap: number) => {
    const clamped = Math.min(10, Math.max(1, newCap));
    setDrafts((d) => ({ ...d, [SILENCE_NUDGE_KEYS.cap]: String(clamped) }));
  };

  const quietStart = value(SILENCE_NUDGE_KEYS.quietStart);
  const quietEnd = value(SILENCE_NUDGE_KEYS.quietEnd);

  return (
    <SettingsAccordion>
      <SettingsSection
        id="silence-nudge"
        icon={Timer}
        accent="emerald"
        title="Auto follow-up when a lead goes quiet"
        description="After the AI answers, if the lead stays silent, send one short message about what they were discussing. Never sent while your team has taken over the chat, or during a paid consultation."
        status={{ label: enabled ? "On" : "Off", tone: enabled ? "on" : "off" }}
        dirty={dirty}
        headerAction={
          <SwitchPill
            on={enabled}
            size="sm"
            loading={toggling}
            disabled={!canManageSettings}
            aria-label="Quiet-lead follow-ups on or off"
            onChange={toggle}
          />
        }
        summary={
          enabled ? (
            <Facts>
              <Fact icon={Bell}>
                {savedReminders.length === 1 ? "1 follow-up" : `${savedReminders.length} follow-ups`}:{" "}
                {savedReminders.map(formatDuration).join(", ")}
              </Fact>
              <Fact icon={Shield}>Max {stored(SILENCE_NUDGE_KEYS.cap)} per lead a day</Fact>
              <Fact icon={Moon}>
                Quiet {formatTime12h(stored(SILENCE_NUDGE_KEYS.quietStart))}–{formatTime12h(stored(SILENCE_NUDGE_KEYS.quietEnd))} IST
              </Fact>
            </Facts>
          ) : (
            <SummaryHint>Off. No follow-up is sent when a lead goes quiet.</SummaryHint>
          )
        }
      >
        <div className="space-y-6">
          {!enabled && (
            <p className="rounded-xl border border-border-subtle bg-surface-subtle px-3 py-2 font-body text-xs text-ink-muted">
              Follow-ups are off. Turn them on with the switch above to set the timing.
            </p>
          )}

          {enabled && (
            <div className="space-y-6">
              {/* Cadence Timeline Section */}
              <div className="rounded-2xl border border-border bg-white p-4 sm:p-6 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2 pb-4 border-b border-border-subtle">
                  <div className="flex items-center gap-2.5">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700">
                      <Bell className="h-4 w-4" />
                    </div>
                    <div>
                      <h4 className="font-display text-sm font-bold text-ink">
                        Follow-up Sequence
                      </h4>
                      <p className="font-body text-xs text-ink-muted">
                        Configure delays between silent intervals before triggering a nudge.
                      </p>
                    </div>
                  </div>
                  <span className="font-label text-xs font-semibold text-ink-secondary bg-surface-subtle border border-border-subtle px-2.5 py-1 rounded-full">
                    {reminders.length} of {MAX_REMINDERS} steps configured
                  </span>
                </div>

                {/* 2-Column Split: Sequence on Left, Boundaries on Right */}
                <div className="mt-5 grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
                  {/* Left Column: Follow-up Timeline */}
                  <div className="lg:col-span-7 xl:col-span-7">
                    <div className="relative pl-2 sm:pl-3">
                      {/* Subtle vertical connection line */}
                      <div className="absolute left-[1.125rem] sm:left-[1.375rem] top-4 bottom-8 w-[2px] bg-gradient-to-b from-emerald-400 via-emerald-200 to-border" />

                      {/* Initial Trigger Node */}
                      <div className="relative mb-5 flex items-center gap-3">
                        <div className="z-10 flex h-6 w-6 items-center justify-center rounded-full bg-emerald-600 text-white shadow-sm ring-4 ring-white">
                          <Zap className="h-3 w-3" />
                        </div>
                        <span className="font-body text-xs font-medium text-ink-secondary">
                          Lead goes silent after AI reply
                        </span>
                      </div>

                      {/* Reminder Steps */}
                      <div className="space-y-3">
                        {reminders.map((mins, i) => {
                          const rowValid = isValidMinutes(mins);
                          const durationDisplay = rowValid ? formatDuration(mins) : "";

                          return (
                            <div key={i} className="relative flex items-start gap-3">
                              {/* Step Number Badge */}
                              <div className="z-10 mt-1.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-100 font-label text-xs font-bold text-emerald-800 shadow-sm ring-4 ring-white">
                                {i + 1}
                              </div>

                              {/* Step Card */}
                              <div
                                className={`flex-1 rounded-xl border p-3 sm:p-3.5 transition-all duration-200 ${
                                  rowValid
                                    ? "border-border-subtle bg-surface-subtle/40 hover:bg-surface-subtle/80 hover:border-border"
                                    : "border-red-300 bg-red-50/30"
                                }`}
                              >
                                <div className="flex items-center justify-between gap-2 mb-2">
                                  <div className="flex items-center gap-2">
                                    <span className="font-display text-xs font-bold text-ink">
                                      {i === 0
                                        ? "1st Follow-up"
                                        : i === 1
                                        ? "2nd Follow-up"
                                        : "3rd Follow-up"}
                                    </span>
                                    {durationDisplay && (
                                      <span className="font-label text-[10px] font-medium text-emerald-700 bg-emerald-50 border border-emerald-200/60 px-1.5 py-0.5 rounded">
                                        {durationDisplay}
                                      </span>
                                    )}
                                  </div>
                                  {reminders.length > 1 && canManageSettings && (
                                    <button
                                      type="button"
                                      onClick={() => removeReminder(i)}
                                      aria-label={`Remove reminder ${i + 1}`}
                                      className="rounded-lg p-0.5 text-ink-muted transition-colors hover:bg-white hover:text-red-600 hover:shadow-xs"
                                    >
                                      <X className="h-3.5 w-3.5" />
                                    </button>
                                  )}
                                </div>

                                {/* Single line: Delay input on left, presets on right */}
                                <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
                                  <div className="flex items-center gap-1.5">
                                    <span className="font-body text-xs text-ink-secondary">
                                      Wait
                                    </span>

                                    <div className="relative inline-flex items-center">
                                      <input
                                        type="text"
                                        inputMode="numeric"
                                        aria-label={`Minutes before reminder ${i + 1}`}
                                        disabled={!canManageSettings}
                                        value={mins}
                                        onChange={(e) =>
                                          setReminder(i, e.target.value.replace(/\D/g, ""))
                                        }
                                        className={`w-16 rounded-lg border bg-white px-2 py-1 pr-7 text-center font-display text-xs font-semibold text-ink shadow-xs transition focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-60 ${
                                          rowValid
                                            ? "border-border focus:border-primary"
                                            : "border-red-400 focus:ring-red-200"
                                        }`}
                                      />
                                      <span className="pointer-events-none absolute right-1.5 font-body text-[10px] text-ink-muted">
                                        min
                                      </span>
                                    </div>

                                    <span className="font-body text-xs text-ink-secondary whitespace-nowrap">
                                      after {i === 0 ? "the AI's reply" : `reminder ${i}`}
                                    </span>
                                  </div>

                                  {/* Presets on the same line */}
                                  {canManageSettings && (
                                    <div className="flex items-center gap-1">
                                      {DURATION_PRESETS.map((p) => (
                                        <button
                                          key={p.mins}
                                          type="button"
                                          onClick={() => setReminder(i, p.mins)}
                                          className={`rounded px-1.5 py-0.5 font-label text-[10px] font-medium transition ${
                                            mins === p.mins
                                              ? "bg-emerald-600 text-white shadow-xs"
                                              : "bg-white text-ink-secondary border border-border hover:border-emerald-300 hover:text-emerald-700"
                                          }`}
                                        >
                                          {p.label}
                                        </button>
                                      ))}
                                    </div>
                                  )}
                                </div>

                                {!rowValid && (
                                  <p className="mt-1.5 font-body text-[11px] text-red-600">
                                    Enter a whole number from 1 to 1440 (up to 24 hours).
                                  </p>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>

                      {/* Add Reminder Button Node */}
                      {reminders.length < MAX_REMINDERS && canManageSettings && (
                        <div className="relative mt-4 flex items-center gap-3">
                          <div className="z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-dashed border-emerald-400 bg-white text-emerald-600">
                            <Plus className="h-3 w-3" />
                          </div>
                          <button
                            type="button"
                            onClick={addReminder}
                            className="inline-flex items-center gap-1.5 rounded-xl border border-dashed border-emerald-300 bg-emerald-50/40 px-3 py-1.5 font-body text-xs font-semibold text-emerald-700 transition hover:bg-emerald-50 hover:border-emerald-400"
                          >
                            <Plus className="h-3.5 w-3.5" />
                            Add another reminder ({reminders.length + 1} of {MAX_REMINDERS})
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Right Column: Daily Limit on Top, Quiet Hours Below */}
                  <div className="lg:col-span-5 xl:col-span-5 space-y-4">
                    {/* Top: Daily Limit per Lead */}
                    <div className="rounded-xl border border-border-subtle bg-surface-subtle/60 p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-amber-100/70 text-amber-700">
                          <Shield className="h-3.5 w-3.5" />
                        </div>
                        <div>
                          <h5 className="font-display text-xs font-bold text-ink">
                            Daily Limit per Lead
                          </h5>
                          <p className="font-body text-[11px] text-ink-muted">
                            Max follow-ups allowed in 24 hours
                          </p>
                        </div>
                      </div>

                      <div className="mt-3.5 flex items-center gap-2.5">
                        {/* Stepper */}
                        <div className="inline-flex items-center rounded-lg border border-border bg-white p-0.5 shadow-xs">
                          <button
                            type="button"
                            disabled={!canManageSettings || capNum <= 1}
                            onClick={() => setCap(capNum - 1)}
                            className="flex h-7 w-7 items-center justify-center rounded-md text-ink transition hover:bg-surface-subtle hover:text-primary disabled:opacity-40"
                            aria-label="Decrease daily limit"
                          >
                            <Minus className="h-3 w-3" />
                          </button>
                          <div className="w-12 text-center">
                            <span className="font-display text-sm font-bold text-ink">
                              {capValid ? capNum : value(SILENCE_NUDGE_KEYS.cap)}
                            </span>
                          </div>
                          <button
                            type="button"
                            disabled={!canManageSettings || capNum >= 10}
                            onClick={() => setCap(capNum + 1)}
                            className="flex h-7 w-7 items-center justify-center rounded-md text-ink transition hover:bg-surface-subtle hover:text-primary disabled:opacity-40"
                            aria-label="Increase daily limit"
                          >
                            <Plus className="h-3 w-3" />
                          </button>
                        </div>

                        <span className="font-label text-xs font-semibold text-ink-secondary bg-white border border-border px-2 py-1 rounded-md">
                          nudges / 24h
                        </span>
                      </div>

                      {/* Quick preset chips */}
                      {canManageSettings && (
                        <div className="mt-3 flex items-center gap-1.5 pt-2 border-t border-border/40">
                          <span className="font-label text-[10px] text-ink-muted">Quick set:</span>
                          {CAP_PRESETS.map((preset) => (
                            <button
                              key={preset}
                              type="button"
                              onClick={() => setCap(parseInt(preset, 10))}
                              className={`rounded px-2 py-0.5 font-label text-[11px] font-semibold transition ${
                                String(capNum) === preset
                                  ? "bg-amber-600 text-white shadow-xs"
                                  : "bg-white text-ink-secondary border border-border hover:border-amber-400 hover:text-amber-800"
                              }`}
                            >
                              {preset}
                            </button>
                          ))}
                        </div>
                      )}

                      {!capValid && (
                        <p className="mt-2 font-body text-[11px] text-red-600">
                          Must be a whole number between 1 and 10.
                        </p>
                      )}

                      {capValid && reminders.length > capNum && (
                        <p className="mt-3 rounded-lg bg-amber-50 border border-amber-200/80 p-2 font-body text-[11px] text-amber-800">
                          ⚠️ Limit is {capNum}, so only {capNum} of your {reminders.length} follow-ups will send to a single lead per day.
                        </p>
                      )}
                    </div>

                    {/* Bottom: Quiet Hours */}
                    <div className="rounded-xl border border-border-subtle bg-surface-subtle/60 p-4">
                      <div className="flex items-center justify-between gap-2 mb-2">
                        <div className="flex items-center gap-2">
                          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary-100/70 text-primary-700">
                            <Moon className="h-3.5 w-3.5" />
                          </div>
                          <div>
                            <h5 className="font-display text-xs font-bold text-ink">
                              Quiet Hours
                            </h5>
                            <p className="font-body text-[11px] text-ink-muted">
                              Pause messages during resting hours
                            </p>
                          </div>
                        </div>
                        <span className="font-label text-[10px] font-bold uppercase tracking-wider text-primary-700 bg-primary-50 border border-primary-200/60 px-2 py-0.5 rounded-full">
                          IST (UTC+5:30)
                        </span>
                      </div>

                      {/* Inline Time Range */}
                      <div className="mt-3 flex items-center gap-2">
                        <div className="flex-1">
                          <span className="block font-label text-[10px] font-bold uppercase tracking-wider text-ink-muted mb-1">
                            Mute From
                          </span>
                          <input
                            type="time"
                            disabled={!canManageSettings}
                            value={quietStart}
                            onChange={(e) =>
                              setDrafts((d) => ({
                                ...d,
                                [SILENCE_NUDGE_KEYS.quietStart]: e.target.value,
                              }))
                            }
                            className="w-full rounded-lg border border-border bg-white px-2.5 py-1.5 font-mono text-xs font-semibold text-ink shadow-xs transition focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-60"
                          />
                        </div>

                        <div className="pt-4 text-ink-muted">
                          <ArrowRight className="h-3.5 w-3.5" />
                        </div>

                        <div className="flex-1">
                          <span className="block font-label text-[10px] font-bold uppercase tracking-wider text-ink-muted mb-1">
                            Resume At
                          </span>
                          <input
                            type="time"
                            disabled={!canManageSettings}
                            value={quietEnd}
                            onChange={(e) =>
                              setDrafts((d) => ({
                                ...d,
                                [SILENCE_NUDGE_KEYS.quietEnd]: e.target.value,
                              }))
                            }
                            className="w-full rounded-lg border border-border bg-white px-2.5 py-1.5 font-mono text-xs font-semibold text-ink shadow-xs transition focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-60"
                          />
                        </div>
                      </div>

                      {/* Summary */}
                      <div className="mt-2.5 flex items-center gap-1.5 font-body text-[11px] text-ink-secondary">
                        <Clock className="h-3 w-3 text-primary-600 shrink-0" />
                        <span>
                          Held between <strong className="text-ink">{formatTime12h(quietStart)}</strong> and{" "}
                          <strong className="text-ink">{formatTime12h(quietEnd)} IST</strong>
                        </span>
                      </div>

                      <p className="mt-2 text-[10px] font-body text-ink-muted">
                        ⚡ 1st follow-up always sends; later ones pause during quiet hours.
                      </p>
                    </div>
                  </div>
                </div>

                {/* Footer notes */}
                <div className="mt-6 rounded-xl bg-surface-subtle border border-border-subtle p-3 text-ink-secondary">
                  <p className="font-body text-xs flex items-center gap-2">
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 font-bold text-[10px]">
                      ✓
                    </span>
                    <span>
                      Each reminder is sent only if the lead has not replied. If the lead
                      replies at any time, the remaining follow-ups are cancelled immediately.
                    </span>
                  </p>
                </div>
              </div>
            </div>
          )}

          <SectionFooter
            status={
              <SaveStatus
                state={saveStates.automations_silence ?? "idle"}
                dirty={dirty}
                idleLabel={
                  enabled
                    ? "Quiet-lead follow-ups are enabled"
                    : "Quiet-lead follow-ups are off"
                }
              />
            }
          >
            <SaveButton
              state={saveStates.automations_silence ?? "idle"}
              dirty={dirty && delaysValid && capValid}
              disabled={!canManageSettings}
              onClick={() =>
                handleSave(
                  "automations_silence",
                  Object.values(SILENCE_NUDGE_KEYS).filter((k) => k !== SILENCE_NUDGE_KEYS.enabled)
                )
              }
            />
          </SectionFooter>
        </div>
      </SettingsSection>
    </SettingsAccordion>
  );
}

