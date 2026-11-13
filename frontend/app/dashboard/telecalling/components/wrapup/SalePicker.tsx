"use client";
import { Minus, Plus, X } from "lucide-react";
import type { CatalogItem } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { formatRupees } from "@/components/deals/money";
import type { SaleLine, WrapupDraft } from "../../lib/wrapup-draft";

type SalePatch = Partial<Pick<WrapupDraft, "saleMode" | "products" | "amountRupees">>;

interface SalePickerProps {
  mode: WrapupDraft["saleMode"];
  products: SaleLine[];
  amountRupees: string;
  catalogItems: CatalogItem[];
  onChange: (patch: SalePatch) => void;
}

const STEP = "grid h-6 w-6 place-items-center rounded-lg border border-[#e2e8f0] text-[#334155] hover:bg-[#f8fafc]";
const MAX_PRODUCTS = 20;

/** Converted: products from the catalog (price comes from the catalog) or one amount. */
export default function SalePicker({ mode, products, amountRupees, catalogItems, onChange }: SalePickerProps) {
  const available = catalogItems.filter((item) => !products.some((p) => p.catalogItemId === item.id));
  const total = products.reduce((sum, p) => sum + (p.pricePaise ?? 0) * p.qty, 0);
  const atLimit = products.length >= MAX_PRODUCTS;

  function add(id: string) {
    const item = catalogItems.find((i) => i.id === id);
    if (!item || item.price_paise == null) return;
    onChange({ products: [...products, { catalogItemId: item.id, name: item.name, qty: 1, pricePaise: item.price_paise }] });
  }

  function setQty(id: string, qty: number) {
    onChange({ products: products.map((p) => (p.catalogItemId === id ? { ...p, qty: Math.max(1, Math.min(1000, qty)) } : p)) });
  }

  return (
    <div className="rounded-2xl border border-emerald-200 bg-emerald-50/50 p-3 space-y-3">
      <div className="inline-flex rounded-xl border border-emerald-200 bg-white p-0.5">
        {(["products", "amount"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => onChange({ saleMode: m })}
            className={`px-3 py-1 rounded-lg font-label text-[11px] font-bold transition-colors ${mode === m ? "bg-emerald-600 text-white" : "text-emerald-800 hover:bg-emerald-50"}`}
          >
            {m === "products" ? "From products" : "Enter amount"}
          </button>
        ))}
      </div>

      {mode === "products" ? (
        <>
          {products.length > 0 && (
            <ul className="space-y-1.5">
              {products.map((p) => (
                <li key={p.catalogItemId} className="flex items-center gap-2 rounded-xl border border-[#e2e8f0] bg-white px-2.5 py-2">
                  <span className="min-w-0 flex-1 truncate font-body text-xs font-semibold text-[#13284A]">{p.name}</span>
                  <div className="flex items-center gap-1">
                    <button type="button" aria-label={`One less ${p.name}`} onClick={() => setQty(p.catalogItemId, p.qty - 1)} className={STEP}>
                      <Minus size={11} />
                    </button>
                    <span className="w-6 text-center font-mono text-xs font-bold tabular-nums">{p.qty}</span>
                    <button type="button" aria-label={`One more ${p.name}`} onClick={() => setQty(p.catalogItemId, p.qty + 1)} className={STEP}>
                      <Plus size={11} />
                    </button>
                  </div>
                  <span className="w-16 text-right font-label text-[11px] font-bold tabular-nums text-[#1e293b]">{formatRupees((p.pricePaise ?? 0) * p.qty)}</span>
                  <button
                    type="button"
                    aria-label={`Remove ${p.name}`}
                    onClick={() => onChange({ products: products.filter((x) => x.catalogItemId !== p.catalogItemId) })}
                    className="text-[#94a3b8] hover:text-rose-600"
                  >
                    <X size={13} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {/* Always shows the "Add a product…" prompt; key resets it after each pick. */}
          <Select
            size="sm"
            value=""
            onChange={add}
            aria-label="Add a product"
            disabled={atLimit || catalogItems.length === 0}
            placeholder={atLimit ? `Limit reached — ${MAX_PRODUCTS} products max` : catalogItems.length === 0 ? "No products yet — enter the amount instead" : "Add a product…"}
            options={available.map((item) => ({
              value: item.id,
              label: `${item.name}${item.price_paise == null ? " (no price)" : ` · ${formatRupees(item.price_paise)}`}`,
              disabled: item.price_paise == null,
            }))}
          />
          {products.length > 0 && <p className="text-right font-label text-xs font-bold text-emerald-800">Total {formatRupees(total)}</p>}
        </>
      ) : (
        <label className="flex items-center gap-2 rounded-xl border border-[#e2e8f0] bg-white px-3 py-2">
          <span className="font-label text-sm font-bold text-[#334155]">₹</span>
          <input
            inputMode="decimal"
            value={amountRupees}
            onChange={(e) => onChange({ amountRupees: e.target.value })}
            placeholder="Amount received"
            aria-label="Sale amount in rupees"
            className="flex-1 bg-transparent font-body text-sm focus:outline-none"
          />
        </label>
      )}
      <p className="font-label text-[10px] text-emerald-800/80">Saving records a Won deal from this call.</p>
    </div>
  );
}
