// Public booking page API. No login: the link's secret token is the key, so this uses plain
// fetch (NOT apiFetch, which attaches a Supabase session). Shapes follow the Bookings
// contract, "Public API" (backend/app/routes/bookings.py, public_router).

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://aira-ai-5tfr.onrender.com";

export interface PublicService {
  id: string;
  name: string;
  duration_min: number;
  price_paise: number | null;
  advance_paise: number | null;
}

export interface PublicResource {
  id: string;
  name: string;
  kind: string;
  service_ids: string[];
}

export interface PublicBookingInfo {
  business_name: string;
  services: PublicService[];
  resources: PublicResource[];
  rules: { days_ahead: number; cancel_cutoff_min: number };
  /** The business's main number, for "please call" lines. */
  business_phone?: string | null;
}

export interface PublicSlot {
  start_at: string;
  resource_id: string;
  resource_name: string;
}

export type BookingStatus = "held" | "booked" | "came" | "cancelled" | "no_show" | string;

export interface CreatedBooking {
  id: string;
  code: string;
  status: BookingStatus;
  start_at: string;
  service_name: string;
  resource_name: string;
  advance_paise: number;
  payment_url: string | null;
  hold_until: string | null;
  /** null when the business has no WhatsApp number yet. */
  whatsapp_url: string | null;
}

export interface PublicBookingStatus {
  code: string;
  status: BookingStatus;
  start_at: string;
  service_name: string;
  resource_name: string;
  advance_paise: number;
  advance_paid: boolean;
  payment_url: string | null;
  can_change: boolean;
  whatsapp_url: string | null;
  /** True once the customer has sent the booking code on WhatsApp (their number is confirmed). */
  phone_checked?: boolean;
  business_phone?: string | null;
  // Used when the server sends them (change-time and the countdown need them).
  service_id?: string;
  resource_id?: string;
  duration_min?: number;
  hold_until?: string | null;
}

export class PublicBookingError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail || `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
}

async function readDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    /* not JSON */
  }
  return "";
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/v1/public/bookings${path}`, {
      cache: "no-store",
      ...init,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new PublicBookingError(0, "");
  }
  if (!res.ok) throw new PublicBookingError(res.status, await readDetail(res));
  return res.json() as Promise<T>;
}

const enc = encodeURIComponent;

export function fetchBookingInfo(token: string): Promise<PublicBookingInfo> {
  return call(`/${enc(token)}`);
}

export async function fetchFreeDays(token: string, serviceId: string, resourceId: string): Promise<string[]> {
  const r = await call<{ dates?: string[] } | string[]>(
    `/${enc(token)}/days?service_id=${enc(serviceId)}&resource_id=${enc(resourceId)}`,
  );
  return Array.isArray(r) ? r : r.dates ?? [];
}

export async function fetchFreeTimes(
  token: string,
  serviceId: string,
  resourceId: string,
  date: string,
): Promise<PublicSlot[]> {
  const r = await call<{ times?: PublicSlot[] } | PublicSlot[]>(
    `/${enc(token)}/times?service_id=${enc(serviceId)}&resource_id=${enc(resourceId)}&date=${enc(date)}`,
  );
  return Array.isArray(r) ? r : r.times ?? [];
}

export function createBooking(
  token: string,
  body: { service_id: string; resource_id: string; start_at: string; phone: string; name: string },
): Promise<CreatedBooking> {
  return call(`/${enc(token)}`, { method: "POST", body: JSON.stringify(body) });
}

export function fetchBookingStatus(token: string, id: string): Promise<PublicBookingStatus> {
  return call(`/${enc(token)}/booking/${enc(id)}`);
}

export function cancelBooking(token: string, id: string): Promise<unknown> {
  return call(`/${enc(token)}/booking/${enc(id)}/cancel`, { method: "POST", body: "{}" });
}

export function moveBooking(
  token: string,
  id: string,
  body: { start_at: string; resource_id?: string },
): Promise<unknown> {
  return call(`/${enc(token)}/booking/${enc(id)}/move`, { method: "POST", body: JSON.stringify(body) });
}
