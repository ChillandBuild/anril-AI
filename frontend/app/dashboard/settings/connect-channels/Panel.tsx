"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { fetchSettings, saveSettings, startRazorpayOAuth } from "./api";
import { CHANNELS, META_CHANNELS, buildSettingsUpdates, hasUnsavedChanges, isChannelConfigured as channelIsConfigured, resolveConnectionSource } from "./channels";
import type { ActivateResult, ChannelConfig, EmbeddedSignupTarget, SaveState, Setting, SettingsMap, WebhookHealth } from "./channels";
import { useMetaSignup } from "./useMetaSignup";
import { useMetaChannelSignup } from "./useMetaChannelSignup";
import { buildDisconnectTarget, disconnectChannel } from "./disconnect";
import type { DisconnectTarget } from "./disconnect";
import EmbeddedSection from "./EmbeddedSection";
import ManualSection from "./ManualSection";
import ChannelConfigModal from "./ChannelConfigModal";
import MetaAssetPickerModal from "./MetaAssetPickerModal";
import MetaChannelPickerModal from "./MetaChannelPickerModal";
import DisconnectDialog from "./DisconnectDialog";

export default function ConnectChannelsPanel({ canManage = true }: { canManage?: boolean }) {
  const [settings, setSettings] = useState<Setting[]>([]);
  const [drafts, setDrafts] = useState<SettingsMap>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [webhookHealth, setWebhookHealth] = useState<WebhookHealth | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [tenantId, setTenantId] = useState<string | null>(null);

  // Modal control
  const [selectedChannel, setSelectedChannel] = useState<ChannelConfig | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [activating, setActivating] = useState(false);
  const [activateResult, setActivateResult] = useState<ActivateResult | null>(null);

  // Disconnect flow
  const [disconnectTarget, setDisconnectTarget] = useState<DisconnectTarget | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);
  const [disconnectError, setDisconnectError] = useState<string | null>(null);

  const [razorpayBusy, setRazorpayBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const s = await fetchSettings();
      setSettings(s);
      setDrafts((prev) => {
        const next: SettingsMap = { ...prev };
        s.forEach((row) => {
          const isKnownField = CHANNELS.some(c => c.fields.some(f => f.key === row.key));
          if (isKnownField) {
            if (!row.is_secret) {
              const value = row.display_value === "Not set" ? "" : row.display_value;
              if (!(row.key in next) || next[row.key] === "") next[row.key] = value;
            } else {
              if (!(row.key in next)) next[row.key] = "";
            }
          }
        });
        return next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/settings/webhook-health`, { headers: auth });
      if (res.ok) setWebhookHealth(await res.json());
    } catch {} finally {
      setHealthLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    loadHealth();
    async function fetchTenantStatus() {
      try {
        const auth = await getAuthHeaders();
        const res = await fetch(`${API_URL}/api/v1/onboarding/status`, { headers: auth });
        if (res.ok) {
          const data = await res.json();
          if (data.tenant_id) setTenantId(data.tenant_id);
        }
      } catch {}
    }
    fetchTenantStatus();
  }, [load, loadHealth]);

  const meta = useMetaSignup({
    canManage,
    onConnected: async () => { await load(); loadHealth(); },
  });

  // Per-card signup for Page/Instagram and ads. Kept apart from `meta` because those
  // Login configurations are General, and only WhatsApp's variation posts the
  // WA_EMBEDDED_SIGNUP message that `meta` waits on before it can finish.
  const channelSignup = useMetaChannelSignup({
    canManage,
    onConnected: async () => { await load(); loadHealth(); },
  });

  const startEmbedded = useCallback((target: EmbeddedSignupTarget) => {
    if (target === "whatsapp") {
      meta.startWhatsAppOnly();
      return;
    }
    channelSignup.start(target);
  }, [meta, channelSignup]);

  // One busy marker across both hooks so a card can only launch one Meta window.
  const busyTarget: EmbeddedSignupTarget | null =
    meta.activeMode === "whatsapp_only" ? "whatsapp" : channelSignup.busyTarget;

  // Check if a channel's fields are completely set in DB
  // Optional fields must not gate activation. Counting them made the Instagram
  // App Secret mandatory in practice, and the only way to light the button back
  // up was pasting a secret that then broke webhook signature checks.
  const isChannelConfigured = useCallback((channel: ChannelConfig) => channelIsConfigured(channel, settings), [settings]);

  // Check if modal channel has drafts changes
  const isModalDirty = useMemo(
    () => (selectedChannel ? hasUnsavedChanges(selectedChannel.fields, drafts, settings) : false),
    [selectedChannel, drafts, settings],
  );

  async function handleSave() {
    if (!canManage) return;
    if (!selectedChannel) return;
    setSaveState("saving");
    setError(null);
    const updates = buildSettingsUpdates(selectedChannel.fields, drafts, settings);

    try {
      if (Object.keys(updates).length > 0) await saveSettings(updates);
      setDrafts(prev => {
        const next = { ...prev };
        if (selectedChannel) {
          selectedChannel.fields.forEach(f => delete next[f.key]);
        }
        return next;
      });
      await load();
      setSaveState("saved");
      setTimeout(() => setSaveState("idle"), 2500);
      loadHealth();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
      setSaveState("idle");
    }
  }

  async function handleActivate() {
    if (!canManage) return;
    if (!selectedChannel) return;
    setActivating(true);
    setActivateResult(null);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/settings/activate`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ channel: selectedChannel.id }),
      });
      const data = await res.json();
      if (!res.ok) {
        setActivateResult({ success: false, message: data.detail ?? "Activation failed" });
      } else {
        let detail = "";
        if (selectedChannel.id === "whatsapp") {
          detail = [
            data.business_name,
            data.phone_number,
            data.subscribed ? "Webhook subscribed ✓" : "Add WABA ID to enable webhook subscription",
          ].filter(Boolean).join(" · ");
        } else if (selectedChannel.id === "meta_ads") {
          detail = [
            data.account_name,
            data.account_id,
            data.currency,
            data.account_status === 1 ? "Account active" : `Account status: ${data.account_status ?? "unknown"}`,
          ].filter(Boolean).join(" · ");
        } else {
          detail = [
            data.page_name,
            data.page_id ? `ID: ${data.page_id}` : null,
            data.subscribed ? "Webhook subscribed ✓" : "Webhook subscription failed — check token scopes",
          ].filter(Boolean).join(" · ");
        }
        setActivateResult({ success: true, message: "Validated & connected", detail });
        await load();
        loadHealth();
      }
    } catch {
      setActivateResult({ success: false, message: "Network error — please try again" });
    } finally {
      setActivating(false);
    }
  }

  // Connect with Razorpay is a full-page redirect: Razorpay sends the browser back to
  // /dashboard/settings/razorpay-callback, which finishes the connection.
  async function startRazorpayConnect() {
    setRazorpayBusy(true);
    setError(null);
    try {
      window.location.assign(await startRazorpayOAuth());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the Razorpay connection");
      setRazorpayBusy(false);
    }
  }

  const openChannelModal = (channel: ChannelConfig) => {
    setSelectedChannel(channel);
    setSaveState("idle");
    setActivateResult(null);
  };

  const closeChannelModal = () => {
    setSelectedChannel(null);
  };

  const openDisconnect = (channelId: string) => {
    setDisconnectError(null);
    setDisconnectTarget(buildDisconnectTarget(channelId, settings));
  };

  async function handleDisconnect(releaseAssets: boolean) {
    if (!disconnectTarget) return;
    setDisconnecting(true);
    setDisconnectError(null);
    try {
      await disconnectChannel(disconnectTarget.channel, releaseAssets);
      setDisconnectTarget(null);
      setSelectedChannel(null);
      await load();
      loadHealth();
    } catch (e) {
      setDisconnectError(e instanceof Error ? e.message : "Disconnect failed");
    } finally {
      setDisconnecting(false);
    }
  }

  const metaConnected = META_CHANNELS.some(c => isChannelConfigured(c));

  return (
    <div className="mx-auto w-full max-w-[1440px] space-y-6 -mt-1 sm:-mt-2">
      {/* A per-card signup can fail before its picker exists — Meta granted nothing,
          or the code exchange was rejected — so that error needs a home up here. */}
      {(error || (channelSignup.error && !channelSignup.assets)) && (
        <div className="flex items-center gap-2 rounded-2xl border border-red-100 bg-red-50 p-3.5 text-red-700">
          <AlertCircle size={15} />
          <span className="font-body text-sm">{error || channelSignup.error}</span>
        </div>
      )}

      {loading ? (
        <div className="space-y-6">
          <div className="h-[420px] animate-pulse rounded-[28px] bg-border-subtle" />
          <div className="h-[380px] animate-pulse rounded-[28px] bg-border-subtle" />
        </div>
      ) : (
        <div className="space-y-6">
          <EmbeddedSection
            settings={settings}
            webhookHealth={webhookHealth}
            healthLoading={healthLoading}
            canManage={canManage}
            isBusy={meta.isBusy}
            error={meta.error}
            isConnected={metaConnected}
            activeMode={meta.activeMode}
            busyTarget={busyTarget}
            onConnect={meta.startStandard}
            onConnectCoexistence={meta.startCoexistence}
            onEmbeddedConnect={startEmbedded}
            onRefreshHealth={loadHealth}
            onManageChannel={openChannelModal}
            onDisconnect={openDisconnect}
          />
          <ManualSection
            settings={settings}
            webhookHealth={webhookHealth}
            healthLoading={healthLoading}
            canManage={canManage}
            busyTarget={busyTarget}
            onRefreshHealth={loadHealth}
            onOpenChannel={openChannelModal}
            onEmbeddedConnect={startEmbedded}
            razorpayBusy={razorpayBusy}
            onRazorpayConnect={startRazorpayConnect}
            onDisconnectChannel={openDisconnect}
          />
        </div>
      )}

      {meta.assets && (
        <MetaAssetPickerModal
          assets={meta.assets}
          selectedPageId={meta.selectedPageId}
          selectedAdAccountId={meta.selectedAdAccountId}
          onSelectPage={meta.setSelectedPageId}
          onSelectAdAccount={meta.setSelectedAdAccountId}
          onConfirm={meta.complete}
          onDismiss={meta.dismissAssets}
          isBusy={meta.isBusy}
          error={meta.error}
          canManage={canManage}
        />
      )}

      {channelSignup.assets && channelSignup.target && (
        <MetaChannelPickerModal
          target={channelSignup.target}
          assets={channelSignup.assets}
          selectedId={channelSignup.selectedId}
          onSelect={channelSignup.setSelectedId}
          onConfirm={channelSignup.complete}
          onDismiss={channelSignup.dismiss}
          isBusy={channelSignup.finishing}
          error={channelSignup.error}
          canManage={canManage}
        />
      )}

      {disconnectTarget && (
        <DisconnectDialog
          target={disconnectTarget}
          busy={disconnecting}
          error={disconnectError}
          onConfirm={handleDisconnect}
          onCancel={() => { setDisconnectTarget(null); setDisconnectError(null); }}
        />
      )}

      {selectedChannel && (
        <ChannelConfigModal
          channel={selectedChannel}
          settings={settings}
          drafts={drafts}
          tenantId={tenantId}
          canManage={canManage}
          configured={isChannelConfigured(selectedChannel)}
          isDirty={isModalDirty}
          saveState={saveState}
          activating={activating}
          activateResult={activateResult}
          webhookHealth={webhookHealth}
          connectionSource={resolveConnectionSource(selectedChannel.id, settings)}
          onDraftChange={(key, value) => setDrafts(prev => ({ ...prev, [key]: value }))}
          onSave={handleSave}
          onActivate={handleActivate}
          onClose={closeChannelModal}
        />
      )}
    </div>
  );
}
