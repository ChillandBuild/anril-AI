import type { MarketplaceStatus } from "@/lib/api";
import { isChannelConfigured, CHANNELS, razorpayOAuthAccount, resolveConnectionSource } from "./channels";
import type { Setting, WebhookHealth } from "./channels";
import { timeAgo } from "./ui";

/** What a tile is doing. Five states that never contradict their own detail line. */
export type ChannelState = "receiving" | "waiting" | "synced" | "attention" | "off";

export type TileId = "whatsapp" | "instagram" | "facebook" | "telegram" | "meta_ads" | "indiamart" | "justdial" | "razorpay";
export type TileGroup = "chat" | "leads" | "payments";

export type TileStatus = { state: ChannelState; label: string; detail: string };

export const TILE_GROUPS: Array<{ id: TileGroup; label: string; hint: string; ids: TileId[] }> = [
  { id: "chat", label: "Chat channels", hint: "Where customers message you", ids: ["whatsapp", "instagram", "facebook", "telegram"] },
  { id: "leads", label: "Lead sources", hint: "Where new enquiries come from", ids: ["meta_ads", "indiamart", "justdial"] },
  { id: "payments", label: "Payments", hint: "How customers pay you", ids: ["razorpay"] },
];

export const TILE_NAME: Record<TileId, string> = {
  whatsapp: "WhatsApp",
  instagram: "Instagram DM",
  facebook: "Facebook Messenger",
  telegram: "Telegram",
  meta_ads: "Meta Ads",
  indiamart: "IndiaMART",
  justdial: "JustDial",
  razorpay: "Razorpay",
};

export const IDLE_DETAIL: Record<TileId, string> = {
  whatsapp: "Chat, templates and broadcasts",
  instagram: "Reply to Instagram DMs in Anril",
  facebook: "Reply to Messenger chats in Anril",
  telegram: "Reply to Telegram chats in Anril",
  meta_ads: "Click-to-WhatsApp ad performance",
  indiamart: "Enquiries land in Leads",
  justdial: "Enquiries land in Leads",
  razorpay: "Take payments inside chats",
};

/** A stored setting value, or null when the row is missing or never set. */
export function settingValue(settings: Setting[], key: string): string | null {
  const row = settings.find(s => s.key === key);
  if (!row?.is_set) return null;
  const value = row.display_value;
  return value && value !== "Not set" ? value : null;
}

/** Status of a channel kept in the settings table (Meta channels, Telegram, Razorpay). */
export function channelStatus(channelId: string, settings: Setting[], health: WebhookHealth | null): TileStatus {
  const channel = CHANNELS.find(c => c.id === channelId);
  if (!channel || !isChannelConfigured(channel, settings)) {
    return { state: "off", label: "Not connected", detail: "" };
  }
  if (health?.token_alerts?.some(a => a.channel === channelId)) {
    return { state: "attention", label: "Needs attention", detail: "Token rejected by Meta" };
  }
  if (channelId === "razorpay") {
    return { state: "synced", label: "Connected", detail: "Accepts in-chat payments" };
  }
  // Meta Ads is polled on a schedule, so "no events" would read as broken.
  if (channelId === "meta_ads") {
    const lastSync = settingValue(settings, "meta_ads_last_sync_at");
    return lastSync
      ? { state: "synced", label: "Synced", detail: `Click-to-WhatsApp · ${timeAgo(lastSync)}` }
      : { state: "waiting", label: "Awaiting sync", detail: "Connected · first sync pending" };
  }
  const lastEvent = health?.health?.[channelId]?.last_event;
  if (lastEvent) return { state: "receiving", label: "Receiving", detail: `Last message ${timeAgo(lastEvent)}` };
  return { state: "waiting", label: "Awaiting first", detail: "Connected · nothing received yet" };
}

/** Status of IndiaMART / JustDial from the marketplace status endpoint. */
export function marketplaceStatus(st: MarketplaceStatus | null | undefined): TileStatus {
  if (!st?.connected) return { state: "off", label: "Not connected", detail: "" };
  if (st.last_lead_at) {
    return { state: "receiving", label: "Receiving", detail: `Last enquiry ${timeAgo(st.last_lead_at)} · ${st.leads_this_month} this month` };
  }
  return { state: "waiting", label: "Awaiting first", detail: "Connected · no enquiries yet" };
}

/** The account a row is bound to: an id (number, handle, page, ad account) and a label beside it. */
export function assetFor(id: TileId, settings: Setting[]): { id: string | null; label: string | null } {
  const v = (key: string) => settingValue(settings, key);
  switch (id) {
    case "whatsapp":
      return { id: v("meta_phone_display") ?? v("meta_phone_number_id"), label: v("meta_verified_name") };
    case "instagram": {
      const handle = v("instagram_username");
      const who = handle ? `@${handle}` : v("instagram_page_id");
      return { id: who, label: who ? "via linked Page" : null };
    }
    case "facebook":
      return { id: v("facebook_page_name") ?? v("facebook_page_id"), label: null };
    case "meta_ads":
      return { id: v("meta_ads_account_id"), label: v("meta_ads_account_name") };
    case "razorpay":
      return { id: razorpayOAuthAccount(settings) ?? v("razorpay_key_id"), label: null };
    default:
      return { id: null, label: null };
  }
}

/** " · via your own API keys" for a Meta channel connected by hand; the hub header covers Meta Business. */
export function connectionNote(id: TileId, state: ChannelState, settings: Setting[]): string {
  if (state === "off" || !["whatsapp", "instagram", "facebook", "meta_ads"].includes(id)) return "";
  return resolveConnectionSource(id, settings) === "manual" ? " · via your own API keys" : "";
}
