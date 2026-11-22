import { apiFetch } from "@/lib/api";
import type { BellAlert } from "@/components/bell/alertKinds";

/** Unread alerts plus anything from the last 7 days (read ones too), newest first, max 100. */
export function fetchBellAlerts(): Promise<BellAlert[]> {
  return apiFetch<{ data: BellAlert[] }>("/api/v1/notifications?include_read=true").then((r) => r.data || []);
}
