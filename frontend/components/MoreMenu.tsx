"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  BarChart2,
  BookOpen,
  Brain,
  Calendar,
  CalendarClock,
  Grid3X3,
  HandCoins,
  Inbox,
  Layers,
  Megaphone,
  Menu,
  BookUser,
  Code2,
  KeyRound,
  LayoutDashboard,
  ListChecks,
  ReceiptText,
  Send,
  ShoppingBag,
  Settings,
  ShieldCheck,
  SquarePen,
  Zap,
  StickyNote,
  Upload,
  Users,
  X,
} from "lucide-react";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { useSubscription } from "@/app/dashboard/contexts/SubscriptionContext";
import { cn, isActive } from "@/lib/utils";
import { getVisibleSettingsItems, SETTINGS_GROUP_ORDER } from "@/components/settingsNavigation";
import { useBrainCount } from "@/hooks/useBrainCount";
import { BrainNavBadge } from "@/components/brain/BrainNavBadge";

const BRAIN_HREF = "/dashboard/brain";

type MoreMenuGate = {
  permissionAny?: string[];
  feature?: string;
  anyFeature?: string[];
};

type MoreMenuSection =
  | "top"
  | "inbox"
  | "engage"
  | "reach"
  | "sms"
  | "commerce"
  | "callIq"
  | "aiSetup"
  | "whatsappSetup"
  | "account";

type MoreMenuItem = MoreMenuGate & {
  href: string;
  icon: typeof Users;
  label: string;
  section: MoreMenuSection;
  /** Extra gate: the item also shows when this gate passes (used by Catalogue). */
  alsoVisibleIf?: MoreMenuGate;
  /** Extra paths that also highlight this item as active. */
  activePrefixes?: string[];
  /** Active on its own path only, not its sub-pages (the SMS dashboard). */
  exact?: boolean;
};

/** Render order. `title: null` renders the items with no heading. */
const MORE_SECTIONS: readonly { key: MoreMenuSection; title: string | null }[] = [
  { key: "top", title: null },
  { key: "inbox", title: "INBOX & LEADS" },
  { key: "engage", title: "ANRIL ENGAGE" },
  { key: "reach", title: "ANRIL REACH" },
  { key: "sms", title: "ANRIL SMS" },
  { key: "commerce", title: "SALES · ANRIL COMMERCE" },
  { key: "callIq", title: "ANRIL CALL IQ" },
  { key: "aiSetup", title: "AI SETUP" },
  { key: "whatsappSetup", title: "WHATSAPP SETUP" },
  { key: "account", title: "ACCOUNT" },
];

const MESSAGING_FEATURES = ["outbound_messaging", "inbound_messaging"];
const SMS_PERMS = ["sms.view", "sms.manage"];

const MORE_ITEMS: MoreMenuItem[] = [
  { href: "/dashboard/analytics", icon: BarChart2, label: "Analytics", section: "top", permissionAny: ["analytics.view"], anyFeature: MESSAGING_FEATURES },
  { href: "/dashboard/leads", icon: Users, label: "Leads", section: "inbox", permissionAny: ["leads.view", "leads.manage"], anyFeature: MESSAGING_FEATURES },
  { href: "/dashboard/inbound-leads", icon: Inbox, label: "Inbound Leads", section: "engage", permissionAny: ["inbound_leads.view", "inbound_leads.manage"], feature: "inbound_messaging" },
  { href: "/dashboard/meta-ads", icon: Megaphone, label: "Meta Ads", section: "engage", permissionAny: ["meta_ads.view", "meta_ads.manage"], feature: "inbound_messaging" },
  { href: "/dashboard/auto-messages", icon: Zap, label: "Auto-Messages", section: "engage", permissionAny: ["auto_messages.view", "auto_messages.manage"], feature: "outbound_messaging" },
  { href: "/dashboard/scheduled-templates", icon: CalendarClock, label: "Scheduled templates", section: "engage", permissionAny: ["leads.manage", "conversations.reply", "telecalling.dialer", "outbound_leads.view", "outbound_leads.manage"], anyFeature: MESSAGING_FEATURES },
  { href: "/dashboard/outbound-leads", icon: Upload, label: "Send", section: "reach", permissionAny: ["outbound_leads.view", "outbound_leads.manage"], feature: "outbound_messaging" },
  { href: "/dashboard/sms", icon: LayoutDashboard, label: "Dashboard", section: "sms", permissionAny: SMS_PERMS, feature: "sms", exact: true },
  { href: "/dashboard/sms/setup", icon: ListChecks, label: "DLT Setup", section: "sms", permissionAny: SMS_PERMS, feature: "sms" },
  { href: "/dashboard/sms/send", icon: Send, label: "Send SMS", section: "sms", permissionAny: SMS_PERMS, feature: "sms" },
  { href: "/dashboard/sms/contacts", icon: BookUser, label: "Address Book", section: "sms", permissionAny: SMS_PERMS, feature: "sms" },
  { href: "/dashboard/sms/reports", icon: BarChart2, label: "Delivery Reports", section: "sms", permissionAny: SMS_PERMS, feature: "sms" },
  { href: "/dashboard/sms/transactions", icon: ReceiptText, label: "Transactions", section: "sms", permissionAny: SMS_PERMS, feature: "sms" },
  { href: "/dashboard/sms/developer", icon: Code2, label: "Dev API", section: "sms", permissionAny: SMS_PERMS, feature: "sms" },
  { href: "/dashboard/sms/otp", icon: KeyRound, label: "Smart OTP", section: "sms", permissionAny: SMS_PERMS, feature: "sms" },
  { href: "/dashboard/deals", icon: HandCoins, label: "Deals", section: "commerce", permissionAny: ["deals.view", "deals.manage"] },
  {
    href: "/dashboard/catalog",
    icon: ShoppingBag,
    label: "Catalogue",
    section: "commerce",
    permissionAny: ["catalog.view", "catalog.manage"],
    anyFeature: MESSAGING_FEATURES,
    alsoVisibleIf: { permissionAny: ["services.view", "services.manage"], anyFeature: MESSAGING_FEATURES },
    activePrefixes: ["/dashboard/catalog", "/dashboard/services"],
  },
  { href: "/dashboard/telecalling/scheduled", icon: Calendar, label: "Scheduled Calls", section: "callIq", permissionAny: ["telecalling.scheduled.view", "telecalling.scheduled"], feature: "telecalling.scheduled" },
  { href: "/dashboard/notes", icon: StickyNote, label: "Call Review", section: "callIq", permissionAny: ["telecalling.notes.view", "telecalling.notes"], feature: "telecalling.notes" },
  { href: "/dashboard/team", icon: Grid3X3, label: "Team Performance", section: "callIq", permissionAny: ["team.view", "team.manage"] },
  { href: BRAIN_HREF, icon: Brain, label: "Anril Brain", section: "aiSetup", permissionAny: ["brain.view"], anyFeature: MESSAGING_FEATURES },
  { href: "/dashboard/knowledge", icon: BookOpen, label: "Knowledge Base", section: "aiSetup", permissionAny: ["knowledge.view", "knowledge.manage"], anyFeature: MESSAGING_FEATURES },
  { href: "/dashboard/templates", icon: SquarePen, label: "Templates", section: "whatsappSetup", permissionAny: ["templates.view", "templates.manage"], feature: "outbound_messaging" },
  { href: "/dashboard/numbers", icon: Layers, label: "Numbers Pool", section: "whatsappSetup", permissionAny: ["numbers.view", "numbers.manage"], anyFeature: MESSAGING_FEATURES },
  { href: "/dashboard/roles", icon: ShieldCheck, label: "Users & Roles", section: "account", permissionAny: ["roles.view", "roles.manage"] },
];

function passesGate(gate: MoreMenuGate, role: string | null, enabledFeatures: string[], permissions: string[]) {
  if (role !== "owner" && gate.permissionAny && !gate.permissionAny.some((permission) => permissions.includes(permission))) return false;
  if (gate.feature && !enabledFeatures.includes(gate.feature)) return false;
  if (gate.anyFeature && !gate.anyFeature.some((feature) => enabledFeatures.includes(feature))) return false;
  return true;
}

function isVisible(item: MoreMenuItem, role: string | null, enabledFeatures: string[], permissions: string[]) {
  if (passesGate(item, role, enabledFeatures, permissions)) return true;
  return item.alsoVisibleIf !== undefined && passesGate(item.alsoVisibleIf, role, enabledFeatures, permissions);
}

function isItemActive(item: MoreMenuItem, pathname: string) {
  if (item.exact) return pathname === item.href;
  if (isActive(pathname, item.href)) return true;
  return (item.activePrefixes ?? []).some((prefix) => pathname.startsWith(prefix));
}

export function MoreMenu() {
  const pathname = usePathname() || "/dashboard";
  const { role, enabledFeatures, permissions } = useAuthRole();
  const [isOpen, setIsOpen] = useState(false);
  const { purchasedFeatures } = useSubscription();

  const items = MORE_ITEMS.filter((item) => isVisible(item, role, enabledFeatures, permissions));
  // Same gate as the Knowledge Base entry: the entry is in `items` exactly when it is allowed.
  const brainCount = useBrainCount(items.some((item) => item.href === BRAIN_HREF));
  const canSettings = role === "owner" || permissions.includes("settings.view") || permissions.includes("settings.manage");
  const settingsItems = getVisibleSettingsItems(purchasedFeatures);
  const settingsActive = pathname.startsWith("/dashboard/settings");

  return (
    <div className="relative lg:hidden">
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        aria-label="More"
        className="flex h-[34px] w-[34px] items-center justify-center rounded-full text-white transition-transform hover:scale-105"
        style={{ background: "linear-gradient(135deg, var(--primary-950), var(--primary-800))" }}
      >
        <Menu size={16} />
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-[70] lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-black/35"
            onClick={() => setIsOpen(false)}
          />
          <div className="absolute left-0 top-0 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] w-[80vw] max-w-xs overflow-y-auto bg-white p-4 pt-[calc(1rem+env(safe-area-inset-top))] shadow-2xl animate-in fade-in slide-in-from-left duration-200">
            <div className="mb-3 flex items-center justify-between px-1">
              <div className="font-display text-sm font-extrabold text-ink">More</div>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="flex h-9 w-9 items-center justify-center rounded-full text-ink-secondary hover:bg-surface-mid"
                aria-label="Close"
              >
                <X size={18} />
              </button>
            </div>
            {items.length === 0 && !canSettings ? (
              <div className="rounded-xl border border-border-subtle bg-surface-low px-3 py-4 text-center font-body text-sm text-ink-muted">
                No more sections are available for this account.
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {MORE_SECTIONS.map((section) => {
                  const sectionItems = items.filter((item) => item.section === section.key);
                  const showSettings = section.key === "account" && canSettings;
                  if (sectionItems.length === 0 && !showSettings) return null;
                  return (
                    <div key={section.key} className="flex flex-col gap-2">
                      {section.title && (
                        <div className="px-2 pt-1 pb-0.5 font-label text-[10px] font-bold uppercase tracking-wider text-ink-muted">
                          {section.title}
                        </div>
                      )}
                      {sectionItems.map((item) => {
                        const Icon = item.icon;
                        const active = isItemActive(item, pathname);
                        return (
                          <Link
                            key={item.href}
                            href={item.href}
                            onClick={() => setIsOpen(false)}
                            className={cn(
                              "flex min-h-12 items-center gap-3 rounded-xl border px-3 py-2.5 text-sm font-bold",
                              active
                                ? "border-primary-muted bg-primary-light text-primary"
                                : "border-border-subtle bg-surface-low text-ink hover:border-border"
                            )}
                          >
                            <Icon size={17} />
                            <span className="min-w-0 truncate">{item.label}</span>
                            {item.href === BRAIN_HREF && <BrainNavBadge count={brainCount} variant="menu" />}
                          </Link>
                        );
                      })}
                      {showSettings && (
                        <div className="mt-1 rounded-xl border border-border-subtle bg-surface-low p-2">
                          <div className={cn(
                            "flex min-h-10 items-center gap-3 rounded-lg px-2 text-sm font-bold",
                            settingsActive ? "text-primary" : "text-ink",
                          )}>
                            <Settings size={17} />
                            <span>Settings</span>
                          </div>
                          <div className="mt-1 flex flex-col gap-1 border-l border-border pl-2">
                            {SETTINGS_GROUP_ORDER.map((group) => {
                              const groupItems = settingsItems.filter((i) => i.group === group);
                              if (groupItems.length === 0) return null;
                              return (
                                <div key={group} className="pt-1.5 first:pt-0">
                                  <div className="px-2 pb-0.5 font-label text-[10px] font-bold uppercase tracking-wider text-ink-muted">
                                    {group}
                                  </div>
                                  {groupItems.map((item) => {
                                    const Icon = item.icon;
                                    const active = isActive(pathname, item.href);
                                    return (
                                      <Link
                                        key={item.href}
                                        href={item.href}
                                        onClick={() => setIsOpen(false)}
                                        className={cn(
                                          "flex min-h-10 items-center gap-2.5 rounded-lg px-2 py-2 text-[13px] font-semibold",
                                          active
                                            ? "bg-primary-light text-primary"
                                            : "text-ink-secondary hover:bg-white hover:text-ink",
                                        )}
                                      >
                                        <Icon size={15} />
                                        <span className="min-w-0 truncate">{item.label}</span>
                                      </Link>
                                    );
                                  })}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
