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

/**
 * Every box key this screen knows. "bookings_today" is added here because the HomeBoxKey type in
 * lib/api.ts does not list it yet; once it does, this can be a plain alias of HomeBoxKey.
 */
export type BoxKey = HomeBoxKey | "bookings_today";

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

/** The working boxes, in default priority order. A person can turn on at most MAX_BOXES of them. */
export const BOX_KEYS: BoxKey[] = [
  "money_in_today",
  "new_enquiries_today",
  "hot_waiting",
  "to_collect",
  "callbacks_today",
  "orders_pending",
  "ads_today",
  "quotes_open",
  "won_month",
  "target_month",
  "low_stock",
  "bookings_today",
  "profit_month",
  "expenses_today",
  "feedback_week",
];

export const BOX_META: Record<BoxKey, BoxMeta> = {
  money_in_today: { label: "Money in today", icon: IndianRupee, group: "money", module: "Commerce", tint: "bg-emerald-50 text-emerald-700" },
  new_enquiries_today: { label: "New enquiries today", icon: UserPlus, group: "leads", module: "Leads", tint: "bg-sky-50 text-sky-700" },
  hot_waiting: { label: "Hot leads waiting", icon: Flame, group: "leads", module: "Chats", tint: "bg-rose-50 text-rose-700" },
  to_collect: { label: "Still to collect", icon: Wallet, group: "money", module: "Commerce", tint: "bg-amber-50 text-amber-700" },
  callbacks_today: { label: "Follow-ups due today", icon: PhoneCall, group: "leads", module: "Call IQ", tint: "bg-violet-50 text-violet-700" },
  orders_pending: { label: "Orders or work pending", icon: PackageOpen, group: "work", module: "Commerce", tint: "bg-orange-50 text-orange-700" },
  ads_today: { label: "Ads today", icon: Megaphone, group: "leads", module: "Ads", tint: "bg-indigo-50 text-indigo-700" },
  quotes_open: { label: "Quotes not confirmed", icon: ReceiptText, group: "leads", module: "Commerce", tint: "bg-teal-50 text-teal-700" },
  won_month: { label: "Won this month", icon: Trophy, group: "leads", module: "Leads", tint: "bg-yellow-50 text-yellow-700" },
  target_month: { label: "Target this month", icon: Target, group: "money", module: "Settings", tint: "bg-lime-50 text-lime-700" },
  low_stock: { label: "Low stock", icon: Package, group: "work", module: "Catalogue", tint: "bg-stone-100 text-stone-700" },
  bookings_today: { label: "Bookings today", icon: CalendarCheck, group: "work", module: "Bookings", tint: "bg-sky-50 text-sky-700" },
  profit_month: { label: "Profit this month", icon: TrendingUp, group: "money", module: "Reports", tint: "bg-green-50 text-green-800" },
  expenses_today: { label: "Expenses today", icon: HandCoins, group: "money", module: "Commerce", tint: "bg-red-50 text-red-700" },
  feedback_week: { label: "Feedback this week", icon: Star, group: "work", module: "Customers", tint: "bg-amber-50 text-amber-800" },
};

export function isBoxKey(key: string): key is BoxKey {
  return Object.prototype.hasOwnProperty.call(BOX_META, key);
}

/** Planned boxes. Shown greyed and locked in Edit Today; never sent to or from the backend. */
export const COMING_SOON_BOXES: { key: string; label: string; icon: LucideIcon; group: BoxGroup; module: string }[] = [
  { key: "renewals_due", label: "Renewals due", icon: CalendarClock, group: "work", module: "Customers" },
];

export const COMING_SOON_BOX_KEYS: string[] = COMING_SOON_BOXES.map((b) => b.key);

/** The lists you can switch on and off. Each shows only when the server sends it to this person. */
export const LIST_KEYS: HomeListKey[] = ["waiting", "low_stock", "todays_bookings", "todays_feedback"];
export const LIST_LABELS: Record<HomeListKey, string> = {
  waiting: "Waiting for your reply",
  low_stock: "Stock running low",
  todays_bookings: "Today's bookings",
  todays_feedback: "Today's feedback",
};

/**
 * Boxes to draw, in order. A saved layout wins, cut down to what this person may
 * see now (a box they lost access to just disappears). No saved layout, or nothing
 * left of it, means the suggested set.
 */
export function resolveBoxes(
  layout: Pick<HomeLayout, "boxes"> | null | undefined,
  today: Pick<HomeToday, "available" | "defaults"> | null | undefined,
): BoxKey[] {
  if (!today) return [];
  const available = new Set<string>(today.available);
  const saved = layout?.boxes;
  if (saved && saved.length > 0) {
    const seen = new Set<string>();
    const kept: BoxKey[] = [];
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
  return {
    waiting: listIsOn(layout, "waiting"),
    low_stock: listIsOn(layout, "low_stock"),
    todays_bookings: listIsOn(layout, "todays_bookings"),
    todays_feedback: listIsOn(layout, "todays_feedback"),
  };
}

export function canAddBox(selected: readonly string[]): boolean {
  return selected.length < MAX_BOXES;
}

/** Add a box at the end. Refuses a duplicate, a coming-soon or unknown key, or a 13th box. */
export function addBox(selected: readonly BoxKey[], key: string): BoxKey[] {
  if (!isBoxKey(key) || selected.includes(key) || !canAddBox(selected)) return [...selected];
  return [...selected, key];
}

export function removeBox(selected: readonly BoxKey[], key: string): BoxKey[] {
  return selected.filter((k) => k !== key);
}

/** Move one box up (-1) or down (+1). Stays put at either end. */
export function moveBox(selected: readonly BoxKey[], key: string, delta: -1 | 1): BoxKey[] {
  const from = selected.indexOf(key as BoxKey);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= selected.length) return [...selected];
  const next = [...selected];
  [next[from], next[to]] = [next[to], next[from]];
  return next;
}

/** Body for PUT /home/layout. */
export function buildSavePayload(selected: readonly BoxKey[], lists: Record<HomeListKey, boolean>): HomeLayoutSave {
  return { boxes: selected.filter(isBoxKey).slice(0, MAX_BOXES) as HomeBoxKey[], lists: { waiting: lists.waiting, low_stock: lists.low_stock, todays_bookings: lists.todays_bookings, todays_feedback: lists.todays_feedback } };
}

/** ₹1,86,400 (Indian grouping); paise only when there are some. A negative number shows as -₹12,000. */
export function formatRupees(paise: number | null | undefined): string {
  if (paise == null || !Number.isFinite(paise)) return "—";
  const whole = paise % 100 === 0;
  const text = "₹" + (Math.abs(paise) / 100).toLocaleString("en-IN", { minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2 });
  return paise < 0 ? "-" + text : text;
}

export function formatBoxValue(box: Pick<HomeBox, "value" | "unit">): string {
  if (box.value == null) return "—";
  if (box.unit === "paise") return formatRupees(box.value);
  // Feedback this week: the average, one decimal ("4.3★").
  if (box.unit === "stars") return Number.isFinite(box.value) ? `${box.value.toFixed(1)}★` : "—";
  // The Target box: a percent for the team, and "Set a target" for an owner who has not set one.
  if (box.unit === "percent") return Number.isFinite(box.value) ? `${box.value.toLocaleString("en-IN")}%` : "—";
  if (box.unit === "set_target") return "Set a target";
  return Number.isFinite(box.value) ? box.value.toLocaleString("en-IN") : "—";
}

/** Profit below zero is a loss: the card says so in words, not only with a minus sign. */
export function isLoss(key: string, box: Pick<HomeBox, "value">): boolean {
  return key === "profit_month" && box.value != null && box.value < 0;
}

/** The small line under a box's number. A loss starts with the word "Loss". */
export function boxSub(key: string, box: Pick<HomeBox, "value" | "sub">): string {
  const sub = box.sub ?? "";
  if (!isLoss(key, box)) return sub;
  return sub ? `Loss · ${sub}` : "Loss";
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

/** One row of the Today's bookings list on Home (the server sends the next 10 of today). */
export type TodaysBooking = {
  id: string;
  start_at: string;
  customer_name: string | null;
  service_name: string;
  resource_name: string;
  status: string;
};

export type TodaysBookings = { total: number; items: TodaysBooking[] };

/** Stars as text for the feedback list: 4 -> "★★★★☆". Out-of-range numbers are held to 0..5. */
export function starsText(stars: number): string {
  const n = Math.max(0, Math.min(5, Math.round(Number.isFinite(stars) ? stars : 0)));
  return "★".repeat(n) + "☆".repeat(5 - n);
}
