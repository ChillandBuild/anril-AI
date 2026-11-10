"use client";
import { useEffect, useState, useCallback } from "react";
import { Phone, Smartphone, RadioTower } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { SaveButton, SaveStatus, SectionFooter, SectionLoadGate, SettingsSection, type SectionLoadState } from "./SettingsSection";
import { CheckField, SwitchPill, TickMark } from "@/components/ui/controls";

type AssignMode = "auto" | "pull" | "available";
type ChannelRule = { enabled: boolean; mode: AssignMode; segments?: string[] };
type RowKey = "whatsapp" | "instagram" | "facebook" | "telegram" | "meta_form" | "other" | "upload";

type TelecallingConfig = {
  enabled: boolean;
  calling_provider?: "telecmi" | "sim_basic";
  max_call_attempts?: number;
  channel_rules?: Partial<Record<RowKey, ChannelRule>>;
  recycle_enabled?: boolean;
  recycle_delay_hours?: number;
  recycle_max_retries?: number;
  recycle_start_hour?: number;
  recycle_end_hour?: number;
};

// Legacy fields the server still accepts. The panel never sends them.
const LEGACY_KEYS = ["calling_provider", "channels", "segments", "assignment_mode"] as const;

const DEFAULT: TelecallingConfig = {
  enabled: false,
  calling_provider: "telecmi",
  max_call_attempts: 4,
};

const SEGMENTS = [
  { key: "A", label: "Hot" },
  { key: "B", label: "Warm" },
  { key: "C", label: "Cold" },
];

const ROWS: { key: RowKey; label: string; hint?: string }[] = [
  { key: "whatsapp", label: "WhatsApp", hint: "Also covers broadcast imports and leads added by hand" },
  { key: "instagram", label: "Instagram" },
  { key: "facebook", label: "Facebook" },
  { key: "telegram", label: "Telegram" },
  { key: "meta_form", label: "Instant forms" },
  { key: "other", label: "Other sources", hint: "IndiaMART, JustDial, website and API" },
  { key: "upload", label: "Telecalling uploads", hint: "Every uploaded row counts" },
];

const MODES: { value: AssignMode; label: string; short: string }[] = [
  { value: "auto", label: "Auto assign", short: "Auto" },
  { value: "pull", label: "Pull", short: "Pull" },
  { value: "available", label: "Available telecallers", short: "Available" },
];

/** The rule for a row, falling back to the default when the loaded data has none. */
function ruleFor(cfg: TelecallingConfig, row: RowKey): ChannelRule {
  const stored = cfg.channel_rules?.[row];
  if (stored) return stored;
  if (row === "upload") return { enabled: true, mode: "auto" };
  return { enabled: true, mode: "auto", segments: row === "other" ? ["A", "B", "C"] : ["A"] };
}

function toggle<T>(arr: T[], item: T): T[] {
  return arr.includes(item) ? arr.filter((x) => x !== item) : [...arr, item];
}

export function TelecallingConfigPanel({ canManage = true }: { canManage?: boolean }) {
  const [config, setConfig] = useState<TelecallingConfig>(DEFAULT);
  const [draft, setDraft] = useState<TelecallingConfig>(DEFAULT);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const [loadState, setLoadState] = useState<SectionLoadState>("loading");
  const { enabledFeatures } = useAuthRole();
  const hasUpload = enabledFeatures.includes("telecalling.upload");

  const load = useCallback(async () => {
    setLoadState("loading");
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/settings/telecalling-config`, { headers: auth });
      if (res.ok) {
        const data: TelecallingConfig = await res.json();
        setConfig(data);
        setDraft(data);
        setLoadState("ready");
        return;
      }
      setLoadState("error");
    } catch {
      setLoadState("error");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const isDirty = JSON.stringify(draft) !== JSON.stringify(config);

  function setRule(row: RowKey, patch: Partial<ChannelRule>) {
    const channel_rules = Object.fromEntries(
      ROWS.map((r) => [r.key, ruleFor(draft, r.key)]),
    ) as Record<RowKey, ChannelRule>;
    channel_rules[row] = { ...channel_rules[row], ...patch };
    setDraft({ ...draft, channel_rules });
  }

  function toggleSegment(row: RowKey, seg: string) {
    const current = ruleFor(draft, row).segments ?? [];
    const next = toggle(current, seg);
    setRule(row, { segments: SEGMENTS.map((s) => s.key).filter((k) => next.includes(k)) });
  }

  async function handleSave() {
    if (!canManage || loadState !== "ready") return;
    setSaveState("saving");
    try {
      const auth = await getAuthHeaders();
      const clientEditableDraft: Record<string, unknown> = { ...draft };
      for (const key of LEGACY_KEYS) delete clientEditableDraft[key];
      const res = await fetch(`${API_URL}/api/v1/settings/telecalling-config`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify(clientEditableDraft),
      });
      if (!res.ok) throw new Error("Save failed");
      const saved: TelecallingConfig = await res.json();
      setConfig(saved);
      setDraft(saved);
      setSaveState("saved");
      setTimeout(() => setSaveState("idle"), 2000);
    } catch {
      setSaveState("idle");
    }
  }

  const controlsDisabled = !canManage || !draft.enabled;
  const visibleRows = ROWS.filter((r) => r.key !== "upload" || hasUpload);

  return (
    <SettingsSection
      id="telecalling-assignment"
      icon={Phone}
      accent="amber"
      title="Telecalling Assignment"
      description="Decide how leads from each channel reach your telecallers."
      status={loadState === "ready" ? { label: draft.enabled ? "Enabled" : "Disabled", tone: draft.enabled ? "on" : "off" } : undefined}
      dirty={isDirty}
    >
      <SectionLoadGate state={loadState} onRetry={load}>
        <div className="space-y-6">
          {/* Master switch */}
          <div
            className={`flex items-center gap-4 rounded-xl border p-3.5 ${
              draft.enabled ? "border-primary/25 bg-primary-light/50" : "border-border bg-white"
            }`}
          >
            <div className="min-w-0 flex-1">
              <div className="font-label text-sm font-semibold text-ink">Telecaller assignment</div>
              <div className="mt-0.5 font-body text-xs text-ink-muted">
                Turn off to stop all automatic assignment. Telecallers can still pick leads by hand.
              </div>
            </div>
            <SwitchPill
              size="md"
              on={draft.enabled}
              disabled={!canManage}
              onChange={(v) => setDraft({ ...draft, enabled: v })}
              aria-label="Telecaller assignment"
            />
          </div>

          {/* Per-channel rules */}
          <div>
            <div className="font-label text-sm font-semibold text-ink mb-1">How each channel is assigned</div>
            <div className="font-body text-xs text-ink-muted mb-3">
              Switch a channel off and its leads are never assigned automatically.
            </div>
            <ul
              className={`rounded-2xl border border-border divide-y divide-border-subtle bg-white transition-opacity duration-200 ${
                draft.enabled ? "" : "opacity-50"
              }`}
            >
              {visibleRows.map((row) => {
                const rule = ruleFor(draft, row.key);
                const segments = rule.segments ?? [];
                const isUpload = row.key === "upload";
                return (
                  <li key={row.key} className="px-4 py-2.5 flex flex-wrap items-center gap-x-4 gap-y-2">
                    <div className="order-1 min-w-0 flex-1 sm:flex-none sm:w-36 sm:shrink-0">
                      <div className="font-label text-sm font-semibold text-ink">{row.label}</div>
                      {row.hint && <div className="font-body text-[11px] leading-tight text-ink-muted">{row.hint}</div>}
                    </div>

                    {!rule.enabled && <span className="order-1 font-body text-xs text-ink-muted">Off</span>}

                    {rule.enabled && (
                      <>
                        {/* Assign by */}
                        <div role="group" aria-label={`${row.label} assign by`} className="order-3 sm:order-2 flex gap-1 p-1 bg-surface-subtle border border-border rounded-xl w-fit">
                          {MODES.map((m) => {
                            const active = rule.mode === m.value;
                            return (
                              <button
                                key={m.value}
                                type="button"
                                aria-pressed={active}
                                disabled={controlsDisabled}
                                onClick={() => setRule(row.key, { mode: m.value })}
                                className={`whitespace-nowrap px-2.5 sm:px-3 py-1.5 rounded-lg font-label text-xs font-bold transition-all disabled:cursor-not-allowed disabled:opacity-55 ${
                                  active ? "bg-white text-ink shadow-sm border border-border/50" : "text-ink-muted hover:text-ink"
                                }`}
                              >
                                <span className="sm:hidden">{m.short}</span>
                                <span className="hidden sm:inline">{m.label}</span>
                              </button>
                            );
                          })}
                        </div>

                        {/* Segments */}
                        {!isUpload && (
                          <div role="group" aria-label={`${row.label} segments`} className="order-4 sm:order-3 flex flex-wrap items-center gap-1.5">
                            {SEGMENTS.map((seg) => {
                              const active = segments.includes(seg.key);
                              return (
                                <button
                                  key={seg.key}
                                  type="button"
                                  role="checkbox"
                                  aria-checked={active}
                                  disabled={controlsDisabled}
                                  onClick={() => toggleSegment(row.key, seg.key)}
                                  className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-label font-semibold text-ink transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-55 ${
                                    active ? "border-primary/25 bg-primary-light/50" : "border-border bg-surface-subtle hover:border-primary/40"
                                  }`}
                                >
                                  <TickMark checked={active} size="sm" />
                                  <span>{seg.label}</span>
                                </button>
                              );
                            })}
                            {segments.length === 0 && (
                              <span className="font-body text-[11px] text-amber-700">Pick one</span>
                            )}
                          </div>
                        )}
                      </>
                    )}

                    <div className="order-2 sm:order-5 ml-auto">
                      <SwitchPill
                        size="sm"
                        on={rule.enabled}
                        disabled={controlsDisabled}
                        onChange={(v) => setRule(row.key, { enabled: v })}
                        aria-label={`${row.label} assignment`}
                      />
                    </div>
                    {/* Phone: name + switch on the first line, options below. */}
                    <div aria-hidden className="order-2 basis-full h-0 sm:hidden" />
                  </li>
                );
              })}
            </ul>
            <p className="mt-2 font-body text-[11px] text-ink-muted leading-relaxed">
              <span className="font-semibold text-ink-secondary">Auto assign</span>: telecallers take turns (round robin).{" "}
              <span className="font-semibold text-ink-secondary">Pull</span>: leads wait in a shared list for “Call next”.{" "}
              <span className="font-semibold text-ink-secondary">Available telecallers</span>: only people on shift and not logged out; if nobody is on shift, online telecallers are asked to take the waiting leads.
            </p>
          </div>

          {/* Calling Provider */}
          <div>
            <div className="font-label text-sm font-semibold text-ink mb-1">Calling Provider</div>
            <div className="font-body text-xs text-ink-muted mb-3">
              This is configured by the developer console. The dialer, lead profile, notes, callbacks, and analytics remain the same.
            </div>
            <div className="rounded-2xl border border-primary-muted bg-primary-light/60 p-4">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-white text-primary">
                  {(draft.calling_provider ?? "telecmi") === "sim_basic" ? <Smartphone size={18} /> : <RadioTower size={18} />}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <p className="font-display text-sm font-bold text-ink">
                      {(draft.calling_provider ?? "telecmi") === "sim_basic" ? "SIM Basic" : "Cloud Telephony"}
                    </p>
                    <span className="badge badge-green">Active</span>
                    <span className="badge badge-gray">Developer managed</span>
                  </div>
                  <p className="mt-1 font-body text-xs leading-relaxed text-ink-muted">
                    {(draft.calling_provider ?? "telecmi") === "sim_basic"
                      ? "Mobile SIM dialing is active. Telecallers log duration, outcome, and notes manually after each call."
                      : "Cloud Telephony API calling is active. Call logs, durations, recordings, and webhook updates are handled automatically."}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Contact Recycling — only visible when telecalling upload is enabled */}
          {hasUpload && (
            <div>
              <div className="font-label text-sm font-semibold text-ink mb-1">Contact Recycling</div>
              <div className="font-body text-xs text-ink-muted mb-3">Automatically re-queue no-answer leads back into the calling queue after a delay</div>

              <CheckField
                className="mb-3"
                checked={draft.recycle_enabled ?? false}
                disabled={!canManage}
                onChange={(v) => setDraft({ ...draft, recycle_enabled: v })}
                label="Enable Contact Recycling"
                description={'No-answer leads reset to "new" after the delay, so they re-enter the calling queue'}
              />

              {draft.recycle_enabled && (
                <div className="space-y-3 pl-1">
                  <div className="flex items-center gap-3">
                    <label className="font-label text-xs font-semibold text-ink w-32">Delay (hours)</label>
                    <input
                      type="number"
                      min={1}
                      max={48}
                      value={draft.recycle_delay_hours ?? 4}
                      onChange={(e) => setDraft({ ...draft, recycle_delay_hours: Number(e.target.value) })}
                      className="w-20 px-3 py-1.5 rounded-lg border border-border text-sm font-body text-ink bg-white"
                    />
                    <span className="font-body text-xs text-ink-muted">Wait this long after last failed call</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <label className="font-label text-xs font-semibold text-ink w-32">Max retries</label>
                    <input
                      type="number"
                      min={1}
                      max={10}
                      value={draft.recycle_max_retries ?? 3}
                      onChange={(e) => setDraft({ ...draft, recycle_max_retries: Number(e.target.value) })}
                      className="w-20 px-3 py-1.5 rounded-lg border border-border text-sm font-body text-ink bg-white"
                    />
                    <span className="font-body text-xs text-ink-muted">Stop recycling after this many total attempts</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <label className="font-label text-xs font-semibold text-ink w-32">Calling hours</label>
                    <select
                      value={draft.recycle_start_hour ?? 9}
                      onChange={(e) => setDraft({ ...draft, recycle_start_hour: Number(e.target.value) })}
                      className="px-3 py-1.5 rounded-lg border border-border text-sm font-body text-ink bg-white"
                    >
                      {Array.from({ length: 24 }, (_, i) => (
                        <option key={i} value={i}>{`${i.toString().padStart(2, "0")}:00`}</option>
                      ))}
                    </select>
                    <span className="font-body text-xs text-ink-muted">to</span>
                    <select
                      value={draft.recycle_end_hour ?? 18}
                      onChange={(e) => setDraft({ ...draft, recycle_end_hour: Number(e.target.value) })}
                      className="px-3 py-1.5 rounded-lg border border-border text-sm font-body text-ink bg-white"
                    >
                      {Array.from({ length: 24 }, (_, i) => (
                        <option key={i} value={i}>{`${i.toString().padStart(2, "0")}:00`}</option>
                      ))}
                    </select>
                    <span className="font-body text-xs text-ink-muted">IST</span>
                  </div>
                </div>
              )}
            </div>
          )}

        </div>

        <SectionFooter status={<SaveStatus state={saveState} dirty={isDirty} idleLabel={draft.enabled ? "Auto-assign is live" : "Auto-assign is off"} />}>
          <SaveButton state={saveState} dirty={isDirty} disabled={!canManage} onClick={handleSave} />
        </SectionFooter>
      </SectionLoadGate>
    </SettingsSection>
  );
}
