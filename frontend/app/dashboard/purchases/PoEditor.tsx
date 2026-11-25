"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Download, FileText, Loader2, MessageCircle, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { API_URL, api, getAuthHeaders } from "@/lib/api";
import type { PurchaseOrder, ReorderSuggestion } from "@/lib/api";
import { AiraLoader } from "@/components/AiraLoader";
import { Select } from "@/components/ui/Select";
import { MobileRecordCard } from "@/components/MobileRecord";
import { usePurchaseOptions } from "@/hooks/useApi";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { Field, GST_RATES, ItemPicker, PoStatusChip, inputCls, lastCost, openShare, rupees, shortDate, toPaise, variantLabel } from "./shared";

/* New purchase order (draft → Send on WhatsApp) and an existing one (status, Goods came, Remind). */

interface Line {
  key: string;
  catalog_item_id: string;
  variant_id: string | null;
  label: string;
  stock: number | null;
  sold_30d: number | null;
  suggested: number | null;
  qty: string;
  cost: string;
  gst_rate: number;
}

function lineKey(itemId: string, variantId: string | null) {
  return `${itemId}:${variantId ?? ""}`;
}

export function PoEditor({ po, suggestions }: { po?: PurchaseOrder; suggestions?: ReorderSuggestion[] }) {
  const router = useRouter();
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("purchases.manage");
  const { data: opts, error } = usePurchaseOptions();
  const editable = canManage && (!po || po.status === "draft");
  const [supplierId, setSupplierId] = useState(po?.supplier_id ?? "");
  const [needBy, setNeedBy] = useState(po?.need_by ?? "");
  const [placeId, setPlaceId] = useState(po?.place_id ?? "");
  const [lines, setLines] = useState<Line[]>([]);
  const [busy, setBusy] = useState<"save" | "send" | "cancel" | null>(null);

  useEffect(() => {
    if (!opts) return;
    if (!placeId) setPlaceId(opts.places.find((p) => p.bills_from)?.id ?? opts.places[0]?.id ?? "");
    if (po) {
      setLines(po.lines.map((li) => ({
        key: lineKey(li.catalog_item_id, li.variant_id), catalog_item_id: li.catalog_item_id, variant_id: li.variant_id,
        label: li.label, stock: null, sold_30d: null, suggested: null, qty: String(li.qty_ordered),
        cost: String(li.unit_cost_paise / 100), gst_rate: Number(li.gst_rate),
      })));
    } else if (suggestions?.length) {
      setLines(suggestions.map((s) => ({
        key: lineKey(s.catalog_item_id, s.variant_id), catalog_item_id: s.catalog_item_id, variant_id: s.variant_id,
        label: s.name + (s.variant_label ? ` · ${s.variant_label}` : ""), stock: s.stock, sold_30d: s.sold_30d,
        suggested: s.suggested, qty: String(s.suggested), cost: String((s.last_cost_paise ?? 0) / 100), gst_rate: s.gst_rate,
      })));
    }
    // Fill once when the options arrive.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opts]);

  const totals = useMemo(() => {
    let items = 0;
    let gst = 0;
    for (const li of lines) {
      const value = (Number(li.qty) || 0) * (toPaise(li.cost) || 0);
      items += value;
      gst += Math.round((value * li.gst_rate) / 100);
    }
    return { items, gst, total: items + gst };
  }, [lines]);

  if (error) return <p className="text-sm text-danger">Couldn&apos;t load your items. Reload the page.</p>;
  if (!opts) return <AiraLoader inline className="min-h-[50vh]" />;

  const supplier = opts.suppliers.find((s) => s.id === supplierId) ?? po?.supplier;
  const bad = lines.some((li) => !(Number(li.qty) > 0) || Number.isNaN(toPaise(li.cost)));
  const ready = Boolean(supplierId) && lines.length > 0 && !bad;

  function update(key: string, patch: Partial<Line>) {
    setLines((ls) => ls.map((li) => (li.key === key ? { ...li, ...patch } : li)));
  }

  async function save(): Promise<PurchaseOrder | null> {
    setBusy("save");
    try {
      const out = await api.purchases.saveOrder({
        supplier_id: supplierId, need_by: needBy || null, place_id: placeId || null,
        lines: lines.map((li) => ({ catalog_item_id: li.catalog_item_id, variant_id: li.variant_id, qty: Number(li.qty),
          unit_cost_paise: toPaise(li.cost), gst_rate: li.gst_rate })),
      }, po?.id);
      return out;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save. Try again.");
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function saveDraft() {
    const out = await save();
    if (out) {
      toast.success(`${out.po_number} saved as a draft.`);
      if (!po) router.replace(`/dashboard/purchases/orders/${out.id}`);
    }
  }

  async function send() {
    const saved = editable ? await save() : po;
    if (!saved) return;
    setBusy("send");
    try {
      const res = await api.purchases.sendOrder(saved.id);
      if (res.sent) toast.success(`${saved.po_number} sent to ${supplier?.name} on WhatsApp.`);
      else if (res.share_url) {
        openShare(res.share_url);
        toast.message("WhatsApp opened on your phone to send it. It's marked as sent.");
      } else toast.error("Add the supplier's WhatsApp number to send it.");
      router.push("/dashboard/purchases");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't send. Try again.");
    } finally {
      setBusy(null);
    }
  }

  async function cancel() {
    if (!po) return;
    setBusy("cancel");
    try {
      await api.purchases.cancelOrder(po.id);
      toast.success(`${po.po_number} cancelled.`);
      router.push("/dashboard/purchases");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't cancel. Try again.");
      setBusy(null);
    }
  }

  async function downloadPdf() {
    if (!po) return;
    try {
      const res = await fetch(`${API_URL}/api/v1/purchases/orders/${encodeURIComponent(po.id)}/pdf`, { headers: await getAuthHeaders() });
      if (!res.ok) throw new Error("Couldn't make the PDF. Try again.");
      const url = URL.createObjectURL(await res.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `${po.po_number}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't make the PDF.");
    }
  }

  async function remind() {
    if (!po) return;
    try {
      openShare((await api.purchases.remindOrder(po.id)).share_url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't open WhatsApp.");
    }
  }

  const preview = [
    `Purchase order ${po?.po_number ?? "PO-…"}`,
    ...lines.map((li) => `${li.label} × ${li.qty || 0}`),
    `Need by: ${needBy ? shortDate(needBy) : "as soon as you can"}`,
  ];
  const open = po && ["sent", "confirmed", "part_received"].includes(po.status);

  return (
    <div className="mx-auto w-full max-w-7xl space-y-4 pb-24">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href="/dashboard/purchases" className="inline-flex items-center gap-1.5 text-xs font-semibold text-ink-secondary hover:text-ink">
          <ArrowLeft size={14} /> Purchase orders
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          {po && <PoStatusChip status={po.status} />}
          {editable && (
            <button type="button" onClick={saveDraft} disabled={!ready || busy !== null}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border bg-white px-3 text-sm font-semibold text-ink hover:bg-surface-low disabled:opacity-50">
              {busy === "save" && <Loader2 size={14} className="animate-spin" />} Save draft
            </button>
          )}
          {editable && (
            <button type="button" onClick={send} disabled={!ready || busy !== null} className="btn-primary inline-flex h-9 items-center gap-1.5 !py-0 disabled:opacity-50">
              {busy === "send" ? <Loader2 size={14} className="animate-spin" /> : <MessageCircle size={15} />} Send on WhatsApp
            </button>
          )}
          {canManage && open && (
            <>
              <button type="button" onClick={remind} className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border bg-white px-3 text-sm font-semibold text-ink hover:bg-surface-low">
                <MessageCircle size={14} /> Remind
              </button>
              <Link href={`/dashboard/purchases/stock-in?po=${po!.id}`} className="btn-primary inline-flex h-9 items-center !py-0">📥 Goods came</Link>
            </>
          )}
          {canManage && po && ["draft", "sent", "confirmed"].includes(po.status) && (
            <button type="button" onClick={cancel} disabled={busy !== null} className="inline-flex h-9 items-center gap-1 px-2 text-sm font-semibold text-ink-muted hover:text-red-600">
              <X size={14} /> Cancel order
            </button>
          )}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Field label="Supplier">
              <Select size="md" value={supplierId} onChange={setSupplierId} disabled={!editable} aria-label="Supplier"
                placeholder={opts.suppliers.length ? "Pick a supplier" : "Add a supplier first"}
                options={opts.suppliers.map((s) => ({ value: s.id, label: s.name }))} />
            </Field>
            <Field label="Purchase order no."><input className={inputCls} disabled value={po?.po_number ?? "Given when saved"} /></Field>
            <Field label="Need by"><input type="date" className={inputCls} value={needBy} disabled={!editable} onChange={(e) => setNeedBy(e.target.value)} /></Field>
            <Field label="Deliver to">
              <Select size="md" value={placeId} onChange={setPlaceId} disabled={!editable} aria-label="Deliver to"
                options={opts.places.map((p) => ({ value: p.id, label: p.name }))} />
            </Field>
          </div>
          {!opts.suppliers.length && editable && (
            <p className="text-sm text-ink-muted">No suppliers yet. <Link href="/dashboard/purchases?tab=suppliers" className="font-semibold text-primary hover:underline">Add one</Link> first.</p>
          )}

          <div className="md:overflow-x-auto md:rounded-card md:border md:border-border md:bg-white md:shadow-sm">
            <div className="space-y-2 md:hidden">
              {lines.length === 0 && (
                <p className="rounded-2xl border border-surface-mid bg-white px-4 py-8 text-center text-sm text-ink-muted">Add the items you want to order.</p>
              )}
              {lines.map((li) => {
                const poLine = po?.lines.find((l) => lineKey(l.catalog_item_id, l.variant_id) === li.key);
                return (
                  <MobileRecordCard key={li.key} className="p-3">
                    <p className="text-sm font-bold text-ink">{li.label}</p>
                    {!po && (
                      <p className="mt-1 text-xs text-ink-muted">
                        In stock <span className={li.stock === 0 ? "font-bold text-rose-700" : "font-semibold text-ink"}>{li.stock ?? "—"}</span>
                        {" · "}Sold 30 days <span className="font-semibold text-ink">{li.sold_30d ?? "—"}</span>
                        {" · "}Suggested <span className="font-semibold text-primary">{li.suggested ?? "—"}</span>
                      </p>
                    )}
                    {po && po.status !== "draft" && <p className="mt-1 text-xs text-ink-muted">Came <span className="font-semibold text-ink">{poLine?.qty_received ?? 0}</span></p>}
                    <div className="mt-3 grid grid-cols-3 gap-2">
                      <label className="block min-w-0 space-y-1">
                        <span className="font-label text-[10px] font-bold uppercase tracking-wider text-ink-muted">Order</span>
                        <input value={li.qty} disabled={!editable} inputMode="numeric" aria-label={`Order ${li.label}`}
                          onChange={(e) => update(li.key, { qty: e.target.value.replace(/\D/g, "") })}
                          className="min-h-10 w-full rounded-lg border border-border px-2 text-base tabular-nums text-center font-bold disabled:bg-surface-low" />
                      </label>
                      <label className="block min-w-0 space-y-1">
                        <span className="font-label text-[10px] font-bold uppercase tracking-wider text-ink-muted">Cost each</span>
                        <input value={li.cost} disabled={!editable} inputMode="decimal" aria-label={`Cost of ${li.label}`}
                          onChange={(e) => update(li.key, { cost: e.target.value })}
                          className="min-h-10 w-full rounded-lg border border-border px-2 text-base tabular-nums disabled:bg-surface-low" />
                      </label>
                      <div className="block min-w-0 space-y-1">
                        <span className="font-label text-[10px] font-bold uppercase tracking-wider text-ink-muted">GST</span>
                        <Select size="md" value={String(li.gst_rate)} disabled={!editable} aria-label={`GST on ${li.label}`}
                          onChange={(v) => update(li.key, { gst_rate: Number(v) })} options={GST_RATES.map((r) => ({ value: String(r), label: `${r}%` }))} />
                      </div>
                    </div>
                    <div className="mt-3 flex items-center justify-between gap-2">
                      <p className="text-[13px] text-ink-muted">Total <b className="tabular-nums text-ink">{rupees((Number(li.qty) || 0) * (toPaise(li.cost) || 0))}</b></p>
                      {editable && (
                        <button type="button" onClick={() => setLines((ls) => ls.filter((x) => x.key !== li.key))} aria-label={`Remove ${li.label}`}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-ink-muted hover:bg-red-50 hover:text-red-600"><Trash2 size={15} /></button>
                      )}
                    </div>
                  </MobileRecordCard>
                );
              })}
            </div>
            <table className="hidden w-full min-w-[760px] text-sm md:table">
              <thead>
                <tr className="border-b border-border bg-surface-low text-left font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                  <th className="px-4 py-3">Item</th>
                  {!po && <th className="px-3 py-3">In stock</th>}
                  {!po && <th className="px-3 py-3">Sold 30 days</th>}
                  {!po && <th className="px-3 py-3">Suggested</th>}
                  <th className="px-3 py-3">Order</th>
                  {po && po.status !== "draft" && <th className="px-3 py-3">Came</th>}
                  <th className="px-3 py-3">Cost each</th>
                  <th className="px-3 py-3">GST</th>
                  <th className="px-3 py-3">Total</th>
                  {editable && <th className="px-2 py-3" />}
                </tr>
              </thead>
              <tbody>
                {lines.length === 0 && (
                  <tr><td colSpan={9} className="px-4 py-8 text-center text-ink-muted">Add the items you want to order.</td></tr>
                )}
                {lines.map((li) => {
                  const poLine = po?.lines.find((l) => lineKey(l.catalog_item_id, l.variant_id) === li.key);
                  return (
                    <tr key={li.key} className="border-b border-border-subtle last:border-b-0">
                      <td className="px-4 py-2.5 font-semibold text-ink">{li.label}</td>
                      {!po && <td className={`px-3 py-2.5 tabular-nums ${li.stock === 0 ? "font-bold text-rose-700" : "text-ink"}`}>{li.stock ?? "—"}</td>}
                      {!po && <td className="px-3 py-2.5 tabular-nums text-ink">{li.sold_30d ?? "—"}</td>}
                      {!po && <td className="px-3 py-2.5 font-semibold tabular-nums text-primary">{li.suggested ?? "—"}</td>}
                      <td className="px-3 py-2.5">
                        <input value={li.qty} disabled={!editable} inputMode="numeric" aria-label={`Order ${li.label}`}
                          onChange={(e) => update(li.key, { qty: e.target.value.replace(/\D/g, "") })}
                          className="h-9 w-20 rounded-lg border border-border px-2 text-center font-bold tabular-nums disabled:bg-surface-low" />
                      </td>
                      {po && po.status !== "draft" && <td className="px-3 py-2.5 tabular-nums text-ink">{poLine?.qty_received ?? 0}</td>}
                      <td className="px-3 py-2.5">
                        <input value={li.cost} disabled={!editable} inputMode="decimal" aria-label={`Cost of ${li.label}`}
                          onChange={(e) => update(li.key, { cost: e.target.value })}
                          className="h-9 w-24 rounded-lg border border-border px-2 tabular-nums disabled:bg-surface-low" />
                      </td>
                      <td className="px-3 py-2.5">
                        <Select size="sm" value={String(li.gst_rate)} disabled={!editable} aria-label={`GST on ${li.label}`} className="w-20"
                          onChange={(v) => update(li.key, { gst_rate: Number(v) })} options={GST_RATES.map((r) => ({ value: String(r), label: `${r}%` }))} />
                      </td>
                      <td className="px-3 py-2.5 font-bold tabular-nums text-ink">{rupees((Number(li.qty) || 0) * (toPaise(li.cost) || 0))}</td>
                      {editable && (
                        <td className="px-2 py-2.5">
                          <button type="button" onClick={() => setLines((ls) => ls.filter((x) => x.key !== li.key))} aria-label={`Remove ${li.label}`}
                            className="rounded-lg p-1 text-ink-muted hover:bg-red-50 hover:text-red-600"><Trash2 size={14} /></button>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="flex flex-wrap items-center justify-between gap-3 px-1 py-3 md:border-t md:border-border md:px-4">
              {editable ? (
                <ItemPicker items={opts.items} onPick={(item, variantId) => {
                  const key = lineKey(item.id, variantId);
                  if (lines.some((li) => li.key === key)) return;
                  const v = variantId ? item.variants.find((x) => x.id === variantId) : null;
                  setLines((ls) => [...ls, { key, catalog_item_id: item.id, variant_id: variantId, label: variantLabel(item, variantId),
                    stock: v ? v.stock : item.stock, sold_30d: null, suggested: null, qty: "1",
                    cost: String(lastCost(item, variantId) / 100), gst_rate: item.gst_rate }]);
                }} />
              ) : <span />}
              <p className="text-sm text-ink">
                Items {rupees(totals.items)} · GST {rupees(totals.gst)} · <b>Total {rupees(totals.total)}</b>
              </p>
            </div>
          </div>
          {!po && (
            <p className="rounded-card border border-primary/20 bg-primary-50/60 px-4 py-3 text-sm text-ink">
              💡 Suggested = enough for the next 30 days, from what sold in the last 30 days, minus what is in stock and already on
              order. You can change any number. Cost comes from the last stock in.
            </p>
          )}
        </div>

        <aside className="space-y-3">
          <div className="rounded-card border border-border bg-white p-4 shadow-sm">
            <p className="text-sm font-bold text-ink">What the supplier gets <span className="font-normal text-ink-muted">on WhatsApp, with the PDF</span></p>
            <div className="mt-3 rounded-xl bg-[#efeae2] p-3">
              <div className="rounded-lg bg-white px-3 py-2 text-[13px] leading-snug text-[#111b21] shadow-sm">
                {preview.map((line, i) => <p key={i} className={i === 0 ? "font-semibold" : ""}>{line}</p>)}
                <div className="mt-2 grid grid-cols-2 gap-2 border-t border-[#e9edef] pt-2 text-center text-[12px] font-semibold text-[#008069]">
                  <span>✓ Confirm</span><span>Change date</span>
                </div>
              </div>
              {po ? (
                <button type="button" onClick={downloadPdf} className="mt-2 flex w-full items-center gap-2 rounded-lg bg-white px-3 py-2 text-left text-[13px] text-[#111b21] shadow-sm hover:bg-[#f7f5f2]">
                  <FileText size={16} className="text-rose-600" /> {po.po_number}.pdf <Download size={13} className="ml-auto text-ink-muted" />
                </button>
              ) : <p className="mt-2 px-1 text-[11px] text-ink-muted">The PDF is made when you save or send.</p>}
            </div>
            <p className="mt-2 text-[11px] text-ink-muted">Inside 24 hours of their last message the PDF goes too; otherwise it&apos;s the approved message, and you can send the PDF from here.</p>
            {supplier && !supplier.phone && (
              <p className="mt-2 text-xs font-semibold text-amber-800">Add {supplier.name}&apos;s WhatsApp number in Suppliers to send it.</p>
            )}
          </div>
          <p className="rounded-card border border-primary/20 bg-primary-50/60 px-4 py-3 text-sm text-ink">
            The supplier taps Confirm → it shows &ldquo;Confirmed by supplier&rdquo;. No reply in 2 days → you get a reminder to call.
            {po?.date_change_asked_at && <b className="mt-1 block text-amber-800">They asked to change the date. Give them a call.</b>}
          </p>
        </aside>
      </div>
    </div>
  );
}
