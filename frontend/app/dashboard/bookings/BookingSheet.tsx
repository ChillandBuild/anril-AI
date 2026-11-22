"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { MessageCircle, Phone } from "lucide-react";
import { toast } from "sonner";
import { bookingsApi, type Booking, type BookingResource } from "@/lib/bookingsApi";
import { FLAG_CLASS, STATUS_CLASS, STATUS_LABEL, bookingFlags, canMarkNoShow, canMarkVisit, customerLabel, isOpen } from "./bookingsLogic";
import { formatDateTime } from "./bookingsTime";
import { SlotPicker, type PickedSlot } from "./SlotPicker";
import { BTN_DANGER, BTN_PRIMARY, BTN_SECONDARY, ConfirmSheet, Field, INPUT_CLS, Sheet, errorText } from "./bookingsUi";
import { cn } from "@/lib/utils";

type Mode = "view" | "move" | "cancel" | "no_show";

/** One booking: what it is, the flags, and Came / Didn't come / Move / Cancel / Open chat. */
export function BookingSheet({
  booking,
  resources,
  canManage,
  myResourceId,
  canSeeMoney,
  initialMode = "view",
  onClose,
  onChanged,
}: {
  booking: Booking;
  resources: BookingResource[];
  canManage: boolean;
  myResourceId: string | null;
  canSeeMoney: boolean;
  initialMode?: Mode;
  onClose: () => void;
  onChanged: () => void;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [picked, setPicked] = useState<PickedSlot | null>(null);
  const [confirmMove, setConfirmMove] = useState(false);

  const column = resources.find((r) => r.id === booking.resource_id)?.name ?? "";
  const who = customerLabel(booking);
  const flags = bookingFlags(booking);
  const firstName = who.split(/\s+/)[0];
  const who2 = { canManage, myResourceId };
  const canVisit = canMarkVisit(booking, who2);
  const canNoShow = canMarkNoShow(booking, who2);
  const open = isOpen(booking.status);

  async function run(fn: () => Promise<unknown>, done: string, after?: () => void) {
    setBusy(true);
    try {
      await fn();
      toast.success(done);
      onChanged();
      if (after) after();
      else onClose();
    } catch (err) {
      toast.error(errorText(err));
      setBusy(false);
      return;
    }
    setBusy(false);
  }

  async function came() {
    setBusy(true);
    try {
      const res = await bookingsApi.came(booking.id);
      onChanged();
      if (res.order_error) {
        // It is marked as came, but the order could not be made. Stay here so the reason is not lost.
        toast.warning(res.order_error, { duration: 10000 });
        setBusy(false);
        return;
      }
      // Only people who may see money are taken to the order.
      if (canSeeMoney && res.href && res.href.startsWith("/dashboard/")) {
        router.push(res.href);
        return;
      }
      toast.success("Marked as came");
      onClose();
    } catch (err) {
      toast.error(errorText(err));
      setBusy(false);
    }
  }

  if (mode === "no_show") {
    return (
      <ConfirmSheet
        title="Mark as didn't come?"
        body={`${who} will be counted as not coming for ${formatDateTime(booking.start_at)}. Too many of these and they are asked for an advance next time.`}
        confirmLabel="Didn't come"
        tone="danger"
        busy={busy}
        onClose={() => setMode("view")}
        onConfirm={() => void run(() => bookingsApi.noShow(booking.id), "Marked as didn't come")}
      />
    );
  }

  if (mode === "cancel") {
    return (
      <Sheet
        title="Cancel this booking?"
        onClose={() => setMode("view")}
        labelId="cancel-title"
        footer={
          <>
            <button type="button" className={BTN_SECONDARY} onClick={() => setMode("view")} disabled={busy}>
              Keep it
            </button>
            <button type="button" className={BTN_DANGER} disabled={busy} onClick={() => void run(() => bookingsApi.cancel(booking.id, reason.trim()), "Booking cancelled")}>
              {busy ? "Working…" : "Cancel booking"}
            </button>
          </>
        }
      >
        <p className="mb-3 text-sm text-ink-secondary">{firstName} gets a WhatsApp saying the booking for {formatDateTime(booking.start_at)} is cancelled.</p>
        <Field label="Reason (optional)" htmlFor="cancel-reason">
          <input id="cancel-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} className={INPUT_CLS} />
        </Field>
      </Sheet>
    );
  }

  if (mode === "move") {
    return (
      <>
        <Sheet
          title={`Move ${who}`}
          wide
          onClose={() => setMode("view")}
          labelId="move-title"
          footer={
            <>
              <button type="button" className={BTN_SECONDARY} onClick={() => setMode("view")} disabled={busy}>
                Back
              </button>
              <button type="button" className={BTN_PRIMARY} disabled={!picked || busy} onClick={() => setConfirmMove(true)}>
                Move to this time
              </button>
            </>
          }
        >
          <p className="mb-3 text-sm text-ink-secondary">
            Now: {formatDateTime(booking.start_at)} · {booking.service_name}
            {column ? ` · ${column}` : ""}
          </p>
          <SlotPicker serviceId={booking.service_id} resourceId={booking.resource_id} value={picked} onChange={setPicked} excludeBookingId={booking.id} />
        </Sheet>
        {confirmMove && picked && (
          <ConfirmSheet
            title="Move this booking?"
            body={`${firstName} gets a WhatsApp about the new time: ${formatDateTime(picked.start_at)}.`}
            confirmLabel="Move it"
            busy={busy}
            onClose={() => setConfirmMove(false)}
            onConfirm={() =>
              void run(() => bookingsApi.move(booking.id, { start_at: picked.start_at, resource_id: picked.resource_id }), "Booking moved")
            }
          />
        )}
      </>
    );
  }

  return (
    <Sheet
      title={`${booking.code} · ${who}`}
      onClose={onClose}
      labelId="booking-title"
      footer={
        <>
          {booking.lead_id && (
            <Link href={`/dashboard/conversations?lead=${encodeURIComponent(booking.lead_id)}`} className={BTN_SECONDARY}>
              <MessageCircle size={15} aria-hidden /> Open chat
            </Link>
          )}
          {canVisit && (
            <>
              {canNoShow && (
                <button type="button" className={BTN_SECONDARY} disabled={busy} onClick={() => setMode("no_show")}>
                  Didn&apos;t come
                </button>
              )}
              <button type="button" className={BTN_PRIMARY} disabled={busy} onClick={() => void came()}>
                Came
              </button>
            </>
          )}
        </>
      }
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn("rounded-full border px-2.5 py-0.5 text-xs font-bold", STATUS_CLASS[booking.status])}>{STATUS_LABEL[booking.status]}</span>
          {flags.map((f) => (
            <span key={f.key} className={cn("rounded-full px-2.5 py-0.5 text-xs font-bold", FLAG_CLASS[f.tone])}>
              {f.label}
            </span>
          ))}
        </div>
        <dl className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-1.5 text-sm">
          <dt className="text-ink-muted">When</dt>
          <dd className="font-semibold text-ink">{formatDateTime(booking.start_at)}</dd>
          <dt className="text-ink-muted">Service</dt>
          <dd className="text-ink">{booking.service_name}</dd>
          {column && (
            <>
              <dt className="text-ink-muted">With</dt>
              <dd className="text-ink">{column}</dd>
            </>
          )}
          <dt className="text-ink-muted">Phone</dt>
          <dd>
            <a href={`tel:${booking.phone}`} className="inline-flex items-center gap-1 font-semibold text-primary-700 hover:underline">
              <Phone size={13} aria-hidden /> {booking.phone}
            </a>
          </dd>
          {booking.note && (
            <>
              <dt className="text-ink-muted">Note</dt>
              <dd className="text-ink">{booking.note}</dd>
            </>
          )}
        </dl>
        {canManage && open && (
          <div className="flex flex-wrap gap-2 border-t border-[#eef2f6] pt-3">
            <button type="button" className={BTN_SECONDARY} onClick={() => setMode("move")}>
              Move
            </button>
            <button type="button" className={BTN_DANGER} onClick={() => setMode("cancel")}>
              Cancel booking
            </button>
          </div>
        )}
        {canSeeMoney && booking.status === "came" && booking.deal_id && (
          <Link href={`/dashboard/deals/orders/${encodeURIComponent(booking.deal_id)}`} className="inline-block text-sm font-semibold text-primary-700 hover:underline">
            Open the order
          </Link>
        )}
      </div>
    </Sheet>
  );
}
