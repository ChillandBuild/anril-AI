import { apiFetch } from "@/lib/api";

/** v9.2 #23 the red "WhatsApp disconnected" banner, and #24 the error page's one-time report. */

export type WhatsAppConnection = { disconnected: boolean; numbers: { id: string; name: string }[] };

export const connectionStatusApi = {
  whatsapp: () => apiFetch<WhatsAppConnection>("/api/v1/connection-status/whatsapp"),
};

/** Banner words: names the number when only one is down, never shows a phone number. */
export function disconnectedMessage(c: WhatsAppConnection): string {
  if (!c.disconnected) return "";
  if (c.numbers.length === 1) return `${c.numbers[0].name} is disconnected, so customers' messages are not reaching you.`;
  return "Some of your WhatsApp numbers are disconnected, so customers' messages are not reaching you.";
}

/** Who sees the banner: the owner, or someone allowed to change settings (they can fix it). */
export function canReconnect(role: string | null | undefined, permissions: string[] | undefined): boolean {
  return role === "owner" || (permissions ?? []).includes("settings.manage");
}

const REPORTED_KEY = "anril_error_reported";

/**
 * Tell Anril support an error page was shown: the error code and the page path only (the server hides ids and
 * drops the query string). Once per browser session; any failure is ignored because the error page must still work.
 */
export function reportClientError(digest: string | undefined, path: string): void {
  try {
    if (sessionStorage.getItem(REPORTED_KEY)) return;
    sessionStorage.setItem(REPORTED_KEY, "1");
    void apiFetch("/api/v1/client-errors", { method: "POST", body: JSON.stringify({ digest: digest ?? null, path }) }).catch(() => {});
  } catch {
    /* storage blocked or offline: skip */
  }
}
