"use client";
import { Check, Loader2, Sparkles, Smartphone, Activity, MessageSquare, Building2, Megaphone, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { ZephyrCourier, timeAgo, FacebookIcon } from "./ui";
import { CHANNELS, META_CHANNELS, isChannelConfigured, razorpayOAuthAccount } from "./channels";
import type { ChannelConfig, EmbeddedSignupTarget, Setting, WebhookHealth } from "./channels";
import type { MetaSignupMode } from "./metaSignupMode";

const VALUE_PROPS: Array<{ title: string; detail: string }> = [
  { title: "Secure one-click connection", detail: "Authorise once in Meta — no tokens to copy or paste" },
  { title: "Official WhatsApp Cloud API", detail: "Templates, broadcasts and delivery reporting" },
  { title: "Number and webhook linked for you", detail: "Anril subscribes your WABA automatically" },
];

/**
 * What a channel is actually doing, replacing the old single `isLive` flag.
 *
 * `isLive` was true when credentials merely existed, so Messenger could show
 * "Live" directly above "No events received yet". These five states never
 * contradict their own subtext, and Meta Ads gets its own word because it is
 * polled on a schedule rather than driven by webhooks.
 */
type ChannelState = "receiving" | "waiting" | "synced" | "attention" | "off";

const STATE_STYLES: Record<ChannelState, string> = {
  receiving: "text-emerald-600",
  waiting: "text-amber-600",
  synced: "text-primary-600",
  attention: "text-rose-600",
  off: "text-ink-muted",
};

const DOT_STYLES: Record<ChannelState, string> = {
  receiving: "bg-emerald-500",
  waiting: "bg-amber-500",
  synced: "bg-primary-500",
  attention: "bg-rose-500",
  off: "bg-ink-muted",
};

const RAIL_STYLES: Record<string, string> = {
  whatsapp: "bg-emerald-500",
  instagram: "bg-pink-500",
  facebook: "bg-blue-500",
  meta_ads: "bg-primary-500",
  razorpay: "bg-indigo-500",
};

const RAZORPAY_CHANNEL = CHANNELS.find(c => c.id === "razorpay");

export default function EmbeddedSection({
  settings,
  webhookHealth,
  healthLoading,
  canManage,
  isBusy,
  error,
  isConnected,
  activeMode,
  onConnect,
  onConnectCoexistence,
  onRefreshHealth,
  onManageChannel,
  onDisconnect,
  razorpayConnected,
  razorpayBusy,
  onRazorpayConnect,
}: {
  settings: Setting[];
  webhookHealth: WebhookHealth | null;
  healthLoading: boolean;
  canManage: boolean;
  isBusy: boolean;
  error: string | null;
  isConnected: boolean;
  activeMode: MetaSignupMode | null;
  busyTarget: EmbeddedSignupTarget | null;
  onConnect: () => void;
  onConnectCoexistence: () => void;
  onEmbeddedConnect: (target: EmbeddedSignupTarget) => void;
  onRefreshHealth: () => void;
  onManageChannel: (channel: ChannelConfig) => void;
  onDisconnect: (channelId: string) => void;
  razorpayConnected: boolean;
  razorpayBusy: boolean;
  onRazorpayConnect: () => void;
}) {
  // Razorpay sits beside the Meta actions so both payments and messaging connect from one place.
  const razorpayAction = razorpayConnected ? (
    <button
      type="button"
      onClick={() => onDisconnect("razorpay")}
      disabled={!canManage}
      className="font-label text-xs font-bold text-red-600 underline decoration-red-300 underline-offset-4 transition-colors hover:text-red-700 hover:decoration-red-600 disabled:cursor-not-allowed disabled:opacity-60"
    >
      Disconnect Razorpay
    </button>
  ) : (
    <button
      type="button"
      onClick={onRazorpayConnect}
      disabled={!canManage || razorpayBusy}
      className="relative inline-flex items-center gap-2 rounded-[10px] bg-gradient-to-r from-[#3b0f79] via-[var(--primary-800)] to-[var(--primary-600)] px-3.5 py-2 font-label text-xs font-bold text-white shadow-[0_0_16px_-3px_rgba(var(--primary-600-rgb),0.45),0_2px_4px_rgba(var(--primary-950-rgb),0.2)] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_24px_rgba(var(--primary-600-rgb),0.65),0_4px_12px_rgba(var(--primary-950-rgb),0.3)] disabled:cursor-not-allowed disabled:opacity-60"
    >
      {razorpayBusy ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={13} />}
      Connect with Razorpay
    </button>
  );

  /** A settings value, or null when the row is missing or never set. */
  function val(key: string): string | null {
    const row = settings.find(s => s.key === key);
    if (!row?.is_set) return null;
    const value = row.display_value;
    return value && value !== "Not set" ? value : null;
  }

  const phoneDisplay = val("meta_phone_display") ?? val("meta_phone_number_id");
  const verifiedName = val("meta_verified_name");
  const wabaId = val("meta_waba_id");
  const pageName = val("facebook_page_name") ?? val("facebook_page_id");
  const igUsername = val("instagram_username");
  const adsName = val("meta_ads_account_name");
  const adsId = val("meta_ads_account_id");
  const connectedAt = val("meta_connected_at");

  function isConfigured(channel: ChannelConfig) {
    return isChannelConfigured(channel, settings);
  }

  /** The Meta asset a channel is bound to — the question the old card never answered. */
  function assetFor(channel: ChannelConfig): { id: string | null; label: string | null } {
    switch (channel.id) {
      case "whatsapp":
        return { id: phoneDisplay, label: verifiedName };
      case "instagram":
        return { id: igUsername ? `@${igUsername}` : val("instagram_page_id"), label: "via linked Page" };
      case "facebook":
        return { id: pageName, label: null };
      case "meta_ads":
        return { id: adsId, label: adsName };
      case "razorpay":
        return { id: razorpayOAuthAccount(settings) ?? val("razorpay_key_id"), label: null };
      default:
        return { id: null, label: null };
    }
  }

  function statusFor(channel: ChannelConfig): { state: ChannelState; label: string; detail: string } {
    if (!isConfigured(channel)) return { state: "off", label: "Not connected", detail: "Not connected yet" };

    if (webhookHealth?.token_alerts?.some(a => a.channel === channel.id)) {
      return { state: "attention", label: "Needs attention", detail: "Token rejected by Meta" };
    }

    if (channel.id === "razorpay") {
      return { state: "synced", label: "Connected", detail: "Accepts in-chat payments" };
    }

    // Meta Ads is polled on a schedule, so "no events" would read as broken.
    if (channel.id === "meta_ads") {
      const lastSync = val("meta_ads_last_sync_at");
      return lastSync
        ? { state: "synced", label: "Synced", detail: `Click-to-WhatsApp · ${timeAgo(lastSync)}` }
        : { state: "waiting", label: "Awaiting sync", detail: "Connected · first sync pending" };
    }

    const lastEvent = webhookHealth?.health?.[channel.id]?.last_event;
    if (lastEvent) {
      return { state: "receiving", label: "Receiving", detail: `Last message ${timeAgo(lastEvent)}` };
    }
    return { state: "waiting", label: "Awaiting first", detail: "Connected · nothing received yet" };
  }

  const rowChannels = RAZORPAY_CHANNEL ? [...META_CHANNELS, RAZORPAY_CHANNEL] : META_CHANNELS;
  const connectedCount = rowChannels.filter(isConfigured).length;

  return (
    <section
      className={cn(
        "overflow-hidden rounded-[20px] border bg-white transition-all duration-300",
        isConnected
          ? "border-emerald-500/25 shadow-[0_4px_24px_-4px_rgba(16,185,129,0.14),0_1px_3px_rgba(0,0,0,0.04)] ring-1 ring-emerald-500/10"
          : "border-border shadow-card"
      )}
    >
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div
        className={cn(
          "grid items-center gap-6 px-6 pt-2.5 pb-3 sm:grid-cols-[1fr_auto] sm:gap-8 sm:px-8 sm:pt-3 sm:pb-3.5 transition-colors duration-300",
          isConnected
            ? "bg-gradient-to-b from-emerald-50/70 via-[#f8fdfa] to-white"
            : "bg-gradient-to-b from-[#f8f5ff]/70 via-[#fcfbff] to-white"
        )}
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-label text-[10.5px] font-bold uppercase tracking-[0.14em] shadow-sm transition-colors",
                isConnected
                  ? "border-emerald-200/90 bg-emerald-50/90 text-emerald-700"
                  : "border-primary-200/90 bg-primary-50/90 text-primary"
              )}
            >
              <Activity size={12} className={isConnected ? "text-emerald-600" : "text-primary"} />
              Connectivity Hub
            </span>
            {!isConnected && (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-primary-500/30 bg-primary-50/90 px-2.5 py-1 font-label text-[10.5px] font-bold uppercase tracking-wider text-primary-700 shadow-[0_0_12px_rgba(var(--primary-500-rgb),0.32)]">
                <Sparkles size={11} className="animate-pulse text-primary-600" />
                Recommended
              </span>
            )}
          </div>

          <h2 className="mt-2.5 font-display text-[26px] font-bold leading-[1.15] tracking-tight text-ink">
            {isConnected ? verifiedName ?? "Meta Business" : "Connect Meta Business"}
          </h2>
          {isConnected ? (
            <p className="mt-2 max-w-[70ch] font-body text-[13px] leading-relaxed text-ink-secondary">
              WhatsApp, Messenger, Instagram and Click-to-WhatsApp ad reporting, through one Meta connection.
            </p>
          ) : (
            <div className="mt-3 grid gap-3 max-w-[90ch] sm:grid-cols-2 sm:gap-6">
              <div className="flex items-start gap-2.5 font-body text-[13px] leading-relaxed text-ink-secondary">
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                <span>One secure connection brings WhatsApp, Messenger, Instagram and Click-to-WhatsApp ad reporting into Anril.</span>
              </div>
              <div className="flex items-start gap-2.5 font-body text-[13px] leading-relaxed text-ink-secondary">
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-primary-400" />
                <span><strong className="font-semibold text-ink">Prefer using your phone?</strong> WhatsApp Coexistence keeps your existing WhatsApp Business mobile app active while syncing with Anril.</span>
              </div>
            </div>
          )}

          {error && (
            <p className="mt-4 rounded-xl bg-red-50 px-4 py-3 font-body text-sm text-red-700">{error}</p>
          )}

          {isConnected ? (
            <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2.5">
              <span className="inline-flex items-center gap-2 font-label text-xs font-bold text-emerald-600">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                Connected{connectedAt ? ` · ${timeAgo(connectedAt)}` : ""}
              </span>
              <button
                type="button"
                onClick={onConnect}
                disabled={!canManage || isBusy}
                title="Refresh permissions and re-pick assets"
                className="relative inline-flex items-center gap-2 rounded-[10px] bg-gradient-to-r from-[#3b0f79] via-[var(--primary-800)] to-[var(--primary-600)] px-3.5 py-2 font-label text-xs font-bold text-white shadow-[0_0_16px_-3px_rgba(var(--primary-600-rgb),0.45),0_2px_4px_rgba(var(--primary-950-rgb),0.2)] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_24px_rgba(var(--primary-600-rgb),0.65),0_4px_12px_rgba(var(--primary-950-rgb),0.3)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isBusy && activeMode === "standard" && <Loader2 size={12} className="animate-spin text-white" />}
                Reconnect Meta Business
              </button>
              <button
                type="button"
                onClick={onConnectCoexistence}
                disabled={!canManage || isBusy}
                title="Keep the WhatsApp mobile app working alongside Anril"
                className="inline-flex items-center gap-2 rounded-[10px] border border-border bg-white px-3.5 py-2 font-label text-xs font-bold text-ink shadow-sm transition-all hover:-translate-y-px hover:border-primary/40 hover:text-primary hover:shadow-[0_4px_12px_-5px_rgba(var(--primary-800-rgb),0.28)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isBusy && activeMode === "coexistence" && <Loader2 size={12} className="animate-spin" />}
                <Smartphone size={13} className="text-ink-secondary" />
                Switch to Coexistence
              </button>
              <button
                type="button"
                onClick={() => onDisconnect("meta")}
                disabled={!canManage || isBusy}
                className="font-label text-xs font-bold text-red-600 underline decoration-red-300 underline-offset-4 transition-colors hover:text-red-700 hover:decoration-red-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Disconnect Meta
              </button>
              {razorpayAction}
            </div>
          ) : (
            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={onConnect}
                disabled={!canManage || isBusy}
                className="relative inline-flex items-center gap-2 rounded-[11px] bg-gradient-to-r from-[#3b0f79] via-[var(--primary-800)] to-[var(--primary-600)] px-5 py-2.5 font-label text-[13px] font-bold text-white shadow-[0_0_20px_-3px_rgba(var(--primary-600-rgb),0.45),0_2px_4px_rgba(var(--primary-950-rgb),0.2)] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_28px_rgba(var(--primary-600-rgb),0.65),0_6px_16px_rgba(var(--primary-950-rgb),0.3)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isBusy && activeMode === "standard" && <Loader2 size={14} className="animate-spin" />}
                Connect Meta Business
              </button>

              <button
                type="button"
                onClick={onConnectCoexistence}
                disabled={!canManage || isBusy}
                className="inline-flex items-center gap-2 rounded-[11px] border border-border bg-white px-4 py-2.5 font-label text-[13px] font-bold text-ink shadow-sm transition-all hover:-translate-y-px hover:border-primary/40 hover:text-primary hover:shadow-[0_4px_12px_-5px_rgba(var(--primary-800-rgb),0.25)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isBusy && activeMode === "coexistence" && <Loader2 size={14} className="animate-spin" />}
                <Smartphone size={13} className="text-ink-secondary" />
                WhatsApp Coexistence
              </button>
              {razorpayAction}
            </div>
          )}
        </div>

        <div className="relative hidden shrink-0 self-center justify-self-end sm:block -my-2.5 sm:-my-4">
          {isConnected && (
            <div className="pointer-events-none absolute -inset-6 rounded-full bg-emerald-400/20 blur-2xl -z-10" />
          )}
          <ZephyrCourier
            variant="embedded"
            compact
            className="!h-48 !w-48 sm:!h-52 sm:!w-52 lg:!h-56 lg:!w-56"
            imageClassName={cn(
              "scale-[1.12] sm:scale-[1.15] origin-center transition-all duration-300",
              isConnected && "drop-shadow-[0_6px_20px_rgba(16,185,129,0.22)]"
            )}
          />
        </div>
      </div>

      {/* ── Account strip / value props ────────────────────────────────── */}
      {isConnected ? (
        <dl className="grid border-y border-border-subtle bg-gradient-to-r from-emerald-50/50 via-[#f9fcf9] to-primary-50/40 sm:grid-cols-2 lg:grid-cols-4">
          <StripCell
            icon={MessageSquare}
            iconBg="bg-emerald-100/90 text-emerald-700 ring-1 ring-emerald-400/25"
            cellBg="hover:bg-gradient-to-br hover:from-emerald-50/70 hover:to-white"
            label="WhatsApp number"
            value={phoneDisplay}
            detail={
              verifiedName ? (
                <span className="inline-flex items-center gap-1 font-semibold text-emerald-700">
                  <CheckCircle2 size={11} className="text-emerald-600" />
                  {verifiedName} · verified
                </span>
              ) : null
            }
          />
          <StripCell
            icon={Building2}
            iconBg="bg-teal-100/90 text-teal-700 ring-1 ring-teal-400/25"
            cellBg="hover:bg-gradient-to-br hover:from-teal-50/70 hover:to-white"
            label="WhatsApp Business account"
            value={wabaId}
            detail={
              <span className="inline-flex items-center gap-1.5 font-semibold text-teal-700">
                <span className="h-1.5 w-1.5 rounded-full bg-teal-500 animate-pulse" />
                Webhook subscribed
              </span>
            }
            mono
          />
          <StripCell
            icon={FacebookIcon}
            iconBg="bg-blue-100/90 text-blue-600 ring-1 ring-blue-400/25"
            cellBg="hover:bg-gradient-to-br hover:from-blue-50/70 hover:to-white"
            label="Facebook Page"
            value={pageName}
            detail={
              <span className="font-semibold text-blue-700">
                {igUsername ? `Messenger + Instagram @${igUsername}` : "Messenger"}
              </span>
            }
          />
          <StripCell
            icon={Megaphone}
            iconBg="bg-primary-100/90 text-primary-600 ring-1 ring-primary-400/25"
            cellBg="hover:bg-gradient-to-br hover:from-primary-50/70 hover:to-white"
            label="Ad account"
            value={adsName}
            detail={
              adsId ? (
                <span className="font-mono text-[11px] font-semibold text-primary-700">
                  {adsId}
                </span>
              ) : null
            }
            detailMono
          />
        </dl>
      ) : (
        <div className="grid border-y border-border-subtle bg-[#fdfcfa] sm:grid-cols-3">
          {VALUE_PROPS.map((prop, i) => (
            <div
              key={prop.title}
              className={cn(
                "flex items-start gap-3 px-6 py-4 sm:px-8",
                i > 0 && "border-t border-border-subtle sm:border-l sm:border-t-0"
              )}
            >
              <Check size={14} className="mt-0.5 shrink-0 text-primary" strokeWidth={2.6} />
              <div className="min-w-0">
                <p className="font-label text-[13px] font-bold leading-snug text-ink">{prop.title}</p>
                <p className="mt-1 font-body text-[11.5px] leading-snug text-ink-secondary">{prop.detail}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Channels ───────────────────────────────────────────────────── */}
      <div className="px-6 pb-2 pt-5 sm:px-8">
        <div className="mb-1 flex items-baseline justify-between gap-3">
          <span className="font-label text-[9.5px] font-bold uppercase tracking-[0.15em] text-ink-muted">
            Channels
          </span>
          <span className="font-label text-[9.5px] font-bold uppercase tracking-[0.15em] text-ink-muted">
            {connectedCount > 0 ? `${connectedCount} connected` : "None connected yet"}
          </span>
        </div>

        <div className="flex flex-col">
          {rowChannels.map(channel => {
            const configured = isConfigured(channel);
            const status = statusFor(channel);
            const asset = assetFor(channel);
            return (
              <div
                key={channel.id}
                className="group relative -mx-3.5 grid min-h-[64px] grid-cols-[auto_1fr_auto] items-center gap-4 rounded-[10px] border-b border-border-subtle px-3.5 transition-colors last:border-b-0 hover:bg-surface-subtle lg:grid-cols-[auto_260px_minmax(0,1fr)_auto_auto] lg:gap-6"
              >
                {/* rail grows out of the row on hover */}
                <span
                  className={cn(
                    "absolute inset-y-3 left-0.5 w-0.5 origin-center scale-y-0 rounded-full transition-transform duration-300 group-hover:scale-y-100",
                    RAIL_STYLES[channel.id]
                  )}
                />

                <div
                  className={cn(
                    "flex h-9 w-9 items-center justify-center rounded-[10px] transition-transform duration-300 group-hover:scale-105",
                    channel.iconBg,
                    !configured && "opacity-50 grayscale"
                  )}
                >
                  <channel.icon size={17} className={channel.iconColor} />
                </div>

                <div className="min-w-0">
                  <p className="font-display text-[13.5px] font-bold leading-tight tracking-tight text-ink">
                    {channel.name}
                  </p>
                  <p className="mt-0.5 truncate font-body text-[11.5px] text-ink-secondary">{status.detail}</p>
                </div>

                <p className="hidden min-w-0 truncate font-body text-xs text-ink-secondary lg:block">
                  {asset.id ? (
                    <>
                      <span className="font-mono text-[11.5px] font-medium tabular-nums tracking-tight text-ink">
                        {asset.id}
                      </span>
                      {asset.label ? ` · ${asset.label}` : ""}
                    </>
                  ) : (
                    <span className="text-ink-muted">&mdash;</span>
                  )}
                </p>

                <span
                  className={cn(
                    "inline-flex min-w-[120px] items-center gap-2 font-label text-xs font-bold",
                    STATE_STYLES[status.state]
                  )}
                >
                  <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT_STYLES[status.state])} />
                  {status.label}
                </span>

                <div className={cn("flex items-center justify-end gap-3.5", configured ? "min-w-[150px]" : "min-w-0")}>
                  {configured && (
                    <>
                      <button
                        type="button"
                        onClick={() => onManageChannel(channel)}
                        className="font-label text-xs font-bold text-primary underline decoration-transparent underline-offset-4 transition-colors hover:decoration-current"
                      >
                        Manage
                      </button>
                      <button
                        type="button"
                        onClick={() => onDisconnect(channel.id)}
                        disabled={!canManage}
                        className="font-label text-xs font-bold text-ink-muted underline decoration-transparent underline-offset-4 opacity-0 transition-all hover:text-danger hover:decoration-current focus-visible:opacity-100 group-hover:opacity-100 disabled:cursor-not-allowed"
                      >
                        Disconnect
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Footer ─────────────────────────────────────────────────────── */}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle bg-[#fdfcfa] px-6 py-3.5 font-body text-[11.5px] text-ink-secondary sm:px-8">
        <span>
          {isConnected
            ? "Webhook verified · Graph API v21.0"
            : "Nothing to check until a channel is connected"}
        </span>
        {isConnected && (
          <button
            type="button"
            onClick={onRefreshHealth}
            disabled={healthLoading}
            className="inline-flex items-center gap-2 font-label text-xs font-bold text-primary underline decoration-transparent underline-offset-4 transition-colors hover:decoration-current disabled:cursor-wait disabled:opacity-60"
          >
            {healthLoading && <Loader2 size={12} className="animate-spin" />}
            {healthLoading ? "Checking…" : "Refresh health"}
          </button>
        )}
      </div>
    </section>
  );
}

function StripCell({
  icon: Icon,
  iconBg,
  label,
  value,
  detail,
  mono = false,
  detailMono = false,
  cellBg = "",
}: {
  icon: React.ComponentType<{ size?: number | string; className?: string }>;
  iconBg: string;
  label: string;
  value: string | null;
  detail: React.ReactNode | string | null;
  mono?: boolean;
  detailMono?: boolean;
  cellBg?: string;
}) {
  return (
    <div
      className={cn(
        "group relative min-w-0 border-b border-border-subtle/80 px-5 py-3 transition-all duration-200 hover:bg-white/95 sm:px-6 sm:py-3.5 sm:[&:nth-child(n+3)]:border-b-0 lg:border-b-0 lg:border-l lg:first:border-l-0",
        cellBg
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] shadow-xs transition-transform duration-200 group-hover:scale-105",
            iconBg
          )}
        >
          <Icon size={15} />
        </div>
        <div className="min-w-0 flex-1">
          <dt className="font-label text-[9px] font-bold uppercase tracking-[0.14em] text-ink-muted">{label}</dt>
          <dd
            className={cn(
              "mt-1 truncate font-display text-[13.5px] font-bold leading-tight text-ink",
              mono && "font-mono text-[13px] font-medium tabular-nums tracking-tight"
            )}
          >
            {value ?? <span className="font-body text-[12.5px] font-medium text-ink-muted">Not linked</span>}
          </dd>
          {detail && (
            <div
              className={cn(
                "mt-0.5 truncate font-body text-[11px] leading-tight text-ink-secondary",
                detailMono && "font-mono tabular-nums tracking-tight"
              )}
            >
              {detail}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
