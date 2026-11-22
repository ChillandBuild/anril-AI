"use client";

import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Download, Loader2, MessageCircle, Plus, Send, TrendingDown } from "lucide-react";
import { toast } from "sonner";
import { API_URL, api, getAuthHeaders } from "@/lib/api";
import type { SupplierPayMethod, SupplierRow } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AiraLoader } from "@/components/AiraLoader";
import { Select } from "@/components/ui/Select";
import { usePurchaseOrders, useStockIns, useSuppliers } from "@/hooks/useApi";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { StatCard } from "../catalog/ItemsTab";
import { Field, PoStatusChip, inputCls, openShare, rupees, shortDate, toPaise, todayIso } from "./shared";

/* Purchases & suppliers. The header shows the tabs (AppHeader HEADER_TABS): Purchase orders,
 * Stock in, Suppliers. */

export default function PurchasesPage() {
  const tab = useSearchParams().get("tab") || "orders";
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("purchases.manage");
  const canTemplates = role === "owner" || permissions.includes("templates.manage");
  return (
    <div className="mx-auto w-full max-w-7xl space-y-4 pb-24">
      {tab === "stock-in" ? <StockInTab canManage={canManage} />
        : tab === "suppliers" ? <SuppliersTab canManage={canManage} />
          : <OrdersTab canManage={canManage} canTemplates={canTemplates} />}
    </div>
  );
}

function Toolbar({ children, note }: { children?: React.ReactNode; note?: string }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-ink-muted">{note}</p>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

function ErrorBox({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="rounded-card border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
      Couldn&apos;t load this. <button type="button" onClick={onRetry} className="font-semibold underline">Try again</button>
    </div>
  );
}

/* ── Purchase orders ───────────────────────────────────────────────────────── */

function OrdersTab({ canManage, canTemplates }: { canManage: boolean; canTemplates: boolean }) {
  const { data, error, mutate } = usePurchaseOrders();
  const [submitting, setSubmitting] = useState(false);
  if (error) return <ErrorBox onRetry={() => mutate()} />;
  if (!data) return <AiraLoader inline className="min-h-[40vh]" />;

  async function remind(id: string) {
    try {
      openShare((await api.purchases.remindOrder(id)).share_url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't open WhatsApp.");
    }
  }

  async function submitTemplate() {
    setSubmitting(true);
    try {
      await api.purchases.submitTemplate();
      toast.success("Sent to WhatsApp for approval. It usually takes a few minutes to a day.");
      await mutate();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't send it to WhatsApp.");
    } finally {
      setSubmitting(false);
    }
  }

  const late = data.late.first;
  return (
    <>
      <Toolbar note="What you asked suppliers for, and what came.">
        {canManage && (
          <Link href="/dashboard/purchases/orders/new" className="btn-primary inline-flex h-9 items-center gap-1.5 !py-0">
            <Plus size={16} /> New purchase order
          </Link>
        )}
      </Toolbar>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <StatCard icon="📝" label="Open orders" value={String(data.open.count)} sub={`${rupees(data.open.paise)} ordered`} />
        <StatCard icon="🚚" label="Coming this week" value={String(data.coming_this_week.count)}
          sub={data.coming_this_week.suppliers.join(" · ") || "Nothing due this week"} />
        <StatCard icon="⚠️" label="Late" tone={data.late.count ? "red" : "plain"} value={String(data.late.count)}
          sub={late ? `${late[0]} · ${late[1]} ${late[1] === 1 ? "day" : "days"}` : "Nothing late"} />
        <StatCard icon="📉" label="To reorder" tone={data.to_reorder.count ? "amber" : "plain"}
          value={`${data.to_reorder.count} ${data.to_reorder.count === 1 ? "item" : "items"}`} sub="below your alert level" />
        <StatCard icon="📦" label="Short or damaged" value={`${data.short_or_damaged.pieces} pcs`}
          sub={`this month${data.short_or_damaged.claim_paise ? ` · claim ${rupees(data.short_or_damaged.claim_paise)}` : ""}`} />
      </div>

      {data.to_reorder.count > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-sm text-ink">
            <TrendingDown size={15} className="mr-1 inline text-amber-700" aria-hidden />
            <b className="text-amber-800">{data.to_reorder.count} {data.to_reorder.count === 1 ? "item is" : "items are"} low.</b>{" "}
            {data.to_reorder.names.join(" · ")}
          </p>
          {canManage && (
            <Link href="/dashboard/purchases/orders/new?suggest=1" className="btn-primary inline-flex h-9 items-center !py-0">Make purchase order</Link>
          )}
        </div>
      )}

      {data.template_status !== "APPROVED" && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-white px-4 py-3 text-sm shadow-sm">
          <p className="text-ink-muted">
            <MessageCircle size={14} className="mr-1 inline" aria-hidden />
            {data.template_status === "PENDING"
              ? "Your purchase order message is with WhatsApp for approval. Until then, orders open WhatsApp on your phone to send."
              : "To send purchase orders with Confirm / Change date buttons to any supplier, WhatsApp must approve the message once."}
          </p>
          {canTemplates && data.template_status !== "PENDING" && (
            <button type="button" onClick={submitTemplate} disabled={submitting}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border px-3 font-semibold text-ink hover:bg-surface-low disabled:opacity-60">
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} Send for approval
            </button>
          )}
        </div>
      )}

      <div className="overflow-x-auto rounded-card border border-border bg-white shadow-sm">
        <table className="w-full min-w-[900px] text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-low text-left font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              <th className="px-4 py-3">PO no. · Supplier</th>
              <th className="px-3 py-3">Items</th>
              <th className="px-3 py-3">Amount</th>
              <th className="px-3 py-3">Sent</th>
              <th className="px-3 py-3">Expected</th>
              <th className="px-3 py-3">Status</th>
              <th className="px-3 py-3" />
            </tr>
          </thead>
          <tbody>
            {data.orders.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-10 text-center text-ink-muted">No purchase orders yet.</td></tr>
            )}
            {data.orders.map((po) => {
              const open = ["sent", "confirmed", "part_received"].includes(po.status);
              return (
                <tr key={po.id} className="border-b border-border-subtle last:border-b-0">
                  <td className="px-4 py-3">
                    <Link href={`/dashboard/purchases/orders/${po.id}`} className="font-bold text-ink hover:underline">
                      {po.po_number} · {po.supplier_name}
                    </Link>
                    {po.date_change_asked_at && open && <p className="text-xs font-semibold text-amber-700">Asked to change the date</p>}
                  </td>
                  <td className="max-w-[260px] truncate px-3 py-3 text-ink" title={po.items_text}>{po.items_text}</td>
                  <td className="px-3 py-3 font-bold tabular-nums text-ink">{rupees(po.total_paise)}</td>
                  <td className="px-3 py-3 text-ink-muted">
                    {po.sent_at ? `${shortDate(po.sent_at)} · ${po.sent_via === "share" ? "from phone" : "WhatsApp"}` : "—"}
                  </td>
                  <td className="px-3 py-3 text-ink">{shortDate(po.need_by)}</td>
                  <td className="px-3 py-3"><PoStatusChip status={po.status} lateDays={po.late_days} ordered={po.ordered} received={po.received} /></td>
                  <td className="px-3 py-3 text-right">
                    {canManage && open && po.late_days > 0 && po.status !== "part_received" ? (
                      <button type="button" onClick={() => remind(po.id)}
                        className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border px-3 font-semibold text-ink hover:bg-surface-low">
                        <MessageCircle size={14} /> Remind
                      </button>
                    ) : canManage && open ? (
                      <Link href={`/dashboard/purchases/stock-in?po=${po.id}`} className="btn-primary inline-flex h-9 items-center !py-0">📥 Goods came</Link>
                    ) : (
                      <Link href={`/dashboard/purchases/orders/${po.id}`} className="font-semibold text-primary hover:underline">Open ›</Link>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="rounded-card border border-primary/20 bg-primary-50/60 px-4 py-3 text-sm text-ink">
        🔗 &ldquo;Goods came&rdquo; opens the order with what you asked for, so you only tick what arrived. Stock, cost price and
        what you owe the supplier update from there.
      </p>
    </>
  );
}

/* ── Stock in ──────────────────────────────────────────────────────────────── */

function StockInTab({ canManage }: { canManage: boolean }) {
  const { data, error, mutate } = useStockIns();
  const [month, setMonth] = useState(todayIso().slice(0, 7));
  const [downloading, setDownloading] = useState(false);
  if (error) return <ErrorBox onRetry={() => mutate()} />;

  async function download() {
    setDownloading(true);
    try {
      const res = await fetch(`${API_URL}${api.purchases.registerCsvPath(month)}`, { headers: await getAuthHeaders() });
      if (!res.ok) throw new Error("Couldn't download it. Try again.");
      const url = URL.createObjectURL(await res.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `purchase-register-${month}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't download it.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <>
      <Toolbar note="Everything that came in, newest first.">
        <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Month for the purchase register"
          className="h-9 rounded-xl border border-border bg-white px-3 text-sm" />
        <button type="button" onClick={download} disabled={downloading}
          className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border bg-white px-3 text-sm font-semibold text-ink hover:bg-surface-low disabled:opacity-60">
          {downloading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />} Purchase register (for your accountant)
        </button>
        {canManage && (
          <Link href="/dashboard/purchases/stock-in" className="btn-primary inline-flex h-9 items-center gap-1.5 !py-0">
            <Plus size={16} /> Stock in
          </Link>
        )}
      </Toolbar>
      {!data ? <AiraLoader inline className="min-h-[30vh]" /> : (
        <div className="overflow-x-auto rounded-card border border-border bg-white shadow-sm">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-border bg-surface-low text-left font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                <th className="px-4 py-3">Date</th>
                <th className="px-3 py-3">Supplier</th>
                <th className="px-3 py-3">Their bill no.</th>
                <th className="px-3 py-3">GST paid</th>
                <th className="px-3 py-3">Total</th>
                <th className="px-3 py-3">Paid</th>
              </tr>
            </thead>
            <tbody>
              {data.data.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-ink-muted">Nothing came in yet. Tap “Stock in” when goods arrive.</td></tr>
              )}
              {data.data.map((row) => (
                <tr key={row.id} className="border-b border-border-subtle last:border-b-0">
                  <td className="px-4 py-3 text-ink">{shortDate(row.bill_date)}</td>
                  <td className="px-3 py-3 font-semibold text-ink">{row.supplier_name || "—"}</td>
                  <td className="px-3 py-3 font-mono text-xs text-ink-muted">{row.bill_no || "—"}</td>
                  <td className="px-3 py-3 tabular-nums text-ink">{rupees(row.gst_paise)}</td>
                  <td className="px-3 py-3 font-bold tabular-nums text-ink">{rupees(row.total_paise)}</td>
                  <td className="px-3 py-3">
                    <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold",
                      row.pay_status === "paid" ? "bg-emerald-50 text-emerald-700" : row.pay_status === "part" ? "bg-amber-50 text-amber-800" : "bg-surface-mid text-ink-secondary")}>
                      {row.pay_status === "paid" ? "Paid" : row.pay_status === "part" ? "Part paid" : "Pay later"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

/* ── Suppliers ─────────────────────────────────────────────────────────────── */

function maskPhone(phone: string | null): string {
  if (!phone) return "";
  const d = phone.replace(/\D/g, "").slice(-10);
  return `${d.slice(0, 2)}•• ••${d.slice(-3)}`;
}

function SuppliersTab({ canManage }: { canManage: boolean }) {
  const { data, error, mutate } = useSuppliers();
  const [view, setView] = useState<"suppliers" | "corrections">("suppliers");
  const [adding, setAdding] = useState(false);
  const [paying, setPaying] = useState<string | null>(null);
  if (error) return <ErrorBox onRetry={() => mutate()} />;
  if (!data) return <AiraLoader inline className="min-h-[40vh]" />;

  async function reorder(row: SupplierRow) {
    try {
      const out = await api.purchases.reorder(row.id);
      if (!out.items) toast.message("Nothing is low right now.");
      else if (!out.share_url) toast.error("Add the supplier's phone number first.");
      else openShare(out.share_url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't make the list.");
    }
  }

  return (
    <>
      <Toolbar note="What you buy, and what you owe.">
        {canManage && (
          <>
            <button type="button" onClick={() => setAdding(true)}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border bg-white px-3 text-sm font-semibold text-ink hover:bg-surface-low">
              <Plus size={15} /> Add supplier
            </button>
            <Link href="/dashboard/purchases/stock-in" className="btn-primary inline-flex h-9 items-center gap-1.5 !py-0"><Plus size={16} /> Stock in</Link>
          </>
        )}
      </Toolbar>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard icon="🚚" label="Bought this month" value={rupees(data.bought_this_month_paise)}
          sub={`${data.bought_from} ${data.bought_from === 1 ? "supplier" : "suppliers"}`} />
        <StatCard icon="⏳" label="You owe" tone={data.owe_paise ? "red" : "plain"} value={rupees(data.owe_paise)}
          sub={`${data.owe_to} ${data.owe_to === 1 ? "supplier" : "suppliers"}`} />
        <StatCard icon="📦" label="Stock value" value={rupees(data.stock_value_paise ?? 0)} sub="at cost price" />
        <StatCard icon="📉" label="Low stock" tone={data.low_stock ? "amber" : "plain"}
          value={`${data.low_stock} ${data.low_stock === 1 ? "item" : "items"}`} sub="reorder suggested" />
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => setView("suppliers")} aria-pressed={view === "suppliers"}
          className={cn("h-9 rounded-full px-4 text-sm font-semibold", view === "suppliers" ? "bg-[#0A1528] text-white" : "border border-border bg-white text-ink hover:bg-surface-low")}>
          Suppliers · {data.suppliers.length}
        </button>
        <Link href="/dashboard/purchases?tab=stock-in" className="inline-flex h-9 items-center rounded-full border border-border bg-white px-4 text-sm font-semibold text-ink hover:bg-surface-low">
          Stock-in history
        </Link>
        <button type="button" onClick={() => setView("corrections")} aria-pressed={view === "corrections"}
          className={cn("h-9 rounded-full px-4 text-sm font-semibold", view === "corrections" ? "bg-[#0A1528] text-white" : "border border-border bg-white text-ink hover:bg-surface-low")}>
          Stock corrections
        </button>
      </div>
      {view === "corrections" ? <StockCorrections /> : <>
      {adding && <SupplierForm onClose={() => setAdding(false)} onSaved={() => { setAdding(false); mutate(); }} />}
      <div className="overflow-x-auto rounded-card border border-border bg-white shadow-sm">
        <table className="w-full min-w-[900px] text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-low text-left font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              <th className="px-4 py-3">Supplier</th>
              <th className="px-3 py-3">Supplies</th>
              <th className="px-3 py-3">Bought this month</th>
              <th className="px-3 py-3">You owe</th>
              <th className="px-3 py-3">Due</th>
              <th className="px-3 py-3" />
            </tr>
          </thead>
          <tbody>
            {data.suppliers.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-10 text-center text-ink-muted">No suppliers yet. Add one, or they are added when you stock in.</td></tr>
            )}
            {data.suppliers.map((row) => (
              <tr key={row.id} className="border-b border-border-subtle align-top last:border-b-0">
                <td className="px-4 py-3">
                  <p className="font-bold text-ink">{row.name}</p>
                  <p className="text-xs text-ink-muted">{[row.city, maskPhone(row.phone)].filter(Boolean).join(" · ")}</p>
                </td>
                <td className="px-3 py-3 text-ink">{row.supplies || "—"}</td>
                <td className="px-3 py-3 font-bold tabular-nums text-ink">{rupees(row.bought_this_month_paise)}</td>
                <td className="px-3 py-3">
                  {row.owe_paise ? <span className="font-bold tabular-nums text-rose-700">{rupees(row.owe_paise)}</span>
                    : <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">Nothing</span>}
                </td>
                <td className="px-3 py-3">
                  {row.overdue_days ? <span className="rounded-full bg-rose-50 px-2 py-0.5 text-xs font-semibold text-rose-700">Overdue {row.overdue_days} {row.overdue_days === 1 ? "day" : "days"}</span>
                    : <span className="text-ink">{row.owe_paise ? shortDate(row.due_date) : "—"}</span>}
                </td>
                <td className="px-3 py-3">
                  {canManage && (
                    <div className="flex flex-col items-end gap-1.5">
                      {paying === row.id ? (
                        <PaymentForm supplier={row} onDone={(saved) => { setPaying(null); if (saved) mutate(); }} />
                      ) : (
                        <button type="button" onClick={() => setPaying(row.id)}
                          className="inline-flex h-8 items-center rounded-lg border border-border px-3 text-sm font-semibold text-ink hover:bg-surface-low">Record payment</button>
                      )}
                      <button type="button" onClick={() => reorder(row)}
                        className="inline-flex h-8 items-center gap-1 rounded-lg border border-border px-3 text-sm font-semibold text-ink hover:bg-surface-low">
                        <MessageCircle size={13} /> Reorder
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="rounded-card border border-primary/20 bg-primary-50/60 px-4 py-3 text-sm text-ink">
        Reorder opens WhatsApp on your phone with the list of low-stock items for that supplier.
      </p>
      </>}
    </>
  );
}

const CORRECTION_LABEL: Record<string, string> = {
  adjustment: "Corrected", count: "Stock count", write_off: "Removed", supplier_return: "Returned to supplier",
};

/* Every stock change that isn't a sale, a purchase or a move: corrections, counts, write-offs, returns. */
function StockCorrections() {
  const { data, error, mutate } = useSWR("stock/corrections", () => api.catalog.stockCorrections());
  if (error) return <ErrorBox onRetry={() => mutate()} />;
  if (!data) return <AiraLoader inline className="min-h-[30vh]" />;
  return (
    <div className="overflow-x-auto rounded-card border border-border bg-white shadow-sm">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-border bg-surface-low text-left font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
            <th className="px-4 py-3">Item</th>
            <th className="px-3 py-3">Change</th>
            <th className="px-3 py-3">Kind</th>
            <th className="px-3 py-3">Why</th>
            <th className="px-3 py-3">By</th>
            <th className="px-3 py-3">When</th>
          </tr>
        </thead>
        <tbody>
          {data.data.length === 0 && (
            <tr><td colSpan={6} className="px-4 py-10 text-center text-ink-muted">No corrections yet. Counts, write-offs and corrected stock show here.</td></tr>
          )}
          {data.data.map((r, i) => (
            <tr key={`${r.at}-${i}`} className="border-b border-border-subtle last:border-b-0">
              <td className="px-4 py-3 font-semibold text-ink">{r.name}{r.variant_label ? ` · ${r.variant_label}` : ""}</td>
              <td className={cn("px-3 py-3 font-bold tabular-nums", r.delta < 0 ? "text-rose-700" : "text-emerald-700")}>{r.delta > 0 ? `+${r.delta}` : r.delta}</td>
              <td className="px-3 py-3 text-ink">{CORRECTION_LABEL[r.reason] ?? r.reason}</td>
              <td className="px-3 py-3 text-ink-muted">{r.note ?? "—"}</td>
              <td className="px-3 py-3 text-ink">{r.by ?? "—"}</td>
              <td className="px-3 py-3 text-ink-muted">{new Date(r.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SupplierForm({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({ name: "", phone: "", city: "", gstin: "", supplies: "" });
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true);
    try {
      await api.purchases.saveSupplier(form);
      toast.success("Supplier added.");
      onSaved();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  }
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <section className="rounded-card border border-primary/30 bg-white p-4 shadow-sm">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Field label="Name"><input className={inputCls} value={form.name} onChange={set("name")} placeholder="Sri Murugan Tex" /></Field>
        <Field label="WhatsApp number"><input className={inputCls} value={form.phone} onChange={set("phone")} inputMode="tel" placeholder="98765 43210" /></Field>
        <Field label="City"><input className={inputCls} value={form.city} onChange={set("city")} placeholder="Erode" /></Field>
        <Field label="GSTIN (optional)"><input className={inputCls} value={form.gstin} onChange={set("gstin")} placeholder="33ABCDE1234F1Z5" /></Field>
        <Field label="Supplies"><input className={inputCls} value={form.supplies} onChange={set("supplies")} placeholder="Silk, Kanchi pattu" /></Field>
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="h-9 rounded-xl px-3 text-sm font-semibold text-ink-muted hover:text-ink">Cancel</button>
        <button type="button" onClick={save} disabled={busy || !form.name.trim()} className="btn-primary inline-flex h-9 items-center gap-1.5 !py-0 disabled:opacity-50">
          {busy && <Loader2 size={14} className="animate-spin" />} Save supplier
        </button>
      </div>
    </section>
  );
}

function PaymentForm({ supplier, onDone }: { supplier: SupplierRow; onDone: (saved: boolean) => void }) {
  const [amount, setAmount] = useState(supplier.owe_paise ? String(supplier.owe_paise / 100) : "");
  const [method, setMethod] = useState<SupplierPayMethod>("upi");
  const [busy, setBusy] = useState(false);
  const paise = toPaise(amount);
  async function save() {
    setBusy(true);
    try {
      await api.purchases.recordPayment(supplier.id, { amount_paise: paise, method });
      toast.success(`${rupees(paise)} to ${supplier.name} recorded.`);
      onDone(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save. Try again.");
      setBusy(false);
    }
  }
  return (
    <div className="flex flex-wrap items-center justify-end gap-1.5">
      <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" aria-label="Amount paid in rupees"
        className="h-8 w-24 rounded-lg border border-border px-2 text-sm tabular-nums" placeholder="₹" />
      <Select size="sm" value={method} onChange={(v) => setMethod(v as SupplierPayMethod)} className="w-24" aria-label="Paid by"
        options={[{ value: "upi", label: "UPI" }, { value: "cash", label: "Cash" }, { value: "bank", label: "Bank" }, { value: "cheque", label: "Cheque" }]} />
      <button type="button" onClick={save} disabled={busy || !(paise > 0)}
        className="h-8 rounded-lg bg-primary px-3 text-xs font-semibold text-white hover:bg-primary-dark disabled:opacity-50">Save</button>
      <button type="button" onClick={() => onDone(false)} className="text-xs font-semibold text-ink-muted">Cancel</button>
    </div>
  );
}
