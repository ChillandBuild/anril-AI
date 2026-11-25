import { ScrollText, ShieldCheck, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";

/* ------------------------------------------------------------------ *
 * Header tabs
 *
 * Pages whose views switch with ?tab= pills in the header. One entry drives
 * the pills, the phone tab strip and the title: the header always reads
 * "<Page> / <tab>", the way Meta Ads does. Adding a tab, or a new tabbed page,
 * only needs an entry here; never hand-write the pills or the "/ tab" part of
 * the title. The first tab is the default view and has no ?tab= in its URL.
 *
 * Route-based tabs (each tab is its own URL) can't use this map: give each
 * route its own "<Page> / <tab>" title in AppHeader's getBaseRouteMetadata
 * (see Meta Ads and Catalogue).
 * ------------------------------------------------------------------ */

export type HeaderTab = { value: string; label: string; icon?: LucideIcon };
export type HeaderTabSet = {
  tabs: HeaderTab[];
  /** Old ?tab= values that still open a tab. */
  aliases?: Record<string, string>;
  /** Write ?tab= for the first tab too (these pages read it literally). */
  explicitDefault?: boolean;
  /** Tighter pills, for sets with many tabs. */
  compact?: boolean;
};

export const HEADER_TABS: Record<string, HeaderTabSet> = {
  "/dashboard/outbound-leads": {
    explicitDefault: true,
    tabs: [
      { value: "upload", label: "Broadcast Message" },
      { value: "history", label: "Broadcast History" },
      { value: "tags", label: "Tags" },
      { value: "opted-out", label: "Opted-Out" },
    ],
  },
  "/dashboard/numbers": {
    tabs: [
      { value: "pool", label: "Active Pool" },
      { value: "activity", label: "Activity Log" },
    ],
  },
  // Documents (RAG) is the default landing tab (2026-09-20). `?tab=ai-tune` is
  // an old link that still opens the Description.
  "/dashboard/knowledge": {
    aliases: { "ai-tune": "description" },
    tabs: [
      { value: "documents", label: "Documents" },
      { value: "description", label: "Description" },
    ],
  },
  "/dashboard/analytics": {
    compact: true,
    tabs: [
      { value: "overview", label: "Overview" },
      { value: "channels", label: "Channels" },
      { value: "inbound", label: "Inbound" },
      { value: "templates", label: "Templates" },
    ],
  },
  "/dashboard/purchases": {
    tabs: [
      { value: "orders", label: "Purchase orders" },
      { value: "stock-in", label: "Stock in" },
      { value: "suppliers", label: "Suppliers" },
    ],
  },
  // "Form answers" is hidden unless form intake is on (see AppHeader).
  "/dashboard/deals": {
    tabs: [
      { value: "deals", label: "Orders" },
      { value: "insights", label: "Insights" },
      { value: "forms", label: "Form answers" },
    ],
  },
  "/dashboard/roles": {
    tabs: [
      { value: "roles", label: "Roles", icon: ShieldCheck },
      { value: "users", label: "Users", icon: Users },
      { value: "audit", label: "Activity log", icon: ScrollText },
    ],
  },
  // Customers. Old links say tab=leads (All people) or tab=reengagement (Follow-ups).
  "/dashboard/leads": {
    aliases: { reengagement: "follow-ups", leads: "people" },
    tabs: [
      { value: "people", label: "All people" },
      { value: "groups", label: "Groups" },
      { value: "said-stop", label: "Said stop" },
      { value: "feedback", label: "Feedback" },
      { value: "follow-ups", label: "Follow-ups" },
    ],
  },
};

/**
 * Pages that draw their own phone tab switch in the page body (Orders, Numbers)
 * or own their tab bar (Reports), so the shared phone strip would repeat it.
 */
const OWN_PHONE_SWITCH = new Set(["/dashboard/deals", "/dashboard/numbers", "/dashboard/analytics"]);

export function activeHeaderTab(set: HeaderTabSet, tabParam: string): HeaderTab {
  const value = set.aliases?.[tabParam] ?? tabParam;
  return set.tabs.find((t) => t.value === value) ?? set.tabs[0];
}

/** The tab set the phone strip under the header shows for this page, or null. */
export function phoneHeaderTabs(pathname: string): HeaderTabSet | null {
  if (OWN_PHONE_SWITCH.has(pathname)) return null;
  return HEADER_TABS[pathname] ?? null;
}
