"use client";

import { useRef, useState } from "react";
import useSWR from "swr";
import { Camera, Download, Loader2, Paperclip, Plus, Repeat, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { API_URL, api, getAuthHeaders } from "@/lib/api";
import type { ExpenseCategory, ExpenseMethod, ExpenseRepeat, ExpensesMonth } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Select } from "@/components/ui/Select";
import { MobileRecordCard, MobileRecordHeader } from "@/components/MobileRecord";
import { Pagination, usePagedList } from "@/components/ui/Pagination";
import { useAuthRole } from "../contexts/AuthRoleContext";

/* Expenses (backend services/expenses.py, migration 313): what the business spends, so profit is real.
 * Rent and salary repeat by themselves; purchases, Meta ads, the Anril plan and stock loss are added by themselves. */

const CATEGORIES: { value: ExpenseCategory; label: string; icon: string }[] = [
  { value: "rent", label: "Rent", icon: "🏠" },
  { value: "salary", label: "Salary", icon: "👥" },
  { value: "electricity", label: "Electricity", icon: "⚡" },
  { value: "transport", label: "Transport", icon: "🚚" },
  { value: "food", label: "Tea & food", icon: "☕" },
  { value: "packing", label: "Packing & courier", icon: "📦" },
  { value: "other", label: "Other", icon: "🧾" },
];
const ICON: Record<string, string> = Object.fromEntries(CATEGORIES.map((c) => [c.value, c.icon]));
const AUTO_ICON: Record<string, string> = { purchases: "🚚", supplier_payments: "🏭", meta_ads: "📊", plan: "🤖", stock_loss: "📉" };
const METHODS: { value: ExpenseMethod; label: string }[] = [
  { value: "cash", label: "Cash" }, { value: "upi", label: "UPI" }, { value: "bank", label: "Bank" }, { value: "card", label: "Card" },
];

function rupees(paise: number) {
  return `${paise < 0 ? "−" : ""}₹${Math.round(Math.abs(paise) / 100).toLocaleString("en-IN")}`;
}
function toPaise(text: string) {
  const n = Number(text.replace(/[^\d.]/g, ""));
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}
function shortDay(iso: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}
function thisMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function ExpensesPage() {
  const { role, permissions } = useAuthRole();
  const canView = role === "owner" || permissions.includes("purchases.view") || permissions.includes("purchases.manage");
  const canAdd = role === "owner" || permissions.includes("purchases.manage") || permissions.includes("deals.manage");
  const canManage = role === "owner" || permissions.includes("purchases.manage");
  const [month, setMonth] = useState(thisMonth());
  const { data, error, mutate } = useSWR(canView ? ["expenses", month] : null, () => api.expenses.month(month));
  const [repeat, setRepeat] = useState<Partial<ExpenseRepeat> | null>(null);
  const [downloading, setDownloading] = useState(false);

  async function download() {
    setDownloading(true);
    try {
      const res = await fetch(`${API_URL}${api.expenses.excelPath(month)}`, { headers: await getAuthHeaders() });
      if (!res.ok) throw new Error("Couldn't make the file. Try again.");
      const url = URL.createObjectURL(await res.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `anril-${month}-for-accountant.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't make the file.");
    } finally {
      setDownloading(false);
    }
  }

  if (!canView) return <p className="py-20 text-center text-sm text-ink-muted">You don&apos;t have access to expenses.</p>;

  return (
    <div className="mx-auto w-full max-w-7xl space-y-4 pb-24">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <input type="month" value={month} max={thisMonth()} onChange={(e) => e.target.value && setMonth(e.target.value)} aria-label="Month"
          className="h-9 rounded-xl border border-border bg-white px-3 text-sm" />
        {canManage && (
          <button type="button" onClick={() => setRepeat({ category: "rent", method: "bank", day_of_month: 1, active: true })}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-border bg-white px-3 text-sm font-semibold text-ink hover:bg-surface-low">
            <Repeat size={14} /> Every month
          </button>
        )}
      </div>
      {error && <p className="rounded-card border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">Couldn&apos;t load expenses. Refresh to try again.</p>}
      {!data ? (
        <div className="flex items-center justify-center gap-2 rounded-card border border-border bg-white py-16 text-sm text-ink-muted"><Loader2 size={16} className="animate-spin" /> Loading…</div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="space-y-3">
            {canAdd && data.is_current && <QuickAdd onAdded={() => mutate()} />}
            <ExpenseTable data={data} canAdd={canAdd} onChanged={() => mutate()} onEditRepeat={canManage ? (r) => setRepeat(r) : undefined} />
            <p className="text-sm text-ink-muted">
              Purchases come from Stock in, Meta ad money from your ad account, the Anril plan from Plan &amp; bills, and stock loss from
              stock counts. You only type the rest. Rent and salary set under <b>Every month</b> are added by themselves on their day.
            </p>
          </div>
          <div className="space-y-3">
            <Profit data={data} />
            <p className="rounded-card border border-primary/20 bg-primary-50/60 px-4 py-3 text-sm leading-relaxed text-ink">
              Purchases are not counted twice: stock you bought becomes &ldquo;cost of items sold&rdquo; when it sells (at its cost price).
            </p>
            <button type="button" onClick={download} disabled={downloading}
              className="flex h-11 w-full items-center justify-center gap-2 rounded-card border border-border bg-white text-sm font-bold text-ink shadow-sm hover:bg-surface-low disabled:opacity-60">
              {downloading ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />} Send month to accountant (Excel)
            </button>
          </div>
        </div>
      )}
      {repeat && <RepeatDialog value={repeat} onClose={() => setRepeat(null)} onSaved={() => { setRepeat(null); mutate(); }} />}
    </div>
  );
}

function QuickAdd({ onAdded }: { onAdded: () => void }) {
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState<ExpenseCategory>("transport");
  const [method, setMethod] = useState<ExpenseMethod>("cash");
  const [label, setLabel] = useState("");
  const [bill, setBill] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  async function save() {
    setBusy(true);
    try {
      const row = await api.expenses.add({ amount_paise: toPaise(amount), category, method, label: label.trim() || undefined });
      if (bill) {
        try {
          await api.expenses.attachBill(row.id, bill);
        } catch (err) {
          toast.error(`Saved, but the bill photo didn't upload: ${err instanceof Error ? err.message : "try again"}`);
        }
      }
      toast.success(`${rupees(row.amount_paise)} ${row.category_label ?? ""} saved.`);
      setAmount(""); setLabel(""); setBill(null);
      if (file.current) file.current.value = "";
      onAdded();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-card border border-border bg-white p-3 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="px-1 font-display text-sm font-bold text-ink">Quick add</span>
        <label className="relative">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-ink-muted">₹</span>
          <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" placeholder="1,200" aria-label="Amount"
            onKeyDown={(e) => { if (e.key === "Enter" && toPaise(amount) > 0) save(); }}
            className="h-10 w-28 rounded-xl border border-border pl-7 pr-2 text-sm tabular-nums outline-none focus:border-primary" />
        </label>
        {CATEGORIES.map((c) => (
          <button key={c.value} type="button" onClick={() => setCategory(c.value)} aria-pressed={category === c.value}
            className={cn("h-9 rounded-xl border px-3 text-sm font-semibold", category === c.value ? "border-primary bg-primary-50 text-primary-800" : "border-border text-ink hover:bg-surface-low")}>
            {c.label}
          </button>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={80} placeholder="What for (optional), e.g. Auto to godown"
          className="h-10 min-w-[200px] flex-1 rounded-xl border border-border px-3 text-sm outline-none focus:border-primary" />
        <Select value={method} onChange={(v) => setMethod(v as ExpenseMethod)} options={METHODS} className="w-28" aria-label="Paid by" />
        <input ref={file} type="file" hidden accept="image/jpeg,image/png,application/pdf" onChange={(e) => setBill(e.target.files?.[0] ?? null)} />
        <button type="button" onClick={() => file.current?.click()}
          className={cn("inline-flex h-10 items-center gap-1.5 rounded-xl border px-3 text-sm font-semibold", bill ? "border-primary bg-primary-50 text-primary-800" : "border-border text-ink hover:bg-surface-low")}>
          <Camera size={15} /> {bill ? "Bill added" : "Bill"}
        </button>
        <button type="button" onClick={save} disabled={busy || toPaise(amount) <= 0}
          className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-primary px-5 text-sm font-bold text-white hover:bg-primary-dark disabled:opacity-50">
          {busy && <Loader2 size={14} className="animate-spin" />} Save
        </button>
      </div>
    </section>
  );
}

function ExpenseTable({ data, canAdd, onChanged, onEditRepeat }: {
  data: ExpensesMonth; canAdd: boolean; onChanged: () => void; onEditRepeat?: (r: ExpenseRepeat) => void;
}) {
  const [confirm, setConfirm] = useState<string | null>(null);
  const repeats = new Map(data.repeats.map((r) => [r.id, r]));
  const expenseRows = usePagedList(data.expenses, data.month_label);

  async function remove(id: string) {
    try {
      await api.expenses.remove(id);
      toast.success("Deleted.");
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't delete.");
    } finally {
      setConfirm(null);
    }
  }

  async function openBill(id: string) {
    try {
      window.open((await api.expenses.billUrl(id)).url, "_blank", "noopener");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't open the bill.");
    }
  }

  const empty = data.expenses.length === 0 && data.auto.length === 0;
  return (
    <div className="rounded-card border border-border bg-white shadow-sm md:overflow-x-auto">
      <div className="hidden md:block">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-border bg-surface-low text-left font-mono text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
            <th className="w-10 px-4 py-3" />
            <th className="px-2 py-3">Type</th>
            <th className="px-3 py-3">Amount</th>
            <th className="px-3 py-3">Date</th>
            <th className="px-3 py-3">Paid by</th>
            <th className="px-2 py-3" />
          </tr>
        </thead>
        <tbody>
          {empty && <tr><td colSpan={6} className="px-4 py-10 text-center text-ink-muted">Nothing spent in {data.month_label} yet.</td></tr>}
          {expenseRows.pageItems.map((e) => {
            const rep = e.repeat_id ? repeats.get(e.repeat_id) : undefined;
            return (
              <tr key={e.id} className="border-b border-border-subtle last:border-b-0">
                <td className="px-4 py-3 text-lg" aria-hidden>{ICON[e.category] ?? "🧾"}</td>
                <td className="px-2 py-3">
                  <span className="font-bold text-ink">{e.label}</span>
                  {e.label !== e.category_label && <span className="ml-1.5 text-xs text-ink-muted">{e.category_label}</span>}
                  {e.repeat_id && (
                    <button type="button" disabled={!rep || !onEditRepeat} onClick={() => rep && onEditRepeat?.(rep)}
                      className="ml-2 rounded-full bg-surface-low px-2 py-0.5 text-xs text-ink-muted enabled:hover:text-ink">every month</button>
                  )}
                </td>
                <td className="px-3 py-3 font-bold tabular-nums text-ink">{rupees(e.amount_paise)}</td>
                <td className="px-3 py-3 text-ink">{shortDay(e.day)}</td>
                <td className="px-3 py-3 text-ink">
                  {e.method_label}
                  {e.has_bill && <button type="button" onClick={() => openBill(e.id)} className="ml-2 text-primary hover:underline" aria-label="Open the bill"><Paperclip size={13} className="inline" /></button>}
                </td>
                <td className="px-2 py-3 text-right">
                  {canAdd && (confirm === e.id ? (
                    <span className="inline-flex items-center gap-2 text-xs">
                      <button type="button" onClick={() => remove(e.id)} className="font-semibold text-danger">Delete</button>
                      <button type="button" onClick={() => setConfirm(null)} className="text-ink-muted">Keep</button>
                    </span>
                  ) : (
                    <button type="button" onClick={() => setConfirm(e.id)} aria-label="Delete" className="text-ink-muted hover:text-danger"><Trash2 size={14} /></button>
                  ))}
                </td>
              </tr>
            );
          })}
          {data.auto.map((a) => (
            <tr key={a.key} className="border-b border-border-subtle last:border-b-0 bg-surface-low/40">
              <td className="px-4 py-3 text-lg" aria-hidden>{AUTO_ICON[a.key] ?? "🧾"}</td>
              <td className="px-2 py-3"><span className="font-bold text-ink">{a.label}</span> <span className="text-xs text-ink-muted">{a.note}</span></td>
              <td className="px-3 py-3 font-bold tabular-nums text-ink">{rupees(a.amount_paise)}</td>
              <td className="px-3 py-3 text-ink">this month</td>
              <td className="px-3 py-3"><span className="rounded-full bg-sky-50 px-2.5 py-0.5 text-xs font-semibold text-sky-700">added by itself</span></td>
              <td />
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      <div className="space-y-3 p-3 md:hidden">
        {empty && <p className="px-1 py-6 text-center text-sm text-ink-muted">Nothing spent in {data.month_label} yet.</p>}
        {expenseRows.pageItems.map((e) => {
          const rep = e.repeat_id ? repeats.get(e.repeat_id) : undefined;
          return (
            <MobileRecordCard key={e.id} className="p-3">
              <MobileRecordHeader
                title={<><span aria-hidden>{ICON[e.category] ?? "🧾"}</span> {e.label}</>}
                subtitle={<>{e.label !== e.category_label ? `${e.category_label} · ` : ""}{shortDay(e.day)} · {e.method_label}</>}
                aside={<span className="text-sm font-bold tabular-nums text-ink">{rupees(e.amount_paise)}</span>}
              />
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {e.repeat_id && (
                  <button type="button" disabled={!rep || !onEditRepeat} onClick={() => rep && onEditRepeat?.(rep)}
                    className="rounded-full bg-surface-low px-2 py-0.5 text-xs text-ink-muted enabled:hover:text-ink">every month</button>
                )}
                {e.has_bill && (
                  <button type="button" onClick={() => openBill(e.id)} aria-label="Open the bill"
                    className="inline-flex min-h-8 items-center gap-1 rounded-lg px-2 text-xs font-semibold text-primary"><Paperclip size={13} /> Bill</button>
                )}
                {canAdd && (
                  <span className="ml-auto">
                    {confirm === e.id ? (
                      <span className="inline-flex items-center gap-3 text-[13px]">
                        <button type="button" onClick={() => remove(e.id)} className="min-h-8 font-semibold text-danger">Delete</button>
                        <button type="button" onClick={() => setConfirm(null)} className="min-h-8 text-ink-muted">Keep</button>
                      </span>
                    ) : (
                      <button type="button" onClick={() => setConfirm(e.id)} aria-label="Delete"
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-ink-muted hover:text-danger"><Trash2 size={16} /></button>
                    )}
                  </span>
                )}
              </div>
            </MobileRecordCard>
          );
        })}
        {data.auto.map((a) => (
          <MobileRecordCard key={a.key} className="bg-surface-low/40 p-3">
            <MobileRecordHeader
              title={<><span aria-hidden>{AUTO_ICON[a.key] ?? "🧾"}</span> {a.label}</>}
              subtitle={`${a.note} · this month`}
              aside={<span className="text-sm font-bold tabular-nums text-ink">{rupees(a.amount_paise)}</span>}
            />
            <span className="mt-2 inline-block rounded-full bg-sky-50 px-2.5 py-0.5 text-xs font-semibold text-sky-700">added by itself</span>
          </MobileRecordCard>
        ))}
      </div>
      <Pagination page={expenseRows.page} total={expenseRows.total} onPageChange={expenseRows.setPage} noun="expenses" />
    </div>
  );
}

function Profit({ data }: { data: ExpensesMonth }) {
  const p = data.profit;
  const row = (label: string, paise: number, tone?: string) => (
    <div className="flex justify-between text-sm"><span className={cn("text-ink", tone)}>{label}</span><span className={cn("font-semibold tabular-nums text-ink", tone)}>{rupees(paise)}</span></div>
  );
  return (
    <section className="rounded-card border border-border bg-white p-4 shadow-sm">
      <h3 className="font-display text-base font-bold text-ink">📈 Real profit · {data.month_label.split(" ")[0]} <span className="text-sm font-normal text-ink-muted">{data.is_current ? "so far" : ""}</span></h3>
      <div className="mt-3 space-y-1.5">
        {row("Sales (before GST)", p.sales_paise)}
        {row("− Refunds", p.refunds_paise, "text-rose-700")}
        {row("− Cost of items sold", p.cogs_paise)}
        {row("− Expenses (no purchases)", p.expenses_paise)}
      </div>
      <div className="mt-3 flex items-baseline justify-between border-t border-border pt-3">
        <span className="font-display text-lg font-bold text-ink">Profit</span>
        <span className={cn("font-display text-xl font-bold tabular-nums", p.profit_paise >= 0 ? "text-emerald-700" : "text-rose-700")}>{rupees(p.profit_paise)}</span>
      </div>
      {p.cogs_paise === 0 && p.sales_paise > 0 && (
        <p className="mt-2 text-xs text-amber-700">Cost of items sold is ₹0: add cost prices to your items (or stock in through Purchases) for a real profit.</p>
      )}
    </section>
  );
}

function RepeatDialog({ value, onClose, onSaved }: { value: Partial<ExpenseRepeat>; onClose: () => void; onSaved: () => void }) {
  const [category, setCategory] = useState<ExpenseCategory>(value.category ?? "rent");
  const [label, setLabel] = useState(value.label ?? "");
  const [amount, setAmount] = useState(value.amount_paise ? String(value.amount_paise / 100) : "");
  const [day, setDay] = useState(String(value.day_of_month ?? 1));
  const [method, setMethod] = useState<ExpenseMethod>(value.method ?? "bank");
  const [busy, setBusy] = useState(false);

  async function save(active = true) {
    setBusy(true);
    try {
      await api.expenses.saveRepeat({ category, label: label.trim(), amount_paise: toPaise(amount), day_of_month: Number(day), method, active }, value.id);
      toast.success(active ? `Added every month on day ${day}.` : "Stopped. Past months stay.");
      onSaved();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-dialog flex items-end justify-center bg-black/40 sm:items-center sm:p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Every month" onClick={(e) => e.stopPropagation()} className="w-full max-w-md rounded-t-2xl bg-white shadow-xl sm:rounded-2xl">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h3 className="font-display text-lg font-bold text-ink">{value.id ? "Change" : "Add"} every-month expense</h3>
          <button type="button" onClick={onClose} aria-label="Close" className="text-ink-muted hover:text-ink"><X size={18} /></button>
        </div>
        <div className="space-y-3 px-5 py-4">
          <div className="flex flex-wrap gap-2">
            {CATEGORIES.filter((c) => c.value !== "food").map((c) => (
              <button key={c.value} type="button" onClick={() => setCategory(c.value)} aria-pressed={category === c.value}
                className={cn("h-9 rounded-xl border px-3 text-sm font-semibold", category === c.value ? "border-primary bg-primary-50 text-primary-800" : "border-border text-ink hover:bg-surface-low")}>
                {c.label}
              </button>
            ))}
          </div>
          <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={80} placeholder="Name (optional), e.g. Shop rent"
            className="h-10 w-full rounded-xl border border-border px-3 text-sm outline-none focus:border-primary" />
          <div className="grid grid-cols-3 gap-2">
            <label className="text-xs font-semibold text-ink-muted">Amount
              <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" placeholder="₹25,000"
                className="mt-1 h-10 w-full rounded-xl border border-border px-3 text-sm font-normal text-ink outline-none focus:border-primary" />
            </label>
            <label className="text-xs font-semibold text-ink-muted">Day of month
              <input value={day} onChange={(e) => setDay(e.target.value.replace(/\D/g, "").slice(0, 2))} inputMode="numeric"
                className="mt-1 h-10 w-full rounded-xl border border-border px-3 text-sm font-normal text-ink outline-none focus:border-primary" />
            </label>
            <label className="text-xs font-semibold text-ink-muted">Paid by
              <Select value={method} onChange={(v) => setMethod(v as ExpenseMethod)} options={METHODS} className="mt-1 w-full" aria-label="Paid by" />
            </label>
          </div>
          <p className="text-xs text-ink-muted">Added by itself on that day every month (the last day in shorter months). You can delete or change a month&apos;s entry.</p>
        </div>
        <div className="flex items-center justify-between gap-2 border-t border-border px-5 py-3">
          {value.id ? <button type="button" onClick={() => save(false)} disabled={busy} className="text-sm font-semibold text-danger">Stop repeating</button> : <span />}
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="h-10 rounded-xl border border-border px-4 text-sm font-semibold text-ink">Cancel</button>
            <button type="button" onClick={() => save(true)} disabled={busy || toPaise(amount) <= 0 || !(Number(day) >= 1 && Number(day) <= 31)}
              className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-primary px-4 text-sm font-bold text-white disabled:opacity-50">
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />} Save
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
