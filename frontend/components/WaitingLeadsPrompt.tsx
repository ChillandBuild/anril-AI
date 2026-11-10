"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Users } from "lucide-react";
import { toast } from "sonner";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { usePolling } from "@/hooks/usePolling";

type OfferState =
  | { state: "none" }
  | { state: "invited"; offer_id: string; lead_count: number }
  | { state: "accepted"; offer_id: string; lead_count: number; seconds_left: number };

const POLL_MS = 20000;

function formatCountdown(totalSeconds: number) {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/**
 * Shows the "leads are waiting" offer to a telecaller who is not on shift.
 * Renders nothing for owners, or for telecallers with no open offer.
 */
export function WaitingLeadsPrompt() {
  const { role, callerId } = useAuthRole();
  const enabled = role === "caller" && !!callerId;

  const [offer, setOffer] = useState<OfferState>({ state: "none" });
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set());
  const [busy, setBusy] = useState(false);
  const prevStateRef = useRef<OfferState["state"]>("none");

  const applyState = useCallback((next: OfferState) => {
    if (prevStateRef.current === "accepted" && next.state === "none") {
      toast.success("Waiting leads added to your list");
    }
    prevStateRef.current = next.state;
    setOffer(next);
    if (next.state === "accepted") setSecondsLeft(next.seconds_left);
  }, []);

  const fetchCurrent = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/v1/assignment-offers/current`, { headers: await getAuthHeaders() });
      if (!res.ok) return;
      applyState((await res.json()) as OfferState);
    } catch {
      // Transient network failure: keep the last known state and try again on the next poll.
    }
  }, [applyState]);

  useEffect(() => {
    if (enabled) fetchCurrent();
  }, [enabled, fetchCurrent]);

  usePolling(fetchCurrent, POLL_MS, enabled);

  // Count down locally between polls. Each poll re-syncs secondsLeft.
  useEffect(() => {
    if (offer.state !== "accepted") return;
    const id = setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, [offer.state]);

  // Window over: ask the server now (it hands the leads out on this read) instead of waiting for the next poll.
  const windowOver = offer.state === "accepted" && secondsLeft === 0;
  useEffect(() => {
    if (!windowOver) return;
    const id = setTimeout(() => void fetchCurrent(), 1500);
    return () => clearTimeout(id);
  }, [windowOver, fetchCurrent]);

  if (!enabled) return null;

  const hideOffer = (offerId: string) => {
    setDismissed((prev) => new Set(prev).add(offerId));
  };

  const respond = async (offerId: string, accept: boolean) => {
    setBusy(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/assignment-offers/${offerId}/respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await getAuthHeaders()) },
        body: JSON.stringify({ accept }),
      });
      if (res.status === 409) {
        hideOffer(offerId);
        applyState({ state: "none" });
        toast.info("These leads are no longer waiting");
        return;
      }
      if (!res.ok) throw new Error("Respond failed");
      applyState((await res.json()) as OfferState);
    } catch {
      toast.error("Could not send your answer. Try again.");
    } finally {
      setBusy(false);
    }
  };

  if (offer.state === "invited") {
    if (dismissed.has(offer.offer_id)) return null;
    const n = offer.lead_count;
    const offerId = offer.offer_id;
    return (
      <div
        role="alertdialog"
        aria-label="Leads waiting"
        className="fixed bottom-4 right-4 z-50 w-[360px] max-w-[calc(100vw-32px)] rounded-2xl border border-border bg-white p-5 shadow-[0_12px_32px_rgba(10,21,40,0.12)]"
      >
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary-light text-primary">
            <Users size={18} />
          </div>
          <div className="min-w-0">
            <p className="font-display text-sm font-bold text-ink">
              {n === 1 ? "1 lead is waiting for a telecaller" : `${n} leads are waiting for a telecaller`}
            </p>
            <p className="mt-1 font-body text-xs text-ink-muted leading-relaxed">
              Nobody is on shift right now. Do you want to take them? If another telecaller also says yes within 2 minutes, the leads are split between you.
            </p>
          </div>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              hideOffer(offerId);
              void respond(offerId, false);
            }}
            className="rounded-xl border border-border bg-white px-4 py-2 font-label text-xs font-bold text-ink transition-colors hover:bg-surface-subtle disabled:opacity-50"
          >
            Not now
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void respond(offerId, true)}
            className="rounded-xl bg-primary px-4 py-2 font-label text-xs font-bold text-white transition-colors hover:bg-primary-dark disabled:opacity-50"
          >
            {n === 1 ? "Take 1 lead" : `Take ${n} leads`}
          </button>
        </div>
      </div>
    );
  }

  if (offer.state === "accepted") {
    return (
      <div
        role="status"
        aria-live="polite"
        className="fixed bottom-4 right-4 z-50 w-[300px] max-w-[calc(100vw-32px)] rounded-2xl border border-border bg-white p-4 shadow-[0_12px_32px_rgba(10,21,40,0.12)]"
      >
        <p className="font-body text-sm text-ink">
          You&apos;re in. Handing out the leads in {formatCountdown(secondsLeft)}&hellip;
        </p>
      </div>
    );
  }

  return null;
}
