"use client";
import { timeAgo } from "./ui";
import ChannelCard from "./ChannelCard";
import { CHANNELS, EMBEDDED_SIGNUP_TARGETS, isChannelConfigured, razorpayOAuthAccount, resolveConnectionSource } from "./channels";
import type { ChannelConfig, EmbeddedSignupTarget, Setting, WebhookHealth } from "./channels";

export default function ManualSection({
  settings,
  webhookHealth,
  healthLoading,
  canManage,
  busyTarget,
  onRefreshHealth,
  onOpenChannel,
  onEmbeddedConnect,
  onDisconnectChannel,
}: {
  settings: Setting[];
  webhookHealth: WebhookHealth | null;
  healthLoading: boolean;
  canManage: boolean;
  busyTarget: EmbeddedSignupTarget | null;
  onRefreshHealth: () => void;
  onOpenChannel: (channel: ChannelConfig) => void;
  onEmbeddedConnect: (target: EmbeddedSignupTarget) => void;
  onDisconnectChannel: (channelId: string) => void;
}) {
  return (
    <section aria-label="Advanced: your own API keys and webhooks">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {CHANNELS.map(channel => {
          const configured = isChannelConfigured(channel, settings);
          const razorpayAccount = channel.id === "razorpay" ? razorpayOAuthAccount(settings) : null;
          const health = webhookHealth?.health?.[channel.id];
          const alert = webhookHealth?.token_alerts?.find(a => a.channel === channel.id);
          const source = resolveConnectionSource(channel.id, settings);
          const statusSetting = settings.find(s => s.key === `${channel.id}_status`);
          const isLive = !channel.hasActivation || statusSetting?.display_value === "live" || Boolean(health?.last_event);
          const adsAccountName = settings.find(s => s.key === "meta_ads_account_name")?.display_value;
          const adsLastSync = settings.find(s => s.key === "meta_ads_last_sync_at")?.display_value;

          const metadata =
            razorpayAccount
              ? `Razorpay account ${razorpayAccount}`
              : channel.id === "meta_ads"
                ? [
                    adsAccountName && adsAccountName !== "Not set" ? adsAccountName : "Ads account connected",
                    adsLastSync && adsLastSync !== "Not set" ? `Synced ${timeAgo(adsLastSync)}` : null,
                  ].filter(Boolean).join(" · ")
                : health?.last_event
                  ? `Active event: ${timeAgo(health.last_event)}`
                  : "No events received yet";

          const embeddedTarget = EMBEDDED_SIGNUP_TARGETS[channel.id];

          return (
            <ChannelCard
              key={channel.id}
              channel={channel}
              configured={configured}
              isLive={isLive}
              hasTokenAlert={Boolean(alert)}
              source={source}
              metadata={metadata}
              healthLoading={healthLoading}
              canManage={canManage}
              embeddedBusy={Boolean(embeddedTarget) && busyTarget === embeddedTarget}
              onRefreshHealth={onRefreshHealth}
              onOpen={() => onOpenChannel(channel)}
              onEmbeddedConnect={
                channel.id === "razorpay" ? undefined : embeddedTarget ? () => onEmbeddedConnect(embeddedTarget) : undefined
              }
              connectedLabel={razorpayAccount ? "Connected via Razorpay" : undefined}
              onDisconnect={() => onDisconnectChannel(channel.id)}
            />
          );
        })}
      </div>
    </section>
  );
}
