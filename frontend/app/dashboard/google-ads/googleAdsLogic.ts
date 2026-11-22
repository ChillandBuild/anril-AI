/** Small pure helpers for the Google Ads page. Months are "YYYY-MM"; money is paise. */

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** This month in Indian time, as "YYYY-MM". */
export function currentMonthIst(now: Date = new Date()): string {
  const ist = new Date(now.getTime() + 5.5 * 3600 * 1000);
  return `${ist.getUTCFullYear()}-${String(ist.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function isMonth(value: string | null | undefined): value is string {
  return !!value && /^\d{4}-(0[1-9]|1[0-2])$/.test(value);
}

export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const index = y * 12 + (m - 1) + delta;
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`;
}

export function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return `${MONTH_NAMES[m - 1]} ${y}`;
}

/** 123456 paise -> "₹1,235" (whole rupees, Indian grouping); null -> "—". */
export function formatRupees(paise: number | null | undefined): string {
  if (paise === null || paise === undefined) return "—";
  return `₹${Math.round(paise / 100).toLocaleString("en-IN")}`;
}

/** What a person typed ("₹1,234.50", "1200") -> paise, or null when it is not a usable amount. */
export function rupeesToPaise(input: string): number | null {
  const cleaned = input.replace(/[₹,\s]|rs\.?/gi, "");
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  return Math.round(parseFloat(cleaned) * 100);
}

/** Whole number typed by a person ("1,234") -> 1234, or null. */
export function parseWholeNumber(input: string): number | null {
  const cleaned = input.replace(/[,\s]/g, "");
  return /^\d{1,9}$/.test(cleaned) ? Number(cleaned) : null;
}

/** "Paid" cell: count, plus the rupees when the caller may see money. */
export function paidCell(orders: number, paise: number | undefined): string {
  if (paise === undefined) return String(orders);
  return orders === 0 ? "0" : `${orders} · ${formatRupees(paise)}`;
}

export function countCell(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("en-IN");
}
