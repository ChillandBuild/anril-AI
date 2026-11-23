"use client";
import { useEffect, useState } from "react";
import { CalendarCheck, X } from "lucide-react";
import { api, type WrapupBookingOptions, type WrapupBookingTime } from "@/lib/api";
import { formatIstWhen } from "@/lib/call-wrapup";
import { setBooking, type WrapupDraft } from "../../lib/wrapup-draft";

const CHIP = "px-3 py-1.5 rounded-full border font-label text-[11px] font-bold transition-all";
const ON = "bg-primary border-primary text-white shadow-sm";
const OFF = "bg-white border-[#e2e8f0] text-[#334155] hover:border-primary-muted hover:text-primary";
const DAY_CHIPS = 7;

function dayLabel(iso: string): string {
  return new Date(`${iso}T00:00:00+05:30`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
}

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: "Asia/Kolkata" });
}

/** "Interested, next step booked": book the visit now. Shows nothing if the business has no Bookings set up. */
export default function BookVisit({ draft, onChange }: { draft: WrapupDraft; onChange: (d: WrapupDraft) => void }) {
  const [options, setOptions] = useState<WrapupBookingOptions | null>(null);
  const [serviceId, setServiceId] = useState<string | null>(null);
  const [days, setDays] = useState<string[]>([]);
  const [day, setDay] = useState<string | null>(null);
  const [times, setTimes] = useState<WrapupBookingTime[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let live = true;
    api.calls.wrapupBooking().then((o) => live && setOptions(o)).catch(() => live && setOptions({ enabled: false, services: [] }));
    return () => { live = false; };
  }, []);

  function pickService(id: string) {
    setServiceId(id);
    setDay(null);
    setTimes([]);
    setError(null);
    setLoading(true);
    api.calls.wrapupBookingDays(id)
      .then((r) => setDays(r.dates.slice(0, DAY_CHIPS)))
      .catch((e: unknown) => { setDays([]); setError(e instanceof Error ? e.message : "Couldn't load the free days."); })
      .finally(() => setLoading(false));
  }

  function pickDay(value: string) {
    if (!serviceId) return;
    setDay(value);
    setTimes([]);
    setError(null);
    setLoading(true);
    api.calls.wrapupBookingTimes(serviceId, value)
      .then((r) => setTimes(r.times))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Couldn't load the free times."))
      .finally(() => setLoading(false));
  }

  if (!options?.enabled) return null;

  if (draft.booking) {
    return (
      <section className="flex items-center justify-between gap-2 rounded-2xl border border-emerald-200 bg-emerald-50/60 p-3">
        <p className="flex items-center gap-2 font-label text-xs font-bold text-emerald-800">
          <CalendarCheck size={14} /> Visit to book: {draft.booking.label}
        </p>
        <button type="button" onClick={() => onChange(setBooking(draft, null))} className="rounded-full p-1 text-emerald-700 hover:bg-emerald-100" aria-label="Don't book this visit">
          <X size={14} />
        </button>
      </section>
    );
  }

  const service = options.services.find((s) => s.id === serviceId);
  return (
    <section className="space-y-2 rounded-2xl border border-[#e2e8f0] bg-[#f8fafc] p-3">
      <p className="font-label text-[10px] font-extrabold uppercase tracking-wider text-[#94a3b8]">Book the visit now (optional)</p>
      <div className="flex flex-wrap gap-1.5">
        {options.services.map((s) => (
          <button key={s.id} type="button" onClick={() => pickService(s.id)} className={`${CHIP} ${serviceId === s.id ? ON : OFF}`}>{s.name}</button>
        ))}
      </div>
      {serviceId && days.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {days.map((d) => (
            <button key={d} type="button" onClick={() => pickDay(d)} className={`${CHIP} ${day === d ? ON : OFF}`}>{dayLabel(d)}</button>
          ))}
        </div>
      )}
      {day && times.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {times.map((t) => (
            <button
              key={`${t.start_at}-${t.resource_id}`}
              type="button"
              onClick={() => onChange(setBooking(draft, {
                serviceId: serviceId as string, startAt: t.start_at,
                label: `${service?.name ?? "Visit"}, ${formatIstWhen(new Date(t.start_at), new Date())}`,
              }))}
              className={`${CHIP} ${OFF}`}
            >
              {clock(t.start_at)}
            </button>
          ))}
        </div>
      )}
      {loading && <p className="font-label text-[10px] text-[#94a3b8]">Loading…</p>}
      {serviceId && !loading && !error && days.length === 0 && <p className="font-label text-[10px] text-[#94a3b8]">No free days for this service.</p>}
      {day && !loading && !error && times.length === 0 && <p className="font-label text-[10px] text-[#94a3b8]">No free times that day.</p>}
      {error && <p className="font-label text-[10px] text-red-600">{error}</p>}
    </section>
  );
}
