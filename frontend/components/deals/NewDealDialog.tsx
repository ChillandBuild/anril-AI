"use client";
import { useEffect, useMemo, useState } from "react";
import { Check, Copy, Package, Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { api, CatalogItem, DealMutationResult, NewDealPayload, PaymentMethod } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { formatRupees } from "./money";

type Outcome = "paid" | "link" | "quote";
type ManualSource = "walk_in" | "call" | "manual";

interface DealLineDraft {
  key: string;
  catalogItemId: string | null;
  name: string;
  qty: number;
  unitPriceRupees: string;
  stockQuantity: number | null;
  heldQuantity: number;
}

interface NewDealDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: (result: DealMutationResult) => void;
  defaultLead?: { id: string; name: string | null; phone: string | null };
  defaultSource?: ManualSource;
  /** Preselect what happens on save, e.g. "link" from the chat's Payment link button. */
  defaultOutcome?: Outcome;
}

const SOURCE_OPTIONS: { value: ManualSource; label: string }[] = [
  { value: "walk_in", label: "Walk-in" },
  { value: "call", label: "Call" },
  { value: "manual", label: "Manual" },
];

const PAYMENT_METHODS: { value: PaymentMethod; label: string }[] = [
  { value: "cash", label: "Cash" },
  { value: "upi", label: "UPI" },
  { value: "card", label: "Card" },
  { value: "bank_transfer", label: "Bank transfer" },
  { value: "other", label: "Other" },
];

function newLine(): DealLineDraft {
  return {
    key: Math.random().toString(36).slice(2),
    catalogItemId: null,
    name: "",
    qty: 1,
    unitPriceRupees: "",
    stockQuantity: null,
    heldQuantity: 0,
  };
}

function CopyLinkRow({ link }: { link: string }) {
  const [copied, setCopied] = useState(false);
  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Could not copy — copy the link manually");
    }
  }
  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 space-y-2">
      <p className="font-label text-xs font-bold text-amber-800">
        WhatsApp message couldn&apos;t be sent — the 24h chat window may be closed. Share this link with the
        customer another way.
      </p>
      <div className="flex items-center gap-2">
        <input
          readOnly
          value={link}
          className="flex-1 min-w-0 truncate rounded-lg border border-amber-200 bg-white px-2.5 py-1.5 font-body text-xs text-ink"
        />
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-amber-300 bg-white px-2.5 py-1.5 font-label text-[11px] font-bold text-amber-800 hover:bg-amber-100"
        >
          {copied ? <Check size={12} className="text-emerald-600" /> : <Copy size={12} />}
          {copied ? "Copied" : "Copy link"}
        </button>
      </div>
    </div>
  );
}

export function NewDealDialog({ open, onClose, onCreated, defaultLead, defaultSource, defaultOutcome }: NewDealDialogProps) {
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [lines, setLines] = useState<DealLineDraft[]>([newLine()]);
  const [catalogItems, setCatalogItems] = useState<CatalogItem[]>([]);
  const [source, setSource] = useState<ManualSource>(defaultSource ?? "walk_in");
  const [outcome, setOutcome] = useState<Outcome>("quote");
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>("cash");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [pendingLink, setPendingLink] = useState<{ result: DealMutationResult; link: string } | null>(null);

  useEffect(() => {
    if (!open) return;
    setPhone("");
    setName("");
    setLines([newLine()]);
    setSource(defaultSource ?? "walk_in");
    setOutcome(defaultOutcome ?? "quote");
    setPaymentMethod("cash");
    setNotes("");
    setPendingLink(null);
    api.catalog
      .listItems()
      .then(setCatalogItems)
      .catch(() => setCatalogItems([]));
    // Reset only depends on the dialog opening, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const total = useMemo(
    () =>
      lines.reduce((sum, line) => {
        const price = Number(line.unitPriceRupees);
        if (!Number.isFinite(price)) return sum;
        return sum + Math.round(price * 100) * line.qty;
      }, 0),
    [lines]
  );

  if (!open) return null;

  function updateLine(key: string, patch: Partial<DealLineDraft>) {
    setLines((prev) => prev.map((line) => (line.key === key ? { ...line, ...patch } : line)));
  }

  function pickCatalogItem(key: string, itemId: string) {
    const item = catalogItems.find((i) => i.id === itemId);
    if (!item) {
      updateLine(key, { catalogItemId: null });
      return;
    }
    updateLine(key, {
      catalogItemId: item.id,
      name: item.name,
      unitPriceRupees: item.price_paise != null ? String(item.price_paise / 100) : "",
      stockQuantity: item.stock_quantity,
      heldQuantity: item.held_quantity ?? 0,
    });
  }

  function addLine() {
    setLines((prev) => [...prev, newLine()]);
  }

  function removeLine(key: string) {
    setLines((prev) => (prev.length > 1 ? prev.filter((line) => line.key !== key) : prev));
  }

  function validate(): string | null {
    if (!defaultLead && !phone.trim()) return "Enter the customer's phone number";
    if (lines.length === 0) return "Add at least one item";
    for (const line of lines) {
      if (!line.name.trim()) return "Every line needs an item name";
      if (!Number.isFinite(line.qty) || line.qty < 1) return "Quantity must be at least 1";
      const price = Number(line.unitPriceRupees);
      if (!line.unitPriceRupees.trim() || !Number.isFinite(price) || price < 0) return "Enter a valid price for every line";
    }
    return null;
  }

  async function handleSubmit() {
    const error = validate();
    if (error) {
      toast.error(error);
      return;
    }
    setSubmitting(true);
    try {
      const payload: NewDealPayload = {
        ...(defaultLead ? { lead_id: defaultLead.id } : { phone: phone.trim(), name: name.trim() || undefined }),
        items: lines.map((line) => ({
          catalog_item_id: line.catalogItemId ?? undefined,
          name: line.name.trim(),
          qty: line.qty,
          unit_price_paise: Math.round(Number(line.unitPriceRupees) * 100),
        })),
        source,
        stage: outcome === "paid" ? "won" : outcome === "link" ? "awaiting_payment" : "quoted",
        payment_method: outcome === "paid" ? paymentMethod : undefined,
        notes: notes.trim() || undefined,
      };
      const result = await api.deals.create(payload);

      if (result.stock_warnings.length > 0) {
        toast.error(
          `Low stock: ${result.stock_warnings.map((w) => `${w.name} (${w.available ?? 0} left)`).join(", ")}`
        );
      }

      if (outcome === "link" && result.message_sent === false && result.payment_link) {
        setPendingLink({ result, link: result.payment_link });
        return;
      }

      if (result.stock_warnings.length === 0) {
        toast.success(outcome === "paid" ? "Sale recorded" : outcome === "link" ? "Payment link sent" : "Quote saved");
      }
      onCreated(result);
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not create the deal");
    } finally {
      setSubmitting(false);
    }
  }

  function finishAfterLink() {
    if (pendingLink) onCreated(pendingLink.result);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-dialog flex items-end justify-center bg-black/50 p-0 backdrop-blur-sm sm:items-center sm:p-4">
      <div className="flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-t-3xl bg-white shadow-2xl sm:rounded-3xl">
        <div className="flex shrink-0 items-center justify-between border-b border-border px-6 py-4">
          <h2 className="font-display text-lg font-bold text-ink">New deal</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-full p-1.5 text-ink-muted hover:bg-surface-subtle hover:text-ink"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {pendingLink ? (
            <CopyLinkRow link={pendingLink.link} />
          ) : (
            <>
              {/* Customer */}
              {defaultLead ? (
                <div className="rounded-2xl border border-border bg-surface-subtle p-3">
                  <p className="font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">Customer</p>
                  <p className="font-body text-sm font-semibold text-ink">{defaultLead.name || defaultLead.phone}</p>
                  {defaultLead.name && defaultLead.phone && (
                    <p className="font-body text-xs text-ink-muted">{defaultLead.phone}</p>
                  )}
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="mb-1 block font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">
                      Phone
                    </label>
                    <input
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      placeholder="9876543210"
                      className="w-full rounded-xl border border-border px-3 py-2 font-body text-sm outline-none focus:border-primary"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">
                      Name (optional)
                    </label>
                    <input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="Customer name"
                      className="w-full rounded-xl border border-border px-3 py-2 font-body text-sm outline-none focus:border-primary"
                    />
                  </div>
                  <p className="col-span-2 font-body text-[11px] text-ink-muted">
                    A new phone number creates a new contact.
                  </p>
                </div>
              )}

              {/* Items */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">
                    Items
                  </label>
                  <button
                    type="button"
                    onClick={addLine}
                    className="inline-flex items-center gap-1 font-label text-[11px] font-bold text-primary hover:text-primary/80"
                  >
                    <Plus size={12} /> Add line
                  </button>
                </div>

                <div className="space-y-2">
                  {lines.map((line) => (
                    <div key={line.key} className="rounded-2xl border border-border p-3 space-y-2">
                      <div className="flex items-center gap-2">
                        <Select
                          size="sm"
                          aria-label="Catalog item"
                          className="w-40 shrink-0"
                          value={line.catalogItemId ?? ""}
                          onChange={(v) => (v ? pickCatalogItem(line.key, v) : updateLine(line.key, { catalogItemId: null }))}
                          options={[
                            { value: "", label: "Free text…" },
                            ...catalogItems.map((item) => ({ value: item.id, label: item.name })),
                          ]}
                        />
                        <input
                          value={line.name}
                          onChange={(e) => updateLine(line.key, { name: e.target.value, catalogItemId: null })}
                          placeholder="Item name"
                          disabled={Boolean(line.catalogItemId)}
                          className="min-w-0 flex-1 rounded-lg border border-border px-2.5 py-1.5 font-body text-sm text-ink outline-none focus:border-primary disabled:bg-surface-subtle disabled:text-ink-muted"
                        />
                        {lines.length > 1 && (
                          <button
                            type="button"
                            onClick={() => removeLine(line.key)}
                            aria-label="Remove line"
                            className="shrink-0 rounded-lg p-1.5 text-ink-muted hover:bg-rose-50 hover:text-rose-600"
                          >
                            <Trash2 size={14} />
                          </button>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="flex items-center gap-1">
                          <span className="font-body text-xs text-ink-muted">Qty</span>
                          <input
                            type="number"
                            min={1}
                            value={line.qty}
                            onChange={(e) => updateLine(line.key, { qty: Math.max(1, Number(e.target.value) || 1) })}
                            className="w-16 rounded-lg border border-border px-2 py-1 font-body text-sm text-ink outline-none focus:border-primary"
                          />
                        </div>
                        <div className="flex items-center gap-1">
                          <span className="font-body text-xs text-ink-muted">₹</span>
                          <input
                            type="number"
                            min={0}
                            step="0.01"
                            value={line.unitPriceRupees}
                            onChange={(e) => updateLine(line.key, { unitPriceRupees: e.target.value })}
                            placeholder="Price"
                            className="w-24 rounded-lg border border-border px-2 py-1 font-body text-sm text-ink outline-none focus:border-primary"
                          />
                        </div>
                        {line.catalogItemId && line.stockQuantity != null && (
                          <span className="ml-auto inline-flex items-center gap-1 font-body text-[11px] text-ink-muted">
                            <Package size={11} /> {line.stockQuantity} in stock · {line.heldQuantity} held
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Source */}
              <div>
                <label className="mb-1.5 block font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">
                  Source
                </label>
                <div className="flex gap-1.5">
                  {SOURCE_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setSource(opt.value)}
                      className={`flex-1 rounded-xl border px-3 py-2 font-label text-xs font-bold transition-colors ${
                        source === opt.value
                          ? "border-primary bg-primary text-white"
                          : "border-border text-ink-muted hover:bg-surface-subtle"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Outcome */}
              <div>
                <label className="mb-1.5 block font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">
                  Outcome
                </label>
                <div className="space-y-1.5">
                  {[
                    { value: "paid" as const, label: "Paid now" },
                    { value: "link" as const, label: "Send payment link on WhatsApp" },
                    { value: "quote" as const, label: "Just a quote" },
                  ].map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setOutcome(opt.value)}
                      className={`flex w-full items-center justify-between rounded-xl border px-3 py-2.5 text-left font-label text-xs font-bold transition-colors ${
                        outcome === opt.value
                          ? "border-primary bg-primary/5 text-primary"
                          : "border-border text-ink-muted hover:bg-surface-subtle"
                      }`}
                    >
                      {opt.label}
                      {outcome === opt.value && <Check size={14} />}
                    </button>
                  ))}
                </div>
                {outcome === "paid" && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {PAYMENT_METHODS.map((pm) => (
                      <button
                        key={pm.value}
                        type="button"
                        onClick={() => setPaymentMethod(pm.value)}
                        className={`rounded-full border px-3 py-1 font-label text-[11px] font-bold transition-colors ${
                          paymentMethod === pm.value
                            ? "border-primary bg-primary text-white"
                            : "border-border text-ink-muted hover:bg-surface-subtle"
                        }`}
                      >
                        {pm.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <label className="mb-1 block font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">
                  Notes (optional)
                </label>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  rows={2}
                  className="w-full rounded-xl border border-border px-3 py-2 font-body text-sm text-ink outline-none focus:border-primary"
                />
              </div>
            </>
          )}
        </div>

        <div className="shrink-0 border-t border-border px-6 py-4 pb-[calc(1rem+env(safe-area-inset-bottom,0px))]">
          {pendingLink ? (
            <button
              type="button"
              onClick={finishAfterLink}
              className="w-full rounded-xl bg-primary py-2.5 font-label text-sm font-bold text-white hover:bg-primary/90"
            >
              Done
            </button>
          ) : (
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="font-label text-[10px] font-bold uppercase tracking-wide text-ink-muted">Total</p>
                <p className="font-display text-2xl font-bold text-ink">{formatRupees(total)}</p>
              </div>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={submitting}
                className="rounded-xl bg-primary px-5 py-2.5 font-label text-sm font-bold text-white hover:bg-primary/90 disabled:opacity-50"
              >
                {submitting ? "Saving…" : "Create deal"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
