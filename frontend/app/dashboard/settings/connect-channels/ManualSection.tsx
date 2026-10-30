"use client";
import { Sliders } from "lucide-react";
import { ZephyrCourier, timeAgo } from "./ui";
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
  razorpayBusy,
  onRazorpayConnect,
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
  razorpayBusy: boolean;
  onRazorpayConnect: () => void;
  onDisconnectChannel: (channelId: string) => void;
}) {
  return (
    <section className="overflow-hidden rounded-[28px] border border-primary-200/80 bg-white shadow-[0_12px_40px_rgba(var(--primary-600-rgb),0.08),0_2px_10px_rgba(0,0,0,0.04)] ring-1 ring-primary-100/50">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="grid items-center gap-6 border-b border-primary-100 bg-gradient-to-r from-primary-50 via-white to-primary-50/40 px-6 py-5 sm:grid-cols-[1fr_auto] sm:gap-8 sm:px-8 sm:py-5.5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-primary-200/90 bg-primary-50/90 px-3 py-1 font-label text-[10.5px] font-bold uppercase tracking-[0.14em] text-primary shadow-sm">
              <Sliders size={12} className="text-primary" />
              Manual API Connection
            </span>
            <span className="inline-flex items-center rounded-full bg-primary-600 px-2.5 py-0.5 font-label text-[10px] font-bold uppercase tracking-wider text-white shadow-sm">
              Advanced
            </span>
          </div>

          <h2 className="mt-2.5 font-display text-xl font-bold leading-tight text-ink sm:text-[22px]">
            Bring your own tokens
          </h2>
          <p className="mt-1.5 max-w-2xl font-body text-xs leading-relaxed text-ink-muted sm:text-[13px]">
            Use your own Business Account ID, permanent access tokens and webhook controls.
            Telegram and Razorpay are configured here only.
          </p>
        </div>

        <div className="hidden shrink-0 self-center justify-self-end sm:block -my-3 sm:-my-4">
          <ZephyrCourier
            variant="manual"
            compact
            className="!h-32 !w-48 sm:!h-36 sm:!w-56"
            imageClassName="scale-105 origin-center"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 p-5 sm:p-7 md:grid-cols-2 lg:grid-cols-3">
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
              embeddedBusy={channel.id === "razorpay" ? razorpayBusy : Boolean(embeddedTarget) && busyTarget === embeddedTarget}
              onRefreshHealth={onRefreshHealth}
              onOpen={() => onOpenChannel(channel)}
              onEmbeddedConnect={
                channel.id === "razorpay" ? onRazorpayConnect : embeddedTarget ? () => onEmbeddedConnect(embeddedTarget) : undefined
              }
              connectLabel={channel.id === "razorpay" ? "Connect with Razorpay" : undefined}
              connectedLabel={razorpayAccount ? "Connected via Razorpay" : undefined}
              onDisconnect={() => onDisconnectChannel(channel.id)}
            />
          );
        })}
      </div>
    </section>
  );
}
