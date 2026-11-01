"use client";
import { useEffect, useState, useCallback } from "react";
import { Inbox } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { SaveButton, SaveStatus, SectionFooter, SectionLoadGate, SettingsSection, type SectionLoadState } from "./SettingsSection";
import { CheckField, TickMark } from "@/components/ui/controls";

type InboxConfig = {
  enabled: boolean;
  auto_assign_enabled: boolean;
  channels: string[];
  triggers: string[];
};

const DEFAULT: InboxConfig = {
  enabled: false,
  auto_assign_enabled: false,
  channels: ["whatsapp", "instagram", "facebook", "telegram"],
  triggers: ["A", "B", "C", "F"],
};

const TRIGGER_LABELS: Record<string, { label: string; always?: boolean }> = {
  A: { label: "AI couldn't answer — sent a generic holding reply" },
  B: { label: "AI failed completely (technical error)" },
  C: { label: "User explicitly asked to speak to a person", always: true },
  D: { label: "User repeated the same question (AI not resolving it)" },
  F: { label: "AI response indicated the team would follow up" },
};

const CHANNEL_LABELS: Record<string, string> = {
  whatsapp: "WhatsApp",
  instagram: "Instagram",
  facebook: "Facebook",
  telegram: "Telegram",
};

function toggle<T>(arr: T[], item: T): T[] {
  return arr.includes(item) ? arr.filter((x) => x !== item) : [...arr, item];
}

export function InboxConfigPanel({ canManage = true }: { canManage?: boolean }) {
  const [config, setConfig] = useState<InboxConfig>(DEFAULT);
  const [draft, setDraft] = useState<InboxConfig>(DEFAULT);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const [loadState, setLoadState] = useState<SectionLoadState>("loading");

  const load = useCallback(async () => {
    setLoadState("loading");
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/settings/inbox-config`, { headers: auth });
      if (res.ok) {
        const data = await res.json();
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

  async function handleSave() {
    if (!canManage || loadState !== "ready") return;
    setSaveState("saving");
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/settings/inbox-config`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify(draft),
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
      id="inbox-escalation"
      icon={Inbox}
      accent="violet"
      title="Inbox Escalation"
      description="Configure when AI escalates leads to the omnichannel inbox for human follow-up."
      status={loadState === "ready" ? { label: draft.enabled ? "Enabled" : "Disabled", tone: draft.enabled ? "on" : "off" } : undefined}
      dirty={isDirty}
    >
      <SectionLoadGate state={loadState} onRetry={load}>
        <div className="space-y-6">
          {/* Master toggles */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <CheckField
              checked={draft.enabled}
              disabled={!canManage}
              onChange={(v) => setDraft({ ...draft, enabled: v })}
              label="Enable Inbox Escalation"
              description="Master switch — off means no handovers are created automatically"
            />
            <CheckField
              checked={draft.auto_assign_enabled}
              disabled={!canManage}
              onChange={(v) => setDraft({ ...draft, auto_assign_enabled: v })}
              label="Auto-Assign (Round-Robin)"
              description="Auto-assign escalated handovers to the active telecaller with fewest leads"
            />
          </div>

          {/* Triggers */}
          <div>
            <div className="font-label text-sm font-semibold text-ink mb-2">Escalation Triggers</div>
            <div className="space-y-2">
              {Object.entries(TRIGGER_LABELS).map(([key, { label, always }]) => (
                <CheckField
                  key={key}
                  checked={always ? true : draft.triggers.includes(key)}
                  disabled={!canManage}
                  locked={always}
                  lockedNote="Always on — cannot be disabled (direct user request)"
                  onChange={() => setDraft({ ...draft, triggers: toggle(draft.triggers, key) })}
                  label={label}
                />
              ))}
            </div>
          </div>

          {/* Channels */}
          <div>
            <div className="font-label text-sm font-semibold text-ink mb-2">Channels</div>
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

        </div>

        <SectionFooter status={<SaveStatus state={saveState} dirty={isDirty} idleLabel={draft.enabled ? "Escalation is live" : "Escalation is off"} />}>
          <SaveButton state={saveState} dirty={isDirty} disabled={!canManage} onClick={handleSave} />
        </SectionFooter>
      </SectionLoadGate>
    </SettingsSection>
  );
}
