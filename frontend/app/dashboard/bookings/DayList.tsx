"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Bot, CalendarPlus, Lightbulb, MessageCircle, Phone, X } from "lucide-react";
import { bookingsApi, type Booking, type BookingResource } from "@/lib/bookingsApi";
import { cn } from "@/lib/utils";
import { FLAG_CLASS, STATUS_CLASS, STATUS_LABEL, bookingFlags, canMarkNoShow, canMarkVisit, customerLabel } from "./bookingsLogic";
import { formatTime } from "./bookingsTime";
import { BTN_PRIMARY, BTN_SECONDARY, errorText } from "./bookingsUi";

type Who = { canManage: boolean; myResourceId: string | null };

const REBOOK_WHY: Record<string, string> = {
  outside_24h_no_template: "they haven't messaged in 24 hours. Call them instead",
  opted_out: "they said stop",
  blocked: "they are blocked",
  whatsapp_not_connected: "WhatsApp isn't connected",
  no_phone: "there's no phone number",
};

/** The four day counts: booked (by AI / staff), came, still to come (confirmed / no reply), didn't come. */
export function dayCounts(bookings: Pick<Booking, "status" | "source" | "confirmed_at">[]) {
  const live = bookings.filter((b) => b.status !== "cancelled");
  const toCome = live.filter((b) => b.status === "booked" || b.status === "held");
  return {
    booked: live.length,
    byAi: live.filter((b) => b.source === "ai").length,
    came: live.filter((b) => b.status === "came").length,
    toCome: toCome.length,
    confirmed: toCome.filter((b) => b.confirmed_at).length,
    noShow: live.filter((b) => b.status === "no_show").length,
  };
}

/** Booked · Came / Paid · Still to come · Didn't come, for the day's own bookings. */
export function DayTiles({ bookings }: { bookings: Booking[] }) {
  const c = dayCounts(bookings);
  const tiles = [
    { label: "Booked", value: c.booked, hint: c.booked ? `${c.byAi} by Anril, ${c.booked - c.byAi} by staff` : "none yet", box: "border-border bg-white", num: "text-ink" },
    { label: "Came / Paid", value: c.came, hint: "marked came", box: "border-[#abefc6] bg-[#f6fef9]", num: "text-[#067647]" },
    { label: "Still to come", value: c.toCome, hint: c.toCome ? `${c.confirmed} confirmed · ${c.toCome - c.confirmed} no reply` : "nobody left", box: "border-[#c7d7fe] bg-[#f5f8ff]", num: "text-[#3538cd]" },
    { label: "Didn't come", value: c.noShow, hint: c.noShow ? "send them a new time" : "everyone turned up", box: "border-border bg-white", num: "text-ink-secondary" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className={cn("rounded-2xl border px-4 py-3", t.box)}>
          <p className="text-xs font-semibold text-ink-secondary">{t.label}</p>
          <p className={cn("text-2xl font-bold tabular-nums", t.num)}>{t.value}</p>
          <p className="text-xs text-ink-muted max-md:hidden">{t.hint}</p>
        </div>
      ))}
    </div>
  );
}

/** No bookings this day: say so, offer the next day, and a tip. */
export function EmptyDay({ onNextDay, canManage, onNew }: { onNextDay: () => void; canManage: boolean; onNew: () => void }) {
  return (
    <div className="rounded-2xl border border-dashed border-border bg-white px-6 py-10 text-center">
      <CalendarPlus size={28} className="mx-auto text-primary" aria-hidden />
      <p className="mt-3 font-display text-base font-bold text-ink">No bookings this day</p>
      <p className="mt-1 text-sm text-ink-secondary">Free all day. Bookings from chats, calls and your booking link show here.</p>
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        <button type="button" className={BTN_SECONDARY} onClick={onNextDay}>See tomorrow ›</button>
        {canManage && <button type="button" className={BTN_PRIMARY} onClick={onNew}>New booking</button>}
      </div>
      <p className="mx-auto mt-5 flex max-w-md items-start justify-center gap-2 text-left text-xs text-ink-muted">
        <Lightbulb size={14} className="mt-0.5 shrink-0 text-amber-500" aria-hidden />
        Tip: share your booking link in your WhatsApp status and Instagram bio. People pick a free time themselves.
      </p>
    </div>
  );
}

/** After Didn't come: send a new time on WhatsApp, call, or leave it. */
function NoShowChooser({ booking, onDone }: { booking: Booking; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  async function rebook() {
    setBusy(true);
    try {
      const res = await bookingsApi.rebookMessage(booking.id);
      if (res.sent) toast.success(`Rebook message sent to ${customerLabel(booking).split(/\s+/)[0]}`);
      else toast.warning(`Not sent: ${REBOOK_WHY[res.reason] ?? "WhatsApp didn't take it"}.`);
      onDone();
    } catch (err) {
      toast.error(errorText(err));
      setBusy(false);
    }
  }
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <span className="text-xs font-semibold text-ink-secondary">Didn&apos;t come, what next?</span>
      <button type="button" disabled={busy} onClick={() => void rebook()} className={cn(BTN_PRIMARY, "min-h-8 px-3 py-1 text-xs")}>
        <MessageCircle size={13} aria-hidden /> Send a new time
      </button>
      <a href={`tel:${booking.phone}`} className={cn(BTN_SECONDARY, "min-h-8 px-3 py-1 text-xs")}>
        <Phone size={13} aria-hidden /> Call
      </a>
      <button type="button" onClick={onDone} className="rounded-lg p-1.5 text-ink-muted hover:bg-slate-100" aria-label="Leave it">
        <X size={14} />
      </button>
    </div>
  );
}

/**
 * The day as a list (time, customer, staff, status) with one-tap Came / Paid and Didn't come.
 * A red line marks "now" on today.
 */
export function DayList({
  bookings,
  resources,
  who,
  isToday,
  canSeeMoney,
  onOpen,
  onChanged,
}: {
  bookings: Booking[];
  resources: BookingResource[];
  who: Who;
  isToday: boolean;
  canSeeMoney: boolean;
  onOpen: (b: Booking) => void;
  onChanged: () => void;
}) {
  const router = useRouter();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  const [now] = useState(() => Date.now());
  const rows = bookings.filter((b) => b.status !== "cancelled");
  const nowIndex = isToday ? rows.findIndex((b) => Date.parse(b.start_at) > now) : -1;

  async function came(b: Booking) {
    setBusyId(b.id);
    try {
      const res = await bookingsApi.came(b.id);
      onChanged();
      if (res.order_error) toast.warning(res.order_error, { duration: 10000 });
      else if (canSeeMoney && res.href && res.href.startsWith("/dashboard/")) {
        const href = res.href;
        toast.success("Marked as came", { action: { label: "Open order", onClick: () => router.push(href) } });
      } else toast.success("Marked as came");
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusyId(null);
    }
  }

  async function noShow(b: Booking) {
    setBusyId(b.id);
    try {
      await bookingsApi.noShow(b.id);
      onChanged();
      setAsking(b.id);
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-white shadow-card">
      <ul className="divide-y divide-border-subtle">
        {rows.map((b, i) => {
          const col = resources.find((r) => r.id === b.resource_id)?.name;
          const open = b.status === "booked" || b.status === "held";
          return (
            <li key={b.id}>
              {i === nowIndex && (
                <div className="flex items-center gap-2 px-4 py-1">
                  <span className="text-[11px] font-bold text-red-600">NOW {formatTime(new Date(now).toISOString())}</span>
                  <span className="h-px flex-1 bg-red-400" aria-hidden />
                </div>
              )}
              <div className={cn(
                "grid grid-cols-[4.5rem_minmax(0,1fr)] items-center gap-x-3 gap-y-2 px-4 py-2.5 lg:grid-cols-[4.5rem_minmax(0,1.4fr)_minmax(0,0.7fr)_minmax(0,1.3fr)_17rem]",
                b.call_now && "bg-[#fffaeb]",
              )}>
                <span className="font-display text-sm font-bold tabular-nums text-ink">{formatTime(b.start_at)}</span>
                <button type="button" onClick={() => onOpen(b)} className="min-w-0 truncate text-left text-sm hover:text-primary">
                  <span className="font-bold text-ink">{customerLabel(b)}</span>
                  <span className="text-ink-secondary"> · {b.service_name}</span>
                </button>
                <span className="hidden truncate text-sm text-ink-secondary lg:block">{col ?? ""}</span>
                <span className="col-span-2 flex flex-wrap items-center gap-1.5 lg:col-span-1">
                  <span className={cn("rounded-full border px-2 py-0.5 text-xs font-bold", STATUS_CLASS[b.status])}>{STATUS_LABEL[b.status]}</span>
                  {b.source === "ai" && open && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-[#eef4ff] px-2 py-0.5 text-xs font-bold text-[#3538cd]">
                      <Bot size={12} aria-hidden /> Booked by AI agent
                    </span>
                  )}
                  {bookingFlags(b).map((f) => (
                    <span key={f.key} className={cn("rounded-full px-2 py-0.5 text-xs font-bold", FLAG_CLASS[f.tone])}>{f.label}</span>
                  ))}
                </span>
                <span className="col-span-2 flex justify-end gap-2 lg:col-span-1">
                  {asking === b.id ? (
                    <NoShowChooser booking={b} onDone={() => setAsking(null)} />
                  ) : open && canMarkVisit(b, who) ? (
                    <>
                      <button type="button" disabled={busyId === b.id} onClick={() => void came(b)} className={cn(BTN_SECONDARY, "min-h-8 px-3 py-1 text-xs")}>
                        ✓ Came / Paid
                      </button>
                      {canMarkNoShow(b, who) && (
                        <button type="button" disabled={busyId === b.id} onClick={() => void noShow(b)} className={cn(BTN_SECONDARY, "min-h-8 px-3 py-1 text-xs text-ink-secondary")}>
                          Didn&apos;t come
                        </button>
                      )}
                    </>
                  ) : b.status === "no_show" && (who.canManage || (who.myResourceId !== null && who.myResourceId === b.resource_id)) ? (
                    <button type="button" onClick={() => setAsking(b.id)} className="text-xs font-bold text-primary hover:underline">
                      Send a new time ›
                    </button>
                  ) : null}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
