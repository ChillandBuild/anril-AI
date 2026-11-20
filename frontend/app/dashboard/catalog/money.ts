import type { CatalogItem, StockMovement } from "@/lib/api";

/** Formats paise as a whole-rupee string with the ₹ sign, e.g. 320000 -> "₹3,200". */
export function formatPaise(paise: number): string {
  return `₹${Math.round(paise / 100).toLocaleString("en-IN")}`;
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

export const STOCK_REASON_LABEL: Record<StockMovement["reason"], string> = {
  sale: "Sold",
  restock: "Restocked",
  adjustment: "Corrected",
  return: "Returned",
};

export const GST_RATE_OPTIONS = [0, 5, 12, 18, 28] as const;

/** Available stock = tracked quantity minus what's held by open awaiting-payment deals. */
export function availableQuantity(stockQuantity: number, heldQuantity: number): number {
  return stockQuantity - heldQuantity;
}

/** Low = at or below the item's own alert level, or 5 pieces when it has none (deals.LOW_STOCK_THRESHOLD). */
export const DEFAULT_LOW_AT = 5;

export function isLow(item: Pick<CatalogItem, "stock_quantity" | "low_stock_at" | "held_quantity">): boolean {
  if (item.stock_quantity == null) return false;
  const available = availableQuantity(item.stock_quantity, item.held_quantity ?? 0);
  return available > 0 && available <= (item.low_stock_at ?? DEFAULT_LOW_AT);
}

/** Stock x cost price, or null when the item isn't counted or has no cost price. */
export function stockValuePaise(item: Pick<CatalogItem, "stock_quantity" | "cost_price_paise">): number | null {
  if (item.stock_quantity == null || item.cost_price_paise == null) return null;
  return Math.max(item.stock_quantity, 0) * item.cost_price_paise;
}
