"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { CalendarPlus, Check, Loader2, MessageCircle } from "lucide-react";
import {
  PublicBookingError,
  cancelBooking,
  fetchBookingInfo,
  fetchBookingStatus,
  fetchFreeDays,
  fetchFreeTimes,
  moveBooking,
  type PublicBookingInfo,
  type PublicBookingStatus,
  type PublicSlot,
} from "@/lib/publicBookingApi";
import {
  buildDayGrid,
  POLL_MS,
  buildIcs,
  cutoffText,
  errorMessage,
  errorText,
  formatCountdown,
  formatTime,
  formatWhen,
  groupTimes,
  heldSteps,
  isLive,
  nextPollDelay,
  rupees,
  safePaymentUrl,
  safeWhatsappUrl,
  secondsLeft,
  statusLabel,
  type PollOutcome,
} from "@/lib/publicBookingLogic";
import { BookLoading, BookMessage, BookShell, ErrorNote, StepHeading, primaryBtn, secondaryBtn } from "../../BookShell";

// The customer's booking status page: opened right after booking, or later from a link.
// A new booking is "held" until the customer sends the code on WhatsApp (this confirms the
// number) and pays the advance, if one is due. While held, the page checks every 10 seconds
// (30 after a 429, and not at all while the tab is hidden) and flips to "Booked!" on its own.

interface Stash {
  hold_until?: string | null;
  service_id?: string;
  resource_id?: string;
}

function readStash(id: string): Stash {
  try {
    const raw = sessionStorage.getItem(`anril-booking:${id}`);
    return raw ? (JSON.parse(raw) as Stash) : {};
  } catch {
    return {};
  }
}

export default function BookingStatusPage() {
  const { token, id } = useParams<{ token: string; id: string }>();
  const [booking, setBooking] = useState<PublicBookingStatus | null | undefined>(undefined);
  const [info, setInfo] = useState<PublicBookingInfo | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [stash, setStash] = useState<Stash>({});
  const [now, setNow] = useState(() => Date.now());
  const [mode, setMode] = useState<"view" | "cancel" | "change">("view");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [cancelledHere, setCancelledHere] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  const load = useCallback(async (): Promise<PollOutcome> => {
    try {
      setBooking(await fetchBookingStatus(token, id));
      setLoadFailed(false);
      return "ok";
    } catch (e) {
      if (e instanceof PublicBookingError && e.status === 404) {
        setBooking(null);
        return "error";
      }
      setLoadFailed(true);
      return e instanceof PublicBookingError && e.status === 429 ? "rate_limited" : "error";
    }
  }, [token, id]);

  useEffect(() => {
    setStash(readStash(id));
    void load();
    fetchBookingInfo(token).then(setInfo).catch(() => setInfo(null));
  }, [token, id, load]);

  const status = booking?.status;
  const held = status === "held";

  // Poll while held: 10 s, 30 s after a 429, paused while the tab is hidden.
  useEffect(() => {
    if (!held) return;
    let delay = POLL_MS;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = () => {
      if (stopped || document.hidden) return;
      clearTimeout(timer);
      timer = setTimeout(tick, delay);
    };
    const tick = async () => {
      if (stopped || document.hidden) return;
      delay = nextPollDelay(delay, await load());
      schedule();
    };
    const onVisible = () => {
      if (document.hidden) clearTimeout(timer);
      else void tick();
    };
    document.addEventListener("visibilitychange", onVisible);
    schedule();
    return () => {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [held, load]);

  // Tick the countdown.
  const holdUntil = booking?.hold_until ?? stash.hold_until ?? null;
  useEffect(() => {
    if (!held || !holdUntil) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [held, holdUntil]);

  useEffect(() => {
    if (info && booking) document.title = `${booking.code} · ${info.business_name}`;
  }, [info, booking]);

  // The booking's service and column, so "Change time" can ask for free times.
  const service = useMemo(() => {
    if (!booking || !info) return undefined;
    const sid = booking.service_id ?? stash.service_id;
    return info.services.find((s) => s.id === sid) ?? info.services.find((s) => s.name === booking.service_name);
  }, [booking, info, stash.service_id]);
  const resourceId = useMemo(() => {
    if (!booking) return undefined;
    if (booking.resource_id) return booking.resource_id;
    const byName = info?.resources.find(
      (r) => r.name === booking.resource_name && (!service || r.service_ids.includes(service.id)),
    );
    return byName?.id ?? stash.resource_id;
  }, [booking, info, service, stash.resource_id]);

  const durationMin = booking?.duration_min ?? service?.duration_min;

  function downloadIcs() {
    if (!booking || !durationMin) return;
    const ics = buildIcs({
      code: booking.code,
      businessName: info?.business_name ?? "Booking",
      serviceName: booking.service_name,
      resourceName: booking.resource_name,
      startAt: booking.start_at,
      durationMin,
    });
    const url = URL.createObjectURL(new Blob([ics], { type: "text/calendar;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${booking.code}.ics`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function doCancel() {
    if (busy) return;
    setBusy(true);
    setActionError("");
    try {
      await cancelBooking(token, id);
      setCancelledHere(true);
      setMode("view");
      await load();
    } catch (e) {
      setActionError(e instanceof PublicBookingError ? errorText(e.status, e.detail) : errorMessage("other"));
    } finally {
      setBusy(false);
    }
  }

  async function doMove(slot: PublicSlot) {
    if (busy) return false;
    setBusy(true);
    setActionError("");
    try {
      await moveBooking(token, id, { start_at: slot.start_at, resource_id: slot.resource_id });
      setMode("view");
      await load();
      return true;
    } catch (e) {
      setActionError(e instanceof PublicBookingError ? errorText(e.status, e.detail) : errorMessage("other"));
      return false;
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (mode !== "view") headingRef.current?.focus();
  }, [mode]);

  if (booking === undefined && !loadFailed) return <BookShell><BookLoading /></BookShell>;
  if (loadFailed && !booking) {
    return (
      <BookShell>
        <BookMessage action={<button type="button" onClick={() => void load()} className={secondaryBtn}>Try again</button>}>
          This page couldn&apos;t be loaded. Check your internet and try again.
        </BookMessage>
      </BookShell>
    );
  }
  if (booking === null || !booking) {
    return (
      <BookShell>
        <BookMessage>We couldn&apos;t find this booking. Ask the business to send the link again.</BookMessage>
      </BookShell>
    );
  }

  const live = isLive(booking.status);
  const left = held ? secondsLeft(holdUntil, now) : null;
  const cutoff = cutoffText(info?.rules.cancel_cutoff_min ?? 180);
  const steps = heldSteps(booking);
  const expired = held && left === 0 && !steps.confirming;
  const releasedUnconfirmed = booking.status === "cancelled" && !cancelledHere && booking.phone_checked !== true;
  const waUrl = safeWhatsappUrl(booking.whatsapp_url);
  const payUrl = safePaymentUrl(booking.payment_url);
  const businessPhone = booking.business_phone ?? info?.business_phone ?? null;
  const tone =
    booking.status === "booked" || booking.status === "came"
      ? "border-emerald-200 bg-emerald-50 text-emerald-900"
      : held
        ? "border-amber-200 bg-amber-50 text-amber-900"
        : "border-slate-200 bg-slate-100 text-slate-700";

  return (
    <BookShell>
      <header className="mb-4">
        <h1 className="text-xl font-bold text-slate-900">{info?.business_name ?? "Your booking"}</h1>
        <p className="text-sm text-slate-500">Your booking</p>
      </header>

      <section aria-label="Booking details" className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <p className={`inline-block rounded-full border px-3 py-1 text-xs font-bold ${tone}`} role="status">
          {statusLabel(booking.status)}
        </p>
        <p className="mt-3 text-2xl font-bold tracking-wide text-slate-900">{booking.code}</p>
        <dl className="mt-3 space-y-1.5 text-sm">
          <Row label="What" value={booking.service_name} />
          <Row label="When" value={formatWhen(booking.start_at)} />
          <Row label="With" value={booking.resource_name} />
          {booking.advance_paise > 0 && (
            <Row label="Advance" value={`${rupees(booking.advance_paise)}${booking.advance_paid ? " paid" : " due"}`} />
          )}
        </dl>
      </section>

      {held && expired && (
        <section className="mt-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" role="alert">
          <p className="text-sm text-slate-700">This time was released because the number wasn&apos;t confirmed. Book again.</p>
          <a href={`/book/${encodeURIComponent(token)}`} className={`${primaryBtn} mt-3`}>Book again</a>
        </section>
      )}

      {held && !expired && (
        <section className="mt-3 space-y-3" aria-label="Keep your time">
          {left !== null && left > 0 && (
            <p className="text-sm text-slate-700">
              We keep this time for you for{" "}
              <span className="font-bold tabular-nums text-slate-900" role="timer" aria-live="off">{formatCountdown(left)}</span>
            </p>
          )}

          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-amber-800">Step 1</p>
            {steps.numberConfirmed ? (
              <p className="mt-1 flex items-center gap-1.5 text-base font-bold text-emerald-800">
                <Check size={18} aria-hidden="true" /> Number confirmed ✓
              </p>
            ) : (
              <>
                <p className="mt-1 text-base font-bold text-amber-950">Confirm on WhatsApp</p>
                <p className="mt-1 text-sm text-amber-900">
                  Tap to send your booking code on WhatsApp — this confirms your number. We keep the time for 15 minutes.
                </p>
                {waUrl ? (
                  <a href={waUrl} className={`${primaryBtn} mt-3`} target="_blank" rel="noopener noreferrer">
                    <MessageCircle size={20} /> Confirm on WhatsApp
                  </a>
                ) : (
                  <p className="mt-2 text-sm text-amber-900">The WhatsApp link isn&apos;t ready yet. Please <CallBusiness phone={businessPhone} />.</p>
                )}
              </>
            )}
          </div>

          {steps.needsAdvance && (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
              <p className="text-xs font-bold uppercase tracking-wider text-amber-800">Step 2</p>
              {steps.advancePaid ? (
                <p className="mt-1 flex items-center gap-1.5 text-base font-bold text-emerald-800">
                  <Check size={18} aria-hidden="true" /> Advance paid ✓
                </p>
              ) : payUrl ? (
                <>
                  <p className="mt-1 text-sm text-amber-900">Pay the advance to keep this time.</p>
                  <a href={payUrl} className={`${primaryBtn} mt-3`}>Pay {rupees(booking.advance_paise)} advance</a>
                </>
              ) : (
                <p className="mt-1 text-sm text-amber-900">
                  Pay {rupees(booking.advance_paise)} advance to keep this time. The payment link isn&apos;t ready yet, please <CallBusiness phone={businessPhone} />.
                </p>
              )}
            </div>
          )}

          {steps.confirming && (
            <p className="flex items-center gap-2 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm font-semibold text-emerald-900" role="status">
              <Loader2 size={16} className="animate-spin" /> All done. Confirming your booking…
            </p>
          )}
        </section>
      )}

      {booking.status === "booked" && (
        <div className="mt-3 space-y-2">
          <p className="flex items-center gap-1.5 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-bold text-emerald-900">
            <Check size={18} aria-hidden="true" /> Your booking is confirmed.
          </p>
          {durationMin ? (
            <button type="button" onClick={downloadIcs} className={secondaryBtn}>
              <CalendarPlus size={18} /> Add to calendar
            </button>
          ) : null}
          {waUrl && (
            <a href={waUrl} className={secondaryBtn} target="_blank" rel="noopener noreferrer">
              <MessageCircle size={18} /> Open WhatsApp chat
            </a>
          )}
        </div>
      )}

      {booking.status === "cancelled" && releasedUnconfirmed && (
        <section className="mt-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" role="alert">
          <p className="text-sm text-slate-700">This time was released because the number wasn&apos;t confirmed. Book again.</p>
          <a href={`/book/${encodeURIComponent(token)}`} className={`${primaryBtn} mt-3`}>Book again</a>
        </section>
      )}
      {booking.status === "cancelled" && !releasedUnconfirmed && (
        <BookMessage>This booking was cancelled. You can book a new time any time from the booking link.</BookMessage>
      )}

      {actionError && mode === "view" && <ErrorNote>{actionError}</ErrorNote>}

      {live && mode === "view" && (
        <section className="mt-4" aria-label="Change or cancel">
          {booking.can_change ? (
            <div className="grid grid-cols-2 gap-2">
              <button type="button" onClick={() => { setActionError(""); setMode("change"); }} className={secondaryBtn} disabled={!service || !resourceId}>
                Change time
              </button>
              <button type="button" onClick={() => { setActionError(""); setMode("cancel"); }} className={secondaryBtn}>
                Cancel booking
              </button>
            </div>
          ) : (
            <p className="rounded-xl bg-slate-100 px-3 py-3 text-sm text-slate-700">
              This booking is less than {cutoff} away. To change or cancel it, please <CallBusiness phone={businessPhone} />.
            </p>
          )}
          {booking.can_change && (!service || !resourceId) && (
            <p className="mt-2 text-xs text-slate-500">To change the time, please call the business.</p>
          )}
        </section>
      )}

      {mode === "cancel" && (
        <section className="mt-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Cancel booking">
          <StepHeading ref={headingRef}>Cancel this booking?</StepHeading>
          <p className="mt-1 text-sm text-slate-600">{booking.service_name}, {formatWhen(booking.start_at)}</p>
          {actionError && <ErrorNote>{actionError}</ErrorNote>}
          <div className="mt-3 grid grid-cols-2 gap-2">
            <button type="button" onClick={() => setMode("view")} disabled={busy} className={secondaryBtn}>Keep it</button>
            <button
              type="button"
              onClick={doCancel}
              disabled={busy}
              className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-xl bg-rose-600 px-4 py-2.5 text-sm font-bold text-white hover:bg-rose-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-700 disabled:opacity-60"
            >
              {busy && <Loader2 size={16} className="animate-spin" />} Yes, cancel
            </button>
          </div>
        </section>
      )}

      {mode === "change" && service && resourceId && (
        <ChangeTime
          token={token}
          serviceId={service.id}
          resourceId={resourceId}
          daysAhead={info?.rules.days_ahead ?? 14}
          headingRef={headingRef}
          busy={busy}
          error={actionError}
          onClose={() => setMode("view")}
          onPick={doMove}
        />
      )}
    </BookShell>
  );
}

function CallBusiness({ phone }: { phone: string | null }) {
  if (phone && /^[+\d\s()-]{6,20}$/.test(phone)) {
    return (
      <a href={`tel:${phone.replace(/[\s()-]/g, "")}`} className="font-semibold underline underline-offset-2">
        call the business on {phone}
      </a>
    );
  }
  return <>call the business</>;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right font-semibold text-slate-900">{value}</dd>
    </div>
  );
}

function ChangeTime({
  token,
  serviceId,
  resourceId,
  daysAhead,
  headingRef,
  busy,
  error,
  onClose,
  onPick,
}: {
  token: string;
  serviceId: string;
  resourceId: string;
  daysAhead: number;
  headingRef: React.RefObject<HTMLHeadingElement>;
  busy: boolean;
  error: string;
  onClose: () => void;
  onPick: (slot: PublicSlot) => Promise<boolean | undefined>;
}) {
  const [days, setDays] = useState<string[] | null>(null);
  const [date, setDate] = useState<string | null>(null);
  const [times, setTimes] = useState<PublicSlot[] | null>(null);
  const [picked, setPicked] = useState<PublicSlot | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [now] = useState(() => Date.now());

  useEffect(() => {
    let live = true;
    fetchFreeDays(token, serviceId, resourceId)
      .then((d) => live && setDays(d))
      .catch(() => live && setLoadError(errorMessage("other")))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [token, serviceId, resourceId]);

  async function chooseDay(d: string) {
    setDate(d);
    setPicked(null);
    setTimes(null);
    setLoading(true);
    setLoadError("");
    try {
      setTimes(await fetchFreeTimes(token, serviceId, resourceId, d));
    } catch {
      setLoadError(errorMessage("other"));
    } finally {
      setLoading(false);
    }
  }

  const grid = buildDayGrid(now, daysAhead, days ?? []);
  const groups = groupTimes(times ?? [], false);

  return (
    <section className="mt-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" aria-label="Change time">
      <StepHeading ref={headingRef}>{date ? "Pick a new time" : "Pick a new day"}</StepHeading>
      {loadError && <ErrorNote>{loadError}</ErrorNote>}
      {loading && <div role="status" aria-label="Loading" className="flex justify-center py-8"><Loader2 className="animate-spin text-slate-400" /></div>}

      {!loading && !date && days && !grid.some((c) => c.enabled) && (
        <p className="mt-3 text-sm text-slate-600">No free days right now. Please call the business.</p>
      )}
      {!loading && !date && days && grid.some((c) => c.enabled) && (
        <ul className="mt-3 grid grid-cols-3 gap-2 min-[400px]:grid-cols-4">
          {grid.map((c) => (
            <li key={c.date}>
              <button
                type="button"
                disabled={!c.enabled}
                onClick={() => void chooseDay(c.date)}
                aria-label={`${c.weekday} ${c.day} ${c.month}${c.enabled ? "" : ", full"}`}
                className="flex min-h-[64px] w-full flex-col items-center justify-center rounded-xl border border-slate-200 bg-white px-1 py-2 hover:border-emerald-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700 disabled:cursor-not-allowed disabled:border-slate-100 disabled:bg-slate-50 disabled:text-slate-300"
              >
                <span className="text-xs font-semibold">{c.isToday ? "Today" : c.weekday}</span>
                <span className="text-lg font-bold leading-6">{c.day}</span>
                <span className="text-xs">{c.month}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {!loading && date && times && groups.length === 0 && (
        <p className="mt-3 text-sm text-slate-600">No free times left that day. Please pick another day.</p>
      )}
      {!loading && date && groups.length > 0 && !picked && (
        <div className="mt-3 space-y-4">
          {groups.map((g) => (
            <section key={g.part} aria-label={g.part}>
              <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">{g.part}</h3>
              <ul className="grid grid-cols-3 gap-2">
                {g.slots.map((s) => (
                  <li key={s.start_at}>
                    <button
                      type="button"
                      onClick={() => setPicked(s)}
                      className="min-h-[48px] w-full rounded-xl border border-slate-200 bg-white px-1 py-2 text-sm font-bold text-slate-900 hover:border-emerald-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700"
                    >
                      {formatTime(s.start_at)}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}

      {picked && (
        <div className="mt-3">
          <p className="text-sm text-slate-700">Move your booking to <strong>{formatWhen(picked.start_at)}</strong>?</p>
          {error && <ErrorNote>{error}</ErrorNote>}
          <div className="mt-3 grid grid-cols-2 gap-2">
            <button type="button" onClick={() => setPicked(null)} disabled={busy} className={secondaryBtn}>Back</button>
            <button type="button" onClick={() => void onPick(picked)} disabled={busy} className={primaryBtn}>
              {busy && <Loader2 size={16} className="animate-spin" />} Yes, move it
            </button>
          </div>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-4">
        {date && !picked && (
          <button type="button" onClick={() => { setDate(null); setTimes(null); }} className="text-sm font-semibold text-emerald-700 underline underline-offset-2">
            Pick another day
          </button>
        )}
        <button type="button" onClick={onClose} className="text-sm font-semibold text-slate-600 underline underline-offset-2">
          Keep my current time
        </button>
      </div>
    </section>
  );
}
