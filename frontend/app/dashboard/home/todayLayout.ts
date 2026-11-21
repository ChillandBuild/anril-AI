// Pure helpers for the Home "Today" block: which boxes exist, which ones to show,
// and how the Edit Today modal changes the list. No React here, so it is unit-tested.
import {
  CalendarCheck,
  CalendarClock,
  Flame,
  HandCoins,
  IndianRupee,
  Megaphone,
  Package,
  PackageOpen,
  PhoneCall,
  ReceiptText,
  Star,
  Target,
  Trophy,
  TrendingUp,
  UserPlus,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import type { HomeBox, HomeBoxKey, HomeLayout, HomeLayoutSave, HomeListKey, HomeToday } from "@/lib/api";

/** Most boxes one person can put on Today. The backend refuses more than this. */
export const MAX_BOXES = 12;
/** Boxes per row on a laptop; the default set is one row. */
export const DEFAULT_BOX_COUNT = 6;

export type BoxGroup = "money" | "leads" | "work";

export const GROUPS: { id: "all" | BoxGroup; label: string }[] = [
  { id: "all", label: "All" },
  { id: "money", label: "Money" },
  { id: "leads", label: "Leads & sales" },
  { id: "work", label: "Work & customers" },
];

export type BoxMeta = {
  label: string;
  icon: LucideIcon;
  group: BoxGroup;
  /** Small grey word in Edit Today: where the number comes from. */
  module: string;
  /** Icon tile colour classes. */
  tint: string;
};

/** The 10 working boxes, in default priority order. */
export const BOX_KEYS: HomeBoxKey[] = [
  "money_in_today",
  "new_enquiries_today",
  "hot_waiting",
  "to_collect",
  "callbacks_today",
  "orders_pending",
  "ads_today",
  "quotes_open",
  "won_month",
  "low_stock",
];

export const BOX_META: Record<HomeBoxKey, BoxMeta> = {
  money_in_today: { label: "Money in today", icon: IndianRupee, group: "money", module: "Commerce", tint: "bg-emerald-50 text-emerald-700" },
  new_enquiries_today: { label: "New enquiries today", icon: UserPlus, group: "leads", module: "Leads", tint: "bg-sky-50 text-sky-700" },
  hot_waiting: { label: "Hot leads waiting", icon: Flame, group: "leads", module: "Chats", tint: "bg-rose-50 text-rose-700" },
  to_collect: { label: "Still to collect", icon: Wallet, group: "money", module: "Commerce", tint: "bg-amber-50 text-amber-700" },
  callbacks_today: { label: "Follow-ups due today", icon: PhoneCall, group: "leads", module: "Call IQ", tint: "bg-violet-50 text-violet-700" },
  orders_pending: { label: "Orders or work pending", icon: PackageOpen, group: "work", module: "Commerce", tint: "bg-orange-50 text-orange-700" },
  ads_today: { label: "Ads today", icon: Megaphone, group: "leads", module: "Ads", tint: "bg-indigo-50 text-indigo-700" },
  quotes_open: { label: "Quotes not confirmed", icon: ReceiptText, group: "leads", module: "Commerce", tint: "bg-teal-50 text-teal-700" },
  won_month: { label: "Won this month", icon: Trophy, group: "leads", module: "Leads", tint: "bg-yellow-50 text-yellow-700" },
  low_stock: { label: "Low stock", icon: Package, group: "work", module: "Catalogue", tint: "bg-stone-100 text-stone-700" },
};

export function isBoxKey(key: string): key is HomeBoxKey {
  return Object.prototype.hasOwnProperty.call(BOX_META, key);
}

/** Planned boxes. Shown greyed and locked in Edit Today; never sent to or from the backend. */
export const COMING_SOON_BOXES: { key: string; label: string; icon: LucideIcon; group: BoxGroup; module: string }[] = [
  { key: "expenses_today", label: "Expenses today", icon: HandCoins, group: "money", module: "Commerce" },
  { key: "profit_month", label: "Profit this month (owner)", icon: TrendingUp, group: "money", module: "Reports" },
  { key: "target_month", label: "Target this month", icon: Target, group: "money", module: "Reports" },
  { key: "bookings_today", label: "Bookings today", icon: CalendarCheck, group: "work", module: "Engage" },
  { key: "feedback_week", label: "Feedback this week", icon: Star, group: "work", module: "Customers" },
  { key: "renewals_due", label: "Renewals due", icon: CalendarClock, group: "work", module: "Customers" },
];

export const COMING_SOON_BOX_KEYS: string[] = COMING_SOON_BOXES.map((b) => b.key);

/** The two lists that work today. */
export const LIST_KEYS: HomeListKey[] = ["waiting", "low_stock"];
export const LIST_LABELS: Record<HomeListKey, string> = {
  waiting: "Waiting for your reply",
  low_stock: "Stock running low",
};

export const COMING_SOON_LISTS: { key: string; label: string }[] = [
  { key: "bookings", label: "Today's bookings" },
  { key: "feedback", label: "Today's feedback" },
];

/**
 * Boxes to draw, in order. A saved layout wins, cut down to what this person may
 * see now (a box they lost access to just disappears). No saved layout, or nothing
 * left of it, means the suggested set.
 */
export function resolveBoxes(
  layout: Pick<HomeLayout, "boxes"> | null | undefined,
  today: Pick<HomeToday, "available" | "defaults"> | null | undefined,
): HomeBoxKey[] {
  if (!today) return [];
  const available = new Set<string>(today.available);
  const saved = layout?.boxes;
  if (saved && saved.length > 0) {
    const seen = new Set<string>();
    const kept: HomeBoxKey[] = [];
    for (const key of saved) {
      if (!isBoxKey(key) || !available.has(key) || seen.has(key)) continue;
      seen.add(key);
      kept.push(key);
    }
    if (kept.length > 0) return kept.slice(0, MAX_BOXES);
  }
  return today.defaults.filter((k) => available.has(k)).slice(0, DEFAULT_BOX_COUNT);
}

/** A list shows only when its data exists AND the person has not switched it off. */
export function listIsOn(layout: Pick<HomeLayout, "lists"> | null | undefined, key: HomeListKey): boolean {
  return layout?.lists?.[key] !== false;
}

export function listsFromLayout(layout: Pick<HomeLayout, "lists"> | null | undefined): Record<HomeListKey, boolean> {
  return { waiting: listIsOn(layout, "waiting"), low_stock: listIsOn(layout, "low_stock") };
}

export function canAddBox(selected: readonly string[]): boolean {
  return selected.length < MAX_BOXES;
}

/** Add a box at the end. Refuses a duplicate, a coming-soon or unknown key, or a 13th box. */
export function addBox(selected: readonly HomeBoxKey[], key: string): HomeBoxKey[] {
  if (!isBoxKey(key) || selected.includes(key) || !canAddBox(selected)) return [...selected];
  return [...selected, key];
}

export function removeBox(selected: readonly HomeBoxKey[], key: string): HomeBoxKey[] {
  return selected.filter((k) => k !== key);
}

/** Move one box up (-1) or down (+1). Stays put at either end. */
export function moveBox(selected: readonly HomeBoxKey[], key: string, delta: -1 | 1): HomeBoxKey[] {
  const from = selected.indexOf(key as HomeBoxKey);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= selected.length) return [...selected];
  const next = [...selected];
  [next[from], next[to]] = [next[to], next[from]];
  return next;
}

/** Body for PUT /home/layout. */
export function buildSavePayload(selected: readonly HomeBoxKey[], lists: Record<HomeListKey, boolean>): HomeLayoutSave {
  return { boxes: selected.filter(isBoxKey).slice(0, MAX_BOXES), lists: { waiting: lists.waiting, low_stock: lists.low_stock } };
}

/** ₹1,86,400 (Indian grouping); paise only when there are some. */
export function formatRupees(paise: number | null | undefined): string {
  if (paise == null || !Number.isFinite(paise)) return "—";
  const whole = paise % 100 === 0;
  return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2 });
}

export function formatBoxValue(box: Pick<HomeBox, "value" | "unit">): string {
  if (box.unit === "paise") return formatRupees(box.value);
  return Number.isFinite(box.value) ? box.value.toLocaleString("en-IN") : "—";
}

/** "5m" · "2h 10m" · "3d". For how long a chat has waited. */
export function waitingFor(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const mins = Math.max(0, Math.floor((now - t) / 60_000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return mins % 60 ? `${hours}h ${mins % 60}m` : `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

/** Minutes waited, for the red bar sentence ("waiting 32 min"). */
export function waitingMinutes(iso: string | null | undefined, now: number = Date.now()): number {
  if (!iso) return 0;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? 0 : Math.max(0, Math.floor((now - t) / 60_000));
}
