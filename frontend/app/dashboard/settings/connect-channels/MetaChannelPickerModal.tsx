"use client";
import { X, Loader2, ArrowRight } from "lucide-react";
import { Portal } from "./ui";
import { Select } from "@/components/ui/Select";
import { assetOptions } from "./useMetaChannelSignup";
import type { MetaChannelAdAccount, MetaChannelAssets, MetaChannelPage, MetaChannelTarget } from "./useMetaChannelSignup";

const COPY: Record<MetaChannelTarget, { title: string; blurb: string; label: string; hint: string; cta: string }> = {
  page: {
    title: "Choose your Facebook Page",
    blurb: "Messenger connects to this Page. If an Instagram business account is linked to it, Instagram DM connects at the same time.",
    label: "Facebook Page",
    hint: "Anril subscribes this Page to message webhooks so replies reach your inbox.",
    cta: "Connect Page",
  },
  ads: {
    title: "Choose your ad account",
    blurb: "Anril reads Click-to-WhatsApp performance from this account. It cannot create, edit, or publish ads.",
    label: "Ad account",
    hint: "Read-only reporting access. Spend, delivery and attribution sync nightly.",
    cta: "Connect ad account",
  },
};

function optionLabel(option: MetaChannelPage | MetaChannelAdAccount): string {
  if ("instagram_business_account" in option && option.instagram_business_account) {
    const username = option.instagram_business_account.username;
    return `${option.name} · Instagram${username ? ` @${username}` : ""} linked`;
  }
  const account = option as MetaChannelAdAccount;
  return [option.name, account.account_id, account.currency].filter(Boolean).join(" · ");
}

export default function MetaChannelPickerModal({
  target,
  assets,
  selectedId,
  onSelect,
  onConfirm,
  onDismiss,
  isBusy,
  error,
  canManage,
}: {
  target: MetaChannelTarget;
  assets: MetaChannelAssets;
  selectedId: string;
  onSelect: (id: string) => void;
  onConfirm: () => void;
  onDismiss: () => void;
  isBusy: boolean;
  error: string | null;
  canManage: boolean;
}) {
  const copy = COPY[target];
  const options = assetOptions(target, assets);

  return (
    <Portal>
      <div className="fixed inset-0 z-dialog flex items-center justify-center bg-black/45 p-4 backdrop-blur-[3px]">
        <div className="w-full max-w-xl overflow-hidden rounded-card bg-surface shadow-card ring-1 ring-[#c4c7c7]/20">
          <div className="flex items-start justify-between border-b border-border-subtle p-6">
            <div>
              <h2 className="font-display text-lg font-bold text-ink">{copy.title}</h2>
              <p className="mt-1 font-body text-xs text-ink-muted">{copy.blurb}</p>
            </div>
            <button
              type="button"
              onClick={onDismiss}
              className="rounded-lg p-1.5 text-on-surface-muted transition-colors hover:bg-surface-low hover:text-on-surface"
              aria-label="Close Meta asset selection"
            >
              <X size={18} />
            </button>
          </div>

          <div className="max-h-[70vh] space-y-5 overflow-y-auto p-6">
            {error && <p className="rounded-xl bg-red-50 px-3 py-2 font-body text-xs text-red-700">{error}</p>}
            <label className="block">
              <span className="font-label text-xs font-bold uppercase tracking-wider text-ink">{copy.label}</span>
              <Select
                value={selectedId}
                onChange={onSelect}
                className="mt-2"
                disabled={isBusy}
                placeholder="Select one to continue"
                options={options.map(option => ({ value: option.id, label: optionLabel(option) }))}
              />
              <p className="mt-1.5 font-body text-[11px] text-ink-muted">{copy.hint}</p>
            </label>
          </div>

          <div className="flex items-center justify-between gap-3 border-t border-border-subtle bg-surface-low p-5">
            <button
              type="button"
              onClick={onDismiss}
              className="rounded-xl px-3 py-2 font-label text-sm font-semibold text-ink-muted hover:bg-white"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={onConfirm}
              disabled={!canManage || isBusy || !selectedId}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-br from-[var(--primary-950)] to-primary px-4 py-2.5 font-label text-sm font-bold text-white transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isBusy ? <><Loader2 size={16} className="animate-spin" />Connecting…</> : <>{copy.cta} <ArrowRight size={16} /></>}
            </button>
          </div>
        </div>
      </div>
    </Portal>
  );
}
