import { apiFetch } from "@/lib/api";

/** Real estate Properties (catalogue). Every call is /api/v1/properties/...; shapes follow routes/properties.py. */

export type PropertyKind = "flat" | "villa" | "plot" | "commercial" | "other";

export const KIND_LABEL: Record<PropertyKind, string> = {
  flat: "Flat",
  villa: "Villa",
  plot: "Plot",
  commercial: "Commercial",
  other: "Other",
};

export interface Property {
  id: string;
  name: string;
  description: string | null;
  /** False = hidden from the AI agent. */
  ai_on: boolean;
  project: string | null;
  kind: PropertyKind;
  bhk: number | null;
  size_text: string | null;
  units_total: number | null;
  units_left: number | null;
  map_url: string | null;
  rera_no: string | null;
  visit_service_id: string | null;
  /** Prices are left out for people without orders access. */
  price_min_paise?: number | null;
  price_max_paise?: number | null;
  created_at?: string;
  /** Only on the single-property call. */
  brochure?: { id: string; title: string | null; url: string | null; pages: number | null } | null;
  photos?: { id: string; url: string; label: string | null }[];
}

export interface PropertyBody {
  name?: string;
  description?: string | null;
  ai_on?: boolean;
  project?: string | null;
  kind?: PropertyKind;
  bhk?: number | null;
  price_min_paise?: number | null;
  price_max_paise?: number | null;
  size_text?: string | null;
  units_total?: number | null;
  units_left?: number | null;
  map_url?: string | null;
  rera_no?: string | null;
}

export interface SiteVisit {
  id: string;
  number: number | null;
  customer_name: string | null;
  phone: string | null;
  start_at: string;
  status: string;
}

export interface PropertyVisits {
  mine: SiteVisit[];
  others: SiteVisit[];
  service_ready: boolean;
  /** False when this person cannot open Bookings. */
  allowed: boolean;
}

const BASE = "/api/v1/properties";
const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });
const id = (value: string) => encodeURIComponent(value);

export const propertiesApi = {
  /** Should the catalogue show the Properties tab for this business? */
  /** Which catalogue tabs this business gets: Properties (real estate) and Courses (education). */
  availability: () =>
    apiFetch<{ enabled: boolean; courses_enabled?: boolean; business_type: string | null }>(`${BASE}/availability`),
  list: (q?: string) => apiFetch<{ data: Property[] }>(`${BASE}${q ? `?q=${encodeURIComponent(q)}` : ""}`).then((r) => r.data),
  get: (propertyId: string) => apiFetch<Property>(`${BASE}/${id(propertyId)}`),
  create: (body: PropertyBody) => apiFetch<Property>(BASE, json("POST", body)),
  update: (propertyId: string, body: PropertyBody) => apiFetch<Property>(`${BASE}/${id(propertyId)}`, json("PATCH", body)),
  remove: (propertyId: string) => apiFetch<{ deleted: boolean }>(`${BASE}/${id(propertyId)}`, json("DELETE")),
  visits: (propertyId: string) => apiFetch<PropertyVisits>(`${BASE}/${id(propertyId)}/visits`),
  attachVisit: (propertyId: string, bookingId: string) =>
    apiFetch<{ attached: boolean }>(`${BASE}/${id(propertyId)}/visits`, json("POST", { booking_id: bookingId })),
  detachVisit: (propertyId: string, bookingId: string) =>
    apiFetch<{ detached: boolean }>(`${BASE}/${id(propertyId)}/visits/${id(bookingId)}`, json("DELETE")),
};

// ── pure helpers ────────────────────────────────────────────────────────────

/** 450000000 paise -> "₹45 lakh", 12000000000 -> "₹12 crore", 8500000 -> "₹85,000". Empty string for null. */
export function formatPriceWords(paise: number | null | undefined): string {
  if (paise == null) return "";
  const rupees = paise / 100;
  for (const [unit, size] of [["crore", 10_000_000], ["lakh", 100_000]] as const) {
    if (rupees >= size) return `₹${Number((rupees / size).toFixed(2))} ${unit}`;
  }
  return `₹${Math.round(rupees).toLocaleString("en-IN")}`;
}

export function priceRangeText(low: number | null | undefined, high: number | null | undefined): string {
  if (low == null && high == null) return "";
  if (low == null || high == null || low === high) return formatPriceWords(low ?? high);
  return `${formatPriceWords(low)} to ${formatPriceWords(high)}`;
}

/** What an owner types -> paise. Accepts "4500000", "45,00,000", "45 lakh", "45L", "1.2 cr", "1.2 crore".
 *  Empty -> null. Anything else -> undefined (so the form can say "numbers only"). */
export function parseMoneyInput(text: string): number | null | undefined {
  const t = text.trim().toLowerCase().replace(/[₹,\s]/g, "");
  if (!t) return null;
  const m = /^(\d+(?:\.\d+)?)(lakhs?|lacs?|lac|l|crores?|cr|c)?$/.exec(t);
  if (!m) return undefined;
  const n = Number(m[1]);
  const unit = m[2] ?? "";
  const factor = unit.startsWith("c") ? 10_000_000 : unit.startsWith("l") ? 100_000 : 1;
  return Math.round(n * factor * 100);
}

/** Whole number or empty. Empty -> null, not a number -> undefined. */
export function parseWholeNumber(text: string): number | null | undefined {
  const t = text.trim();
  if (!t) return null;
  return /^\d+$/.test(t) ? Number(t) : undefined;
}

/** "3 BHK flat", "Villa", "Plot" — the short line under a property's name. */
export function kindLine(p: Pick<Property, "kind" | "bhk">): string {
  const kind = KIND_LABEL[p.kind] ?? "Property";
  return p.bhk ? `${p.bhk} BHK ${kind.toLowerCase()}` : kind;
}

/** "12 of 20 left", "Sold out", "Not counted". */
export function unitsText(left: number | null | undefined, total: number | null | undefined): string {
  if (left == null) return "Not counted";
  if (left === 0) return "Sold out";
  return total != null ? `${left} of ${total} left` : `${left} left`;
}
