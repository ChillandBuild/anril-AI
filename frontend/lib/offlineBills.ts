// v9.2 #74: bills made while the internet is down wait on this device and go out when it is back.
// Each bill carries a "send once" key (client_ref): if a try did reach the server before the connection
// dropped, sending it again returns that same bill instead of making a second one.
import type { NewBillInput } from "@/lib/api";

export type QueuedBill = {
  client_ref: string;
  body: NewBillInput & { client_ref: string };
  made_at: string; // ISO time it was billed on the device
  label: string; // "Priya · ₹4,500" for the waiting list
  error?: string; // the server refused it (not a connection problem): shown, never retried on its own
};

const KEY = "anril_offline_bills_v1";

function read(): QueuedBill[] {
  try {
    const raw = localStorage.getItem(KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.filter((b) => b && typeof b.client_ref === "string" && b.body) : [];
  } catch {
    return [];
  }
}

function write(list: QueuedBill[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    /* storage full or blocked: the bill stays on screen with its error */
  }
  try {
    window.dispatchEvent(new Event("anril-offline-bills"));
  } catch {
    /* not in a browser */
  }
}

export function newClientRef(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return `bill-${c.randomUUID()}`;
  return `bill-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/** A connection problem (worth saving and retrying), as opposed to the server saying no. */
export function isConnectionError(e: unknown): boolean {
  if (typeof navigator !== "undefined" && navigator.onLine === false) return true;
  const msg = e instanceof Error ? e.message : String(e ?? "");
  return e instanceof TypeError || /cannot reach server|timed out|failed to fetch|network ?error|load failed/i.test(msg);
}

export function queuedBills(): QueuedBill[] {
  return read();
}

export function queueBill(bill: QueuedBill): void {
  const list = read();
  const at = list.findIndex((b) => b.client_ref === bill.client_ref);
  if (at >= 0) list[at] = bill; // keep its place in line
  else list.push(bill);
  write(list);
}

export function dropBill(clientRef: string): void {
  write(read().filter((b) => b.client_ref !== clientRef));
}

/** "Billed offline at 23 Nov, 3:05 pm" — kept on the bill so the time it was really made is not lost. */
export function offlineNote(madeAt: string, existing?: string): string {
  const d = new Date(madeAt);
  const when = Number.isNaN(d.getTime())
    ? madeAt
    : d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true });
  const line = `Billed offline at ${when}; sent when the internet was back.`;
  return existing?.trim() ? `${existing.trim()}\n${line}` : line;
}

/**
 * Send every waiting bill once, oldest first. Stops at the first connection problem (still offline).
 * A bill the server refuses keeps its plain-words reason and is not retried until the owner taps Send again.
 */
export async function sendQueued(
  send: (body: QueuedBill["body"]) => Promise<unknown>,
  only?: string,
): Promise<{ sent: number; failed: number; offline: boolean }> {
  let sent = 0;
  let failed = 0;
  for (const bill of read()) {
    if (only ? bill.client_ref !== only : Boolean(bill.error)) continue;
    try {
      await send({ ...bill.body, notes: offlineNote(bill.made_at, bill.body.notes) });
      dropBill(bill.client_ref);
      sent++;
    } catch (e) {
      if (isConnectionError(e)) return { sent, failed, offline: true };
      failed++;
      queueBill({ ...bill, error: e instanceof Error ? e.message : "The bill could not be saved" });
    }
  }
  return { sent, failed, offline: false };
}
