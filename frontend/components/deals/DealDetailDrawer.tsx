"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, Copy, MessageCircle, X } from "lucide-react";
import { toast } from "sonner";
import { api, Deal, PaymentMethod } from "@/lib/api";
import { prettify } from "@/app/dashboard/intake/columns";
import { StageBadge } from "./StageBadge";
import { SourceBadge } from "./SourceBadge";
import { formatRupees } from "./money";

const PAYMENT_METHODS: { value: PaymentMethod; label: string }[] = [
  { value: "cash", label: "Cash" },
  { value: "upi", label: "UPI" },
  { value: "card", label: "Card" },
  { value: "bank_transfer", label: "Bank transfer" },
  { value: "other", label: "Other" },
];

interface DealDetailDrawerProps {
  dealId: string;
  onClose: () => void;
  onChanged: () => void;
  canManage: boolean;
}

export function DealDetailDrawer({ dealId, onClose, onChanged, canManage }: DealDetailDrawerProps) {
  const [deal, setDeal] = useState<Deal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showWonForm, setShowWonForm] = useState(false);
  const [showLostForm, setShowLostForm] = useState(false);
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>("cash");
  const [lostReason, setLostReason] = useState("");
  const [copied, setCopied] = useState(false);

  async function load() {
    setLoading(true);
    setError(false);
    try {
      setDeal(await api.deals.get(dealId));
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealId]);

  async function handleMarkWon() {
    setBusy(true);
    try {
      const result = await api.deals.updateStage(dealId, { stage: "won", payment_method: paymentMethod });
      setDeal(result.deal);
      if (result.stock_warnings.length > 0) {
        toast.error(
          `Low stock: ${result.stock_warnings.map((w) => `${w.name} (${w.available ?? 0} left)`).join(", ")}`
        );
      } else {
        toast.success("Marked as won");
      }
      setShowWonForm(false);
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update the deal");
    } finally {
      setBusy(false);
    }
  }

  async function handleMarkLost() {
    if (!lostReason.trim()) {
      toast.error("Enter a reason");
      return;
    }
    setBusy(true);
    try {
      const result = await api.deals.updateStage(dealId, { stage: "lost", lost_reason: lostReason.trim() });
      setDeal(result.deal);
      toast.success("Marked as lost");
      setShowLostForm(false);
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update the deal");
    } finally {
      setBusy(false);
    }
  }

  async function handleSendLink() {
    setBusy(true);
    try {
      const result = await api.deals.sendLink(dealId);
      await load();
      if (result.message_sent) {
        toast.success("Payment link sent");
      } else {
        toast.error("WhatsApp message couldn't be sent — the 24h chat window may be closed. Copy the link below.");
      }
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not send the link");
    } finally {
      setBusy(false);
    }
  }

  async function copyLink(link: string) {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Could not copy link");
    }
  }

  const canAct = canManage && deal && deal.stage !== "won" && deal.stage !== "lost";

  return (
    <div className="fixed inset-0 z-dialog flex justify-end bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-md flex-col overflow-hidden bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-border px-5 py-4">
          <h2 className="font-display text-base font-bold text-ink">
            {deal ? deal.deal_label : "Deal"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-full p-1.5 text-ink-muted hover:bg-surface-subtle hover:text-ink"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {loading && <p className="font-body text-sm text-ink-muted">Loading…</p>}
          {!loading && error && (
            <div className="space-y-2">
              <p className="font-body text-sm text-rose-600">Could not load this deal.</p>
              <button
                type="button"
                onClick={load}
                className="rounded-xl border border-border px-3 py-1.5 font-label text-xs font-bold text-ink hover:bg-surface-subtle"
              >
                Retry
              </button>
            </div>
          )}
          {!loading && !error && deal && (
            <>
              <div className="flex items-center gap-2 flex-wrap">
                <StageBadge stage={deal.stage} />
                <SourceBadge source={deal.source} />
              </div>

              <div>
                <p className="font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">Customer</p>
                <p className="font-body text-sm font-semibold text-ink">
                  {deal.lead.name || deal.lead.phone || "Unknown"}
                </p>
                {deal.lead.phone && <p className="font-body text-xs text-ink-muted">{deal.lead.phone}</p>}
                {deal.lead.id && (
                  <Link
                    href={`/dashboard/conversations?lead=${deal.lead.id}`}
                    className="mt-1 inline-flex items-center gap-1 font-label text-xs font-bold text-primary hover:text-primary/80"
                  >
                    <MessageCircle size={12} /> Open chat
                  </Link>
                )}
              </div>

              <div>
                <p className="mb-1.5 font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">Items</p>
                <div className="space-y-1.5 rounded-2xl border border-border p-3">
                  {deal.items.map((item) => (
                    <div key={item.id} className="flex items-center justify-between gap-2">
                      <p className="font-body text-sm text-ink">
                        {item.name} <span className="text-ink-muted">×{item.qty}</span>
                      </p>
                      <p className="font-body text-sm text-ink">{formatRupees(item.line_total_paise)}</p>
                    </div>
                  ))}
                  <div className="mt-1 flex items-center justify-between border-t border-border-subtle pt-1.5">
                    <p className="font-label text-xs font-bold text-ink">Total</p>
                    <p className="font-display text-lg font-bold text-ink">{formatRupees(deal.total_paise)}</p>
                  </div>
                </div>
              </div>

              {deal.intake_answers && Object.keys(deal.intake_answers).length > 0 && (
                <div>
                  <p className="mb-1.5 font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">Form answers</p>
                  <div className="rounded-xl border border-border overflow-hidden divide-y divide-border-subtle">
                    {Object.entries(deal.intake_answers).map(([key, value]) => {
                      let displayValue: string;
                      if (typeof value === "string") {
                        displayValue = value;
                      } else if (typeof value === "number" || typeof value === "boolean") {
                        displayValue = String(value);
                      } else if (Array.isArray(value)) {
                        displayValue = value.join(", ");
                      } else if (typeof value === "object" && value !== null) {
                        displayValue = JSON.stringify(value);
                      } else {
                        displayValue = "—";
                      }
                      return (
                        <div
                          key={key}
                          className="grid grid-cols-[minmax(0,140px)_minmax(0,1fr)] gap-3 px-3 py-2"
                        >
                          <p className="text-xs text-ink-muted">{prettify(key)}</p>
                          <p className="text-sm font-semibold text-ink break-words">{displayValue}</p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {deal.notes && (
                <div>
                  <p className="font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">Notes</p>
                  <p className="font-body text-sm text-ink">{deal.notes}</p>
                </div>
              )}

              {deal.payment_link && (
                <div>
                  <p className="mb-1 font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">
                    Payment link
                  </p>
                  <div className="flex items-center gap-2">
                    <input
                      readOnly
                      value={deal.payment_link}
                      className="flex-1 min-w-0 truncate rounded-lg border border-border bg-surface-subtle px-2.5 py-1.5 font-body text-xs text-ink"
                    />
                    <button
                      type="button"
                      onClick={() => copyLink(deal.payment_link!)}
                      className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 font-label text-[11px] font-bold text-ink-muted hover:bg-surface-subtle"
                    >
                      {copied ? <Check size={12} className="text-emerald-600" /> : <Copy size={12} />}
                      {copied ? "Copied" : "Copy"}
                    </button>
                  </div>
                </div>
              )}

              {deal.stage === "lost" && deal.lost_reason && (
                <div>
                  <p className="font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">Lost reason</p>
                  <p className="font-body text-sm text-ink">{deal.lost_reason}</p>
                </div>
              )}

              {canAct && (
                <div className="space-y-2 border-t border-border pt-4">
                  {(deal.stage === "quoted" || deal.stage === "awaiting_payment") && (
                    <button
                      type="button"
                      onClick={handleSendLink}
                      disabled={busy}
                      className="w-full rounded-xl border border-border py-2 font-label text-xs font-bold text-ink hover:bg-surface-subtle disabled:opacity-50"
                    >
                      {deal.stage === "awaiting_payment" ? "Resend link" : "Send payment link"}
                    </button>
                  )}

                  {showWonForm ? (
                    <div className="space-y-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3">
                      <p className="font-label text-[10px] font-bold uppercase tracking-wide text-emerald-800">
                        Payment method
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {PAYMENT_METHODS.map((pm) => (
                          <button
                            key={pm.value}
                            type="button"
                            onClick={() => setPaymentMethod(pm.value)}
                            className={`rounded-full border px-3 py-1 font-label text-[11px] font-bold ${
                              paymentMethod === pm.value
                                ? "border-emerald-600 bg-emerald-600 text-white"
                                : "border-emerald-200 bg-white text-emerald-800"
                            }`}
                          >
                            {pm.label}
                          </button>
                        ))}
                      </div>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={handleMarkWon}
                          disabled={busy}
                          className="flex-1 rounded-lg bg-primary py-1.5 font-label text-xs font-bold text-white hover:bg-primary-dark disabled:opacity-50"
                        >
                          Confirm won
                        </button>
                        <button
                          type="button"
                          onClick={() => setShowWonForm(false)}
                          className="rounded-lg border border-emerald-200 px-3 py-1.5 font-label text-xs font-bold text-emerald-800"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setShowWonForm(true)}
                      className="w-full rounded-xl bg-primary py-2 font-label text-xs font-bold text-white hover:bg-primary-dark"
                    >
                      Mark won
                    </button>
                  )}

                  {showLostForm ? (
                    <div className="space-y-2 rounded-xl border border-rose-200 bg-rose-50 p-3">
                      <textarea
                        value={lostReason}
                        onChange={(e) => setLostReason(e.target.value)}
                        placeholder="Reason"
                        rows={2}
                        className="w-full rounded-lg border border-rose-200 bg-white px-2.5 py-1.5 font-body text-xs text-ink outline-none"
                      />
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={handleMarkLost}
                          disabled={busy}
                          className="flex-1 rounded-lg bg-rose-600 py-1.5 font-label text-xs font-bold text-white hover:bg-rose-700 disabled:opacity-50"
                        >
                          Confirm lost
                        </button>
                        <button
                          type="button"
                          onClick={() => setShowLostForm(false)}
                          className="rounded-lg border border-rose-200 px-3 py-1.5 font-label text-xs font-bold text-rose-800"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setShowLostForm(true)}
                      className="w-full rounded-xl border border-rose-200 py-2 font-label text-xs font-bold text-rose-700 hover:bg-rose-50"
                    >
                      Mark lost
                    </button>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
