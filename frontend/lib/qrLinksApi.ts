import { apiFetch } from "@/lib/api";

// WhatsApp › QR & links. Backend: app/routes/qr_links.py.

export interface QrStats {
  opens: number;
  chats: number;
  new_customers: number;
  paid_orders: number;
  /** Only sent to people who can see money (deals.view). */
  paid_paise?: number;
}

export interface QrLink {
  id: string;
  code: string;
  name: string;
  first_message: string;
  place_id: string | null;
  place_name: string | null;
  archived: boolean;
  url: string;
  stats: QrStats;
}

export interface QrPlace {
  id: string;
  name: string;
}

export interface QrList {
  items: QrLink[];
  places: QrPlace[];
}

export interface QrInput {
  name: string;
  first_message: string;
  place_id?: string | null;
}

export const listQrLinks = () => apiFetch<QrList>("/api/v1/qr-links");

export const createQrLink = (body: QrInput) =>
  apiFetch<QrLink>("/api/v1/qr-links", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const updateQrLink = (id: string, body: Partial<QrInput> & { archived?: boolean }) =>
  apiFetch<QrLink>(`/api/v1/qr-links/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
