"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ChevronLeft, ExternalLink, History, Loader2, Lock, Minus, Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { api, CatalogItemDetail, CatalogVariantGroup, StockWhy } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Select } from "@/components/ui/Select";
import { useAuthRole } from "../../../contexts/AuthRoleContext";
import { ChipInput, SIZE_PRESETS, cellKey } from "../../VariantChips";
import { StockHistoryDrawer } from "../../StockHistoryDrawer";
import { DEFAULT_LOW_AT, GST_RATE_OPTIONS, formatPaise } from "../../money";

const ITEM_TYPES = ["product", "service", "property", "course", "other"];

const WHY: { id: StockWhy; label: string }[] = [
  { id: "stock_in", label: "New stock came" },
  { id: "found", label: "Found in shop" },
  { id: "damaged", label: "Damaged" },
  { id: "lost", label: "Lost" },
  { id: "supplier_return", label: "Return to supplier" },
  { id: "count_wrong", label: "Count was wrong" },
];

type Saved = { id: string; stock: number };
type Target = { variantId: string | null; label: string; current: number };

const toPaise = (rupees: string) => (rupees.trim() === "" ? null : Math.round(Number(rupees) * 100));
const toRupees = (paise: number | null | undefined) => (paise == null ? "" : String(paise / 100));
const badNumber = (v: string) => v.trim() !== "" && (Number.isNaN(Number(v)) || Number(v) < 0);

function Card({ title, aside, children, className }: { title?: React.ReactNode; aside?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-card border border-border bg-white p-4 shadow-sm sm:p-5", className)}>
      {(title || aside) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="font-display text-base font-bold text-ink">{title}</h2>}
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

function Field({ label, hint, children, className }: { label: React.ReactNode; hint?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1 block text-sm font-semibold text-ink">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-ink-muted">{hint}</span>}
    </label>
  );
}

const inputCls = "h-10 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none transition-colors focus:border-primary disabled:bg-surface-low";

export default function CatalogueItemPage() {
  const { id } = useParams<{ id: string }>();
  const isNew = id === "new";
  const router = useRouter();
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("catalog.manage");

  const [detail, setDetail] = useState<CatalogItemDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [groups, setGroups] = useState<CatalogVariantGroup[]>([]);

  // form
  const [name, setName] = useState("");
  const [itemType, setItemType] = useState("product");
  const [groupId, setGroupId] = useState("");
  const [newGroup, setNewGroup] = useState<string | null>(null);
  const [price, setPrice] = useState("");
  const [priceNote, setPriceNote] = useState("");
  const [gst, setGst] = useState("");
  const [hsn, setHsn] = useState("");
  const [cost, setCost] = useState("");
  const [lowAt, setLowAt] = useState("");
  const [description, setDescription] = useState("");
  const [ready, setReady] = useState(true);
  const [batches, setBatches] = useState(false);
  const [openingStock, setOpeningStock] = useState("");
  // sizes x colours
  const [sizes, setSizes] = useState<string[]>([]);
  const [colours, setColours] = useState<string[]>([]);
  const [rowPrice, setRowPrice] = useState<Record<string, string>>({});
  const [newStock, setNewStock] = useState<Record<string, string>>({});
  const [showGrid, setShowGrid] = useState(false);
  const snapshot = useRef("");

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<Target | null>(null);
  const [to, setTo] = useState(0);
  const [why, setWhy] = useState<StockWhy | null>(null);
  const [correcting, setCorrecting] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const saved = useMemo(() => {
    const map = new Map<string, Saved>();
    detail?.variants.forEach((v) => map.set(cellKey(v.size, v.colour), { id: v.id, stock: v.stock_quantity }));
    return map;
  }, [detail]);
  const hadGrid = (detail?.variants.length ?? 0) > 0;
  const hasGrid = sizes.length > 0 || colours.length > 0;
  const isProduct = itemType === "product";

  const formState = useCallback(() => JSON.stringify({
    name, itemType, groupId, price, priceNote, gst, hsn, cost, lowAt, description, ready, batches, openingStock, sizes, colours, rowPrice, newStock,
  }), [name, itemType, groupId, price, priceNote, gst, hsn, cost, lowAt, description, ready, batches, openingStock, sizes, colours, rowPrice, newStock]);

  const fill = useCallback((d: CatalogItemDetail) => {
    setDetail(d);
    setName(d.name);
    setItemType(d.item_type);
    setGroupId(d.variant_group_id ?? "");
    setPrice(toRupees(d.price_paise));
    setPriceNote(d.price_note ?? "");
    setGst(d.gst_rate != null ? String(d.gst_rate) : "");
    setHsn(d.hsn_code ?? "");
    setCost(toRupees(d.cost_price_paise));
    setLowAt(d.low_stock_at != null ? String(d.low_stock_at) : "");
    setDescription(d.description ?? "");
    setReady(d.status === "ready");
    setBatches(d.tracks_batches === true);
    setOpeningStock("");
    setSizes(d.sizes);
    setColours(d.colours);
    const rp: Record<string, string> = {};
    (d.colours.length ? d.colours : [""]).forEach((c) => {
      const prices = d.variants.filter((v) => (v.colour ?? "") === c).map((v) => v.price_paise);
      if (prices.length && prices.every((p) => p != null && p === prices[0])) rp[c] = toRupees(prices[0]);
    });
    setRowPrice(rp);
    setNewStock({});
    setShowGrid(d.variants.length > 0);
  }, []);

  useEffect(() => {
    api.catalog.listVariantGroups().then(setGroups).catch(() => setGroups([]));
    if (isNew) {
      snapshot.current = "";
      return;
    }
    api.catalog.item(id).then(fill).catch((e) => setLoadError(e instanceof Error ? e.message : "Couldn't load this item"));
  }, [id, isNew, fill]);

  // The first render after loading is the "saved" state; anything after is unsaved.
  useEffect(() => {
    if (detail && !snapshot.current) snapshot.current = formState();
  }, [detail, formState]);
  const dirty = isNew ? name.trim() !== "" : !!snapshot.current && snapshot.current !== formState();

  // Default correction target: the single stock number, or the first sold-out size.
  useEffect(() => {
    if (!detail || detail.item_type !== "product") return setTarget(null);
    if (detail.variants.length === 0) {
      return setTarget({ variantId: null, label: "", current: detail.stock_quantity ?? 0 });
    }
    setTarget((cur) => {
      const still = cur?.variantId && detail.variants.find((v) => v.id === cur.variantId);
      const pick = still || detail.variants.find((v) => v.stock_quantity === 0) || detail.variants[0];
      return { variantId: pick.id, label: [pick.colour, pick.size].filter(Boolean).join(" · "), current: pick.stock_quantity };
    });
  }, [detail]);
  useEffect(() => {
    setTo(target ? target.current : 0);
    setWhy(null);
  }, [target]);

  const sizeCols = sizes.length ? sizes : [null];
  const colourRows = colours.length ? colours : [null];
  const total = detail?.stock_quantity ?? null;

  async function save() {
    if (!name.trim()) return setError("Type the item name");
    for (const [label, v] of [["Price", price], ["Cost price", cost], ["Stock", openingStock], ["Low stock", lowAt]] as const) {
      if (badNumber(v)) return setError(`${label} must be a number, 0 or more`);
    }
    if (hsn.trim() && !/^\d{4,8}$/.test(hsn.trim())) return setError("HSN is 4 to 8 digits");
    const useGrid = isProduct && showGrid && hasGrid;
    if (hadGrid && !useGrid && !window.confirm("Remove the sizes and colours? Their stock goes to 0.")) return;
    setSaving(true);
    setError(null);
    try {
      let group = groupId || null;
      if (newGroup !== null && newGroup.trim()) {
        const created = await api.catalog.createVariantGroup({ name: newGroup.trim(), item_type: itemType });
        setGroups((g) => [...g, created]);
        group = created.id;
        setGroupId(created.id);
        setNewGroup(null);
      }
      const payload = {
        name: name.trim(),
        item_type: itemType,
        description: description.trim() || null,
        variant_group_id: group,
        price_paise: toPaise(price),
        price_note: priceNote.trim() || null,
        gst_rate: gst === "" ? null : Number(gst),
        hsn_code: hsn.trim() || null,
        cost_price_paise: toPaise(cost),
        low_stock_at: lowAt.trim() === "" ? null : Math.round(Number(lowAt)),
        status: (ready ? "ready" : "draft") as "ready" | "draft",
        ...(isNew && isProduct && !useGrid && openingStock.trim() !== "" ? { stock_quantity: Math.round(Number(openingStock)) } : {}),
      };
      const item = isNew ? await api.catalog.createItem(payload) : await api.catalog.updateItem(id, payload);
      if (isNew && payload.status === "ready") await api.catalog.updateItem(item.id, { status: "ready" });
      if (useGrid || hadGrid) {
        const cells = useGrid
          ? colourRows.flatMap((c) => sizeCols.map((s) => {
            const key = cellKey(s, c);
            const old = saved.get(key);
            const typed = Math.max(0, Math.round(Number(newStock[key] || 0)));
            return { size: s, colour: c, stock: old ? old.stock : typed, price_paise: toPaise(rowPrice[c ?? ""] ?? "") };
          })).filter((cell) => cell.size || cell.colour)
          : [];
        await api.catalog.saveVariants(item.id, { sizes: useGrid ? sizes : [], colours: useGrid ? colours : [], cells });
      }
      if (isProduct && batches !== (detail?.tracks_batches === true)) await api.catalog.setBatchTracking(item.id, batches);
      toast.success(isNew ? "Item added" : "Saved");
      snapshot.current = "";
      if (isNew) {
        router.replace(`/dashboard/catalog/items/${item.id}`);
      } else {
        fill(await api.catalog.item(item.id));
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : "Couldn't save";
      setError(message);
      toast.error(message);
    } finally {
      setSaving(false);
    }
  }

  async function saveCorrection() {
    if (!detail || !target || !why) return;
    setCorrecting(true);
    try {
      const updated = await api.catalog.correctStock(detail.id, { variant_id: target.variantId, to, why });
      setDetail(updated);
      toast.success("Stock corrected and saved in the history");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't correct the stock");
    } finally {
      setCorrecting(false);
    }
  }

  async function addPhotos(files: FileList | null) {
    if (!detail || !files?.length) return;
    setUploading(true);
    try {
      for (const file of Array.from(files)) await api.catalog.uploadMedia(detail.id, file);
      const fresh = await api.catalog.item(detail.id);
      setDetail((d) => (d ? { ...d, photos: fresh.photos, meta_sync_state: fresh.meta_sync_state, meta_sync_error: fresh.meta_sync_error, meta_pending: fresh.meta_pending } : fresh));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't add the photo");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function removePhoto(mediaId: string) {
    if (!detail || !window.confirm("Remove this photo?")) return;
    try {
      await api.catalog.deleteMedia(mediaId);
      setDetail({ ...detail, photos: detail.photos.filter((p) => p.id !== mediaId) });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't remove the photo");
    }
  }

  async function deleteItem() {
    if (!detail || !window.confirm(`Delete ${detail.name}? Its stock history goes too, and it comes off your WhatsApp catalogue.`)) return;
    try {
      await api.catalog.deleteItem(detail.id);
      toast.success("Item deleted");
      router.push("/dashboard/catalog");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't delete the item");
    }
  }

  if (loadError) {
    return (
      <div className="py-20 text-center text-sm text-ink-muted">
        {loadError} <Link href="/dashboard/catalog" className="font-semibold text-primary">Back to catalogue</Link>
      </div>
    );
  }
  if (!isNew && !detail) return <div className="min-h-[320px] animate-pulse rounded-card bg-surface-low" />;

  const stockValue = total != null && detail?.cost_price_paise != null ? Math.max(total, 0) * detail.cost_price_paise : null;
  const ro = !canManage;

  return (
    <div className="space-y-4 pb-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href="/dashboard/catalog" className="inline-flex h-9 items-center gap-1 rounded-xl border border-border bg-white px-3 text-sm font-semibold text-ink hover:bg-surface-low">
          <ChevronLeft size={16} /> Back to catalogue
        </Link>
        <div className="flex items-center gap-3">
          {dirty && !isNew && <span className="text-xs font-semibold text-amber-700">Unsaved changes</span>}
          {canManage && (
            <button type="button" onClick={save} disabled={saving || (!dirty && !isNew)} className="btn-primary inline-flex h-9 items-center gap-1.5 !py-0 disabled:opacity-50">
              {saving && <Loader2 size={14} className="animate-spin" />} {isNew ? "Add item" : "Save"}
            </button>
          )}
        </div>
      </div>
      {error && <div className="rounded-card border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">{error}</div>}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-4">
          <Card title="Basic">
            <div className="mb-4 flex flex-wrap items-center gap-2">
              {detail?.photos.map((p) => (
                <div key={p.id} className="group relative h-20 w-20 overflow-hidden rounded-xl border border-border bg-surface-low">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={p.url} alt={p.label ?? name} className="h-full w-full object-cover" />
                  {canManage && (
                    <button type="button" onClick={() => removePhoto(p.id)} aria-label="Remove photo"
                      className="absolute right-1 top-1 hidden rounded-full bg-black/60 p-0.5 text-white group-hover:block">
                      <X size={12} />
                    </button>
                  )}
                </div>
              ))}
              {canManage && (
                isNew ? (
                  <span className="flex h-20 items-center rounded-xl border border-dashed border-border px-3 text-xs text-ink-muted">Add photos after you save</span>
                ) : (
                  <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading} aria-label="Add photos"
                    className="flex h-20 w-20 items-center justify-center rounded-xl border-2 border-dashed border-border text-ink-muted hover:border-primary hover:text-primary">
                    {uploading ? <Loader2 size={18} className="animate-spin" /> : <Plus size={20} />}
                  </button>
                )
              )}
              <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={(e) => addPhotos(e.target.files)} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name">
                <input value={name} onChange={(e) => setName(e.target.value)} disabled={ro} className={inputCls} placeholder="e.g. Kanchi pattu" autoFocus={isNew} />
              </Field>
              <Field label="Group">
                {newGroup === null ? (
                  <Select value={groupId} disabled={ro} onChange={(v) => (v === "__new__" ? setNewGroup("") : setGroupId(v))}
                    options={[{ value: "", label: "No group" }, ...groups.map((g) => ({ value: g.id, label: g.name })), { value: "__new__", label: "+ New group" }]} />
                ) : (
                  <div className="flex gap-2">
                    <input value={newGroup} onChange={(e) => setNewGroup(e.target.value)} className={inputCls} placeholder="e.g. Sarees" autoFocus />
                    <button type="button" onClick={() => setNewGroup(null)} className="rounded-xl px-2 text-sm text-ink-muted hover:text-ink">Cancel</button>
                  </div>
                )}
              </Field>
              <Field label="Price">
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-ink-muted">₹</span>
                    <input value={price} onChange={(e) => setPrice(e.target.value)} disabled={ro} inputMode="decimal" className={cn(inputCls, "pl-7")} placeholder="4200" />
                  </div>
                  <input value={priceNote} onChange={(e) => setPriceNote(e.target.value)} disabled={ro} className={cn(inputCls, "w-32")} placeholder="note (optional)" />
                </div>
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="GST">
                  <Select value={gst} disabled={ro} onChange={setGst}
                    options={[{ value: "", label: "None" }, ...GST_RATE_OPTIONS.map((r) => ({ value: String(r), label: `${r}%` }))]} />
                </Field>
                <Field label="HSN">
                  <input value={hsn} onChange={(e) => setHsn(e.target.value)} disabled={ro} inputMode="numeric" className={cn(inputCls, "font-mono")} placeholder="5007" />
                </Field>
              </div>
              <Field label={<span className="inline-flex items-center gap-1">Cost price <Lock size={12} className="text-ink-muted" /></span>}
                hint="What you paid. Never shown to customers; used for stock value.">
                <div className="relative">
                  <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-ink-muted">₹</span>
                  <input value={cost} onChange={(e) => setCost(e.target.value)} disabled={ro} inputMode="decimal" className={cn(inputCls, "pl-7")} placeholder="2600" />
                </div>
              </Field>
              <Field label="Type">
                <Select value={itemType} disabled={ro} onChange={setItemType}
                  options={ITEM_TYPES.map((t) => ({ value: t, label: <span className="capitalize">{t}</span>, text: t }))} />
              </Field>
            </div>
            <Field label="Description" className="mt-3" hint="The AI uses this when it tells customers about the item. It also shows on your WhatsApp catalogue.">
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} disabled={ro} rows={2}
                className="w-full rounded-xl border border-border bg-white px-3 py-2 text-sm outline-none focus:border-primary" placeholder="Pure silk, zari border, 6.2 m with blouse" />
            </Field>
            <label className="mt-3 flex cursor-pointer items-start gap-2.5 rounded-xl bg-surface-low px-3 py-2.5">
              <input type="checkbox" checked={ready} disabled={ro} onChange={(e) => setReady(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[var(--primary)]" />
              <span className="text-sm">
                <span className="font-semibold text-ink">Ready to sell</span>
                <span className="block text-xs text-ink-muted">The AI can offer it and it shows on your WhatsApp catalogue. Untick to keep it as a draft.</span>
              </span>
            </label>
            {isProduct && (
              <label className="mt-2 flex cursor-pointer items-start gap-2.5 rounded-xl bg-surface-low px-3 py-2.5">
                <input type="checkbox" checked={batches} disabled={ro} onChange={(e) => setBatches(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[var(--primary)]" />
                <span className="text-sm">
                  <span className="font-semibold text-ink">Track batches &amp; expiry</span>
                  <span className="block text-xs text-ink-muted">
                    {batches && !detail?.tracks_batches && !isNew
                      ? "On Save, the stock you have now becomes one “Opening stock” batch. New stock gets its batch no. and expiry in Purchases → Stock in."
                      : !batches && detail?.tracks_batches
                        ? "On Save, batch numbers and expiry dates for this item are forgotten. The stock count stays."
                        : "For medicines, food, cosmetics: each batch has its own stock and expiry; bills sell the first-expiring one and never an expired one."}
                  </span>
                </span>
              </label>
            )}
          </Card>

          {isProduct && (
            <Card title={<span>🎨 Sizes and colours <span className="text-sm font-normal text-ink-muted">each one has its own stock</span></span>}
              aside={!showGrid && canManage ? (
                <button type="button" onClick={() => setShowGrid(true)} className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline">
                  <Plus size={14} /> Add sizes or colours
                </button>
              ) : null}>
              {!showGrid ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  {isNew ? (
                    <Field label="In stock now" hint="Leave empty if you don't count stock for this item.">
                      <input value={openingStock} onChange={(e) => setOpeningStock(e.target.value)} inputMode="numeric" className={inputCls} placeholder="e.g. 12" />
                    </Field>
                  ) : (
                    <div>
                      <p className="mb-1 text-sm font-semibold text-ink">In stock now</p>
                      <p className={cn("flex h-10 items-center rounded-xl border px-3 text-sm font-bold tabular-nums",
                        total === 0 ? "border-rose-200 bg-rose-50 text-rose-700" : "border-border bg-surface-low text-ink")}>
                        {total == null ? "Not counted" : `${total} pieces`}
                      </p>
                      <p className="mt-1 text-xs text-ink-muted">Change it with Correct stock, so the reason is saved.</p>
                    </div>
                  )}
                  <Field label="Low stock at" hint={`Shows as Low at this number or fewer (${DEFAULT_LOW_AT} when empty).`}>
                    <input value={lowAt} onChange={(e) => setLowAt(e.target.value)} disabled={ro} inputMode="numeric" className={inputCls} placeholder={String(DEFAULT_LOW_AT)} />
                  </Field>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <ChipInput label="Sizes" values={sizes} onChange={setSizes} placeholder="Add size" presets={SIZE_PRESETS} />
                    <ChipInput label="Colours" values={colours} onChange={setColours} placeholder="Add colour" />
                  </div>
                  {hasGrid && (
                    <div className="overflow-x-auto rounded-xl border border-border">
                      <table className="w-full min-w-[480px] text-sm">
                        <thead>
                          <tr className="bg-surface-low font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                            <th className="px-3 py-2 text-left">Stock</th>
                            {sizeCols.map((s) => <th key={s ?? "_"} className="px-2 py-2 text-center">{s ?? "Pieces"}</th>)}
                            <th className="px-3 py-2 text-right">Price</th>
                          </tr>
                        </thead>
                        <tbody>
                          {colourRows.map((c) => (
                            <tr key={c ?? "_"} className="border-t border-border-subtle">
                              <td className="px-3 py-2 font-semibold text-ink">{c ?? "All"}</td>
                              {sizeCols.map((s) => {
                                const key = cellKey(s, c);
                                const old = saved.get(key);
                                if (!old) {
                                  return (
                                    <td key={key} className="px-2 py-2 text-center">
                                      <input value={newStock[key] ?? ""} onChange={(e) => setNewStock({ ...newStock, [key]: e.target.value })}
                                        disabled={ro} inputMode="numeric" placeholder="0" aria-label={`Opening stock ${[c, s].filter(Boolean).join(" ")}`}
                                        className="h-9 w-14 rounded-lg border border-dashed border-primary/50 bg-white text-center text-sm tabular-nums outline-none focus:border-primary" />
                                    </td>
                                  );
                                }
                                const selected = target?.variantId === old.id;
                                return (
                                  <td key={key} className="px-2 py-2 text-center">
                                    <button type="button" disabled={ro}
                                      onClick={() => setTarget({ variantId: old.id, label: [c, s].filter(Boolean).join(" · "), current: old.stock })}
                                      aria-label={`Correct stock ${[c, s].filter(Boolean).join(" ")}`}
                                      className={cn("h-9 w-14 rounded-lg border text-sm font-bold tabular-nums transition-shadow",
                                        old.stock === 0 ? "border-rose-200 bg-rose-50 text-rose-700" : old.stock === 1 ? "border-amber-200 bg-amber-50 text-amber-800" : "border-border bg-white text-ink",
                                        selected && "ring-2 ring-primary ring-offset-1")}>
                                      {old.stock}
                                    </button>
                                  </td>
                                );
                              })}
                              <td className="px-3 py-2 text-right">
                                <div className="relative ml-auto w-28">
                                  <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-ink-muted">₹</span>
                                  <input value={rowPrice[c ?? ""] ?? ""} onChange={(e) => setRowPrice({ ...rowPrice, [c ?? ""]: e.target.value })}
                                    disabled={ro} inputMode="decimal" placeholder={price || "price"} aria-label={`Price ${c ?? ""}`}
                                    className="h-9 w-full rounded-lg border border-border bg-white pl-6 pr-2 text-right text-sm font-bold tabular-nums outline-none focus:border-primary" />
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <p className="text-xs text-ink-muted">
                    Red = out of stock. Yellow = last piece. Tap a number to correct it. New boxes (dashed) take the opening stock and are saved with Save.
                    An empty price uses the item price.
                  </p>
                  <Field label="Low stock at" className="max-w-xs" hint={`Shows as Low at this number or fewer, in all (${DEFAULT_LOW_AT} when empty).`}>
                    <input value={lowAt} onChange={(e) => setLowAt(e.target.value)} disabled={ro} inputMode="numeric" className={inputCls} placeholder={String(DEFAULT_LOW_AT)} />
                  </Field>
                </div>
              )}
            </Card>
          )}
        </div>

        <aside className="space-y-4">
          {detail && (
            <Card title="📦 This item">
              <dl className="space-y-1.5 text-sm">
                <Row label="In stock">{total == null ? "Not counted" : `${total} pieces`}{(detail.held_quantity ?? 0) > 0 && <span className="font-normal text-ink-muted"> · {detail.held_quantity} held for unpaid links</span>}</Row>
                <Row label="Stock value">{stockValue != null ? `${formatPaise(stockValue)} at cost ${formatPaise(detail.cost_price_paise ?? 0)}` : "Add a cost price"}</Row>
                <Row label="Sold this month">{detail.sold_this_month}</Row>
                <Row label="Asked but out">{detail.waiting ? `${detail.waiting} on the waiting list` : "Nobody waiting"}</Row>
              </dl>
              <button type="button" onClick={() => setHistoryOpen(true)} className="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:underline">
                <History size={14} /> Stock history
              </button>
            </Card>
          )}

          {detail && target && canManage && !(dirty && hadGrid && (sizes.join() !== detail.sizes.join() || colours.join() !== detail.colours.join())) && (
            <section className="rounded-card border-2 border-primary bg-white p-4 shadow-md sm:p-5">
              <h2 className="font-display text-base font-bold text-ink">✎ Correct stock{target.label ? ` · ${target.label}` : ""}</h2>
              <div className="mt-3 flex items-center gap-2">
                <button type="button" onClick={() => setTo((n) => Math.max(0, n - 1))} aria-label="One less"
                  className="flex h-10 w-12 items-center justify-center rounded-xl border border-border hover:bg-surface-low"><Minus size={16} /></button>
                <div className="flex h-10 min-w-[110px] items-center justify-center gap-1.5 rounded-xl border border-border px-3 font-bold tabular-nums">
                  <span className="text-ink-muted">{target.current}</span> →
                  <input value={to} onChange={(e) => setTo(Math.max(0, Math.round(Number(e.target.value) || 0)))} inputMode="numeric" aria-label="Right stock"
                    className="w-12 bg-transparent text-center outline-none" />
                </div>
                <button type="button" onClick={() => setTo((n) => n + 1)} aria-label="One more"
                  className="flex h-10 w-12 items-center justify-center rounded-xl border border-border hover:bg-surface-low"><Plus size={16} /></button>
              </div>
              <p className="mt-3 text-sm font-semibold text-ink">Why? <span className="font-normal text-ink-muted">(needed)</span></p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {WHY.map((w) => (
                  <button key={w.id} type="button" onClick={() => setWhy(w.id)} aria-pressed={why === w.id}
                    className={cn("rounded-full border px-3 py-1 text-sm font-semibold transition-colors",
                      why === w.id ? "border-primary bg-primary-50 text-primary-800" : "border-border text-ink hover:bg-surface-low")}>
                    {w.label}
                  </button>
                ))}
              </div>
              <button type="button" onClick={saveCorrection} disabled={!why || to === target.current || correcting}
                className="btn-primary mt-3 inline-flex h-9 w-full items-center justify-center gap-1.5 !py-0 disabled:opacity-50">
                {correcting && <Loader2 size={14} className="animate-spin" />} Save correction
              </button>
              <p className="mt-2 text-xs text-ink-muted">Saved in the stock history with your name and the reason.</p>
            </section>
          )}

          {detail && isProduct && <WhatsAppCard detail={detail} />}

          {detail && canManage && (
            <button type="button" onClick={deleteItem} className="inline-flex items-center gap-1.5 px-1 text-sm font-semibold text-ink-muted hover:text-danger">
              <Trash2 size={14} /> Delete item
            </button>
          )}
        </aside>
      </div>

      {historyOpen && detail && <StockHistoryDrawer itemId={detail.id} itemName={detail.name} onClose={() => setHistoryOpen(false)} />}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="text-right font-bold text-ink">{children}</dd>
    </div>
  );
}

function WhatsAppCard({ detail }: { detail: CatalogItemDetail }) {
  let tone = "border-border bg-white";
  let text: React.ReactNode;
  if (detail.status !== "ready") {
    text = "Drafts don't show on your WhatsApp catalogue.";
  } else if (detail.meta_sync_state === "error" || detail.meta_sync_state === "skipped") {
    tone = "border-rose-200 bg-rose-50/60";
    text = <><span className="font-semibold text-rose-700">Not on WhatsApp yet.</span> {detail.meta_sync_error}</>;
  } else if (detail.meta_sync_state === "synced" && !detail.meta_pending) {
    tone = "border-emerald-200 bg-emerald-50/60";
    text = <span className="font-semibold text-emerald-800">✓ On your WhatsApp catalogue, with live stock.</span>;
  } else if (detail.meta_sync_state === "sending" || (detail.meta_pending && detail.meta_sync_state)) {
    text = "Sending the latest change to Meta…";
  } else {
    text = "Shows here once the WhatsApp catalogue is turned on (Catalogue, top of the Items list).";
  }
  return (
    <section className={cn("rounded-card border p-4 text-sm sm:p-5", tone)}>
      <h2 className="mb-1.5 font-display text-base font-bold text-ink">🛍️ WhatsApp catalogue</h2>
      <p className="text-ink">{text}</p>
      {detail.status === "ready" && (
        <a href={detail.public_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 font-semibold text-primary hover:underline">
          Item page customers see <ExternalLink size={13} />
        </a>
      )}
    </section>
  );
}
