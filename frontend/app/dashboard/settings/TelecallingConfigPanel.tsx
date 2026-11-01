"use client";
import { useEffect, useState, useCallback } from "react";
import { Phone, Smartphone, RadioTower } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { SaveButton, SaveStatus, SectionFooter, SectionLoadGate, SettingsSection, type SectionLoadState } from "./SettingsSection";
import { CheckField, TickMark } from "@/components/ui/controls";

type TelecallingConfig = {
  enabled: boolean;
  calling_provider?: "telecmi" | "sim_basic";
  segments: string[];
  channels: string[];
  max_call_attempts?: number;
  assignment_mode?: "push" | "pull";
  recycle_enabled?: boolean;
  recycle_delay_hours?: number;
  recycle_max_retries?: number;
  recycle_start_hour?: number;
  recycle_end_hour?: number;
};

const DEFAULT: TelecallingConfig = {
  enabled: false,
  calling_provider: "telecmi",
  segments: ["A"],
  channels: ["whatsapp"],
  max_call_attempts: 4,
  assignment_mode: "push",
};

const SEGMENT_LABELS: Record<string, string> = {
  A: "Hot",
  B: "Warm",
  C: "Cold",
};

const CHANNEL_LABELS: Record<string, string> = {
  whatsapp: "WhatsApp",
};

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
        const data = await res.json();
        const sanitizedData = {
          ...data,
          channels: data.channels ? data.channels.filter((c: string) => c === "whatsapp") : ["whatsapp"]
        };
        setConfig(sanitizedData);
        setDraft(sanitizedData);
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

  async function handleSave() {
    if (!canManage || loadState !== "ready") return;
    setSaveState("saving");
    try {
      const auth = await getAuthHeaders();
      const clientEditableDraft = { ...draft };
      delete clientEditableDraft.calling_provider;
      const res = await fetch(`${API_URL}/api/v1/settings/telecalling-config`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify(clientEditableDraft),
      });
      if (!res.ok) throw new Error("Save failed");
      const saved = await res.json();
      setConfig(saved);
      setDraft(saved);
      setSaveState("saved");
      setTimeout(() => setSaveState("idle"), 2000);
    } catch {
      setSaveState("idle");
    }
  }

  return (
    <SettingsSection
      id="telecalling-assignment"
      icon={Phone}
      accent="amber"
      title="Telecalling Assignment"
      description="Automatically assign leads to telecallers when they enter a qualifying segment."
      status={loadState === "ready" ? { label: draft.enabled ? "Enabled" : "Disabled", tone: draft.enabled ? "on" : "off" } : undefined}
      dirty={isDirty}
    >
      <SectionLoadGate state={loadState} onRetry={load}>
        <div className="space-y-6">
          {/* Master toggle */}
          <CheckField
            checked={draft.enabled}
            disabled={!canManage}
            onChange={(v) => setDraft({ ...draft, enabled: v })}
            label="Enable Auto-Assign to Telecallers"
            description="Automatically assign qualifying leads to the active telecaller with fewest leads on segment change"
          />

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

          {/* Segments */}
          <div>
            <div className="font-label text-sm font-semibold text-ink mb-1">Segments to Assign</div>
            <div className="font-body text-xs text-ink-muted mb-2">Which lead segments are worked by telecallers (auto-assigned in Push mode, pooled for Call Next in Pull mode)</div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(SEGMENT_LABELS).map(([seg, label]) => {
                const active = draft.segments.includes(seg);
                return (
                  <button
                    key={seg}
                    type="button"
                    role="checkbox"
                    aria-checked={active}
                    disabled={!canManage}
                    onClick={() => setDraft({ ...draft, segments: toggle(draft.segments, seg) })}
                    className={`flex items-center gap-2 rounded-xl border px-3 py-2 transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-55 ${
                      active ? "border-primary/25 bg-primary-light/50" : "border-border bg-surface-subtle hover:border-primary/40"
                    }`}
                  >
                    <TickMark checked={active} size="sm" />
                    <span className="font-label text-sm font-semibold text-ink">{label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Channels */}
          <div>
            <div className="font-label text-sm font-semibold text-ink mb-1">Channels</div>
            <div className="font-body text-xs text-ink-muted mb-2">Which channels feed into the telecalling queue (typically WhatsApp only)</div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(CHANNEL_LABELS).map(([ch, label]) => {
                const active = draft.channels.includes(ch);
                return (
                  <button
                    key={ch}
                    type="button"
                    role="checkbox"
                    aria-checked={active}
                    disabled={!canManage}
                    onClick={() => setDraft({ ...draft, channels: toggle(draft.channels, ch) })}
                    className={`flex items-center gap-2 rounded-xl border px-3 py-2 transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-55 ${
                      active ? "border-primary/25 bg-primary-light/50" : "border-border bg-surface-subtle hover:border-primary/40"
                    }`}
                  >
                    <TickMark checked={active} size="sm" />
                    <span className="font-label text-sm font-semibold text-ink">{label}</span>
                  </button>
                );
              })}
            </div>
          </div>


          {/* Assignment Mode */}
          <div>
            <div className="font-label text-sm font-semibold text-ink mb-1">Assignment Mode</div>
            <div className="font-body text-xs text-ink-muted mb-2">Choose how leads are distributed to telecallers</div>
            <div className="flex gap-2 p-1 bg-surface-subtle border border-border rounded-xl w-fit">
              <button
                type="button"
                onClick={() => setDraft({ ...draft, assignment_mode: "push" })}
                className={`px-4 py-2 rounded-lg font-label text-xs font-bold transition-all ${
                  (draft.assignment_mode ?? "push") === "push"
                    ? "bg-white text-ink shadow-sm border border-border/50"
                    : "text-ink-muted hover:text-ink"
                }`}
              >
                Push (Auto-Assign)
              </button>
              <button
                type="button"
                onClick={() => setDraft({ ...draft, assignment_mode: "pull" })}
                className={`px-4 py-2 rounded-lg font-label text-xs font-bold transition-all ${
                  draft.assignment_mode === "pull"
                    ? "bg-white text-ink shadow-sm border border-border/50"
                    : "text-ink-muted hover:text-ink"
                }`}
              >
                Pull (Shark Tank)
              </button>
            </div>
            <p className="font-body text-[11px] text-ink-muted mt-2 max-w-md">
              {(draft.assignment_mode ?? "push") === "push" ? (
                <span><strong>Push</strong> — leads auto-assign to callers by round-robin.</span>
              ) : (
                <span><strong>Pull</strong> — leads wait in a shared pool; callers grab the next one with &quot;Call Next&quot;.</span>
              )}
            </p>
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
