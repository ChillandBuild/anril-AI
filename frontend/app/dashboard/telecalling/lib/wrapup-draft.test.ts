import { describe, expect, it } from "vitest";
import type { WrapupContext } from "@/lib/api";
import { applyContext, draftError, draftToPayload, emptyDraft, selectConnect, selectOutcome, setBooking, type WrapupDraft } from "./wrapup-draft";

const NOW = new Date("2026-09-27T08:30:00Z");
const LATER = "2026-09-27T12:30:00.000Z";
const CTX: WrapupContext = {
  connect_prefill: "not_picked",
  never_connected: false,
  failed_before: 0,
  retry_suggestions: { not_picked: "2026-09-27T10:30:00+00:00", busy: "2026-09-27T09:00:00+00:00", switched_off: "2026-09-28T04:30:00+00:00" },
};

function connected(outcome: WrapupDraft["outcome"], patch: Partial<WrapupDraft> = {}): WrapupDraft {
  return { ...selectOutcome(selectConnect(emptyDraft(), "connected", null), outcome!), ...patch };
}

describe("selecting", () => {
  it("fills the suggested retry for a call that didn't connect", () => {
    const d = selectConnect(emptyDraft(), "busy", CTX);
    expect(d).toMatchObject({ manualStatus: "busy", outcome: null, nextActionAt: CTX.retry_suggestions.busy });
  });

  it("clears the retry when switching to connected", () => {
    expect(selectConnect(selectConnect(emptyDraft(), "busy", CTX), "connected", CTX).nextActionAt).toBeNull();
  });

  it("clears reason and language when the result changes", () => {
    const d = selectOutcome(connected("not_interested", { reason: "price" }), "maybe_later");
    expect(d.reason).toBeNull();
  });

  it("applies the cloud pre-fill once, without overriding the telecaller", () => {
    expect(applyContext(emptyDraft(), CTX)).toMatchObject({ manualStatus: "not_picked", nextActionAt: CTX.retry_suggestions.not_picked });
    const mine = selectConnect(emptyDraft(), "connected", null);
    expect(applyContext(mine, CTX)).toBe(mine);
    const waiting = { ...emptyDraft(), manualStatus: "switched_off" as const, retrySuggested: true };
    expect(applyContext(waiting, CTX).nextActionAt).toBe(CTX.retry_suggestions.switched_off);
  });

  it("overwrites a still-suggested retry time when a later, more accurate context arrives (W4/W7)", () => {
    // Lead-only context (before the SIM call's log id is known): 1st failure, so "+2h".
    const first = selectConnect(emptyDraft(), "not_picked", CTX);
    expect(first.nextActionAt).toBe(CTX.retry_suggestions.not_picked);
    // The call-id-scoped re-fetch reveals this is actually the 3rd failure in a row.
    const laterCtx: WrapupContext = {
      ...CTX, failed_before: 2,
      retry_suggestions: { ...CTX.retry_suggestions, not_picked: "2026-09-28T04:30:00+00:00" },
    };
    expect(applyContext(first, laterCtx).nextActionAt).toBe(laterCtx.retry_suggestions.not_picked);
  });

  it("keeps a time the telecaller picked themselves, even if a fresher context arrives", () => {
    const picked: WrapupDraft = {
      ...selectConnect(emptyDraft(), "not_picked", CTX),
      nextActionAt: "2026-09-30T05:00:00.000Z",
      retrySuggested: false,
    };
    const laterCtx: WrapupContext = { ...CTX, retry_suggestions: { ...CTX.retry_suggestions, not_picked: "2026-09-29T00:00:00+00:00" } };
    expect(applyContext(picked, laterCtx)).toBe(picked);
  });

  it("never lets a never-connected lead be logged as Connected (W7)", () => {
    const neverConnectedCtx: WrapupContext = { ...CTX, never_connected: true, connect_prefill: null };
    const flipped = applyContext(selectConnect(emptyDraft(), "connected", null), neverConnectedCtx);
    expect(flipped.manualStatus).toBe("not_picked");
    expect(flipped.nextActionAt).toBe(neverConnectedCtx.retry_suggestions.not_picked);
  });
});

describe("validation mirrors the server", () => {
  it("walks the telecaller through the required fields", () => {
    expect(draftError(emptyDraft(), NOW)).toBe("Pick whether the call connected.");
    expect(draftError(selectConnect(emptyDraft(), "connected", null), NOW)).toBe("Pick what happened on the call.");
    expect(draftError(connected("interested_booked"), NOW)).toBe("Pick a date and time.");
    expect(draftError(connected("interested_booked", { nextActionAt: LATER }), NOW)).toBe("Add a short note for this result.");
    expect(draftError(connected("interested_booked", { nextActionAt: LATER, notes: "Demo Friday" }), NOW)).toBeNull();
    expect(draftError(connected("not_interested"), NOW)).toBe("Pick why they're not interested.");
    expect(draftError(connected("disqualified"), NOW)).toBe("Pick why the lead is disqualified.");
    expect(draftError(connected("language_barrier"), NOW)).toBe("Pick the language the customer speaks.");
    expect(draftError(connected("converted", { notes: "paid" }), NOW)).toBe("Add the products sold.");
    expect(draftError(connected("converted", { notes: "paid", saleMode: "amount", amountRupees: "0" }), NOW)).toBe("Enter the sale amount.");
    expect(draftError(connected("maybe_later"), NOW)).toBeNull();
  });

  it("rejects past times", () => {
    expect(draftError(connected("call_later", { nextActionAt: "2026-09-27T08:00:00Z" }), NOW)).toBe("Pick a time in the future.");
  });

  it("blocks Save for Connected on a never-connected call, even before the draft is auto-flipped (W7)", () => {
    expect(draftError(connected("maybe_later"), NOW, true)).toBe("The call record shows nobody answered.");
    expect(draftError(connected("maybe_later"), NOW, false)).toBeNull();
  });
});

describe("payload", () => {
  it("sends products or an amount for a sale, never both", () => {
    const products = connected("converted", {
      notes: " paid ",
      products: [{ catalogItemId: "i1", name: "Pen", qty: 2, pricePaise: 5000 }],
      amountRupees: "900",
    });
    expect(draftToPayload(products)).toMatchObject({
      manual_status: "connected", outcome: "converted", notes: "paid",
      products: [{ catalog_item_id: "i1", qty: 2 }], amount_paise: null,
    });
    const amount = { ...products, saleMode: "amount" as const, amountRupees: "1,499.50" };
    expect(draftToPayload(amount)).toMatchObject({ products: [], amount_paise: 149950 });
  });

  it("sends stop_messages only for do-not-call", () => {
    expect(draftToPayload(connected("do_not_call", { stopMessages: true })).stop_messages).toBe(true);
    expect(draftToPayload(connected("maybe_later", { stopMessages: true })).stop_messages).toBe(false);
  });

  it("never sends a result for a call that didn't connect", () => {
    expect(draftToPayload(selectConnect(emptyDraft(), "busy", CTX))).toMatchObject({ manual_status: "busy", outcome: null });
  });

  it("sends no explicit time while the retry time is still just a suggestion (W7)", () => {
    const suggested = selectConnect(emptyDraft(), "busy", CTX);
    expect(suggested.retrySuggested).toBe(true);
    expect(draftToPayload(suggested).next_action_at).toBeNull();
  });

  it("sends the exact time once the telecaller has picked it themselves", () => {
    const picked = { ...selectConnect(emptyDraft(), "busy", CTX), nextActionAt: "2026-09-30T05:00:00.000Z", retrySuggested: false };
    expect(draftToPayload(picked).next_action_at).toBe("2026-09-30T05:00:00.000Z");
  });
});

describe("visit booking on Interested, next step booked", () => {
  const VISIT = { serviceId: "svc-1", startAt: "2026-09-28T05:30:00.000Z", label: "Haircut, Tomorrow 11:00 AM" };

  it("the visit time is the next-step time, so no second time needs picking", () => {
    const d = setBooking(connected("interested_booked", { notes: "Coming in" }), VISIT);
    expect(d.nextActionAt).toBe(VISIT.startAt);
    expect(draftError(d, NOW)).toBeNull();
    expect(draftToPayload(d).booking).toEqual({ service_id: "svc-1", resource_id: "any", start_at: VISIT.startAt });
    expect(draftToPayload(d).next_action_at).toBe(VISIT.startAt);
  });

  it("sends no booking when none was picked, or for any other result", () => {
    expect(draftToPayload(connected("interested_booked", { notes: "x", nextActionAt: LATER })).booking).toBeNull();
    const other = selectOutcome(setBooking(connected("interested_booked"), VISIT), "maybe_later");
    expect(other.booking).toBeNull();
    expect(draftToPayload({ ...connected("maybe_later"), booking: VISIT }).booking).toBeNull();
  });

  it("clearing the booking clears the time, and changing the connect answer drops it", () => {
    const d = setBooking(setBooking(connected("interested_booked"), VISIT), null);
    expect(d.booking).toBeNull();
    expect(d.nextActionAt).toBeNull();
    expect(selectConnect(setBooking(connected("interested_booked"), VISIT), "busy", CTX).booking).toBeNull();
  });
});
