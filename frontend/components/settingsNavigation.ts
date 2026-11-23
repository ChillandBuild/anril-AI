import {
  BellRing,
  Clock,
  CreditCard,
  Headset,
  Megaphone,
  RadioTower,
  Receipt,
  Repeat,
  ShieldCheck,
  Sparkles,
  Target,
  Type,
  UserCircle,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import type { NavAccess } from "@/components/nav/navSections";

/** The four groups of the Settings list and the Settings home cards, in display order. */
export type SettingsGroup = "My business" | "Connections" | "Team & roles" | "Alerts & automations";

export type SettingsNavItem = {
  href: string;
  icon: LucideIcon;
  label: string;
  /** null = the one link under the groups (Plans & subscription): no heading, no card. */
  group: SettingsGroup | null;
  entitlement?: "notifications" | "claude";
  /** Any of these permissions opens the page (owners always pass). */
  permissionAny: readonly string[];
  /** Open to everyone logged in, whatever their permissions (Text size). The subscription rule still applies. */
  openToAll?: true;
  /** The page needs an active subscription. False only for Plans & subscription, so unsubscribed users can still pay. */
  needsSubscription: boolean;
};

/** The tenant feature key the operator adds to switch on Anril AI (the Claude connector). */
export const CLAUDE_FEATURE = "claude";
export const CLAUDE_SETTINGS_HREF = "/dashboard/settings/claude";

export const SETTINGS_HOME_HREF = "/dashboard/settings";
export const ROLES_HREF = "/dashboard/roles";
export const SUBSCRIPTION_HREF = "/dashboard/subscription";

/** The gate every page that used to be a Settings page keeps. */
const SETTINGS_PERMS = ["settings.view", "settings.manage"] as const;
const ROLES_PERMS = ["roles.view", "roles.manage"] as const;
const SUBSCRIPTION_PERMS = ["subscription.view", "subscription.manage"] as const;

const settingsPage = (
  href: string, icon: LucideIcon, label: string, group: SettingsGroup, entitlement?: SettingsNavItem["entitlement"],
): SettingsNavItem => ({ href, icon, label, group, entitlement, permissionAny: SETTINGS_PERMS, needsSubscription: true });

// Order here is the order groups and items render in the sidebar, the Settings
// home page and the mobile "More" menu: see sidebar.tsx / MoreMenu.tsx.
export const SETTINGS_ITEMS: SettingsNavItem[] = [
  settingsPage("/dashboard/settings/account", UserCircle, "Business details", "My business"),
  settingsPage(CLAUDE_SETTINGS_HREF, Sparkles, "Anril AI for Claude", "My business", "claude"),
  settingsPage("/dashboard/settings/payments", Wallet, "Payments & advance", "My business"),
  settingsPage("/dashboard/settings/target", Target, "Target & profit", "My business"),
  // Every person picks their own text size, telecallers included, so this row has no permission gate.
  { href: "/dashboard/settings/display", icon: Type, label: "Text size", group: "My business", permissionAny: [], openToAll: true, needsSubscription: true },
  settingsPage("/dashboard/settings/connect-channels", RadioTower, "Channels", "Connections"),
  settingsPage("/dashboard/settings/telecalling-behavior", Headset, "Calling", "Connections"),
  settingsPage("/dashboard/settings/calling-rules", Clock, "Calling rules", "Connections"),
  settingsPage("/dashboard/settings/meta-charges", Receipt, "Limits & Meta charges", "Connections"),
  { href: ROLES_HREF, icon: ShieldCheck, label: "Team & roles", group: "Team & roles", permissionAny: ROLES_PERMS, needsSubscription: true },
  settingsPage("/dashboard/settings/alerts", Megaphone, "Alerts", "Alerts & automations", "notifications"),
  settingsPage("/dashboard/settings/notifications", BellRing, "Push & lead claims", "Alerts & automations", "notifications"),
  { href: "/dashboard/automations", icon: Repeat, label: "Automations", group: "Alerts & automations", permissionAny: ["settings.view", "settings.manage", "templates.view", "templates.manage"], needsSubscription: true },
  { href: SUBSCRIPTION_HREF, icon: CreditCard, label: "Plans & subscription", group: null, permissionAny: SUBSCRIPTION_PERMS, needsSubscription: false },
];

/** Groups, in display order, for rendering group headings above their items. */
export const SETTINGS_GROUP_ORDER: SettingsGroup[] = ["My business", "Connections", "Team & roles", "Alerts & automations"];

/** One plain line per group, shown on its Settings home card. */
export const SETTINGS_GROUP_INFO: Record<SettingsGroup, { description: string }> = {
  "My business": { description: "Business details, payments, your target and text size." },
  Connections: { description: "Connect your messaging channels and set how calling works." },
  "Team & roles": { description: "Add your team and choose what each person can see." },
  "Alerts & automations": { description: "Choose which alerts reach you and when, and see every automatic message." },
};

const matchesPath = (pathname: string, href: string) => pathname === href || pathname.startsWith(`${href}/`);

/**
 * Settings mode of the sidebar, and the Settings row's highlight: the Settings
 * home, every settings page, Team & roles and Plans & subscription. Auto-reply,
 * Follow-ups and Inbox & handover stay under /dashboard/settings/ in the address
 * bar but live elsewhere in the menu, so this matches the list's own addresses,
 * not that prefix.
 */
export function isSettingsPath(pathname: string): boolean {
  return pathname === SETTINGS_HOME_HREF || SETTINGS_ITEMS.some((item) => matchesPath(pathname, item.href));
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

/** Entitlement filter only (what the tenant bought / was switched on). Per-user gates are settingsItemsFor / settingsItemsForMember. */
export function getVisibleSettingsItems(purchasedFeatures: string[], claudeOn = false): SettingsNavItem[] {
  const showNotifications = hasNotificationSettings(purchasedFeatures);

  return SETTINGS_ITEMS.filter((item) => {
    if (item.entitlement === "notifications") return showNotifications;
    if (item.entitlement === "claude") return claudeOn;
    return true;
  });
}

/** May this user open the page? Gate only (no entitlements): the desktop rule, subscription included. */
export function settingsItemVisible(item: SettingsNavItem, access: NavAccess): boolean {
  return (!item.needsSubscription || access.isSubscribed) && (item.openToAll === true || access.canAny([...item.permissionAny]));
}

/** Desktop: the items this user sees, in list order. */
export function settingsItemsFor(access: NavAccess, purchasedFeatures: string[], claudeOn: boolean): SettingsNavItem[] {
  return getVisibleSettingsItems(purchasedFeatures, claudeOn).filter((item) => settingsItemVisible(item, access));
}

/**
 * Phone drawer: the same gates minus the subscription check, which the drawer has
 * never made (every drawer row is permission-only). A page the user cannot use
 * while unsubscribed is bounced to Home by the dashboard layout, as before.
 */
export function settingsItemsForMember(
  role: string | null, permissions: string[], purchasedFeatures: string[], claudeOn: boolean,
): SettingsNavItem[] {
  return getVisibleSettingsItems(purchasedFeatures, claudeOn).filter(
    (item) => role === "owner" || item.openToAll === true || item.permissionAny.some((permission) => permissions.includes(permission)),
  );
}

/** The grouped shape the sidebar list, the drawer and the home cards all render. */
export function groupSettingsItems(items: readonly SettingsNavItem[]): {
  groups: { group: SettingsGroup; items: SettingsNavItem[] }[];
  /** Items with no group, shown after the groups (Plans & subscription). */
  loose: SettingsNavItem[];
} {
  return {
    groups: SETTINGS_GROUP_ORDER.flatMap((group) => {
      const inGroup = items.filter((item) => item.group === group);
      return inGroup.length > 0 ? [{ group, items: inGroup }] : [];
    }),
    loose: items.filter((item) => item.group === null),
  };
}

/** The row to light up in a list: the item with the longest address that matches the page. */
export function activeSettingsItem(items: readonly SettingsNavItem[], pathname: string): SettingsNavItem | null {
  return items
    .filter((item) => matchesPath(pathname, item.href))
    .reduce<SettingsNavItem | null>((best, item) => (!best || item.href.length > best.href.length ? item : best), null);
}
