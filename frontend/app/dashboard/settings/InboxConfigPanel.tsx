"use client";
import { useCallback, useEffect, useState } from "react";
import { API_URL, api, getAuthHeaders } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { CheckField, TickMark } from "@/components/ui/controls";
import type { SectionLoadState } from "./SettingsSection";

export type InboxConfig = {
  enabled: boolean;
  auto_assign_enabled: boolean;
  channels: string[];
  triggers: string[];
  /** Trigger H: an order at or above this (paise). */
  order_above_paise?: number | null;
  /** Who gets a handed-over chat with no teammate yet, and who takes it if nobody replies in 15 minutes. */
  handover_to?: string | null;
  backup_to?: string | null;
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
  G: { label: "Customer is angry or complains" },
  H: { label: "Big order, or a bulk order" },
  I: { label: "Customer sends a photo (the AI can't read images)" },
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
  const [team, setTeam] = useState<{ value: string; label: string }[]>([]);
  useEffect(() => {
    api.callers.list()
      .then(({ data }) => setTeam(data.filter((c) => c.active !== false).map((c) => ({ value: c.id, label: c.name }))))
      .catch(() => {});
  }, []);
  const rupees = Math.round((draft.order_above_paise ?? 2500000) / 100);
  const people = [{ value: "", label: "Nobody: everyone can pick it up" }, ...team];
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
      {draft.triggers.includes("H") && (
        <label className="flex flex-wrap items-center gap-2 text-sm text-ink">
          A big order is above ₹
          <input type="number" min={1} step={500} value={rupees} disabled={disabled} aria-label="Big order above, in rupees"
            onChange={(e) => setDraft({ ...draft, order_above_paise: Math.max(1, Number(e.target.value) || 0) * 100 })}
            className="h-9 w-28 rounded-lg border border-border px-2 text-sm" />
        </label>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <div className="mb-1.5 font-label text-xs font-semibold uppercase tracking-wider text-ink-muted">Who gets the chat</div>
          <Select size="sm" aria-label="Who gets the chat" value={draft.handover_to ?? ""} disabled={disabled}
            onChange={(v) => setDraft({ ...draft, handover_to: v || null })} options={people} />
          <p className="mt-1 text-xs text-ink-muted">When the chat has no teammate yet.</p>
        </div>
        <div>
          <div className="mb-1.5 font-label text-xs font-semibold uppercase tracking-wider text-ink-muted">Then, if no reply in 15 min</div>
          <Select size="sm" aria-label="Backup" value={draft.backup_to ?? ""} disabled={disabled || !draft.handover_to}
            onChange={(v) => setDraft({ ...draft, backup_to: v || null })}
            options={[{ value: "", label: "Nobody: the owner is alerted" }, ...team.filter((t) => t.value !== draft.handover_to)]} />
          <p className="mt-1 text-xs text-ink-muted">The owner is still told after 15 minutes.</p>
        </div>
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
