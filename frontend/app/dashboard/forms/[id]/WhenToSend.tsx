"use client";
import { Bot, Megaphone, Radio } from "lucide-react";
import type { WaFormTiming, WaFormTriggers } from "@/lib/api";
import { cn } from "@/lib/utils";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { SwitchPill } from "@/components/ui/controls";
import { useFormReachOptions } from "@/hooks/useApi";

const WHEN_MAX = 300; // backend whatsapp_form_reach.WHEN_MAX

const TIMING_OPTIONS: { value: WaFormTiming; label: string }[] = [
  { value: "instead", label: "Instead of Anril's first reply" },
  { value: "after", label: "After Anril's first reply" },
];

function Rule({
  icon, title, hint, on, onToggle, disabled, children,
}: {
  icon: React.ReactNode; title: string; hint: string; on: boolean; onToggle: (v: boolean) => void;
  disabled?: boolean; children?: React.ReactNode;
}) {
  return (
    <div className={cn("rounded-2xl p-4 ring-1 transition-colors", on ? "bg-primary-light/30 ring-primary/25" : "bg-surface ring-surface-mid")}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 gap-3">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-primary-700 ring-1 ring-surface-mid">
            {icon}
          </span>
          <div className="min-w-0">
            <p className="font-label text-sm font-semibold text-ink">{title}</p>
            <p className="font-body text-xs leading-relaxed text-ink-secondary">{hint}</p>
          </div>
        </div>
        <SwitchPill on={on} onChange={onToggle} disabled={disabled} aria-label={title} />
      </div>
      {on && children && <div className="mt-4 space-y-3 pl-11">{children}</div>}
    </div>
  );
}

function PickList({
  items, chosen, onChange, empty, disabled,
}: {
  items: { id: string; name: string; note?: string | null }[];
  chosen: string[];
  onChange: (next: string[]) => void;
  empty: string;
  disabled?: boolean;
}) {
  if (items.length === 0) return <p className="font-body text-xs text-ink-muted">{empty}</p>;
  return (
    <ul className="max-h-56 divide-y divide-surface-mid overflow-y-auto rounded-xl bg-white ring-1 ring-surface-mid">
      {items.map((item) => {
        const on = chosen.includes(item.id);
        return (
          <li key={item.id}>
            <label className="flex cursor-pointer items-center justify-between gap-3 px-3 py-2 hover:bg-surface-low">
              <span className="min-w-0">
                <span className="block truncate font-body text-sm text-ink">{item.name}</span>
                {item.note && <span className="block font-body text-[11px] text-ink-muted">{item.note}</span>}
              </span>
              <input
                type="checkbox"
                checked={on}
                disabled={disabled}
                onChange={() => onChange(on ? chosen.filter((c) => c !== item.id) : [...chosen, item.id])}
                className="h-4 w-4 shrink-0 accent-[var(--primary)]"
              />
            </label>
          </li>
        );
      })}
    </ul>
  );
}

/** When Anril sends this form by itself. Every rule is the client's own; nothing is on by default. */
export function WhenToSend({
  triggers, onChange, disabled,
}: {
  triggers: WaFormTriggers;
  onChange: (next: WaFormTriggers) => void;
  disabled?: boolean;
}) {
  const anyOn = triggers.ads.enabled || triggers.broadcasts.enabled;
  const { data: options } = useFormReachOptions(anyOn);
  const set = <K extends keyof WaFormTriggers>(key: K, patch: Partial<WaFormTriggers[K]>) =>
    onChange({ ...triggers, [key]: { ...triggers[key], ...patch } });
  const allAds = triggers.ads.ad_ids.length === 0;

  return (
    <div className="space-y-3">
      <Rule
        icon={<Bot size={16} />}
        title="Anril's AI sends it"
        hint="In any chat, when the conversation matches your rule. Your team can always send it by hand too."
        on={triggers.ai.enabled}
        onToggle={(v) => set("ai", { enabled: v })}
        disabled={disabled}
      >
        <label className="block space-y-1">
          <span className="font-label text-xs font-semibold text-ink">Send it when…</span>
          <textarea
            value={triggers.ai.when}
            rows={2}
            disabled={disabled}
            onChange={(e) => set("ai", { when: e.target.value })}
            placeholder="e.g. someone wants to book a site visit, or asks to see the flat"
            className={cn(
              "w-full resize-y rounded-lg border bg-white px-3 py-2 font-body text-sm text-ink focus:outline-none",
              triggers.ai.when.length > WHEN_MAX ? "border-red-300" : "border-surface-mid focus:border-primary/40",
            )}
          />
          <span className={cn("block font-body text-[11px] tabular-nums", triggers.ai.when.length > WHEN_MAX ? "text-red-600" : "text-ink-muted")}>
            {triggers.ai.when.length}/{WHEN_MAX} · Any language. The AI also writes the line above the form&apos;s button.
          </span>
        </label>
      </Rule>

      <Rule
        icon={<Megaphone size={16} />}
        title="Customers from Click-to-WhatsApp ads"
        hint="When someone messages you from an ad. Each person gets it at most once a week."
        on={triggers.ads.enabled}
        onToggle={(v) => set("ads", { enabled: v })}
        disabled={disabled}
      >
        <SegmentedControl
          aria-label="Which ads"
          value={allAds ? "all" : "chosen"}
          disabled={disabled}
          onChange={(v) => set("ads", { ad_ids: v === "all" ? [] : options?.ads.slice(0, 1).map((a) => a.id) ?? [] })}
          options={[{ value: "all", label: "Every ad" }, { value: "chosen", label: "Chosen ads" }]}
        />
        {!allAds && (
          <PickList
            items={(options?.ads ?? []).map((a) => ({ id: a.id, name: a.name, note: a.status === "ACTIVE" ? "Running" : a.status?.toLowerCase() }))}
            chosen={triggers.ads.ad_ids}
            onChange={(ad_ids) => set("ads", { ad_ids })}
            empty="No Click-to-WhatsApp ads found yet. They appear once Meta Ads is connected and an ad has run."
            disabled={disabled}
          />
        )}
        <SegmentedControl
          aria-label="When the form goes for ad customers"
          value={triggers.ads.timing}
          disabled={disabled}
          onChange={(v) => set("ads", { timing: v })}
          options={TIMING_OPTIONS}
        />
      </Rule>

      <Rule
        icon={<Radio size={16} />}
        title="Replies to a broadcast"
        hint="When someone answers a broadcast sent with one of these templates. (To put the form inside the broadcast itself, add an Open form button to the template.)"
        on={triggers.broadcasts.enabled}
        onToggle={(v) => set("broadcasts", { enabled: v })}
        disabled={disabled}
      >
        <PickList
          items={(options?.templates ?? []).map((t) => ({ id: t, name: t }))}
          chosen={triggers.broadcasts.templates}
          onChange={(templates) => set("broadcasts", { templates })}
          empty="No approved templates yet."
          disabled={disabled}
        />
        <SegmentedControl
          aria-label="When the form goes for broadcast replies"
          value={triggers.broadcasts.timing}
          disabled={disabled}
          onChange={(v) => set("broadcasts", { timing: v })}
          options={TIMING_OPTIONS}
        />
      </Rule>
    </div>
  );
}

export function StatsLine({ stats }: { stats: { sent: number; submitted: number; paid: number | null } }) {
  const rate = stats.sent ? Math.round((stats.submitted / stats.sent) * 100) : null;
  return (
    <p className="font-body text-xs text-ink-muted tabular-nums">
      Sent {stats.sent} · Submitted {stats.submitted}
      {rate !== null && ` (${rate}%)`}
      {stats.paid !== null && ` · Paid ${stats.paid}`}
    </p>
  );
}
