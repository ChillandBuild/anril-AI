"use client";
import { useCallback, useEffect, useState } from "react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { CheckField, TickMark } from "@/components/ui/controls";
import type { SectionLoadState } from "./SettingsSection";

export type InboxConfig = {
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
  A: { label: "AI couldn't answer and sent a holding reply" },
  F: { label: "AI said the team would follow up" },
  B: { label: "AI failed (technical error)" },
  D: { label: "Customer asked the same thing again" },
  C: { label: "Customer asked for a person", always: true },
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

export type InboxConfigState = ReturnType<typeof useInboxConfig>;

/** Handover settings (/settings/inbox-config): loaded once, edited as a draft, saved by the page's one Save bar. */
export function useInboxConfig() {
  const [saved, setSaved] = useState<InboxConfig>(DEFAULT);
  const [draft, setDraft] = useState<InboxConfig>(DEFAULT);
  const [loadState, setLoadState] = useState<SectionLoadState>("loading");

  const load = useCallback(async () => {
    setLoadState("loading");
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/settings/inbox-config`, { headers: auth });
      if (!res.ok) throw new Error("load failed");
      const data = (await res.json()) as InboxConfig;
      setSaved(data);
      setDraft(data);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }, []);
  useEffect(() => void load(), [load]);

  const dirty = loadState === "ready" && JSON.stringify(draft) !== JSON.stringify(saved);

  /** Returns an error message, or null when saved. */
  const save = useCallback(async (): Promise<string | null> => {
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/settings/inbox-config`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify(draft),
      });
      if (!res.ok) throw new Error("save failed");
      const data = (await res.json()) as InboxConfig;
      setSaved(data);
      setDraft(data);
      return null;
    } catch {
      return "Handover settings did not save";
    }
  }, [draft]);

  return { draft, setDraft, loadState, load, dirty, save };
}

export function HandoverFields({ state, disabled }: { state: InboxConfigState; disabled: boolean }) {
  const { draft, setDraft } = state;
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        {Object.entries(TRIGGER_LABELS).map(([key, { label, always }]) => (
          <CheckField
            key={key}
            checked={always ? true : draft.triggers.includes(key)}
            disabled={disabled}
            locked={always}
            lockedNote="Always on"
            onChange={() => setDraft({ ...draft, triggers: toggle(draft.triggers, key) })}
            label={label}
          />
        ))}
      </div>
      <CheckField
        checked={draft.auto_assign_enabled}
        disabled={disabled}
        onChange={(v) => setDraft({ ...draft, auto_assign_enabled: v })}
        label="Share out in turn to the team"
        description="Each handed-over chat goes to the active telecaller with the fewest leads."
      />
      <div>
        <div className="mb-2 font-label text-xs font-semibold uppercase tracking-wider text-ink-muted">On these channels</div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(CHANNEL_LABELS).map(([ch, label]) => {
            const active = draft.channels.includes(ch);
            return (
              <button
                key={ch}
                type="button"
                role="checkbox"
                aria-checked={active}
                disabled={disabled}
                onClick={() => setDraft({ ...draft, channels: toggle(draft.channels, ch) })}
                className={`flex items-center gap-2 rounded-xl border px-3 py-1.5 transition-colors disabled:cursor-not-allowed disabled:opacity-55 ${
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
  );
}
