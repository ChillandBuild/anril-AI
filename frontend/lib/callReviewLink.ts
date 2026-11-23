import { apiFetch } from "@/lib/api";

/** What the Call reviews page needs to open one call from a "Review call" link (?call=<id>). */
export interface CallToReview {
  id: string;
  lead_id: string | null;
  created_at: string;
}

const CALL_ID = /^[0-9a-fA-F-]{8,64}$/;

/** The call id from the ?call= value, or null when it is missing or not shaped like an id. */
export function callIdFromParam(value: string | null | undefined): string | null {
  const id = (value ?? "").trim();
  return CALL_ID.test(id) ? id : null;
}

/** The calendar day (YYYY-MM-DD, in the viewer's own time zone) a call happened on. null for a bad timestamp. */
export function localDayOf(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function fetchCallToReview(callId: string): Promise<CallToReview> {
  return apiFetch<CallToReview>(`/api/v1/calls/${encodeURIComponent(callId)}`);
}
