"use client";

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Layers, Loader2, Package, Pencil, Plus, Search, Sparkles, Trash2, X } from "lucide-react";
import { api, CatalogItem, CatalogVariantGroup } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ItemForm, ITEM_TYPES } from "./ItemForm";
import { ItemThumb } from "./ItemThumb";
import { StockDialog } from "./StockDialog";
import { availableQuantity, formatPaise } from "./money";

const GRID_COLS = "grid-cols-[1.7fr_100px_140px_130px_110px_100px_100px_80px]";

function StockCell({ item }: { item: CatalogItem }) {
  if (item.stock_quantity == null) {
    return <span className="text-ink-muted">Not tracked</span>;
  }
  const held = item.held_quantity ?? 0;
  const available = availableQuantity(item.stock_quantity, held);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1.5">
        <span className="text-ink">
          {item.stock_quantity} in stock{held > 0 ? ` · ${held} held` : ""}
        </span>
        {available <= 0 && (
          <span className="rounded-full bg-danger/10 px-1.5 py-0.5 text-[10px] font-bold uppercase text-danger">
            Out
          </span>
        )}
        {available > 0 && available <= 5 && (
          <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-amber-700">
            Low
          </span>
        )}
      </div>
    </div>
  );
}

export function ItemsTab({ canManage, toolbarSlot }: { canManage: boolean; toolbarSlot: HTMLElement | null }) {
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [variantGroups, setVariantGroups] = useState<CatalogVariantGroup[]>([]);
  const [isLoadingGroups, setIsLoadingGroups] = useState(true);
  const [groupsError, setGroupsError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingItem, setEditingItem] = useState<CatalogItem | null>(null);
  const [stockItem, setStockItem] = useState<CatalogItem | null>(null);
  const [isReindexing, setIsReindexing] = useState(false);
  const [showGroups, setShowGroups] = useState(false);
  const itemsMissingEmbedding = useMemo(
    () => items.filter((item) => item.status === "ready" && !item.embedding).length,
    [items]
  );

  // Variant groups panel state
  const [newPanelGroupName, setNewPanelGroupName] = useState("");
  const [newPanelGroupType, setNewPanelGroupType] = useState(ITEM_TYPES[0]);
  const [isCreatingGroupFromPanel, setIsCreatingGroupFromPanel] = useState(false);
  const [panelGroupError, setPanelGroupError] = useState<string | null>(null);

  async function loadItems(q?: string) {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.catalog.listItems(q);
      setItems(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load catalog items");
    } finally {
      setIsLoading(false);
    }
  }

  async function loadVariantGroups() {
    setIsLoadingGroups(true);
    setGroupsError(null);
    try {
      const data = await api.catalog.listVariantGroups();
      setVariantGroups(data);
    } catch (err) {
      setGroupsError(err instanceof Error ? err.message : "Failed to load variant groups");
    } finally {
      setIsLoadingGroups(false);
    }
  }

  useEffect(() => {
    const handle = setTimeout(() => loadItems(query || undefined), 300);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  useEffect(() => {
    loadVariantGroups();
  }, []);

  useEffect(() => {
    if (successMessage) {
      const t = setTimeout(() => setSuccessMessage(null), 5000);
      return () => clearTimeout(t);
    }
  }, [successMessage]);

  async function handleToggleStatus(item: CatalogItem) {
    if (!canManage) return;
    const nextStatus = item.status === "ready" ? "draft" : "ready";
    try {
      const updated = await api.catalog.updateItem(item.id, { status: nextStatus });
      setItems((prev) => prev.map((i) => (i.id === item.id ? updated : i)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update item status");
    }
  }

  async function handleDelete(item: CatalogItem) {
    if (!canManage) return;
    try {
      await api.catalog.deleteItem(item.id);
      setItems((prev) => prev.filter((i) => i.id !== item.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete item");
    }
  }

  async function handleReindex() {
    if (!canManage) return;
    setIsReindexing(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const res = await api.catalog.reindex();
      if (res.success) {
        setSuccessMessage(`Catalog reindexed successfully! Embedded ${res.items_embedded} of ${res.items_total} items.`);
        await loadItems(query);
      } else {
        setError("Reindexing failed");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reindex catalog");
    } finally {
      setIsReindexing(false);
    }
  }

  async function handleCreateGroupFromPanel() {
    if (!canManage || !newPanelGroupName.trim()) return;
    setIsCreatingGroupFromPanel(true);
    setPanelGroupError(null);
    try {
      const newGroup = await api.catalog.createVariantGroup({
        name: newPanelGroupName.trim(),
        item_type: newPanelGroupType,
      });
      setVariantGroups((prev) => [...prev, newGroup]);
      setNewPanelGroupName("");
    } catch (err) {
      setPanelGroupError(err instanceof Error ? err.message : "Failed to create group");
    } finally {
      setIsCreatingGroupFromPanel(false);
    }
  }

  function handleStockAdjusted(itemId: string, quantityAfter: number | null) {
    setItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, stock_quantity: quantityAfter } : i)));
  }

  return (
    <div className="space-y-4">
      {toolbarSlot &&
        createPortal(
          <>
            <label className="relative block w-full sm:w-56">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search products"
                className="h-9 w-full rounded-xl border border-border bg-surface-low pl-9 pr-3 text-sm outline-none transition-colors focus:border-primary"
              />
            </label>
            <button
              type="button"
              onClick={() => setShowGroups((open) => !open)}
              aria-expanded={showGroups}
              className={cn(
                "inline-flex h-9 items-center gap-1.5 rounded-xl px-2 text-sm font-semibold transition-colors hover:bg-surface-low",
                showGroups ? "text-primary" : "text-ink-muted hover:text-ink"
              )}
            >
              <Layers size={14} />
              <span>Variant groups ({variantGroups.length})</span>
            </button>
            {canManage && (
              <>
                <button
                  type="button"
                  onClick={handleReindex}
                  disabled={isReindexing}
                  className="btn-ghost relative border border-border bg-white text-ink inline-flex items-center justify-center gap-2 h-9 px-3 rounded-xl text-sm transition-colors hover:bg-surface-low disabled:opacity-50"
                  title={
                    itemsMissingEmbedding > 0
                      ? `${itemsMissingEmbedding} item(s) aren't indexed yet -- the AI can't reliably find them. Reindex to fix.`
                      : "Reindex catalog items to refresh AI embeddings"
                  }
                >
                  {isReindexing ? <Loader2 size={15} className="animate-spin text-ink-muted" /> : <Sparkles size={15} className="text-primary" />}
                  <span>{isReindexing ? "Reindexing..." : "Reindex"}</span>
                  {!isReindexing && itemsMissingEmbedding > 0 && (
                    <span className="absolute -right-2 -top-2 flex h-5 min-w-5 items-center justify-center rounded-full bg-amber-500 px-1 text-[11px] font-semibold text-white">
                      {itemsMissingEmbedding}
                    </span>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => setShowAddModal(true)}
                  className="btn-primary inline-flex h-9 items-center justify-center gap-2 !py-0"
                >
                  <Plus size={16} />
                  Add product
                </button>
              </>
            )}
          </>,
          toolbarSlot
        )}

      {error && (
        <div className="rounded-card border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">{error}</div>
      )}

      {successMessage && (
        <div className="rounded-card border border-success/30 bg-success/5 px-4 py-3 text-sm text-success flex justify-between items-center">
          <span>{successMessage}</span>
          <button type="button" onClick={() => setSuccessMessage(null)} className="text-success hover:opacity-70">
            <X size={16} />
          </button>
        </div>
      )}

      {/* Variant Groups Panel -- toggled by the "Variant groups (N)" link in the toolbar */}
      {showGroups && (
        <div className="rounded-card border border-border bg-white p-4 shadow-sm">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between mb-4">
            <p className="text-sm text-ink-muted">
              Group variants (e.g. properties in different locations) so Anril can disambiguate them.
            </p>
            {canManage && (
              <div className="flex flex-wrap gap-2">
                <input
                  value={newPanelGroupName}
                  onChange={(e) => setNewPanelGroupName(e.target.value)}
                  className="h-9 rounded-xl border border-border bg-surface-low px-3 text-sm outline-none focus:border-primary w-48"
                  placeholder="New group name"
                />
                <select
                  value={newPanelGroupType}
                  onChange={(e) => setNewPanelGroupType(e.target.value)}
                  className="h-9 rounded-xl border border-border bg-surface-low px-3 text-sm outline-none focus:border-primary capitalize"
                >
                  {ITEM_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={handleCreateGroupFromPanel}
                  disabled={isCreatingGroupFromPanel || !newPanelGroupName.trim()}
                  className="btn-primary inline-flex items-center justify-center gap-1 px-3 py-1.5 text-xs"
                >
                  <Plus size={12} />
                  Add Group
                </button>
              </div>
            )}
          </div>
          {panelGroupError && <p className="mb-3 text-sm text-danger">{panelGroupError}</p>}
          {groupsError && (
            <p className="mb-3 text-sm text-danger">Failed to load variant groups: {groupsError}</p>
          )}
          {isLoadingGroups ? (
            <div className="flex items-center justify-center gap-2 py-4 text-sm text-ink-muted">
              <Loader2 size={15} className="animate-spin" />
              Loading variant groups...
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {variantGroups.map((group) => {
                const count = items.filter((i) => i.variant_group_id === group.id).length;
                return (
                  <div key={group.id} className="rounded-xl border border-border bg-surface-low p-3">
                    <p className="font-semibold text-ink truncate">{group.name}</p>
                    <div className="mt-1 flex items-center justify-between text-xs text-ink-muted">
                      <span className="capitalize">{group.item_type}</span>
                      <span>{count} {count === 1 ? "item" : "items"}</span>
                    </div>
                  </div>
                );
              })}
              {variantGroups.length === 0 && !groupsError && (
                <p className="text-sm text-ink-muted col-span-full text-center py-4">No variant groups created yet.</p>
              )}
            </div>
          )}
        </div>
      )}

      <div className="overflow-x-auto rounded-card border border-border bg-white shadow-sm">
        <div className="min-w-[900px]">
          <div className={cn("grid gap-3 border-b border-border bg-surface-low px-4 py-3 text-xs font-bold uppercase text-ink-muted", GRID_COLS)}>
            <span>Item</span>
            <span>Price</span>
            <span>Stock</span>
            <span>Variant Group</span>
            <span>Type</span>
            <span>Status</span>
            <span>Updated</span>
            <span />
          </div>
          {isLoading && (
            <div className="flex items-center justify-center gap-2 px-4 py-10 text-sm text-ink-muted">
              <Loader2 size={16} className="animate-spin" />
              Loading products...
            </div>
          )}
          {!isLoading && items.length === 0 && (
            <div className="px-4 py-10 text-center text-sm text-ink-muted">
              No products yet. Click &ldquo;Add product&rdquo; to create your first one.
            </div>
          )}
          {!isLoading &&
            items.map((item) => (
              <div key={item.id} className={cn("grid items-center gap-3 border-b border-border-subtle px-4 py-3 text-sm last:border-b-0", GRID_COLS)}>
                <div className="flex min-w-0 items-center gap-3">
                  <ItemThumb name={item.name} thumbnailUrl={item.thumbnail_url} />
                  <span className="truncate font-semibold text-ink" title={item.name}>{item.name}</span>
                </div>
                <span className="text-ink-muted">{item.price_paise != null ? formatPaise(item.price_paise) : "—"}</span>
                <StockCell item={item} />
                <span className="text-ink-muted truncate" title={variantGroups.find((g) => g.id === item.variant_group_id)?.name || "Ungrouped"}>
                  {variantGroups.find((g) => g.id === item.variant_group_id)?.name || "—"}
                </span>
                <span className="capitalize text-ink-muted">{item.item_type}</span>
                <span>
                  <button
                    type="button"
                    onClick={() => handleToggleStatus(item)}
                    disabled={!canManage}
                    className={cn(
                      "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold transition-colors disabled:cursor-default",
                      item.status === "ready" ? "bg-success/10 text-success" : "bg-warning/10 text-warning"
                    )}
                  >
                    {item.status === "ready" ? "Ready" : "Draft"}
                  </button>
                </span>
                <span className="text-ink-muted">{new Date(item.updated_at).toLocaleDateString()}</span>
                <div className="flex justify-end items-center gap-1">
                  {item.item_type === "product" && (
                    <button
                      type="button"
                      onClick={() => setStockItem(item)}
                      disabled={!canManage}
                      className="inline-flex h-7 items-center gap-1 rounded-lg border border-border px-2 text-xs font-semibold text-ink-muted transition-colors hover:bg-surface-low hover:text-ink disabled:cursor-not-allowed disabled:opacity-45"
                      aria-label={`Update stock for ${item.name}`}
                    >
                      <Package size={12} />
                      Stock
                    </button>
                  )}
                  {canManage && (
                    <>
                      <button
                        type="button"
                        onClick={() => setEditingItem(item)}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-surface-low hover:text-ink"
                        aria-label={`Edit ${item.name}`}
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(item)}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-danger/10 hover:text-danger"
                        aria-label={`Delete ${item.name}`}
                      >
                        <Trash2 size={14} />
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
        </div>
      </div>

      {showAddModal && (
        <ItemForm
          onClose={() => setShowAddModal(false)}
          onSaved={(item) => {
            setItems((prev) => [item, ...prev]);
            setShowAddModal(false);
          }}
          variantGroups={variantGroups}
          onGroupCreated={(newGroup) => setVariantGroups((prev) => [...prev, newGroup])}
        />
      )}

      {editingItem && (
        <ItemForm
          itemToEdit={editingItem}
          onClose={() => setEditingItem(null)}
          onSaved={(updated) => {
            setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
            setEditingItem(null);
          }}
          variantGroups={variantGroups}
          onGroupCreated={(newGroup) => setVariantGroups((prev) => [...prev, newGroup])}
        />
      )}

      {stockItem && (
        <StockDialog
          item={stockItem}
          onClose={() => setStockItem(null)}
          onAdjusted={(quantityAfter) => handleStockAdjusted(stockItem.id, quantityAfter)}
        />
      )}
    </div>
  );
}
