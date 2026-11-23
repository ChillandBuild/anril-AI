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

export const TILE_META: Record<TileId, { name: string; initials: string; badge: string }> = {
  whatsapp: { name: "WhatsApp", initials: "WA", badge: "bg-green-100 text-green-800" },
  instagram: { name: "Instagram DM", initials: "IG", badge: "bg-pink-100 text-pink-800" },
  facebook: { name: "Facebook Messenger", initials: "FB", badge: "bg-blue-100 text-blue-800" },
  telegram: { name: "Telegram", initials: "TG", badge: "bg-sky-100 text-sky-800" },
  meta_ads: { name: "Meta Ads", initials: "AD", badge: "bg-indigo-100 text-indigo-800" },
  indiamart: { name: "IndiaMART", initials: "IM", badge: "bg-orange-100 text-orange-800" },
  justdial: { name: "JustDial", initials: "JD", badge: "bg-amber-100 text-amber-800" },
  razorpay: { name: "Razorpay", initials: "RP", badge: "bg-blue-100 text-blue-700" },
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

/** The account a tile is bound to: number, handle, page, ad account, or an em dash. */
export function accountLine(id: TileId, settings: Setting[]): string {
  const v = (key: string) => settingValue(settings, key);
  const join = (...parts: Array<string | null>) => parts.filter(Boolean).join(" · ");
  switch (id) {
    case "whatsapp":
      return join(v("meta_phone_display") ?? v("meta_phone_number_id"), v("meta_verified_name")) || "—";
    case "instagram": {
      const handle = v("instagram_username");
      const who = handle ? `@${handle}` : v("instagram_page_id");
      return who ? `${who} · via linked Page` : "—";
    }
    case "facebook": {
      const page = v("facebook_page_name") ?? v("facebook_page_id");
      return page ? `Page: ${page}` : "—";
    }
    case "meta_ads":
      return join(v("meta_ads_account_name"), v("meta_ads_account_id")) || "—";
    case "razorpay":
      return razorpayOAuthAccount(settings) ?? v("razorpay_key_id") ?? "—";
    case "telegram": {
      const ch = CHANNELS.find(c => c.id === "telegram");
      return ch && isChannelConfigured(ch, settings) ? "Bot connected" : "No bot linked";
    }
    default:
      return "—";
  }
}

/** " · via Meta Business · 48d ago" for a Meta-connected tile, "" otherwise. */
export function viaSuffix(id: TileId, state: ChannelState, settings: Setting[]): string {
  if (state === "off" || !["whatsapp", "instagram", "facebook", "meta_ads"].includes(id)) return "";
  if (resolveConnectionSource(id, settings) !== "embedded") return " · via your own API keys";
  const at = settingValue(settings, "meta_connected_at");
  return at ? ` · via Meta Business · ${timeAgo(at)}` : " · via Meta Business";
}

export type StateCounts = { connected: number; total: number; receiving: number; quiet: number; attention: number; off: number };

/** Green states (receiving, synced) count as receiving; waiting as quiet. */
export function countStates(states: ChannelState[]): StateCounts {
  const c: StateCounts = { connected: 0, total: states.length, receiving: 0, quiet: 0, attention: 0, off: 0 };
  for (const s of states) {
    if (s === "off") c.off++;
    else {
      c.connected++;
      if (s === "waiting") c.quiet++;
      else if (s === "attention") c.attention++;
      else c.receiving++;
    }
  }
  return c;
}

function joinNames(names: string[], last = "and"): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} ${last} ${names[names.length - 1]}`;
}

/** One plain sentence for the summary card. */
export function summarySentence(states: Partial<Record<TileId, ChannelState>>): string {
  const on = (id: TileId) => states[id] !== undefined && states[id] !== "off";
  const chatNames = (["whatsapp", "instagram", "facebook"] as TileId[])
    .filter(on)
    .map(id => (id === "facebook" ? "Messenger" : TILE_META[id].name.replace(" DM", "")));
  if (on("telegram")) chatNames.push("Telegram");
  const parts: string[] = [];
  parts.push(
    chatNames.length
      ? `Customers can reach you on ${joinNames(chatNames)}.`
      : "Connect WhatsApp, Instagram or Messenger so customers can reach you.",
  );
  const needFix = (Object.keys(states) as TileId[]).filter(id => states[id] === "attention").map(id => TILE_META[id].name);
  if (needFix.length) parts.push(`${joinNames(needFix)} ${needFix.length > 1 ? "need" : "needs"} attention. Reconnect to keep messages flowing.`);
  const missing = (["indiamart", "justdial"] as TileId[]).filter(id => id in states && !on(id)).map(id => TILE_META[id].name);
  if (missing.length) parts.push(`Connect ${joinNames(missing, "or")} to bring their enquiries in too.`);
  return parts.join(" ");
}
