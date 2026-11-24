"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { toast } from "sonner";
import { ArrowLeft, Check, FileDown, Loader2, Plus, Send, Trash2 } from "lucide-react";
import { api, type AdvanceRule, type NewBillItem } from "@/lib/api";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { Select } from "@/components/ui/Select";
import { cn } from "@/lib/utils";
import { computeBill } from "../orders/billMath";
import { reportSend, rupees } from "../orders/orderUi";

type Line = { key: string; item: NewBillItem | null; name: string; qty: string; price: string };
type AdvanceKind = "rule" | "none" | "percent" | "fixed";

function istToday(plusDays = 0): string {
  const d = new Date(Date.now() + plusDays * 86400000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(d);
}

function dayText(iso: string): string {
  if (!iso) return "";
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

function paise(text: string): number {
  const n = Number(text.replace(/[^\d.]/g, ""));
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}

/** The advance a rule asks for (same as backend order_quotes.advance_for). */
function advanceFor(total: number, rule: { kind: string; value: number; min_total_paise?: number }): number {
  if (rule.kind === "none" || total <= 0) return 0;
  if (rule.min_total_paise && total < rule.min_total_paise) return 0;
  const amount = rule.kind === "percent" ? Math.round((total * rule.value) / 100) : Math.round(rule.value * 100);
  return Math.max(0, Math.min(amount, total));
}

function ruleText(rule: AdvanceRule | undefined): string {
  if (!rule || rule.kind === "none") return "no advance";
  const base = rule.kind === "percent" ? `${rule.value}%` : rupees(Math.round(rule.value * 100));
  return rule.min_total_paise ? `${base} above ${rupees(rule.min_total_paise)}` : base;
}

let nextKey = 0;

export default function NewQuotePage() {
  const router = useRouter();
  const { role, permissions, tenantName } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("deals.manage");
  const { data: options } = useSWR("new-bill-options", () => api.orders.billOptions(), { revalidateOnFocus: false });
  const { data: rule, mutate: mutateRule } = useSWR("orders-advance-rule", () => api.orders.advanceRule(), { revalidateOnFocus: false });
  const { data: advanceOpts } = useSWR("orders-advance-options", () => api.orders.advanceOptions(), { revalidateOnFocus: false });
  const advanceLocked = role !== "owner" && advanceOpts?.staff_can_change === false; // v9.2 screen 155

  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [validUntil, setValidUntil] = useState(istToday(7));
  const [lines, setLines] = useState<Line[]>([]);
  const [pick, setPick] = useState("");
  const [discountKind, setDiscountKind] = useState<"rupees" | "percent">("percent");
  const [discountText, setDiscountText] = useState("");
  const [advanceKind, setAdvanceKind] = useState<AdvanceKind>("rule");
  const [advanceText, setAdvanceText] = useState("");
  const [readyIn, setReadyIn] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState<"draft" | "send" | "pdf" | null>(null);

  useEffect(() => {
    const digits = phone.replace(/\D/g, "");
    if (digits.length < 10) return;
    const t = setTimeout(() => {
      api.orders.findCustomer(phone).then((r) => { if (r.found && r.name && !name) setName(r.name); }).catch(() => {});
    }, 350);
    return () => clearTimeout(t);
    // name is read only so a typed name isn't overwritten
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phone]);

  const includeGst = options?.prices_include_gst ?? true;
  const rows = lines.map((l) => ({
    unit_price_paise: paise(l.price), qty: Math.max(1, Math.round(Number(l.qty) || 1)), gst_rate: l.item?.gst_rate ?? null,
  }));
  const subtotal = rows.reduce((a, r) => a + r.unit_price_paise * r.qty, 0);
  const discount = discountKind === "percent" ? Math.round((subtotal * (Number(discountText) || 0)) / 100) : paise(discountText);
  const totals = computeBill(rows, { discount_paise: discount, include_gst: includeGst, bill_type: "gst" });
  // "The rule" = each item's own advance, else the shop's (same as backend order_quotes.order_advance)
  const ruleAdvance = (() => {
    const total = totals.total_paise;
    const shop = rule ?? { kind: "none", value: 0 };
    if (!lines.some((l) => l.item?.advance_rule)) return advanceFor(total, shop);
    const share = (i: number) => Math.round((total * rows[i].unit_price_paise * rows[i].qty) / (subtotal || 1));
    let adv = advanceFor(lines.reduce((n, l, i) => n + (l.item?.advance_rule ? 0 : share(i)), 0), shop);
    lines.forEach((l, i) => {
      const r = l.item?.advance_rule;
      if (!r || r.kind === "none") return;
      const part = share(i);
      const ask = r.kind === "percent" ? Math.round((part * r.value) / 100) : Math.round(r.value * 100) * rows[i].qty;
      adv += Math.max(0, Math.min(ask, part));
    });
    return Math.max(0, Math.min(adv, total));
  })();
  const advance = advanceKind === "rule"
    ? ruleAdvance
    : advanceKind === "none" ? 0
    : advanceFor(totals.total_paise, { kind: advanceKind, value: Number(advanceText) || 0 });
  const gstRates = new Set(lines.map((l) => l.item?.gst_rate || 0).filter(Boolean));
  const hasPhone = phone.replace(/\D/g, "").length >= 10;
  const first = name.trim().split(" ")[0] || "there";
  const shop = tenantName || "your shop";

  const catalogue = useMemo(() => (options?.items ?? []).map((i) => ({ value: i.id, label: `${i.name}${i.price_paise != null ? ` · ${rupees(i.price_paise)}` : ""}` })), [options]);

  function addItem(id: string) {
    const item = options?.items.find((i) => i.id === id);
    if (!item) return;
    setLines((cur) => [...cur, { key: `l${nextKey++}`, item, name: item.name, qty: "1", price: item.price_paise != null ? String(item.price_paise / 100) : "" }]);
    setPick("");
  }

  function update(key: string, patch: Partial<Line>) {
    setLines((cur) => cur.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  }

  async function saveAsShopRule() {
    if (advanceKind !== "percent" && advanceKind !== "fixed") return;
    try {
      await api.orders.saveAdvanceRule({ kind: advanceKind, value: Number(advanceText) || 0, min_total_paise: 0 });
      await mutateRule();
      setAdvanceKind("rule");
      toast.success("Saved as the shop's advance rule");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't save the rule");
    }
  }

  async function save(mode: "draft" | "send" | "pdf") {
    if (!hasPhone) return toast.error("Add the customer's phone number");
    if (!lines.length) return toast.error("Add at least one item");
    if (lines.some((l) => !l.name.trim() || !l.price)) return toast.error("Every item needs a name and a price");
    setSaving(mode);
    try {
      const out = await api.orders.createQuote({
        phone, name: name.trim() || undefined,
        items: lines.map((l) => ({
          ...(l.item ? { catalog_item_id: l.item.id } : { name: l.name.trim() }),
          qty: Math.max(1, Math.round(Number(l.qty) || 1)), unit_price_paise: paise(l.price),
        })),
        discount_paise: totals.discount_paise,
        valid_until: validUntil,
        advance: advanceKind === "rule" || advanceKind === "none" ? { kind: advanceKind } : { kind: advanceKind, value: Number(advanceText) || 0 },
        ready_in_days: readyIn ? Number(readyIn) : null,
        notes: notes.trim() || undefined,
        send: mode === "send",
      });
      if (mode === "send") reportSend(out.order.id, "quote", out.message);
      else toast.success("Quote saved as a draft");
      if (mode === "pdf" && out.order.bill_url) window.open(out.order.bill_url, "_blank", "noopener");
      router.push(`/dashboard/deals/orders/${out.order.id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't save the quote");
    } finally {
      setSaving(null);
    }
  }

  if (!canManage) return <p className="py-20 text-center text-sm text-on-surface-muted">You need Orders manage access to send quotes.</p>;

  const advanceOptions = [
    { value: "rule", label: rule ? `Shop rule · ${ruleText(rule)}` : "Shop rule" },
    { value: "none", label: "No advance" },
    { value: "percent", label: "A percent" },
    { value: "fixed", label: "A fixed amount" },
  ];

  return (
    <div className="space-y-4 md:-mt-3">
      <Link href="/dashboard/deals" className="inline-flex items-center gap-1.5 rounded-xl border border-[#e2e8f0] bg-white px-3 py-2 font-label text-xs font-bold text-[#334155] shadow-sm hover:border-slate-300">
        <ArrowLeft size={14} /> Orders
      </Link>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-w-0 space-y-4">
          <section className="grid gap-3 rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm sm:grid-cols-[1fr_1fr_200px]">
            <label className="block">
              <span className="font-label text-xs font-bold text-[#0A1528]">Customer phone</span>
              <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" placeholder="98402 77889"
                className="mt-1 h-10 w-full rounded-xl border border-[#e2e8f0] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary-200" />
            </label>
            <label className="block">
              <span className="font-label text-xs font-bold text-[#0A1528]">Name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Suresh K · SK Textiles"
                className="mt-1 h-10 w-full rounded-xl border border-[#e2e8f0] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary-200" />
            </label>
            <label className="block">
              <span className="font-label text-xs font-bold text-[#0A1528]">Quote valid till</span>
              <input type="date" value={validUntil} min={istToday()} onChange={(e) => setValidUntil(e.target.value)}
                className="mt-1 h-10 w-full rounded-xl border border-[#e2e8f0] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary-200" />
            </label>
          </section>

          <section className="rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead className="bg-[#f8fafc] font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted">
                  <tr>
                    <th className="px-3 py-2 text-left">Item</th>
                    <th className="w-20 px-3 py-2 text-right">Qty</th>
                    <th className="w-32 px-3 py-2 text-right">Price each</th>
                    <th className="w-28 px-3 py-2 text-right">Total</th>
                    <th className="w-8" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#f1f5f9]">
                  {lines.map((l) => (
                    <tr key={l.key}>
                      <td className="px-3 py-2">
                        {l.item ? <span className="font-label text-[13px] font-bold text-[#0A1528]">{l.name}</span> : (
                          <input value={l.name} onChange={(e) => update(l.key, { name: e.target.value })} placeholder="Item name" aria-label="Item name"
                            className="h-9 w-full rounded-lg border border-[#e2e8f0] px-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-200" />
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <input value={l.qty} onChange={(e) => update(l.key, { qty: e.target.value.replace(/\D/g, "") })} inputMode="numeric" aria-label="Quantity"
                          className="h-9 w-full rounded-lg border border-[#e2e8f0] px-2 text-right text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-primary-200" />
                      </td>
                      <td className="px-3 py-2">
                        <input value={l.price} onChange={(e) => update(l.key, { price: e.target.value.replace(/[^\d.]/g, "") })} inputMode="decimal" aria-label="Price each" placeholder="₹"
                          className="h-9 w-full rounded-lg border border-[#e2e8f0] px-2 text-right text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-primary-200" />
                      </td>
                      <td className="px-3 py-2 text-right font-bold tabular-nums">{rupees(paise(l.price) * Math.max(1, Number(l.qty) || 1))}</td>
                      <td className="px-1 py-2">
                        <button type="button" onClick={() => setLines((cur) => cur.filter((x) => x.key !== l.key))} aria-label="Remove item"
                          className="rounded-lg p-1.5 text-[#94a3b8] hover:bg-rose-50 hover:text-rose-600"><Trash2 size={14} /></button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Select value={pick} onChange={addItem} options={catalogue} placeholder="＋ Add item from catalogue" className="w-full sm:w-72 text-xs" />
              <button type="button" onClick={() => setLines((cur) => [...cur, { key: `l${nextKey++}`, item: null, name: "", qty: "1", price: "" }])}
                className="inline-flex items-center gap-1 font-label text-xs font-bold text-primary-700 hover:text-primary-900">
                <Plus size={13} /> Item not in the catalogue
              </button>
            </div>
            <dl className="mt-4 space-y-1.5 border-t border-[#eef2f6] pt-3 text-sm">
              <div className="flex items-center justify-between gap-3 text-on-surface-muted">
                <dt className="flex items-center gap-2">
                  Discount
                  <span className="flex rounded-lg border border-[#e2e8f0] p-0.5">
                    {(["percent", "rupees"] as const).map((k) => (
                      <button key={k} type="button" onClick={() => setDiscountKind(k)}
                        className={cn("rounded-md px-2 py-0.5 font-label text-[11px] font-bold", discountKind === k ? "bg-primary text-white" : "text-[#64748b]")}>
                        {k === "percent" ? "%" : "₹"}
                      </button>
                    ))}
                  </span>
                  <input value={discountText} onChange={(e) => setDiscountText(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal" placeholder="0" aria-label="Discount"
                    className="h-7 w-20 rounded-lg border border-[#e2e8f0] px-2 text-right text-xs tabular-nums focus:outline-none focus:ring-2 focus:ring-primary-200" />
                </dt>
                <dd className="tabular-nums">{totals.discount_paise ? `− ${rupees(totals.discount_paise)}` : "₹0"}</dd>
              </div>
              {totals.gst_paise > 0 && (
                <div className="flex justify-between text-on-surface-muted">
                  <dt>GST{gstRates.size === 1 ? ` ${Array.from(gstRates)[0]}%` : ""} {includeGst ? "(included)" : ""}</dt>
                  <dd className="tabular-nums">{rupees(totals.gst_paise)}</dd>
                </div>
              )}
              <div className="flex items-baseline justify-between pt-1">
                <dt className="font-display text-lg font-bold text-[#0A1528]">Total</dt>
                <dd className="font-display text-2xl font-extrabold tabular-nums text-[#0A1528]">{rupees(totals.total_paise)}</dd>
              </div>
            </dl>
          </section>

          <section className="grid gap-3 rounded-2xl border border-[#e2e8f0] bg-white p-4 shadow-sm sm:grid-cols-2">
            <div>
              <span className="font-label text-xs font-bold text-[#0A1528]">Advance to confirm</span>
              <div className="mt-1 flex gap-2">
                <Select value={advanceKind} onChange={(v) => setAdvanceKind(v as AdvanceKind)} options={advanceOptions} className="flex-1 text-sm"
                  disabled={advanceLocked} aria-label="Advance to confirm" />
                {(advanceKind === "percent" || advanceKind === "fixed") && (
                  <input value={advanceText} onChange={(e) => setAdvanceText(e.target.value.replace(/[^\d.]/g, ""))} inputMode="decimal"
                    placeholder={advanceKind === "percent" ? "30 %" : "₹ 1,000"} aria-label="Advance"
                    className="h-10 w-28 rounded-xl border border-[#e2e8f0] px-3 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-primary-200" />
                )}
              </div>
              <p className="mt-1 text-[11px] text-on-surface-muted">
                {advance ? `${rupees(advance)} on Accept` : "No advance: Accept just confirms the order"}
                {advanceLocked ? " · the owner set this for every order" : ""}
                {role === "owner" && (advanceKind === "percent" || advanceKind === "fixed") && Number(advanceText) > 0 && (
                  <> · <button type="button" onClick={saveAsShopRule} className="font-bold text-primary-700 hover:text-primary-900">Make this the shop rule</button></>
                )}
              </p>
            </div>
            <label className="block">
              <span className="font-label text-xs font-bold text-[#0A1528]">Ready by</span>
              <div className="mt-1 flex items-center gap-2">
                <input value={readyIn} onChange={(e) => setReadyIn(e.target.value.replace(/\D/g, "").slice(0, 3))} inputMode="numeric" placeholder="10" aria-label="Ready in days"
                  className="h-10 w-20 rounded-xl border border-[#e2e8f0] px-3 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-primary-200" />
                <span className="text-sm text-on-surface-muted">days after they accept</span>
              </div>
            </label>
            <label className="block sm:col-span-2">
              <span className="font-label text-xs font-bold text-[#0A1528]">Note for you (not sent)</span>
              <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional"
                className="mt-1 h-10 w-full rounded-xl border border-[#e2e8f0] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary-200" />
            </label>
          </section>

          <p className="rounded-2xl border border-primary-100 bg-primary-50/50 px-4 py-3 text-xs leading-5 text-[#0A1528]">
            When {name.trim() ? `${first} taps` : "they tap"} <b>Accept</b>: the order is made by itself{advance ? `, the ${rupees(advance)} advance link goes to them` : ""}, and you get an alert.
            No reply in 2 days → one polite reminder. Not accepted by {dayText(validUntil)} → marked <b>Quote expired</b>.
          </p>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex gap-2">
              <button type="button" onClick={() => save("pdf")} disabled={!!saving}
                className="inline-flex items-center gap-1.5 rounded-xl border border-[#e2e8f0] bg-white px-4 py-2.5 font-label text-sm font-bold text-[#334155] shadow-sm disabled:opacity-50">
                {saving === "pdf" ? <Loader2 size={14} className="animate-spin" /> : <FileDown size={14} />} Quote PDF
              </button>
              <button type="button" onClick={() => save("draft")} disabled={!!saving}
                className="rounded-xl border border-[#e2e8f0] bg-white px-4 py-2.5 font-label text-sm font-bold text-[#334155] shadow-sm disabled:opacity-50">
                {saving === "draft" ? <Loader2 size={14} className="inline animate-spin" /> : "Save draft"}
              </button>
            </div>
            <button type="button" onClick={() => save("send")} disabled={!!saving}
              className="inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 font-label text-sm font-bold text-white shadow-sm hover:bg-primary/90 disabled:opacity-50">
              {saving === "send" ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} Send quote on WhatsApp
            </button>
          </div>
        </div>

        <aside className="h-fit overflow-hidden rounded-2xl border border-[#e2e8f0] bg-[#efe7dd] shadow-sm lg:sticky lg:top-4">
          <div className="bg-[#0b5f55] px-4 py-2.5 font-label text-sm font-bold text-white">Preview · as {name.trim() ? first : "they"} will see it</div>
          <div className="space-y-3 p-4">
            <div className="rounded-xl bg-white p-3 text-[13px] leading-5 text-[#111827] shadow-sm">
              <p className="font-bold">Quote from {shop}</p>
              <p>Vanakkam {first} 🙏</p>
              {lines.length === 0 ? <p className="text-[#94a3b8]">Items appear here…</p> : lines.map((l) => (
                <p key={l.key}>• {l.name || "Item"} × {Math.max(1, Number(l.qty) || 1)} · {rupees(paise(l.price) * Math.max(1, Number(l.qty) || 1))}</p>
              ))}
              {totals.discount_paise > 0 && <p>Discount: − {rupees(totals.discount_paise)}</p>}
              <p className="font-bold">Total {rupees(totals.total_paise)}{totals.gst_paise > 0 && includeGst ? " (GST incl.)" : ""}</p>
              {(advance > 0 || readyIn) && (
                <p>{[advance ? `Advance ${rupees(advance)} to confirm` : "", readyIn ? `ready in ${readyIn} days` : ""].filter(Boolean).join(" · ")}</p>
              )}
              <p className="text-[11px] text-[#6b7280]">Valid till {dayText(validUntil)} · PDF link</p>
              <div className="mt-2 divide-y divide-[#f1f5f9] border-t border-[#f1f5f9] text-center font-semibold text-[#0b8a7a]">
                <p className="py-2"><Check size={13} className="inline" /> Accept quote</p>
                <p className="py-2">Ask a question</p>
              </div>
            </div>
            <p className="ml-auto w-fit rounded-xl bg-[#d9fdd3] px-3 py-1.5 text-[13px] text-[#111827] shadow-sm"><Check size={12} className="inline" /> Accept quote</p>
            <div className="rounded-xl bg-white p-3 text-[13px] leading-5 text-[#111827] shadow-sm">
              Nandri {first}! 🎉 Order confirmed.{advance > 0 ? ` Pay the ${rupees(advance)} advance here to start: ` : ""}
              {advance > 0 && <span className="text-[#0b8a7a]">rzp.io/…</span>}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
