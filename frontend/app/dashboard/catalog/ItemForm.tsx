"use client";

import { useRef, useState } from "react";
import { Loader2, Plus, X } from "lucide-react";
import { toast } from "sonner";
import { api, CatalogItem, CatalogVariantGroup } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { GST_RATE_OPTIONS } from "./money";

export const ITEM_TYPES = ["product", "service", "property", "course", "other"];

/** Add/edit form for a catalog item: identity, price, stock and GST, attributes, variant group. */
export function ItemForm({
  onClose,
  onSaved,
  itemToEdit = null,
  variantGroups,
  onGroupCreated,
}: {
  onClose: () => void;
  onSaved: (item: CatalogItem) => void;
  itemToEdit?: CatalogItem | null;
  variantGroups: CatalogVariantGroup[];
  onGroupCreated: (group: CatalogVariantGroup) => void;
}) {
  const [name, setName] = useState(itemToEdit?.name || "");
  const [itemType, setItemType] = useState(itemToEdit?.item_type || ITEM_TYPES[0]);
  const [description, setDescription] = useState(itemToEdit?.description || "");
  const [priceRupees, setPriceRupees] = useState(
    itemToEdit?.price_paise != null ? String(itemToEdit.price_paise / 100) : ""
  );
  const [priceNote, setPriceNote] = useState(itemToEdit?.price_note || "");
  const [stockQuantity, setStockQuantity] = useState(
    itemToEdit?.stock_quantity != null ? String(itemToEdit.stock_quantity) : ""
  );
  const [gstRate, setGstRate] = useState(
    itemToEdit?.gst_rate != null ? String(itemToEdit.gst_rate) : ""
  );
  const [variantGroupId, setVariantGroupId] = useState(itemToEdit?.variant_group_id || "");

  const nextAttrId = useRef(0);
  const [attributes, setAttributes] = useState<{ id: number; key: string; value: string }[]>(() => {
    if (itemToEdit?.attributes) {
      const entries = Object.entries(itemToEdit.attributes);
      return entries.length > 0
        ? entries.map(([key, value]) => ({ id: nextAttrId.current++, key, value }))
        : [{ id: nextAttrId.current++, key: "", value: "" }];
    }
    return [{ id: nextAttrId.current++, key: "", value: "" }];
  });

  const [showNewGroupInput, setShowNewGroupInput] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [isCreatingGroup, setIsCreatingGroup] = useState(false);
  const [groupError, setGroupError] = useState<string | null>(null);

  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreateGroup() {
    if (!newGroupName.trim()) return;
    setIsCreatingGroup(true);
    setGroupError(null);
    try {
      const newGroup = await api.catalog.createVariantGroup({
        name: newGroupName.trim(),
        item_type: itemType,
      });
      onGroupCreated(newGroup);
      setVariantGroupId(newGroup.id);
      setNewGroupName("");
      setShowNewGroupInput(false);
    } catch (err) {
      setGroupError(err instanceof Error ? err.message : "Failed to create group");
    } finally {
      setIsCreatingGroup(false);
    }
  }

  function handleAddAttribute() {
    setAttributes((prev) => [...prev, { id: nextAttrId.current++, key: "", value: "" }]);
  }

  function handleRemoveAttribute(id: number) {
    setAttributes((prev) => prev.filter((attr) => attr.id !== id));
  }

  function handleAttributeChange(id: number, field: "key" | "value", val: string) {
    setAttributes((prev) =>
      prev.map((attr) => (attr.id === id ? { ...attr, [field]: val } : attr))
    );
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    setIsSaving(true);
    setError(null);

    const attrRecord: Record<string, string> = {};
    for (const attr of attributes) {
      const k = attr.key.trim();
      const v = attr.value.trim();
      if (k) {
        attrRecord[k] = v;
      }
    }

    const trimmedPrice = priceRupees.trim();
    if (trimmedPrice && (Number.isNaN(Number(trimmedPrice)) || Number(trimmedPrice) < 0)) {
      setError("Price must be a non-negative number");
      setIsSaving(false);
      return;
    }
    const trimmedStock = itemType === "product" ? stockQuantity.trim() : "";
    if (trimmedStock && (Number.isNaN(Number(trimmedStock)) || Number(trimmedStock) < 0)) {
      setError("Stock must be a non-negative number");
      setIsSaving(false);
      return;
    }

    try {
      let savedItem: CatalogItem;
      const payload = {
        name: name.trim(),
        item_type: itemType,
        description: description.trim() || null,
        variant_group_id: variantGroupId || null,
        attributes: attrRecord,
        price_paise: trimmedPrice ? Math.round(Number(trimmedPrice) * 100) : null,
        price_note: priceNote.trim() || null,
        stock_quantity: trimmedStock ? Math.round(Number(trimmedStock)) : null,
        gst_rate: gstRate === "" ? null : Number(gstRate),
      };

      if (itemToEdit) {
        savedItem = await api.catalog.updateItem(itemToEdit.id, payload);
      } else {
        savedItem = await api.catalog.createItem(payload);
      }
      onSaved(savedItem);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to save item";
      setError(message);
      toast.error(message);
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-card bg-white p-5 shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="font-display text-lg font-bold text-ink">
            {itemToEdit ? "Edit product" : "Add product"}
          </h3>
          <button type="button" onClick={onClose} className="text-ink-muted hover:text-ink" aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-semibold uppercase text-ink-muted">Name</label>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="h-10 w-full rounded-xl border border-border bg-surface-low px-3 text-sm outline-none focus:border-primary"
              placeholder="e.g. Chocolate Cake"
              autoFocus
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold uppercase text-ink-muted">Type</label>
            <Select
              value={itemType}
              onChange={setItemType}
              options={ITEM_TYPES.map((type) => ({ value: type, label: <span className="capitalize">{type}</span>, text: type }))}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold uppercase text-ink-muted">Price (optional)</label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-ink-muted">₹</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={priceRupees}
                  onChange={(event) => setPriceRupees(event.target.value)}
                  className="h-10 w-full rounded-xl border border-border bg-surface-low pl-7 pr-3 text-sm outline-none focus:border-primary"
                  placeholder="3200"
                />
              </div>
              <input
                type="text"
                value={priceNote}
                onChange={(event) => setPriceNote(event.target.value)}
                className="h-10 w-40 rounded-xl border border-border bg-surface-low px-3 text-sm outline-none focus:border-primary"
                placeholder="e.g. starting from"
              />
            </div>
            <p className="mt-1 text-xs text-ink-muted">
              When set, Anril can quote this price directly in WhatsApp replies.
            </p>
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold uppercase text-ink-muted">GST rate (optional)</label>
            <Select
              value={gstRate}
              onChange={setGstRate}
              options={[{ value: "", label: "None" }, ...GST_RATE_OPTIONS.map((rate) => ({ value: String(rate), label: `${rate}%` }))]}
            />
            <p className="mt-1 text-xs text-ink-muted">Used on your monthly sales file, not shown to customers.</p>
          </div>
          {itemType === "product" && (
            <div>
              <label className="mb-1 block text-xs font-semibold uppercase text-ink-muted">Stock (optional)</label>
              <input
                type="number"
                min="0"
                step="1"
                value={stockQuantity}
                onChange={(event) => setStockQuantity(event.target.value)}
                className="h-10 w-full rounded-xl border border-border bg-surface-low px-3 text-sm outline-none focus:border-primary"
                placeholder="Leave blank if you don't track stock for this item"
              />
              <p className="mt-1 text-xs text-ink-muted">
                {itemToEdit
                  ? "Changes are saved as a stock correction in the history."
                  : "When set, Anril stops recommending this item for purchase once it hits 0 — but can still tell a customer it's out of stock if asked."}
              </p>
            </div>
          )}
          <div>
            <label className="mb-1 block text-xs font-semibold uppercase text-ink-muted">Description (optional)</label>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={3}
              className="w-full rounded-xl border border-border bg-surface-low px-3 py-2 text-sm outline-none focus:border-primary"
              placeholder="Short description Anril can use when recommending this item"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold uppercase text-ink-muted">Variant Group</label>
            {!showNewGroupInput ? (
              <Select
                value={variantGroupId}
                onChange={(val) => {
                  if (val === "__new__") {
                    setShowNewGroupInput(true);
                  } else {
                    setVariantGroupId(val);
                  }
                }}
                options={[
                  { value: "", label: "None (Ungrouped)" },
                  ...variantGroups.map((group) => ({ value: group.id, label: `${group.name} (${group.item_type})` })),
                  { value: "__new__", label: "+ New group" },
                ]}
              />
            ) : (
              <div className="flex gap-2">
                <input
                  value={newGroupName}
                  onChange={(event) => setNewGroupName(event.target.value)}
                  className="h-10 flex-1 rounded-xl border border-border bg-surface-low px-3 text-sm outline-none focus:border-primary"
                  placeholder="New group name"
                  autoFocus
                />
                <button
                  type="button"
                  onClick={handleCreateGroup}
                  disabled={isCreatingGroup}
                  className="btn-primary px-3 text-xs font-semibold shrink-0"
                >
                  {isCreatingGroup ? <Loader2 size={12} className="animate-spin" /> : "Create"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowNewGroupInput(false);
                    setNewGroupName("");
                  }}
                  className="btn-ghost px-3 text-xs shrink-0"
                >
                  Cancel
                </button>
              </div>
            )}
            {groupError && <p className="mt-1 text-xs text-danger">{groupError}</p>}
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold uppercase text-ink-muted">Attributes</label>
            <div className="space-y-2">
              {attributes.map((attr) => (
                <div key={attr.id} className="flex items-center gap-2">
                  <input
                    value={attr.key}
                    onChange={(e) => handleAttributeChange(attr.id, "key", e.target.value)}
                    className="h-9 flex-1 rounded-xl border border-border bg-surface-low px-3 text-xs outline-none focus:border-primary"
                    placeholder="Key (e.g. location)"
                  />
                  <input
                    value={attr.value}
                    onChange={(e) => handleAttributeChange(attr.id, "value", e.target.value)}
                    className="h-9 flex-1 rounded-xl border border-border bg-surface-low px-3 text-xs outline-none focus:border-primary"
                    placeholder="Value (e.g. Coimbatore)"
                  />
                  <button
                    type="button"
                    onClick={() => handleRemoveAttribute(attr.id)}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-ink-muted hover:bg-danger/10 hover:text-danger"
                    aria-label="Remove attribute"
                  >
                    <X size={14} />
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={handleAddAttribute}
                className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
              >
                <Plus size={12} />
                Add attribute
              </button>
            </div>
          </div>

          {error && <p className="text-sm text-danger">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} className="btn-ghost px-4 py-2">
              Cancel
            </button>
            <button type="submit" disabled={isSaving} className="btn-primary inline-flex items-center gap-2 px-4 py-2 disabled:opacity-60">
              {isSaving && <Loader2 size={14} className="animate-spin" />}
              {itemToEdit ? "Save changes" : "Add product"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
