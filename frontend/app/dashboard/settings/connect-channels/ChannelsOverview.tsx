"use client";
import { useState } from "react";
import { Activity, Building2, Check, CheckCircle2, Loader2, Megaphone, MessageSquare, Smartphone, Sparkles, Store } from "lucide-react";
import type { MarketplaceStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import { FacebookIcon, timeAgo } from "./ui";
import { CHANNELS, EMBEDDED_SIGNUP_TARGETS, isChannelConfigured } from "./channels";
import type { ChannelConfig, EmbeddedSignupTarget, Setting, WebhookHealth } from "./channels";
import type { MetaSignupMode } from "./metaSignupMode";
import type { ProviderId } from "./MarketplaceLeadsSection";
import {
  IDLE_DETAIL, TILE_GROUPS, TILE_NAME, assetFor, channelStatus, connectionNote, marketplaceStatus, settingValue,
} from "./tiles";
import type { ChannelState, TileId, TileStatus } from "./tiles";

type IconType = React.ComponentType<{ size?: number | string; className?: string }>;

const VALUE_PROPS: Array<{ title: string; detail: string }> = [
  { title: "Secure one-click connection", detail: "Authorise once in Meta — no tokens to copy or paste" },
  { title: "Official WhatsApp Cloud API", detail: "Templates, broadcasts and delivery reporting" },
  { title: "Number and webhook linked for you", detail: "Anril subscribes your WABA automatically" },
];

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

const RAIL_STYLES: Record<TileId, string> = {
  whatsapp: "bg-emerald-500",
  instagram: "bg-pink-500",
  facebook: "bg-blue-500",
  telegram: "bg-sky-500",
  meta_ads: "bg-primary-500",
  indiamart: "bg-orange-500",
  justdial: "bg-amber-500",
  razorpay: "bg-indigo-500",
};

/** IndiaMART and JustDial live outside CHANNELS, so their row icon is set here. */
const MARKETPLACE_ICON: Record<ProviderId, { icon: IconType; iconBg: string; iconColor: string }> = {
  indiamart: { icon: Store, iconBg: "bg-orange-100", iconColor: "text-orange-600" },
  justdial: { icon: Store, iconBg: "bg-amber-100", iconColor: "text-amber-600" },
};

const PRIMARY_BUTTON =
  "inline-flex items-center gap-2 rounded-[10px] bg-primary px-3.5 py-2 font-label text-xs font-bold text-white shadow-sm transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-60";
const OUTLINE_BUTTON =
  "inline-flex items-center gap-2 rounded-[10px] border border-border bg-white px-3.5 py-2 font-label text-xs font-bold text-ink shadow-sm transition-all hover:-translate-y-px hover:border-primary/40 hover:text-primary hover:shadow-[0_4px_12px_-5px_rgba(var(--primary-800-rgb),0.28)] disabled:cursor-not-allowed disabled:opacity-60";

export default function ChannelsOverview({
  settings,
  webhookHealth,
  healthLoading,
  canManage,
  metaConnected,
  metaBusy,
  metaMode,
  busyTarget,
  marketplace,
  marketplaceError,
  razorpayBusy,
  advanced,
  onRefreshHealth,
  onManageChannel,
  onConnectMeta,
  onConnectCoexistence,
  onEmbeddedConnect,
  onDisconnect,
  onRazorpayConnect,
  onOpenMarketplace,
}: {
  settings: Setting[];
  webhookHealth: WebhookHealth | null;
  healthLoading: boolean;
  canManage: boolean;
  metaConnected: boolean;
  metaBusy: boolean;
  metaMode: MetaSignupMode | null;
  busyTarget: EmbeddedSignupTarget | null;
  marketplace: Record<ProviderId, MarketplaceStatus> | null;
  marketplaceError: boolean;
  razorpayBusy: boolean;
  advanced: React.ReactNode;
  onRefreshHealth: () => void;
  onManageChannel: (channel: ChannelConfig) => void;
  onConnectMeta: () => void;
  onConnectCoexistence: () => void;
  onEmbeddedConnect: (target: EmbeddedSignupTarget) => void;
  onDisconnect: (channelId: string) => void;
  onRazorpayConnect: () => void;
  onOpenMarketplace: (provider: ProviderId) => void;
}) {
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const val = (key: string) => settingValue(settings, key);
  const phoneDisplay = val("meta_phone_display") ?? val("meta_phone_number_id");
  const verifiedName = val("meta_verified_name");
  const wabaId = val("meta_waba_id");
  const pageName = val("facebook_page_name") ?? val("facebook_page_id");
  const igUsername = val("instagram_username");
  const adsName = val("meta_ads_account_name");
  const adsId = val("meta_ads_account_id");
  const connectedAt = val("meta_connected_at");

  const isMarketplace = (id: TileId): id is ProviderId => id === "indiamart" || id === "justdial";

  // Until IndiaMART/JustDial status arrives (or if it fails) those rows are unknown, not "Not connected".
  const statusOf = (id: TileId): TileStatus => {
    if (!isMarketplace(id)) return channelStatus(id, settings, webhookHealth);
    if (!marketplace) return { state: "off", label: marketplaceError ? "Couldn't check" : "Checking…", detail: "" };
    return marketplaceStatus(marketplace[id]);
  };

  function connectFor(id: TileId) {
    if (isMarketplace(id)) return () => onOpenMarketplace(id);
    if (id === "razorpay") return onRazorpayConnect;
    if (id === "telegram") return () => { const c = CHANNELS.find(ch => ch.id === "telegram"); if (c) onManageChannel(c); };
    return () => { const t = EMBEDDED_SIGNUP_TARGETS[id]; if (t) onEmbeddedConnect(t); };
  }

  function manageFor(id: TileId) {
    if (isMarketplace(id)) return () => onOpenMarketplace(id);
    return () => { const c = CHANNELS.find(ch => ch.id === id); if (c) onManageChannel(c); };
  }

  return (
    <div className="space-y-5">
      <section
        className={cn(
          "overflow-hidden rounded-[20px] border bg-white transition-all duration-300",
          metaConnected
            ? "border-emerald-500/25 shadow-[0_4px_24px_-4px_rgba(16,185,129,0.14),0_1px_3px_rgba(0,0,0,0.04)] ring-1 ring-emerald-500/10"
            : "border-border shadow-card",
        )}
      >
        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div
          className={cn(
            "grid items-center gap-6 px-6 py-5 transition-colors duration-300 sm:grid-cols-[1fr_auto] sm:gap-8 sm:px-8",
            metaConnected
              ? "bg-gradient-to-b from-emerald-50/70 via-[#f8fdfa] to-white"
              : "bg-gradient-to-b from-[#f8f5ff]/70 via-[#fcfbff] to-white",
          )}
        >
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-label text-[10.5px] font-bold uppercase tracking-[0.14em] shadow-sm transition-colors",
                  metaConnected ? "border-emerald-200/90 bg-emerald-50/90 text-emerald-700" : "border-primary-200/90 bg-primary-50/90 text-primary",
                )}
              >
                <Activity size={12} className={metaConnected ? "text-emerald-600" : "text-primary"} />
                Connectivity Hub
              </span>
              {!metaConnected && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-primary-500/30 bg-primary-50/90 px-2.5 py-1 font-label text-[10.5px] font-bold uppercase tracking-wider text-primary-700 shadow-[0_0_12px_rgba(var(--primary-500-rgb),0.32)]">
                  <Sparkles size={11} className="animate-pulse text-primary-600" />
                  Recommended
                </span>
              )}
            </div>

            <h2 className="mt-2.5 font-display text-[26px] font-bold leading-[1.15] tracking-tight text-ink">
              {metaConnected ? verifiedName ?? "Meta Business" : "Connect Meta Business"}
            </h2>
            {metaConnected ? (
              <p className="mt-2 max-w-[70ch] font-body text-[13px] leading-relaxed text-ink-secondary">
                WhatsApp, Messenger, Instagram and Click-to-WhatsApp ad reporting, through one Meta connection.
              </p>
            ) : (
              <div className="mt-3 grid max-w-[90ch] gap-3 sm:grid-cols-2 sm:gap-6">
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

            {metaConnected ? (
              <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2.5">
                <span className="inline-flex items-center gap-2 font-label text-xs font-bold text-emerald-600">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  Connected{connectedAt ? ` · ${timeAgo(connectedAt)}` : ""}
                </span>
                <button type="button" onClick={onConnectMeta} disabled={!canManage || metaBusy} title="Refresh permissions and re-pick assets" className={PRIMARY_BUTTON}>
                  {metaBusy && metaMode === "standard" && <Loader2 size={12} className="animate-spin" />}
                  Reconnect Meta Business
                </button>
                <button type="button" onClick={onConnectCoexistence} disabled={!canManage || metaBusy} title="Keep the WhatsApp mobile app working alongside Anril" className={OUTLINE_BUTTON}>
                  {metaBusy && metaMode === "coexistence" && <Loader2 size={12} className="animate-spin" />}
                  <Smartphone size={13} className="text-ink-secondary" />
                  Switch to Coexistence
                </button>
                <button
                  type="button"
                  onClick={() => onDisconnect("meta")}
                  disabled={!canManage || metaBusy}
                  className="font-label text-xs font-bold text-red-600 underline decoration-red-300 underline-offset-4 transition-colors hover:text-red-700 hover:decoration-red-600 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Disconnect Meta
                </button>
              </div>
            ) : (
              <div className="mt-5 flex flex-wrap items-center gap-3">
                <button type="button" onClick={onConnectMeta} disabled={!canManage || metaBusy} className={cn(PRIMARY_BUTTON, "rounded-[11px] px-5 py-2.5 text-[13px]")}>
                  {metaBusy && metaMode === "standard" && <Loader2 size={14} className="animate-spin" />}
                  Connect Meta Business
                </button>
                <button type="button" onClick={onConnectCoexistence} disabled={!canManage || metaBusy} className={cn(OUTLINE_BUTTON, "rounded-[11px] px-4 py-2.5 text-[13px]")}>
                  {metaBusy && metaMode === "coexistence" && <Loader2 size={14} className="animate-spin" />}
                  <Smartphone size={13} className="text-ink-secondary" />
                  WhatsApp Coexistence
                </button>
              </div>
            )}
          </div>

          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/login/tealy-poster.png" alt="" width={150} height={150} className="-my-2 hidden h-[150px] w-[150px] flex-none object-contain sm:block" />
        </div>

        {/* ── Account strip / value props ────────────────────────────────── */}
        {metaConnected ? (
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
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-teal-500" />
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
              detail={<span className="font-semibold text-blue-700">{igUsername ? `Messenger + Instagram @${igUsername}` : "Messenger"}</span>}
            />
            <StripCell
              icon={Megaphone}
              iconBg="bg-primary-100/90 text-primary-600 ring-1 ring-primary-400/25"
              cellBg="hover:bg-gradient-to-br hover:from-primary-50/70 hover:to-white"
              label="Ad account"
              value={adsName}
              detail={adsId ? <span className="font-mono text-[11px] font-semibold text-primary-700">{adsId}</span> : null}
              detailMono
            />
          </dl>
        ) : (
          <div className="grid border-y border-border-subtle bg-[#fdfcfa] sm:grid-cols-3">
            {VALUE_PROPS.map((prop, i) => (
              <div key={prop.title} className={cn("flex items-start gap-3 px-6 py-4 sm:px-8", i > 0 && "border-t border-border-subtle sm:border-l sm:border-t-0")}>
                <Check size={14} className="mt-0.5 shrink-0 text-primary" strokeWidth={2.6} />
                <div className="min-w-0">
                  <p className="font-label text-[13px] font-bold leading-snug text-ink">{prop.title}</p>
                  <p className="mt-1 font-body text-[11.5px] leading-snug text-ink-secondary">{prop.detail}</p>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── Channels, one segment per group ────────────────────────────── */}
        <div className="flex flex-col px-6 pb-2 sm:px-8">
          {TILE_GROUPS.map((group, gi) => {
            const statuses = group.ids.map(id => statusOf(id));
            const connectedCount = statuses.filter(s => s.state !== "off").length;
            return (
              <div key={group.id} className={cn("pt-5", gi > 0 && "mt-3 border-t border-border-subtle")}>
                <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <div className="min-w-0">
                    <span className="font-label text-[10.5px] font-bold uppercase tracking-[0.15em] text-ink-secondary">{group.label}</span>
                    <span className="ml-2 font-body text-[11.5px] text-ink-muted">{group.hint}</span>
                  </div>
                  <span className="font-label text-[9.5px] font-bold uppercase tracking-[0.15em] text-ink-muted">
                    {connectedCount > 0 ? `${connectedCount} connected` : "None connected yet"}
                  </span>
                </div>

                <div className="flex flex-col">
                  {group.ids.map((id, i) => {
                    const status = statuses[i];
                    const connected = status.state !== "off";
                    const channel = CHANNELS.find(c => c.id === id);
                    const icon = channel ?? (isMarketplace(id) ? MARKETPLACE_ICON[id] : null);
                    // Only channels kept in the settings table can be disconnected from here.
                    const canDisconnect = Boolean(channel && isChannelConfigured(channel, settings));
                    const asset = assetFor(id, settings);
                    const target = EMBEDDED_SIGNUP_TARGETS[id];
                    const busy = id === "razorpay" ? razorpayBusy : Boolean(target) && busyTarget === target;
                    const detail = connected ? `${status.detail}${connectionNote(id, status.state, settings)}` : IDLE_DETAIL[id];
                    const name = TILE_NAME[id];
                    return (
                      <div
                        key={id}
                        className="group relative -mx-3.5 grid min-h-[64px] grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-4 rounded-[10px] border-b border-border-subtle px-3.5 py-2.5 transition-colors last:border-b-0 hover:bg-surface-subtle lg:grid-cols-[auto_260px_minmax(0,1fr)_auto_auto] lg:gap-6 lg:py-0"
                      >
                        {/* rail grows out of the row on hover */}
                        <span className={cn("absolute inset-y-3 left-0.5 w-0.5 origin-center scale-y-0 rounded-full transition-transform duration-300 group-hover:scale-y-100", RAIL_STYLES[id])} />

                        {icon && (
                          <div className={cn("flex h-9 w-9 items-center justify-center rounded-[10px] transition-transform duration-300 group-hover:scale-105", icon.iconBg, !connected && "opacity-50 grayscale")}>
                            <icon.icon size={17} className={icon.iconColor} />
                          </div>
                        )}

                        <div className="min-w-0">
                          <p className="font-display text-[13.5px] font-bold leading-tight tracking-tight text-ink">{name}</p>
                          <p className="mt-0.5 font-body text-[11.5px] text-ink-secondary lg:truncate" title={detail}>{detail}</p>
                          <StatusLabel status={status} className="mt-1 inline-flex lg:hidden" />
                        </div>

                        <p className="hidden min-w-0 truncate font-body text-xs text-ink-secondary lg:block">
                          {asset.id ? (
                            <>
                              <span className="font-mono text-[11.5px] font-medium tabular-nums tracking-tight text-ink">{asset.id}</span>
                              {asset.label ? ` · ${asset.label}` : ""}
                            </>
                          ) : (
                            <span className="text-ink-muted">&mdash;</span>
                          )}
                        </p>

                        <StatusLabel status={status} className="hidden min-w-[120px] lg:inline-flex" />

                        <div className="flex min-w-0 flex-col items-end gap-1.5 lg:min-w-[150px] lg:flex-row lg:items-center lg:justify-end lg:gap-3.5">
                          {connected ? (
                            <>
                              <button
                                type="button"
                                onClick={manageFor(id)}
                                aria-label={`Manage ${name}`}
                                className="font-label text-xs font-bold text-primary underline decoration-transparent underline-offset-4 transition-colors hover:decoration-current"
                              >
                                Manage
                              </button>
                              {canDisconnect && (
                                <button
                                  type="button"
                                  onClick={() => onDisconnect(id)}
                                  disabled={!canManage}
                                  aria-label={`Disconnect ${name}`}
                                  className="font-label text-xs font-bold text-ink-muted underline decoration-transparent underline-offset-4 opacity-0 transition-all hover:text-danger hover:decoration-current focus-visible:opacity-100 group-hover:opacity-100 disabled:cursor-not-allowed [@media(hover:none)]:opacity-100"
                                >
                                  Disconnect
                                </button>
                              )}
                            </>
                          ) : (
                            <button
                              type="button"
                              onClick={connectFor(id)}
                              disabled={!canManage || busy}
                              aria-label={`Connect ${name}`}
                              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 font-label text-xs font-bold text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {busy && <Loader2 size={12} className="animate-spin" />}
                              {busy ? "Opening…" : "Connect"}
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Footer ─────────────────────────────────────────────────────── */}
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle bg-[#fdfcfa] px-6 py-3.5 font-body text-[11.5px] text-ink-secondary sm:px-8">
          {metaConnected && <span>Webhook verified · Graph API v21.0</span>}
          <button
            type="button"
            onClick={onRefreshHealth}
            disabled={healthLoading}
            className="ml-auto inline-flex items-center gap-2 font-label text-xs font-bold text-primary underline decoration-transparent underline-offset-4 transition-colors hover:decoration-current disabled:cursor-wait disabled:opacity-60"
          >
            {healthLoading && <Loader2 size={12} className="animate-spin" />}
            {healthLoading ? "Checking…" : "Refresh health"}
          </button>
        </div>
      </section>

      <section className="overflow-hidden rounded-2xl border border-border bg-white shadow-card">
        <div className="flex flex-wrap items-center gap-3 pl-2 pr-5">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/login/healy-poster.png" alt="" width={150} height={150} className="-my-2 hidden h-[150px] w-[150px] flex-none object-contain sm:block" />
          <div className="min-w-0 flex-[1_1_300px] py-4">
            <div className="font-display font-extrabold text-ink">Advanced: your own API keys and webhooks</div>
            <div className="font-body text-[13px] text-ink-secondary">For a business account you manage yourself. Telegram and Razorpay keys also go here.</div>
          </div>
          <button
            type="button"
            onClick={() => setAdvancedOpen(o => !o)}
            aria-expanded={advancedOpen}
            className="inline-flex items-center rounded-[10px] border border-border bg-white px-3.5 py-2 font-label text-[13px] font-bold text-ink transition-colors hover:border-primary/40 hover:text-primary"
          >
            {advancedOpen ? "Close" : "Open"}
          </button>
        </div>
        {advancedOpen && <div className="border-t border-border-subtle p-5">{advanced}</div>}
      </section>
    </div>
  );
}

/** Coloured dot and word. The caller sets display, since mobile and desktop place it differently. */
function StatusLabel({ status, className }: { status: TileStatus; className: string }) {
  return (
    <span className={cn("items-center gap-2 font-label text-xs font-bold", STATE_STYLES[status.state], className)}>
      <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT_STYLES[status.state])} />
      {status.label}
    </span>
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
  icon: IconType;
  iconBg: string;
  label: string;
  value: string | null;
  detail: React.ReactNode | null;
  mono?: boolean;
  detailMono?: boolean;
  cellBg?: string;
}) {
  return (
    <div
      className={cn(
        "group relative min-w-0 border-b border-border-subtle/80 px-5 py-3 transition-all duration-200 hover:bg-white/95 sm:px-6 sm:py-3.5 sm:[&:nth-child(n+3)]:border-b-0 lg:border-b-0 lg:border-l lg:first:border-l-0",
        cellBg,
      )}
    >
      <div className="flex items-start gap-3">
        <div className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] shadow-xs transition-transform duration-200 group-hover:scale-105", iconBg)}>
          <Icon size={15} />
        </div>
        <div className="min-w-0 flex-1">
          <dt className="font-label text-[9px] font-bold uppercase tracking-[0.14em] text-ink-muted">{label}</dt>
          <dd className={cn("mt-1 truncate font-display text-[13.5px] font-bold leading-tight text-ink", mono && "font-mono text-[13px] font-medium tabular-nums tracking-tight")}>
            {value ?? <span className="font-body text-[12.5px] font-medium text-ink-muted">Not linked</span>}
          </dd>
          {detail && (
            <div className={cn("mt-0.5 truncate font-body text-[11px] leading-tight text-ink-secondary", detailMono && "font-mono tabular-nums tracking-tight")}>
              {detail}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
