/** The wrap-up form's state and rules, kept pure so they are unit-tested and mirror the server. */
import type { CallConnect, CallResult, OutcomeReason, PreferredLanguage, WrapupContext, WrapupPayload } from "@/lib/api";
import { resultOption } from "@/lib/call-wrapup";

export interface SaleLine {
  catalogItemId: string;
  name: string;
  qty: number;
  pricePaise: number | null;
}

export interface WrapupDraft {
  manualStatus: CallConnect | null;
  outcome: CallResult | null;
  notes: string;
  nextActionAt: string | null;
  /** True while `nextActionAt` is still a suggestion (from selectConnect/applyContext), not a
   * time the telecaller chose themselves. A fresh context is free to overwrite it while true;
   * the picker clears it the moment the telecaller touches the time. */
  retrySuggested: boolean;
  reason: OutcomeReason | null;
  preferredLanguage: PreferredLanguage | null;
  stopMessages: boolean;
  saleMode: "products" | "amount";
  products: SaleLine[];
  amountRupees: string;
  /** "Next step booked": a real booking to make when the wrap-up is saved (only when Bookings is set up). */
  booking: DraftBooking | null;
}

export interface DraftBooking {
  serviceId: string;
  /** The visit time (ISO). Also the next-step time of the wrap-up. */
  startAt: string;
  /** "Haircut, Tomorrow 11:00 AM": what the telecaller sees after picking. */
  label: string;
}

const PAST_TOLERANCE_MS = 5 * 60_000;
const MAX_NOTES_LENGTH = 2000;
const MAX_PRODUCTS = 20;
const MAX_AMOUNT_PAISE = 10_000_000_000;

export function emptyDraft(): WrapupDraft {
  return {
    manualStatus: null, outcome: null, notes: "", nextActionAt: null, retrySuggested: false, reason: null,
    preferredLanguage: null, stopMessages: false, saleMode: "products", products: [], amountRupees: "",
    booking: null,
  };
}

export function selectConnect(draft: WrapupDraft, value: CallConnect, context: WrapupContext | null): WrapupDraft {
  if (value === "connected") return { ...draft, manualStatus: value, nextActionAt: null, retrySuggested: false };
  return {
    ...draft, manualStatus: value, outcome: null, reason: null, preferredLanguage: null, stopMessages: false,
    nextActionAt: context?.retry_suggestions[value] ?? null, retrySuggested: true, booking: null,
  };
}

export function selectOutcome(draft: WrapupDraft, value: CallResult): WrapupDraft {
  return {
    ...draft, outcome: value, reason: null, preferredLanguage: null, stopMessages: false,
    nextActionAt: resultOption(value).time ? draft.nextActionAt : null,
    booking: value === "interested_booked" ? draft.booking : null,
  };
}

/** Pick (or clear) the visit to book. The visit time doubles as the wrap-up's next-step time. */
export function setBooking(draft: WrapupDraft, booking: DraftBooking | null): WrapupDraft {
  return { ...draft, booking, nextActionAt: booking ? booking.startAt : null, retrySuggested: false };
}

/**
 * The cloud pre-fill and retry suggestion arrive after the form opens (and again, for a SIM call,
 * once its call-log id is known and the streak count is accurate — W4). Never override a time the
 * telecaller picked themselves, but a still-suggested time tracks the latest context so a stale
 * "+2h" from a lead-only fetch doesn't survive past the call-id-scoped re-fetch.
 */
export function applyContext(draft: WrapupDraft, context: WrapupContext): WrapupDraft {
  if (!draft.manualStatus) {
    return context.connect_prefill ? selectConnect(draft, context.connect_prefill, context) : draft;
  }
  // The call record says nobody ever answered: Connected can never be true for this lead (W7).
  if (context.never_connected && draft.manualStatus === "connected") {
    return selectConnect(draft, context.connect_prefill ?? "not_picked", context);
  }
  if (draft.manualStatus !== "connected" && draft.retrySuggested) {
    return { ...draft, nextActionAt: context.retry_suggestions[draft.manualStatus] };
  }
  return draft;
}

export function amountPaise(rupees: string): number | null {
  const value = Number(rupees.replace(/,/g, "").trim());
  if (!Number.isFinite(value) || value < 1) return null;
  const paise = Math.round(value * 100);
  return paise <= MAX_AMOUNT_PAISE ? paise : null;
}

function futureError(iso: string, now: Date): string | null {
  return new Date(iso).getTime() < now.getTime() - PAST_TOLERANCE_MS ? "Pick a time in the future." : null;
}

/** `neverConnected` mirrors the call record (W7): Connected can never be saved for it, even if
 * the draft hasn't been auto-flipped away from it yet (e.g. the context fetch is still in flight). */
export function draftError(draft: WrapupDraft, now: Date, neverConnected = false): string | null {
  if (!draft.manualStatus) return "Pick whether the call connected.";
  if (draft.manualStatus === "connected" && neverConnected) return "The call record shows nobody answered.";
  if (draft.manualStatus !== "connected") {
    return draft.nextActionAt ? futureError(draft.nextActionAt, now) : "Pick when to try again.";
  }
  if (!draft.outcome) return "Pick what happened on the call.";
  const option = resultOption(draft.outcome);
  if (option.time === "required" && !draft.nextActionAt) return "Pick a date and time.";
  if (option.time && draft.nextActionAt) {
    const past = futureError(draft.nextActionAt, now);
    if (past) return past;
  }
  if (draft.outcome === "not_interested" && !draft.reason) return "Pick why they're not interested.";
  if (draft.outcome === "disqualified" && !draft.reason) return "Pick why the lead is disqualified.";
  if (draft.outcome === "language_barrier" && !draft.preferredLanguage) return "Pick the language the customer speaks.";
  if (draft.outcome === "converted") {
    if (draft.saleMode === "products" && draft.products.length === 0) return "Add the products sold.";
    if (draft.saleMode === "products" && draft.products.length > MAX_PRODUCTS) return `Remove some products — ${MAX_PRODUCTS} is the most you can add.`;
    if (draft.saleMode === "amount" && amountPaise(draft.amountRupees) === null) return "Enter the sale amount.";
  }
  if (draft.notes.length > MAX_NOTES_LENGTH) return "Notes are too long — keep it under 2,000 characters.";
  if (option.notes && !draft.notes.trim()) return "Add a short note for this result.";
  return null;
}

export function draftToPayload(draft: WrapupDraft): WrapupPayload {
  const connected = draft.manualStatus === "connected";
  const sale = connected && draft.outcome === "converted";
  return {
    manual_status: draft.manualStatus as CallConnect,
    outcome: connected ? draft.outcome : null,
    notes: draft.notes.trim() || null,
    // Still just a suggestion: send nothing so the server computes the streak-aware time itself
    // from the freshest data, instead of freezing in whatever this client last saw (W7).
    next_action_at: draft.retrySuggested ? null : draft.nextActionAt,
    reason: draft.reason,
    preferred_language: draft.preferredLanguage,
    stop_messages: connected && draft.outcome === "do_not_call" && draft.stopMessages,
    products: sale && draft.saleMode === "products"
      ? draft.products.map((p) => ({ catalog_item_id: p.catalogItemId, qty: p.qty }))
      : [],
    amount_paise: sale && draft.saleMode === "amount" ? amountPaise(draft.amountRupees) : null,
    booking: connected && draft.outcome === "interested_booked" && draft.booking
      ? { service_id: draft.booking.serviceId, resource_id: "any", start_at: draft.booking.startAt }
      : null,
  };
}
