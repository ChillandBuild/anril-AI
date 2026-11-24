import {
  ArrowDownToLine, BarChart2, BookOpen, Brain, Calendar, Coins, FileCheck, GraduationCap, HandCoins,
  Layers, Megaphone, MessageSquare, MessageSquareText, Phone, PhoneCall, RadioTower, Send, Settings,
  ShoppingBag, Sparkles, StickyNote, Trophy, Upload, Users, Zap, type LucideIcon,
  BookUser, Code2, History, KeyRound, LayoutDashboard, ListChecks, ReceiptText, SlidersHorizontal,
  Truck, CalendarClock, QrCode, MousePointerClick,
  Wallet,
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
  /** The Telecalling pages (keys of TC_FEATURE_MAP) this user may open: feature flags and permissions applied. */
  telecallingPages: readonly string[];
  can: (permission: string) => boolean;
  canAny: (permissions: string[]) => boolean;
  /** True for the telecaller role. Optional so existing callers and fixtures need no change. */
  isCaller?: boolean;
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
export type NavBadgeKey = "conversations" | "brain" | "alerts";

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
  /** `tab` is the current ?tab= value ("" when there is none). Most pages ignore it. */
  isActive: (pathname: string, tab?: string) => boolean;
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
  isActive: (pathname: string, tab?: string) => boolean;
}

/** Every entry of a section is a plain row (the nested Telecalling group is gone). */
export type NavEntry = NavLeaf;

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

/** The four Telecalling pages that carry a gate. Per-page gates live in TC_FEATURE_MAP / TC_PERMISSION_MAP; the Call IQ rows reuse them (dial and scripts follow Dialer and Upload). */
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
    isActive: (p, tab = "") => leaf.pages.some((page) => page.isActive(p, tab)),
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

const GOOGLE_ADS: NavLeaf = {
  kind: "link",
  key: "google-ads",
  href: "/dashboard/google-ads",
  label: "Google Ads",
  icon: MousePointerClick,
  visible: (a) => a.isSubscribed && a.canAny(["meta_ads.view", "meta_ads.manage"]) && a.inboundOn,
  isActive: (p) => p.startsWith("/dashboard/google-ads"),
};

const BOOKINGS: NavLeaf = {
  kind: "link",
  key: "bookings",
  href: "/dashboard/bookings",
  label: "Bookings",
  icon: CalendarClock,
  visible: (a) => a.isSubscribed && a.canAny(["bookings.view", "bookings.manage"]),
  isActive: (p) => p.startsWith("/dashboard/bookings"),
};

const prefixPage = (key: string, label: string, href: string, visible: NavPage["visible"]): NavPage => ({
  key, label, href, visible, isActive: (p) => p.startsWith(href),
});

/** Follow-ups was a Settings page, so it keeps the Settings gate. */
const settingsVisible = (a: NavAccess) => a.isSubscribed && a.canSettings;

const autoMessagesVisible = (a: NavAccess) =>
  a.isSubscribed && a.canAny(["auto_messages.view", "auto_messages.manage"]) && a.outboundOn;
const AUTO_MESSAGES_SENT = "/dashboard/auto-messages/sent";

const AUTO_MESSAGE_PAGES: readonly NavPage[] = [
  {
    ...prefixPage("auto-messages", "When something happens", "/dashboard/auto-messages", autoMessagesVisible),
    // /dashboard/auto-messages/sent is its own chip (Sent), so it must not light this one.
    isActive: (p) => p.startsWith("/dashboard/auto-messages") && !p.startsWith(AUTO_MESSAGES_SENT),
  },
  prefixPage("follow-ups", "Follow-ups", "/dashboard/settings/follow-ups", settingsVisible),
  prefixPage(
    "scheduled-templates", "One-time sends", "/dashboard/scheduled-templates",
    (a) =>
      a.isSubscribed &&
      a.canAny(["leads.manage", "conversations.reply", "telecalling.dialer", "outbound_leads.view", "outbound_leads.manage"]) &&
      (a.outboundOn || a.messagingOn),
  ),
  prefixPage("auto-messages-sent", "Sent", AUTO_MESSAGES_SENT, autoMessagesVisible),
];

const AUTO_MESSAGES = pagesLeaf({ key: "auto-messages", label: "Auto-Messages", icon: Zap, pages: AUTO_MESSAGE_PAGES });

/** One page since 2026-11-23; the old Handover address redirects to it. */
const REPLY_PAGES: readonly NavPage[] = [
  {
    key: "auto-reply",
    label: "Replies & handover",
    href: "/dashboard/settings/auto-reply",
    visible: settingsVisible,
    isActive: (p) => p.startsWith("/dashboard/settings/auto-reply") || p.startsWith("/dashboard/settings/inbox"),
  },
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
    ["overview", "Overview", LayoutDashboard],
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
      // Overview comes first, so clicking Anril OTP opens it. Send & check keeps the bare /dashboard/otp, exact match.
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

/** Purchases & suppliers: purchase orders, stock in, suppliers (its own money permissions). */
const PURCHASES: NavLeaf = {
  kind: "link",
  key: "purchases",
  href: "/dashboard/purchases",
  label: "Purchases",
  icon: Truck,
  visible: (a) => a.isSubscribed && a.canAny(["purchases.view", "purchases.manage"]),
  isActive: (p) => p.startsWith("/dashboard/purchases"),
};

/** Expenses: what the business spends, and real profit (purchases money permissions). */
const EXPENSES: NavLeaf = {
  kind: "link",
  key: "expenses",
  href: "/dashboard/expenses",
  label: "Expenses",
  icon: Wallet,
  visible: (a) => a.isSubscribed && a.canAny(["purchases.view", "purchases.manage"]),
  isActive: (p) => p.startsWith("/dashboard/expenses"),
};

const TC_QUEUE = "/dashboard/telecalling";
const TC_UPLOAD = "/dashboard/telecalling/upload";
const TC_SCHEDULED = "/dashboard/telecalling/scheduled";
const NOTES = "/dashboard/notes";
const TEAM = "/dashboard/team";

/** A Telecalling page's own gate: bought, subscribed, and that page allowed by feature flag and permission (tcGroupItems). */
const tcPageVisible = (gateHref: string): NavPage["visible"] => (a) =>
  a.telecallingVisible && a.telecallingPages.includes(gateHref);

/** Team and its Assignment Log tab share one gate (the Team page has no extra role rule on the log). */
const teamVisible = (a: NavAccess) => a.isSubscribed && a.can("team.view");

/** The Upload page opens its first view for any ?tab= it does not know, so the Call lists page is every tab but the other two. */
const uploadTab = (tab: string): "upload" | "history" | "scripts" =>
  tab === "history" || tab === "scripts" ? tab : "upload";

/** A page at one exact address: no sub-pages, so /dashboard/telecalling does not also light up on /dashboard/telecalling/scheduled. */
const exactPage = (p: string, href: string) => p === href || p === `${href}/`;

/** Calling: work the queue (its own tab dials by hand) and read the scripts. Scripts follow the Upload page's gate. */
const CALLING_PAGES: readonly NavPage[] = [
  { key: "calling-queue", label: "Call from the queue", href: TC_QUEUE, visible: tcPageVisible(TC_QUEUE), isActive: (p) => exactPage(p, TC_QUEUE) },
  {
    key: "calling-scripts", label: "Scripts", href: `${TC_UPLOAD}?tab=scripts`, visible: tcPageVisible(TC_UPLOAD),
    isActive: (p, tab = "") => exactPage(p, TC_UPLOAD) && uploadTab(tab) === "scripts",
  },
];

/** Leads to call: the lists you upload, the calls booked for later, and who each lead went to. */
const LEADS_TO_CALL_PAGES: readonly NavPage[] = [
  {
    key: "leads-call-lists", label: "Call lists", href: TC_UPLOAD, visible: tcPageVisible(TC_UPLOAD),
    isActive: (p, tab = "") => exactPage(p, TC_UPLOAD) && uploadTab(tab) === "upload",
  },
  { key: "leads-scheduled", label: "Scheduled calls", href: TC_SCHEDULED, visible: tcPageVisible(TC_SCHEDULED), isActive: (p) => p === TC_SCHEDULED || p.startsWith(`${TC_SCHEDULED}/`) },
  {
    key: "leads-uploads", label: "Uploads", href: `${TC_UPLOAD}?tab=history`, visible: tcPageVisible(TC_UPLOAD),
    isActive: (p, tab = "") => exactPage(p, TC_UPLOAD) && uploadTab(tab) === "history",
  },
  {
    key: "leads-who-got-which", label: "Who got which lead", href: `${TEAM}?tab=log`, visible: teamVisible,
    isActive: (p, tab = "") => p.startsWith(TEAM) && tab === "log",
  },
];

const CALLING = pagesLeaf({ key: "calling", label: "Calling", icon: PhoneCall, pages: CALLING_PAGES });
const LEADS_TO_CALL = pagesLeaf({ key: "leads-to-call", label: "Leads to call", icon: ListChecks, pages: LEADS_TO_CALL_PAGES });

const CALL_REVIEWS: NavLeaf = {
  kind: "link",
  key: "call-reviews",
  href: NOTES,
  label: "Call reviews",
  icon: StickyNote,
  visible: tcPageVisible(NOTES),
  isActive: (p) => p.startsWith(NOTES),
};

/** Team is people admin: teams, shifts, daily targets, attendance, moving leads. The numbers live on Live, Evaluation and Results. */
const TEAM_ROW: NavLeaf = {
  kind: "link",
  key: "team",
  href: TEAM,
  label: "Team",
  icon: Trophy,
  visible: teamVisible,
  isActive: (p, tab = "") => p.startsWith(TEAM) && tab !== "log",
};

/** Call IQ (v9.2 #21): who is calling now, AI call scores, and calls -> orders -> money. */
const CALL_IQ_LIVE: NavLeaf = {
  kind: "link",
  key: "call-iq-live",
  href: "/dashboard/call-iq/live",
  label: "Live",
  icon: RadioTower,
  visible: (a) => a.isSubscribed && a.canAny(["team.view", "telecalling.view"]),
  isActive: (p) => p.startsWith("/dashboard/call-iq/live"),
};

/** The alert count (unseen call alerts, owners and managers) rides on this row: the Needs attention list that handles them is here. */
const CALL_IQ_EVALUATION: NavLeaf = {
  kind: "link",
  key: "call-iq-evaluation",
  href: "/dashboard/call-iq/evaluation",
  label: "Evaluation",
  icon: ListChecks,
  badge: "alerts",
  visible: teamVisible,
  isActive: (p) => p.startsWith("/dashboard/call-iq/evaluation"),
};

const CALL_IQ_RESULTS: NavLeaf = {
  kind: "link",
  key: "call-iq-results",
  href: "/dashboard/call-iq/results",
  label: "Results",
  icon: BarChart2,
  visible: teamVisible,
  isActive: (p) => p.startsWith("/dashboard/call-iq/results"),
};

/** Anril Setup (v9.2 #23): questions the AI could not answer, its report card, and the scoring rules (read-only). */
const knowledgeVisible = (a: NavAccess) => a.isSubscribed && a.canAny(["knowledge.view", "knowledge.manage"]) && a.messagingOn;

const COULDNT_ANSWER: NavLeaf = {
  kind: "link",
  key: "couldnt-answer",
  href: "/dashboard/brain/couldnt-answer",
  label: "Couldn't answer",
  icon: MessageSquare,
  visible: knowledgeVisible,
  isActive: (p) => p.startsWith("/dashboard/brain/couldnt-answer"),
};

const AI_REPORT_CARD: NavLeaf = {
  kind: "link",
  key: "ai-report-card",
  href: "/dashboard/brain/report-card",
  label: "AI report card",
  icon: ReceiptText,
  // The report card endpoint answers 403 for the caller role, so telecallers do not see the entry.
  visible: (a) => knowledgeVisible(a) && !a.isCaller,
  isActive: (p) => p.startsWith("/dashboard/brain/report-card"),
};

const QUESTIONS_SCORING: NavLeaf = {
  kind: "link",
  key: "questions-scoring",
  href: "/dashboard/brain/scoring",
  label: "Questions & scoring",
  icon: SlidersHorizontal,
  visible: knowledgeVisible,
  isActive: (p) => p.startsWith("/dashboard/brain/scoring"),
};

const ANRIL_BRAIN: NavLeaf = {
  kind: "link",
  key: "anril-brain",
  href: "/dashboard/brain",
  label: "Anril Brain",
  icon: Brain,
  badge: "brain",
  visible: (a) => a.brainGate,
  isActive: (p) => p.startsWith("/dashboard/brain") && !["/couldnt-answer", "/report-card", "/scoring"].some((sub) => p.startsWith(`/dashboard/brain${sub}`)),
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

/** Teach & offers: same gate as Knowledge Base (it teaches the same AI agent). */
const TEACH_AND_OFFERS: NavLeaf = {
  kind: "link",
  key: "teach-offers",
  href: "/dashboard/teach",
  label: "Teach & offers",
  icon: GraduationCap,
  visible: (a) => a.isSubscribed && a.canAny(["knowledge.view", "knowledge.manage"]) && a.messagingOn,
  isActive: (p) => p.startsWith("/dashboard/teach"),
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

const QR_LINKS: NavLeaf = {
  kind: "link",
  key: "qr-links",
  href: "/dashboard/qr-links",
  label: "QR & links",
  icon: QrCode,
  visible: (a) => a.isSubscribed && a.canAny(["numbers.view", "numbers.manage"]) && a.messagingOn,
  isActive: (p) => p.startsWith("/dashboard/qr-links"),
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
    // Text size is open to everyone; someone who can open ONLY that row skips the
    // Settings home (which needs settings.view) and lands on Text size itself.
    visible: (a) => a.isSubscribed && SETTINGS_ITEMS.some((item) => !item.openToAll && settingsItemVisible(item, a)),
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

const ENGAGE: NavSection = { key: "engage", title: "Engage", icon: RadioTower, entries: [INBOUND_LEADS, BOOKINGS, META_ADS, GOOGLE_ADS, AUTO_MESSAGES] };
const SMS: NavSection = { key: "sms", title: "Anril SMS", icon: MessageSquareText, entries: SMS_PAGES };
const OTP: NavSection = { key: "otp", title: "Anril OTP", icon: KeyRound, entries: OTP_PAGES };
const COMMERCE: NavSection = { key: "commerce", title: "Commerce", icon: Coins, entries: [DEALS, CATALOGUE, PURCHASES, EXPENSES] };
const CALL_IQ: NavSection = { key: "callIq", title: "Call IQ", icon: Phone, entries: [CALLING, LEADS_TO_CALL, CALL_REVIEWS, TEAM_ROW, CALL_IQ_LIVE, CALL_IQ_EVALUATION, CALL_IQ_RESULTS] };
const AI_SETUP: NavSection = { key: "aiSetup", title: "Anril Setup", icon: Brain, entries: [ANRIL_BRAIN, COULDNT_ANSWER, AI_REPORT_CARD, QUESTIONS_SCORING, KNOWLEDGE_BASE, TEACH_AND_OFFERS, REPLIES_AND_HANDOVER] };
const WHATSAPP: NavSection = { key: "whatsappSetup", title: "WhatsApp", icon: FileCheck, entries: [TEMPLATES, NUMBERS_POOL, QR_LINKS] };

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
 * `tab` is the current ?tab= value, for rows that split one path by tab.
 */
export function resolveOpenSection(
  choice: string | null | undefined,
  sections: readonly NavSection[],
  pathname: string,
  tab = "",
): string | null {
  if (choice !== undefined) return choice;
  return sections.find((s) => sectionContainsPage(s, pathname, tab))?.key ?? null;
}

export function sectionContainsPage(section: NavSection, pathname: string, tab = ""): boolean {
  return section.entries.some((entry) => entry.isActive(pathname, tab));
}

/** Wide pages that fold the desktop sidebar to its icon strip when opened. Telecalling (queue, dial, upload, scheduled) and Call reviews fold, as before; Team does not. */
const FOLDS_SIDEBAR: readonly NavEntry[] = [CONVERSATIONS, SEGMENTS, INBOUND_LEADS, OUTBOUND_LEADS, DEALS];
const FOLDING_PREFIXES = ["/dashboard/telecalling", "/dashboard/notes"] as const;

export function sidebarFoldsOn(pathname: string): boolean {
  return FOLDS_SIDEBAR.some((entry) => entry.isActive(pathname)) || startsWithAny(pathname, FOLDING_PREFIXES);
}

export interface ChipSet {
  key: "autoMessages" | "otpSetup" | "calling" | "leadsToCall";
  /** The menu row these pages share. */
  leafKey: string;
  chips: readonly NavPage[];
}

/** The pages that share one menu row, in chip order. The page header renders these as a row of chips. */
export const CHIP_SETS: readonly ChipSet[] = [
  { key: "autoMessages", leafKey: AUTO_MESSAGES.key, chips: AUTO_MESSAGE_PAGES },
  { key: "otpSetup", leafKey: "otp-settings", chips: OTP_SETUP_PAGES },
  { key: "calling", leafKey: CALLING.key, chips: CALLING_PAGES },
  { key: "leadsToCall", leafKey: LEADS_TO_CALL.key, chips: LEADS_TO_CALL_PAGES },
];

/** The chip set for the page you are on (`tab` = its ?tab= value), or null when the page has no siblings. */
export function chipSetFor(pathname: string, tab = ""): ChipSet | null {
  return CHIP_SETS.find((set) => set.chips.some((chip) => chip.isActive(pathname, tab))) ?? null;
}

const CALL_IQ_META: Record<string, { title: string; description: string }> = {
  [TC_QUEUE]: { title: "Calling / Call from the queue", description: "Manage calls, callers, and lead queues in real time." },
  [TC_SCHEDULED]: { title: "Leads to call / Scheduled calls", description: "View and manage upcoming scheduled calls for leads." },
  [NOTES]: { title: "Call reviews", description: "Listen to calls, read the AI's marks and leave coaching notes." },
  "/dashboard/call-iq/live": { title: "Call IQ / Live", description: "Who is on a call, on a break, free or not logged in, right now." },
  "/dashboard/call-iq/evaluation": { title: "Call IQ / Evaluation", description: "How well each telecaller talks to customers, scored by the AI, and where each one can improve." },
  "/dashboard/call-iq/results": { title: "Call IQ / Results", description: "Calls, then visits booked, then orders, then money, for each telecaller." },
};

/**
 * The header title and subtitle for the Call IQ pages (Calling, Leads to call,
 * Call reviews, Team), or null for any other address. The Upload and Team pages
 * split into several views by ?tab=, so `tab` picks the view's name.
 */
export function callIqRouteMeta(pathname: string, tab = ""): { title: string; description: string } | null {
  if (exactPage(pathname, TC_UPLOAD)) {
    const view = uploadTab(tab);
    if (view === "history") return { title: "Leads to call / Uploads", description: "Review past CSV uploads, processing status, and import summaries." };
    if (view === "scripts") return { title: "Calling / Scripts", description: "Manage call scripts and guidelines for telecallers to follow." };
    return { title: "Leads to call / Call lists", description: "Upload contacts, assign them to queues, and start call campaigns." };
  }
  if (pathname === TEAM) {
    if (tab === "log") return { title: "Leads to call / Who got which lead", description: "Which telecaller each lead went to, and why." };
    return { title: "Team", description: "Your telecallers: teams, shift hours, daily targets, attendance and moving leads." };
  }
  return CALL_IQ_META[pathname] ?? null;
}
