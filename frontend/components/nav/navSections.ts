import {
  BarChart2, BookOpen, Brain, Calendar, CalendarClock, CreditCard, FileCheck, HandCoins, Layers,
  Megaphone, MessageSquare, Phone, RadioTower, Settings, ShieldCheck, ShoppingBag,
  StickyNote, Upload, Users, Zap, type LucideIcon,
} from "lucide-react";
import { SETTINGS_ITEMS } from "@/components/settingsNavigation";

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
  canServices: boolean;
  canSettings: boolean;
  brainGate: boolean;
  telecallingVisible: boolean;
  can: (permission: string) => boolean;
  canAny: (permissions: string[]) => boolean;
}

export type SectionKey =
  | "inbox"
  | "engage"
  | "reach"
  | "commerce"
  | "callIq"
  | "aiSetup"
  | "whatsappSetup"
  | "account";

/** Badge slots. The sidebar owns the live counts and renders them by key. */
export type NavBadgeKey = "conversations" | "brain";

export interface NavLeaf {
  kind: "link";
  key: string;
  href: string;
  label: string;
  icon: LucideIcon;
  badge?: NavBadgeKey;
  visible: (access: NavAccess) => boolean;
  isActive: (pathname: string) => boolean;
}

/** A nested group rendered by sidebar.tsx with its own fold state (Telecalling, Settings). */
export interface NavGroup {
  kind: "group";
  key: "telecalling" | "settings";
  label: string;
  icon: LucideIcon;
  visible: (access: NavAccess) => boolean;
  isActive: (pathname: string) => boolean;
}

export type NavEntry = NavLeaf | NavGroup;

export interface NavSection {
  key: SectionKey;
  title: string;
  defaultOpen: boolean;
  entries: NavEntry[];
}

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

const startsWithAny = (pathname: string, prefixes: readonly string[]): boolean =>
  prefixes.some((prefix) => pathname.startsWith(prefix));

/** Top-level slot: Dashboard for dashboard.view holders, otherwise Overview. */
export function dashboardEntry(access: NavAccess): { href: string; label: string } {
  return access.can("dashboard.view")
    ? { href: "/dashboard", label: "Dashboard" }
    : { href: "/dashboard/profile", label: "Overview" };
}

export const ANALYTICS_LINK: NavLeaf = {
  kind: "link",
  key: "analytics",
  href: "/dashboard/analytics",
  label: "Analytics",
  icon: BarChart2,
  visible: (a) => a.isSubscribed && a.can("analytics.view") && a.messagingOn,
  isActive: (p) => p.startsWith("/dashboard/analytics"),
};

const CONVERSATIONS: NavLeaf = {
  kind: "link",
  key: "conversations",
  href: "/dashboard/conversations",
  label: "Conversations",
  icon: MessageSquare,
  badge: "conversations",
  visible: (a) => a.isSubscribed && a.messagingOn && a.canAny(["conversations.view", "conversations.reply"]),
  isActive: (p) => p.startsWith("/dashboard/conversations"),
};

const SEGMENTS: NavLeaf = {
  kind: "link",
  key: "segments",
  href: "/dashboard/leads",
  label: "Segments",
  icon: Users,
  visible: (a) => a.isSubscribed && a.can("leads.view") && a.messagingOn,
  isActive: (p) => p.startsWith("/dashboard/leads"),
};

const INBOUND_LEADS: NavLeaf = {
  kind: "link",
  key: "inbound-leads",
  href: "/dashboard/inbound-leads",
  label: "Inbound Leads",
  icon: RadioTower,
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

const AUTO_MESSAGES: NavLeaf = {
  kind: "link",
  key: "auto-messages",
  href: "/dashboard/auto-messages",
  label: "Auto-Messages",
  icon: Zap,
  visible: (a) => a.isSubscribed && a.canAny(["auto_messages.view", "auto_messages.manage"]) && a.outboundOn,
  isActive: (p) => p.startsWith("/dashboard/auto-messages"),
};

const SCHEDULED_TEMPLATES: NavLeaf = {
  kind: "link",
  key: "scheduled-templates",
  href: "/dashboard/scheduled-templates",
  label: "Scheduled templates",
  icon: CalendarClock,
  visible: (a) =>
    a.isSubscribed &&
    a.canAny(["leads.manage", "conversations.reply", "telecalling.dialer", "outbound_leads.view", "outbound_leads.manage"]) &&
    (a.outboundOn || a.messagingOn),
  isActive: (p) => p.startsWith("/dashboard/scheduled-templates"),
};

const OUTBOUND_LEADS: NavLeaf = {
  kind: "link",
  key: "outbound-leads",
  href: "/dashboard/outbound-leads",
  label: "Outbound Leads",
  icon: Upload,
  visible: (a) => a.isSubscribed && a.canAny(["outbound_leads.view", "outbound_leads.manage"]) && a.outboundOn,
  isActive: (p) => p.startsWith("/dashboard/outbound-leads"),
};

const DEALS: NavLeaf = {
  kind: "link",
  key: "deals",
  href: "/dashboard/deals",
  label: "Deals",
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
  isActive: (p) => startsWithAny(p, ["/dashboard/catalog", "/dashboard/services"]),
};

const TELECALLING_GROUP: NavGroup = {
  kind: "group",
  key: "telecalling",
  label: "Telecalling",
  icon: Phone,
  visible: (a) => a.telecallingVisible,
  isActive: (p) => startsWithAny(p, ["/dashboard/telecalling", "/dashboard/notes"]),
};

const TEAM_PERFORMANCE: NavLeaf = {
  kind: "link",
  key: "team-performance",
  href: "/dashboard/team",
  label: "Team Performance",
  icon: Users,
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
  label: "Numbers Pool",
  icon: Layers,
  visible: (a) => a.isSubscribed && a.canAny(["numbers.view", "numbers.manage"]) && a.messagingOn,
  isActive: (p) => p.startsWith("/dashboard/numbers"),
};

const USERS_AND_ROLES: NavLeaf = {
  kind: "link",
  key: "users-and-roles",
  href: "/dashboard/roles",
  label: "Users & Roles",
  icon: ShieldCheck,
  visible: (a) => a.isSubscribed && a.canAny(["roles.view", "roles.manage"]),
  isActive: (p) => p.startsWith("/dashboard/roles"),
};

const SUBSCRIPTION: NavLeaf = {
  kind: "link",
  key: "subscription",
  href: "/dashboard/subscription",
  label: "Subscription",
  icon: CreditCard,
  visible: (a) => a.canAny(["subscription.view", "subscription.manage"]),
  isActive: (p) => p === "/dashboard/subscription",
};

const SETTINGS_GROUP: NavGroup = {
  kind: "group",
  key: "settings",
  label: "Settings",
  icon: Settings,
  visible: (a) => a.isSubscribed && a.canSettings,
  isActive: (p) => SETTINGS_ITEMS.some((item) => p.startsWith(item.href)),
};

/** Sections render top to bottom in this order. Dashboard and Analytics sit above them. */
export const NAV_SECTIONS: readonly NavSection[] = [
  { key: "inbox", title: "INBOX & LEADS", defaultOpen: true, entries: [CONVERSATIONS, SEGMENTS] },
  { key: "engage", title: "ANRIL ENGAGE", defaultOpen: false, entries: [INBOUND_LEADS, META_ADS, AUTO_MESSAGES, SCHEDULED_TEMPLATES] },
  { key: "reach", title: "ANRIL REACH", defaultOpen: false, entries: [OUTBOUND_LEADS] },
  { key: "commerce", title: "SALES · ANRIL COMMERCE", defaultOpen: false, entries: [DEALS, CATALOGUE] },
  { key: "callIq", title: "ANRIL CALL IQ", defaultOpen: false, entries: [TELECALLING_GROUP, TEAM_PERFORMANCE] },
  { key: "aiSetup", title: "AI SETUP", defaultOpen: false, entries: [ANRIL_BRAIN, KNOWLEDGE_BASE] },
  { key: "whatsappSetup", title: "WHATSAPP SETUP", defaultOpen: false, entries: [TEMPLATES, NUMBERS_POOL] },
  { key: "account", title: "ACCOUNT", defaultOpen: false, entries: [USERS_AND_ROLES, SUBSCRIPTION, SETTINGS_GROUP] },
];

/** Visible entries only, in render order. Empty means the section heading is hidden. */
export function visibleEntries(section: NavSection, access: NavAccess): NavEntry[] {
  return section.entries.filter((entry) => entry.visible(access));
}

/** Explicit user click wins. Otherwise open if it is a default-open section or holds the current page. */
export function resolveSectionOpen(
  explicit: boolean | undefined,
  defaultOpen: boolean,
  containsActivePage: boolean,
): boolean {
  if (explicit !== undefined) return explicit;
  return defaultOpen || containsActivePage;
}

export function sectionContainsPage(section: NavSection, pathname: string): boolean {
  return section.entries.some((entry) => entry.isActive(pathname));
}
