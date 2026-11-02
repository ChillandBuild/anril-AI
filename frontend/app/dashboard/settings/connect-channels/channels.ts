import { MessageSquare, Send, Megaphone, IndianRupee } from "lucide-react";
import { InstagramIcon, FacebookIcon } from "./ui";

export type EmbeddedSignupSession = { waba_id?: string; phone_number_id?: string; business_id?: string; is_coexistence?: boolean };
export type MetaBusinessLoginState = "idle" | "connecting" | "selecting" | "finishing" | "success" | "error";
export type MetaBusinessAssets = {
  session_id: string;
  pages: Array<{ id: string; name: string; instagram_business_account?: { id: string; username?: string } | null }>;
  ad_accounts: Array<{ id: string; name: string; account_id?: string; currency?: string }>;
  catalogs: Array<{ id: string; name: string }>;
};

// ── Types ───────────────────────────────────────────────────────────────────
export type Setting = {
  key: string;
  display_value: string;
  is_secret: boolean;
  is_set: boolean;
  updated_at: string;
};

export type SettingsMap = Record<string, string>;

export type FieldDef = {
  key: string;
  label: string;
  placeholder?: string;
  secret: boolean;
  required?: boolean;
  hint?: string;
};

export type ActivateResult = {
  success: boolean;
  message: string;
  detail?: string;
};

export type ChannelHealth = {
  last_event: string | null;
};

export type TokenAlert = {
  channel: string;
  error: string;
  created_at: string;
};

export type WebhookHealth = {
  health: Record<string, ChannelHealth>;
  token_alerts: TokenAlert[];
};

export type SaveState = "idle" | "dirty" | "saving" | "saved";

export type ChannelConfig = {
  id: string;
  name: string;
  description: string;
  icon: React.ComponentType<{ size?: number | string; className?: string }>;
  iconBg: string;
  iconColor: string;
  themeColor: string;
  fields: FieldDef[];
  hasActivation: boolean;
};


// ── Channel Definitions ──────────────────────────────────────────────────────
export const CHANNELS: ChannelConfig[] = [
  {
    id: "whatsapp",
    name: "WhatsApp Cloud API",
    description: "Deploy automated flows, notifications, and outbound campaigns using WhatsApp Business App.",
    icon: MessageSquare,
    iconBg: "bg-emerald-100",
    iconColor: "text-emerald-600",
    themeColor: "emerald",
    fields: [
      { key: "meta_phone_number_id", label: "Phone Number ID", secret: false, required: true },
      { key: "meta_waba_id", label: "WhatsApp Business Account ID (WABA ID)", secret: false, required: true, hint: "Found in Meta Business Manager → WhatsApp Accounts. Required for webhook subscription." },
      { key: "meta_access_token", label: "Permanent Access Token", secret: true, required: true },
      { key: "meta_webhook_verify_token", label: "Webhook Verify Token", secret: true, required: true, hint: "Pick any string. Paste the same value into Meta Developer App → Webhook → Verify Token (shared by WhatsApp, Instagram, Facebook)." },
      { key: "meta_app_secret", label: "Meta App Secret", secret: true, required: true, hint: "Meta Developer App → Settings → Basic → App Secret. Used to verify inbound Facebook + Instagram webhooks." },
    ],
    hasActivation: true,
  },
  {
    id: "instagram",
    name: "Instagram DM",
    description: "Automate responses, track conversations, and manage direct messages from your Instagram business account.",
    icon: InstagramIcon,
    iconBg: "bg-pink-100",
    iconColor: "text-pink-600",
    themeColor: "pink",
    fields: [
      { key: "instagram_page_id", label: "Instagram Page ID / Business Account ID", secret: false, required: true, hint: "Meta Business Manager Page ID or Instagram Business Account ID" },
      { key: "instagram_access_token", label: "Instagram Page Access Token", secret: true, required: true, hint: "Permanent page access token with instagram_manage_messages scope" },
      { key: "instagram_app_secret", label: "Instagram App Secret", secret: true, required: false, hint: "Only if Instagram uses Instagram-Login (graph.instagram.com): Meta App → Instagram → API setup with Instagram login → App secret. Leave blank to reuse the Meta App Secret." },
    ],
    hasActivation: true,
  },
  {
    id: "facebook",
    name: "Facebook Messenger",
    description: "Interact with your page visitors, handle support tickets, and route incoming Facebook Messenger chats.",
    icon: FacebookIcon,
    iconBg: "bg-blue-100",
    iconColor: "text-blue-600",
    themeColor: "blue",
    fields: [
      { key: "facebook_page_id", label: "Facebook Page ID", secret: false, required: true, hint: "Your Facebook Page's numeric ID from Page settings" },
      { key: "facebook_access_token", label: "Facebook Page Access Token", secret: true, required: true, hint: "Permanent page access token with pages_messaging scope" },
    ],
    hasActivation: true,
  },
  {
    id: "meta_ads",
    name: "Meta Ads",
    description: "Connect an ad account for Click-to-WhatsApp performance, spend, delivery, and attribution.",
    icon: Megaphone,
    iconBg: "bg-indigo-100",
    iconColor: "text-indigo-600",
    themeColor: "indigo",
    fields: [
      { key: "meta_ads_account_id", label: "Ads Account ID", secret: false, required: true, hint: "Business Settings → Accounts → Ad accounts. Enter digits or act_<digits>." },
      { key: "meta_ads_access_token", label: "Ads System User Token", secret: true, required: true, hint: "Use a System User token with ads_read. Anril imports only single-destination Click-to-WhatsApp ads." },
    ],
    hasActivation: true,
  },
  {
    id: "telegram",
    name: "Telegram Bot",
    description: "Connect your Telegram bot to handle direct messages, support queries, and group notifications.",
    icon: Send,
    iconBg: "bg-sky-100",
    iconColor: "text-sky-600",
    themeColor: "sky",
    fields: [
      { key: "telegram_bot_token", label: "Telegram Bot Token", secret: true, required: true, hint: "Obtain this token from @BotFather on Telegram" },
    ],
    hasActivation: true,
  },
  {
    id: "razorpay",
    name: "Razorpay Payments",
    description: "Accept in-chat consultation payments (e.g. Paid Expert Handoff) directly into your own Razorpay account.",
    icon: IndianRupee,
    iconBg: "bg-violet-100",
    iconColor: "text-violet-600",
    themeColor: "violet",
    fields: [
      { key: "razorpay_key_id", label: "Key ID", secret: false, required: true, hint: "Razorpay Dashboard → Settings → API Keys." },
      { key: "razorpay_key_secret", label: "Key Secret", secret: true, required: true },
      { key: "razorpay_webhook_secret", label: "Webhook Secret", secret: true, required: true, hint: "Set this exact value as the Secret when creating the webhook in Razorpay Dashboard → Settings → Webhooks, pointed at the URL below." },
    ],
    hasActivation: false,
  },
];

export const WHATSAPP_CHANNEL = CHANNELS[0];

/** Channels the Meta embedded flow can provision. Order drives the status rows. */
export const META_CHANNEL_IDS = ["whatsapp", "instagram", "facebook", "meta_ads"] as const;

export const META_CHANNELS: ChannelConfig[] = META_CHANNEL_IDS
  .map(id => CHANNELS.find(c => c.id === id))
  .filter((c): c is ChannelConfig => Boolean(c));

/** Channels with no embedded path — manual configuration is the only way in. */
export const STANDALONE_CHANNELS: ChannelConfig[] = CHANNELS.filter(
  c => !META_CHANNEL_IDS.includes(c.id as (typeof META_CHANNEL_IDS)[number])
);

export type EmbeddedSignupTarget = "whatsapp" | "page" | "ads";

/**
 * Which Embedded Signup configuration connects each channel from its own card.
 *
 * Meta makes every asset listed in a Login configuration mandatory, so one combined
 * configuration blocks any customer who lacks one of its assets. Each target points
 * at a narrow configuration instead. Messenger and Instagram share "page" because
 * Instagram DMs ride the linked Page's token — one signup connects both. Channels
 * absent here have no embedded path.
 */
export const EMBEDDED_SIGNUP_TARGETS: Record<string, EmbeddedSignupTarget> = {
  whatsapp: "whatsapp",
  instagram: "page",
  facebook: "page",
  meta_ads: "ads",
};

export type ConnectionSource = "embedded" | "manual";

/**
 * How a channel's credentials got there.
 *
 * Tenants connected before the source marker existed have no `*_connection_source`
 * row. `meta_business_access_token` is written only by Meta-guided flows and never
 * by the manual token form, so its presence is a sound fallback signal.
 */
export function resolveConnectionSource(channelId: string, settings: Setting[]): ConnectionSource {
  if (!META_CHANNEL_IDS.includes(channelId as (typeof META_CHANNEL_IDS)[number])) return "manual";

  const explicit = settings.find(s => s.key === `${channelId}_connection_source`)?.display_value;
  if (explicit === "embedded") return "embedded";
  if (explicit === "manual") return "manual";

  return settings.find(s => s.key === "meta_business_access_token")?.is_set ? "embedded" : "manual";
}

/** Written only by the backend's Connect with Razorpay flow (services/razorpay_oauth.py). */
export const RAZORPAY_OAUTH_ACCOUNT_KEY = "razorpay_oauth_account_id";

/** The Razorpay account connected through OAuth, or null when the tenant uses pasted keys (or nothing). */
export function razorpayOAuthAccount(settings: Setting[]): string | null {
  return storedPlainValue(settings, RAZORPAY_OAUTH_ACCOUNT_KEY) || null;
}

/** Every required field is stored — or, for Razorpay, the OAuth connection stands in for the keys. */
export function isChannelConfigured(channel: ChannelConfig, settings: Setting[]): boolean {
  if (channel.id === "razorpay" && razorpayOAuthAccount(settings)) return true;
  return channel.fields.every(f => !f.required || settings.find(s => s.key === f.key)?.is_set);
}

function storedPlainValue(settings: Setting[], key: string): string {
  const row = settings.find(s => s.key === key);
  return !row || row.display_value === "Not set" ? "" : row.display_value;
}

/**
 * The settings to PATCH for one channel form.
 *
 * A blank secret means "keep what is stored": the form shows a stored secret as
 * dots with an empty draft, and the backend deletes any key sent as "". Sending
 * the blank draft wiped every secret the user had not retyped. Plain fields are
 * still sent when emptied, so they can be cleared. Removing a secret is the
 * channel's Disconnect action.
 */
export function buildSettingsUpdates(
  fields: FieldDef[],
  drafts: SettingsMap,
  settings: Setting[],
): SettingsMap {
  const updates: SettingsMap = {};
  for (const field of fields) {
    const draft = drafts[field.key];
    if (draft === undefined) continue;
    if (field.secret) {
      if (draft.length > 0) updates[field.key] = draft;
    } else if (draft !== storedPlainValue(settings, field.key)) {
      updates[field.key] = draft;
    }
  }
  return updates;
}

export function hasUnsavedChanges(fields: FieldDef[], drafts: SettingsMap, settings: Setting[]): boolean {
  return Object.keys(buildSettingsUpdates(fields, drafts, settings)).length > 0;
}
