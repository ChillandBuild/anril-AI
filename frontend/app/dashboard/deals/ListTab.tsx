"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { ChevronUp, ChevronDown, Download } from "lucide-react";
import { api, DealFilters, DealSummary, DealListPage, DealSort } from "@/lib/api";
import { formatRupees } from "@/components/deals/money";
import { StageBadge } from "@/components/deals/StageBadge";
import { SourceBadge } from "@/components/deals/SourceBadge";
import { CheckTick } from "@/components/ui/controls";
import { MobileRecordCard, MobileRecordField, MobileRecordGrid, MobileRecordHeader } from "@/components/MobileRecord";
import { cn, timeAgo, formatPhone } from "@/lib/utils";
import { getDealTags } from "@/lib/deal-tags";
import { shortRupees, PAYMENT_LABEL } from "@/lib/deal-filters";
import { PAGE_SIZE } from "@/lib/pagination";
import { phoneCell } from "@/lib/csvPhone";
import { Pagination } from "@/components/ui/Pagination";

const BRAND_COLORS = ["#038285", "#0A1528", "#6366f1", "#b45309", "#be123c", "#047857"];

function getColorForLead(leadId: string): string {
  let hash = 0;
  for (let i = 0; i < leadId.length; i++) {
    hash = ((hash << 5) - hash) + leadId.charCodeAt(i);
    hash = hash & hash;
  }
  return BRAND_COLORS[Math.abs(hash) % BRAND_COLORS.length];
}

function Avatar({ name, phone, leadId }: { name?: string | null; phone?: string | null; leadId: string }) {
  // Two-letter initials: first letters of first two words, else first chars of phone
  let initials = "?";
  if (name) {
    initials = name.trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  } else if (phone) {
    initials = phone.substring(0, 2).toUpperCase();
  }
  return (
    <div
      style={{ backgroundColor: getColorForLead(leadId) }}
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white"
    >
      {initials}
    </div>
  );
}

function paymentText(deal: DealSummary): string {
  return deal.payment_method ? PAYMENT_LABEL[deal.payment_method] : deal.lost_reason || "—";
}

function csvCell(value: string): string {
  return `"${value.replace(/"/g, '""')}"`;
}

/** Download deals as a CSV file. */
export function downloadDealsCsv(deals: DealSummary[], filename: string) {
  const csv = [
    ["Deal", "Customer", "Phone", "Items", "Stage", "Source", "Value (₹)", "Payment", "Created"].join(","),
    ...deals.map((deal) =>
      [
        csvCell(deal.deal_label),
        csvCell(deal.lead.name || ""),
        csvCell(phoneCell(deal.lead.phone)),
        csvCell(deal.item_summary),
        deal.stage,
        deal.source,
        Math.round(deal.total_paise / 100),
        csvCell(paymentText(deal)),
        new Date(deal.created_at).toLocaleDateString("en-IN"),
      ].join(",")
    ),
  ].join("\n");

  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** Every deal matching the filters, fetched page by page (the API caps a page at 100). */
export async function fetchAllDeals(filters: DealFilters, sort: DealSort, dir: "asc" | "desc"): Promise<DealSummary[]> {
  const all: DealSummary[] = [];
  for (let page = 1; ; page++) {
    const result = await api.deals.list(filters, { sort, dir, page, limit: 100 });
    all.push(...result.data);
    if (result.data.length === 0 || all.length >= result.total) return all;
  }
}

export function ListTab({
  filters,
  sort,
  dir,
  page,
  onSortChange,
  onPageChange,
  onOpenDeal,
  onClearFilters,
  reloadToken,
}: {
  filters: DealFilters;
  sort: DealSort;
  dir: "asc" | "desc";
  page: number;
  onSortChange: (sort: DealSort, dir: "asc" | "desc") => void;
  onPageChange: (page: number) => void;
  onOpenDeal: (id: string) => void;
  onClearFilters: () => void;
  reloadToken: number;
}) {
  const router = useRouter();
  const [data, setData] = useState<DealListPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const result = await api.deals.list(
        {
          stage: filters.stage,
          source: filters.source,
          q: filters.q,
          created_from: filters.created_from,
          created_to: filters.created_to,
          min_rupees: filters.min_rupees,
          max_rupees: filters.max_rupees,
          payment_method: filters.payment_method,
          product: filters.product,
          attention: filters.attention,
        },
        { sort, dir, page, limit: PAGE_SIZE }
      );
      setData(result);
      setSelectedIds(new Set());
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [filters, sort, dir, page]);

  useEffect(() => {
    load();
  }, [load, reloadToken]);

  const handleSort = (newSort: DealSort) => {
    onSortChange(newSort, sort === newSort && dir === "desc" ? "asc" : "desc");
  };

  const deals = data?.data ?? [];
  const selectedDeals = deals.filter((d) => selectedIds.has(d.id));
  const selectedTotal = selectedDeals.reduce((sum, d) => sum + d.total_paise, 0);

  function toggleOne(id: string, next: boolean) {
    const ids = new Set(selectedIds);
    if (next) ids.add(id);
    else ids.delete(id);
    setSelectedIds(ids);
  }

  async function copyPayLink(link: string) {
    try {
      await navigator.clipboard.writeText(link);
      toast.success("Payment link copied");
    } catch {
      toast.error("Couldn't copy the link");
    }
  }

  function rowAction(deal: DealSummary) {
    // Awaiting payment → the next step is chasing the money; everything else → talk to the customer.
    if (deal.stage === "awaiting_payment" && deal.payment_link) {
      return (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            copyPayLink(deal.payment_link!);
          }}
          className="whitespace-nowrap rounded-lg border border-primary px-3 py-1.5 text-xs font-bold text-primary hover:bg-primary/5"
        >
          Copy pay link
        </button>
      );
    }
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          router.push(`/dashboard/conversations?lead=${deal.lead.id}`);
        }}
        className="whitespace-nowrap rounded-lg bg-primary px-4 py-1.5 text-xs font-bold text-white hover:bg-primary/90"
      >
        Open chat
      </button>
    );
  }

  function sortHeader(key: DealSort, label: string, alignRight = false) {
    return (
      <button
        type="button"
        onClick={() => handleSort(key)}
        className={cn(
          "flex items-center gap-1 uppercase tracking-wider hover:text-[#0A1528]",
          alignRight && "ml-auto",
          sort === key && "text-primary"
        )}
      >
        {label}
        {sort === key && (dir === "asc" ? <ChevronUp size={12} /> : <ChevronDown size={12} />)}
      </button>
    );
  }

  if (loading && !data) {
    return (
      <div className="space-y-2 p-4">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="h-12 animate-pulse rounded-xl bg-[#f1f5f9]" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center gap-3 p-10 text-center">
        <p className="text-xs text-[#64748b]">Couldn&apos;t load deals.</p>
        <button
          type="button"
          onClick={load}
          className="rounded-lg bg-primary px-4 py-1.5 text-xs font-bold text-white hover:bg-primary/90"
        >
          Retry
        </button>
      </div>
    );
  }

  if (deals.length === 0) {
    return (
      <div className="p-10 text-center text-xs text-[#64748b]">
        <p>No deals match these filters</p>
        <button
          type="button"
          onClick={onClearFilters}
          className="mt-2 text-xs font-semibold text-primary hover:opacity-70"
        >
          Clear filters
        </button>
      </div>
    );
  }

  const thClass = "px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-[#64748b] whitespace-nowrap";

  return (
    <div className={cn("transition-opacity", loading && "opacity-60")}>
      {selectedIds.size > 0 && (
        <div className="mx-4 mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-[#0A1528] px-4 py-2.5 text-white">
          <span className="text-xs font-bold">
            {selectedIds.size} selected · {shortRupees(selectedTotal)}
          </span>
          <button
            type="button"
            onClick={() => downloadDealsCsv(selectedDeals, "deals-selected.csv")}
            className="flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 text-xs font-bold transition-colors hover:bg-white/20"
          >
            <Download size={12} />
            Export selected
          </button>
          <button
            type="button"
            onClick={() => setSelectedIds(new Set())}
            className="ml-auto text-xs font-bold text-white/60 hover:text-white"
          >
            Clear
          </button>
        </div>
      )}

      {/* Table */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[#f1f5f9]">
              <th className="px-4 py-3 text-left">
                <CheckTick
                  checked={selectedIds.size === deals.length}
                  indeterminate={selectedIds.size > 0 && selectedIds.size < deals.length}
                  onChange={(next) => setSelectedIds(next ? new Set(deals.map((d) => d.id)) : new Set())}
                  aria-label="Select all deals on this page"
                />
              </th>
              <th className={thClass}>{sortHeader("deal_number", "Deal")}</th>
              <th className={thClass}>Customer</th>
              <th className={thClass}>Items</th>
              <th className={thClass}>Stage</th>
              <th className={thClass}>Source</th>
              <th className={cn(thClass, "text-right")}>{sortHeader("total_paise", "Value", true)}</th>
              <th className={thClass}>Payment</th>
              <th className={thClass}>Last activity</th>
              <th className={thClass}>{sortHeader("created_at", "Created")}</th>
              <th className={cn(thClass, "text-right")}>Action</th>
            </tr>
          </thead>
          <tbody>
            {deals.map((deal) => {
              const tags = getDealTags(deal);
              return (
                <tr
                  key={deal.id}
                  onClick={() => onOpenDeal(deal.id)}
                  className={cn(
                    "cursor-pointer border-t border-[#f1f5f9] transition-colors hover:bg-[#f8fafc]",
                    selectedIds.has(deal.id) && "bg-primary-light/60"
                  )}
                >
                  <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                    <CheckTick
                      checked={selectedIds.has(deal.id)}
                      onChange={(next) => toggleOne(deal.id, next)}
                      aria-label={`Select deal ${deal.deal_label}`}
                    />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-[#64748b]">{deal.deal_label}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2.5">
                      <Avatar name={deal.lead.name} phone={deal.lead.phone} leadId={deal.lead.id} />
                      <div className="min-w-0">
                        <div className="truncate text-sm font-bold text-[#0A1528]">{deal.lead.name || "—"}</div>
                        <div className="whitespace-nowrap text-xs text-[#64748b]">{formatPhone(deal.lead.phone)}</div>
                      </div>
                    </div>
                  </td>
                  <td className="max-w-[220px] px-4 py-3">
                    <p className="truncate text-sm text-[#334155]">{deal.item_summary}</p>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    <div className="flex flex-col items-start gap-1">
                      <StageBadge stage={deal.stage} />
                      {tags.map((tag) => (
                        <span
                          key={tag.key}
                          className={cn(
                            "inline-flex items-center rounded-full border px-1.5 py-0.5 font-label text-[10px] font-bold",
                            tag.tone === "muted"
                              ? "border-slate-200 bg-slate-50 text-slate-600"
                              : tag.tone === "warning"
                              ? "border-amber-200 bg-amber-50 text-amber-700"
                              : "border-rose-200 bg-rose-50 text-rose-600"
                          )}
                        >
                          {tag.label}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    <SourceBadge source={deal.source} />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right text-sm font-bold tabular-nums text-[#0A1528]">
                    {formatRupees(deal.total_paise)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-[#334155]">{paymentText(deal)}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-[#64748b]">
                    {deal.last_activity_at ? timeAgo(deal.last_activity_at) : "—"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-[#64748b]">{timeAgo(deal.created_at)}</td>
                  <td className="px-4 py-3 text-right">{rowAction(deal)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Phone view */}
      <div className="block space-y-3 p-3 md:hidden">
        {deals.map((deal) => (
          <MobileRecordCard key={deal.id} onClick={() => onOpenDeal(deal.id)} className="cursor-pointer">
            <MobileRecordHeader
              title={deal.lead.name || formatPhone(deal.lead.phone)}
              subtitle={`${deal.deal_label} · ${deal.item_summary}`}
              aside={<StageBadge stage={deal.stage} />}
            />
            <MobileRecordGrid>
              <MobileRecordField label="Value" value={formatRupees(deal.total_paise)} />
              <MobileRecordField label="Source" value={<SourceBadge source={deal.source} />} />
              <MobileRecordField label="Payment" value={paymentText(deal)} />
              <MobileRecordField label="Created" value={timeAgo(deal.created_at)} />
            </MobileRecordGrid>
            <div className="mt-4 flex justify-end">{rowAction(deal)}</div>
          </MobileRecordCard>
        ))}
      </div>

      <Pagination page={page} total={data!.total} onPageChange={onPageChange} noun="deals" />
    </div>
  );
}
