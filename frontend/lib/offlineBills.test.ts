import { beforeEach, describe, expect, it, vi } from "vitest";
import { dropBill, isConnectionError, newClientRef, offlineNote, queueBill, queuedBills, sendQueued, type QueuedBill } from "./offlineBills";

const store: Record<string, string> = {};
beforeEach(() => {
  for (const k of Object.keys(store)) delete store[k];
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = v; },
  });
  vi.stubGlobal("navigator", { onLine: true });
});

function bill(ref: string, extra: Partial<QueuedBill> = {}): QueuedBill {
  return {
    client_ref: ref, made_at: "2026-11-23T09:35:00Z", label: "Priya · ₹4,500",
    body: { client_ref: ref, mode: "now", items: [{ catalog_item_id: "i1", qty: 1 }], discount_paise: 0, bill_type: "gst", method: "cash" },
    ...extra,
  };
}

describe("offline bills (v9.2 #74)", () => {
  it("makes keys the server accepts", () => {
    const ref = newClientRef();
    expect(ref).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(newClientRef()).not.toBe(ref);
  });

  it("tells a dropped connection from the server saying no", () => {
    expect(isConnectionError(new Error("Cannot reach server — it may be restarting. Try again in 30 seconds."))).toBe(true);
    expect(isConnectionError(new Error("Request timed out"))).toBe(true);
    expect(isConnectionError(new TypeError("Failed to fetch"))).toBe(true);
    expect(isConnectionError(new Error("The advance can't be more than the total"))).toBe(false);
  });

  it("queues, replaces by key and drops", () => {
    queueBill(bill("bill-aaaaaaaa"));
    queueBill(bill("bill-aaaaaaaa", { label: "again" }));
    queueBill(bill("bill-bbbbbbbb"));
    expect(queuedBills().map((b) => b.label)).toEqual(["again", "Priya · ₹4,500"]); // replaced in place
    dropBill("bill-aaaaaaaa");
    expect(queuedBills().map((b) => b.client_ref)).toEqual(["bill-bbbbbbbb"]);
  });

  it("sends oldest first with the same key, stops when still offline, keeps refusals with their reason", async () => {
    queueBill(bill("bill-11111111"));
    queueBill(bill("bill-22222222"));
    queueBill(bill("bill-33333333"));
    const send = vi.fn()
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce(new Error("That GSTIN doesn't look right"))
      .mockRejectedValueOnce(new Error("Cannot reach server — it may be restarting."));
    const out = await sendQueued(send);
    expect(out).toEqual({ sent: 1, failed: 1, offline: true });
    expect(send.mock.calls[0][0].client_ref).toBe("bill-11111111");
    expect(send.mock.calls[0][0].notes).toMatch(/^Billed offline at /);
    const left = queuedBills();
    expect(left.map((b) => [b.client_ref, b.error ?? null])).toEqual([
      ["bill-22222222", "That GSTIN doesn't look right"], ["bill-33333333", null]]);
    // A refused bill is only retried when the owner taps Send on it.
    const send2 = vi.fn().mockResolvedValue({});
    expect(await sendQueued(send2)).toEqual({ sent: 1, failed: 0, offline: false });
    expect(send2.mock.calls.map((c) => c[0].client_ref)).toEqual(["bill-33333333"]);
    expect(await sendQueued(send2, "bill-22222222")).toEqual({ sent: 1, failed: 0, offline: false });
    expect(queuedBills()).toEqual([]);
  });

  it("keeps the shop's own note and adds when it was billed", () => {
    expect(offlineNote("2026-11-23T09:35:00Z", "Gift wrap")).toMatch(/^Gift wrap\nBilled offline at .+; sent when the internet was back\.$/);
  });
});
