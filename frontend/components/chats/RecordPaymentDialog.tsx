"use client";
import { useEffect, useMemo, useState } from "react";
import { Banknote, Check, CreditCard, Loader2, MessageCircle, Plus, Receipt, Smartphone, X } from "lucide-react";
import { toast } from "sonner";
import { api, CatalogItem, Lead } from "@/lib/api";
import { cn, formatPhone } from "@/lib/utils";
import { Select } from "@/components/ui/Select";
import { SwitchPill } from "@/components/ui/controls";
import { formatRupees } from "@/components/deals/money";
import { getChannel } from "@/components/channel-avatar";
import type { Option } from "./inboxFilters";

type Method = "link" | "cash" | "upi" | "card";

const METHODS: { value: Method; label: string; icon: typeof Banknote }[] = [
  { value: "link", label: "Send link on WhatsApp", icon: MessageCircle },
  { value: "cash", label: "Cash", icon: Banknote },
  { value: "upi", label: "UPI", icon: Smartphone },
  { value: "card", label: "Card", icon: CreditCard },
];

const QUICK_PICKS = 3;

function toPaise(rupees: string): number {
  const n = Number(rupees.replace(/[^\d.]/g, ""));
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}

/**
 * Chats > Record payment. One short form: how it was paid, how much, who sold it and what for.
 * Saved as a deal; a WhatsApp link turns the chat Came / Paid by itself when the customer pays.
 */
export function RecordPaymentDialog({
  open,
  onClose,
  lead,
  team,
  defaultMethod = "link",
  defaultSoldBy,
  onRecorded,
}: {
  open: boolean;
  onClose: () => void;
  lead: Lead;
  team: Option[];
  defaultMethod?: Method;
  defaultSoldBy?: string | null;
  onRecorded?: () => void;
}) {
  const isWhatsApp = getChannel(lead.source) === "whatsapp";
  const [method, setMethod] = useState<Method>(isWhatsApp ? defaultMethod : "cash");
  const [amount, setAmount] = useState("");
  const [amountTouched, setAmountTouched] = useState(false);
  const [soldBy, setSoldBy] = useState<string>(defaultSoldBy ?? "");
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [suggested, setSuggested] = useState<string[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [showMore, setShowMore] = useState(false);
  const [pricesIncludeGst, setPricesIncludeGst] = useState(true);
  const [saving, setSaving] = useState(false);
  const name = lead.name || formatPhone(lead.phone) || "the customer";

  useEffect(() => {
    if (!open) return;
    setMethod(isWhatsApp ? defaultMethod : "cash");
    setAmount("");
    setAmountTouched(false);
    setSoldBy(defaultSoldBy ?? "");
    setPicked([]);
    setShowMore(false);
    let live = true;
    api.catalog.listItems()
      .then((items) => live && setCatalog(items.filter((i) => i.price_paise != null)))
      .catch(() => {});
    api.deals.recordPaymentOptions(lead.id)
      .then((o) => {
        if (!live) return;
        setSuggested(o.suggested_item_ids);
        setPricesIncludeGst(o.prices_include_gst);
      })
      .catch(() => {});
    return () => { live = false; };
  }, [open, lead.id, defaultMethod, defaultSoldBy, isWhatsApp]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !saving) onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, saving, onClose]);

  const byId = useMemo(() => new Map(catalog.map((i) => [i.id, i])), [catalog]);
  // Quoted products first, then the rest of the catalogue, so the likely ones are one tap away.
  const quickPicks = useMemo(() => {
    const ids = [...suggested.filter((id) => byId.has(id)), ...catalog.map((i) => i.id)];
    return Array.from(new Set([...picked, ...ids])).slice(0, Math.max(QUICK_PICKS, picked.length));
  }, [suggested, catalog, picked, byId]);

  const pickedTotal = picked.reduce((sum, id) => sum + (byId.get(id)?.price_paise ?? 0), 0);

  function togglePick(id: string) {
    const next = picked.includes(id) ? picked.filter((p) => p !== id) : [...picked, id];
    setPicked(next);
    if (!amountTouched) {
      const sum = next.reduce((s, pid) => s + (byId.get(pid)?.price_paise ?? 0), 0);
      setAmount(sum ? String(Math.round(sum / 100)) : "");
    }
  }

  const amountPaise = toPaise(amount);
  // When the business's prices exclude GST, the deal adds it on top (same rule as Deals).
  const gstPaise = pricesIncludeGst
    ? 0
    : (() => {
        if (!picked.length) return 0;
        const lines = picked.map((id) => byId.get(id));
        const others = lines.slice(0, -1).reduce((s, it) => s + (it?.price_paise ?? 0), 0);
        const prices = [...lines.slice(0, -1).map((it) => it?.price_paise ?? 0), Math.max(0, amountPaise - others)];
        return lines.reduce((s, it, idx) => s + Math.round((prices[idx] * (it?.gst_rate ?? 0)) / 100), 0);
      })();
  const payable = amountPaise + gstPaise;
  const othersTotal = picked.slice(0, -1).reduce((s, id) => s + (byId.get(id)?.price_paise ?? 0), 0);
  const amountError =
    amount && amountPaise < 100 ? "Enter at least ₹1."
    : picked.length > 1 && amountPaise < othersTotal ? `The products picked come to more than this. Raise the amount or remove one.`
    : null;
  const canSave = amountPaise >= 100 && !amountError && !saving;

  async function save() {
    if (!canSave) return;
    setSaving(true);
    try {
      const res = await api.deals.recordPayment({
        lead_id: lead.id,
        method,
        amount_paise: amountPaise,
        item_ids: picked,
        sold_by: soldBy || null,
      });
      if (method === "link") {
        if (res.message_sent) toast.success(`Payment link sent to ${name}`);
        else toast.warning("Link made, but WhatsApp didn't send it. Copy it from Deals and share it yourself.");
      } else {
        toast.success(`${formatRupees(res.deal?.total_paise ?? payable)} recorded as paid`);
      }
      onRecorded?.();
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't record the payment");
    } finally {
      setSaving(false);
    }
  }

  if (!open) return null;

  const moreOptions = catalog
    .filter((i) => !quickPicks.includes(i.id))
    .map((i) => ({ value: i.id, label: `${i.name} · ${formatRupees(i.price_paise)}`, text: i.name }));

  return (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-[#0A1528]/45 p-4" onMouseDown={() => !saving && onClose()}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="record-payment-title"
        onMouseDown={(e) => e.stopPropagation()}
        className="flex max-h-[calc(100dvh-2rem)] w-full max-w-[560px] flex-col overflow-hidden rounded-2xl bg-white shadow-[0_30px_80px_-20px_rgba(10,21,40,0.45)]"
      >
        {/* Header */}
        <div className="flex items-start gap-3 px-6 pt-5 pb-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary-light text-primary">
            <Receipt size={19} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 id="record-payment-title" className="truncate font-display text-[17px] font-bold text-[#0A1528]">
              Record payment · {name}
            </h2>
            <p className="mt-0.5 text-[12px] leading-snug text-[#64748b]">
              Saved as an order in <span className="font-semibold text-primary">Commerce › Deals</span>.
              The chat becomes <span className="font-semibold text-[#0A1528]">Came / Paid</span> once it&apos;s paid.
            </p>
          </div>
          <button onClick={onClose} disabled={saving} aria-label="Close" className="rounded-lg p-1.5 text-[#64748b] hover:bg-slate-100 hover:text-[#0A1528]">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-6 pb-5">
          {/* Paid by */}
          <section>
            <p className="mb-2 font-label text-[10.5px] font-bold uppercase tracking-[0.08em] text-[#64748b]">Paid by</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-[2.1fr_1fr_1fr_1fr]">
              {METHODS.map((m) => {
                const Icon = m.icon;
                const active = method === m.value;
                const disabled = m.value === "link" && !isWhatsApp;
                return (
                  <button
                    key={m.value}
                    type="button"
                    aria-pressed={active}
                    disabled={disabled}
                    title={disabled ? "Payment links go out on WhatsApp only" : undefined}
                    onClick={() => setMethod(m.value)}
                    className={cn(
                      "flex h-10 items-center justify-center gap-1.5 rounded-xl border px-2 text-[12.5px] font-semibold transition-colors",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30",
                      active
                        ? "border-primary bg-primary-light text-primary"
                        : "border-[#e2e8f0] text-[#334155] hover:border-slate-300 hover:bg-[#f8fafc]",
                      disabled && "cursor-not-allowed opacity-40 hover:bg-transparent",
                      m.value === "link" && "col-span-2 sm:col-span-1"
                    )}
                  >
                    <Icon size={15} />
                    <span className="truncate">{m.label}</span>
                  </button>
                );
              })}
            </div>
          </section>

          {/* Amount + Sold by */}
          <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="rp-amount" className="mb-2 block font-label text-[10.5px] font-bold uppercase tracking-[0.08em] text-[#64748b]">
                Amount
              </label>
              <div className={cn(
                "flex h-12 items-center rounded-xl border px-3.5 focus-within:ring-2",
                amountError ? "border-red-300 focus-within:ring-red-100" : "border-[#e2e8f0] focus-within:border-primary focus-within:ring-primary/15"
              )}>
                <span className="mr-1.5 font-display text-[20px] font-bold text-[#94a3b8]">₹</span>
                <input
                  id="rp-amount"
                  inputMode="decimal"
                  autoFocus
                  value={amount}
                  onChange={(e) => { setAmount(e.target.value.replace(/[^\d.]/g, "")); setAmountTouched(true); }}
                  onKeyDown={(e) => { if (e.key === "Enter") void save(); }}
                  placeholder="0"
                  className="w-full bg-transparent font-display text-[20px] font-bold text-[#0A1528] placeholder:text-[#cbd5e1] focus:outline-none"
                />
              </div>
              {amountError && <p className="mt-1.5 text-[11.5px] text-red-600">{amountError}</p>}
            </div>
            <div>
              <p id="rp-sold-by" className="mb-2 font-label text-[10.5px] font-bold uppercase tracking-[0.08em] text-[#64748b]">Sold by</p>
              <Select
                aria-labelledby="rp-sold-by"
                value={soldBy}
                onChange={setSoldBy}
                options={[{ value: "", label: "Not set" }, ...team]}
                className="h-12 rounded-xl"
              />
            </div>
          </section>

          {/* What for */}
          <section>
            <p className="mb-2 font-label text-[10.5px] font-bold uppercase tracking-[0.08em] text-[#64748b]">
              What for <span className="normal-case tracking-normal font-semibold text-primary">· from your catalogue</span>
            </p>
            {catalog.length === 0 ? (
              <p className="text-[12px] text-[#64748b]">No priced products in your catalogue yet. The amount is saved as one payment.</p>
            ) : (
              <div className="flex flex-wrap items-center gap-1.5">
                {quickPicks.map((id) => {
                  const item = byId.get(id);
                  if (!item) return null;
                  const on = picked.includes(id);
                  return (
                    <button
                      key={id}
                      type="button"
                      aria-pressed={on}
                      onClick={() => togglePick(id)}
                      className={cn(
                        "inline-flex h-9 max-w-full items-center gap-1.5 rounded-full border px-3.5 text-[12.5px] font-semibold transition-colors",
                        on ? "border-primary bg-primary-light text-primary" : "border-[#e2e8f0] text-[#334155] hover:border-slate-300 hover:bg-[#f8fafc]"
                      )}
                    >
                      {on && <Check size={13} strokeWidth={2.75} />}
                      <span className="truncate">{item.name}</span>
                      <span className={on ? "text-primary/70" : "text-[#94a3b8]"}>{formatRupees(item.price_paise)}</span>
                    </button>
                  );
                })}
                {moreOptions.length > 0 && (showMore ? (
                  <div className="min-w-[220px] flex-1">
                    <Select
                      size="sm"
                      value=""
                      onChange={(v) => { if (v) { togglePick(v); setShowMore(false); } }}
                      placeholder="Pick a product…"
                      aria-label="More products"
                      options={moreOptions}
                    />
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setShowMore(true)}
                    className="inline-flex h-9 items-center gap-1 rounded-full border border-dashed border-[#cbd5e1] px-3.5 text-[12.5px] font-semibold text-[#475569] hover:border-primary hover:text-primary"
                  >
                    <Plus size={13} /> More
                  </button>
                ))}
              </div>
            )}
            {picked.length > 0 && amountTouched && amountPaise !== pickedTotal && !amountError && (
              <p className="mt-2 text-[11.5px] text-[#64748b]">
                Catalogue price {formatRupees(pickedTotal)}; saved at {formatRupees(amountPaise)} ({amountPaise < pickedTotal ? "a discount" : "extra"} on the last product).
              </p>
            )}
          </section>

          {/* GST invoice: shown now, switched on once GST details are collected at onboarding. */}
          <section className="flex items-center gap-3 rounded-xl border border-[#eef1f5] bg-[#fbfcfd] px-4 py-3">
            <SwitchPill on={false} disabled onChange={() => {}} size="sm" aria-label="Send GST invoice on WhatsApp" />
            <div className="min-w-0">
              <p className="text-[13px] font-semibold text-[#0A1528]">Send GST invoice on WhatsApp</p>
              <p className="text-[11.5px] text-[#64748b]">Coming soon. It switches on once your GST details are set up.</p>
            </div>
          </section>

          {/* What happens next, in plain words */}
          <div className="rounded-xl bg-[#ecfdf5] px-4 py-3 text-[12.5px] leading-relaxed text-[#065f46]">
            {method === "link" ? (
              <>
                The link goes to {name}&apos;s chat. When they pay, the order is marked paid in Deals and the chat
                becomes <span className="font-bold">Came / Paid {amountPaise ? formatRupees(payable) : ""}</span> by itself. No more taps.
              </>
            ) : (
              <>
                Saved as paid by {METHODS.find((m) => m.value === method)?.label} now. The chat becomes{" "}
                <span className="font-bold">Came / Paid {amountPaise ? formatRupees(payable) : ""}</span>.
              </>
            )}
            {gstPaise > 0 && <> Includes {formatRupees(gstPaise)} GST, added on top of your prices.</>}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center gap-3 border-t border-[#eef1f5] px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="h-11 flex-1 rounded-xl border border-[#e2e8f0] text-[13.5px] font-semibold text-[#334155] hover:bg-slate-50 sm:flex-none sm:px-8"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={!canSave}
            className="inline-flex h-11 flex-[2] items-center justify-center gap-2 rounded-xl bg-primary text-[13.5px] font-bold text-white shadow-sm hover:bg-[var(--primary-900)] disabled:cursor-not-allowed disabled:opacity-45"
          >
            {saving && <Loader2 size={15} className="animate-spin" />}
            {method === "link"
              ? "Send link on WhatsApp"
              : `Record ${amountPaise ? formatRupees(payable) : ""} paid`.replace("  ", " ")}
          </button>
        </div>
      </div>
    </div>
  );
}
