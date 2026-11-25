import {
  BarChart2,
  RadioTower,
  MessageSquare,
  BookOpen,
  Brain,
  Grid3X3,
  HandCoins,
  History,
  Inbox,
  Layers,
  Megaphone,
  BookUser,
  Code2,
  KeyRound,
  LayoutDashboard,
  ListChecks,
  ReceiptText,
  Send,
  ShoppingBag,
  SlidersHorizontal,
  SquarePen,
  Sparkles,
  Zap,
  StickyNote,
  Users,
  Truck, Wallet, GraduationCap, CalendarClock, QrCode, MousePointerClick } from "lucide-react";
import { isActive } from "@/lib/utils";

const BRAIN_HREF = "/dashboard/brain";

export type MoreMenuGate = {
  permissionAny?: string[];
  feature?: string;
  anyFeature?: string[];
  /** Roles that never see this entry, whatever their permissions (the page's endpoint refuses them). */
  hiddenForRoles?: string[];
};

export type MoreMenuSection =
  | "customers"
  | "whatsapp"
  | "setup"
  | "engage"
  | "reach"
  | "otp"
  | "sms"
  | "commerce"
  | "callIq"
  | "reports"
  | "settings";

/** One page a row can open. */
export type MoreMenuPage = MoreMenuGate & {
  href: string;
  /** Extra gate: the page is also allowed when this gate passes (used by Catalogue). */
  alsoVisibleIf?: MoreMenuGate;
  /** Extra paths that also highlight the row as active. */
  activePrefixes?: string[];
  /** Active on its own path only, not its sub-pages (the SMS dashboard). */
  exact?: boolean;
  /** For pages that are one view of a path (Upload, Team): active only when this holds for the current ?tab= value. `href` may carry the ?tab= it opens. */
  activeWhen?: (tab: string) => boolean;
};

/**
 * One drawer row. Most rows stand for one page. A row that stands for several
 * (Auto-Messages, Setup, Replies & handover, Leads to call) shows when the user may open ANY of
 * its pages, opens the first one they may open (the order of `pages`), and is
 * active on all of them.
 */
export type MoreMenuItem = {
  key: string;
  icon: typeof Users;
  label: string;
  section: MoreMenuSection;
  pages: MoreMenuPage[];
};

/** Render order. `title: null` renders the rows with no heading. */
export const MORE_SECTIONS: readonly { key: MoreMenuSection; title: string | null }[] = [
  { key: "customers", title: null },
  { key: "whatsapp", title: "WhatsApp" },
  { key: "setup", title: "Anril Setup" },
  { key: "engage", title: "Engage" },
  { key: "reach", title: null },
  { key: "otp", title: "Anril OTP" },
  { key: "sms", title: "Anril SMS" },
  { key: "commerce", title: "Commerce" },
  { key: "callIq", title: "Call IQ" },
  { key: "reports", title: null },
  // The Settings box below carries its own "Settings" heading, so the section has none.
  { key: "settings", title: null },
];

const MESSAGING_FEATURES = ["outbound_messaging", "inbound_messaging"];
const SMS_PERMS = ["sms.view", "sms.manage"];
/** Anril OTP is not behind the SMS feature flag, so it is gated by permissions only. */
// Same rule as the desktop sidebar (navSections.otpVisible) and the backend (routes/otp.py `view`).
const OTP_PERMS = ["sms.view", "sms.manage", "settings.view", "settings.manage"];
/** The gate the Settings box uses; the pages that used to live under Settings keep it. */
const SETTINGS_PERMS = ["settings.view", "settings.manage"];
/** The gates the Call IQ pages had in the drawer (scheduled, notes, team) and, for the Upload page, in the sidebar. */
const SCHEDULED_GATE: MoreMenuGate = { permissionAny: ["telecalling.scheduled.view", "telecalling.scheduled"], feature: "telecalling.scheduled" };
const UPLOAD_GATE: MoreMenuGate = { permissionAny: ["telecalling.upload.view", "telecalling.upload"], feature: "telecalling.upload" };
const TEAM_GATE: MoreMenuGate = { permissionAny: ["team.view", "team.manage"] };

const sms = (href: string, icon: typeof Users, label: string, exact?: boolean): MoreMenuItem => ({
  key: href, icon, label, section: "sms", pages: [{ href, permissionAny: SMS_PERMS, feature: "sms", exact }],
});

export const MORE_ITEMS: MoreMenuItem[] = [
  { key: "leads", icon: Users, label: "Customers", section: "customers", pages: [{ href: "/dashboard/leads", permissionAny: ["leads.view", "leads.manage"], anyFeature: MESSAGING_FEATURES }] },
  { key: "templates", icon: SquarePen, label: "Templates", section: "whatsapp", pages: [{ href: "/dashboard/templates", permissionAny: ["templates.view", "templates.manage"], feature: "outbound_messaging" }] },
  { key: "numbers", icon: Layers, label: "Numbers", section: "whatsapp", pages: [{ href: "/dashboard/numbers", permissionAny: ["numbers.view", "numbers.manage"], anyFeature: MESSAGING_FEATURES }] },
  { key: "qr-links", icon: QrCode, label: "QR & links", section: "whatsapp", pages: [{ href: "/dashboard/qr-links", permissionAny: ["numbers.view", "numbers.manage"], anyFeature: MESSAGING_FEATURES }] },
  { key: "brain", icon: Brain, label: "Anril Brain", section: "setup", pages: [{ href: BRAIN_HREF, exact: true, permissionAny: ["brain.view"], anyFeature: MESSAGING_FEATURES }] },
  { key: "couldnt-answer", icon: MessageSquare, label: "Couldn't answer", section: "setup", pages: [{ href: "/dashboard/brain/couldnt-answer", permissionAny: ["knowledge.view", "knowledge.manage"], anyFeature: MESSAGING_FEATURES }] },
  { key: "ai-report-card", icon: ReceiptText, label: "AI report card", section: "setup", pages: [{ href: "/dashboard/brain/report-card", permissionAny: ["knowledge.view", "knowledge.manage"], anyFeature: MESSAGING_FEATURES, hiddenForRoles: ["caller"] }] },
  { key: "questions-scoring", icon: SlidersHorizontal, label: "Questions & scoring", section: "setup", pages: [{ href: "/dashboard/brain/scoring", permissionAny: ["knowledge.view", "knowledge.manage"], anyFeature: MESSAGING_FEATURES }] },
  { key: "knowledge", icon: BookOpen, label: "Knowledge Base", section: "setup", pages: [{ href: "/dashboard/knowledge", permissionAny: ["knowledge.view", "knowledge.manage"], anyFeature: MESSAGING_FEATURES }] },
  { key: "teach", icon: GraduationCap, label: "Teach & offers", section: "setup", pages: [{ href: "/dashboard/teach", permissionAny: ["knowledge.view", "knowledge.manage"], anyFeature: MESSAGING_FEATURES }] },
  {
    key: "replies",
    icon: Sparkles,
    label: "Replies & handover",
    section: "setup",
    pages: [
      { href: "/dashboard/settings/auto-reply", permissionAny: SETTINGS_PERMS },
      { href: "/dashboard/settings/inbox", permissionAny: SETTINGS_PERMS },
    ],
  },
  { key: "inbound-leads", icon: Inbox, label: "Inbound Leads", section: "engage", pages: [{ href: "/dashboard/inbound-leads", permissionAny: ["inbound_leads.view", "inbound_leads.manage"], feature: "inbound_messaging" }] },
  { key: "bookings", icon: CalendarClock, label: "Bookings", section: "engage", pages: [{ href: "/dashboard/bookings", permissionAny: ["bookings.view", "bookings.manage"] }] },
  { key: "meta-ads", icon: Megaphone, label: "Meta Ads", section: "engage", pages: [{ href: "/dashboard/meta-ads", permissionAny: ["meta_ads.view", "meta_ads.manage"], feature: "inbound_messaging" }] },
  { key: "google-ads", icon: MousePointerClick, label: "Google Ads", section: "engage", pages: [{ href: "/dashboard/google-ads", permissionAny: ["meta_ads.view", "meta_ads.manage"], feature: "inbound_messaging" }] },
  {
    key: "auto-messages",
    icon: Zap,
    label: "Auto-Messages",
    section: "engage",
    pages: [
      { href: "/dashboard/auto-messages", permissionAny: ["auto_messages.view", "auto_messages.manage"], feature: "outbound_messaging" },
      { href: "/dashboard/settings/follow-ups", permissionAny: SETTINGS_PERMS },
      { href: "/dashboard/scheduled-templates", permissionAny: ["leads.manage", "conversations.reply", "telecalling.dialer", "outbound_leads.view", "outbound_leads.manage"], anyFeature: MESSAGING_FEATURES },
    ],
  },
  { key: "reach", icon: Send, label: "Reach", section: "reach", pages: [{ href: "/dashboard/outbound-leads", permissionAny: ["outbound_leads.view", "outbound_leads.manage"], feature: "outbound_messaging" }] },
  { key: "otp-send", icon: KeyRound, label: "Send & check", section: "otp", pages: [{ href: "/dashboard/otp", permissionAny: OTP_PERMS, exact: true }] },
  { key: "otp-history", icon: History, label: "History", section: "otp", pages: [{ href: "/dashboard/otp/history", permissionAny: OTP_PERMS }] },
  {
    key: "otp-setup",
    icon: SlidersHorizontal,
    label: "Setup",
    section: "otp",
    pages: [
      { href: "/dashboard/otp/settings", permissionAny: OTP_PERMS },
      { href: "/dashboard/otp/api", permissionAny: OTP_PERMS },
    ],
  },
  sms("/dashboard/sms", LayoutDashboard, "Dashboard", true),
  sms("/dashboard/sms/setup", ListChecks, "DLT Setup"),
  sms("/dashboard/sms/send", Send, "Send SMS"),
  sms("/dashboard/sms/contacts", BookUser, "Address Book"),
  sms("/dashboard/sms/reports", BarChart2, "Delivery Reports"),
  sms("/dashboard/sms/transactions", ReceiptText, "Transactions"),
  sms("/dashboard/sms/developer", Code2, "Dev API"),
  { key: "deals", icon: HandCoins, label: "Orders & payments", section: "commerce", pages: [{ href: "/dashboard/deals", permissionAny: ["deals.view", "deals.manage"] }] },
  {
    key: "catalog",
    icon: ShoppingBag,
    label: "Catalogue",
    section: "commerce",
    pages: [{
      href: "/dashboard/catalog",
      permissionAny: ["catalog.view", "catalog.manage"],
      anyFeature: MESSAGING_FEATURES,
      alsoVisibleIf: { permissionAny: ["services.view", "services.manage"], anyFeature: MESSAGING_FEATURES },
      activePrefixes: ["/dashboard/catalog", "/dashboard/services"],
    }],
  },
  { key: "purchases", icon: Truck, label: "Purchases", section: "commerce", pages: [{ href: "/dashboard/purchases", permissionAny: ["purchases.view", "purchases.manage"] }] },
  { key: "expenses", icon: Wallet, label: "Expenses", section: "commerce", pages: [{ href: "/dashboard/expenses", permissionAny: ["purchases.view", "purchases.manage"] }] },
  {
    key: "leads-to-call",
    icon: ListChecks,
    label: "Leads to call",
    section: "callIq",
    pages: [
      // Call lists and Uploads are two views of the Upload page; the Upload page opens Call lists for any other ?tab=.
      { href: "/dashboard/telecalling/upload", ...UPLOAD_GATE, activeWhen: (tab) => tab !== "scripts" },
      { href: "/dashboard/telecalling/scheduled", ...SCHEDULED_GATE },
      { href: "/dashboard/telecalling/upload?tab=history", ...UPLOAD_GATE, activeWhen: (tab) => tab === "history" },
      { href: "/dashboard/team?tab=log", ...TEAM_GATE, activeWhen: (tab) => tab === "log" },
    ],
  },
  { key: "call-reviews", icon: StickyNote, label: "Call reviews", section: "callIq", pages: [{ href: "/dashboard/notes", permissionAny: ["telecalling.notes.view", "telecalling.notes"], feature: "telecalling.notes" }] },
  { key: "team", icon: Grid3X3, label: "Team", section: "callIq", pages: [{ href: "/dashboard/team", ...TEAM_GATE, activeWhen: (tab) => tab !== "log" }] },
  { key: "call-iq-live", icon: RadioTower, label: "Live", section: "callIq", pages: [{ href: "/dashboard/call-iq/live", permissionAny: ["team.view", "telecalling.view"] }] },
  { key: "call-iq-evaluation", icon: ListChecks, label: "Evaluation", section: "callIq", pages: [{ href: "/dashboard/call-iq/evaluation", permissionAny: ["team.view"] }] },
  { key: "call-iq-results", icon: BarChart2, label: "Results", section: "callIq", pages: [{ href: "/dashboard/call-iq/results", permissionAny: ["team.view"] }] },
  { key: "analytics", icon: BarChart2, label: "Reports", section: "reports", pages: [{ href: "/dashboard/analytics", permissionAny: ["analytics.view"], anyFeature: MESSAGING_FEATURES }] },
];

function passesGate(gate: MoreMenuGate, role: string | null, enabledFeatures: string[], permissions: string[]) {
  if (role && gate.hiddenForRoles?.includes(role)) return false;
  if (role !== "owner" && gate.permissionAny && !gate.permissionAny.some((permission) => permissions.includes(permission))) return false;
  if (gate.feature && !enabledFeatures.includes(gate.feature)) return false;
  if (gate.anyFeature && !gate.anyFeature.some((feature) => enabledFeatures.includes(feature))) return false;
  return true;
}

function canOpen(page: MoreMenuPage, role: string | null, enabledFeatures: string[], permissions: string[]) {
  if (passesGate(page, role, enabledFeatures, permissions)) return true;
  return page.alsoVisibleIf !== undefined && passesGate(page.alsoVisibleIf, role, enabledFeatures, permissions);
}

/** The page a row opens: the first of its pages this user may open, or null (row hidden). */
export function resolveHref(item: MoreMenuItem, role: string | null, enabledFeatures: string[], permissions: string[]): string | null {
  return item.pages.find((page) => canOpen(page, role, enabledFeatures, permissions))?.href ?? null;
}

/** Rows this user sees, in render order, each with the page it opens. */
export function getVisibleMoreItems(role: string | null, enabledFeatures: string[], permissions: string[]) {
  return MORE_ITEMS.flatMap((item) => {
    const href = resolveHref(item, role, enabledFeatures, permissions);
    return href === null ? [] : [{ ...item, href }];
  });
}

function isPageActive(page: MoreMenuPage, pathname: string, tab: string) {
  if (page.activeWhen && !page.activeWhen(tab)) return false;
  const path = page.href.split("?")[0];
  if (page.exact) return pathname === path;
  if (isActive(pathname, path)) return true;
  return (page.activePrefixes ?? []).some((prefix) => pathname.startsWith(prefix));
}

/** `tab` is the current ?tab= value ("" when none): Leads to call and Team split /dashboard/team and the Upload page by it. */
export function isItemActive(item: MoreMenuItem, pathname: string, tab = "") {
  return item.pages.some((page) => isPageActive(page, pathname, tab));
}
