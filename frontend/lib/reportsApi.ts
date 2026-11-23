import { apiFetch, getAuthHeaders } from "@/lib/api";
import type { NavAccess } from "@/components/nav/navSections";

/**
 * Reports (staff side). Every call is /api/v1/reports/... and every report comes back as
 * { period, before, in_short, money_hidden? }. All report types live here; screens import from here only.
 * Readers are defensive: a key the server leaves out is simply not shown.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://aira-ai-5tfr.onrender.com";

// ─── Tabs ─────────────────────────────────────────────────────────────────────

export type ReportTab = "overview" | "money" | "customers" | "ads" | "team" | "items" | "campaigns" | "ask";

export const TAB_LABELS: Record<ReportTab, string> = {
  overview: "Overview",
  money: "Money",
  customers: "Customers",
  ads: "Ads",
  team: "Service & team",
  items: "Items & orders",
  campaigns: "Campaigns",
  ask: "Ask a question",
};

export const TAB_ORDER: readonly ReportTab[] = ["overview", "money", "customers", "ads", "team", "items", "campaigns", "ask"];

const OLD_TAB_KEYS: Record<string, ReportTab> = { templates: "campaigns", inbound: "customers", channels: "team" };

/** ?tab= value to a tab. Old keys keep working; anything unknown opens Overview. */
export function resolveTab(raw: string | null | undefined): ReportTab {
  if (!raw) return "overview";
  if ((TAB_ORDER as readonly string[]).includes(raw)) return raw as ReportTab;
  return OLD_TAB_KEYS[raw] ?? "overview";
}

/** Tabs this user may open: each shows only when its menu item is visible to them. */
export function visibleTabs(access: NavAccess, moneyHidden = false): ReportTab[] {
  const orders = access.isSubscribed && access.canAny(["deals.view", "deals.manage"]);
  const ads = access.isSubscribed && access.canAny(["meta_ads.view", "meta_ads.manage"]) && access.inboundOn;
  const reach = access.isSubscribed && access.canAny(["outbound_leads.view", "outbound_leads.manage"]) && access.outboundOn;
  const shown: Record<ReportTab, boolean> = {
    overview: true,
    money: orders && !moneyHidden,
    customers: true,
    ads,
    team: true,
    items: orders,
    campaigns: reach,
    ask: true,
  };
  return TAB_ORDER.filter((t) => shown[t]);
}

// ─── Dates ────────────────────────────────────────────────────────────────────

export type ReportPreset = "today" | "yesterday" | "last_7d" | "last_14d" | "last_30d" | "custom";
export interface ReportRange { preset: ReportPreset; start: string; end: string }
export type CompareMode = "previous" | "off";

const pad = (n: number) => String(n).padStart(2, "0");
const isoDay = (d: Date) => `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;

/** Today in India as a UTC-midnight Date (so day maths never drifts). */
export function istToday(now: Date = new Date()): Date {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(now);
  const v = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return new Date(Date.UTC(Number(v.year), Number(v.month) - 1, Number(v.day)));
}

/** The from / to (both inclusive, IST days) a range means. null when a custom range is not complete yet. */
export function rangeDates(range: ReportRange, now: Date = new Date()): { from: string; to: string } | null {
  if (range.preset === "custom") {
    return range.start && range.end && range.start <= range.end ? { from: range.start, to: range.end } : null;
  }
  const end = istToday(now);
  const start = new Date(end);
  if (range.preset === "yesterday") {
    start.setUTCDate(start.getUTCDate() - 1);
    end.setUTCDate(end.getUTCDate() - 1);
  } else if (range.preset === "last_7d") start.setUTCDate(start.getUTCDate() - 6);
  else if (range.preset === "last_14d") start.setUTCDate(start.getUTCDate() - 13);
  else if (range.preset === "last_30d") start.setUTCDate(start.getUTCDate() - 29);
  return { from: isoDay(start), to: isoDay(end) };
}

/** "2026-10" to a custom range covering the whole month. null when the text is not a month. */
export function monthRange(month: string | null | undefined): ReportRange | null {
  if (!month || !/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) return null;
  const [y, m] = month.split("-").map(Number);
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return { preset: "custom", start: `${month}-01`, end: `${month}-${pad(last)}` };
}

/** The month before today, as YYYY-MM (the accountant file's default). */
export function previousMonth(now: Date = new Date()): string {
  const t = istToday(now);
  const d = new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth() - 1, 1));
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}`;
}

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export function monthLabel(month: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(month);
  if (!m) return month;
  return `${MONTH_NAMES[Number(m[2]) - 1] ?? m[2]} ${m[1]}`;
}

export function reportQuery(range: ReportRange, compare: CompareMode, extra: Record<string, string | undefined> = {}, now?: Date): string | null {
  const dates = rangeDates(range, now);
  if (!dates) return null;
  const qs = new URLSearchParams({ from: dates.from, to: dates.to, compare });
  for (const [k, v] of Object.entries(extra)) if (v) qs.set(k, v);
  return qs.toString();
}

// ─── Formatting ───────────────────────────────────────────────────────────────

export type MetricKind = "count" | "paise" | "seconds" | "percent" | "ratio";

export function formatRupees(paise: number | null | undefined): string {
  if (paise === null || paise === undefined || Number.isNaN(paise)) return "—";
  const rupees = paise / 100;
  const whole = Math.abs(paise) % 100 === 0;
  return `${rupees < 0 ? "-" : ""}₹${Math.abs(rupees).toLocaleString("en-IN", { minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: whole ? 0 : 2 })}`;
}

export function formatSeconds(s: number | null | undefined): string {
  if (s === null || s === undefined || Number.isNaN(s)) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  return m ? `${h}h ${m}m` : `${h}h`;
}

export function formatValue(value: number | null | undefined, kind: MetricKind): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (kind === "paise") return formatRupees(value);
  if (kind === "seconds") return formatSeconds(value);
  if (kind === "percent") return `${Math.round(value)}%`;
  if (kind === "ratio") return `₹${value.toFixed(2)}`;
  return value.toLocaleString("en-IN");
}

/** Guess how to show a number from its key name (the server names money keys *_paise, times *_seconds). */
export function metricKind(key: string): MetricKind {
  if (key.endsWith("_paise")) return "paise";
  if (key.endsWith("_seconds") || key.endsWith("_secs")) return "seconds";
  if (key.endsWith("_pct") || key.endsWith("_percent")) return "percent";
  return "count";
}

/** "first_chats" to "First chats". */
export function humanizeKey(key: string): string {
  const text = key.replace(/_(paise|pct|percent|seconds|secs)$/, "").replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Numbers where a smaller figure is the good news (costs, waiting, refunds, said stop). */
export function lowerIsBetter(key: string): boolean {
  return /(cost|per_|seconds|secs|refund|said_stop|unhappy|owed|short|unmarked|spend|expenses)/.test(key);
}

export interface Delta { pct: number | null; dir: "up" | "down" | "same"; good: boolean | null }

/** Change from `before` to `now`. pct is null when before is 0 or missing. */
export function deltaOf(now: number | null | undefined, before: number | null | undefined, lower = false): Delta {
  if (now === null || now === undefined || before === null || before === undefined) return { pct: null, dir: "same", good: null };
  const dir = now > before ? "up" : now < before ? "down" : "same";
  const pct = before === 0 ? null : Math.round(((now - before) / Math.abs(before)) * 100);
  const good = dir === "same" ? null : lower ? dir === "down" : dir === "up";
  return { pct, dir, good };
}

// ─── Report shapes ────────────────────────────────────────────────────────────

export type NumMap = Record<string, number | null>;

export interface PeopleRef { metric: string; id?: string }

export interface ReportBase<P = NumMap> {
  period: P;
  before: P | null;
  in_short: string;
  /** True when this person may not see rupee figures; the money keys are then left out, not zero. */
  money_hidden?: boolean;
}

export interface ReportCard {
  key: string;
  label: string;
  value: number | null;
  before?: number | null;
  kind?: MetricKind;
  /** Opens the people behind the number. */
  people?: PeopleRef;
  href?: string;
  /** True for a figure that is worked out from cost prices and expenses, not counted (the profit card). */
  estimate?: boolean;
}

export interface TodoItem { text: string; count: number; href: string }

export interface SalesTarget {
  this_month?: { month?: string; target_paise?: number | null; money_in_paise?: number | null; pct?: number | null };
  cost_coverage?: { with_cost: number; total: number } | null;
  /** Only for people who may see profit (Orders view and Purchases view). */
  profit_this_month?: { profit_paise: number; month?: string } | null;
}

export interface OverviewReport extends ReportBase {
  target?: SalesTarget | null;
  todo: TodoItem[];
  cards: ReportCard[];
  unmarked_chats?: { count: number; href: string } | null;
}

export interface MoneyReport extends ReportBase {
  /** "range" when the numbers match the picked days, "month" when they are for the whole month. */
  scope?: "range" | "month";
  scope_label?: string;
  has_cost_prices?: boolean;
  cost_coverage?: { with_cost: number; total: number } | null;
}

export interface LabelCount { key?: string; label: string; count: number; people?: PeopleRef }

export interface CustomersReport extends ReportBase {
  funnel?: LabelCount[];
  came_from?: LabelCount[];
}

export interface AdRow {
  id: string;
  name: string;
  platform: "meta" | "google";
  spend_paise?: number | null;
  chats: number;
  hot: number;
  sales: number;
  earned_paise?: number | null;
  cost_per_chat_paise?: number | null;
  cost_per_hot_paise?: number | null;
  cost_per_sale_paise?: number | null;
  /** Money earned for every ₹1 spent, 2 decimals. */
  money_back?: number | null;
}

export interface AdsReport extends ReportBase { rows: AdRow[] }

export interface ReplyTimes { answered: number | null; p50_seconds: number | null; p90_seconds: number | null }

export interface TeamReport extends ReportBase {
  reply_times?: { ai: ReplyTimes | null; staff: ReplyTimes | null } | null;
  handled?: { by_ai_alone: number; passed_to_person: number } | null;
  sales_by_person?: { name: string; count: number; sales_paise?: number | null }[];
  stars_by_person?: { name: string; avg: number; count: number }[];
  calls?: NumMap | null;
}

export interface ItemsReport extends ReportBase {
  top_items?: { name: string; qty: number; sales_paise?: number | null }[];
  low_stock?: { name: string; left: number }[];
  orders_by_stage?: { stage: string; label?: string; count: number; total_paise?: number | null }[];
}

export interface CampaignRow {
  id: string;
  name: string;
  sent: number;
  delivered?: number | null;
  read?: number | null;
  replied?: number | null;
  said_stop?: number | null;
  paid?: number | null;
  paid_paise?: number | null;
}

export interface CampaignsReport extends ReportBase { rows: CampaignRow[] }

export interface PersonRow { lead_id: string; name: string | null; phone: string | null; detail?: string | null }

export type CsvTab = "overview" | "customers" | "ads" | "team" | "items" | "campaigns";

// ─── Calls ────────────────────────────────────────────────────────────────────

export function reportPath(tab: string, query: string, ext = ""): string {
  return `/api/v1/reports/${tab}${ext}?${query}`;
}

export function getReport<T>(tab: Exclude<ReportTab, "ask">, query: string): Promise<T> {
  return apiFetch<T>(reportPath(tab, query));
}

/** The people behind a number. The server may send a list or { people: [...] }. */
export async function getPeople(metric: string, query: string, id?: string): Promise<PersonRow[]> {
  const qs = new URLSearchParams(query);
  qs.set("metric", metric);
  if (id) qs.set("id", id);
  const res = await apiFetch<PersonRow[] | { people?: PersonRow[] }>(`/api/v1/reports/people?${qs.toString()}`);
  return Array.isArray(res) ? res : res.people ?? [];
}

/** GET a file and save it. Used for the CSV and Excel downloads. */
export async function downloadFile(path: string, fileName: string): Promise<void> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_URL}${path}`, { headers });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(typeof err?.detail === "string" ? err.detail : "The download did not work. Try again.");
  }
  const url = window.URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export function downloadCsv(tab: CsvTab, query: string): Promise<void> {
  return downloadFile(reportPath(tab, query, ".csv"), `report-${tab}.csv`);
}

export function downloadAccountantFile(month: string): Promise<void> {
  return downloadFile(`/api/v1/reports/money/accountant.xlsx?month=${encodeURIComponent(month)}`, `accountant-${month}.xlsx`);
}

// ─── Ask ──────────────────────────────────────────────────────────────────────

export interface AskChart { kind: "bar" | "line"; labels: string[]; values: number[] }
export interface AskLink { label: string; href: string }
export interface AskResult { answer: string; chart?: AskChart | null; links?: AskLink[] | null }

export function askQuestion(question: string): Promise<AskResult> {
  return apiFetch<AskResult>("/api/v1/ask", { method: "POST", body: JSON.stringify({ question }) });
}

/** Only keep a chart the screen can draw: matching lengths, real numbers. */
export function cleanChart(chart: AskChart | null | undefined): AskChart | null {
  if (!chart || (chart.kind !== "bar" && chart.kind !== "line")) return null;
  const n = Math.min(chart.labels?.length ?? 0, chart.values?.length ?? 0);
  if (n === 0) return null;
  const values = chart.values.slice(0, n).map((v) => (Number.isFinite(v) ? v : 0));
  return { kind: chart.kind, labels: chart.labels.slice(0, n).map(String), values };
}

/** Links must stay inside the app. */
export function safeLinks(links: AskLink[] | null | undefined): AskLink[] {
  return (links ?? []).filter((l) => l && typeof l.label === "string" && typeof l.href === "string" && l.href.startsWith("/") && !l.href.startsWith("//"));
}

// ─── People keys ──────────────────────────────────────────────────────────────

/** Number keys that are people, and the /people metric that lists them. */
const PEOPLE_KEYS: Record<string, string> = {
  new_chats: "new_chats",
  first_chats: "new_chats",
  hot: "hot",
  hot_leads: "hot",
  paid: "paid",
  buyers: "paid",
  repeat: "repeat",
  repeat_buyers: "repeat",
  bought_new: "bought_new",
  new_buyers: "bought_new",
  feedback_unhappy: "feedback_unhappy",
  unhappy_feedback: "feedback_unhappy",
  unmarked_chats: "unmarked_chats",
};

export function peopleMetricFor(key: string): string | null {
  return PEOPLE_KEYS[key] ?? null;
}

export function leadHref(leadId: string): string {
  return `/dashboard/leads/${leadId}`;
}
