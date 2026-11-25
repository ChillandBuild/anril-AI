"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Check, Download, RefreshCw, Search } from "lucide-react";
import { api, DealStage, DealSummaryStats, DealSource, PaymentMethod, DealAttention } from "@/lib/api";
import { filtersFromParams, filtersToParams, ATTENTION_LABEL, shortRupees, SOURCE_LABEL, PAYMENT_LABEL } from "@/lib/deal-filters";
import { cn } from "@/lib/utils";
import { ListTab, downloadDealsCsv, fetchAllDeals } from "./ListTab";
import { FilterPopover } from "@/components/deals/FilterPopover";
import { TickMark } from "@/components/ui/controls";

type Filters = ReturnType<typeof filtersFromParams>;
type StageKey = DealStage | "all";

const STAGE_CARDS: { key: StageKey; label: string; hint: string; edge: string }[] = [
  { key: "all", label: "All deals", hint: "Every deal", edge: "bg-primary" },
  { key: "quoted", label: "Quoted", hint: "Follow up", edge: "bg-slate-400" },
  { key: "awaiting_payment", label: "Awaiting payment", hint: "Link sent · chase it", edge: "bg-amber-400" },
  { key: "won", label: "Won", hint: "Paid", edge: "bg-emerald-500" },
  { key: "lost", label: "Lost", hint: "Didn't close", edge: "bg-rose-500" },
];

const SOURCES: DealSource[] = ["whatsapp", "form", "call", "walk_in", "manual", "indiamart", "justdial"];
const PAYMENTS: PaymentMethod[] = ["razorpay", "cash", "upi", "card", "bank_transfer", "other"];
const ATTENTIONS: DealAttention[] = ["unpaid_3d", "link_expiring", "refund"];

function weekAgoIso(): string {
  const d = new Date();
  d.setDate(d.getDate() - 7);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(d);
}

function daysAgoIso(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(d);
}

// Saved views: each one is a fixed set of filters. Stage is left alone so a view
// combines with the stage card above.
const VIEWS: { id: string; label: string; filters: () => Partial<Filters> }[] = [
  { id: "all", label: "All deals", filters: () => ({}) },
  { id: "unpaid", label: "Unpaid 3+ days", filters: () => ({ attention: ["unpaid_3d"] }) },
  { id: "big", label: "Big deals ₹10k+", filters: () => ({ min_rupees: 10000 }) },
  { id: "indiamart", label: "IndiaMART", filters: () => ({ source: ["indiamart"] }) },
  { id: "week", label: "This week", filters: () => ({ created_from: weekAgoIso() }) },
];

// Keys a saved view or filter can set (stage, sort and paging are separate controls).
const FILTER_KEYS = ["q", "source", "created_from", "created_to", "min_rupees", "max_rupees", "payment_method", "product", "attention"] as const;

function sameFilters(a: Partial<Filters>, b: Partial<Filters>): boolean {
  return FILTER_KEYS.every((k) => JSON.stringify(a[k] ?? null) === JSON.stringify(b[k] ?? null));
}

function listText<T extends string>(values: T[] | undefined, labels: Record<T, string>): string {
  if (!values || values.length === 0) return "All";
  return values.map((v) => labels[v] ?? v).join(", ");
}

function toggled<T>(list: T[] | undefined, value: T, on: boolean): T[] | undefined {
  const next = on ? [...(list || []), value] : (list || []).filter((v) => v !== value);
  return next.length > 0 ? next : undefined;
}

function TickRow({ checked, label, onChange }: { checked: boolean; label: string; onChange: (on: boolean) => void }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-xs font-semibold text-[#334155] hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
    >
      <TickMark checked={checked} size="sm" />
      <span className="truncate">{label}</span>
    </button>
  );
}

function PickRow({ selected, label, onClick }: { selected: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left text-xs font-semibold hover:bg-slate-50",
        selected ? "text-primary" : "text-[#334155]"
      )}
    >
      {label}
      {selected && <Check size={14} />}
    </button>
  );
}

const fieldLabel = "block text-[10px] font-bold uppercase tracking-wider text-[#64748b]";
const fieldInput =
  "mt-1 w-full rounded-lg border border-[#e2e8f0] px-2.5 py-1.5 text-xs text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary/20";

export function DealsTab({
  onOpenDeal,
  reloadToken,
}: {
  onOpenDeal: (id: string) => void;
  reloadToken: number;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryError, setSummaryError] = useState(false);
  const [summary, setSummary] = useState<DealSummaryStats | null>(null);
  const [searchText, setSearchText] = useState("");
  const [refreshToken, setRefreshToken] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [exporting, setExporting] = useState(false);

  // Memoize filters by URL string so the fetches don't loop
  const paramsKey = searchParams.toString();
  const filters = useMemo(() => filtersFromParams(new URLSearchParams(paramsKey)), [paramsKey]);


  const updateFilters = useCallback(
    (newFilters: Filters) => {
      router.replace(`/dashboard/deals?${filtersToParams(newFilters).toString()}`, { scroll: false });
    },
    [router]
  );

  const setFilter = (patch: Partial<Filters>) => updateFilters({ ...filters, ...patch, page: 1 });

  useEffect(() => {
    setSearchText(filters.q ?? "");
  }, [filters.q]);

  // Search with a 300ms debounce
  useEffect(() => {
    if (searchText === (filters.q ?? "")) return;
    const timer = setTimeout(() => {
      updateFilters({ ...filters, q: searchText || undefined, page: 1 });
    }, 300);
    return () => clearTimeout(timer);
  }, [searchText, filters, updateFilters]);

  // Stage counts ignore the stage filter so every card keeps its number.
  const summaryFilters = useMemo(
    () => ({
      source: filters.source,
      q: filters.q,
      created_from: filters.created_from,
      created_to: filters.created_to,
      min_rupees: filters.min_rupees,
      max_rupees: filters.max_rupees,
      payment_method: filters.payment_method,
      product: filters.product,
      attention: filters.attention,
    }),
    [filters]
  );

  const loadSummary = useCallback(async () => {
    setSummaryLoading(true);
    setSummaryError(false);
    try {
      setSummary(await api.deals.summary(summaryFilters));
    } catch {
      setSummaryError(true);
    } finally {
      setSummaryLoading(false);
    }
  }, [summaryFilters]);

  useEffect(() => {
    loadSummary();
  }, [loadSummary, reloadToken, refreshToken]);

  const stages = summary?.stages;
  const stageStat = (key: StageKey) => {
    if (!stages) return { count: undefined, total: 0 };
    if (key === "all") {
      const all = Object.values(stages);
      return { count: all.reduce((s, x) => s + x.count, 0), total: all.reduce((s, x) => s + x.total_paise, 0) };
    }
    return { count: stages[key]?.count ?? 0, total: stages[key]?.total_paise ?? 0 };
  };

  const activeView = VIEWS.find((v) => sameFilters(filters, v.filters()));
  const hasFilters = FILTER_KEYS.some((k) => filters[k] !== undefined) || !!filters.stage;

  const createdText = filters.created_from || filters.created_to
    ? `${filters.created_from ?? "…"} – ${filters.created_to ?? "now"}`
    : "Any time";
  const valueText = filters.min_rupees != null || filters.max_rupees != null
    ? `₹${filters.min_rupees ?? 0} – ${filters.max_rupees != null ? `₹${filters.max_rupees}` : "any"}`
    : "Any";

  function clearFilters() {
    setSearchText("");
    updateFilters({});
  }

  async function refresh() {
    setRefreshing(true);
    setRefreshToken((n) => n + 1);
    // The list and numbers reload on the token; keep the spinner up briefly so the click registers.
    setTimeout(() => setRefreshing(false), 600);
  }

  async function exportAll() {
    setExporting(true);
    try {
      const deals = await fetchAllDeals(filters, filters.sort || "created_at", filters.dir || "desc");
      if (deals.length === 0) {
        toast.info("No deals to export");
        return;
      }
      downloadDealsCsv(deals, "deals.csv");
      toast.success(`Exported ${deals.length} deal${deals.length === 1 ? "" : "s"}`);
    } catch {
      toast.error("Export failed — try again");
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* Stage cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        {STAGE_CARDS.map(({ key, label, hint, edge }) => {
          const { count, total } = stageStat(key);
          const isSelected = (filters.stage || "all") === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setFilter({ stage: key === "all" ? undefined : key })}
              className={cn(
                "relative flex items-center gap-3 overflow-hidden rounded-2xl border bg-white py-4 pl-5 pr-4 text-left transition-all",
                isSelected ? "border-2 border-primary ring-4 ring-primary/10" : "border-[#e2e8f0] hover:border-slate-300"
              )}
            >
              <div className={cn("absolute bottom-3 left-0 top-3 w-1 rounded-r", edge)} />
              <div className="min-w-[2ch] font-display text-3xl font-bold tabular-nums text-[#0A1528]">
                {summaryLoading && count === undefined ? (
                  <span className="inline-block h-8 w-8 animate-pulse rounded bg-[#f1f5f9] align-middle" />
                ) : (
                  count ?? "—"
                )}
              </div>
              <div className="min-w-0">
                <div className="truncate text-sm font-bold text-[#0A1528]">{label}</div>
                <div className="text-xs font-bold tabular-nums text-[#334155]">{shortRupees(total)}</div>
                <div className="truncate text-xs text-[#64748b]">{hint}</div>
              </div>
            </button>
          );
        })}
      </div>

      {summaryError && (
        <div className="flex items-center justify-between rounded-xl border border-amber-200 bg-amber-50 px-4 py-2">
          <p className="text-xs text-amber-700">Couldn&apos;t load the stage numbers.</p>
          <button type="button" onClick={loadSummary} className="text-xs font-bold text-amber-700 hover:opacity-70">
            Retry
          </button>
        </div>
      )}

      {/* Main card: filters + table */}
      <div className="rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
        {/* One row on desktop: filters and buttons keep their size; the search box fills the leftover space and gives it up to "Clear" when one shows. */}
        <div className="flex flex-wrap items-center gap-1.5 border-b border-[#e2e8f0] p-4 lg:flex-nowrap">
          <div className="relative min-w-28 flex-1">
            <Search size={14} className="absolute left-3 top-2.5 text-[#64748b]" />
            <input
              type="text"
              placeholder="Search deals"
              title="Search by name, phone or deal ID (D-0012)"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              className="w-full rounded-xl border border-[#e2e8f0] py-2 pl-10 pr-3 text-xs focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>

          <FilterPopover label="View" value={activeView?.label ?? "Custom"} active={!!activeView && activeView.id !== "all"} closeOnPick>
            {VIEWS.map((v) => (
              <PickRow
                key={v.id}
                label={v.label}
                selected={activeView?.id === v.id}
                onClick={() => updateFilters({ ...v.filters(), stage: filters.stage, sort: filters.sort, dir: filters.dir })}
              />
            ))}
          </FilterPopover>

          <FilterPopover label="Source" value={listText(filters.source, SOURCE_LABEL)} active={!!filters.source}>
            {SOURCES.map((s) => (
              <TickRow
                key={s}
                label={SOURCE_LABEL[s]}
                checked={filters.source?.includes(s) ?? false}
                onChange={(on) => setFilter({ source: toggled(filters.source, s, on) })}
              />
            ))}
          </FilterPopover>

          <FilterPopover label="Created" value={createdText} active={!!(filters.created_from || filters.created_to)}>
            <PickRow
              label="Any time"
              selected={!filters.created_from && !filters.created_to}
              onClick={() => setFilter({ created_from: undefined, created_to: undefined })}
            />
            {[7, 30, 90].map((days) => (
              <PickRow
                key={days}
                label={`Last ${days} days`}
                selected={filters.created_from === daysAgoIso(days) && !filters.created_to}
                onClick={() => setFilter({ created_from: daysAgoIso(days), created_to: undefined })}
              />
            ))}
            <div className="mt-1 space-y-2 border-t border-[#f1f5f9] px-2.5 pb-1 pt-2">
              <label className="block">
                <span className={fieldLabel}>From</span>
                <input
                  type="date"
                  value={filters.created_from || ""}
                  onChange={(e) => setFilter({ created_from: e.target.value || undefined })}
                  className={fieldInput}
                />
              </label>
              <label className="block">
                <span className={fieldLabel}>To</span>
                <input
                  type="date"
                  value={filters.created_to || ""}
                  onChange={(e) => setFilter({ created_to: e.target.value || undefined })}
                  className={fieldInput}
                />
              </label>
            </div>
          </FilterPopover>

          <FilterPopover label="Value" value={valueText} active={filters.min_rupees != null || filters.max_rupees != null}>
            <div className="space-y-2 p-1.5">
              <label className="block">
                <span className={fieldLabel}>Min ₹</span>
                <input
                  type="number"
                  min={0}
                  value={filters.min_rupees ?? ""}
                  onChange={(e) => setFilter({ min_rupees: e.target.value ? parseInt(e.target.value, 10) : undefined })}
                  placeholder="0"
                  className={fieldInput}
                />
              </label>
              <label className="block">
                <span className={fieldLabel}>Max ₹</span>
                <input
                  type="number"
                  min={0}
                  value={filters.max_rupees ?? ""}
                  onChange={(e) => setFilter({ max_rupees: e.target.value ? parseInt(e.target.value, 10) : undefined })}
                  placeholder="Any"
                  className={fieldInput}
                />
              </label>
            </div>
          </FilterPopover>

          <FilterPopover label="Payment" value={listText(filters.payment_method, PAYMENT_LABEL)} active={!!filters.payment_method}>
            {PAYMENTS.map((m) => (
              <TickRow
                key={m}
                label={PAYMENT_LABEL[m]}
                checked={filters.payment_method?.includes(m) ?? false}
                onChange={(on) => setFilter({ payment_method: toggled(filters.payment_method, m, on) })}
              />
            ))}
          </FilterPopover>

          {summary && summary.products.length > 0 && (
            <FilterPopover label="Product" value={filters.product?.join(", ") || "All"} active={!!filters.product}>
              <div className="max-h-56 overflow-y-auto">
                {summary.products.map((p) => (
                  <TickRow
                    key={p}
                    label={p}
                    checked={filters.product?.includes(p) ?? false}
                    onChange={(on) => setFilter({ product: toggled(filters.product, p, on) })}
                  />
                ))}
              </div>
            </FilterPopover>
          )}

          <FilterPopover label="More" value={listText(filters.attention, ATTENTION_LABEL)} active={!!filters.attention}>
            {ATTENTIONS.map((a) => (
              <TickRow
                key={a}
                label={ATTENTION_LABEL[a]}
                checked={filters.attention?.includes(a) ?? false}
                onChange={(on) => setFilter({ attention: toggled(filters.attention, a, on) })}
              />
            ))}
          </FilterPopover>

          {hasFilters && (
            <button
              type="button"
              onClick={clearFilters}
              className="shrink-0 whitespace-nowrap px-1 text-xs font-semibold text-primary hover:opacity-70"
            >
              Clear
            </button>
          )}

          <div className="ml-auto flex shrink-0 gap-1.5">
            <button
              type="button"
              onClick={refresh}
              title="Refresh"
              aria-label="Refresh"
              disabled={refreshing}
              className={cn(
                "flex items-center gap-1.5 whitespace-nowrap rounded-xl border border-[#e2e8f0] bg-white py-2 text-xs font-bold text-[#0A1528] transition-colors hover:bg-[#f8fafc] disabled:opacity-40",
                hasFilters ? "px-2.5" : "px-3"
              )}
            >
              <RefreshCw size={14} className={cn(refreshing && "animate-spin")} />
              {/* Label only when no filter is set — "Clear" needs the room otherwise. */}
              {!hasFilters && "Refresh"}
            </button>
            <button
              type="button"
              onClick={exportAll}
              title="Export"
              aria-label="Export"
              disabled={exporting}
              className="flex items-center gap-1.5 whitespace-nowrap rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 text-xs font-bold text-[#0A1528] transition-colors hover:bg-[#f8fafc] disabled:opacity-40"
            >
              <Download size={14} />
              {exporting ? "Exporting…" : "Export"}
            </button>
          </div>
        </div>

        <ListTab
          filters={filters}
          sort={filters.sort || "created_at"}
          dir={filters.dir || "desc"}
          page={filters.page || 1}
          onSortChange={(sort, dir) => updateFilters({ ...filters, sort, dir, page: 1 })}
          onPageChange={(page) => updateFilters({ ...filters, page })}
          onOpenDeal={onOpenDeal}
          onClearFilters={clearFilters}
          reloadToken={reloadToken + refreshToken}
        />
      </div>
    </div>
  );
}
