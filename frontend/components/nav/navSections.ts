import {
  ArrowDownToLine, BarChart2, BookOpen, Brain, Calendar, Coins, FileCheck, HandCoins,
  Layers, Megaphone, MessageSquare, MessageSquareText, Phone, PhoneCall, RadioTower, Send, Settings,
  ShoppingBag, Sparkles, StickyNote, Trophy, Upload, Users, Zap, type LucideIcon,
  BookUser, Code2, History, KeyRound, LayoutDashboard, ListChecks, ReceiptText, SlidersHorizontal,
} from "lucide-react";
import {
  SETTINGS_HOME_HREF, SETTINGS_ITEMS, isSettingsPath, settingsItemVisible,
} from "@/components/settingsNavigation";

/**
 * Everything the sidebar needs to decide what is visible. Built once per render
 * in sidebar.tsx from the same role/permission/feature state the old gates used,
 * so each item's `visible` predicate below is a verbatim copy of its old `if`.
 */
export interface NavAccess {
  isSubscribed: boolean;
  messagingOn: boolean;
  inboundOn: boolean;
  outboundOn: boolean;
  smsOn: boolean;
  canServices: boolean;
  canSettings: boolean;
  brainGate: boolean;
  telecallingVisible: boolean;
  can: (permission: string) => boolean;
  canAny: (permissions: string[]) => boolean;
}

export type SectionKey =
  | "engage"
  | "sms"
  | "otp"
  | "commerce"
  | "callIq"
  | "aiSetup"
  | "whatsappSetup";

/** Badge slots. The sidebar owns the live counts and renders them by key. */
export type NavBadgeKey = "conversations" | "brain";

/**
 * One address a menu row stands for. A row with `pages` is visible when ANY of
 * its pages is, opens the first visible one (see leafHref), and is active on all
 * of them. The same list feeds the chips in the page header (CHIP_SETS), so a
 * chip is hidden for exactly the users who could not open that page.
 */
export interface NavPage {
  key: string;
  /** The chip label. */
  label: string;
  href: string;
  visible: (access: NavAccess) => boolean;
  isActive: (pathname: string) => boolean;
}

export interface NavLeaf {
  kind: "link";
  key: string;
  href: string;
  label: string;
  icon: LucideIcon;
  badge?: NavBadgeKey;
  /** Set on rows that stand for several pages. `visible` and `isActive` are derived from it. */
  pages?: readonly NavPage[];
  visible: (access: NavAccess) => boolean;
  isActive: (pathname: string) => boolean;
}

/** A nested group rendered by sidebar.tsx with its own fold state (Telecalling). */
export interface NavGroup {
  kind: "group";
  key: "telecalling";
  label: string;
  icon: LucideIcon;
  visible: (access: NavAccess) => boolean;
  isActive: (pathname: string) => boolean;
}

export type NavEntry = NavLeaf | NavGroup;

export interface NavSection {
  key: SectionKey;
  title: string;
  /** Icon on the section's row in the sidebar. */
  icon: LucideIcon;
  entries: NavEntry[];
}

/**
 * One row of the main menu, top to bottom (Home sits above it). A link is a
 * one-page module shown as a plain row; a section folds open to its pages.
 * Order and names follow the v9.2 redesign menu (Phase 1: menu only, every
 * page keeps its address).
 */
export type NavMenuItem =
  | { kind: "link"; leaf: NavLeaf }
  | { kind: "section"; section: NavSection };

export interface TelecallingPage {
  href: string;
  label: string;
  icon: LucideIcon;
}

/** The four pages inside the Telecalling group. Per-page gates live in TC_FEATURE_MAP / TC_PERMISSION_MAP. */
export const TELECALLING_ITEMS: readonly TelecallingPage[] = [
  { href: "/dashboard/telecalling/upload", icon: Upload, label: "Upload" },
  { href: "/dashboard/telecalling", icon: Phone, label: "Dialer" },
  { href: "/dashboard/telecalling/scheduled", icon: Calendar, label: "Scheduled Calls" },
  { href: "/dashboard/notes", icon: StickyNote, label: "Call Review" },
];

export const TC_FEATURE_MAP: Record<string, string> = {
  "/dashboard/telecalling/upload": "telecalling.upload",
  "/dashboard/telecalling": "telecalling.dialer",
  "/dashboard/telecalling/scheduled": "telecalling.scheduled",
  "/dashboard/notes": "telecalling.notes",
};

export const TC_PERMISSION_MAP: Record<string, string[]> = {
  "/dashboard/telecalling/upload": ["telecalling.upload.view", "telecalling.upload"],
  "/dashboard/telecalling": ["telecalling.dialer.view", "telecalling.dialer"],
  "/dashboard/telecalling/scheduled": ["telecalling.scheduled.view", "telecalling.scheduled"],
  "/dashboard/notes": ["telecalling.notes.view", "telecalling.notes"],
};

/** A row that stands for several pages: visible if any page is, active on any page. `href` is the first page's. */
function pagesLeaf(leaf: Pick<NavLeaf, "key" | "label" | "icon"> & { pages: readonly NavPage[] }): NavLeaf {
  return {
    kind: "link",
    ...leaf,
    href: leaf.pages[0].href,
    visible: (a) => leaf.pages.some((page) => page.visible(a)),
    isActive: (p) => leaf.pages.some((page) => page.isActive(p)),
  };
}

/** Where a row opens for this user: the first of its pages they can see, else the row's own address. */
export function leafHref(leaf: NavLeaf, access: NavAccess): string {
  return leaf.pages?.find((page) => page.visible(access))?.href ?? leaf.href;
}

const startsWithAny = (pathname: string, prefixes: readonly string[]): boolean =>
  prefixes.some((prefix) => pathname.startsWith(prefix));

/** Top-level slot: Dashboard for dashboard.view holders, otherwise Overview. */
export function dashboardEntry(access: NavAccess): { href: string; label: string } {
  return access.can("dashboard.view")
    ? { href: "/dashboard", label: "Home" }
    : { href: "/dashboard/profile", label: "Overview" };
}

export const ANALYTICS_LINK: NavLeaf = {
  kind: "link",
  key: "analytics",
  href: "/dashboard/analytics",
  label: "Reports",
  icon: BarChart2,
  visible: (a) => a.isSubscribed && a.can("analytics.view") && a.messagingOn,
  isActive: (p) => p.startsWith("/dashboard/analytics"),
};

const CONVERSATIONS: NavLeaf = {
  kind: "link",
  key: "conversations",
  href: "/dashboard/conversations",
  label: "Chats",
  icon: MessageSquare,
  badge: "conversations",
  visible: (a) => a.isSubscribed && a.messagingOn && a.canAny(["conversations.view", "conversations.reply"]),
  isActive: (p) => p.startsWith("/dashboard/conversations"),
};

const SEGMENTS: NavLeaf = {
  kind: "link",
  key: "segments",
  href: "/dashboard/leads",
  label: "Customers",
  icon: Users,
  visible: (a) => a.isSubscribed && a.can("leads.view") && a.messagingOn,
  isActive: (p) => p.startsWith("/dashboard/leads"),
};

const INBOUND_LEADS: NavLeaf = {
  kind: "link",
  key: "inbound-leads",
  href: "/dashboard/inbound-leads",
  label: "Inbound Leads",
  icon: ArrowDownToLine,
  visible: (a) => a.isSubscribed && a.can("inbound_leads.view") && a.inboundOn,
  isActive: (p) => p.startsWith("/dashboard/inbound-leads"),
};

const META_ADS: NavLeaf = {
  kind: "link",
  key: "meta-ads",
  href: "/dashboard/meta-ads",
  label: "Meta Ads",
  icon: Megaphone,
  visible: (a) => a.isSubscribed && a.canAny(["meta_ads.view", "meta_ads.manage"]) && a.inboundOn,
  isActive: (p) => p.startsWith("/dashboard/meta-ads"),
};

const prefixPage = (key: string, label: string, href: string, visible: NavPage["visible"]): NavPage => ({
  key, label, href, visible, isActive: (p) => p.startsWith(href),
});

/** Follow-ups was a Settings page, so it keeps the Settings gate. */
const settingsVisible = (a: NavAccess) => a.isSubscribed && a.canSettings;

const AUTO_MESSAGE_PAGES: readonly NavPage[] = [
  prefixPage(
    "auto-messages", "When something happens", "/dashboard/auto-messages",
    (a) => a.isSubscribed && a.canAny(["auto_messages.view", "auto_messages.manage"]) && a.outboundOn,
  ),
  prefixPage("follow-ups", "Follow-ups", "/dashboard/settings/follow-ups", settingsVisible),
  prefixPage(
    "scheduled-templates", "One-time sends", "/dashboard/scheduled-templates",
    (a) =>
      a.isSubscribed &&
      a.canAny(["leads.manage", "conversations.reply", "telecalling.dialer", "outbound_leads.view", "outbound_leads.manage"]) &&
      (a.outboundOn || a.messagingOn),
  ),
];

const AUTO_MESSAGES = pagesLeaf({ key: "auto-messages", label: "Auto-Messages", icon: Zap, pages: AUTO_MESSAGE_PAGES });

const REPLY_PAGES: readonly NavPage[] = [
  prefixPage("auto-reply", "Auto-reply", "/dashboard/settings/auto-reply", settingsVisible),
  prefixPage("inbox", "Handover", "/dashboard/settings/inbox", settingsVisible),
];

const REPLIES_AND_HANDOVER = pagesLeaf({ key: "replies-handover", label: "Replies & handover", icon: Sparkles, pages: REPLY_PAGES });

const OUTBOUND_LEADS: NavLeaf = {
  kind: "link",
  key: "outbound-leads",
  href: "/dashboard/outbound-leads",
  label: "Reach",
  icon: Send,
  visible: (a) => a.isSubscribed && a.canAny(["outbound_leads.view", "outbound_leads.manage"]) && a.outboundOn,
  isActive: (p) => p.startsWith("/dashboard/outbound-leads"),
};

const smsVisible = (a: NavAccess) => a.isSubscribed && a.smsOn && a.canAny(["sms.view", "sms.manage"]);

/** Anril SMS pages, in the order of the reseller panel clients know. Slug "" is the SMS dashboard. */
const SMS_PAGES: NavLeaf[] = ([
  ["", "Dashboard", LayoutDashboard],
  ["setup", "DLT Setup", ListChecks],
  ["send", "Send SMS", Send],
  ["contacts", "Address Book", BookUser],
  ["reports", "Delivery Reports", BarChart2],
  ["transactions", "Transactions", ReceiptText],
  ["developer", "Dev API", Code2],
] as const satisfies readonly (readonly [string, string, LucideIcon])[]).map(([slug, label, icon]): NavLeaf => {
  const href = slug ? `/dashboard/sms/${slug}` : "/dashboard/sms";
  return {
    kind: "link",
    key: slug ? `sms-${slug}` : "sms",
    href,
    label,
    icon,
    visible: smsVisible,
    isActive: (p) => (slug ? p === href || p.startsWith(`${href}/`) : p === href),
  };
});

/** Anril OTP is its own section, not under SMS, so WhatsApp-only clients can reach it (not gated on smsOn).
 *  Same permission list as MoreMenu OTP_PERMS and the backend's routes/otp.py `view`. */
const otpVisible = (a: NavAccess) => a.isSubscribed && a.canAny(["sms.view", "sms.manage", "settings.view", "settings.manage"]);

const exactOrChild = (href: string) => (p: string) => p === href || p.startsWith(`${href}/`);

const OTP_SETUP_PAGES: readonly NavPage[] = [
  { key: "otp-settings", label: "Rules", href: "/dashboard/otp/settings", visible: otpVisible, isActive: exactOrChild("/dashboard/otp/settings") },
  { key: "otp-api", label: "Connect your website", href: "/dashboard/otp/api", visible: otpVisible, isActive: exactOrChild("/dashboard/otp/api") },
];

const OTP_PAGES: NavLeaf[] = [
  ...([
    ["", "Send & check", KeyRound],
    ["history", "History", History],
  ] as const satisfies readonly (readonly [string, string, LucideIcon])[]).map(([slug, label, icon]): NavLeaf => {
    const href = slug ? `/dashboard/otp/${slug}` : "/dashboard/otp";
    return {
      kind: "link",
      key: slug ? `otp-${slug}` : "otp",
      href,
      label,
      icon,
      visible: otpVisible,
      isActive: (p) => (slug ? p === href || p.startsWith(`${href}/`) : p === href),
    };
  }),
  pagesLeaf({ key: "otp-settings", label: "Setup", icon: SlidersHorizontal, pages: OTP_SETUP_PAGES }),
];

const DEALS: NavLeaf = {
  kind: "link",
  key: "deals",
  href: "/dashboard/deals",
  label: "Orders & payments",
  icon: HandCoins,
  visible: (a) => a.isSubscribed && a.canAny(["deals.view", "deals.manage"]),
  isActive: (p) => p.startsWith("/dashboard/deals") || p.startsWith("/dashboard/intake"),
};

/**
 * Catalogue replaces the old Products and Services items. It shows when EITHER
 * old gate passed: Products = isSubscribed && catalog perms && messagingOn,
 * Services = isSubscribed && canServices && messagingOn.
 */
const CATALOGUE: NavLeaf = {
  kind: "link",
  key: "catalogue",
  href: "/dashboard/catalog",
  label: "Catalogue",
  icon: ShoppingBag,
  visible: (a) =>
    a.isSubscribed && a.messagingOn &&
    (a.canAny(["catalog.view", "catalog.manage"]) || a.canServices),
  isActive: (p) => startsWithAny(p, ["/dashboard/catalog", "/dashboard/services", "/dashboard/forms"]),
};

const TELECALLING_GROUP: NavGroup = {
  kind: "group",
  key: "telecalling",
  label: "Telecalling",
  icon: PhoneCall,
  visible: (a) => a.telecallingVisible,
  isActive: (p) => startsWithAny(p, ["/dashboard/telecalling", "/dashboard/notes"]),
};

const TEAM_PERFORMANCE: NavLeaf = {
  kind: "link",
  key: "team-performance",
  href: "/dashboard/team",
  label: "Team Performance",
  icon: Trophy,
  visible: (a) => a.isSubscribed && a.can("team.view"),
  isActive: (p) => p.startsWith("/dashboard/team"),
};

const ANRIL_BRAIN: NavLeaf = {
  kind: "link",
  key: "anril-brain",
  href: "/dashboard/brain",
  label: "Anril Brain",
  icon: Brain,
  badge: "brain",
  visible: (a) => a.brainGate,
  isActive: (p) => p.startsWith("/dashboard/brain"),
};

const KNOWLEDGE_BASE: NavLeaf = {
  kind: "link",
  key: "knowledge-base",
  href: "/dashboard/knowledge",
  label: "Knowledge Base",
  icon: BookOpen,
  visible: (a) => a.isSubscribed && a.canAny(["knowledge.view", "knowledge.manage"]) && a.messagingOn,
  isActive: (p) => p.startsWith("/dashboard/knowledge"),
};

const TEMPLATES: NavLeaf = {
  kind: "link",
  key: "templates",
  href: "/dashboard/templates",
  label: "Templates",
  icon: FileCheck,
  visible: (a) => a.isSubscribed && a.canAny(["templates.view", "templates.manage"]) && a.outboundOn,
  isActive: (p) => p.startsWith("/dashboard/templates"),
};

const NUMBERS_POOL: NavLeaf = {
  kind: "link",
  key: "numbers-pool",
  href: "/dashboard/numbers",
  label: "Numbers",
  icon: Layers,
  visible: (a) => a.isSubscribed && a.canAny(["numbers.view", "numbers.manage"]) && a.messagingOn,
  isActive: (p) => p.startsWith("/dashboard/numbers"),
};

/**
 * The last row of the menu. It stands for every page in the Settings list (see
 * SETTINGS_ITEMS) and keeps each page's own gate: it shows if the user may open
 * ANY of them, and opens the Settings home, or, when the user may open only Plans
 * & subscription (no active subscription: the dashboard layout sends them away
 * from everything else), that page. It is active on all of them.
 */
const SETTINGS_PAGES: readonly NavPage[] = [
  {
    key: "settings-home",
    label: "Settings",
    href: SETTINGS_HOME_HREF,
    visible: (a) => a.isSubscribed && SETTINGS_ITEMS.some((item) => settingsItemVisible(item, a)),
    isActive: isSettingsPath,
  },
  ...SETTINGS_ITEMS.map((item): NavPage => ({
    key: item.href,
    label: item.label,
    href: item.href,
    visible: (a) => settingsItemVisible(item, a),
    isActive: isSettingsPath,
  })),
];

const SETTINGS = pagesLeaf({ key: "settings", label: "Settings", icon: Settings, pages: SETTINGS_PAGES });

const ENGAGE: NavSection = { key: "engage", title: "Engage", icon: RadioTower, entries: [INBOUND_LEADS, META_ADS, AUTO_MESSAGES] };
const SMS: NavSection = { key: "sms", title: "Anril SMS", icon: MessageSquareText, entries: SMS_PAGES };
const OTP: NavSection = { key: "otp", title: "Anril OTP", icon: KeyRound, entries: OTP_PAGES };
const COMMERCE: NavSection = { key: "commerce", title: "Commerce", icon: Coins, entries: [DEALS, CATALOGUE] };
const CALL_IQ: NavSection = { key: "callIq", title: "Call IQ", icon: Phone, entries: [TELECALLING_GROUP, TEAM_PERFORMANCE] };
const AI_SETUP: NavSection = { key: "aiSetup", title: "Anril Setup", icon: Brain, entries: [ANRIL_BRAIN, KNOWLEDGE_BASE, REPLIES_AND_HANDOVER] };
const WHATSAPP: NavSection = { key: "whatsappSetup", title: "WhatsApp", icon: FileCheck, entries: [TEMPLATES, NUMBERS_POOL] };

/** The main menu below Home, top to bottom. */
export const NAV_MENU: readonly NavMenuItem[] = [
  { kind: "link", leaf: CONVERSATIONS },
  { kind: "link", leaf: SEGMENTS },
  { kind: "section", section: WHATSAPP },
  { kind: "section", section: AI_SETUP },
  { kind: "section", section: ENGAGE },
  { kind: "link", leaf: OUTBOUND_LEADS },
  { kind: "section", section: OTP },
  { kind: "section", section: SMS },
  { kind: "section", section: COMMERCE },
  { kind: "section", section: CALL_IQ },
  { kind: "link", leaf: ANALYTICS_LINK },
  { kind: "link", leaf: SETTINGS },
];

/** The folding sections of the menu, in render order. */
export const NAV_SECTIONS: readonly NavSection[] = NAV_MENU.flatMap((item) => (item.kind === "section" ? [item.section] : []));

/** The plain rows of the menu (Chats, Customers, Reach, Reports, Settings). */
export const NAV_LINKS: readonly NavLeaf[] = NAV_MENU.flatMap((item) => (item.kind === "link" ? [item.leaf] : []));

/** Visible entries only, in render order. Empty means the section heading is hidden. */
export function visibleEntries(section: NavSection, access: NavAccess): NavEntry[] {
  return section.entries.filter((entry) => entry.visible(access));
}

/**
 * The one open section (an accordion, so the menu never grows past the
 * screen). A click wins (null = all shut); otherwise the section holding the
 * current page. Pages outside every section (Home and the plain links) shut all.
 */
export function resolveOpenSection(
  choice: string | null | undefined,
  sections: readonly NavSection[],
  pathname: string,
): string | null {
  if (choice !== undefined) return choice;
  return sections.find((s) => sectionContainsPage(s, pathname))?.key ?? null;
}

export function sectionContainsPage(section: NavSection, pathname: string): boolean {
  return section.entries.some((entry) => entry.isActive(pathname));
}

/** Wide pages that fold the desktop sidebar to its icon strip when opened. */
const FOLDS_SIDEBAR: readonly NavEntry[] = [CONVERSATIONS, SEGMENTS, INBOUND_LEADS, OUTBOUND_LEADS, DEALS, TELECALLING_GROUP];

export function sidebarFoldsOn(pathname: string): boolean {
  return FOLDS_SIDEBAR.some((entry) => entry.isActive(pathname));
}

export interface ChipSet {
  key: "autoMessages" | "replies" | "otpSetup";
  /** The menu row these pages share. */
  leafKey: string;
  chips: readonly NavPage[];
}

/** The pages that share one menu row, in chip order. The page header renders these as a row of chips. */
export const CHIP_SETS: readonly ChipSet[] = [
  { key: "autoMessages", leafKey: AUTO_MESSAGES.key, chips: AUTO_MESSAGE_PAGES },
  { key: "replies", leafKey: REPLIES_AND_HANDOVER.key, chips: REPLY_PAGES },
  { key: "otpSetup", leafKey: "otp-settings", chips: OTP_SETUP_PAGES },
];

/** The chip set for the page you are on, or null when the page has no siblings. */
export function chipSetFor(pathname: string): ChipSet | null {
  return CHIP_SETS.find((set) => set.chips.some((chip) => chip.isActive(pathname))) ?? null;
}
