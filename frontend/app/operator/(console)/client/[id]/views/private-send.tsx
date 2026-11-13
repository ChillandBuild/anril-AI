"use client";
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2, Lock } from "lucide-react";
import { toast } from "sonner";
import {
  PRIVATE_SEND_GRACE_HOURS,
  PRIVATE_SEND_TIERS,
  capForTier,
  getPrivateSend,
  tierForCap,
  updatePrivateSendSettings,
  type PrivateSendTier,
} from "@/lib/operator";
import { Select } from "@/components/ui/Select";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { OperatorToggle } from "../../../components/operator-toggle";
import { SkeletonCard } from "../components/skeleton";
import { PrivateSendKeys } from "./private-send-keys";
import { PrivateSendUsagePanel } from "./private-send-usage";
import type { PrivateSendOverview, PrivateSendReplyMode, PrivateSendSettingsPatch } from "../types";

const FEATURE_KEY = "private_send";
const META_REJECTED_STATUS = 502;
const META_REJECTED_MESSAGE = "Meta didn't accept the change; nothing was saved.";

const selectCls =
  "w-full rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink outline-none transition-colors focus:border-primary disabled:opacity-60";

const REPLY_OPTIONS: { id: PrivateSendReplyMode; title: string; desc: string }[] = [
  { id: "client", title: "Client's system", desc: "Anril never sees replies or numbers" },
  { id: "aira", title: "Anril AI answers", desc: "replies come to Anril's inbox, so Anril sees the number of anyone who replies" },
];

interface Props {
  tenantId: string;
  enabledFeatures: string[];
  onToggleFeature: (feature: string) => void;
  featureUpdating: boolean;
}

export function PrivateSendView({ tenantId, enabledFeatures, onToggleFeature, featureUpdating }: Props) {
  const featureOn = enabledFeatures.includes(FEATURE_KEY);
  const [data, setData] = useState<PrivateSendOverview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [replyError, setReplyError] = useState<string | null>(null);
  const [tier, setTier] = useState<PrivateSendTier>("none");
  const [customCap, setCustomCap] = useState("");

  const syncCapDraft = useCallback((cap: number | null) => {
    setTier(tierForCap(cap));
    setCustomCap(cap !== null && tierForCap(cap) === "custom" ? String(cap) : "");
  }, []);

  const reload = useCallback(async () => {
    try {
      const next = await getPrivateSend(tenantId);
      setData(next);
      syncCapDraft(next.monthly_cap);
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to load Private Send");
    }
  }, [tenantId, syncCapDraft]);

  useEffect(() => {
    if (!featureOn) {
      setData(null);
      return;
    }
    reload();
  }, [featureOn, reload]);

  async function save(key: string, patch: PrivateSendSettingsPatch) {
    setSaving(key);
    try {
      const next = await updatePrivateSendSettings(tenantId, patch);
      setData(next);
      syncCapDraft(next.monthly_cap);
      return true;
    } catch (e) {
      const status = (e as { status?: number }).status;
      const message = status === META_REJECTED_STATUS ? META_REJECTED_MESSAGE : e instanceof Error ? e.message : "Failed to save";
      if (key === "reply_mode") setReplyError(message);
      else toast.error(message);
      return false;
    } finally {
      setSaving(null);
    }
  }

  function changeReplyMode(mode: PrivateSendReplyMode) {
    if (!data || data.reply_mode === mode || saving) return;
    setReplyError(null);
    save("reply_mode", { reply_mode: mode });
  }

  const nextCap = capForTier(tier, customCap);
  const capDirty = data !== null && nextCap !== undefined && nextCap !== data.monthly_cap;

  return (
    <div className="space-y-6">
      <div className="rounded-card border border-border bg-white p-4 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="flex items-center gap-2 text-sm font-semibold text-ink">
              <Lock size={16} className="text-ink-muted" />
              Private Send
            </p>
            <p className="mt-1 text-xs leading-relaxed text-ink-muted">
              The client&apos;s own server sends the WhatsApp templates, so Anril never sees lead names or numbers.
              Anril controls the license, the monthly cap, reply routing and offline grace.
            </p>
          </div>
          <OperatorToggle
            checked={featureOn}
            onChange={() => onToggleFeature(FEATURE_KEY)}
            loading={featureUpdating}
            aria-label="Toggle Private Send"
          />
        </div>
      </div>

      {!featureOn && <p className="text-xs text-ink-muted">Turn Private Send on to manage keys, the cap and usage.</p>}

      {featureOn && loadError && (
        <div className="rounded-xl border border-danger/20 bg-red-50 p-4 text-sm text-danger">{loadError}</div>
      )}

      {featureOn && !data && !loadError && (
        <div className="grid grid-cols-2 gap-4">
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {featureOn && data && (
        <>
          <div>
            <h3 className="mb-3 text-sm font-semibold text-ink">Plan tier</h3>
            <div className="rounded-card border border-border bg-white p-4 shadow-sm">
              <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
                <label className="block">
                  <span className="mb-1.5 block text-xs font-medium text-ink-muted">Monthly sends</span>
                  <Select
                    value={tier}
                    onChange={(v) => setTier(v as PrivateSendTier)}
                    disabled={saving === "cap"}
                    options={PRIVATE_SEND_TIERS.map((t) => ({ value: t.id, label: t.label }))}
                  />
                </label>
                {tier === "custom" && (
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-medium text-ink-muted">Custom cap</span>
                    <input
                      type="number"
                      inputMode="numeric"
                      min={1}
                      value={customCap}
                      onChange={(e) => setCustomCap(e.target.value)}
                      placeholder="e.g. 25000"
                      className={selectCls}
                    />
                  </label>
                )}
                <button
                  type="button"
                  onClick={() => nextCap !== undefined && save("cap", { monthly_cap: nextCap })}
                  disabled={!capDirty || saving === "cap"}
                  className="inline-flex items-center justify-center gap-1.5 rounded-full bg-primary px-4 py-2 font-label text-xs font-bold text-white shadow-sm transition-all hover:bg-primary/90 disabled:opacity-50"
                >
                  {saving === "cap" ? <Loader2 size={13} className="animate-spin" /> : "Save cap"}
                </button>
              </div>
              {tier === "custom" && nextCap === undefined && (
                <p className="mt-2 text-xs text-warning">Enter a whole number above zero.</p>
              )}
            </div>
          </div>

          <PrivateSendKeys tenantId={tenantId} keys={data.keys} onChanged={reload} />

          <div>
            <h3 className="mb-3 text-sm font-semibold text-ink">When a customer replies</h3>
            <div role="radiogroup" aria-label="When a customer replies" className="grid gap-4 md:grid-cols-2">
              {REPLY_OPTIONS.map((o) => {
                const selected = data.reply_mode === o.id;
                return (
                  <button
                    key={o.id}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() => changeReplyMode(o.id)}
                    disabled={saving === "reply_mode"}
                    className={`rounded-card border p-4 text-left shadow-sm transition-all ${
                      selected ? "border-primary bg-primary-light ring-1 ring-primary/10" : "border-border bg-white hover:border-primary-muted"
                    } ${saving === "reply_mode" ? "opacity-70" : ""}`}
                  >
                    <p className="flex items-center gap-2 text-sm font-semibold text-ink">
                      {o.title}
                      {saving === "reply_mode" && !selected && <Loader2 size={13} className="animate-spin" />}
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-ink-muted">{o.desc}</p>
                  </button>
                );
              })}
            </div>
            {data.reply_mode === "aira" && (
              <div className="mt-3 flex items-start gap-2 rounded-xl border border-warning/30 bg-warning/10 p-3 text-xs text-warning">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                <p>Replies come to Anril&apos;s inbox, so Anril sees the number of anyone who replies.</p>
              </div>
            )}
            {replyError && (
              <p role="alert" className="mt-3 rounded-xl border border-danger/20 bg-red-50 p-3 text-xs text-danger">{replyError}</p>
            )}
          </div>

          <div>
            <h3 className="mb-3 text-sm font-semibold text-ink">Offline grace</h3>
            <div className="rounded-card border border-border bg-white p-4 shadow-sm">
              <div className="max-w-md">
                <span id="offline-grace-label" className="mb-1.5 block text-xs font-medium text-ink-muted">Keep sending after the plug-in last checked in for</span>
                <SegmentedControl
                  aria-labelledby="offline-grace-label"
                  value={String(data.offline_grace_hours)}
                  onChange={(v) => save("grace", { offline_grace_hours: Number(v) })}
                  disabled={saving === "grace"}
                  options={PRIVATE_SEND_GRACE_HOURS.map((h) => ({ value: String(h), label: `${h} ${h === 1 ? "hour" : "hours"}` }))}
                />
              </div>
            </div>
          </div>

          <PrivateSendUsagePanel usage={data.usage} cap={data.monthly_cap} />
        </>
      )}
    </div>
  );
}
