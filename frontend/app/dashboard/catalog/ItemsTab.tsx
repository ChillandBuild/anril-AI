"use client";

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, Loader2, Plus, Printer, Search, Sparkles, Upload } from "lucide-react";
import { api, CatalogItem, CatalogVariantGroup } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Pagination, usePagedList } from "@/components/ui/Pagination";
import { ItemThumb } from "./ItemThumb";
import { MetaCatalogueBar } from "./MetaCatalogueBar";
import { formatPaise, isLow, stockValuePaise } from "./money";
import { costsHidden } from "@/lib/billBrand";
import { MobileRecordCard, MobileRecordHeader } from "@/components/MobileRecord";

type Filter = "all" | "out" | "low" | "waiting" | "not_selling" | "draft";

const NOT_SELLING_DAYS = 30;

function notSelling(item: CatalogItem): boolean {
  if (item.stock_quantity == null || item.stock_quantity <= 0 || (item.sold_30d ?? 0) > 0) return false;
  return Date.now() - new Date(item.created_at).getTime() > NOT_SELLING_DAYS * 86_400_000;
}

function isOut(item: CatalogItem): boolean {
  return item.stock_quantity === 0 || (item.out_variants?.length ?? 0) > 0;
}

function sizesText(item: CatalogItem): string {
  const s = item.sizes?.length ?? 0;
  const c = item.colours?.length ?? 0;
  if (!s && !c) return "—";
  const parts = [];
  if (c) parts.push(`${c} colour${c === 1 ? "" : "s"}`);
  if (s) parts.push(s <= 2 ? item.sizes!.join(", ") : `${s} sizes`);
  return parts.join(" · ");
}

function StockCell({ item }: { item: CatalogItem }) {
  if (item.item_type !== "product") return <span className="text-ink-muted">—</span>;
  if (item.stock_quantity == null) return <span className="text-ink-muted">Not counted</span>;
  const out = item.out_variants?.length ?? 0;
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span className="font-bold tabular-nums text-ink">{item.stock_quantity}</span>
      {item.stock_quantity === 0 ? (
        <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[11px] font-bold text-rose-700">Out</span>
      ) : out > 0 ? (
        <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[11px] font-bold text-rose-700">{out} out</span>
      ) : isLow(item) ? (
        <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-bold text-amber-700">{item.stock_quantity} left</span>
      ) : null}
    </span>
  );
}

function SyncDot({ item }: { item: CatalogItem }) {
  if (item.item_type !== "product" || item.status !== "ready") return null;
  if (item.meta_sync_state === "error" || item.meta_sync_state === "skipped") {
    return <span title={item.meta_sync_error ?? "Needs a fix"} className="h-2 w-2 shrink-0 rounded-full bg-rose-500" />;
  }
  if (item.meta_sync_state === "synced" && !item.meta_pending) {
    return <span title="On your WhatsApp catalogue" className="h-2 w-2 shrink-0 rounded-full bg-emerald-500" />;
  }
  return null;
}

export function StatCard({ icon, label, value, sub, tone, active, onClick }: {
  icon: string; label: string; value: string; sub: string; tone?: "red" | "amber" | "plain"; active?: boolean; onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      aria-pressed={active}
      className={cn(
        "rounded-card border bg-white px-3 py-2 text-left shadow-sm transition-colors enabled:hover:border-primary/40 md:px-4 md:py-3",
        active ? "border-primary ring-1 ring-primary/30" : "border-border"
      )}
    >
      <p className="text-[13px] font-semibold text-ink-muted"><span aria-hidden>{icon}</span> {label}</p>
      <p className={cn("mt-0.5 font-display text-2xl font-bold tabular-nums",
        tone === "red" ? "text-rose-700" : tone === "amber" ? "text-amber-700" : "text-ink")}>{value}</p>
      <p className="truncate text-xs text-ink-muted max-md:hidden" title={sub}>{sub}</p>
    </button>
  );
}

export function ItemsTab({ canManage, toolbarSlot }: { canManage: boolean; toolbarSlot: HTMLElement | null }) {
  const router = useRouter();
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [groups, setGroups] = useState<CatalogVariantGroup[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isReindexing, setIsReindexing] = useState(false);

  async function loadItems(q?: string) {
    setIsLoading(true);
    setError(null);
    try {
      setItems(await api.catalog.listItems(q));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load your items");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    const handle = setTimeout(() => loadItems(query || undefined), 300);
    return () => clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    api.catalog.listVariantGroups().then(setGroups).catch(() => setGroups([]));
  }, []);

  const groupName = useMemo(() => new Map(groups.map((g) => [g.id, g.name])), [groups]);
  const products = useMemo(() => items.filter((i) => i.item_type === "product"), [items]);
  const missingIndex = useMemo(() => items.filter((i) => i.status === "ready" && !i.embedding).length, [items]);

  // The API leaves cost prices out for people without Orders access: no stock value then.
  const costsAreHidden = useMemo(() => items.length > 0 && items.every((i) => costsHidden(i as { costs_hidden?: boolean })), [items]);

  const stats = useMemo(() => {
    const tracked = products.filter((i) => i.stock_quantity != null);
    const pieces = tracked.reduce((a, i) => a + Math.max(i.stock_quantity ?? 0, 0), 0);
    const value = tracked.reduce((a, i) => a + (stockValuePaise(i) ?? 0), 0);
    const noCost = tracked.filter((i) => (i.stock_quantity ?? 0) > 0 && i.cost_price_paise == null).length;
    const outNames = products.flatMap((i) =>
      i.stock_quantity === 0 ? [i.name] : (i.out_variants ?? []).map((v) => `${i.name.split(" ")[0]} ${v}`));
    return {
      pieces, value, noCost, outNames,
      low: products.filter((i) => !isOut(i) && isLow(i)).length,
      waitingPeople: items.reduce((a, i) => a + (i.waiting ?? 0), 0),
      notSelling: products.filter(notSelling).length,
    };
  }, [items, products]);

  const counts: Record<Filter, number> = useMemo(() => ({
    all: items.length,
    out: products.filter(isOut).length,
    low: products.filter((i) => !isOut(i) && isLow(i)).length,
    waiting: items.filter((i) => (i.waiting ?? 0) > 0).length,
    not_selling: products.filter(notSelling).length,
    draft: items.filter((i) => i.status === "draft").length,
  }), [items, products]);

  const shown = useMemo(() => items.filter((i) => {
    switch (filter) {
      case "out": return i.item_type === "product" && isOut(i);
      case "low": return i.item_type === "product" && !isOut(i) && isLow(i);
      case "waiting": return (i.waiting ?? 0) > 0;
      case "not_selling": return i.item_type === "product" && notSelling(i);
      case "draft": return i.status === "draft";
      default: return true;
    }
  }), [items, filter]);

  const paged = usePagedList(shown, `${query}|${filter}`);

  async function handleReindex() {
    setIsReindexing(true);
    try {
      await api.catalog.reindex();
      await loadItems(query || undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't refresh the AI index");
    } finally {
      setIsReindexing(false);
    }
  }

  const toggle = (f: Filter) => setFilter((cur) => (cur === f ? "all" : f));
  const FILTERS: { id: Filter; label: string }[] = [
    { id: "all", label: "All" },
    { id: "out", label: "Out of stock" },
    { id: "low", label: "Low stock" },
    { id: "waiting", label: "Waiting for stock" },
    { id: "not_selling", label: "Not selling" },
    { id: "draft", label: "Drafts" },
  ];

  return (
    <div className="space-y-4">
      {toolbarSlot && createPortal(
        <>
          <label className="relative block w-full sm:w-56">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search items"
              className="h-9 w-full rounded-xl border border-border bg-white pl-9 pr-3 text-sm outline-none transition-colors focus:border-primary"
            />
          </label>
          {canManage && missingIndex > 0 && (
            <button type="button" onClick={handleReindex} disabled={isReindexing}
              title={`${missingIndex} item(s) aren't indexed yet, so the AI may not find them`}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-amber-200 bg-amber-50 px-3 text-sm font-semibold text-amber-800 hover:bg-amber-100 disabled:opacity-60">
              {isReindexing ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              Teach the AI {missingIndex} new
            </button>
          )}
          {canManage && (
            <Link href="/dashboard/catalog/price-list"
              className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border bg-white px-3 text-sm font-semibold text-ink hover:bg-surface-low">
              <Upload size={15} /> Upload price list
            </Link>
          )}
          {canManage && (
            <Link href="/dashboard/catalog/labels"
              className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border bg-white px-3 text-sm font-semibold text-ink hover:bg-surface-low">
              <Printer size={15} /> Barcode labels
            </Link>
          )}
          {canManage && (
            <Link href="/dashboard/catalog/items/new" className="btn-primary inline-flex h-9 items-center justify-center gap-1.5 !py-0 max-md:order-first max-md:h-11 max-md:w-full">
              <Plus size={16} /> Add item
            </Link>
          )}
        </>,
        toolbarSlot
      )}

      <MetaCatalogueBar canManage={canManage} onChanged={() => loadItems(query || undefined)} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {costsAreHidden ? (
          <StatCard icon="📦" label="Stock value" value="Not shown" sub={`${stats.pieces} pieces · cost prices are for people who can see Orders`} />
        ) : (
          <StatCard icon="📦" label="Stock value" value={formatPaise(stats.value)}
            sub={`at cost price · ${stats.pieces} pieces${stats.noCost ? ` · ${stats.noCost} without cost` : ""}`} />
        )}
        <StatCard icon="🔴" label="Out of stock" tone={stats.outNames.length ? "red" : "plain"}
          value={`${stats.outNames.length} ${stats.outNames.length === 1 ? "size" : "sizes"}`}
          sub={stats.outNames.slice(0, 3).join(", ") || "Nothing sold out"} active={filter === "out"} onClick={() => toggle("out")} />
        <StatCard icon="🟡" label="Low" tone={stats.low ? "amber" : "plain"} value={`${stats.low} ${stats.low === 1 ? "item" : "items"}`}
          sub="at or below the alert level" active={filter === "low"} onClick={() => toggle("low")} />
        <StatCard icon="🙋" label="Asked but out" value={`${stats.waitingPeople} ${stats.waitingPeople === 1 ? "person" : "people"}`}
          sub="on the waiting list for a sold-out size" active={filter === "waiting"} onClick={() => toggle("waiting")} />
        <StatCard icon="🐢" label="Not selling" value={`${stats.notSelling} ${stats.notSelling === 1 ? "item" : "items"}`}
          sub={`nothing sold in ${NOT_SELLING_DAYS} days`} active={filter === "not_selling"} onClick={() => toggle("not_selling")} />
      </div>

      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button key={f.id} type="button" onClick={() => setFilter(f.id)} aria-pressed={filter === f.id}
            className={cn("inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-sm font-semibold transition-colors",
              filter === f.id ? "border-primary bg-primary-50 text-primary-800" : "border-border bg-white text-ink-muted hover:text-ink")}>
            {f.label}{f.id === "all" || counts[f.id] ? <span className="tabular-nums opacity-70">{counts[f.id]}</span> : null}
          </button>
        ))}
      </div>

      {error && <div className="rounded-card border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">{error}</div>}

      <div className="md:overflow-x-auto md:rounded-card md:border md:border-border md:bg-white md:shadow-sm">
        <div className="hidden md:block">
        <table className="w-full min-w-[920px] text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-low text-left font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              <th className="px-4 py-3">Item</th>
              <th className="px-3 py-3">Sizes / colours</th>
              <th className="px-3 py-3">Price</th>
              <th className="px-3 py-3">GST · HSN</th>
              <th className="px-3 py-3">Stock</th>
              <th className="px-3 py-3">Stock value</th>
              <th className="px-3 py-3" title="People on the waiting list for a sold-out size">Waiting</th>
              <th className="px-3 py-3" />
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={8} className="px-4 py-10 text-center text-ink-muted">
                <Loader2 size={16} className="mr-2 inline animate-spin" />Loading items…
              </td></tr>
            )}
            {!isLoading && shown.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-10 text-center text-ink-muted">
                {items.length === 0 ? "No items yet. Tap “Add item” to add your first one." : "Nothing here."}
              </td></tr>
            )}
            {!isLoading && paged.pageItems.map((item) => {
              const value = stockValuePaise(item);
              const href = `/dashboard/catalog/items/${item.id}`;
              return (
                <tr key={item.id} onClick={() => router.push(href)}
                  className="cursor-pointer border-b border-border-subtle last:border-b-0 hover:bg-surface-low/60">
                  <td className="px-4 py-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <ItemThumb name={item.name} thumbnailUrl={item.thumbnail_url} />
                      <div className="min-w-0">
                        <p className="flex items-center gap-1.5 font-bold text-ink">
                          <span className="truncate">{item.name}</span>
                          <SyncDot item={item} />
                          {item.status === "draft" && <span className="rounded-full bg-surface-low px-1.5 text-[10px] font-bold uppercase text-ink-muted">Draft</span>}
                        </p>
                        <p className="truncate text-xs text-ink-muted">
                          {(item.variant_group_id && groupName.get(item.variant_group_id)) || (item.item_type === "product" ? "" : item.item_type)}
                        </p>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-3 text-ink">{sizesText(item)}</td>
                  <td className="px-3 py-3 font-bold tabular-nums text-ink">{item.price_paise != null ? formatPaise(item.price_paise) : "—"}</td>
                  <td className="px-3 py-3 font-mono text-xs text-ink-muted">
                    {item.gst_rate != null ? `${item.gst_rate}%` : "—"}{item.hsn_code ? ` · ${item.hsn_code}` : ""}
                  </td>
                  <td className="px-3 py-3"><StockCell item={item} /></td>
                  <td className="px-3 py-3 tabular-nums text-ink">{value != null ? formatPaise(value) : "—"}</td>
                  <td className="px-3 py-3 tabular-nums text-ink">{item.waiting || "—"}</td>
                  <td className="px-3 py-3 text-right">
                    <Link href={href} onClick={(e) => e.stopPropagation()} className="inline-flex items-center font-semibold text-primary hover:underline">
                      Open <ChevronRight size={14} />
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        </div>
        <div className="space-y-2 md:hidden">
          {isLoading && (
            <div className="rounded-2xl border border-surface-mid bg-white px-4 py-10 text-center text-sm text-ink-muted shadow-sm">
              <Loader2 size={16} className="mr-2 inline animate-spin" />Loading items...
            </div>
          )}
          {!isLoading && shown.length === 0 && (
            <div className="rounded-2xl border border-surface-mid bg-white px-4 py-10 text-center text-sm text-ink-muted shadow-sm">
              {items.length === 0 ? "No items yet. Tap \“Add item\” to add your first one." : "Nothing here."}
            </div>
          )}
          {!isLoading && paged.pageItems.map((item) => {
            const value = stockValuePaise(item);
            const href = `/dashboard/catalog/items/${item.id}`;
            const kind = (item.variant_group_id && groupName.get(item.variant_group_id)) || (item.item_type === "product" ? "" : item.item_type);
            const sizes = sizesText(item);
            return (
              <MobileRecordCard key={item.id} className="cursor-pointer p-3" onClick={() => router.push(href)}>
                <div className="flex items-start gap-3">
                  <ItemThumb name={item.name} thumbnailUrl={item.thumbnail_url} />
                  <div className="min-w-0 flex-1">
                    <MobileRecordHeader
                      title={
                        <span className="flex items-center gap-1.5">
                          <span className="truncate">{item.name}</span>
                          <SyncDot item={item} />
                          {item.status === "draft" && <span className="rounded-full bg-surface-low px-1.5 text-[10px] font-bold uppercase text-ink-muted">Draft</span>}
                        </span>
                      }
                      subtitle={[sizes !== "\—" ? sizes : "", kind].filter(Boolean).join(" \· ") || undefined}
                      aside={<StockCell item={item} />}
                    />
                    <p className="mt-1.5 text-[13px] text-ink">
                      <span className="font-bold tabular-nums">{item.price_paise != null ? formatPaise(item.price_paise) : "\—"}</span>
                      {item.gst_rate != null && <span className="text-ink-muted"> \· GST {item.gst_rate}%</span>}
                      {value != null && <span className="text-ink-muted"> \· Stock value {formatPaise(value)}</span>}
                      {item.waiting ? <span className="text-ink-muted"> \· {item.waiting} waiting</span> : null}
                    </p>
                  </div>
                </div>
                <div className="mt-2 flex justify-end">
                  <Link href={href} onClick={(e) => e.stopPropagation()}
                    className="inline-flex min-h-9 items-center text-[13px] font-semibold text-primary">
                    Open <ChevronRight size={14} />
                  </Link>
                </div>
              </MobileRecordCard>
            );
          })}
        </div>
        <Pagination page={paged.page} total={paged.total} onPageChange={paged.setPage} noun="items" />
      </div>
      <p className="text-xs text-ink-muted">
        Tap an item to see and correct the stock of each size and colour. Stock goes down by itself with every bill.
      </p>
    </div>
  );
}
