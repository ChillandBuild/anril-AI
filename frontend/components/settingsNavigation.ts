import {
  Headset,
  Megaphone,
  RadioTower,
  Sparkles,
  UserCircle,
} from "lucide-react";

export type SettingsGroup = "Account" | "Channels" | "Calling" | "Alerts";

export type SettingsNavItem = {
  href: string;
  icon: typeof UserCircle;
  label: string;
  group: SettingsGroup;
  entitlement?: "notifications" | "claude";
};

/** The tenant feature key the operator adds to switch on Anril AI (the Claude connector). */
export const CLAUDE_FEATURE = "claude";
export const CLAUDE_SETTINGS_HREF = "/dashboard/settings/claude";

// Order here is the order groups and items render in the sidebar and the
// mobile "More" menu — see sidebar.tsx / MoreMenu.tsx.
export const SETTINGS_ITEMS: SettingsNavItem[] = [
  { href: "/dashboard/settings/account", icon: UserCircle, label: "Profile & Business", group: "Account" },
  { href: CLAUDE_SETTINGS_HREF, icon: Sparkles, label: "Anril AI for Claude", group: "Account", entitlement: "claude" },
  { href: "/dashboard/settings/connect-channels", icon: RadioTower, label: "Connect Channels", group: "Channels" },
  { href: "/dashboard/settings/telecalling-behavior", icon: Headset, label: "Telecalling Behavior", group: "Calling" },
  { href: "/dashboard/settings/notifications", icon: Megaphone, label: "Notifications", group: "Alerts", entitlement: "notifications" },
];

/**
 * Auto-reply, Follow-ups and Inbox & handover are no longer Settings pages (they
 * live under Anril Setup and Engage in the menu). Their addresses stay under
 * /dashboard/settings/, so the Settings list is matched from its own items, not
 * from that prefix.
 */
export function isSettingsPath(pathname: string): boolean {
  return SETTINGS_ITEMS.some((item) => pathname.startsWith(item.href));
}

export function hasNotificationSettings(purchasedFeatures: string[]): boolean {
  return purchasedFeatures.length === 0
    || purchasedFeatures.includes("inbound_messaging")
    || purchasedFeatures.includes("outbound_messaging");
}

/** Anril AI for Claude is owner-only, and only for a client the operator has switched on. */
export function claudeSettingsOn(role: string | null, enabledFeatures: string[]): boolean {
  return role === "owner" && enabledFeatures.includes(CLAUDE_FEATURE);
}

export function getVisibleSettingsItems(purchasedFeatures: string[], claudeOn = false): SettingsNavItem[] {
  const showNotifications = hasNotificationSettings(purchasedFeatures);

  return SETTINGS_ITEMS.filter((item) => {
    if (item.entitlement === "notifications") return showNotifications;
    if (item.entitlement === "claude") return claudeOn;
    return true;
  });
}

/** Groups, in display order, for rendering group headings above their items. */
export const SETTINGS_GROUP_ORDER: SettingsGroup[] = ["Account", "Channels", "Calling", "Alerts"];
