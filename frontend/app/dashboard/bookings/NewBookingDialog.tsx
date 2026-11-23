"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Select } from "@/components/ui/Select";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { bookingsApi, type Booking, type BookingHistory, type BookingSetup } from "@/lib/bookingsApi";
import { historyNote, parsePhone, resourcesForService, rupees } from "./bookingsLogic";
import { formatDateTime, istOf } from "./bookingsTime";
import { SlotPicker, type PickedSlot } from "./SlotPicker";
import { BTN_PRIMARY, BTN_SECONDARY, Field, INPUT_CLS, Notice, Sheet, errorText } from "./bookingsUi";

export interface NewBookingPrefill {
  phone?: string;
  name?: string;
  leadId?: string;
  source?: "phone" | "walk_in" | "chat";
  serviceId?: string;
  /** "any" or a column id. */
  resourceId?: string;
  /** A free gap that was clicked on the Day tab. */
  startAt?: string;
}

/**
 * New booking: service -> column (or anyone free) -> day -> free time. Used by the Bookings page
 * and by "Book a visit" in a chat (prefilled with the customer, source "chat").
 */
export function NewBookingDialog({
  setup,
  prefill,
  canSeeMoney,
  onClose,
  onCreated,
}: {
  setup: BookingSetup;
  prefill?: NewBookingPrefill;
  canSeeMoney: boolean;
  onClose: () => void;
  onCreated: (booking: Booking) => void;
}) {
  const services = useMemo(() => setup.services.filter((s) => s.active), [setup.services]);
  const [phone, setPhone] = useState(prefill?.phone ?? "");
  const [name, setName] = useState(prefill?.name ?? "");
  const [serviceId, setServiceId] = useState(prefill?.serviceId ?? (services.length === 1 ? services[0].id : ""));
  const [resourceId, setResourceId] = useState(prefill?.resourceId ?? "any");
  const [slot, setSlot] = useState<PickedSlot | null>(null);
  // A clicked free gap. Kept across service changes; dropped once the person picks a time themselves.
  const [wantedStart, setWantedStart] = useState<string | null>(prefill?.startAt ?? null);
  const [source, setSource] = useState<"phone" | "walk_in" | "chat">(prefill?.source ?? "phone");
  const [note, setNote] = useState("");
  const [sendAdvance, setSendAdvance] = useState(true);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<BookingHistory | null>(null);

  const service = services.find((s) => s.id === serviceId) ?? null;
  const columns = useMemo(() => (service ? resourcesForService(setup.resources, service.id) : []), [service, setup.resources]);
  const parsed = parsePhone(phone);
  const hasAdvance = service ? (typeof service.advance_paise === "number" ? service.advance_paise > 0 : !canSeeMoney) : false;

  // A column picked earlier may not do the newly picked service.
  useEffect(() => {
    if (resourceId !== "any" && service && !columns.some((c) => c.id === resourceId)) setResourceId("any");
  }, [resourceId, service, columns]);

  // Past didn't-comes: asked for once the phone is a full number.
  useEffect(() => {
    setHistory(null);
    if (!parsed.ok) return;
    let live = true;
    bookingsApi.history(parsed.digits).then((h) => live && setHistory(h)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [parsed.ok, parsed.digits]);

  const pick = useCallback((s: PickedSlot, auto?: boolean) => {
    setSlot(s);
    if (!auto) setWantedStart(null);
  }, []);

  const note2 = historyNote(history);
  const prefillDate = prefill?.startAt ? istOf(prefill.startAt)?.date : undefined;
  const startAt = slot?.start_at ?? null;
  const ready = parsed.ok && service !== null && startAt !== null && !busy;

  async function submit() {
    if (!ready || !service || !startAt) return;
    setBusy(true);
    try {
      const booking = await bookingsApi.create({
        service_id: service.id,
        resource_id: resourceId,
        start_at: startAt,
        phone: parsed.digits,
        customer_name: name.trim() || undefined,
        lead_id: prefill?.leadId,
        source,
        note: note.trim() || undefined,
        send_advance_link: hasAdvance && sendAdvance,
      });
      toast.success(`Booked ${booking.code ?? ""} for ${formatDateTime(booking.start_at)}`.replace("  ", " "));
      // The booking exists, so the sheet closes; the warning says what still needs doing by hand.
      if (booking.advance_error) toast.warning(booking.advance_error, { duration: 10000 });
      onCreated(booking);
    } catch (err) {
      toast.error(errorText(err, "Could not book that time."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet
      title="New booking"
      wide
      onClose={onClose}
      labelId="new-booking-title"
      footer={
        <>
          <button type="button" className={BTN_SECONDARY} onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className={BTN_PRIMARY} onClick={() => void submit()} disabled={!ready}>
            {busy && <Loader2 size={14} className="animate-spin" />} Book it
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Phone" htmlFor="nb-phone" hint={phone && !parsed.ok ? (parsed.error ?? undefined) : "10-digit mobile number"}>
            <input id="nb-phone" inputMode="tel" autoComplete="off" value={phone} onChange={(e) => setPhone(e.target.value)} className={INPUT_CLS} placeholder="98765 43210" />
          </Field>
          <Field label="Name (optional)" htmlFor="nb-name">
            <input id="nb-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} className={INPUT_CLS} />
          </Field>
        </div>
        {note2 && <Notice tone={history && history.no_shows > 0 ? "amber" : "slate"}>{note2}</Notice>}

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Service" htmlFor="nb-service">
            <Select
              id="nb-service"
              value={serviceId}
              onChange={(v) => {
                setServiceId(v);
                setSlot(null);
              }}
              placeholder="Pick a service"
              options={services.map((s) => ({
                value: s.id,
                label: `${s.name} · ${s.duration_min} min${canSeeMoney && typeof s.price_paise === "number" && s.price_paise > 0 ? ` · ${rupees(s.price_paise)}` : ""}`,
                text: s.name,
              }))}
            />
          </Field>
          <Field label="Who" htmlFor="nb-who">
            <Select
              id="nb-who"
              value={resourceId}
              onChange={(v) => {
                setResourceId(v);
                setSlot(null);
              }}
              disabled={!service}
              options={[{ value: "any", label: "Anyone free" }, ...columns.map((c) => ({ value: c.id, label: c.name }))]}
            />
          </Field>
        </div>

        {service ? (
          <SlotPicker
            key={`${service.id}-${resourceId}`}
            serviceId={service.id}
            resourceId={resourceId}
            value={slot}
            initialDate={prefillDate}
            wantedStart={wantedStart}
            onChange={pick}
          />
        ) : (
          <p className="text-sm text-ink-muted">Pick a service to see the free times.</p>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          {prefill?.source !== "chat" && (
            <Field label="How did they book?">
              <SegmentedControl
                aria-label="How did they book"
                value={source === "chat" ? "phone" : source}
                onChange={(v) => setSource(v)}
                options={[
                  { value: "phone", label: "Phone call" },
                  { value: "walk_in", label: "Walked in" },
                ]}
              />
            </Field>
          )}
          <Field label="Note (optional)" htmlFor="nb-note">
            <input id="nb-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} className={INPUT_CLS} />
          </Field>
        </div>

        {hasAdvance && (
          <label className="flex items-start gap-2 text-sm text-ink">
            <input type="checkbox" checked={sendAdvance} onChange={(e) => setSendAdvance(e.target.checked)} className="mt-1 h-4 w-4" />
            <span>
              Send the advance link on WhatsApp
              {service && typeof service.advance_paise === "number" && service.advance_paise > 0 ? ` (${rupees(service.advance_paise)})` : " (if this service has one)"}
            </span>
          </label>
        )}
      </div>
    </Sheet>
  );
}
