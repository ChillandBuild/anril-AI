import { API_URL, apiFetch, getAuthHeaders } from "@/lib/api";

/** Bookings (staff side). Every call is /api/v1/bookings/...; shapes follow the Bookings API contract. */

export type BookingStatus = "held" | "booked" | "came" | "no_show" | "cancelled";
export type BookingSource = "link" | "chat" | "phone" | "walk_in" | "ai";
export type ResourceKind = "person" | "chair" | "room";

/** {"0".."6": [["10:00","13:00"],["16:00","20:00"]]}, 0 = Monday. A missing or empty day = day off. */
export type HoursBlock = [string, string];
export type WeekHours = Record<string, HoursBlock[]>;

export interface BookingSettings {
  link_on: boolean;
  days_ahead: number;
  min_notice_min: number;
  cancel_cutoff_min: number;
  one_per_day: boolean;
  no_show_limit: number;
}

export interface BookingService {
  id: string;
  name: string;
  duration_min: number;
  /** Money is left out for people without orders access. */
  price_paise?: number;
  advance_paise?: number;
  gap_after_min: number;
  active: boolean;
  resource_ids: string[];
}

export interface BookingResource {
  id: string;
  name: string;
  kind: ResourceKind;
  user_id: string | null;
  hours: WeekHours;
  active: boolean;
  sort: number;
  service_ids: string[];
}

export interface BookingLeave {
  id: string;
  resource_id: string;
  from_date: string;
  to_date: string;
  note: string | null;
}

export type TemplateState = "APPROVED" | "PENDING" | "REJECTED" | string;

export interface BookingSetup {
  settings: BookingSettings;
  /** Null when the person may not see the link (only managers do). */
  link_url: string | null;
  services: BookingService[];
  resources: BookingResource[];
  leave: BookingLeave[];
  /** has_view: false = this person's role cannot open Bookings yet. */
  team: { user_id: string; name: string; has_view?: boolean }[];
  my_resource_id: string | null;
  can_manage: boolean;
  templates: { update: TemplateState | null; reminder: TemplateState | null };
}

export interface Booking {
  id: string;
  number: number;
  code: string;
  status: BookingStatus;
  source: BookingSource;
  start_at: string;
  end_at: string;
  block_end_at: string;
  service_id: string;
  service_name: string;
  resource_id: string;
  customer_name: string | null;
  phone: string;
  lead_id: string | null;
  phone_checked: boolean;
  advance_paise?: number;
  /** True when this booking has an advance to pay; sent even when the amount is hidden. */
  advance_needed?: boolean;
  advance_paid: boolean;
  deal_id: string | null;
  confirmed_at: string | null;
  call_now: boolean;
  note: string | null;
  /** Set when the advance-payment link could not be sent. */
  advance_error?: string | null;
  /** Site visits only: how the visit went (set after Came). */
  visit_outcome?: VisitOutcome | null;
  /** Site visits: where to pick the buyer up. */
  pickup?: string | null;
}

/** Bookings > Site visits row. */
export type SiteVisit = Booking & { property_name: string | null; shown_by: string | null; segment: string | null };

export type VisitOutcome = "liked_thinking" | "ready_to_book" | "not_interested" | "token_paid";

export type FreeRanges = Record<string, [string, string][]>;

export interface DayView {
  date: string;
  resources: BookingResource[];
  bookings: Booking[];
  free: FreeRanges;
}

export interface WeekView {
  start: string;
  days: { date: string; bookings: Booking[] }[];
  resources: BookingResource[];
}

export interface FreeTime {
  start_at: string;
  resource_id: string;
  resource_name: string;
}

export interface BookingHistory {
  bookings_count: number;
  no_shows: number;
  advance_needed: boolean;
}

export interface NewBookingBody {
  service_id: string;
  resource_id: string | "any";
  start_at: string;
  phone: string;
  customer_name?: string;
  lead_id?: string;
  source: "phone" | "walk_in" | "chat";
  note?: string;
  send_advance_link: boolean;
}

export interface ServiceBody {
  name: string;
  duration_min: number;
  price_paise?: number;
  advance_paise?: number;
  gap_after_min: number;
  resource_ids: string[];
  active: boolean;
}

export interface ResourceBody {
  name: string;
  kind: ResourceKind;
  user_id: string | null;
  hours: WeekHours;
  active: boolean;
  sort: number;
  service_ids: string[];
}

const BASE = "/api/v1/bookings";
const q = (params: Record<string, string | undefined>) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") u.set(k, v);
  const s = u.toString();
  return s ? `?${s}` : "";
};
const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export const bookingsApi = {
  setup: () => apiFetch<BookingSetup>(`${BASE}/setup`),
  saveSettings: (body: BookingSettings) => apiFetch<{ settings: BookingSettings }>(`${BASE}/settings`, json("PUT", body)),
  /** The old link stops working. */
  newLink: () => apiFetch<{ link_url: string }>(`${BASE}/settings/new-link`, json("POST")),
  /** Planner adds this route; it submits the two WhatsApp message templates. */
  setupTemplates: () => apiFetch<unknown>(`${BASE}/templates/setup`, json("POST")),

  createService: (body: ServiceBody) => apiFetch<BookingService>(`${BASE}/services`, json("POST", body)),
  updateService: (id: string, body: Partial<ServiceBody>) => apiFetch<BookingService>(`${BASE}/services/${encodeURIComponent(id)}`, json("PATCH", body)),
  /** Soft delete: the service stops being offered; old bookings keep it. */
  removeService: (id: string) => apiFetch<unknown>(`${BASE}/services/${encodeURIComponent(id)}`, json("DELETE")),

  createResource: (body: ResourceBody) => apiFetch<BookingResource>(`${BASE}/resources`, json("POST", body)),
  updateResource: (id: string, body: Partial<ResourceBody>) => apiFetch<BookingResource>(`${BASE}/resources/${encodeURIComponent(id)}`, json("PATCH", body)),
  removeResource: (id: string) => apiFetch<unknown>(`${BASE}/resources/${encodeURIComponent(id)}`, json("DELETE")),
  addLeave: (resourceId: string, body: { from_date: string; to_date: string; note?: string }) =>
    apiFetch<BookingLeave>(`${BASE}/resources/${encodeURIComponent(resourceId)}/leave`, json("POST", body)),
  removeLeave: (id: string) => apiFetch<unknown>(`${BASE}/leave/${encodeURIComponent(id)}`, json("DELETE")),

  day: (date: string) => apiFetch<DayView>(`${BASE}/day${q({ date })}`),
  week: (start: string) => apiFetch<WeekView>(`${BASE}/week${q({ start })}`),
  /** excludeBookingId: when moving, the booking's own time counts as free. */
  free: (serviceId: string, resourceId: string, date: string, excludeBookingId?: string) =>
    apiFetch<{ times: FreeTime[] }>(`${BASE}/free${q({ service_id: serviceId, resource_id: resourceId, date, exclude_booking_id: excludeBookingId })}`),
  freeDays: (serviceId: string, resourceId: string, excludeBookingId?: string) =>
    apiFetch<{ dates: string[] }>(`${BASE}/free-days${q({ service_id: serviceId, resource_id: resourceId, exclude_booking_id: excludeBookingId })}`),
  history: (phone: string) => apiFetch<BookingHistory>(`${BASE}/history${q({ phone })}`),

  create: (body: NewBookingBody) => apiFetch<Booking>(BASE, json("POST", body)),
  move: (id: string, body: { start_at: string; resource_id?: string }) =>
    apiFetch<Booking>(`${BASE}/${encodeURIComponent(id)}/move`, json("POST", body)),
  cancel: (id: string, reason?: string) =>
    apiFetch<Booking>(`${BASE}/${encodeURIComponent(id)}/cancel`, json("POST", { reason: reason || undefined })),
  came: (id: string) => apiFetch<{ deal_id: string | null; href: string | null; order_error?: string | null }>(`${BASE}/${encodeURIComponent(id)}/came`, json("POST")),
  visitOutcome: (id: string, outcome: VisitOutcome) =>
    apiFetch<{ visit_outcome: VisitOutcome; loan_followup_due_at: string | null }>(`${BASE}/${encodeURIComponent(id)}/visit-outcome`, json("POST", { outcome })),
  noShow: (id: string) => apiFetch<Booking>(`${BASE}/${encodeURIComponent(id)}/no-show`, json("POST")),
  siteVisits: () => apiFetch<{ data: SiteVisit[]; service_ready: boolean }>(`${BASE}/site-visits`),
  setPickup: (id: string, pickup: string) =>
    apiFetch<{ pickup: string | null }>(`${BASE}/${encodeURIComponent(id)}/pickup`, json("PATCH", { pickup })),
  /** Didn't come, what next? > "we missed you, pick another time" on WhatsApp (inside the 24-hour window). */
  rebookMessage: (id: string) =>
    apiFetch<{ sent: boolean; reason: string }>(`${BASE}/${encodeURIComponent(id)}/rebook-message`, json("POST")),
  /** The list for one day (end left out) or a week, as a file. Needs "Download lists". */
  exportCsv: async (start: string, end?: string) => {
    const res = await fetch(`${API_URL}${BASE}/export${q({ start, end })}`, { headers: await getAuthHeaders() });
    if (!res.ok) throw new Error(res.status === 403 ? "You don't have permission to download lists." : "Could not prepare the download. Try again.");
    const url = window.URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = `bookings_${start}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  },
};
