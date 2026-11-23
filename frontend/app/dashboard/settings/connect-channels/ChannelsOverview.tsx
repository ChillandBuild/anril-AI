"use client";
import { useState } from "react";
import { Loader2 } from "lucide-react";
import type { MarketplaceStatus } from "@/lib/api";
import ChannelTile, { StatePill } from "./ChannelTile";
import type { TileMenuItem } from "./ChannelTile";
import { CHANNELS, EMBEDDED_SIGNUP_TARGETS, META_CHANNEL_IDS, isChannelConfigured } from "./channels";
import type { ChannelConfig, EmbeddedSignupTarget, Setting, WebhookHealth } from "./channels";
import type { ProviderId } from "./MarketplaceLeadsSection";
import {
  IDLE_DETAIL, TILE_GROUPS, TILE_META, accountLine, channelStatus, countStates, marketplaceStatus, summarySentence, viaSuffix,
} from "./tiles";
import type { TileId, TileStatus } from "./tiles";

const META_IDS: string[] = [...META_CHANNEL_IDS];

export default function ChannelsOverview({
  settings,
  webhookHealth,
  healthLoading,
  canManage,
  metaConnected,
  metaBusy,
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

  const isMarketplace = (id: TileId): id is ProviderId => id === "indiamart" || id === "justdial";

  // Until IndiaMART/JustDial status arrives (or if it fails) those tiles are unknown, not "Not connected".
  const unknown = (id: TileId) => isMarketplace(id) && !marketplace;
  const statusOf = (id: TileId): TileStatus =>
    unknown(id)
      ? { state: "off", label: marketplaceError ? "Couldn't check" : "Checking…", detail: "" }
      : isMarketplace(id) ? marketplaceStatus(marketplace?.[id]) : channelStatus(id, settings, webhookHealth);

  const allIds = TILE_GROUPS.flatMap(g => g.ids);
  const knownIds = allIds.filter(id => !unknown(id));
  const statuses = Object.fromEntries(allIds.map(id => [id, statusOf(id)])) as Record<TileId, TileStatus>;
  const counts = { ...countStates(knownIds.map(id => statuses[id].state)), total: allIds.length };
  const sentence = summarySentence(Object.fromEntries(knownIds.map(id => [id, statuses[id].state])));

  function menuFor(id: TileId, configured: boolean): TileMenuItem[] {
    if (isMarketplace(id)) return [];
    const channel = CHANNELS.find(c => c.id === id);
    const items: TileMenuItem[] = [];
    if (META_IDS.includes(id)) {
      items.push(
        metaConnected
          ? { label: "Reconnect Meta Business", hint: "Refresh permissions and re-pick assets", disabled: metaBusy, onSelect: onConnectMeta }
          : { label: "Connect Meta Business", hint: "WhatsApp, Messenger, Instagram and ads in one go", disabled: metaBusy, onSelect: onConnectMeta },
        {
          label: metaConnected ? "Switch to Coexistence" : "WhatsApp Coexistence",
          hint: "Keep the WhatsApp phone app working too",
          disabled: metaBusy,
          onSelect: onConnectCoexistence,
        },
      );
      if (metaConnected) items.push({ label: "Disconnect Meta Business…", danger: true, disabled: metaBusy, onSelect: () => onDisconnect("meta") });
    }
    if (configured && channel) {
      items.push({ label: `Disconnect ${TILE_META[id].name}…`, danger: true, disabled: metaBusy, onSelect: () => onDisconnect(id) });
    }
    return items;
  }

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

  const pill = (n: number, state: TileStatus["state"], label: string) =>
    n > 0 ? <StatePill key={label} state={state} label={`${n} ${label}`} /> : null;

  return (
    <div className="space-y-5">
      <section className="flex flex-wrap items-center gap-4 overflow-hidden rounded-2xl border border-border bg-white pl-6 shadow-card">
        <div className="min-w-0 flex-[1_1_380px] py-5">
          <div className="font-display text-[22px] font-extrabold text-ink">{counts.connected} of {counts.total} connected</div>
          <p className="mt-1 max-w-prose font-body text-sm text-ink-secondary">{sentence}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {pill(counts.receiving, "receiving", "receiving")}
            {pill(counts.quiet, "waiting", "quiet")}
            {counts.attention > 0 && pill(counts.attention, "attention", "need attention")}
            {pill(counts.off, "off", "not connected")}
          </div>
        </div>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/login/tealy-poster.png" alt="" width={150} height={150} className="-my-2 mr-2 h-[150px] w-[150px] flex-none object-contain" />
      </section>

      {TILE_GROUPS.map((group, gi) => (
        <section key={group.id} className="flex flex-col gap-2.5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <span className="font-label text-xs font-bold uppercase tracking-[0.06em] text-ink-secondary">{group.label}</span>{" "}
              <span className="font-body text-xs text-ink-secondary">· {group.hint}</span>
            </div>
            {gi === 0 && (
              <button
                type="button"
                onClick={onRefreshHealth}
                disabled={healthLoading}
                className="inline-flex items-center gap-1.5 font-label text-xs font-bold text-primary underline decoration-transparent underline-offset-4 transition-colors hover:decoration-current disabled:cursor-wait disabled:opacity-60"
              >
                {healthLoading && <Loader2 size={12} className="animate-spin" />}
                {healthLoading ? "Checking…" : "Refresh health"}
              </button>
            )}
          </div>
          <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(260px,1fr))" }}>
            {group.ids.map(id => {
              const status = statuses[id];
              const connected = status.state !== "off";
              const channel = CHANNELS.find(c => c.id === id);
              const configured = channel ? isChannelConfigured(channel, settings) : connected;
              const target = EMBEDDED_SIGNUP_TARGETS[id];
              const busy = id === "razorpay" ? razorpayBusy : Boolean(target) && busyTarget === target;
              const bottom = connected
                ? `${status.detail}${viaSuffix(id, status.state, settings)}`
                : IDLE_DETAIL[id];
              return (
                <ChannelTile
                  key={id}
                  id={id}
                  account={isMarketplace(id) ? "—" : accountLine(id, settings)}
                  status={status}
                  bottom={bottom}
                  connected={connected}
                  busy={busy}
                  canManage={canManage}
                  menu={menuFor(id, configured)}
                  onManage={manageFor(id)}
                  onConnect={connectFor(id)}
                />
              );
            })}
          </div>
        </section>
      ))}

      <section className="overflow-hidden rounded-2xl border border-border bg-white shadow-card">
        <div className="flex flex-wrap items-center gap-3 pl-2 pr-5">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/login/healy-poster.png" alt="" width={150} height={150} className="-my-2 h-[150px] w-[150px] flex-none object-contain" />
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
