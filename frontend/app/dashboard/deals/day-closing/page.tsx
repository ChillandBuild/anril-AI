"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { toast } from "sonner";
import {
  ArrowLeft, Banknote, CreditCard, Download, Hourglass, Landmark, Loader2, MessageCircle, Package, Plus, Smartphone, Trash2, Undo2, Wallet,
} from "lucide-react";
import { API_URL, api, getAuthHeaders, type DayClosing } from "@/lib/api";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { cn } from "@/lib/utils";
import { rupees } from "../orders/orderUi";

const QUICK = ["Tea & food", "Transport", "Packing", "Salary advance", "Other"];
const METHOD_ICON: Record<string, typeof Banknote> = {
  cash: Banknote, upi: Smartphone, card: CreditCard, razorpay: MessageCircle, bank_transfer: Landmark, other: Wallet,
};
const METHOD_HINT: Record<string, string> = {
  cash: "Count your drawer ↓", upi: "check in your UPI app", card: "check the card machine", razorpay: "paid online",
  bank_transfer: "check your bank", other: "",
};

function istToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
}

function paise(text: string): number {
  const n = Number(text.replace(/[^\d.]/g, ""));
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}

function dayTitle(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

function Card({ icon: Icon, label, value, sub, tone }: { icon: typeof Banknote; label: string; value: string; sub: string; tone?: string }) {
  return (
    <div className="rounded-2xl border border-[#e8edf2] bg-white px-4 py-3 shadow-sm">
      <p className="flex items-center gap-1.5 font-label text-[13px] font-bold text-[#0A1528]"><Icon size={15} className="text-[#64748b]" /> {label}</p>
      <p className={cn("mt-1 font-display text-2xl font-extrabold leading-none tabular-nums text-[#0A1528]", tone)}>{value}</p>
      <p className="mt-1 truncate text-xs text-[#64748b]">{sub}</p>
    </div>
  );
}

export default function DayClosingPage() {
  const search = useSearchParams();
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("deals.manage");
  const [day, setDay] = useState(search.get("day") || istToday());
  const { data, error, mutate } = useSWR<DayClosing>(["day-closing", day], () => api.orders.dayClosing(day));
  const [opening, setOpening] = useState("");
  const [counted, setCounted] = useState("");
  const [label, setLabel] = useState("");
  const [amount, setAmount] = useState("");
  const [spentBy, setSpentBy] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    if (!data) return;
    setOpening(String((data.closed?.opening_paise ?? data.drawer.opening_paise) / 100));
    setCounted(data.closed ? String(data.closed.counted_paise / 100) : "");
  }, [data]);

  const d = data?.drawer;
  const openingPaise = paise(opening);
  const shouldBe = d ? openingPaise + d.cash_sales_paise - d.cash_refunds_paise - d.cash_expenses_paise : 0;
  const diff = counted.trim() ? paise(counted) - shouldBe : null;

  async function addExpense() {
    const amt = paise(amount);
    if (!label.trim()) return toast.error("What was it for?");
    if (amt < 100) return toast.error("Type the amount");
    setBusy("expense");
    try {
      await mutate(await api.orders.addCashExpense({ day, label: label.trim(), amount_paise: amt, spent_by: spentBy.trim() || undefined }), { revalidate: false });
      setLabel(""); setAmount(""); setSpentBy("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't add it");
    } finally {
      setBusy(null);
    }
  }

  async function removeExpense(id: string) {
    try {
      await mutate(await api.orders.deleteCashExpense(id, day), { revalidate: false });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't remove it");
    }
  }

  async function closeTheDay() {
    if (!counted.trim()) return toast.error("Count the drawer and type what you counted");
    setBusy("close");
    try {
      const out = await api.orders.closeDay({ day, opening_paise: openingPaise, counted_paise: paise(counted) });
      await mutate(out, { revalidate: false });
      if (out.difference_paise === 0) toast.success("Day closed. The drawer matches 👍");
      else toast.success(`Day closed · ${rupees(Math.abs(out.difference_paise))} ${out.difference_paise < 0 ? "short" : "over"}. Saved with your name.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't close the day");
    } finally {
      setBusy(null);
    }
  }

  async function download() {
    setDownloading(true);
    try {
      const res = await fetch(`${API_URL}${api.orders.dayClosingExportPath(day)}`, { headers: await getAuthHeaders() });
      if (!res.ok) throw new Error("Download failed");
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `day-closing-${day}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Couldn't download it");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="space-y-4 md:-mt-3">
      <div className="flex flex-wrap items-center gap-2">
        <Link href="/dashboard/deals" className="inline-flex items-center gap-1.5 rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 font-label text-xs font-bold text-[#334155] shadow-sm hover:border-slate-300">
          <ArrowLeft size={14} /> Orders
        </Link>
        <h1 className="font-display text-lg font-bold text-[#0A1528]">Day closing · {dayTitle(day)}</h1>
        <input type="date" value={day} max={istToday()} onChange={(e) => e.target.value && setDay(e.target.value)} aria-label="Day"
          className="h-9 rounded-xl border border-[#e2e8f0] bg-white px-3 text-xs font-bold text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary-200" />
        <button type="button" onClick={download} disabled={downloading || !data}
          className="ml-auto inline-flex items-center gap-1.5 rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 font-label text-xs font-bold text-[#334155] shadow-sm disabled:opacity-50">
          {downloading ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />} Download
        </button>
      </div>

      {error ? (
        <p className="rounded-2xl border border-[#e2e8f0] bg-white p-10 text-center text-sm text-on-surface-muted">Couldn&apos;t load the day. Refresh to try again.</p>
      ) : !data || !d ? (
        <div className="flex min-h-[280px] items-center justify-center"><Loader2 className="animate-spin text-primary" /></div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <Card icon={Wallet} label="Money in" value={rupees(data.money_in.paise)}
                sub={data.money_in.bills ? `${data.money_in.bills} ${data.money_in.bills === 1 ? "bill" : "bills"} · ${rupees(data.money_in.average_paise)} average` : "nothing yet"} />
              <Card icon={Undo2} label="Refunds" value={rupees(data.refunds.paise)} tone={data.refunds.paise ? "text-rose-600" : undefined}
                sub={data.refunds.items.length ? data.refunds.items.map((r) => `${r.name}, ${r.method.toLowerCase()}`).join(" · ") : "none"} />
              <Card icon={Hourglass} label="Cash spent" value={rupees(data.expenses.paise)} tone={data.expenses.paise ? "text-amber-700" : undefined}
                sub={`${data.expenses.items.length} ${data.expenses.items.length === 1 ? "entry" : "entries"}`} />
            </div>

            <section className="overflow-hidden rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
              <table className="w-full text-sm">
                <thead className="bg-[#f8fafc] font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">
                  <tr><th className="px-4 py-2.5 text-left">Paid by</th><th className="px-4 py-2.5 text-right">Bills</th><th className="px-4 py-2.5 text-right">Amount</th><th className="hidden px-4 py-2.5 sm:table-cell" /></tr>
                </thead>
                <tbody className="divide-y divide-[#f1f5f9]">
                  {data.methods.length === 0 ? (
                    <tr><td colSpan={4} className="px-4 py-8 text-center text-xs text-on-surface-muted">No money in on this day yet.</td></tr>
                  ) : data.methods.map((m) => {
                    const Icon = METHOD_ICON[m.method] ?? Wallet;
                    return (
                      <tr key={m.method}>
                        <td className="px-4 py-3 font-label font-bold text-[#0A1528]"><span className="inline-flex items-center gap-2"><Icon size={15} className="text-[#64748b]" /> {m.method === "razorpay" ? "WhatsApp link" : m.label}</span></td>
                        <td className="px-4 py-3 text-right tabular-nums">{m.orders}</td>
                        <td className="px-4 py-3 text-right font-bold tabular-nums">{rupees(m.paise)}</td>
                        <td className="hidden px-4 py-3 text-xs text-on-surface-muted sm:table-cell">{METHOD_HINT[m.method]}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>

            <section className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm sm:p-5">
              <h2 className="inline-flex items-center gap-2 font-label text-sm font-bold text-[#0A1528]"><Banknote size={16} /> Cash in drawer</h2>
              <dl className="mt-3 space-y-1.5 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-[#334155]">Opening cash <span className="text-xs text-on-surface-muted">{d.opening_from === "yesterday" ? "(yesterday's count)" : ""}</span></dt>
                  <dd>
                    <input value={opening} onChange={(e) => setOpening(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" aria-label="Opening cash"
                      disabled={!canManage}
                      className="h-8 w-28 rounded-lg border border-[#e2e8f0] px-2 text-right text-sm font-bold tabular-nums focus:outline-none focus:ring-2 focus:ring-primary-200" />
                  </dd>
                </div>
                <div className="flex justify-between text-[#334155]"><dt>+ Cash sales</dt><dd className="tabular-nums">{rupees(d.cash_sales_paise)}</dd></div>
                {d.cash_refunds_paise > 0 && <div className="flex justify-between text-[#334155]"><dt>− Cash refunds</dt><dd className="tabular-nums text-rose-600">{rupees(d.cash_refunds_paise)}</dd></div>}
                {d.cash_expenses_paise > 0 && (
                  <div className="flex justify-between gap-3 text-[#334155]">
                    <dt className="truncate">− Cash spent: {data.expenses.items.map((e) => `${e.label.toLowerCase()} ${rupees(e.amount_paise)}`).join(", ")}</dt>
                    <dd className="tabular-nums text-rose-600">{rupees(d.cash_expenses_paise)}</dd>
                  </div>
                )}
                <div className="flex justify-between border-t border-[#e2e8f0] pt-2 font-bold text-[#0A1528]"><dt>Should be</dt><dd className="tabular-nums">{rupees(shouldBe)}</dd></div>
              </dl>
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 font-label text-sm font-bold text-[#0A1528]">You counted
                  <span className="relative">
                    <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-on-surface-muted">₹</span>
                    <input value={counted} onChange={(e) => setCounted(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" aria-label="You counted"
                      disabled={!canManage} placeholder="0"
                      className="h-10 w-36 rounded-xl border border-[#e2e8f0] pl-7 pr-3 text-base font-bold tabular-nums focus:outline-none focus:ring-2 focus:ring-primary-200" />
                  </span>
                </label>
                {diff !== null && (
                  <span className={cn("rounded-full px-2.5 py-1 font-label text-xs font-bold",
                    diff === 0 ? "bg-emerald-50 text-emerald-700" : diff < 0 ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-800")}>
                    {diff === 0 ? "Matches" : `${rupees(Math.abs(diff))} ${diff < 0 ? "short" : "over"}`}
                  </span>
                )}
                {canManage && (
                  <button type="button" onClick={closeTheDay} disabled={!!busy}
                    className="ml-auto inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 font-label text-sm font-bold text-white shadow-sm hover:bg-primary/90 disabled:opacity-50">
                    {busy === "close" && <Loader2 size={14} className="animate-spin" />} {data.closed ? "Close again" : "Close the day"}
                  </button>
                )}
              </div>
              <p className="mt-2 text-xs text-on-surface-muted">
                {data.closed
                  ? `Closed ${new Date(data.closed.closed_at).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}: counted ${rupees(data.closed.counted_paise)}${data.closed.difference_paise ? `, ${rupees(Math.abs(data.closed.difference_paise))} ${data.closed.difference_paise < 0 ? "short" : "over"}` : ", matched"}. `
                  : ""}
                A difference is saved with your name in the activity log, and the owner gets a bell.
              </p>
            </section>
          </div>

          <div className="space-y-4">
            <section className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
              <h2 className="font-label text-sm font-bold text-[#0A1528]">Cash spent <span className="font-normal text-on-surface-muted">from the drawer</span></h2>
              <ul className="mt-2 divide-y divide-[#f1f5f9]">
                {data.expenses.items.length === 0 && <li className="py-2 text-xs text-on-surface-muted">Nothing yet.</li>}
                {data.expenses.items.map((e) => (
                  <li key={e.id} className="flex items-center gap-2 py-2 text-sm">
                    <span className="min-w-0 flex-1 truncate text-[#334155]">{e.label}{e.spent_by ? <span className="text-on-surface-muted"> · {e.spent_by}</span> : null}</span>
                    <span className="font-bold tabular-nums">{rupees(e.amount_paise)}</span>
                    {canManage && !data.closed && (
                      <button type="button" onClick={() => removeExpense(e.id)} aria-label={`Remove ${e.label}`} className="rounded p-1 text-[#94a3b8] hover:text-rose-600"><Trash2 size={13} /></button>
                    )}
                  </li>
                ))}
              </ul>
              {canManage && (
                <div className="mt-3 space-y-2 border-t border-dashed border-[#e2e8f0] pt-3">
                  <div className="flex flex-wrap gap-1.5">
                    {QUICK.map((q) => (
                      <button key={q} type="button" onClick={() => setLabel(q === "Other" ? "" : q)}
                        className={cn("rounded-full border px-2.5 py-1 font-label text-[11px] font-bold", label === q ? "border-primary bg-primary-50 text-primary-800" : "border-[#e2e8f0] text-[#334155]")}>
                        {q}
                      </button>
                    ))}
                  </div>
                  <div className="grid grid-cols-[1fr_90px] gap-2">
                    <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="What for" aria-label="What for" maxLength={80}
                      className="h-9 rounded-lg border border-[#e2e8f0] px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-200" />
                    <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" placeholder="₹" aria-label="Amount"
                      className="h-9 rounded-lg border border-[#e2e8f0] px-2.5 text-right text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-primary-200" />
                  </div>
                  <div className="flex gap-2">
                    <input value={spentBy} onChange={(e) => setSpentBy(e.target.value)} placeholder="Who (optional)" aria-label="Who spent it" maxLength={60}
                      className="h-9 min-w-0 flex-1 rounded-lg border border-[#e2e8f0] px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-200" />
                    <button type="button" onClick={addExpense} disabled={!!busy}
                      className="inline-flex items-center gap-1 rounded-lg bg-[#0A1528] px-3 font-label text-xs font-bold text-white disabled:opacity-50">
                      {busy === "expense" ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />} Add
                    </button>
                  </div>
                </div>
              )}
            </section>

            <section className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
              <h2 className="inline-flex items-center gap-1.5 font-label text-sm font-bold text-[#0A1528]"><Package size={15} /> Running low <span className="font-normal text-on-surface-muted">· stock goes down with every bill</span></h2>
              {data.running_low.length === 0 ? (
                <p className="mt-2 text-xs text-on-surface-muted">Nothing is down to its last 2 pieces.</p>
              ) : (
                <ul className="mt-2 space-y-1 text-sm">
                  {data.running_low.map((r) => (
                    <li key={r.name} className="flex justify-between gap-2">
                      <span className="truncate text-[#334155]">{r.name}</span>
                      <span className={cn("shrink-0 font-bold", r.left === 0 ? "text-rose-600" : "text-amber-700")}>{r.left === 0 ? "out" : `${r.left} left`}</span>
                    </li>
                  ))}
                </ul>
              )}
              <Link href="/dashboard/catalog" className="mt-2 inline-block font-label text-xs font-bold text-primary-700 hover:text-primary-900">Stock in ›</Link>
            </section>

            {data.expiring && (data.expiring.expired > 0 || data.expiring.soon > 0) && (
              <section className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
                <h2 className="font-label text-sm font-bold text-[#0A1528]">⏳ Expiring <span className="font-normal text-on-surface-muted">· batches</span></h2>
                <p className="mt-2 text-sm text-[#334155]">
                  {data.expiring.expired > 0 && <b className="text-rose-600">{data.expiring.expired} expired</b>}
                  {data.expiring.expired > 0 && data.expiring.soon > 0 && " · "}
                  {data.expiring.soon > 0 && <b className="text-amber-700">{data.expiring.soon} within 30 days</b>}
                </p>
                {data.expiring.names.length > 0 && <p className="mt-1 truncate text-xs text-on-surface-muted">{data.expiring.names.join(", ")}</p>}
                <Link href="/dashboard/catalog?tab=batches" className="mt-2 inline-block font-label text-xs font-bold text-primary-700 hover:text-primary-900">Batches &amp; expiry ›</Link>
              </section>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
